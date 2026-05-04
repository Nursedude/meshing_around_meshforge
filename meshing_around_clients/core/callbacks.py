"""Shared callback registration, dispatch, and alert cooldown logic.

Extracted from MeshtasticAPI and MQTTMeshtasticClient which both
implemented identical copies of these patterns.

Also provides shared input validation helpers (safe_float, safe_int)
and shared data extraction (extract_position) used by both API classes
to validate data from mesh network packets.
"""

import logging
import logging.handlers
import math
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CALLBACK_EVENTS = (
    "on_connect",
    "on_disconnect",
    "on_message",
    "on_node_update",
    "on_alert",
    "on_position",
    "on_telemetry",
    "on_command",
)
# Lifecycle events fire at most a few times per session; dispatch them
# synchronously so callers (and tests) can rely on "after connect()
# returns, the on_connect callback has already run."  Only the high-
# frequency message-path events go through the worker queue.
_SYNCHRONOUS_EVENTS = frozenset({"on_connect", "on_disconnect"})
_DEFAULT_COOLDOWN_SECONDS = 300
_MAX_COOLDOWN_ENTRIES = 1000

# Async callback dispatch — paho's network thread enqueues here so it
# never blocks on TUI rendering or file I/O.  The worker is opt-in via
# ``_start_callback_worker()``; until then ``_trigger_callbacks`` stays
# synchronous (tests and shutdown paths rely on this).
_CALLBACK_QUEUE_MAX = 500
_DROP_LOG_INTERVAL_SEC = 1.0
_WORKER_POLL_TIMEOUT_SEC = 0.5

# Alert log rotation — matches the RotatingFileHandler shape used for
# mesh_client.log so operators see a familiar pattern on disk.
_ALERT_LOG_MAX_BYTES = 10 * 1024 * 1024
_ALERT_LOG_BACKUPS = 3
# Cap on alert.message bytes when written to the log line.  Prevents a
# single malformed/oversized alert from burning the rotation budget.
_ALERT_LOG_MESSAGE_CAP = 1024


def safe_float(value: Any, min_val: float, max_val: float) -> Optional[float]:
    """Safely extract and validate a float value within range.

    Rejects None, NaN, Inf, and values outside [min_val, max_val].
    Used by both MeshtasticAPI and MQTTMeshtasticClient to validate
    incoming position/telemetry data from mesh network packets.
    """
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        if min_val <= f <= max_val:
            return f
    except (TypeError, ValueError):
        pass
    return None


def safe_int(value: Any, min_val: int, max_val: int) -> Optional[int]:
    """Safely extract and validate an int value within range.

    Rejects None and values outside [min_val, max_val].
    Used by both MeshtasticAPI and MQTTMeshtasticClient to validate
    incoming telemetry data from mesh network packets.
    """
    if value is None:
        return None
    try:
        i = int(value)
        if min_val <= i <= max_val:
            return i
    except (TypeError, ValueError):
        pass
    return None


def extract_position(pos_data: dict) -> Optional[Any]:
    """Extract and validate a Position from a dict with latitude/latitudeI keys.

    Shared by MeshtasticAPI and MQTTMeshtasticClient to avoid duplicating
    the latitude/longitude parsing and validation logic.

    Returns a Position object if both coordinates are valid, else None.
    """
    from meshing_around_clients.core.models import VALID_LAT_RANGE, VALID_LON_RANGE, Position

    lat = safe_float(pos_data.get("latitude"), *VALID_LAT_RANGE)
    if lat is None:
        lat_i = pos_data.get("latitudeI", 0)
        lat = lat_i / 1e7 if lat_i else None
        if lat is not None:
            lat = safe_float(lat, *VALID_LAT_RANGE)

    lon = safe_float(pos_data.get("longitude"), *VALID_LON_RANGE)
    if lon is None:
        lon_i = pos_data.get("longitudeI", 0)
        lon = lon_i / 1e7 if lon_i else None
        if lon is not None:
            lon = safe_float(lon, *VALID_LON_RANGE)

    if lat is not None and lon is not None:
        return Position(
            latitude=lat,
            longitude=lon,
            altitude=pos_data.get("altitude", 0),
            time=datetime.now(timezone.utc),
        )
    return None


def play_alert_sound(sound_file: str) -> bool:
    """Play an alert sound file. Returns True if playback was attempted.

    Uses platform-available CLI tools (paplay, aplay, afplay).
    No additional dependencies required — stdlib only.
    """
    import shutil
    import subprocess

    if not os.path.isfile(sound_file):
        logger.warning("Sound file not found: %s", sound_file)
        return False

    for player in ("paplay", "aplay", "afplay"):
        if shutil.which(player):
            try:
                subprocess.Popen(
                    [player, sound_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except OSError as e:
                logger.debug("Sound player %s failed: %s", player, e)

    logger.debug("No sound player available")
    return False


class CallbackMixin:
    """Mixin providing event callback registration, dispatch, and alert cooldown.

    Classes using this mixin must call ``_init_callbacks()`` in their ``__init__``.
    """

    def _init_callbacks(self) -> None:
        self._callbacks: Dict[str, List[Callable]] = {e: [] for e in _CALLBACK_EVENTS}
        self._alert_cooldowns: Dict[str, float] = {}
        self._alert_cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS
        self._cooldown_lock = threading.Lock()

        # Async dispatch state.  Worker is started by the connecting class
        # (MQTTMeshtasticClient.connect / MeshtasticAPI.connect).  Until
        # then _trigger_callbacks dispatches synchronously, so unit tests
        # and lifecycle paths see the existing behavior.
        self._cb_queue: "queue.Queue[Optional[Tuple[str, tuple, dict]]]" = queue.Queue(maxsize=_CALLBACK_QUEUE_MAX)
        self._cb_drops: int = 0
        self._cb_drops_lock = threading.Lock()
        self._cb_last_drop_log: float = 0.0
        self._cb_worker: Optional[threading.Thread] = None
        self._cb_worker_running = threading.Event()

        # Cached alert log handler (lazy-created on first write).
        self._alert_log_handler: Optional[logging.handlers.RotatingFileHandler] = None
        self._alert_log_path: Optional[str] = None
        self._alert_log_lock = threading.Lock()

    def _start_callback_worker(self) -> None:
        """Switch _trigger_callbacks from sync to async dispatch.

        Idempotent.  Spawns a daemon worker that drains _cb_queue in FIFO
        order so paho's network thread can return immediately after
        enqueue.
        """
        if self._cb_worker is not None and self._cb_worker.is_alive():
            return
        self._cb_worker_running.set()
        self._cb_worker = threading.Thread(
            target=self._callback_worker_loop,
            name="callback-dispatch",
            daemon=True,
        )
        self._cb_worker.start()

    def _stop_callback_worker(self, timeout: float = 2.0) -> None:
        """Drain pending callbacks and stop the worker thread.

        Posts a sentinel so any events queued *before* shutdown still run,
        preserving on_disconnect ordering.  Safe to call when no worker
        is running.
        """
        if self._cb_worker is None:
            return
        self._cb_worker_running.clear()
        try:
            self._cb_queue.put(None, timeout=0.1)
        except queue.Full:
            pass
        try:
            self._cb_worker.join(timeout=timeout)
        except RuntimeError:
            pass
        self._cb_worker = None
        self._close_alert_log_handler()

    def _close_alert_log_handler(self) -> None:
        """Flush + close the cached alert log handler, if any.

        Called from ``_stop_callback_worker`` so an orderly disconnect()
        guarantees buffered alert writes hit disk.  Idempotent.
        """
        with self._alert_log_lock:
            if self._alert_log_handler is None:
                return
            try:
                self._alert_log_handler.close()
            except OSError as e:
                logger.debug("Alert log handler close failed: %s", e)
            self._alert_log_handler = None
            self._alert_log_path = None

    def _callback_worker_loop(self) -> None:
        while self._cb_worker_running.is_set() or not self._cb_queue.empty():
            try:
                item = self._cb_queue.get(timeout=_WORKER_POLL_TIMEOUT_SEC)
            except queue.Empty:
                continue
            try:
                if item is None:
                    return
                event, args, kwargs = item
                self._dispatch_callbacks_sync(event, *args, **kwargs)
            finally:
                try:
                    self._cb_queue.task_done()
                except ValueError:
                    pass

    def _dispatch_callbacks_sync(self, event: str, *args: Any, **kwargs: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except (TypeError, ValueError, AttributeError) as e:
                logger.warning("Callback error for %s (%s): %s", event, type(e).__name__, e)

    def callback_queue_depth(self) -> int:
        return self._cb_queue.qsize()

    def callback_queue_drops(self) -> int:
        with self._cb_drops_lock:
            return self._cb_drops

    def _ensure_node(self, node_id: str, node_num: int = 0, **kwargs: Any) -> Tuple[Any, bool]:
        """Get existing node or create a new one with timestamps.

        Returns (node, is_new). Fires on_node_update callback for new nodes.
        Requires ``self.network`` (a MeshNetwork instance) on the host class.
        """
        from meshing_around_clients.core.models import Node

        is_new = node_id not in self.network.nodes
        if is_new:
            node = Node(
                node_id=node_id,
                node_num=node_num,
                last_heard=datetime.now(timezone.utc),
                first_seen=datetime.now(timezone.utc),
                **kwargs,
            )
            self.network.add_node(node)
            self._trigger_callbacks("on_node_update", node_id, True)
        else:
            node = self.network.get_node(node_id)
            if node:
                node.last_heard = datetime.now(timezone.utc)
                node.is_online = True
        return node, is_new

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for an event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable) -> bool:
        """Unregister a callback for an event. Returns True if found and removed."""
        if event in self._callbacks:
            try:
                self._callbacks[event].remove(callback)
                return True
            except ValueError:
                return False
        return False

    def clear_callbacks(self, event: Optional[str] = None) -> None:
        """Clear all callbacks, or callbacks for a specific event."""
        if event:
            if event in self._callbacks:
                self._callbacks[event].clear()
        else:
            for e in self._callbacks:
                self._callbacks[e].clear()

    def _trigger_callbacks(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Trigger all callbacks for an event.

        Lifecycle events (on_connect, on_disconnect) dispatch synchronously
        so callers can rely on ordering against connect()/disconnect().
        High-frequency message-path events go through the worker queue
        when one is running, so paho's network thread returns immediately.

        Without a worker, fall through to synchronous dispatch — preserves
        the legacy behavior tests and direct callers depend on.
        """
        if event in _SYNCHRONOUS_EVENTS:
            self._dispatch_callbacks_sync(event, *args, **kwargs)
            return
        worker = self._cb_worker
        if worker is not None and worker.is_alive():
            try:
                self._cb_queue.put_nowait((event, args, kwargs))
                return
            except queue.Full:
                with self._cb_drops_lock:
                    self._cb_drops += 1
                    drops = self._cb_drops
                    now = time.monotonic()
                    if now - self._cb_last_drop_log > _DROP_LOG_INTERVAL_SEC:
                        self._cb_last_drop_log = now
                        logger.debug(
                            "Callback queue full (event=%s, total drops=%d) — TUI consumer stalled?",
                            event,
                            drops,
                        )
                return
        self._dispatch_callbacks_sync(event, *args, **kwargs)

    def _drain_callbacks(self, timeout: float = 1.0) -> bool:
        """Wait for the callback worker to process pending events.

        Returns True if drained within ``timeout``, False on timeout.
        Useful in tests to synchronize against the async dispatch path.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._cb_queue.empty():
                return True
            time.sleep(0.01)
        return self._cb_queue.empty()

    def _dispatch_alert_actions(self, alert: Any) -> None:
        """Run configured alert actions: logging, sound, file output.

        Called after ``network.add_alert()`` and ``_trigger_callbacks("on_alert", ...)``.
        Requires ``self.config`` with an ``alerts`` attribute (AlertConfig).
        """
        config = getattr(self, "config", None)
        if config is None:
            return
        alerts_cfg = getattr(config, "alerts", None)
        if alerts_cfg is None:
            return

        # Log to Python logger so it appears in the TUI Log/Diagnostics screen
        logger.warning(
            "ALERT [%s] sev=%d: %s -- %s",
            alert.alert_type.value if hasattr(alert.alert_type, "value") else alert.alert_type,
            alert.severity,
            alert.title,
            alert.message,
        )

        # Play sound if configured
        if getattr(alerts_cfg, "play_sound", False):
            sound_file = getattr(alerts_cfg, "sound_file", "")
            if sound_file:
                play_alert_sound(sound_file)

        # Write to alert log file if configured
        if getattr(alerts_cfg, "log_to_file", False):
            log_file = getattr(alerts_cfg, "log_file", "")
            if log_file:
                self._log_alert_to_file(alert, log_file)

    def _log_alert_to_file(self, alert: Any, log_file: str) -> None:
        """Append a single alert entry to the configured log file.

        Uses a cached RotatingFileHandler (10 MiB × 3 backups) so a long-
        running TUI on a Pi 2W doesn't grow alerts.log without bound.
        """
        try:
            log_path = os.path.join(os.getcwd(), log_file)
            handler = self._get_alert_log_handler(log_path)
            if handler is None:
                return
            ts = alert.timestamp.isoformat() if alert.timestamp else datetime.now(timezone.utc).isoformat()
            alert_type = alert.alert_type.value if hasattr(alert.alert_type, "value") else str(alert.alert_type)
            msg = alert.message or ""
            if len(msg) > _ALERT_LOG_MESSAGE_CAP:
                msg = msg[: _ALERT_LOG_MESSAGE_CAP - 3] + "..."
            line = f"{ts} | {alert_type} | sev={alert.severity} | {alert.title} | {msg}"
            record = logging.LogRecord(
                name="mesh.alerts",
                level=logging.WARNING,
                pathname=__file__,
                lineno=0,
                msg=line,
                args=(),
                exc_info=None,
            )
            with self._alert_log_lock:
                handler.emit(record)
        except OSError as e:
            logger.error("Failed to write alert log to %s: %s", log_file, e)

    def _get_alert_log_handler(self, log_path: str) -> Optional[logging.handlers.RotatingFileHandler]:
        """Return a cached RotatingFileHandler for the alert log path."""
        with self._alert_log_lock:
            if self._alert_log_handler is not None and self._alert_log_path == log_path:
                return self._alert_log_handler
            # Path changed (or first call) — close any old handler and open fresh.
            if self._alert_log_handler is not None:
                try:
                    self._alert_log_handler.close()
                except OSError:
                    pass
                self._alert_log_handler = None
            try:
                parent = os.path.dirname(log_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                handler = logging.handlers.RotatingFileHandler(
                    log_path,
                    maxBytes=_ALERT_LOG_MAX_BYTES,
                    backupCount=_ALERT_LOG_BACKUPS,
                    encoding="utf-8",
                )
                handler.setFormatter(logging.Formatter("%(message)s"))
                self._alert_log_handler = handler
                self._alert_log_path = log_path
                return handler
            except OSError as e:
                logger.error("Failed to open alert log %s: %s", log_path, e)
                return None

    def _is_alert_cooled_down(self, node_id: str, alert_type: str) -> bool:
        """Check if alert should be suppressed (still in cooldown).

        Thread-safe: protected by ``_cooldown_lock``.
        Returns True if suppressed, False if the alert should fire.
        """
        key = f"{node_id}|{alert_type}"
        now = time.monotonic()
        with self._cooldown_lock:
            last = self._alert_cooldowns.get(key)
            if last is not None and (now - last) < self._alert_cooldown_seconds:
                return True  # Still in cooldown — suppress
            self._alert_cooldowns[key] = now
            # Prune stale cooldown entries to prevent unbounded growth
            if len(self._alert_cooldowns) > _MAX_COOLDOWN_ENTRIES:
                cutoff = now - (self._alert_cooldown_seconds * 3)
                self._alert_cooldowns = {k: v for k, v in self._alert_cooldowns.items() if v > cutoff}
        return False  # Cooldown expired — allow alert

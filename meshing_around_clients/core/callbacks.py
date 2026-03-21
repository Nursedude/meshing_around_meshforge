"""Shared callback registration, dispatch, and alert cooldown logic.

Extracted from MeshtasticAPI and MQTTMeshtasticClient which both
implemented identical copies of these patterns.

Also provides shared input validation helpers (safe_float, safe_int)
and shared data extraction (extract_position) used by both API classes
to validate data from mesh network packets.
"""

import logging
import math
import os
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
_DEFAULT_COOLDOWN_SECONDS = 300
_MAX_COOLDOWN_ENTRIES = 1000


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
        """Trigger all callbacks for an event."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except (TypeError, ValueError, AttributeError) as e:
                logger.warning("Callback error for %s (%s): %s", event, type(e).__name__, e)

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
        """Append a single alert entry to the configured log file."""
        try:
            log_path = os.path.join(os.getcwd(), log_file)
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            ts = alert.timestamp.isoformat() if alert.timestamp else datetime.now(timezone.utc).isoformat()
            alert_type = alert.alert_type.value if hasattr(alert.alert_type, "value") else str(alert.alert_type)
            line = f"{ts} | {alert_type} | sev={alert.severity} | {alert.title} | {alert.message}\n"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            logger.error("Failed to write alert log to %s: %s", log_file, e)

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

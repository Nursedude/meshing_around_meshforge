"""Shared callback registration, dispatch, and alert cooldown logic.

Extracted from MeshtasticAPI and MQTTMeshtasticClient which both
implemented identical copies of these patterns.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

_CALLBACK_EVENTS = (
    "on_connect",
    "on_disconnect",
    "on_message",
    "on_node_update",
    "on_alert",
    "on_position",
    "on_telemetry",
)
_DEFAULT_COOLDOWN_SECONDS = 300
_MAX_COOLDOWN_ENTRIES = 1000


class CallbackMixin:
    """Mixin providing event callback registration, dispatch, and alert cooldown.

    Classes using this mixin must call ``_init_callbacks()`` in their ``__init__``.
    """

    def _init_callbacks(self) -> None:
        self._callbacks: Dict[str, List[Callable]] = {e: [] for e in _CALLBACK_EVENTS}
        self._alert_cooldowns: Dict[str, float] = {}
        self._alert_cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS
        self._cooldown_lock = threading.Lock()

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for an event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Trigger all callbacks for an event."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except (TypeError, ValueError, AttributeError) as e:
                logger.warning("Callback error for %s (%s): %s", event, type(e).__name__, e)

    def _is_alert_cooled_down(self, node_id: str, alert_type: str) -> bool:
        """Check if alert should be suppressed (still in cooldown).

        Thread-safe: protected by ``_cooldown_lock``.
        Returns True if suppressed, False if the alert should fire.
        """
        key = f"{node_id}:{alert_type}"
        now = time.monotonic()
        with self._cooldown_lock:
            last = self._alert_cooldowns.get(key)
            if last is not None and (now - last) < self._alert_cooldown_seconds:
                return True  # Still in cooldown — suppress
            self._alert_cooldowns[key] = now
            # Prune stale cooldown entries to prevent unbounded growth
            if len(self._alert_cooldowns) > _MAX_COOLDOWN_ENTRIES:
                cutoff = now - (self._alert_cooldown_seconds * 2)
                self._alert_cooldowns = {k: v for k, v in self._alert_cooldowns.items() if v > cutoff}
        return False  # Cooldown expired — allow alert

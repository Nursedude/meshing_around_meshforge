"""
Unit tests for meshing_around_clients.core.callbacks
"""

import sys
import threading
import time
import unittest

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.callbacks import (
    _CALLBACK_EVENTS,
    _DEFAULT_COOLDOWN_SECONDS,
    _MAX_COOLDOWN_ENTRIES,
    CallbackMixin,
    safe_float,
    safe_int,
)


class _TestHost(CallbackMixin):
    """Minimal host class that uses CallbackMixin."""

    def __init__(self):
        self._init_callbacks()


class TestInitCallbacks(unittest.TestCase):
    """Test _init_callbacks() initialization."""

    def test_callbacks_dict_has_all_events(self):
        host = _TestHost()
        for event in _CALLBACK_EVENTS:
            self.assertIn(event, host._callbacks)
            self.assertEqual(host._callbacks[event], [])

    def test_cooldown_state_initialized(self):
        host = _TestHost()
        self.assertEqual(host._alert_cooldowns, {})
        self.assertEqual(host._alert_cooldown_seconds, _DEFAULT_COOLDOWN_SECONDS)
        self.assertIsInstance(host._cooldown_lock, type(threading.Lock()))


class TestRegisterCallback(unittest.TestCase):
    """Test register_callback()."""

    def test_register_valid_event(self):
        host = _TestHost()

        def cb():
            pass

        host.register_callback("on_connect", cb)
        self.assertIn(cb, host._callbacks["on_connect"])

    def test_register_invalid_event_ignored(self):
        host = _TestHost()

        def cb():
            pass

        host.register_callback("nonexistent_event", cb)
        # Should not raise, and no new key should appear
        self.assertNotIn("nonexistent_event", host._callbacks)

    def test_register_multiple_callbacks(self):
        host = _TestHost()

        def cb1():
            pass

        def cb2():
            pass

        host.register_callback("on_message", cb1)
        host.register_callback("on_message", cb2)
        self.assertEqual(len(host._callbacks["on_message"]), 2)


class TestTriggerCallbacks(unittest.TestCase):
    """Test _trigger_callbacks()."""

    def test_trigger_calls_all_registered(self):
        host = _TestHost()
        results = []
        host.register_callback("on_connect", lambda: results.append("a"))
        host.register_callback("on_connect", lambda: results.append("b"))
        host._trigger_callbacks("on_connect")
        self.assertEqual(results, ["a", "b"])

    def test_trigger_passes_args_and_kwargs(self):
        host = _TestHost()
        captured = {}
        host.register_callback("on_message", lambda x, y=None: captured.update({"x": x, "y": y}))
        host._trigger_callbacks("on_message", 42, y="hello")
        self.assertEqual(captured, {"x": 42, "y": "hello"})

    def test_trigger_exception_in_callback_does_not_propagate(self):
        host = _TestHost()
        results = []
        host.register_callback("on_alert", lambda: (_ for _ in ()).throw(ValueError("boom")))
        host.register_callback("on_alert", lambda: results.append("ok"))
        # The first callback raises, but the second should still run
        host._trigger_callbacks("on_alert")
        self.assertEqual(results, ["ok"])

    def test_trigger_unknown_event_no_error(self):
        host = _TestHost()
        # Should not raise even for unknown events
        host._trigger_callbacks("nonexistent_event")


class TestAlertCooldown(unittest.TestCase):
    """Test _is_alert_cooled_down()."""

    def test_first_call_allows_alert(self):
        host = _TestHost()
        self.assertFalse(host._is_alert_cooled_down("!node1", "battery"))

    def test_repeated_call_within_window_suppresses(self):
        host = _TestHost()
        host._is_alert_cooled_down("!node1", "battery")
        self.assertTrue(host._is_alert_cooled_down("!node1", "battery"))

    def test_different_nodes_are_independent(self):
        host = _TestHost()
        host._is_alert_cooled_down("!node1", "battery")
        # Different node should not be suppressed
        self.assertFalse(host._is_alert_cooled_down("!node2", "battery"))

    def test_different_alert_types_are_independent(self):
        host = _TestHost()
        host._is_alert_cooled_down("!node1", "battery")
        # Different alert type should not be suppressed
        self.assertFalse(host._is_alert_cooled_down("!node1", "emergency"))

    def test_cooldown_expires(self):
        host = _TestHost()
        host._alert_cooldown_seconds = 0  # Instant expiry
        host._is_alert_cooled_down("!node1", "battery")
        time.sleep(0.01)  # Ensure monotonic time advances
        self.assertFalse(host._is_alert_cooled_down("!node1", "battery"))

    def test_pruning_when_exceeding_max_entries(self):
        host = _TestHost()
        host._alert_cooldown_seconds = 0  # All entries will be stale for pruning
        # Fill up beyond the limit
        for i in range(_MAX_COOLDOWN_ENTRIES + 10):
            host._alert_cooldowns[f"!node{i}:battery"] = 0.0  # Ancient timestamps
        # Trigger pruning via a new call
        time.sleep(0.01)
        host._is_alert_cooled_down("!trigger", "prune")
        # After pruning, stale entries should be removed
        self.assertLessEqual(len(host._alert_cooldowns), _MAX_COOLDOWN_ENTRIES)

    def test_thread_safety(self):
        host = _TestHost()
        host._alert_cooldown_seconds = 0
        errors = []

        def worker(thread_id):
            try:
                for i in range(50):
                    host._is_alert_cooled_down(f"!node{thread_id}", f"alert{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")


class TestSafeFloat(unittest.TestCase):
    """Test safe_float() shared validation function."""

    def test_valid_float_in_range(self):
        self.assertEqual(safe_float(45.5, -90.0, 90.0), 45.5)

    def test_none_returns_none(self):
        self.assertIsNone(safe_float(None, -90.0, 90.0))

    def test_nan_returns_none(self):
        self.assertIsNone(safe_float(float("nan"), -90.0, 90.0))

    def test_inf_returns_none(self):
        self.assertIsNone(safe_float(float("inf"), -90.0, 90.0))

    def test_negative_inf_returns_none(self):
        self.assertIsNone(safe_float(float("-inf"), -90.0, 90.0))

    def test_below_range_returns_none(self):
        self.assertIsNone(safe_float(-91.0, -90.0, 90.0))

    def test_above_range_returns_none(self):
        self.assertIsNone(safe_float(91.0, -90.0, 90.0))

    def test_boundary_min_accepted(self):
        self.assertEqual(safe_float(-90.0, -90.0, 90.0), -90.0)

    def test_boundary_max_accepted(self):
        self.assertEqual(safe_float(90.0, -90.0, 90.0), 90.0)

    def test_string_number_converted(self):
        self.assertEqual(safe_float("3.14", 0.0, 10.0), 3.14)

    def test_non_numeric_string_returns_none(self):
        self.assertIsNone(safe_float("abc", 0.0, 10.0))

    def test_zero_in_range(self):
        self.assertEqual(safe_float(0.0, -1.0, 1.0), 0.0)


class TestSafeInt(unittest.TestCase):
    """Test safe_int() shared validation function."""

    def test_valid_int_in_range(self):
        self.assertEqual(safe_int(85, 0, 101), 85)

    def test_none_returns_none(self):
        self.assertIsNone(safe_int(None, 0, 101))

    def test_below_range_returns_none(self):
        self.assertIsNone(safe_int(-5, 0, 101))

    def test_above_range_returns_none(self):
        self.assertIsNone(safe_int(200, 0, 101))

    def test_boundary_min_accepted(self):
        self.assertEqual(safe_int(0, 0, 101), 0)

    def test_boundary_max_accepted(self):
        self.assertEqual(safe_int(101, 0, 101), 101)

    def test_float_truncated_to_int(self):
        self.assertEqual(safe_int(3.7, 0, 10), 3)

    def test_string_number_converted(self):
        self.assertEqual(safe_int("42", 0, 100), 42)

    def test_non_numeric_string_returns_none(self):
        self.assertIsNone(safe_int("abc", 0, 100))


if __name__ == "__main__":
    unittest.main()

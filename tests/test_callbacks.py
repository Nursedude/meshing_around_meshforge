"""
Unit tests for meshing_around_clients.core.callbacks
"""

import sys
import threading
import time
import unittest
import unittest.mock

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.callbacks import (
    _CALLBACK_EVENTS,
    _DEFAULT_COOLDOWN_SECONDS,
    _MAX_COOLDOWN_ENTRIES,
    CallbackMixin,
    extract_position,
    play_alert_sound,
    safe_float,
    safe_int,
)
from meshing_around_clients.core.models import MeshNetwork, Node


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


class TestUnregisterCallback(unittest.TestCase):
    """Test unregister_callback()."""

    def test_unregister_existing(self):
        host = _TestHost()
        cb = lambda: None  # noqa: E731
        host.register_callback("on_connect", cb)
        self.assertTrue(host.unregister_callback("on_connect", cb))
        self.assertNotIn(cb, host._callbacks["on_connect"])

    def test_unregister_nonexistent_returns_false(self):
        host = _TestHost()
        self.assertFalse(host.unregister_callback("on_connect", lambda: None))

    def test_unregister_invalid_event_returns_false(self):
        host = _TestHost()
        self.assertFalse(host.unregister_callback("bogus_event", lambda: None))


class TestClearCallbacks(unittest.TestCase):
    """Test clear_callbacks()."""

    def test_clear_specific_event(self):
        host = _TestHost()
        host.register_callback("on_connect", lambda: None)
        host.register_callback("on_message", lambda: None)
        host.clear_callbacks("on_connect")
        self.assertEqual(len(host._callbacks["on_connect"]), 0)
        self.assertEqual(len(host._callbacks["on_message"]), 1)

    def test_clear_all(self):
        host = _TestHost()
        host.register_callback("on_connect", lambda: None)
        host.register_callback("on_message", lambda: None)
        host.clear_callbacks()
        for event in _CALLBACK_EVENTS:
            self.assertEqual(len(host._callbacks[event]), 0)

    def test_clear_nonexistent_event_no_error(self):
        host = _TestHost()
        host.clear_callbacks("bogus_event")  # Should not raise


class TestExtractPosition(unittest.TestCase):
    """Test extract_position() shared helper."""

    def test_valid_float_coords(self):
        pos = extract_position({"latitude": 45.5, "longitude": -122.6, "altitude": 100})
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.latitude, 45.5)
        self.assertAlmostEqual(pos.longitude, -122.6)
        self.assertEqual(pos.altitude, 100)

    def test_latitudeI_fallback(self):
        pos = extract_position({"latitudeI": 455000000, "longitudeI": -1226000000})
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.latitude, 45.5, places=1)
        self.assertAlmostEqual(pos.longitude, -122.6, places=1)

    def test_missing_coords_returns_none(self):
        self.assertIsNone(extract_position({}))

    def test_out_of_range_lat_returns_none(self):
        self.assertIsNone(extract_position({"latitude": 999, "longitude": -122.6}))

    def test_out_of_range_lon_returns_none(self):
        self.assertIsNone(extract_position({"latitude": 45.5, "longitude": 999}))

    def test_zero_latitudeI_treated_as_missing(self):
        self.assertIsNone(extract_position({"latitudeI": 0, "longitudeI": 0}))

    def test_mixed_float_and_integer(self):
        pos = extract_position({"latitude": 45.5, "longitudeI": -1226000000})
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.latitude, 45.5)
        self.assertAlmostEqual(pos.longitude, -122.6, places=1)

    def test_altitude_defaults_to_zero(self):
        pos = extract_position({"latitude": 45.5, "longitude": -122.6})
        self.assertIsNotNone(pos)
        self.assertEqual(pos.altitude, 0)

    def test_has_timestamp(self):
        pos = extract_position({"latitude": 45.5, "longitude": -122.6})
        self.assertIsNotNone(pos.time)


class TestEnsureNode(unittest.TestCase):
    """Test _ensure_node() get-or-create helper."""

    def setUp(self):
        self.host = _TestHost()
        self.host.network = MeshNetwork()

    def test_creates_new_node(self):
        node, is_new = self.host._ensure_node("!aabb0011", 0xAABB0011)
        self.assertTrue(is_new)
        self.assertEqual(node.node_id, "!aabb0011")
        self.assertIn("!aabb0011", self.host.network.nodes)

    def test_returns_existing_node(self):
        existing = Node(node_id="!aabb0011", node_num=0xAABB0011)
        self.host.network.add_node(existing)
        node, is_new = self.host._ensure_node("!aabb0011", 0xAABB0011)
        self.assertFalse(is_new)
        self.assertIs(node, existing)

    def test_updates_last_heard_on_existing(self):
        from datetime import timedelta

        old_time = self.host.network.nodes.get("!aabb0011") or None
        existing = Node(node_id="!aabb0011", node_num=0xAABB0011)
        from datetime import datetime, timezone

        existing.last_heard = datetime.now(timezone.utc) - timedelta(hours=1)
        old_time = existing.last_heard
        self.host.network.add_node(existing)
        node, _ = self.host._ensure_node("!aabb0011")
        self.assertGreater(node.last_heard, old_time)

    def test_fires_callback_for_new_node(self):
        events = []
        self.host.register_callback("on_node_update", lambda *a: events.append(a))
        self.host._ensure_node("!aabb0011", 0xAABB0011)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], ("!aabb0011", True))

    def test_no_callback_for_existing_node(self):
        self.host.network.add_node(Node(node_id="!aabb0011", node_num=0xAABB0011))
        events = []
        self.host.register_callback("on_node_update", lambda *a: events.append(a))
        self.host._ensure_node("!aabb0011")
        self.assertEqual(len(events), 0)

    def test_kwargs_passed_to_new_node(self):
        node, _ = self.host._ensure_node("!aabb0011", 0xAABB0011, short_name="TST")
        self.assertEqual(node.short_name, "TST")

    def test_sets_is_online_on_existing(self):
        existing = Node(node_id="!aabb0011", node_num=0xAABB0011)
        existing.is_online = False
        self.host.network.add_node(existing)
        node, is_new = self.host._ensure_node("!aabb0011")
        self.assertFalse(is_new)
        self.assertTrue(node.is_online)


class TestPlayAlertSound(unittest.TestCase):
    """Test play_alert_sound() stub."""

    def test_nonexistent_file_returns_false(self):
        self.assertFalse(play_alert_sound("/nonexistent/file.oga"))

    def test_empty_path_returns_false(self):
        self.assertFalse(play_alert_sound(""))

    @unittest.mock.patch("shutil.which", return_value=None)
    @unittest.mock.patch("os.path.isfile", return_value=True)
    def test_no_player_returns_false(self, mock_isfile, mock_which):
        self.assertFalse(play_alert_sound("/some/file.oga"))

    @unittest.mock.patch("subprocess.Popen")
    @unittest.mock.patch("shutil.which", return_value="/usr/bin/paplay")
    @unittest.mock.patch("os.path.isfile", return_value=True)
    def test_successful_playback(self, mock_isfile, mock_which, mock_popen):
        self.assertTrue(play_alert_sound("/some/file.oga"))
        mock_popen.assert_called_once()

    @unittest.mock.patch("subprocess.Popen", side_effect=OSError("no such player"))
    @unittest.mock.patch("shutil.which")
    @unittest.mock.patch("os.path.isfile", return_value=True)
    def test_popen_failure_tries_next(self, mock_isfile, mock_which, mock_popen):
        # All players fail with OSError
        mock_which.return_value = "/usr/bin/paplay"
        self.assertFalse(play_alert_sound("/some/file.oga"))


if __name__ == "__main__":
    unittest.main()

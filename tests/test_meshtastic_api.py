"""
Unit tests for meshing_around_clients.core.meshtastic_api

Tests MockMeshtasticAPI — the hardware-free mock used in demo mode.
"""

import sys
import time
import unittest

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.config import Config  # noqa: E402
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI  # noqa: E402


class TestMockAPIConnect(unittest.TestCase):
    """Test MockMeshtasticAPI connection lifecycle."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)

    def tearDown(self):
        self.api.disconnect()

    def test_connect_sets_connected(self):
        result = self.api.connect()
        self.assertTrue(result)
        self.assertTrue(self.api.connection_info.connected)
        self.assertEqual(self.api.connection_info.interface_type, "mock")

    def test_connect_creates_demo_nodes(self):
        self.api.connect()
        nodes = self.api.get_nodes()
        self.assertGreaterEqual(len(nodes), 5, "Should create at least 5 demo nodes")

    def test_connect_sets_my_node_id(self):
        self.api.connect()
        self.assertTrue(self.api.connection_info.my_node_id.startswith("!"))
        self.assertGreater(self.api.connection_info.my_node_num, 0)

    def test_disconnect(self):
        self.api.connect()
        self.api.disconnect()
        self.assertFalse(self.api.connection_info.connected)

    def test_double_disconnect_safe(self):
        self.api.connect()
        self.api.disconnect()
        self.api.disconnect()  # Should not raise


class TestMockAPISendMessage(unittest.TestCase):
    """Test MockMeshtasticAPI message sending."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_send_message_returns_true(self):
        result = self.api.send_message("Hello mesh!", "^all", channel=0)
        self.assertTrue(result)

    def test_send_message_adds_to_network(self):
        initial_count = len(list(self.api.network.messages))
        self.api.send_message("Test message", "^all", channel=0)
        final_count = len(list(self.api.network.messages))
        self.assertGreater(final_count, initial_count)

    def test_send_message_text_preserved(self):
        self.api.send_message("Exact test text", "^all", channel=0)
        messages = list(self.api.network.messages)
        found = any(m.text == "Exact test text" for m in messages)
        self.assertTrue(found, "Sent message text should appear in network messages")


class TestMockAPIDemoTraffic(unittest.TestCase):
    """Test MockMeshtasticAPI demo traffic generation."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_demo_event_generates_activity(self):
        """Calling _generate_demo_event() should produce messages or telemetry."""
        # Call directly to avoid flaky timing from the 5-15s background interval
        for _ in range(10):
            self.api._generate_demo_event()
        messages = list(self.api.network.messages)
        # With 60% message chance over 10 events, probability of 0 messages is 0.4^10 ≈ 0.01%
        self.assertGreater(len(messages), 0, "Demo events should generate messages")

    def test_demo_nodes_have_telemetry(self):
        """Demo nodes should have telemetry data."""
        time.sleep(2)
        nodes = self.api.get_nodes()
        nodes_with_telemetry = [n for n in nodes if n.telemetry is not None]
        self.assertGreater(len(nodes_with_telemetry), 0, "Some demo nodes should have telemetry")

    def test_demo_nodes_have_positions(self):
        """Demo nodes should have position data."""
        nodes = self.api.get_nodes()
        nodes_with_position = [n for n in nodes if n.position is not None]
        self.assertGreater(len(nodes_with_position), 0, "Some demo nodes should have positions")


class TestMockAPICallbacks(unittest.TestCase):
    """Test MockMeshtasticAPI callback system."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.callback_events = []

    def tearDown(self):
        self.api.disconnect()

    def test_on_connect_callback(self):
        self.api.register_callback("on_connect", lambda *args: self.callback_events.append("connect"))
        self.api.connect()
        self.assertIn("connect", self.callback_events)

    def test_on_disconnect_callback(self):
        self.api.register_callback("on_disconnect", lambda *args: self.callback_events.append("disconnect"))
        self.api.connect()
        self.api.disconnect()
        self.assertIn("disconnect", self.callback_events)


class TestMockAPINetworkState(unittest.TestCase):
    """Test MockMeshtasticAPI network state consistency."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_get_nodes_returns_list(self):
        nodes = self.api.get_nodes()
        self.assertIsInstance(nodes, list)

    def test_get_alerts_returns_list(self):
        alerts = self.api.get_alerts()
        self.assertIsInstance(alerts, list)

    def test_network_health_valid(self):
        health = self.api.network.mesh_health
        self.assertIn("score", health)
        self.assertIn("status", health)
        self.assertGreaterEqual(health["score"], 0)
        self.assertLessEqual(health["score"], 100)


class TestMockAPIPositionValidation(unittest.TestCase):
    """Test _handle_position() input validation."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()
        # Pick the first demo node to test against
        self.node_id = list(self.api.network.nodes.keys())[0]

    def tearDown(self):
        self.api.disconnect()

    def _make_position_packet(self, lat=None, lon=None, lat_i=None, lon_i=None, alt=0):
        position = {}
        if lat is not None:
            position["latitude"] = lat
        if lon is not None:
            position["longitude"] = lon
        if lat_i is not None:
            position["latitudeI"] = lat_i
        if lon_i is not None:
            position["longitudeI"] = lon_i
        position["altitude"] = alt
        return {"fromId": self.node_id, "decoded": {"position": position}}

    def test_valid_coordinates_accepted(self):
        packet = self._make_position_packet(lat=45.5, lon=-122.6)
        self.api._handle_position(packet)
        node = self.api.network.nodes[self.node_id]
        self.assertIsNotNone(node.position)
        self.assertAlmostEqual(node.position.latitude, 45.5)
        self.assertAlmostEqual(node.position.longitude, -122.6)

    def test_nan_latitude_rejected(self):
        # Store original position
        original_pos = self.api.network.nodes[self.node_id].position
        packet = self._make_position_packet(lat=float("nan"), lon=-122.6)
        self.api._handle_position(packet)
        node = self.api.network.nodes[self.node_id]
        # Position should not have been updated to NaN
        self.assertEqual(node.position, original_pos)

    def test_inf_longitude_rejected(self):
        original_pos = self.api.network.nodes[self.node_id].position
        packet = self._make_position_packet(lat=45.5, lon=float("inf"))
        self.api._handle_position(packet)
        node = self.api.network.nodes[self.node_id]
        self.assertEqual(node.position, original_pos)

    def test_out_of_range_latitude_rejected(self):
        original_pos = self.api.network.nodes[self.node_id].position
        packet = self._make_position_packet(lat=91.0, lon=-122.6)
        self.api._handle_position(packet)
        node = self.api.network.nodes[self.node_id]
        self.assertEqual(node.position, original_pos)

    def test_out_of_range_longitude_rejected(self):
        original_pos = self.api.network.nodes[self.node_id].position
        packet = self._make_position_packet(lat=45.5, lon=181.0)
        self.api._handle_position(packet)
        node = self.api.network.nodes[self.node_id]
        self.assertEqual(node.position, original_pos)

    def test_latitudeI_conversion_works(self):
        packet = self._make_position_packet(lat_i=455000000, lon_i=-1226000000)
        self.api._handle_position(packet)
        node = self.api.network.nodes[self.node_id]
        self.assertIsNotNone(node.position)
        self.assertAlmostEqual(node.position.latitude, 45.5)
        self.assertAlmostEqual(node.position.longitude, -122.6)


class TestMockAPITelemetryValidation(unittest.TestCase):
    """Test _handle_telemetry() input validation."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()
        self.node_id = list(self.api.network.nodes.keys())[0]

    def tearDown(self):
        self.api.disconnect()

    def _make_telemetry_packet(self, **metrics):
        return {"fromId": self.node_id, "decoded": {"telemetry": {"deviceMetrics": metrics}}}

    def test_valid_telemetry_accepted(self):
        packet = self._make_telemetry_packet(batteryLevel=85, voltage=3.7, channelUtilization=15.0, airUtilTx=2.5)
        self.api._handle_telemetry(packet)
        node = self.api.network.nodes[self.node_id]
        self.assertEqual(node.telemetry.battery_level, 85)
        self.assertAlmostEqual(node.telemetry.voltage, 3.7)
        self.assertAlmostEqual(node.telemetry.channel_utilization, 15.0)

    def test_negative_battery_rejected(self):
        node = self.api.network.nodes[self.node_id]
        original_battery = node.telemetry.battery_level
        packet = self._make_telemetry_packet(batteryLevel=-5)
        self.api._handle_telemetry(packet)
        # Should keep original value, not accept -5
        self.assertEqual(node.telemetry.battery_level, original_battery)

    def test_battery_over_101_rejected(self):
        node = self.api.network.nodes[self.node_id]
        original_battery = node.telemetry.battery_level
        packet = self._make_telemetry_packet(batteryLevel=200)
        self.api._handle_telemetry(packet)
        self.assertEqual(node.telemetry.battery_level, original_battery)

    def test_channel_utilization_over_100_rejected(self):
        node = self.api.network.nodes[self.node_id]
        original_util = node.telemetry.channel_utilization
        packet = self._make_telemetry_packet(channelUtilization=150.0)
        self.api._handle_telemetry(packet)
        self.assertEqual(node.telemetry.channel_utilization, original_util)


class TestMockAPISendMessageValidation(unittest.TestCase):
    """Test send_message() byte-length validation."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_send_message_rejects_oversized(self):
        result = self.api.send_message("x" * 229)
        self.assertFalse(result)

    def test_send_message_allows_228_bytes(self):
        result = self.api.send_message("x" * 228)
        self.assertTrue(result)

    def test_send_message_rejects_multibyte_overflow(self):
        # 58 emoji * 4 bytes = 232 > 228
        result = self.api.send_message("\U0001f600" * 58)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()

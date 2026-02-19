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


if __name__ == "__main__":
    unittest.main()

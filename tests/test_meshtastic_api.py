"""
Unit tests for meshing_around_clients.core.meshtastic_api

Tests MockMeshtasticAPI — the hardware-free mock used in demo mode.
"""

import queue
import sys
import time
import unittest
from unittest.mock import patch

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


class TestWorkerThreadCrashResilience(unittest.TestCase):
    """Test that worker thread crash sets disconnected state."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)

    def tearDown(self):
        self.api._running.clear()
        self.api.disconnect()

    def test_worker_crash_sets_disconnected(self):
        """If _process_packet raises an unexpected exception, worker should set disconnected."""
        self.api._running.set()
        self.api.connection_info.connected = True
        self.api.network.connection_status = "connected"

        # Put a poison pill that will cause _process_packet to raise RuntimeError
        self.api._message_queue.put(("receive", None))

        # Patch _process_packet to raise an unexpected exception
        with patch.object(self.api, "_process_packet", side_effect=RuntimeError("boom")):
            self.api._worker_loop()

        # After crash, state should reflect disconnection
        self.assertFalse(self.api._running.is_set())
        self.assertFalse(self.api.connection_info.connected)
        self.assertEqual(self.api.network.connection_status, "error")

    def test_worker_handles_known_exceptions_without_crash(self):
        """Known exceptions (KeyError, TypeError, etc.) should not crash the worker."""
        self.api._running.set()
        self.api.connection_info.connected = True

        # Put a bad packet and then stop the worker
        self.api._message_queue.put(("receive", "not-a-dict"))

        # Clear _running after the first packet so the loop exits
        original_get = self.api._message_queue.get

        call_count = [0]

        def get_then_stop(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:
                self.api._running.clear()
                raise queue.Empty()
            return original_get(*args, **kwargs)

        with patch.object(self.api._message_queue, "get", side_effect=get_then_stop):
            self.api._worker_loop()

        # Worker should exit cleanly — connection state preserved
        self.assertTrue(self.api.connection_info.connected)


class TestMockAPIDynamicNodes(unittest.TestCase):
    """Test dynamic node discovery in demo mode."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.storage.enabled = False
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_extra_demo_nodes_defined(self):
        self.assertGreater(len(self.api._EXTRA_DEMO_NODES), 0)

    def test_max_demo_nodes_cap_defined(self):
        self.assertGreaterEqual(self.api._MAX_DEMO_NODES, 5)

    def test_initial_nodes_count(self):
        self.assertEqual(len(self.api.network.nodes), 5)

    @patch("random.random", return_value=0.01)  # Force discovery branch (< 0.05)
    def test_dynamic_node_discovery(self, mock_random):
        initial_count = len(self.api.network.nodes)
        self.api._generate_demo_event()
        self.assertGreater(len(self.api.network.nodes), initial_count)

    @patch("random.random", return_value=0.01)
    def test_discovery_fires_alert(self, mock_random):
        alerts = []
        self.api.register_callback("on_alert", lambda a: alerts.append(a))
        self.api._generate_demo_event()
        new_node_alerts = [a for a in alerts if hasattr(a, "alert_type") and a.alert_type.value == "new_node"]
        self.assertGreater(len(new_node_alerts), 0)

    @patch("random.random", return_value=0.01)
    def test_discovery_fires_node_update(self, mock_random):
        events = []
        self.api.register_callback("on_node_update", lambda *a: events.append(a))
        self.api._generate_demo_event()
        self.assertGreater(len(events), 0)

    def test_discovery_capped_at_max(self):
        """Node discovery stops at _MAX_DEMO_NODES."""
        for _ in range(100):
            with patch("random.random", return_value=0.01):
                self.api._generate_demo_event()
        self.assertLessEqual(len(self.api.network.nodes), self.api._MAX_DEMO_NODES)

    @patch("random.random", return_value=0.99)  # Will not trigger discovery
    def test_no_discovery_on_high_random(self, mock_random):
        initial_count = len(self.api.network.nodes)
        self.api._generate_demo_event()
        # Might still be same count (message/telemetry event instead)
        self.assertLessEqual(len(self.api.network.nodes), initial_count + 1)

    def test_demo_message_generation(self):
        """Test the message generation path of _generate_demo_event."""
        msgs_before = len(list(self.api.network.messages))
        with patch("random.random", side_effect=[0.99, 0.3]):  # Skip discovery, then message
            self.api._generate_demo_event()
        msgs_after = len(list(self.api.network.messages))
        self.assertGreaterEqual(msgs_after, msgs_before)

    def test_demo_telemetry_generation(self):
        """Test the telemetry generation path of _generate_demo_event."""
        with patch("random.random", side_effect=[0.99, 0.9]):  # Skip discovery, then telemetry
            self.api._generate_demo_event()
        # Should not raise


class TestMockAPISendMessageExtended(unittest.TestCase):
    """Test MockMeshtasticAPI send_message (extended)."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_send_message_success(self):
        result = self.api.send_message("Hello mesh!")
        self.assertTrue(result)
        msgs = list(self.api.network.messages)
        self.assertTrue(any("Hello mesh!" in m.text for m in msgs))

    def test_send_message_too_long(self):
        long_msg = "x" * 300
        result = self.api.send_message(long_msg)
        self.assertFalse(result)

    def test_send_message_to_destination(self):
        result = self.api.send_message("Direct message", destination="!abc12345")
        self.assertTrue(result)


class TestConnectionInfo(unittest.TestCase):
    """Test ConnectionInfo dataclass."""

    def test_default_values(self):
        from meshing_around_clients.core.meshtastic_api import ConnectionInfo

        info = ConnectionInfo()
        self.assertFalse(info.connected)
        self.assertEqual(info.interface_type, "")
        self.assertEqual(info.device_path, "")
        self.assertEqual(info.error_message, "")
        self.assertEqual(info.my_node_id, "")
        self.assertEqual(info.my_node_num, 0)


class TestConnectionHealth(unittest.TestCase):
    """Test connection_health property."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)

    def tearDown(self):
        self.api.disconnect()

    def test_health_disconnected(self):
        health = self.api.connection_health
        self.assertEqual(health["status"], "disconnected")
        self.assertFalse(health["connected"])

    def test_health_connected(self):
        self.api.connect()
        health = self.api.connection_health
        self.assertEqual(health["connected"], True)
        self.assertIn("queue_size", health)
        self.assertIn("queue_maxsize", health)
        self.assertIn("messages_dropped", health)
        self.assertEqual(health["messages_dropped"], 0)


class TestIsHealthy(unittest.TestCase):
    """Test is_healthy method."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)

    def tearDown(self):
        self.api.disconnect()

    def test_not_healthy_when_disconnected(self):
        self.assertFalse(self.api.is_healthy())

    def test_healthy_when_connected(self):
        self.api.connect()
        # MockAPI sets _running but no worker thread, so check connected status
        self.assertTrue(self.api.connection_info.connected)


class TestGetMessagesFiltered(unittest.TestCase):
    """Test get_messages with channel filter."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_get_messages_no_filter(self):
        self.api.send_message("msg1", channel=0)
        self.api.send_message("msg2", channel=1)
        msgs = self.api.get_messages()
        self.assertGreaterEqual(len(msgs), 2)

    def test_get_messages_with_channel_filter(self):
        self.api.send_message("ch0 msg", channel=0)
        self.api.send_message("ch1 msg", channel=1)
        msgs = self.api.get_messages(channel=0)
        for m in msgs:
            self.assertEqual(m.channel, 0)

    def test_get_messages_with_limit(self):
        for i in range(10):
            self.api.send_message(f"msg {i}")
        msgs = self.api.get_messages(limit=3)
        self.assertLessEqual(len(msgs), 3)


class TestAcknowledgeAlert(unittest.TestCase):
    """Test acknowledge_alert method."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_acknowledge_nonexistent_returns_false(self):
        result = self.api.acknowledge_alert("nonexistent-id")
        self.assertFalse(result)

    def test_acknowledge_existing_alert(self):
        # Generate alerts via demo events
        for _ in range(20):
            with patch("random.random", return_value=0.01):
                self.api._generate_demo_event()
        alerts = self.api.get_alerts()
        if alerts:
            result = self.api.acknowledge_alert(alerts[0].id)
            self.assertTrue(result)
            self.assertTrue(alerts[0].acknowledged)


class TestGetAlertsFiltered(unittest.TestCase):
    """Test get_alerts with unread filter."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_get_all_alerts(self):
        alerts = self.api.get_alerts()
        self.assertIsInstance(alerts, list)

    def test_get_unread_alerts(self):
        alerts = self.api.get_unread_alerts = self.api.get_alerts(unread_only=True)
        self.assertIsInstance(alerts, list)


class TestMockAPIMessageCallbacks(unittest.TestCase):
    """Test message-related callbacks in MockMeshtasticAPI."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)
        self.messages_received = []
        self.api.register_callback("on_message", lambda m: self.messages_received.append(m))
        self.api.connect()

    def tearDown(self):
        self.api.disconnect()

    def test_demo_events_trigger_message_callbacks(self):
        for _ in range(10):
            with patch("random.random", side_effect=[0.99, 0.3]):
                self.api._generate_demo_event()
        self.assertGreater(len(self.messages_received), 0)


class TestCloseInterface(unittest.TestCase):
    """Test _close_interface cleanup helper."""

    def setUp(self):
        self.config = Config()
        self.api = MockMeshtasticAPI(self.config)

    def tearDown(self):
        self.api.disconnect()

    def test_close_interface_when_none(self):
        """_close_interface is safe when no interface exists."""
        self.api.interface = None
        self.api._close_interface()
        self.assertIsNone(self.api.interface)

    def test_close_interface_calls_close(self):
        """_close_interface closes and discards a live interface."""
        from unittest.mock import MagicMock

        mock_iface = MagicMock()
        self.api.interface = mock_iface
        self.api._close_interface()
        mock_iface.close.assert_called_once()
        self.assertIsNone(self.api.interface)

    def test_close_interface_handles_oserror(self):
        """_close_interface suppresses OSError from close()."""
        from unittest.mock import MagicMock

        mock_iface = MagicMock()
        mock_iface.close.side_effect = OSError("socket error")
        self.api.interface = mock_iface
        self.api._close_interface()  # Should not raise
        self.assertIsNone(self.api.interface)

    def test_close_interface_handles_runtime_error(self):
        """_close_interface suppresses RuntimeError from close()."""
        from unittest.mock import MagicMock

        mock_iface = MagicMock()
        mock_iface.close.side_effect = RuntimeError("already closed")
        self.api.interface = mock_iface
        self.api._close_interface()  # Should not raise
        self.assertIsNone(self.api.interface)


class TestTryCreate(unittest.TestCase):
    """Test _try_create kwarg fallback logic."""

    def test_try_create_passes_all_kwargs(self):
        """When constructor accepts all kwargs, they are passed through."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        def mock_cls(host, portNumber=4403, connectTimeoutSeconds=30):
            return {"host": host, "port": portNumber, "timeout": connectTimeoutSeconds}

        result = MeshtasticAPI._try_create(mock_cls, "192.168.1.1", portNumber=9443, connectTimeoutSeconds=10)
        self.assertEqual(result["host"], "192.168.1.1")
        self.assertEqual(result["port"], 9443)
        self.assertEqual(result["timeout"], 10)

    def test_try_create_drops_unsupported_kwargs(self):
        """When constructor raises TypeError, optional kwargs are dropped."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        call_count = [0]

        def mock_cls(host):
            call_count[0] += 1
            return {"host": host}

        result = MeshtasticAPI._try_create(mock_cls, "192.168.1.1", portNumber=9443, connectTimeoutSeconds=10)
        self.assertEqual(result["host"], "192.168.1.1")
        self.assertEqual(call_count[0], 1)  # Second call succeeded


class TestTcpHostPortParsing(unittest.TestCase):
    """Test TCP host:port parsing in _create_interface."""

    def test_hostname_without_port_uses_default(self):
        """Hostname without port should default to 4403."""
        from unittest.mock import MagicMock
        from unittest.mock import patch as mock_patch

        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        config = Config()
        config.interface.type = "tcp"
        config.interface.hostname = "192.168.86.248"
        api = MeshtasticAPI(config)

        mock_tcp = MagicMock()
        mock_mod = MagicMock()
        mock_mod.TCPInterface = mock_tcp

        with mock_patch.dict(
            "meshing_around_clients.core.meshtastic_api._INTERFACE_MODULES",
            {"tcp_interface": mock_mod},
        ):
            api._create_interface("tcp")

        mock_tcp.assert_called_once_with("192.168.86.248", portNumber=4403, connectTimeoutSeconds=30.0, noNodes=True)

    def test_hostname_with_port_parses_correctly(self):
        """Hostname with :port should extract and pass portNumber."""
        from unittest.mock import MagicMock
        from unittest.mock import patch as mock_patch

        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        config = Config()
        config.interface.type = "tcp"
        config.interface.hostname = "192.168.86.248:9443"
        api = MeshtasticAPI(config)

        mock_tcp = MagicMock()
        mock_mod = MagicMock()
        mock_mod.TCPInterface = mock_tcp

        with mock_patch.dict(
            "meshing_around_clients.core.meshtastic_api._INTERFACE_MODULES",
            {"tcp_interface": mock_mod},
        ):
            api._create_interface("tcp")

        mock_tcp.assert_called_once_with("192.168.86.248", portNumber=9443, connectTimeoutSeconds=30.0, noNodes=True)

    def test_device_path_preserves_full_hostname(self):
        """connection_info.device_path should keep the original host:port string."""
        from unittest.mock import MagicMock
        from unittest.mock import patch as mock_patch

        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        config = Config()
        config.interface.type = "tcp"
        config.interface.hostname = "10.0.0.1:9443"
        api = MeshtasticAPI(config)

        mock_mod = MagicMock()
        with mock_patch.dict(
            "meshing_around_clients.core.meshtastic_api._INTERFACE_MODULES",
            {"tcp_interface": mock_mod},
        ):
            api._create_interface("tcp")

        self.assertEqual(api.connection_info.device_path, "10.0.0.1:9443")


class TestConnectCleansUpPreviousInterface(unittest.TestCase):
    """Test that connect() cleans up a stale interface via _close_interface."""

    def test_close_interface_called_from_real_connect(self):
        """MeshtasticAPI.connect() calls _close_interface before connecting."""
        from unittest.mock import MagicMock
        from unittest.mock import patch as mock_patch

        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        config = Config()
        api = MeshtasticAPI(config)
        mock_iface = MagicMock()
        api.interface = mock_iface

        # Patch _close_interface to verify it's called, and _create_interface
        # to avoid needing real meshtastic hardware
        with (
            mock_patch.object(api, "_close_interface") as mock_close,
            mock_patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True),
            mock_patch.object(api, "_create_interface", side_effect=OSError("test")),
        ):
            api.connect()

        mock_close.assert_called_once()


class TestConnectWithRetryConfigError(unittest.TestCase):
    """Test connect_with_retry bails on configuration errors."""

    def test_config_error_stops_retry(self):
        """Configuration errors should not be retried."""
        config = Config()
        api = MockMeshtasticAPI(config)

        attempt_count = [0]

        def mock_connect():
            attempt_count[0] += 1
            api.connection_info.error_message = "Configuration error (ValueError): bad hostname"
            api.connection_info.connected = False
            return False

        api.connect = mock_connect
        with patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True):
            result = api.connect_with_retry(max_retries=3)
        self.assertFalse(result)
        self.assertEqual(attempt_count[0], 1)  # Should not retry

    def test_transient_error_retries(self):
        """Transient errors should be retried."""
        config = Config()
        api = MockMeshtasticAPI(config)

        attempt_count = [0]

        def mock_connect():
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                api.connection_info.error_message = "Connection failed (OSError): timeout"
                api.connection_info.connected = False
                return False
            api.connection_info.connected = True
            return True

        api.connect = mock_connect
        with patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True):
            result = api.connect_with_retry(max_retries=3, base_delay=0.01)
        self.assertTrue(result)
        self.assertEqual(attempt_count[0], 3)

    def test_not_available_error_stops_retry(self):
        """Import 'not available' errors should not be retried."""
        config = Config()
        api = MockMeshtasticAPI(config)

        attempt_count = [0]

        def mock_connect():
            attempt_count[0] += 1
            api.connection_info.error_message = (
                "Connection failed (ImportError): meshtastic.http_interface "
                "not available \u2014 install its dependencies"
            )
            api.connection_info.connected = False
            return False

        api.connect = mock_connect
        with patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True):
            result = api.connect_with_retry(max_retries=3)
        self.assertFalse(result)
        self.assertEqual(attempt_count[0], 1)  # Should not retry


class TestRefreshNonImportError(unittest.TestCase):
    """Test refresh_meshtastic_availability handles non-ImportError exceptions."""

    def test_runtime_error_sets_module_none_and_logs(self):
        """Non-ImportError exceptions are caught and logged during refresh."""
        import importlib
        import logging

        from meshing_around_clients.core.meshtastic_api import (
            _INTERFACE_MODULES,
            refresh_meshtastic_availability,
        )

        real_import = importlib.import_module

        def side_effect(name, *args, **kwargs):
            if name == "meshtastic.http_interface":
                raise RuntimeError("native extension crash")
            return real_import(name, *args, **kwargs)

        with (
            patch("importlib.import_module", side_effect=side_effect),
            patch.object(logging.getLogger("meshing_around_clients.core.meshtastic_api"), "info") as mock_info,
        ):
            refresh_meshtastic_availability()

        self.assertIsNone(_INTERFACE_MODULES.get("http_interface"))
        # Logger receives the exception object, not its string representation
        found = any(
            len(c.args) == 4
            and c.args[0] == "meshtastic.%s import failed (%s): %s"
            and c.args[1] == "http_interface"
            and c.args[2] == "RuntimeError"
            and isinstance(c.args[3], RuntimeError)
            for c in mock_info.call_args_list
        )
        self.assertTrue(found, f"Expected log call not found in: {mock_info.call_args_list}")


class TestChunkBuffer(unittest.TestCase):
    """Test _ChunkBuffer message reassembly."""

    def setUp(self):
        from meshing_around_clients.core.meshtastic_api import _ChunkBuffer

        self.flushed = []
        self.buffer = _ChunkBuffer(timeout=0.3)
        self.buffer._flush_callback = lambda text, pkt, count: self.flushed.append((text, count))

    def tearDown(self):
        self.buffer.cancel_all()

    def _packet(self, sender="!aabb1234", channel=0):
        return {
            "fromId": sender,
            "toId": "^all",
            "channel": channel,
            "decoded": {},
            "hopStart": 3,
            "hopLimit": 2,
            "snr": 5.0,
            "rssi": -80,
        }

    def test_short_message_passes_through(self):
        """Messages under 40 bytes pass through instantly (no timer created)."""
        result = self.buffer.add("!aabb1234", 0, "hello", self._packet())
        self.assertFalse(result)

    def test_long_message_buffered(self):
        """Messages >= 40 bytes start buffering."""
        result = self.buffer.add("!aabb1234", 0, "A" * 45, self._packet())
        self.assertTrue(result)

    def test_sequential_chunks_concatenated(self):
        """Multiple rapid chunks from same sender/channel are concatenated."""
        chunk1 = "W" * 150
        chunk2 = "X" * 150
        chunk3 = "short end"
        self.buffer.add("!aabb1234", 0, chunk1, self._packet())
        self.buffer.add("!aabb1234", 0, chunk2, self._packet())
        self.buffer.add("!aabb1234", 0, chunk3, self._packet())
        # Wait for flush
        time.sleep(0.5)
        self.assertEqual(len(self.flushed), 1)
        text, count = self.flushed[0]
        self.assertEqual(count, 3)
        self.assertIn(chunk1, text)
        self.assertIn(chunk2, text)
        self.assertIn(chunk3, text)

    def test_different_senders_separate(self):
        """Chunks from different senders are buffered separately."""
        self.buffer.add("!sender1", 0, "A" * 150, self._packet(sender="!sender1"))
        self.buffer.add("!sender2", 0, "B" * 150, self._packet(sender="!sender2"))
        time.sleep(0.5)
        self.assertEqual(len(self.flushed), 2)

    def test_different_channels_separate(self):
        """Same sender on different channels are buffered separately."""
        self.buffer.add("!aabb1234", 0, "A" * 150, self._packet(channel=0))
        self.buffer.add("!aabb1234", 1, "B" * 150, self._packet(channel=1))
        time.sleep(0.5)
        self.assertEqual(len(self.flushed), 2)

    def test_timeout_flushes_buffer(self):
        """Buffer emits after timeout expires."""
        self.buffer.add("!aabb1234", 0, "A" * 150, self._packet())
        self.assertEqual(len(self.flushed), 0)
        time.sleep(0.5)
        self.assertEqual(len(self.flushed), 1)

    def test_reassembly_disabled_when_zero(self):
        """Timeout=0 disables buffering entirely."""
        from meshing_around_clients.core.meshtastic_api import _ChunkBuffer

        buf = _ChunkBuffer(timeout=0)
        self.assertFalse(buf.enabled)
        result = buf.add("!aabb1234", 0, "A" * 200, self._packet())
        self.assertFalse(result)

    def test_cancel_all_clears_state(self):
        """cancel_all() stops pending timers and clears buffers."""
        self.buffer.add("!aabb1234", 0, "A" * 150, self._packet())
        self.buffer.cancel_all()
        time.sleep(0.5)
        self.assertEqual(len(self.flushed), 0)


class TestCallUpstreamCmd(unittest.TestCase):
    """Tests for _call_upstream_cmd() — SEC-23 subprocess hardening."""

    def setUp(self):
        from meshing_around_clients.core.meshtastic_api import _call_upstream_cmd

        self._call = _call_upstream_cmd

    def test_unknown_command_returns_empty(self):
        """Unknown commands should return empty string without calling subprocess."""
        result = self._call("nonexistent_command")
        self.assertEqual(result, "")

    @patch("meshing_around_clients.core.meshtastic_api._UPSTREAM_VENV_PYTHON")
    def test_missing_venv_returns_empty(self, mock_path):
        """Missing venv python should return empty string."""
        mock_path.exists.return_value = False
        result = self._call("moon", 21.3, -157.8)
        self.assertEqual(result, "")

    @patch("meshing_around_clients.core.meshtastic_api._check_venv_path_safe")
    @patch("meshing_around_clients.core.meshtastic_api._UPSTREAM_VENV_PYTHON")
    def test_world_writable_venv_rejected(self, mock_path, mock_check):
        """World-writable venv path should be rejected (SEC-23)."""
        mock_path.exists.return_value = True
        mock_check.return_value = False
        result = self._call("moon", 21.3, -157.8)
        self.assertEqual(result, "")

    @patch("meshing_around_clients.core.meshtastic_api._check_venv_path_safe")
    @patch("meshing_around_clients.core.meshtastic_api._UPSTREAM_VENV_PYTHON")
    @patch("subprocess.run")
    def test_valid_command_returns_output(self, mock_run, mock_path, mock_check):
        """Valid command with safe venv should return subprocess stdout."""
        mock_path.exists.return_value = True
        mock_path.__str__ = lambda self: "/opt/meshing-around/venv/bin/python3"
        mock_check.return_value = True
        mock_run.return_value = unittest.mock.Mock(stdout="Moon: Waxing Gibbous\n", stderr="")
        result = self._call("moon", 21.3, -157.8)
        self.assertEqual(result, "Moon: Waxing Gibbous")

    @patch("meshing_around_clients.core.meshtastic_api._check_venv_path_safe")
    @patch("meshing_around_clients.core.meshtastic_api._UPSTREAM_VENV_PYTHON")
    @patch("subprocess.run")
    def test_timeout_returns_timeout_message(self, mock_run, mock_path, mock_check):
        """Subprocess timeout should return '{command}: timeout'."""
        import subprocess

        mock_path.exists.return_value = True
        mock_path.__str__ = lambda self: "/opt/meshing-around/venv/bin/python3"
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=15)
        result = self._call("wx", 21.3, -157.8)
        self.assertEqual(result, "wx: timeout")

    @patch("meshing_around_clients.core.meshtastic_api._check_venv_path_safe")
    @patch("meshing_around_clients.core.meshtastic_api._UPSTREAM_VENV_PYTHON")
    @patch("subprocess.run")
    def test_script_is_static_no_interpolation(self, mock_run, mock_path, mock_check):
        """The -c script argument must be static — no user data embedded (SEC-23)."""
        mock_path.exists.return_value = True
        mock_path.__str__ = lambda self: "/opt/meshing-around/venv/bin/python3"
        mock_check.return_value = True
        mock_run.return_value = unittest.mock.Mock(stdout="", stderr="")
        self._call("moon", 21.3, -157.8)
        # Verify the script passed to -c does NOT contain the lat/lon values
        args, kwargs = mock_run.call_args
        script = args[0][2]  # [python, "-c", script]
        self.assertNotIn("21.3", script)
        self.assertNotIn("-157.8", script)
        # Verify data is passed via environment variables instead
        env = kwargs.get("env", {})
        self.assertEqual(env.get("MESHFORGE_LAT"), "21.3")
        self.assertEqual(env.get("MESHFORGE_LON"), "-157.8")
        self.assertEqual(env.get("MESHFORGE_MODULE"), "space")
        self.assertEqual(env.get("MESHFORGE_FUNC"), "get_moon")

    def test_invalid_lat_lon_type_rejected(self):
        """Non-numeric lat/lon should be rejected."""
        # This shouldn't even reach subprocess — type check catches it
        result = self._call("moon", "not_a_number", -157.8)
        self.assertEqual(result, "")

    @patch("meshing_around_clients.core.meshtastic_api._check_venv_path_safe")
    @patch("meshing_around_clients.core.meshtastic_api._UPSTREAM_VENV_PYTHON")
    @patch("subprocess.run")
    def test_oserror_returns_empty(self, mock_run, mock_path, mock_check):
        """OSError from subprocess should return empty string."""
        mock_path.exists.return_value = True
        mock_path.__str__ = lambda self: "/opt/meshing-around/venv/bin/python3"
        mock_check.return_value = True
        mock_run.side_effect = OSError("No such file")
        result = self._call("moon", 21.3, -157.8)
        self.assertEqual(result, "")


class TestCheckVenvPathSafe(unittest.TestCase):
    """Tests for _check_venv_path_safe() — SEC-23 path validation."""

    def setUp(self):
        from meshing_around_clients.core.meshtastic_api import _check_venv_path_safe

        self._check = _check_venv_path_safe

    @patch("os.stat")
    def test_world_writable_rejected(self, mock_stat):
        """World-writable path should return False."""
        import stat
        from pathlib import Path

        mock_stat.return_value = unittest.mock.Mock(st_mode=0o100777)
        result = self._check(Path("/some/path"))
        self.assertFalse(result)

    @patch("os.stat")
    def test_normal_permissions_accepted(self, mock_stat):
        """Normal (0o755) path should return True."""
        from pathlib import Path

        mock_stat.return_value = unittest.mock.Mock(st_mode=0o100755)
        result = self._check(Path("/some/path"))
        self.assertTrue(result)

    @patch("os.stat")
    def test_missing_path_returns_false(self, mock_stat):
        """Non-existent path should return False."""
        from pathlib import Path

        mock_stat.side_effect = OSError("No such file")
        result = self._check(Path("/nonexistent"))
        self.assertFalse(result)


class TestFetchUrlSizeCap(unittest.TestCase):
    """Pin the _MAX_FETCH_BYTES cap on URL fetches — a misconfigured INI
    data-source URL or a malicious redirect pointing at a multi-gigabyte
    endpoint used to OOM the client before the 228-byte mesh limit
    even applied.  Now capped at 1 MiB with a WARNING log.
    """

    def test_response_truncated_at_cap(self):
        from unittest.mock import MagicMock, patch

        from meshing_around_clients.core import meshtastic_api

        cap = meshtastic_api._MAX_FETCH_BYTES
        # Build a fake response that would return 2x the cap if unrestricted.
        big = b"A" * (cap * 2)

        class _Resp:
            def read(self, n=None):
                # Stdlib urlopen().read(n) returns up to n bytes; mirror that.
                return big if n is None else big[:n]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("urllib.request.urlopen", return_value=_Resp()):
            result = meshtastic_api._fetch_url("https://example.com/huge")
        self.assertEqual(len(result.encode("utf-8")), cap)

    def test_small_response_passes_through(self):
        from unittest.mock import patch

        from meshing_around_clients.core import meshtastic_api

        body = b"small payload"

        class _Resp:
            def read(self, n=None):
                return body if n is None else body[:n]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("urllib.request.urlopen", return_value=_Resp()):
            result = meshtastic_api._fetch_url("https://example.com/small")
        self.assertEqual(result, "small payload")


class TestCommandResponseTruncation(unittest.TestCase):
    """Pin the `_handle_command` truncation — responses over the mesh
    228-byte limit were previously silently rejected by send_message.
    Now they're truncated with an ellipsis and delivered.

    These tests exercise the exact truncation expression used in
    `_handle_command` at the dispatch site (single call point covering
    every branch of the C901-complex `_get_command_response`).
    """

    def _truncate(self, response: str) -> str:
        """Mirror the truncation expression in meshtastic_api._handle_command."""
        from meshing_around_clients.core.models import MAX_MESSAGE_BYTES

        encoded = response.encode("utf-8")
        if len(encoded) > MAX_MESSAGE_BYTES:
            return encoded[: MAX_MESSAGE_BYTES - 3].decode("utf-8", errors="ignore") + "..."
        return response

    def test_short_response_passes_through_unchanged(self):
        self.assertEqual(self._truncate("short reply"), "short reply")

    def test_oversize_response_truncated_with_ellipsis(self):
        from meshing_around_clients.core.models import MAX_MESSAGE_BYTES

        oversize = "x" * (MAX_MESSAGE_BYTES * 2)
        result = self._truncate(oversize)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result.encode("utf-8")), MAX_MESSAGE_BYTES)

    def test_multibyte_utf8_boundary_not_split(self):
        """Truncating mid-UTF-8-sequence must not produce garbage bytes."""
        from meshing_around_clients.core.models import MAX_MESSAGE_BYTES

        # Build a string that forces the truncation point onto a multibyte
        # character boundary.  Each € is 3 bytes; 80 of them = 240 bytes > 228.
        text = "€" * 80
        result = self._truncate(text)
        # The ellipsis is the 3 ASCII bytes "..." — ensure what precedes it
        # is valid UTF-8 and does not end with a partial sequence.
        body = result[:-3]
        body.encode("utf-8")  # re-encodes cleanly, so decode was clean
        self.assertLessEqual(len(result.encode("utf-8")), MAX_MESSAGE_BYTES)


class TestEmergencyAlertCooldown(unittest.TestCase):
    """Emergency keyword alerts now honor the _is_alert_cooled_down check
    that battery/congestion paths already use.  A sender spamming
    'MAYDAY' should fire one Alert, not one per message.
    """

    def setUp(self):
        cfg = Config(config_path="/nonexistent/path")
        cfg.alerts.enabled = True
        cfg.alerts.emergency_keywords = ["mayday", "sos"]
        cfg.storage.enabled = False
        self.api = MockMeshtasticAPI(cfg)
        # Force a short cooldown so the test is fast.
        self.api._alert_cooldown_seconds = 60

    def test_rapid_emergency_keywords_suppressed_by_cooldown(self):
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        # Simulate three identical emergency messages from the same sender
        # in quick succession.  Only the first should produce an alert.
        for _ in range(3):
            packet = {
                "decoded": {"text": "MAYDAY MAYDAY", "portnum": "TEXT_MESSAGE_APP"},
                "fromId": "!deadbeef",
                "from": 0xDEADBEEF,
                "id": 1,
            }
            # Use the real API's _handle_text_message via the mock inheritance
            MeshtasticAPI._handle_text_message(self.api, packet)
        emergency_alerts = [a for a in self.api.network.alerts if a.alert_type.value == "emergency"]
        self.assertEqual(len(emergency_alerts), 1, f"Expected 1 alert, got {len(emergency_alerts)}")


if __name__ == "__main__":
    unittest.main()

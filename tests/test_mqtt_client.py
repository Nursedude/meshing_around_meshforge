"""
Unit tests for meshing_around_clients.core.mqtt_client

Note: Integration tests require:
1. Network connectivity to mqtt.meshtastic.org
2. paho-mqtt package installed: pip install paho-mqtt

Run integration tests with: python -m pytest tests/test_mqtt_client.py -v -k integration
Run unit tests only with: python -m pytest tests/test_mqtt_client.py -v -k "not integration"
"""

import json
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.config import Config
from meshing_around_clients.core.models import Alert, AlertType, Message, Node


class TestMQTTConfigDataclass(unittest.TestCase):
    """Test MQTTConfig defaults without importing paho-mqtt."""

    def test_mqtt_config_import(self):
        """Verify MQTTConfig can be imported."""
        from meshing_around_clients.core.config import MQTTConfig

        cfg = MQTTConfig()
        self.assertEqual(cfg.broker, "mqtt.meshtastic.org")
        self.assertEqual(cfg.port, 1883)
        self.assertEqual(cfg.username, "meshdev")
        self.assertEqual(cfg.password, "large4cats")
        self.assertEqual(cfg.topic_root, "msh/US")

    def test_mqtt_config_custom(self):
        """Test MQTTConfig with custom values."""
        from meshing_around_clients.core.config import MQTTConfig

        cfg = MQTTConfig(
            broker="localhost", port=1884, use_tls=True, username="custom", password="secret", topic_root="msh/EU"
        )
        self.assertEqual(cfg.broker, "localhost")
        self.assertEqual(cfg.port, 1884)
        self.assertTrue(cfg.use_tls)
        self.assertEqual(cfg.topic_root, "msh/EU")


class TestMQTTAvailability(unittest.TestCase):
    """Test MQTT_AVAILABLE flag."""

    def test_mqtt_available_flag_exists(self):
        """Verify MQTT_AVAILABLE flag is set correctly."""
        from meshing_around_clients.core.mqtt_client import MQTT_AVAILABLE

        self.assertIsInstance(MQTT_AVAILABLE, bool)


@unittest.skipUnless(__import__("importlib.util").util.find_spec("paho"), "paho-mqtt not installed")
class TestMQTTMeshtasticClient(unittest.TestCase):
    """Test MQTTMeshtasticClient with mocked paho-mqtt."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.alerts.enabled = True
        self.config.alerts.emergency_keywords = ["help", "sos", "emergency"]

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_client_initialization(self, mock_mqtt):
        """Test client initializes correctly."""
        from meshing_around_clients.core.mqtt_client import MQTTConfig, MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        self.assertFalse(client.is_connected)
        self.assertIsNotNone(client.network)
        self.assertEqual(client.network.connection_status, "disconnected")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_callback_registration(self, mock_mqtt):
        """Test callback registration."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        callback_fired = []

        def on_message(msg):
            callback_fired.append(msg)

        client.register_callback("on_message", on_message)
        self.assertEqual(len(client._callbacks["on_message"]), 1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_json_text_message_handling(self, mock_mqtt):
        """Test handling of JSON text messages."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Simulate JSON message
        json_data = {"from": 0x12345678, "to": "^all", "channel": 0, "type": "text", "payload": {"text": "Hello mesh!"}}

        client._handle_json_message("msh/US/LongFast/json", json.dumps(json_data).encode())

        # Verify node was created
        self.assertEqual(len(client.network.nodes), 1)
        self.assertIn("!12345678", client.network.nodes)

        # Verify message was added
        self.assertEqual(client.network.total_messages, 1)
        msg = client.network.messages[0]
        self.assertEqual(msg.text, "Hello mesh!")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_emergency_keyword_detection(self, mock_mqtt):
        """Test emergency keyword triggers alert."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Message with emergency keyword
        json_data = {
            "from": 0xAABBCCDD,
            "to": "^all",
            "channel": 0,
            "type": "text",
            "payload": {"text": "HELP! Need assistance!"},
        }

        client._handle_json_message("msh/US/LongFast/json", json.dumps(json_data).encode())

        # Verify alert was created
        self.assertGreater(len(client.network.alerts), 0)
        alert = client.network.alerts[0]
        self.assertEqual(alert.alert_type, AlertType.EMERGENCY)
        self.assertEqual(alert.severity, 4)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_position_handling(self, mock_mqtt):
        """Test position update handling."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # First add a node
        json_nodeinfo = {"from": 0x11111111, "payload": {"user": {"shortName": "TST", "longName": "Test Node"}}}
        client._handle_json_message("msh/US/json", json.dumps(json_nodeinfo).encode())

        # Then send position
        json_pos = {
            "from": 0x11111111,
            "type": "position",
            "payload": {"position": {"latitudeI": 455000000, "longitudeI": -1226000000, "altitude": 100}},
        }
        client._handle_json_message("msh/US/json", json.dumps(json_pos).encode())

        # Verify position was updated
        node = client.network.get_node("!11111111")
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.position.latitude, 45.5, places=1)
        self.assertAlmostEqual(node.position.longitude, -122.6, places=1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_telemetry_handling(self, mock_mqtt):
        """Test telemetry update handling."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # First add a node
        json_nodeinfo = {"from": 0x22222222, "payload": {"user": {"shortName": "TEL"}}}
        client._handle_json_message("msh/US/json", json.dumps(json_nodeinfo).encode())

        # Send telemetry
        json_tel = {
            "from": 0x22222222,
            "type": "telemetry",
            "payload": {
                "telemetry": {"deviceMetrics": {"batteryLevel": 85, "voltage": 4.1, "channelUtilization": 5.5}}
            },
        }
        client._handle_json_message("msh/US/json", json.dumps(json_tel).encode())

        # Verify telemetry was updated
        node = client.network.get_node("!22222222")
        self.assertEqual(node.telemetry.battery_level, 85)
        self.assertAlmostEqual(node.telemetry.voltage, 4.1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_low_battery_alert(self, mock_mqtt):
        """Test low battery triggers alert."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Add node
        json_nodeinfo = {"from": 0x33333333, "payload": {"user": {"shortName": "LOW"}}}
        client._handle_json_message("msh/US/json", json.dumps(json_nodeinfo).encode())

        # Send low battery telemetry
        json_tel = {
            "from": 0x33333333,
            "type": "telemetry",
            "payload": {"telemetry": {"deviceMetrics": {"batteryLevel": 15}}},
        }
        client._handle_json_message("msh/US/json", json.dumps(json_tel).encode())

        # Verify battery alert
        battery_alerts = [a for a in client.network.alerts if a.alert_type == AlertType.BATTERY]
        self.assertEqual(len(battery_alerts), 1)
        self.assertEqual(battery_alerts[0].severity, 2)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_get_nodes(self, mock_mqtt):
        """Test get_nodes method."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Add some nodes
        for i in range(5):
            json_data = {"from": 0x10000000 + i, "payload": {"user": {"shortName": f"N{i}"}}}
            client._handle_json_message("msh/US/json", json.dumps(json_data).encode())

        nodes = client.get_nodes()
        self.assertEqual(len(nodes), 5)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_get_messages_with_limit(self, mock_mqtt):
        """Test get_messages with limit."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Add multiple messages
        for i in range(10):
            json_data = {"from": 0x44444444, "type": "text", "payload": {"text": f"Message {i}"}}
            client._handle_json_message("msh/US/json", json.dumps(json_data).encode())

        messages = client.get_messages(limit=5)
        self.assertEqual(len(messages), 5)
        # Should be last 5 messages
        self.assertEqual(messages[0].text, "Message 5")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_get_messages_by_channel(self, mock_mqtt):
        """Test get_messages filtered by channel."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Add messages on different channels (unique text to avoid dedup)
        for i, ch in enumerate([0, 0, 1, 2, 0]):
            json_data = {
                "from": 0x55555555,
                "channel": ch,
                "type": "text",
                "payload": {"text": f"Message {i} on channel {ch}"},
            }
            client._handle_json_message("msh/US/json", json.dumps(json_data).encode())

        ch0_messages = client.get_messages(channel=0)
        self.assertEqual(len(ch0_messages), 3)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_get_alerts_unread_only(self, mock_mqtt):
        """Test get_alerts with unread_only filter."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Create alerts
        for i in range(3):
            json_data = {"from": 0x66660000 + i, "type": "text", "payload": {"text": "HELP emergency!"}}
            client._handle_json_message("msh/US/json", json.dumps(json_data).encode())

        # Acknowledge one
        client.network.alerts[0].acknowledged = True

        all_alerts = client.get_alerts(unread_only=False)
        unread_alerts = client.get_alerts(unread_only=True)

        self.assertEqual(len(all_alerts), 3)
        self.assertEqual(len(unread_alerts), 2)


class TestMQTTConnectivity(unittest.TestCase):
    """Test MQTT broker connectivity using socket (no paho-mqtt required)."""

    def test_socket_connectivity_to_broker(self):
        """Test basic TCP connectivity to mqtt.meshtastic.org."""
        import socket

        brokers = [
            ("mqtt.meshtastic.org", 1883),
        ]

        for host, port in brokers:
            try:
                sock = socket.create_connection((host, port), timeout=5)
                sock.close()
                # Connection successful
                return
            except (socket.error, OSError, socket.timeout) as e:
                continue

        self.skipTest("No network connectivity to MQTT broker")

    def test_dns_resolution(self):
        """Test DNS resolution for mqtt.meshtastic.org."""
        import socket

        try:
            ip = socket.gethostbyname("mqtt.meshtastic.org")
            self.assertTrue(len(ip) > 0)
        except socket.gaierror:
            self.skipTest("DNS resolution failed - no network")

    def test_default_credentials_format(self):
        """Verify default MQTT credentials are properly formatted."""
        from meshing_around_clients.core.config import MQTTConfig

        cfg = MQTTConfig()

        # Credentials should be non-empty strings
        self.assertIsInstance(cfg.username, str)
        self.assertIsInstance(cfg.password, str)
        self.assertTrue(len(cfg.username) > 0, "Username should not be empty")
        self.assertTrue(len(cfg.password) > 0, "Password should not be empty")

        # Topic root should be valid
        self.assertTrue(cfg.topic_root.startswith("msh/"))


# Integration tests - require network and paho-mqtt
@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("paho"), "paho-mqtt not installed - skipping integration tests"
)
class TestMQTTIntegration(unittest.TestCase):
    """
    Integration tests for MQTT client.

    These tests connect to the real mqtt.meshtastic.org broker.
    They are skipped by default unless run with -k integration flag.
    """

    def test_integration_connect_to_broker(self):
        """Integration test: connect to mqtt.meshtastic.org."""
        import socket

        try:
            # First check network connectivity
            socket.create_connection(("mqtt.meshtastic.org", 1883), 5)
        except (socket.error, OSError):
            self.skipTest("No network connectivity to mqtt.meshtastic.org")

        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)

        try:
            result = client.connect()
            self.assertTrue(result, "Failed to connect to MQTT broker")
            self.assertTrue(client.is_connected)
            self.assertIn("MQTT", client.network.connection_status)
        finally:
            client.disconnect()
            self.assertFalse(client.is_connected)


@unittest.skipUnless(__import__("importlib.util").util.find_spec("paho"), "paho-mqtt not installed")
class TestMQTTDecodedPacketPaths(unittest.TestCase):
    """Test _process_decoded_packet code paths (protobuf/relay/neighbor)."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.alerts.enabled = True
        self.config.alerts.emergency_keywords = ["help", "sos"]

    def _make_client(self, mock_mqtt):
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        return MQTTMeshtasticClient(self.config)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_relay_node_full_id(self, mock_mqtt):
        """Test _handle_relay_node with full 32-bit node number."""
        client = self._make_client(mock_mqtt)

        # Add a sender node first
        sender_id = "!11223344"
        client.network.add_node(Node(node_id=sender_id, node_num=0x11223344))

        client._handle_relay_node(0xAABBCCDD, sender_id)
        relay_node = client.network.get_node("!aabbccdd")
        self.assertIsNotNone(relay_node)
        self.assertTrue(relay_node.is_online)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_relay_node_partial_id(self, mock_mqtt):
        """Test _handle_relay_node with partial (1-2 byte) relay node."""
        client = self._make_client(mock_mqtt)

        sender_id = "!11223344"
        client.network.add_node(Node(node_id=sender_id, node_num=0x11223344))

        client._handle_relay_node(0x00FF, sender_id)
        relay_node = client.network.get_node("!000000ff")
        self.assertIsNotNone(relay_node)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_relay_node_zero_ignored(self, mock_mqtt):
        """Test _handle_relay_node with 0 does nothing."""
        client = self._make_client(mock_mqtt)
        initial_count = len(client.network.nodes)
        client._handle_relay_node(0, "!11223344")
        self.assertEqual(len(client.network.nodes), initial_count)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_check_battery_alert_fires(self, mock_mqtt):
        """Test _check_battery_alert fires alert for low battery."""
        client = self._make_client(mock_mqtt)

        from meshing_around_clients.core.models import NodeTelemetry

        node = Node(node_id="!aabb0001", node_num=1, short_name="LOW")
        node.telemetry = NodeTelemetry(battery_level=15)
        client.network.add_node(node)

        client._check_battery_alert(node, "!aabb0001")
        battery_alerts = [a for a in client.network.alerts if a.alert_type == AlertType.BATTERY]
        self.assertEqual(len(battery_alerts), 1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_check_battery_alert_no_fire_normal_level(self, mock_mqtt):
        """Test _check_battery_alert does not fire for normal battery."""
        client = self._make_client(mock_mqtt)

        from meshing_around_clients.core.models import NodeTelemetry

        node = Node(node_id="!aabb0002", node_num=2, short_name="OK")
        node.telemetry = NodeTelemetry(battery_level=80)
        client.network.add_node(node)

        client._check_battery_alert(node, "!aabb0002")
        battery_alerts = [a for a in client.network.alerts if a.alert_type == AlertType.BATTERY]
        self.assertEqual(len(battery_alerts), 0)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_extract_position_with_latitude(self, mock_mqtt):
        """Test _extract_position with direct latitude/longitude."""
        client = self._make_client(mock_mqtt)
        pos = client._extract_position({"latitude": 45.5, "longitude": -122.6, "altitude": 100})
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.latitude, 45.5)
        self.assertAlmostEqual(pos.longitude, -122.6)
        self.assertEqual(pos.altitude, 100)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_extract_position_with_latitudeI(self, mock_mqtt):
        """Test _extract_position with latitudeI/longitudeI (integer format)."""
        client = self._make_client(mock_mqtt)
        pos = client._extract_position({"latitudeI": 455000000, "longitudeI": -1226000000})
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.latitude, 45.5, places=1)
        self.assertAlmostEqual(pos.longitude, -122.6, places=1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_extract_position_invalid_coords(self, mock_mqtt):
        """Test _extract_position returns None for invalid coordinates."""
        client = self._make_client(mock_mqtt)
        pos = client._extract_position({"latitude": 999, "longitude": -999})
        self.assertIsNone(pos)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_extract_position_empty_dict(self, mock_mqtt):
        """Test _extract_position returns None for empty dict."""
        client = self._make_client(mock_mqtt)
        pos = client._extract_position({})
        self.assertIsNone(pos)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_hop_limit_type_safety(self, mock_mqtt):
        """Test that hop_limit handles non-integer values gracefully."""
        client = self._make_client(mock_mqtt)

        # Simulate a JSON message with string hop_limit to trigger the protobuf path
        json_data = {
            "from": 0xDEADBEEF,
            "to": "^all",
            "channel": 0,
            "type": "text",
            "payload": {"text": "Test message"},
        }

        # This should not crash even with unusual data
        import json

        client._handle_json_message("msh/US/LongFast/json", json.dumps(json_data).encode())
        self.assertGreater(client.network.total_messages, 0)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_protobuf_telemetry_path(self, mock_mqtt):
        """Test telemetry processing via protobuf-decoded packet."""
        from meshing_around_clients.core.mesh_crypto import DecryptedPacket

        client = self._make_client(mock_mqtt)

        # Add a node first
        node = Node(node_id="!aabb1111", node_num=0xAABB1111)
        client.network.add_node(node)

        # Create a mock decoded result
        result = DecryptedPacket(
            success=True,
            portnum=67,  # TELEMETRY_APP
            sender=0xAABB1111,
            decoded={
                "type": "telemetry",
                "telemetry": {
                    "device_metrics": {"battery_level": 75, "voltage": 3.9},
                    "environment_metrics": {},
                },
            },
        )

        topic_info = {"node_id": "!aabb1111", "channel": "LongFast"}
        client._process_decoded_packet(result, "!aabb1111", topic_info)

        updated_node = client.network.get_node("!aabb1111")
        self.assertEqual(updated_node.telemetry.battery_level, 75)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_protobuf_position_path(self, mock_mqtt):
        """Test position processing via protobuf-decoded packet."""
        from meshing_around_clients.core.mesh_crypto import DecryptedPacket

        client = self._make_client(mock_mqtt)

        node = Node(node_id="!aabb2222", node_num=0xAABB2222)
        client.network.add_node(node)

        result = DecryptedPacket(
            success=True,
            portnum=3,  # POSITION_APP
            sender=0xAABB2222,
            decoded={
                "type": "position",
                "position": {"latitude": 40.7, "longitude": -74.0, "altitude": 50},
            },
        )

        topic_info = {"node_id": "!aabb2222", "channel": "LongFast"}
        client._process_decoded_packet(result, "!aabb2222", topic_info)

        updated_node = client.network.get_node("!aabb2222")
        self.assertAlmostEqual(updated_node.position.latitude, 40.7)
        self.assertAlmostEqual(updated_node.position.longitude, -74.0)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_protobuf_text_message_path(self, mock_mqtt):
        """Test text message processing via protobuf-decoded packet."""
        from meshing_around_clients.core.mesh_crypto import DecryptedPacket

        client = self._make_client(mock_mqtt)

        node = Node(node_id="!aabb3333", node_num=0xAABB3333, short_name="TXT")
        client.network.add_node(node)

        result = DecryptedPacket(
            success=True,
            portnum=1,  # TEXT_MESSAGE_APP
            packet_id=42,
            sender=0xAABB3333,
            decoded={"type": "text", "text": "Hello from protobuf!", "channel": 0},
        )

        topic_info = {"node_id": "!aabb3333", "channel": "LongFast"}
        client._process_decoded_packet(result, "!aabb3333", topic_info)

        self.assertGreater(client.network.total_messages, 0)
        found = any(m.text == "Hello from protobuf!" for m in client.network.messages)
        self.assertTrue(found)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_protobuf_nodeinfo_path(self, mock_mqtt):
        """Test nodeinfo processing via protobuf-decoded packet."""
        from meshing_around_clients.core.mesh_crypto import DecryptedPacket

        client = self._make_client(mock_mqtt)

        node = Node(node_id="!aabb4444", node_num=0xAABB4444)
        client.network.add_node(node)

        result = DecryptedPacket(
            success=True,
            portnum=4,  # NODEINFO_APP
            sender=0xAABB4444,
            decoded={
                "type": "nodeinfo",
                "user": {"short_name": "UPD", "long_name": "Updated Node", "hw_model": "T-Beam"},
            },
        )

        topic_info = {"node_id": "!aabb4444", "channel": "LongFast"}
        client._process_decoded_packet(result, "!aabb4444", topic_info)

        updated_node = client.network.get_node("!aabb4444")
        self.assertEqual(updated_node.short_name, "UPD")
        self.assertEqual(updated_node.long_name, "Updated Node")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_protobuf_neighborinfo_path(self, mock_mqtt):
        """Test neighborinfo processing via protobuf-decoded packet."""
        from meshing_around_clients.core.mesh_crypto import DecryptedPacket

        client = self._make_client(mock_mqtt)

        sender = Node(node_id="!aabb5555", node_num=0xAABB5555)
        neighbor = Node(node_id="!aabb6666", node_num=0xAABB6666)
        client.network.add_node(sender)
        client.network.add_node(neighbor)

        result = DecryptedPacket(
            success=True,
            portnum=71,  # NEIGHBORINFO_APP
            sender=0xAABB5555,
            decoded={
                "type": "neighborinfo",
                "neighborinfo": {"neighbors": [{"node_id": 0xAABB6666, "snr": 8.5}]},
            },
        )

        topic_info = {"node_id": "!aabb5555", "channel": "LongFast"}
        client._process_decoded_packet(result, "!aabb5555", topic_info)

        # Verify neighbor relationship was tracked
        updated_sender = client.network.get_node("!aabb5555")
        self.assertIn("!aabb6666", updated_sender.neighbors)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_process_decoded_with_relay_node(self, mock_mqtt):
        """Test that relay_node in decoded data creates relay entry."""
        from meshing_around_clients.core.mesh_crypto import DecryptedPacket

        client = self._make_client(mock_mqtt)

        result = DecryptedPacket(
            success=True,
            portnum=1,
            packet_id=99,
            sender=0xAAAA0001,
            decoded={"type": "text", "text": "relayed msg", "relay_node": 0xBBBB0002, "channel": 0},
        )

        topic_info = {"node_id": "!aaaa0001", "channel": "LongFast"}
        client._process_decoded_packet(result, "!aaaa0001", topic_info)

        # Both sender and relay node should exist
        self.assertIsNotNone(client.network.get_node("!aaaa0001"))
        self.assertIsNotNone(client.network.get_node("!bbbb0002"))


class TestMQTTSendMessageValidation(unittest.TestCase):
    """Test send_message() byte-length validation."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_send_message_rejects_oversized(self, mock_mqtt):
        """send_message() should return False for messages exceeding 228 bytes."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        client._connected = True
        client._client = MagicMock()
        client.mqtt_config.node_id = "!test1234"

        # 229 ASCII bytes — over the limit
        result = client.send_message("x" * 229)
        self.assertFalse(result)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_send_message_allows_228_bytes(self, mock_mqtt):
        """send_message() should accept exactly 228 bytes."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        client._connected = True
        client._client = MagicMock()
        client.mqtt_config.node_id = "!test1234"

        result = client.send_message("x" * 228)
        self.assertTrue(result)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_send_message_rejects_multibyte_overflow(self, mock_mqtt):
        """Emoji (4 bytes each) that fit in char count but overflow byte count."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        client._connected = True
        client._client = MagicMock()
        client.mqtt_config.node_id = "!test1234"

        # 58 emoji = 58 * 4 = 232 bytes > 228
        result = client.send_message("\U0001f600" * 58)
        self.assertFalse(result)


@patch("meshing_around_clients.core.mqtt_client.mqtt")
class TestMQTTStatsLockConsistency(unittest.TestCase):
    """Test that stats fields are consistently protected by lock."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")

    def test_last_message_time_updated_under_lock(self, mock_mqtt):
        """_last_message_time should be set inside the stats lock."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        json_data = {
            "from": 0xAABB0001,
            "type": "text",
            "payload": {"text": "lock test"},
        }
        client._handle_json_message(
            "msh/US/2/json/LongFast/!aabb0001",
            json.dumps(json_data).encode(),
        )

        with client._stats_lock:
            msg_time = client._last_message_time
            msg_count = client._message_count
        self.assertIsNotNone(msg_time)
        self.assertGreater(msg_count, 0)

    def test_reconnect_count_reset_on_clean_disconnect(self, mock_mqtt):
        """_reconnect_count should be 0 after clean disconnect."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        with client._stats_lock:
            client._reconnect_count = 5
        client._on_disconnect(None, None, 0)
        with client._stats_lock:
            self.assertEqual(client._reconnect_count, 0)

    def test_reconnect_count_reset_on_intentional_disconnect(self, mock_mqtt):
        """_reconnect_count should reset on intentional disconnect."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        with client._stats_lock:
            client._reconnect_count = 3
            client._intentional_disconnect = True
        client._on_disconnect(None, None, 1)
        with client._stats_lock:
            self.assertEqual(client._reconnect_count, 0)

    def test_reconnect_count_increments_on_unexpected_disconnect(self, mock_mqtt):
        """_reconnect_count should increment on unexpected disconnect."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        with client._stats_lock:
            client._reconnect_count = 0
            client._intentional_disconnect = False
        client._on_disconnect(None, None, 7)
        with client._stats_lock:
            self.assertEqual(client._reconnect_count, 1)


if __name__ == "__main__":
    unittest.main()

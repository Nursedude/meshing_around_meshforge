"""
Unit tests for meshing_around_clients.core.mqtt_client

Note: Integration tests require:
1. Network connectivity to mqtt.meshtastic.org
2. paho-mqtt package installed: pip install paho-mqtt

Run integration tests with: python -m pytest tests/test_mqtt_client.py -v -k integration
Run unit tests only with: python -m pytest tests/test_mqtt_client.py -v -k "not integration"
"""

import unittest
from unittest.mock import patch, MagicMock
import json
from datetime import datetime

import sys
sys.path.insert(0, str(__file__).rsplit('/tests/', 1)[0])

from meshing_around_clients.core.config import Config
from meshing_around_clients.core.models import Node, Message, Alert, AlertType


class TestMQTTConfigDataclass(unittest.TestCase):
    """Test MQTTConfig defaults without importing paho-mqtt."""

    def test_mqtt_config_import(self):
        """Verify MQTTConfig can be imported."""
        from meshing_around_clients.core.mqtt_client import MQTTConfig
        cfg = MQTTConfig()
        self.assertEqual(cfg.broker, "mqtt.meshtastic.org")
        self.assertEqual(cfg.port, 1883)
        self.assertEqual(cfg.username, "meshdev")
        self.assertEqual(cfg.password, "large4cats")
        self.assertEqual(cfg.topic_root, "msh/US")

    def test_mqtt_config_custom(self):
        """Test MQTTConfig with custom values."""
        from meshing_around_clients.core.mqtt_client import MQTTConfig
        cfg = MQTTConfig(
            broker="localhost",
            port=1884,
            use_tls=True,
            username="custom",
            password="secret",
            topic_root="msh/EU"
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


@unittest.skipUnless(
    __import__('importlib.util').util.find_spec('paho'),
    "paho-mqtt not installed"
)
class TestMQTTMeshtasticClient(unittest.TestCase):
    """Test MQTTMeshtasticClient with mocked paho-mqtt."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.alerts.enabled = True
        self.config.alerts.emergency_keywords = ["help", "sos", "emergency"]

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
    def test_client_initialization(self, mock_mqtt):
        """Test client initializes correctly."""
        from meshing_around_clients.core.mqtt_client import (
            MQTTMeshtasticClient, MQTTConfig
        )

        client = MQTTMeshtasticClient(self.config)
        self.assertFalse(client.is_connected)
        self.assertIsNotNone(client.network)
        self.assertEqual(client.network.connection_status, "disconnected")

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
    def test_callback_registration(self, mock_mqtt):
        """Test callback registration."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        callback_fired = []

        def on_message(msg):
            callback_fired.append(msg)

        client.register_callback("on_message", on_message)
        self.assertEqual(len(client._callbacks["on_message"]), 1)

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
    def test_json_text_message_handling(self, mock_mqtt):
        """Test handling of JSON text messages."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Simulate JSON message
        json_data = {
            "from": 0x12345678,
            "to": "^all",
            "channel": 0,
            "type": "text",
            "payload": {"text": "Hello mesh!"}
        }

        client._handle_json_message("msh/US/LongFast/json", json.dumps(json_data).encode())

        # Verify node was created
        self.assertEqual(len(client.network.nodes), 1)
        self.assertIn("!12345678", client.network.nodes)

        # Verify message was added
        self.assertEqual(client.network.total_messages, 1)
        msg = client.network.messages[0]
        self.assertEqual(msg.text, "Hello mesh!")

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
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
            "payload": {"text": "HELP! Need assistance!"}
        }

        client._handle_json_message("msh/US/LongFast/json", json.dumps(json_data).encode())

        # Verify alert was created
        self.assertGreater(len(client.network.alerts), 0)
        alert = client.network.alerts[0]
        self.assertEqual(alert.alert_type, AlertType.EMERGENCY)
        self.assertEqual(alert.severity, 4)

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
    def test_position_handling(self, mock_mqtt):
        """Test position update handling."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # First add a node
        json_nodeinfo = {
            "from": 0x11111111,
            "payload": {"user": {"shortName": "TST", "longName": "Test Node"}}
        }
        client._handle_json_message("msh/US/json", json.dumps(json_nodeinfo).encode())

        # Then send position
        json_pos = {
            "from": 0x11111111,
            "type": "position",
            "payload": {
                "position": {
                    "latitudeI": 455000000,
                    "longitudeI": -1226000000,
                    "altitude": 100
                }
            }
        }
        client._handle_json_message("msh/US/json", json.dumps(json_pos).encode())

        # Verify position was updated
        node = client.network.get_node("!11111111")
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.position.latitude, 45.5, places=1)
        self.assertAlmostEqual(node.position.longitude, -122.6, places=1)

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
    def test_telemetry_handling(self, mock_mqtt):
        """Test telemetry update handling."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # First add a node
        json_nodeinfo = {
            "from": 0x22222222,
            "payload": {"user": {"shortName": "TEL"}}
        }
        client._handle_json_message("msh/US/json", json.dumps(json_nodeinfo).encode())

        # Send telemetry
        json_tel = {
            "from": 0x22222222,
            "type": "telemetry",
            "payload": {
                "telemetry": {
                    "deviceMetrics": {
                        "batteryLevel": 85,
                        "voltage": 4.1,
                        "channelUtilization": 5.5
                    }
                }
            }
        }
        client._handle_json_message("msh/US/json", json.dumps(json_tel).encode())

        # Verify telemetry was updated
        node = client.network.get_node("!22222222")
        self.assertEqual(node.telemetry.battery_level, 85)
        self.assertAlmostEqual(node.telemetry.voltage, 4.1)

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
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
            "payload": {"telemetry": {"deviceMetrics": {"batteryLevel": 15}}}
        }
        client._handle_json_message("msh/US/json", json.dumps(json_tel).encode())

        # Verify battery alert
        battery_alerts = [a for a in client.network.alerts if a.alert_type == AlertType.BATTERY]
        self.assertEqual(len(battery_alerts), 1)
        self.assertEqual(battery_alerts[0].severity, 2)

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
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

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
    def test_get_messages_with_limit(self, mock_mqtt):
        """Test get_messages with limit."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Add multiple messages
        for i in range(10):
            json_data = {
                "from": 0x44444444,
                "type": "text",
                "payload": {"text": f"Message {i}"}
            }
            client._handle_json_message("msh/US/json", json.dumps(json_data).encode())

        messages = client.get_messages(limit=5)
        self.assertEqual(len(messages), 5)
        # Should be last 5 messages
        self.assertEqual(messages[0].text, "Message 5")

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
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
                "payload": {"text": f"Message {i} on channel {ch}"}
            }
            client._handle_json_message("msh/US/json", json.dumps(json_data).encode())

        ch0_messages = client.get_messages(channel=0)
        self.assertEqual(len(ch0_messages), 3)

    @patch('meshing_around_clients.core.mqtt_client.mqtt')
    def test_get_alerts_unread_only(self, mock_mqtt):
        """Test get_alerts with unread_only filter."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)

        # Create alerts
        for i in range(3):
            json_data = {
                "from": 0x66660000 + i,
                "type": "text",
                "payload": {"text": "HELP emergency!"}
            }
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
        from meshing_around_clients.core.mqtt_client import MQTTConfig
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
    __import__('importlib.util').util.find_spec('paho'),
    "paho-mqtt not installed - skipping integration tests"
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


if __name__ == "__main__":
    unittest.main()

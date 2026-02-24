"""
Unit tests for meshing_around_clients.core.models
"""

import json
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.models import (
    Alert,
    AlertType,
    MeshNetwork,
    Message,
    MessageType,
    Node,
    NodeRole,
    NodeTelemetry,
    Position,
)


class TestEnums(unittest.TestCase):
    """Test enum definitions."""

    def test_node_role_values(self):
        self.assertEqual(NodeRole.CLIENT.value, "CLIENT")
        self.assertEqual(NodeRole.ROUTER.value, "ROUTER")
        self.assertEqual(NodeRole.REPEATER.value, "REPEATER")

    def test_alert_type_values(self):
        self.assertEqual(AlertType.EMERGENCY.value, "emergency")
        self.assertEqual(AlertType.BATTERY.value, "battery")
        self.assertEqual(AlertType.NEW_NODE.value, "new_node")

    def test_message_type_values(self):
        self.assertEqual(MessageType.TEXT.value, "text")
        self.assertEqual(MessageType.POSITION.value, "position")
        self.assertEqual(MessageType.TELEMETRY.value, "telemetry")


class TestPosition(unittest.TestCase):
    """Test Position dataclass."""

    def test_default_values(self):
        pos = Position()
        self.assertEqual(pos.latitude, 0.0)
        self.assertEqual(pos.longitude, 0.0)
        self.assertEqual(pos.altitude, 0)
        self.assertIsNone(pos.time)

    def test_custom_values(self):
        now = datetime.now(timezone.utc)
        pos = Position(latitude=45.5, longitude=-122.6, altitude=100, time=now)
        self.assertEqual(pos.latitude, 45.5)
        self.assertEqual(pos.longitude, -122.6)
        self.assertEqual(pos.altitude, 100)
        self.assertEqual(pos.time, now)

    def test_to_dict(self):
        now = datetime.now(timezone.utc)
        pos = Position(latitude=45.5, longitude=-122.6, altitude=100, time=now)
        d = pos.to_dict()
        self.assertEqual(d["latitude"], 45.5)
        self.assertEqual(d["longitude"], -122.6)
        self.assertEqual(d["altitude"], 100)
        self.assertEqual(d["time"], now.isoformat())

    def test_to_dict_no_time(self):
        pos = Position(latitude=1.0, longitude=2.0)
        d = pos.to_dict()
        self.assertIsNone(d["time"])


class TestNodeTelemetry(unittest.TestCase):
    """Test NodeTelemetry dataclass."""

    def test_default_values(self):
        tel = NodeTelemetry()
        self.assertEqual(tel.battery_level, 0)
        self.assertEqual(tel.voltage, 0.0)
        self.assertEqual(tel.snr, 0.0)

    def test_to_dict(self):
        now = datetime.now(timezone.utc)
        tel = NodeTelemetry(battery_level=85, voltage=4.1, snr=10.5, last_updated=now)
        d = tel.to_dict()
        self.assertEqual(d["battery_level"], 85)
        self.assertEqual(d["voltage"], 4.1)
        self.assertEqual(d["snr"], 10.5)
        self.assertEqual(d["last_updated"], now.isoformat())


class TestNode(unittest.TestCase):
    """Test Node dataclass."""

    def test_default_initialization(self):
        node = Node(node_id="!abc12345", node_num=12345)
        self.assertEqual(node.node_id, "!abc12345")
        self.assertEqual(node.node_num, 12345)
        self.assertEqual(node.short_name, "")
        self.assertEqual(node.role, NodeRole.CLIENT)
        self.assertIsNotNone(node.position)
        self.assertIsNotNone(node.telemetry)

    def test_display_name_long_name(self):
        node = Node(node_id="!abc12345", node_num=12345, long_name="Test Node")
        self.assertEqual(node.display_name, "Test Node")

    def test_display_name_short_name(self):
        node = Node(node_id="!abc12345", node_num=12345, short_name="TST")
        self.assertEqual(node.display_name, "TST")

    def test_display_name_fallback(self):
        node = Node(node_id="!abc12345", node_num=12345)
        self.assertEqual(node.display_name, "!2345")

    def test_time_since_heard_never(self):
        node = Node(node_id="!abc12345", node_num=12345)
        self.assertEqual(node.time_since_heard, "Never")

    def test_time_since_heard_seconds(self):
        node = Node(node_id="!abc12345", node_num=12345)
        node.last_heard = datetime.now(timezone.utc) - timedelta(seconds=30)
        self.assertIn("s ago", node.time_since_heard)

    def test_time_since_heard_minutes(self):
        node = Node(node_id="!abc12345", node_num=12345)
        node.last_heard = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.assertIn("m ago", node.time_since_heard)

    def test_time_since_heard_hours(self):
        node = Node(node_id="!abc12345", node_num=12345)
        node.last_heard = datetime.now(timezone.utc) - timedelta(hours=2)
        self.assertIn("h ago", node.time_since_heard)

    def test_time_since_heard_days(self):
        node = Node(node_id="!abc12345", node_num=12345)
        node.last_heard = datetime.now(timezone.utc) - timedelta(days=3)
        self.assertIn("d ago", node.time_since_heard)

    def test_to_dict(self):
        node = Node(node_id="!abc12345", node_num=12345, long_name="Test")
        d = node.to_dict()
        self.assertEqual(d["node_id"], "!abc12345")
        self.assertEqual(d["node_num"], 12345)
        self.assertEqual(d["long_name"], "Test")
        self.assertEqual(d["role"], "CLIENT")
        self.assertIn("position", d)
        self.assertIn("telemetry", d)


class TestMessage(unittest.TestCase):
    """Test Message dataclass."""

    def test_default_initialization(self):
        msg = Message(id="msg1", sender_id="!sender123")
        self.assertEqual(msg.id, "msg1")
        self.assertEqual(msg.sender_id, "!sender123")
        self.assertEqual(msg.message_type, MessageType.TEXT)
        self.assertIsNotNone(msg.timestamp)

    def test_is_broadcast_empty_recipient(self):
        msg = Message(id="msg1", sender_id="!sender123", recipient_id="")
        self.assertTrue(msg.is_broadcast)

    def test_is_broadcast_all(self):
        msg = Message(id="msg1", sender_id="!sender123", recipient_id="^all")
        self.assertTrue(msg.is_broadcast)

    def test_is_not_broadcast(self):
        msg = Message(id="msg1", sender_id="!sender123", recipient_id="!recipient456")
        self.assertFalse(msg.is_broadcast)

    def test_time_formatted(self):
        msg = Message(id="msg1", sender_id="!sender123")
        msg.timestamp = datetime(2026, 1, 15, 14, 30, 45)
        self.assertEqual(msg.time_formatted, "14:30:45")

    def test_to_dict(self):
        msg = Message(id="msg1", sender_id="!sender123", text="Hello")
        d = msg.to_dict()
        self.assertEqual(d["id"], "msg1")
        self.assertEqual(d["sender_id"], "!sender123")
        self.assertEqual(d["text"], "Hello")
        self.assertEqual(d["message_type"], "text")
        self.assertIn("is_broadcast", d)


class TestAlert(unittest.TestCase):
    """Test Alert dataclass."""

    def test_default_initialization(self):
        alert = Alert(id="alert1", alert_type=AlertType.EMERGENCY, title="Test", message="Test msg")
        self.assertEqual(alert.id, "alert1")
        self.assertEqual(alert.alert_type, AlertType.EMERGENCY)
        self.assertEqual(alert.severity, 1)
        self.assertIsNotNone(alert.timestamp)

    def test_severity_label(self):
        alert = Alert(id="a1", alert_type=AlertType.BATTERY, title="T", message="M", severity=1)
        self.assertEqual(alert.severity_label, "Low")
        alert.severity = 2
        self.assertEqual(alert.severity_label, "Medium")
        alert.severity = 3
        self.assertEqual(alert.severity_label, "High")
        alert.severity = 4
        self.assertEqual(alert.severity_label, "Critical")
        alert.severity = 99
        self.assertEqual(alert.severity_label, "Unknown")

    def test_severity_color(self):
        alert = Alert(id="a1", alert_type=AlertType.BATTERY, title="T", message="M", severity=1)
        self.assertEqual(alert.severity_color, "blue")
        alert.severity = 4
        self.assertEqual(alert.severity_color, "red")

    def test_to_dict(self):
        alert = Alert(id="a1", alert_type=AlertType.EMERGENCY, title="Emergency", message="Help!", severity=4)
        d = alert.to_dict()
        self.assertEqual(d["id"], "a1")
        self.assertEqual(d["alert_type"], "emergency")
        self.assertEqual(d["severity_label"], "Critical")


class TestMeshNetwork(unittest.TestCase):
    """Test MeshNetwork dataclass."""

    def test_default_initialization(self):
        network = MeshNetwork()
        self.assertEqual(len(network.nodes), 0)
        self.assertEqual(len(network.messages), 0)
        self.assertEqual(len(network.alerts), 0)
        self.assertEqual(network.connection_status, "disconnected")

    def test_add_node(self):
        network = MeshNetwork()
        node = Node(node_id="!abc123", node_num=123)
        network.add_node(node)
        self.assertEqual(len(network.nodes), 1)
        self.assertIsNotNone(network.get_node("!abc123"))

    def test_add_message(self):
        network = MeshNetwork()
        msg = Message(id="msg1", sender_id="!sender")
        network.add_message(msg)
        self.assertEqual(network.total_messages, 1)

    def test_add_message_bounded(self):
        network = MeshNetwork()
        for i in range(1100):
            msg = Message(id=f"msg{i}", sender_id="!sender")
            network.add_message(msg)
        self.assertEqual(network.total_messages, 1000)

    def test_add_alert(self):
        network = MeshNetwork()
        alert = Alert(id="a1", alert_type=AlertType.BATTERY, title="T", message="M")
        network.add_alert(alert)
        self.assertEqual(len(network.alerts), 1)

    def test_online_nodes(self):
        network = MeshNetwork()
        node1 = Node(node_id="!n1", node_num=1, is_online=True)
        node2 = Node(node_id="!n2", node_num=2, is_online=False)
        network.add_node(node1)
        network.add_node(node2)
        self.assertEqual(len(network.online_nodes), 1)

    def test_favorite_nodes(self):
        network = MeshNetwork()
        node1 = Node(node_id="!n1", node_num=1, is_favorite=True)
        node2 = Node(node_id="!n2", node_num=2, is_favorite=False)
        network.add_node(node1)
        network.add_node(node2)
        self.assertEqual(len(network.favorite_nodes), 1)

    def test_unread_alerts(self):
        network = MeshNetwork()
        alert1 = Alert(id="a1", alert_type=AlertType.BATTERY, title="T", message="M", acknowledged=False)
        alert2 = Alert(id="a2", alert_type=AlertType.BATTERY, title="T", message="M", acknowledged=True)
        network.add_alert(alert1)
        network.add_alert(alert2)
        self.assertEqual(len(network.unread_alerts), 1)

    def test_get_messages_for_channel(self):
        network = MeshNetwork()
        msg1 = Message(id="m1", sender_id="!s", channel=0)
        msg2 = Message(id="m2", sender_id="!s", channel=1)
        msg3 = Message(id="m3", sender_id="!s", channel=0)
        network.add_message(msg1)
        network.add_message(msg2)
        network.add_message(msg3)
        ch0_msgs = network.get_messages_for_channel(0)
        self.assertEqual(len(ch0_msgs), 2)

    def test_get_messages_for_node(self):
        network = MeshNetwork()
        msg1 = Message(id="m1", sender_id="!node1")
        msg2 = Message(id="m2", sender_id="!node2", recipient_id="!node1")
        msg3 = Message(id="m3", sender_id="!node3")
        network.add_message(msg1)
        network.add_message(msg2)
        network.add_message(msg3)
        node_msgs = network.get_messages_for_node("!node1")
        self.assertEqual(len(node_msgs), 2)

    def test_to_dict(self):
        network = MeshNetwork()
        network.my_node_id = "!mynode"
        d = network.to_dict()
        self.assertEqual(d["my_node_id"], "!mynode")
        self.assertIn("nodes", d)
        self.assertIn("messages", d)
        self.assertIn("online_node_count", d)

    def test_to_json(self):
        network = MeshNetwork()
        j = network.to_json()
        self.assertIsInstance(j, str)
        parsed = json.loads(j)
        self.assertIn("nodes", parsed)

    def test_thread_safety(self):
        """Test concurrent access to MeshNetwork."""
        network = MeshNetwork()
        errors = []

        def add_nodes():
            try:
                for i in range(100):
                    node = Node(node_id=f"!n{threading.current_thread().name}_{i}", node_num=i)
                    network.add_node(node)
            except Exception as e:
                errors.append(e)

        def add_messages():
            try:
                for i in range(100):
                    msg = Message(id=f"m{threading.current_thread().name}_{i}", sender_id="!s")
                    network.add_message(msg)
            except Exception as e:
                errors.append(e)

        def read_data():
            try:
                for _ in range(100):
                    _ = network.online_nodes
                    _ = network.total_messages
                    _ = network.to_dict()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=add_nodes, name=f"add_nodes_{i}"))
            threads.append(threading.Thread(target=add_messages, name=f"add_messages_{i}"))
            threads.append(threading.Thread(target=read_data, name=f"read_data_{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")


class TestMeshNetworkPersistence(unittest.TestCase):
    """Test MeshNetwork persistence methods."""

    def test_from_dict_basic(self):
        """Test restoring network from dictionary."""
        data = {
            "my_node_id": "!test123",
            "connection_status": "connected",
            "channel_count": 3,
            "nodes": {
                "!node1": {
                    "node_id": "!node1",
                    "node_num": 12345,
                    "short_name": "N1",
                    "long_name": "Node One",
                    "hardware_model": "T-Beam",
                    "is_online": True,
                    "role": "ROUTER",
                }
            },
            "channels": {"0": {"name": "Primary", "role": "PRIMARY", "message_count": 42}},
        }
        network = MeshNetwork.from_dict(data)
        self.assertEqual(network.my_node_id, "!test123")
        self.assertEqual(network.connection_status, "connected")
        self.assertEqual(len(network.nodes), 1)
        self.assertEqual(network.nodes["!node1"].short_name, "N1")
        self.assertEqual(network.nodes["!node1"].role, NodeRole.ROUTER)
        # from_dict restores channels, which update the default 8 channels
        self.assertIn(0, network.channels)
        self.assertEqual(network.channels[0].name, "Primary")

    def test_from_json(self):
        """Test restoring network from JSON string."""
        json_str = '{"my_node_id": "!json_test", "nodes": {}, "channels": {}}'
        network = MeshNetwork.from_json(json_str)
        self.assertEqual(network.my_node_id, "!json_test")

    def test_from_json_invalid(self):
        """Test handling invalid JSON."""
        network = MeshNetwork.from_json("not valid json")
        # Should return empty network
        self.assertEqual(len(network.nodes), 0)

    def test_roundtrip(self):
        """Test save and restore roundtrip."""
        # Create network with data
        network = MeshNetwork()
        network.my_node_id = "!roundtrip"
        network.connection_status = "connected"
        node = Node(node_id="!n1", node_num=1, short_name="RT", long_name="Roundtrip Test")
        network.add_node(node)

        # Convert to dict and back
        data = network.to_dict()
        restored = MeshNetwork.from_dict(data)

        self.assertEqual(restored.my_node_id, "!roundtrip")
        self.assertEqual(len(restored.nodes), 1)
        self.assertEqual(restored.nodes["!n1"].short_name, "RT")

    def test_save_and_load_file(self):
        """Test file-based persistence."""
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "network_state.json"

            # Create and save network
            network = MeshNetwork()
            network.my_node_id = "!filetest"
            node = Node(node_id="!f1", node_num=1, short_name="FT")
            network.add_node(node)

            result = network.save_to_file(filepath)
            self.assertTrue(result)
            self.assertTrue(filepath.exists())

            # Check file permissions (should be 600)
            mode = os.stat(filepath).st_mode & 0o777
            self.assertEqual(mode, 0o600)

            # Load and verify
            loaded = MeshNetwork.load_from_file(filepath)
            self.assertEqual(loaded.my_node_id, "!filetest")
            self.assertEqual(len(loaded.nodes), 1)

    def test_load_nonexistent_file(self):
        """Test loading from nonexistent file returns empty network."""
        network = MeshNetwork.load_from_file("/nonexistent/path/state.json")
        self.assertEqual(len(network.nodes), 0)

    def test_from_dict_handles_bad_data(self):
        """Test that from_dict handles malformed data gracefully."""
        data = {
            "nodes": {
                "!good": {"node_id": "!good", "node_num": 1, "short_name": "Good"},
                "!bad": {"invalid": "data"},  # Missing required fields
            }
        }
        network = MeshNetwork.from_dict(data)
        # Should have at least the good node
        self.assertIn("!good", network.nodes)


if __name__ == "__main__":
    unittest.main()

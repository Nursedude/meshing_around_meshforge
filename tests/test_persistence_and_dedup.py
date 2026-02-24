"""
Integration tests for message persistence, alert deduplication,
connection state synchronization, and failover scenarios.

Tests:
- Message/alert persistence roundtrip (crash recovery)
- Alert deduplication per node (cooldown prevents spam)
- MQTT _connected flag thread safety
- Failover reconnection scenarios
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from meshing_around_clients.core.config import Config
from meshing_around_clients.core.models import (
    Alert,
    AlertType,
    MeshNetwork,
    Message,
    MessageType,
    Node,
)

# =============================================================================
# Message Persistence Tests
# =============================================================================


class TestMessagePersistenceRoundtrip(unittest.TestCase):
    """Test that messages and alerts survive save/load cycles."""

    def test_messages_persist_through_save_load(self):
        """Messages should be restored after save_to_file / load_from_file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "state.json"

            # Create network with messages
            network = MeshNetwork()
            network.my_node_id = "!persist01"
            for i in range(5):
                msg = Message(
                    id=f"msg-{i}",
                    sender_id="!sender01",
                    sender_name="TestNode",
                    text=f"Test message {i}",
                    channel=0,
                    message_type=MessageType.TEXT,
                    is_incoming=(i % 2 == 0),
                )
                network.add_message(msg)

            # Save
            self.assertTrue(network.save_to_file(filepath))

            # Load
            loaded = MeshNetwork.load_from_file(filepath)
            self.assertEqual(loaded.my_node_id, "!persist01")
            self.assertEqual(len(loaded.messages), 5)

            # Verify message content
            msgs = list(loaded.messages)
            self.assertEqual(msgs[0].id, "msg-0")
            self.assertEqual(msgs[0].text, "Test message 0")
            self.assertEqual(msgs[0].sender_name, "TestNode")
            self.assertTrue(msgs[0].is_incoming)
            self.assertFalse(msgs[1].is_incoming)

    def test_alerts_persist_through_save_load(self):
        """Alerts should be restored after save_to_file / load_from_file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "state.json"

            network = MeshNetwork()
            for i in range(3):
                alert = Alert(
                    id=f"alert-{i}",
                    alert_type=AlertType.BATTERY,
                    title=f"Test Alert {i}",
                    message=f"Alert message {i}",
                    severity=2,
                    source_node="!node01",
                    acknowledged=(i == 1),
                    metadata={"battery_level": 15 + i},
                )
                network.add_alert(alert)

            self.assertTrue(network.save_to_file(filepath))
            loaded = MeshNetwork.load_from_file(filepath)

            self.assertEqual(len(loaded.alerts), 3)
            alerts = list(loaded.alerts)
            self.assertEqual(alerts[0].id, "alert-0")
            self.assertEqual(alerts[0].alert_type, AlertType.BATTERY)
            self.assertEqual(alerts[0].severity, 2)
            self.assertFalse(alerts[0].acknowledged)
            self.assertTrue(alerts[1].acknowledged)
            self.assertEqual(alerts[2].metadata["battery_level"], 17)

    def test_outgoing_messages_survive_crash(self):
        """Outgoing (is_incoming=False) messages persist for crash recovery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "state.json"

            network = MeshNetwork()
            # Simulate an outgoing message
            out_msg = Message(
                id="out-001",
                sender_id="!me",
                sender_name="Me (MQTT)",
                recipient_id="!dest",
                text="Important outgoing message",
                is_incoming=False,
                ack_received=False,
            )
            network.add_message(out_msg)
            network.save_to_file(filepath)

            loaded = MeshNetwork.load_from_file(filepath)
            msgs = list(loaded.messages)
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0].text, "Important outgoing message")
            self.assertFalse(msgs[0].is_incoming)
            self.assertFalse(msgs[0].ack_received)

    def test_persistence_with_all_message_types(self):
        """All MessageType values survive persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "state.json"

            network = MeshNetwork()
            for mt in MessageType:
                msg = Message(
                    id=f"msg-{mt.value}",
                    sender_id="!sender",
                    message_type=mt,
                    text=f"Type: {mt.value}",
                )
                network.add_message(msg)

            network.save_to_file(filepath)
            loaded = MeshNetwork.load_from_file(filepath)

            loaded_types = {m.message_type for m in loaded.messages}
            for mt in MessageType:
                self.assertIn(mt, loaded_types, f"MessageType.{mt.name} lost in persistence")

    def test_persistence_with_all_alert_types(self):
        """All AlertType values survive persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "state.json"

            network = MeshNetwork()
            for at in AlertType:
                alert = Alert(
                    id=f"alert-{at.value}",
                    alert_type=at,
                    title=f"Type: {at.value}",
                    message="Test",
                )
                network.add_alert(alert)

            network.save_to_file(filepath)
            loaded = MeshNetwork.load_from_file(filepath)

            loaded_types = {a.alert_type for a in loaded.alerts}
            for at in AlertType:
                self.assertIn(at, loaded_types, f"AlertType.{at.name} lost in persistence")

    def test_persistence_handles_corrupt_messages_gracefully(self):
        """Corrupt message entries are skipped, valid ones restored."""
        data = {
            "my_node_id": "!test",
            "nodes": {},
            "channels": {},
            "messages": [
                {"id": "good", "sender_id": "!s", "text": "ok", "message_type": "text"},
                {"corrupt": True},  # Missing required fields
                {"id": "good2", "sender_id": "!s2", "text": "ok2", "message_type": "text"},
            ],
            "alerts": [
                {"id": "a1", "alert_type": "battery", "title": "T", "message": "M"},
                {},  # Empty dict
                {"id": "a2", "alert_type": "invalid_type", "title": "T2", "message": "M2"},
            ],
        }
        network = MeshNetwork.from_dict(data)
        # Should restore valid messages, skip corrupt
        self.assertGreaterEqual(len(network.messages), 2)
        # Invalid alert type should fall back to CUSTOM
        alert_ids = [a.id for a in network.alerts]
        self.assertIn("a2", alert_ids)

    def test_timestamp_preservation(self):
        """Message timestamps survive roundtrip with timezone info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "state.json"

            network = MeshNetwork()
            ts = datetime(2026, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
            msg = Message(id="ts-test", sender_id="!s", text="timestamp test")
            msg.timestamp = ts
            network.add_message(msg)

            network.save_to_file(filepath)
            loaded = MeshNetwork.load_from_file(filepath)

            restored_msg = list(loaded.messages)[0]
            self.assertIsNotNone(restored_msg.timestamp)
            self.assertEqual(restored_msg.timestamp.year, 2026)
            self.assertEqual(restored_msg.timestamp.month, 1)
            self.assertEqual(restored_msg.timestamp.hour, 14)


# =============================================================================
# Alert Deduplication Tests
# =============================================================================


@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("paho"),
    "paho-mqtt not installed",
)
class TestAlertDeduplicationMQTT(unittest.TestCase):
    """Test per-node alert deduplication in MQTT client."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.alerts.enabled = True
        self.config.alerts.emergency_keywords = ["help", "sos"]

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_battery_alert_fires_once_per_cooldown(self, mock_mqtt):
        """Same node's low battery should not spam alerts within cooldown."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        client._alert_cooldown_seconds = 300  # 5 min cooldown

        # First add the node
        nodeinfo = {"from": 0xAABBCCDD, "payload": {"user": {"shortName": "LO"}}}
        client._handle_json_message("msh/US/json", json.dumps(nodeinfo).encode())

        # Send low battery telemetry 3 times
        for i in range(3):
            tel = {
                "from": 0xAABBCCDD,
                "id": f"tel-{i}",
                "type": "telemetry",
                "payload": {"telemetry": {"deviceMetrics": {"batteryLevel": 10}}},
            }
            client._handle_json_message("msh/US/json", json.dumps(tel).encode())

        # Should have only 1 battery alert (others suppressed by cooldown)
        battery_alerts = [a for a in client.network.alerts if a.alert_type == AlertType.BATTERY]
        self.assertEqual(len(battery_alerts), 1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_congestion_alert_fires_once_per_cooldown(self, mock_mqtt):
        """Same node's congestion should not spam alerts within cooldown."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        client._alert_cooldown_seconds = 300

        nodeinfo = {"from": 0x11223344, "payload": {"user": {"shortName": "CG"}}}
        client._handle_json_message("msh/US/json", json.dumps(nodeinfo).encode())

        for i in range(3):
            tel = {
                "from": 0x11223344,
                "id": f"cong-{i}",
                "type": "telemetry",
                "payload": {"telemetry": {"deviceMetrics": {"channelUtilization": 50.0}}},
            }
            client._handle_json_message("msh/US/json", json.dumps(tel).encode())

        congestion_alerts = [a for a in client.network.alerts if "Congestion" in a.title]
        self.assertEqual(len(congestion_alerts), 1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_different_nodes_get_separate_cooldowns(self, mock_mqtt):
        """Different nodes should each get their own alert cooldown."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        client._alert_cooldown_seconds = 300

        # Two different nodes with low battery
        for node_num in [0xAAAA0001, 0xAAAA0002]:
            nodeinfo = {"from": node_num, "payload": {"user": {"shortName": "N"}}}
            client._handle_json_message("msh/US/json", json.dumps(nodeinfo).encode())

            tel = {
                "from": node_num,
                "id": f"bat-{node_num}",
                "type": "telemetry",
                "payload": {"telemetry": {"deviceMetrics": {"batteryLevel": 5}}},
            }
            client._handle_json_message("msh/US/json", json.dumps(tel).encode())

        battery_alerts = [a for a in client.network.alerts if a.alert_type == AlertType.BATTERY]
        self.assertEqual(len(battery_alerts), 2)  # One per node

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_cooldown_expires_allows_new_alert(self, mock_mqtt):
        """After cooldown expires, a new alert should fire."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        client = MQTTMeshtasticClient(self.config)
        client._alert_cooldown_seconds = 0.1  # Very short cooldown for testing

        nodeinfo = {"from": 0xBBBBBBBB, "payload": {"user": {"shortName": "EX"}}}
        client._handle_json_message("msh/US/json", json.dumps(nodeinfo).encode())

        # First telemetry
        tel1 = {
            "from": 0xBBBBBBBB,
            "id": "t1",
            "type": "telemetry",
            "payload": {"telemetry": {"deviceMetrics": {"batteryLevel": 10}}},
        }
        client._handle_json_message("msh/US/json", json.dumps(tel1).encode())

        # Wait for cooldown to expire
        time.sleep(0.2)

        # Second telemetry should trigger new alert
        tel2 = {
            "from": 0xBBBBBBBB,
            "id": "t2",
            "type": "telemetry",
            "payload": {"telemetry": {"deviceMetrics": {"batteryLevel": 8}}},
        }
        client._handle_json_message("msh/US/json", json.dumps(tel2).encode())

        battery_alerts = [a for a in client.network.alerts if a.alert_type == AlertType.BATTERY]
        self.assertEqual(len(battery_alerts), 2)


# =============================================================================
# Connection State Synchronization Tests
# =============================================================================


@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("paho"),
    "paho-mqtt not installed",
)
class TestConnectedFlagThreadSafety(unittest.TestCase):
    """Test that _connected flag access is thread-safe."""

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_concurrent_connected_reads_and_writes(self, mock_mqtt):
        """Concurrent reads/writes to is_connected should not crash."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        errors = []

        def toggle_connected():
            try:
                for _ in range(200):
                    with client._stats_lock:
                        client._connected = not client._connected
            except Exception as e:
                errors.append(e)

        def read_connected():
            try:
                for _ in range(200):
                    _ = client.is_connected
            except Exception as e:
                errors.append(e)

        def read_health():
            try:
                for _ in range(100):
                    _ = client.connection_health
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=toggle_connected, name=f"toggle_{i}"))
            threads.append(threading.Thread(target=read_connected, name=f"read_{i}"))
            threads.append(threading.Thread(target=read_health, name=f"health_{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_on_connect_on_disconnect_simulated(self, mock_mqtt):
        """Simulated connect/disconnect callbacks should update state safely."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()  # Mock the MQTT client for subscribe calls

        # Simulate on_connect
        client._on_connect(None, None, None, 0)
        self.assertTrue(client.is_connected)
        self.assertEqual(client.network.connection_status, "connected (MQTT)")

        # Simulate on_disconnect
        client._on_disconnect(None, None, 0)
        self.assertFalse(client.is_connected)
        self.assertEqual(client.network.connection_status, "disconnected")


# =============================================================================
# Failover Scenario Tests
# =============================================================================


@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("paho"),
    "paho-mqtt not installed",
)
class TestFailoverScenarios(unittest.TestCase):
    """Test connection failover and recovery patterns."""

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_reconnect_count_increments_on_unexpected_disconnect(self, mock_mqtt):
        """Unexpected disconnects should increment reconnect count."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()

        # Simulate connect then unexpected disconnect
        client._on_connect(None, None, None, 0)
        client._on_disconnect(None, None, 1)  # rc=1 = unexpected

        health = client.connection_health
        self.assertEqual(health["reconnect_count"], 1)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_clean_disconnect_no_reconnect_count(self, mock_mqtt):
        """Clean disconnects should not increment reconnect count."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()

        client._on_connect(None, None, None, 0)
        client._on_disconnect(None, None, 0)  # rc=0 = clean

        health = client.connection_health
        self.assertEqual(health["reconnect_count"], 0)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_reconnect_resets_count(self, mock_mqtt):
        """Successful reconnect should reset the reconnect count."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()

        # Connect, then unexpected disconnect (bumps count)
        client._on_connect(None, None, None, 0)
        client._on_disconnect(None, None, 1)

        with client._stats_lock:
            self.assertEqual(client._reconnect_count, 1)

        # Reconnect success should reset
        client._on_connect(None, None, None, 0)

        with client._stats_lock:
            self.assertEqual(client._reconnect_count, 0)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_network_state_preserved_across_reconnect(self, mock_mqtt):
        """Node data should survive reconnection cycles."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()

        # Connect and add some nodes
        client._on_connect(None, None, None, 0)
        nodeinfo = {"from": 0xDEADBEEF, "payload": {"user": {"shortName": "SV", "longName": "Survive"}}}
        client._handle_json_message("msh/US/json", json.dumps(nodeinfo).encode())

        self.assertEqual(len(client.network.nodes), 1)

        # Simulate disconnect + reconnect
        client._on_disconnect(None, None, 1)
        client._on_connect(None, None, None, 0)

        # Nodes should still be there
        self.assertEqual(len(client.network.nodes), 1)
        node = client.network.get_node("!deadbeef")
        self.assertIsNotNone(node)
        self.assertEqual(node.long_name, "Survive")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_connection_health_status_transitions(self, mock_mqtt):
        """Health status should correctly reflect connection state."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()

        # Initially disconnected
        self.assertEqual(client.connection_health["status"], "disconnected")

        # After connect, no traffic yet
        client._on_connect(None, None, None, 0)
        client._connection_start = datetime.now(timezone.utc)
        health = client.connection_health
        self.assertIn(health["status"], ["connected_no_traffic", "healthy"])


# =============================================================================
# WebSocket Load Pattern Tests (unit-level)
# =============================================================================


class TestNetworkStateConcurrentAccess(unittest.TestCase):
    """Test MeshNetwork under concurrent load (simulates WebSocket broadcast)."""

    def test_concurrent_message_adds_and_reads(self):
        """Simulate WebSocket load: concurrent message adds and serialization."""
        network = MeshNetwork()
        errors = []
        message_count = 200

        def add_messages():
            try:
                for i in range(message_count):
                    msg = Message(
                        id=f"ws-{threading.current_thread().name}-{i}",
                        sender_id="!sender",
                        text=f"msg {i}",
                    )
                    network.add_message(msg)
            except Exception as e:
                errors.append(e)

        def serialize_state():
            try:
                for _ in range(50):
                    _ = network.to_dict()
                    _ = network.to_json()
            except Exception as e:
                errors.append(e)

        def read_alerts():
            try:
                for _ in range(50):
                    _ = network.unread_alerts
                    _ = network.mesh_health
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(4):
            threads.append(threading.Thread(target=add_messages, name=f"writer_{i}"))
            threads.append(threading.Thread(target=serialize_state, name=f"serial_{i}"))
            threads.append(threading.Thread(target=read_alerts, name=f"reader_{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(len(errors), 0, f"Concurrent access errors: {errors}")
        # Messages are bounded by deque maxlen
        self.assertLessEqual(len(network.messages), 1000)

    def test_concurrent_alert_adds_during_serialization(self):
        """Alerts should be safely addable during to_dict() serialization."""
        network = MeshNetwork()
        errors = []

        def add_alerts():
            try:
                for i in range(100):
                    alert = Alert(
                        id=f"a-{threading.current_thread().name}-{i}",
                        alert_type=AlertType.BATTERY,
                        title="T",
                        message="M",
                    )
                    network.add_alert(alert)
            except Exception as e:
                errors.append(e)

        def serialize():
            try:
                for _ in range(100):
                    data = network.to_dict()
                    json.dumps(data)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=add_alerts, name="alerter_1"),
            threading.Thread(target=add_alerts, name="alerter_2"),
            threading.Thread(target=serialize, name="serializer"),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Concurrent alert errors: {errors}")


if __name__ == "__main__":
    unittest.main()

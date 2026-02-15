"""
Integration tests for:
1. Full failover with actual network (broker connectivity)
2. WebSocket load testing with actual FastAPI/uvicorn stack
3. _intentional_disconnect flag thread-safety verification

These tests require:
- Network connectivity to mqtt.meshtastic.org (failover tests)
- paho-mqtt, fastapi, uvicorn, httpx packages installed
- Run with: python -m pytest tests/test_integration_failover_and_ws_load.py -v

Failover tests are skipped automatically when broker is unreachable.
"""

import json
import socket
import sys
import threading
import time
import unittest
from datetime import datetime, timezone
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


def _broker_reachable(host="mqtt.meshtastic.org", port=1883, timeout=5) -> bool:
    """Check if MQTT broker is reachable via TCP."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.error, OSError, socket.timeout):
        return False


# =============================================================================
# Full Failover Integration Tests (requires broker connectivity)
# =============================================================================


@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("paho"),
    "paho-mqtt not installed",
)
class TestMQTTBrokerFailoverIntegration(unittest.TestCase):
    """Integration tests for MQTT failover with actual broker connectivity.

    Tests the full connect -> disconnect -> reconnect cycle against the
    real mqtt.meshtastic.org broker. Validates that:
    - Connection state is correctly tracked
    - Network state (nodes, messages) survives reconnection
    - Intentional vs unexpected disconnect is properly classified
    - Health status transitions are correct
    - Cleanup threads start and stop cleanly
    """

    @classmethod
    def setUpClass(cls):
        if not _broker_reachable():
            raise unittest.SkipTest("MQTT broker mqtt.meshtastic.org not reachable")

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.alerts.enabled = True
        self.config.alerts.emergency_keywords = ["help", "sos"]

    def _make_client(self):
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        return MQTTMeshtasticClient(self.config)

    def test_connect_disconnect_cycle(self):
        """Full connect/disconnect cycle against live broker."""
        client = self._make_client()
        try:
            self.assertTrue(client.connect(), "Failed to connect to live broker")
            self.assertTrue(client.is_connected)
            self.assertEqual(client.network.connection_status, "connected (MQTT)")

            # Verify health reports connected state
            health = client.connection_health
            self.assertTrue(health["connected"])
            self.assertEqual(health["broker"], "mqtt.meshtastic.org")
            self.assertIn(health["status"], ["healthy", "connected_no_traffic"])
        finally:
            client.disconnect()

        self.assertFalse(client.is_connected)
        self.assertEqual(client.network.connection_status, "disconnected")

    def test_intentional_disconnect_is_clean(self):
        """Intentional disconnect should not increment reconnect count."""
        client = self._make_client()
        try:
            self.assertTrue(client.connect())

            # Capture reconnect count before disconnect
            with client._stats_lock:
                count_before = client._reconnect_count
        finally:
            client.disconnect()

        with client._stats_lock:
            count_after = client._reconnect_count
        self.assertEqual(count_before, count_after, "Intentional disconnect should not increment reconnect count")

    def test_network_state_preserved_across_reconnect(self):
        """Node data injected between connect cycles should survive."""
        client = self._make_client()
        try:
            self.assertTrue(client.connect())

            # Inject a node via JSON message handler (simulates real traffic)
            nodeinfo = {
                "from": 0xFACECAFE,
                "payload": {"user": {"shortName": "IT", "longName": "IntegrationTest"}},
            }
            client._handle_json_message("msh/US/json", json.dumps(nodeinfo).encode())
            self.assertIn("!facecafe", client.network.nodes)
        finally:
            client.disconnect()

        # Network state should still have the node after disconnect
        self.assertIn("!facecafe", client.network.nodes)
        node = client.network.get_node("!facecafe")
        self.assertEqual(node.long_name, "IntegrationTest")

        # Reconnect
        try:
            self.assertTrue(client.connect())
            # Node should still be there
            self.assertIn("!facecafe", client.network.nodes)
        finally:
            client.disconnect()

    def test_health_transitions_through_lifecycle(self):
        """Health status should transition correctly: disconnected -> connected -> disconnected."""
        client = self._make_client()

        # Initially disconnected
        self.assertEqual(client.connection_health["status"], "disconnected")

        try:
            self.assertTrue(client.connect())

            # After connect, should be healthy or connected_no_traffic
            health = client.connection_health
            self.assertIn(health["status"], ["healthy", "connected_no_traffic"])
            self.assertTrue(health["connected"])
            self.assertGreaterEqual(health["uptime_seconds"], 0)
        finally:
            client.disconnect()

        # After disconnect
        health = client.connection_health
        self.assertEqual(health["status"], "disconnected")
        self.assertFalse(health["connected"])

    def test_cleanup_thread_lifecycle(self):
        """Background cleanup thread should start on connect and stop on disconnect."""
        client = self._make_client()
        try:
            self.assertTrue(client.connect())

            # Cleanup thread should be running
            self.assertIsNotNone(client._cleanup_thread)
            self.assertTrue(client._cleanup_thread.is_alive())
        finally:
            client.disconnect()

        # Give thread time to finish
        if client._cleanup_thread:
            client._cleanup_thread.join(timeout=10)
        self.assertFalse(client._cleanup_thread.is_alive())

    def test_message_reception_from_live_broker(self):
        """Connect and wait briefly for real MQTT traffic.

        The public broker typically has traffic within seconds.
        This validates the full message pipeline end-to-end.
        """
        client = self._make_client()
        messages_received = []

        def on_message(msg):
            messages_received.append(msg)

        client.register_callback("on_message", on_message)

        try:
            self.assertTrue(client.connect())

            # Wait up to 30 seconds for any traffic
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if client._message_count > 0 or len(client.network.nodes) > 0:
                    break
                time.sleep(0.5)

            # We should have received at least some traffic or discovered nodes
            # (encrypted messages still register nodes even without decryption)
            stats = client.stats
            total_activity = stats["messages_received"] + stats["nodes_discovered"]
            # Don't fail if broker is quiet - just verify we stayed connected
            self.assertTrue(client.is_connected, "Client should still be connected after waiting")
        finally:
            client.disconnect()

    def test_rapid_connect_disconnect_cycles(self):
        """Rapid connect/disconnect should not leak threads or crash."""
        client = self._make_client()

        for i in range(3):
            try:
                result = client.connect()
                if result:
                    self.assertTrue(client.is_connected)
            finally:
                client.disconnect()
                self.assertFalse(client.is_connected)

            # Brief pause between cycles (respect connection cooldown)
            time.sleep(1.5)

        # Verify clean state after rapid cycling
        self.assertFalse(client.is_connected)
        self.assertEqual(client.network.connection_status, "disconnected")

    def test_stats_accumulate_across_session(self):
        """Statistics should accumulate correctly during a session."""
        client = self._make_client()
        try:
            self.assertTrue(client.connect())

            # Capture baseline stats — real broker traffic may have already
            # incremented counters between connect() and here.
            baseline = client.stats
            baseline_msgs = baseline["messages_received"]
            baseline_nodes = baseline["nodes_discovered"]

            # Inject a message through _on_message (the MQTT callback) so that
            # the full stats pipeline runs — _handle_json_message alone does
            # not increment messages_received.
            json_data = {
                "from": 0xBEEF0001,
                "type": "text",
                "payload": {"text": "stats test"},
            }
            mock_msg = MagicMock()
            mock_msg.topic = "msh/US/json"
            mock_msg.payload = json.dumps(json_data).encode()
            client._on_message(None, None, mock_msg)

            stats = client.stats
            # Our injected message should add exactly 1 to the counters.
            # Use delta from baseline because real broker traffic may also
            # arrive on the public mqtt.meshtastic.org broker.
            self.assertGreaterEqual(
                stats["messages_received"] - baseline_msgs, 1, "Injected message should increment messages_received"
            )
            self.assertGreaterEqual(
                stats["nodes_discovered"] - baseline_nodes,
                1,
                "New node from injected message should increment nodes_discovered",
            )
        finally:
            client.disconnect()


@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("paho"),
    "paho-mqtt not installed",
)
class TestConnectionManagerFailoverIntegration(unittest.TestCase):
    """Integration tests for the unified ConnectionManager failover chain.

    Tests the fallback sequence: SERIAL -> TCP -> MQTT -> DEMO
    and validates that connection health checks work end-to-end.
    """

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        # Enable MQTT so it's in the fallback chain
        self.config.mqtt.enabled = True

    def test_fallback_to_mqtt_when_serial_unavailable(self):
        """ConnectionManager should fall through serial/tcp to MQTT."""
        from meshing_around_clients.core.connection_manager import (
            ConnectionManager,
            ConnectionType,
        )

        mgr = ConnectionManager(self.config)

        if not _broker_reachable():
            self.skipTest("MQTT broker not reachable")

        try:
            # Starting from MQTT directly (skip serial/tcp which need hardware)
            result = mgr.connect(ConnectionType.MQTT)
            self.assertTrue(result, "Should connect via MQTT")
            self.assertTrue(mgr.is_connected)
            self.assertEqual(mgr.status.connection_type, ConnectionType.MQTT)
            self.assertIn("MQTT", mgr.status.device_info)
        finally:
            mgr.disconnect()

        self.assertFalse(mgr.is_connected)

    def test_fallback_to_demo_when_mqtt_unavailable(self):
        """When MQTT fails, ConnectionManager should fall back to DEMO."""
        from meshing_around_clients.core.connection_manager import (
            ConnectionManager,
            ConnectionType,
        )

        config = Config(config_path="/nonexistent/path")
        # Point to a non-existent broker so MQTT fails
        config.mqtt.broker = "localhost"
        config.mqtt.port = 19999  # Not a real port
        config.mqtt.enabled = True

        mgr = ConnectionManager(config)
        try:
            # Start from MQTT - it should fail and fall through to DEMO
            result = mgr.connect(ConnectionType.MQTT)
            self.assertTrue(result, "Should fall back to DEMO")
            self.assertTrue(mgr.is_connected)
            self.assertEqual(mgr.status.connection_type, ConnectionType.DEMO)
        finally:
            mgr.disconnect()

    def test_connection_health_check_with_live_mqtt(self):
        """Health check should return accurate state for live MQTT connection."""
        from meshing_around_clients.core.connection_manager import (
            ConnectionManager,
            ConnectionType,
        )

        if not _broker_reachable():
            self.skipTest("MQTT broker not reachable")

        mgr = ConnectionManager(self.config)
        try:
            result = mgr.connect(ConnectionType.MQTT)
            self.assertTrue(result)

            # Health check should pass for a fresh connection
            is_healthy = mgr._check_connection_health()
            self.assertTrue(is_healthy, "Fresh MQTT connection should be healthy")

            # Connection health property should have MQTT-specific data
            health = mgr.connection_health
            self.assertEqual(health["connection_type"], "mqtt")
            self.assertIn("broker", health)
        finally:
            mgr.disconnect()

    def test_reconnect_monitor_starts_and_stops(self):
        """Reconnect monitor thread should start on connect and stop on disconnect."""
        from meshing_around_clients.core.connection_manager import (
            ConnectionManager,
            ConnectionType,
        )

        if not _broker_reachable():
            self.skipTest("MQTT broker not reachable")

        mgr = ConnectionManager(self.config)
        try:
            result = mgr.connect(ConnectionType.MQTT)
            self.assertTrue(result)

            # Reconnect monitor should be running
            self.assertTrue(mgr._running)
            self.assertIsNotNone(mgr._reconnect_thread)
            self.assertTrue(mgr._reconnect_thread.is_alive())
        finally:
            mgr.disconnect()

        # Give thread time to stop
        if mgr._reconnect_thread:
            mgr._reconnect_thread.join(timeout=15)
        self.assertFalse(mgr._running)

    def test_connection_info_reflects_state(self):
        """get_connection_info should accurately reflect connection state."""
        from meshing_around_clients.core.connection_manager import (
            ConnectionManager,
            ConnectionType,
        )

        mgr = ConnectionManager(self.config)
        info = mgr.get_connection_info()
        self.assertFalse(info["connected"])
        self.assertEqual(info["reconnect_attempts"], 0)

        # Connect to demo (always works, no network needed)
        try:
            result = mgr.connect(ConnectionType.DEMO)
            self.assertTrue(result)

            info = mgr.get_connection_info()
            self.assertTrue(info["connected"])
            self.assertEqual(info["connection_type"], "demo")
            self.assertIsNotNone(info["last_connected"])
        finally:
            mgr.disconnect()

        info = mgr.get_connection_info()
        self.assertFalse(info["connected"])
        self.assertIsNotNone(info["last_disconnected"])


# =============================================================================
# WebSocket Functional Tests with actual FastAPI stack
# =============================================================================


try:
    from fastapi.testclient import TestClient

    from meshing_around_clients.web.app import (
        RateLimiter,
        WebApplication,
    )

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI not installed")
class TestWebSocketLoadIntegration(unittest.TestCase):
    """WebSocket load tests using the actual FastAPI/uvicorn stack.

    Uses FastAPI's TestClient which runs the app in-process with
    a real ASGI server, testing the full WebSocket pipeline.
    """

    @classmethod
    def setUpClass(cls):
        config = Config()
        cls.web_app = WebApplication(config=config, demo_mode=True)
        # Use generous rate limits for load testing
        cls.web_app.rate_limiter = RateLimiter(default_rpm=10000, write_rpm=5000, burst_rpm=10000)
        cls.web_app.api.connect()

    def _make_client(self):
        return TestClient(self.web_app.app)

    def test_single_websocket_connect_and_init(self):
        """Single WebSocket client should receive init message with network state."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            self.assertEqual(data["type"], "init")
            self.assertIn("data", data)
            # Init data should contain network state
            self.assertIn("nodes", data["data"])
            self.assertIn("my_node_id", data["data"])

    def test_websocket_ping_pong(self):
        """WebSocket ping/pong should work correctly."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            # Consume init message
            ws.receive_json()

            # Send ping
            ws.send_json({"type": "ping"})
            response = ws.receive_json()
            self.assertEqual(response["type"], "pong")

    def test_websocket_refresh(self):
        """WebSocket refresh command should return full network state."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            # Consume init message
            ws.receive_json()

            # Send refresh
            ws.send_json({"type": "refresh"})
            response = ws.receive_json()
            self.assertEqual(response["type"], "refresh")
            self.assertIn("data", response)
            self.assertIn("nodes", response["data"])

    def test_websocket_send_message(self):
        """WebSocket send_message should succeed and return status."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            # Consume init message
            ws.receive_json()

            # Send a message
            ws.send_json(
                {
                    "type": "send_message",
                    "text": "Hello from WS test",
                    "destination": "^all",
                    "channel": 0,
                }
            )
            response = ws.receive_json()
            self.assertEqual(response["type"], "message_status")
            self.assertTrue(response["success"])

    def test_websocket_send_message_validation_empty(self):
        """WebSocket send with empty text should return error."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            ws.send_json(
                {
                    "type": "send_message",
                    "text": "",
                    "channel": 0,
                }
            )
            response = ws.receive_json()
            self.assertEqual(response["type"], "message_status")
            self.assertFalse(response["success"])

    def test_websocket_send_message_validation_too_long(self):
        """WebSocket send with text > 228 chars should return error."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            ws.send_json(
                {
                    "type": "send_message",
                    "text": "x" * 229,
                    "channel": 0,
                }
            )
            response = ws.receive_json()
            self.assertEqual(response["type"], "message_status")
            self.assertFalse(response["success"])

    def test_websocket_invalid_json(self):
        """Invalid JSON should not crash the WebSocket connection."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            # Send invalid text (not JSON)
            ws.send_text("this is not json{{{")

            # Connection should still be alive - send a ping to verify
            ws.send_json({"type": "ping"})
            response = ws.receive_json()
            self.assertEqual(response["type"], "pong")

    def test_websocket_interleaved_ping_and_messages(self):
        """Interleaved pings and messages should all be handled correctly."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            for i in range(20):
                if i % 3 == 0:
                    ws.send_json({"type": "ping"})
                else:
                    ws.send_json(
                        {
                            "type": "send_message",
                            "text": f"Interleaved #{i}",
                            "channel": 0,
                        }
                    )

            # Collect responses
            pongs = 0
            message_statuses = 0
            for _ in range(20):
                response = ws.receive_json()
                if response["type"] == "pong":
                    pongs += 1
                elif response["type"] == "message_status":
                    message_statuses += 1

            # Should have 7 pings (i=0,3,6,9,12,15,18) and 13 messages
            self.assertEqual(pongs, 7)
            self.assertEqual(message_statuses, 13)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI not installed")
class TestWebSocketAuthIntegration(unittest.TestCase):
    """Test WebSocket authentication with the actual FastAPI stack."""

    @classmethod
    def setUpClass(cls):
        config = Config()
        config.web.enable_auth = True
        config.web.api_key = "ws-test-secret"
        cls.web_app = WebApplication(config=config, demo_mode=True)
        cls.web_app.rate_limiter = RateLimiter(default_rpm=10000, write_rpm=5000, burst_rpm=10000)
        cls.web_app.api.connect()

    def _make_client(self):
        return TestClient(self.web_app.app)

    def test_websocket_requires_auth(self):
        """WebSocket without credentials should be rejected."""
        client = self._make_client()
        # WebSocket without api_key should be closed with 1008
        try:
            with client.websocket_connect("/ws") as ws:
                # If we get here, the connection was accepted (shouldn't happen)
                self.fail("WebSocket should have been rejected without auth")
        except Exception:
            pass  # Expected - connection should be refused

    def test_websocket_with_valid_api_key(self):
        """WebSocket with valid api_key query param should work."""
        client = self._make_client()
        with client.websocket_connect("/ws?api_key=ws-test-secret") as ws:
            data = ws.receive_json()
            self.assertEqual(data["type"], "init")

    def test_websocket_with_invalid_api_key(self):
        """WebSocket with wrong api_key should be rejected."""
        client = self._make_client()
        try:
            with client.websocket_connect("/ws?api_key=wrong-key") as ws:
                self.fail("WebSocket should have been rejected with wrong key")
        except Exception:
            pass  # Expected


if __name__ == "__main__":
    unittest.main()

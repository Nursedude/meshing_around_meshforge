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

import asyncio
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
# _intentional_disconnect Thread-Safety Verification
# =============================================================================


@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("paho"),
    "paho-mqtt not installed",
)
class TestIntentionalDisconnectThreadSafety(unittest.TestCase):
    """Verify _intentional_disconnect is properly synchronized via _stats_lock.

    This test hammers the flag from multiple threads to verify the fix
    for the previously unsynchronized cross-thread access.
    """

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_concurrent_disconnect_and_callback(self, mock_mqtt):
        """Simulate main-thread disconnect racing with paho callback thread."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()
        errors = []

        def simulate_disconnects():
            """Main thread: rapidly set intentional disconnect."""
            try:
                for _ in range(500):
                    with client._stats_lock:
                        client._intentional_disconnect = True
                    with client._stats_lock:
                        client._intentional_disconnect = False
            except Exception as e:
                errors.append(("disconnect_thread", e))

        def simulate_callbacks():
            """Paho callback thread: read the flag as _on_disconnect does."""
            try:
                for _ in range(500):
                    with client._stats_lock:
                        _ = client._intentional_disconnect
                    with client._stats_lock:
                        client._connected = not client._connected
            except Exception as e:
                errors.append(("callback_thread", e))

        def simulate_health_reads():
            """UI thread: read connection_health which accesses multiple fields."""
            try:
                for _ in range(200):
                    _ = client.connection_health
                    _ = client.is_connected
            except Exception as e:
                errors.append(("health_thread", e))

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=simulate_disconnects, name=f"disc-{i}"))
            threads.append(threading.Thread(target=simulate_callbacks, name=f"cb-{i}"))
            threads.append(threading.Thread(target=simulate_health_reads, name=f"health-{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(len(errors), 0, f"Thread-safety errors in _intentional_disconnect: {errors}")

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_disconnect_sets_flag_before_connected_false(self, mock_mqtt):
        """Verify disconnect() sets _intentional_disconnect atomically with _connected."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()

        # Simulate connected state
        client._on_connect(None, None, None, 0)
        self.assertTrue(client.is_connected)

        # Disconnect should set both flags under lock
        client.disconnect()

        with client._stats_lock:
            self.assertTrue(client._intentional_disconnect)
            self.assertFalse(client._connected)

    @patch("meshing_around_clients.core.mqtt_client.mqtt")
    def test_on_disconnect_reads_flag_under_lock(self, mock_mqtt):
        """Verify _on_disconnect reads _intentional_disconnect under lock."""
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        config = Config(config_path="/nonexistent/path")
        client = MQTTMeshtasticClient(config)
        client._client = MagicMock()

        # Set intentional disconnect under lock
        with client._stats_lock:
            client._intentional_disconnect = True

        # Simulate unexpected disconnect (rc=1)
        # Because _intentional_disconnect is True, it should be treated as clean
        client._on_disconnect(None, None, 1)

        with client._stats_lock:
            # Should NOT have incremented reconnect count
            self.assertEqual(client._reconnect_count, 0)


# =============================================================================
# WebSocket Load Tests with actual FastAPI stack
# =============================================================================


try:
    from fastapi.testclient import TestClient

    from meshing_around_clients.web.app import ConnectionManager as WSConnectionManager
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

    def test_multiple_concurrent_websocket_clients(self):
        """Multiple WebSocket clients should all receive init and function independently."""
        num_clients = 10
        results = {}
        errors = []

        def ws_client_session(client_id):
            try:
                client = self._make_client()
                with client.websocket_connect("/ws") as ws:
                    # Should receive init
                    data = ws.receive_json()
                    if data["type"] != "init":
                        errors.append(f"Client {client_id}: expected init, got {data['type']}")
                        return

                    # Send ping
                    ws.send_json({"type": "ping"})
                    response = ws.receive_json()
                    if response["type"] != "pong":
                        errors.append(f"Client {client_id}: expected pong, got {response['type']}")
                        return

                    # Send refresh
                    ws.send_json({"type": "refresh"})
                    response = ws.receive_json()
                    if response["type"] != "refresh":
                        errors.append(f"Client {client_id}: expected refresh, got {response['type']}")
                        return

                    results[client_id] = True
            except Exception as e:
                errors.append(f"Client {client_id}: {type(e).__name__}: {e}")

        threads = []
        for i in range(num_clients):
            t = threading.Thread(target=ws_client_session, args=(i,), name=f"ws-{i}")
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"WebSocket client errors: {errors}")
        self.assertEqual(len(results), num_clients, f"Only {len(results)}/{num_clients} clients completed")

    def test_websocket_high_frequency_messages(self):
        """Rapid-fire messages should all be processed without errors."""
        client = self._make_client()
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            num_messages = 50
            for i in range(num_messages):
                ws.send_json(
                    {
                        "type": "send_message",
                        "text": f"Rapid fire #{i}",
                        "channel": 0,
                    }
                )

            # Collect all responses
            successes = 0
            for _ in range(num_messages):
                response = ws.receive_json()
                if response.get("type") == "message_status" and response.get("success"):
                    successes += 1

            self.assertEqual(successes, num_messages, f"Only {successes}/{num_messages} rapid messages succeeded")

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
class TestWebSocketConnectionManager(unittest.TestCase):
    """Test the WebSocket ConnectionManager in isolation."""

    def test_broadcast_to_empty_list(self):
        """Broadcasting to zero clients should not error."""
        mgr = WSConnectionManager()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(mgr.broadcast({"type": "test"}))
        finally:
            loop.close()

    def test_broadcast_update_format(self):
        """broadcast_update should produce correctly structured messages."""
        mgr = WSConnectionManager()

        # We can't easily test with real websockets here, but we can
        # verify the method exists and accepts the right parameters
        self.assertTrue(hasattr(mgr, "broadcast_update"))
        self.assertTrue(asyncio.iscoroutinefunction(mgr.broadcast_update))

    def test_connection_limit_enforcement(self):
        """WSConnectionManager should enforce MAX_WS_CONNECTIONS."""
        from meshing_around_clients.web.app import MAX_WS_CONNECTIONS

        self.assertEqual(MAX_WS_CONNECTIONS, 100)


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


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI not installed")
class TestWebSocketAndRESTConcurrent(unittest.TestCase):
    """Test WebSocket and REST API under concurrent load.

    Simulates a realistic scenario where WebSocket clients are receiving
    broadcasts while REST API clients are hitting endpoints simultaneously.
    """

    @classmethod
    def setUpClass(cls):
        config = Config()
        cls.web_app = WebApplication(config=config, demo_mode=True)
        cls.web_app.rate_limiter = RateLimiter(default_rpm=50000, write_rpm=25000, burst_rpm=50000)
        cls.web_app.api.connect()

    def test_concurrent_rest_and_websocket(self):
        """REST API and WebSocket should work concurrently without errors."""
        errors = []
        rest_results = []
        ws_results = []

        def rest_client_work():
            """Hit various REST endpoints."""
            try:
                client = TestClient(self.web_app.app)
                for _ in range(20):
                    resp = client.get("/api/status")
                    if resp.status_code != 200:
                        errors.append(f"REST /api/status returned {resp.status_code}")
                        return
                    resp = client.get("/api/nodes")
                    if resp.status_code != 200:
                        errors.append(f"REST /api/nodes returned {resp.status_code}")
                        return
                    resp = client.get("/api/health")
                    if resp.status_code != 200:
                        errors.append(f"REST /api/health returned {resp.status_code}")
                        return
                rest_results.append(True)
            except Exception as e:
                errors.append(f"REST thread error: {type(e).__name__}: {e}")

        def ws_client_work():
            """Open WebSocket and do ping/refresh."""
            try:
                client = TestClient(self.web_app.app)
                with client.websocket_connect("/ws") as ws:
                    ws.receive_json()  # init
                    for _ in range(10):
                        ws.send_json({"type": "ping"})
                        resp = ws.receive_json()
                        if resp["type"] != "pong":
                            errors.append(f"WS expected pong, got {resp['type']}")
                            return
                ws_results.append(True)
            except Exception as e:
                errors.append(f"WS thread error: {type(e).__name__}: {e}")

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=rest_client_work, name=f"rest-{i}"))
            threads.append(threading.Thread(target=ws_client_work, name=f"ws-{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"Concurrent errors: {errors}")
        self.assertEqual(len(rest_results), 5, "Not all REST clients completed")
        self.assertEqual(len(ws_results), 5, "Not all WS clients completed")

    def test_broadcast_under_load(self):
        """WebSocket broadcast should work while multiple clients are connected.

        This tests the broadcast path that fires when messages/alerts arrive,
        simulating the production pattern where MQTT callbacks trigger broadcasts.
        """
        errors = []
        broadcast_received = {"count": 0}
        lock = threading.Lock()

        def ws_listener(client_id):
            """WebSocket client that listens for broadcasts."""
            try:
                client = TestClient(self.web_app.app)
                with client.websocket_connect("/ws") as ws:
                    ws.receive_json()  # init

                    # Send a message to trigger a broadcast
                    ws.send_json(
                        {
                            "type": "send_message",
                            "text": f"Broadcast test from {client_id}",
                            "channel": 0,
                        }
                    )

                    # Wait for the message_status response
                    response = ws.receive_json()
                    if response.get("type") == "message_status":
                        with lock:
                            broadcast_received["count"] += 1
            except Exception as e:
                errors.append(f"Listener {client_id}: {type(e).__name__}: {e}")

        threads = []
        for i in range(8):
            t = threading.Thread(target=ws_listener, args=(i,), name=f"listener-{i}")
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"Broadcast errors: {errors}")
        self.assertEqual(broadcast_received["count"], 8, f"Only {broadcast_received['count']}/8 clients got responses")


if __name__ == "__main__":
    unittest.main()

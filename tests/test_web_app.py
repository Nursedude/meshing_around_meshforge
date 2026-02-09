"""
Unit tests for meshing_around_clients.web.app

Tests all web API endpoints, CSRF protection, rate limiting,
message search/filter, and WebSocket functionality.
"""

import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from fastapi.testclient import TestClient  # noqa: E402

from meshing_around_clients.core.config import Config  # noqa: E402
from meshing_around_clients.web.app import (  # noqa: E402
    CSRFProtection,
    RateLimiter,
    WebApplication,
    create_app,
)


def _make_app(demo_mode=True, enable_auth=False, api_key=""):
    """Create a test WebApplication in demo mode."""
    config = Config()
    config.web.enable_auth = enable_auth
    config.web.api_key = api_key
    web_app = WebApplication(config=config, demo_mode=demo_mode)
    # Connect the demo API so we have test data
    if demo_mode:
        web_app.api.connect()
    return web_app


class TestCSRFProtection(unittest.TestCase):
    """Test CSRF token generation and validation."""

    def setUp(self):
        self.csrf = CSRFProtection()

    def test_generate_token_length(self):
        token = self.csrf.generate_token()
        # 32 bytes = 64 hex chars
        self.assertEqual(len(token), 64)

    def test_generate_token_uniqueness(self):
        tokens = {self.csrf.generate_token() for _ in range(100)}
        self.assertEqual(len(tokens), 100)

    def test_validate_safe_methods(self):
        """GET/HEAD/OPTIONS should always pass CSRF check."""
        for method in ("GET", "HEAD", "OPTIONS"):
            request = MagicMock()
            request.method = method
            self.assertTrue(self.csrf.validate_request(request))

    def test_validate_api_key_exempt(self):
        """Requests with X-API-Key header are exempt from CSRF."""
        request = MagicMock()
        request.method = "POST"
        request.headers = {"X-API-Key": "test-key"}
        self.assertTrue(self.csrf.validate_request(request))

    def test_validate_bearer_exempt(self):
        """Requests with Bearer auth are exempt from CSRF."""
        request = MagicMock()
        request.method = "POST"
        request.headers = {"Authorization": "Bearer some-token", "Content-Type": "text/html"}
        request.cookies = {}
        self.assertTrue(self.csrf.validate_request(request))

    def test_validate_json_without_cookie(self):
        """First JSON request without cookie should pass."""
        request = MagicMock()
        request.method = "POST"
        request.headers = {"Content-Type": "application/json"}
        request.cookies = {}
        self.assertTrue(self.csrf.validate_request(request))

    def test_validate_json_with_matching_tokens(self):
        """JSON request with matching cookie and header tokens should pass."""
        token = self.csrf.generate_token()
        request = MagicMock()
        request.method = "POST"
        request.headers = {"Content-Type": "application/json", "x-csrf-token": token}
        request.cookies = {"csrf_token": token}
        self.assertTrue(self.csrf.validate_request(request))

    def test_validate_json_with_mismatched_tokens(self):
        """JSON request with mismatched tokens should fail."""
        request = MagicMock()
        request.method = "POST"
        request.headers = {"Content-Type": "application/json", "x-csrf-token": "wrong"}
        request.cookies = {"csrf_token": "correct"}
        self.assertFalse(self.csrf.validate_request(request))

    def test_validate_form_post_missing_tokens(self):
        """Form POST without CSRF tokens should fail."""
        request = MagicMock()
        request.method = "POST"
        request.headers = {"Content-Type": "application/x-www-form-urlencoded"}
        request.cookies = {}
        self.assertFalse(self.csrf.validate_request(request))

    def test_validate_form_post_with_matching_tokens(self):
        """Form POST with matching cookie and header tokens should pass."""
        token = self.csrf.generate_token()
        request = MagicMock()
        request.method = "POST"
        request.headers = {"Content-Type": "application/x-www-form-urlencoded", "x-csrf-token": token}
        request.cookies = {"csrf_token": token}
        self.assertTrue(self.csrf.validate_request(request))


class TestRateLimiter(unittest.TestCase):
    """Test rate limiting logic."""

    def test_allows_within_limit(self):
        limiter = RateLimiter(default_rpm=5)
        for _ in range(5):
            allowed, _ = limiter.check("127.0.0.1")
            self.assertTrue(allowed)

    def test_blocks_over_limit(self):
        limiter = RateLimiter(default_rpm=3)
        for _ in range(3):
            limiter.check("127.0.0.1")
        allowed, headers = limiter.check("127.0.0.1")
        self.assertFalse(allowed)
        self.assertEqual(headers["X-RateLimit-Remaining"], "0")

    def test_different_ips_independent(self):
        limiter = RateLimiter(default_rpm=2)
        limiter.check("10.0.0.1")
        limiter.check("10.0.0.1")
        # Second IP should still be allowed
        allowed, _ = limiter.check("10.0.0.2")
        self.assertTrue(allowed)

    def test_write_category_lower_limit(self):
        limiter = RateLimiter(default_rpm=100, write_rpm=2)
        limiter.check("127.0.0.1", "write")
        limiter.check("127.0.0.1", "write")
        allowed, _ = limiter.check("127.0.0.1", "write")
        self.assertFalse(allowed)

    def test_headers_present(self):
        limiter = RateLimiter(default_rpm=10)
        _, headers = limiter.check("127.0.0.1")
        self.assertIn("X-RateLimit-Limit", headers)
        self.assertIn("X-RateLimit-Remaining", headers)
        self.assertIn("X-RateLimit-Reset", headers)
        self.assertEqual(headers["X-RateLimit-Limit"], "10")


class TestWebAPIEndpoints(unittest.TestCase):
    """Test all web API endpoints via TestClient."""

    @classmethod
    def setUpClass(cls):
        cls.web_app = _make_app(demo_mode=True)
        # Use generous rate limits for test suite
        cls.web_app.rate_limiter = RateLimiter(default_rpm=1000, write_rpm=500, burst_rpm=1000)
        cls.client = TestClient(cls.web_app.app)

    # ---- HTML Pages ----

    def test_index_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])

    def test_nodes_page(self):
        resp = self.client.get("/nodes")
        self.assertEqual(resp.status_code, 200)

    def test_messages_page(self):
        resp = self.client.get("/messages")
        self.assertEqual(resp.status_code, 200)

    def test_alerts_page(self):
        resp = self.client.get("/alerts")
        self.assertEqual(resp.status_code, 200)

    def test_topology_page(self):
        resp = self.client.get("/topology")
        self.assertEqual(resp.status_code, 200)

    def test_map_page(self):
        resp = self.client.get("/map")
        self.assertEqual(resp.status_code, 200)

    # ---- CSRF Token Endpoint ----

    def test_csrf_token_endpoint(self):
        resp = self.client.get("/api/csrf-token")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("csrf_token", data)
        self.assertEqual(len(data["csrf_token"]), 64)
        # Should set a cookie
        self.assertIn("csrf_token", resp.cookies)

    # ---- Status API ----

    def test_api_status(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("connected", data)
        self.assertIn("node_count", data)
        self.assertIn("demo_mode", data)
        self.assertTrue(data["demo_mode"])

    # ---- Network API ----

    def test_api_network(self):
        resp = self.client.get("/api/network")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("nodes", data)
        self.assertIn("my_node_id", data)

    # ---- Nodes API ----

    def test_api_nodes(self):
        resp = self.client.get("/api/nodes")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("nodes", data)
        self.assertIn("total", data)
        self.assertIn("online", data)
        self.assertGreater(data["total"], 0)

    def test_api_node_by_id(self):
        # Get a node ID from the list first
        nodes = self.client.get("/api/nodes").json()["nodes"]
        if nodes:
            node_id = nodes[0]["node_id"]
            resp = self.client.get(f"/api/nodes/{node_id}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["node_id"], node_id)

    def test_api_node_not_found(self):
        resp = self.client.get("/api/nodes/!nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_api_node_neighbors(self):
        nodes = self.client.get("/api/nodes").json()["nodes"]
        if nodes:
            node_id = nodes[0]["node_id"]
            resp = self.client.get(f"/api/nodes/{node_id}/neighbors")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["node_id"], node_id)
            self.assertIn("neighbors", data)

    def test_api_node_neighbors_not_found(self):
        resp = self.client.get("/api/nodes/!nonexistent/neighbors")
        self.assertEqual(resp.status_code, 404)

    # ---- Messages API ----

    def test_api_messages(self):
        resp = self.client.get("/api/messages")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("messages", data)
        self.assertIn("total", data)

    def test_api_messages_with_channel_filter(self):
        resp = self.client.get("/api/messages?channel=0")
        self.assertEqual(resp.status_code, 200)

    def test_api_messages_with_limit(self):
        resp = self.client.get("/api/messages?limit=5")
        self.assertEqual(resp.status_code, 200)

    # ---- Message Search/Filter ----

    def test_api_messages_search_text(self):
        # Send a message first so we have something to search
        self.client.post(
            "/api/messages/send",
            json={"text": "unique_search_term_xyz", "channel": 0},
            headers={"Content-Type": "application/json"},
        )
        resp = self.client.get("/api/messages?search=unique_search_term_xyz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for msg in data["messages"]:
            self.assertIn("unique_search_term_xyz", msg.get("text", "").lower())

    def test_api_messages_search_no_match(self):
        resp = self.client.get("/api/messages?search=zzzznowaythisexists")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 0)

    def test_api_messages_filter_sender(self):
        resp = self.client.get("/api/messages?sender=Me")
        self.assertEqual(resp.status_code, 200)

    def test_api_messages_invalid_since(self):
        resp = self.client.get("/api/messages?since=not-a-date")
        self.assertEqual(resp.status_code, 400)

    def test_api_messages_valid_since(self):
        resp = self.client.get("/api/messages?since=2020-01-01T00:00:00Z")
        self.assertEqual(resp.status_code, 200)

    # ---- Send Message API ----

    def test_api_send_message(self):
        resp = self.client.post(
            "/api/messages/send",
            json={"text": "Hello mesh!", "channel": 0},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "sent")

    def test_api_send_message_empty(self):
        resp = self.client.post(
            "/api/messages/send",
            json={"text": "", "channel": 0},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_send_message_too_long(self):
        resp = self.client.post(
            "/api/messages/send",
            json={"text": "x" * 229, "channel": 0},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_send_message_invalid_channel(self):
        resp = self.client.post(
            "/api/messages/send",
            json={"text": "test", "channel": 9},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 400)

    # ---- Alerts API ----

    def test_api_alerts(self):
        resp = self.client.get("/api/alerts")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("alerts", data)
        self.assertIn("total", data)
        self.assertIn("unread", data)

    def test_api_alerts_unread_only(self):
        resp = self.client.get("/api/alerts?unread_only=true")
        self.assertEqual(resp.status_code, 200)

    # ---- Topology API ----

    def test_api_topology(self):
        resp = self.client.get("/api/topology")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("nodes", data)
        self.assertIn("routes", data)
        self.assertIn("edges", data)
        self.assertIn("total_nodes", data)

    # ---- Health API ----

    def test_api_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("score", data)

    # ---- Channels API ----

    def test_api_channels(self):
        resp = self.client.get("/api/channels")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("channels", data)
        self.assertIn("active_count", data)

    # ---- Routes API ----

    def test_api_routes(self):
        resp = self.client.get("/api/routes")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("routes", data)
        self.assertIn("total", data)

    # ---- GeoJSON API ----

    def test_api_geojson(self):
        resp = self.client.get("/api/geojson")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertIn("features", data)

    # ---- Congestion API ----

    def test_api_congestion(self):
        resp = self.client.get("/api/congestion")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("nodes", data)
        self.assertIn("total", data)

    # ---- Traceroute API ----

    def test_api_traceroute(self):
        resp = self.client.get("/api/traceroute")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("routes", data)
        self.assertIn("total", data)

    # ---- Connect/Disconnect API ----

    def test_api_connect(self):
        resp = self.client.post(
            "/api/connect",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_api_disconnect(self):
        resp = self.client.post(
            "/api/disconnect",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "disconnected")

    # ---- Config API ----

    def test_api_config(self):
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("web", data)
        self.assertIn("mqtt", data)


class TestWebAuthEndpoints(unittest.TestCase):
    """Test endpoints that require authentication."""

    @classmethod
    def setUpClass(cls):
        cls.web_app = _make_app(demo_mode=True, enable_auth=True, api_key="test-secret-key")
        cls.web_app.rate_limiter = RateLimiter(default_rpm=1000, write_rpm=500, burst_rpm=1000)
        cls.client = TestClient(cls.web_app.app)

    def test_send_message_unauthorized(self):
        """POST without API key should return 401."""
        resp = self.client.post(
            "/api/messages/send",
            json={"text": "test", "channel": 0},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_send_message_with_api_key(self):
        """POST with valid API key should succeed."""
        resp = self.client.post(
            "/api/messages/send",
            json={"text": "authed message", "channel": 0},
            headers={"Content-Type": "application/json", "X-API-Key": "test-secret-key"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_send_message_wrong_api_key(self):
        """POST with wrong API key should return 401."""
        resp = self.client.post(
            "/api/messages/send",
            json={"text": "test", "channel": 0},
            headers={"Content-Type": "application/json", "X-API-Key": "wrong-key"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_config_unauthorized(self):
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 401)

    def test_config_authorized(self):
        resp = self.client.get("/api/config", headers={"X-API-Key": "test-secret-key"})
        self.assertEqual(resp.status_code, 200)

    def test_connect_unauthorized(self):
        resp = self.client.post(
            "/api/connect",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_disconnect_unauthorized(self):
        resp = self.client.post(
            "/api/disconnect",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_public_endpoints_no_auth_needed(self):
        """Public endpoints should work without auth."""
        for path in [
            "/api/status",
            "/api/nodes",
            "/api/messages",
            "/api/alerts",
            "/api/health",
            "/api/channels",
            "/api/routes",
            "/api/geojson",
            "/api/congestion",
            "/api/traceroute",
            "/api/topology",
            "/api/csrf-token",
        ]:
            resp = self.client.get(path)
            self.assertIn(resp.status_code, [200], f"Failed for {path}: {resp.status_code}")


class TestRateLimitMiddleware(unittest.TestCase):
    """Test rate limiting middleware via HTTP requests."""

    def test_rate_limit_headers_present(self):
        web_app = _make_app(demo_mode=True)
        client = TestClient(web_app.app)
        resp = client.get("/api/status")
        self.assertIn("x-ratelimit-limit", resp.headers)
        self.assertIn("x-ratelimit-remaining", resp.headers)

    def test_rate_limit_429_on_excess(self):
        """Verify 429 is returned when rate limit is exceeded."""
        web_app = _make_app(demo_mode=True)
        # Set very low limit for testing
        web_app.rate_limiter = RateLimiter(default_rpm=3, write_rpm=2, burst_rpm=5)
        client = TestClient(web_app.app)

        # Exhaust the limit
        for _ in range(3):
            resp = client.get("/api/status")
            self.assertEqual(resp.status_code, 200)

        # Next request should be rate limited
        resp = client.get("/api/status")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Retry-After", resp.headers)


class TestCSRFMiddleware(unittest.TestCase):
    """Test CSRF middleware via HTTP requests."""

    def test_csrf_cookie_set_on_first_request(self):
        web_app = _make_app(demo_mode=True)
        client = TestClient(web_app.app)
        resp = client.get("/")
        self.assertIn("csrf_token", resp.cookies)

    def test_json_post_allowed_without_csrf(self):
        """JSON POST without prior cookie should work (first request scenario)."""
        web_app = _make_app(demo_mode=True)
        client = TestClient(web_app.app)
        resp = client.post(
            "/api/messages/send",
            json={"text": "test", "channel": 0},
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_json_post_with_valid_csrf(self):
        """JSON POST with matching CSRF tokens should work."""
        web_app = _make_app(demo_mode=True)
        client = TestClient(web_app.app)

        # Get a CSRF token
        token_resp = client.get("/api/csrf-token")
        token = token_resp.json()["csrf_token"]

        resp = client.post(
            "/api/messages/send",
            json={"text": "csrf test", "channel": 0},
            headers={
                "Content-Type": "application/json",
                "X-CSRF-Token": token,
            },
            cookies={"csrf_token": token},
        )
        self.assertEqual(resp.status_code, 200)


class TestCreateApp(unittest.TestCase):
    """Test the create_app factory function."""

    def test_create_app_returns_fastapi(self):
        app = create_app(demo_mode=True)
        self.assertIsNotNone(app)
        self.assertEqual(app.title, "Meshing-Around Web Client")

    def test_create_app_with_config(self):
        config = Config()
        app = create_app(config=config, demo_mode=True)
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()

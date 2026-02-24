"""
Unit tests for meshing_around_clients.web.middleware

Tests cover CSRF protection, rate limiting, and WebSocket management.
"""

import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.web.middleware import (
    CSRFProtection,
    RateLimiter,
    WebSocketManager,
)

# ==================== CSRF Protection Tests ====================


class TestCSRFProtection(unittest.TestCase):
    """Test CSRFProtection class."""

    def setUp(self):
        self.csrf = CSRFProtection()

    def test_generate_token_returns_hex_string(self):
        token = self.csrf.generate_token()
        self.assertIsInstance(token, str)
        # TOKEN_LENGTH=32 bytes -> 64 hex chars
        self.assertEqual(len(token), 64)
        # Should be valid hex
        int(token, 16)

    def test_generate_token_unique(self):
        tokens = {self.csrf.generate_token() for _ in range(10)}
        self.assertEqual(len(tokens), 10)

    def test_safe_methods_always_valid(self):
        for method in ("GET", "HEAD", "OPTIONS"):
            request = self._make_request(method=method)
            self.assertTrue(self.csrf.validate_request(request))

    def test_api_key_exempt(self):
        request = self._make_request(
            method="POST",
            headers={"X-API-Key": "secret-key"},
        )
        self.assertTrue(self.csrf.validate_request(request))

    def test_bearer_auth_exempt(self):
        request = self._make_request(
            method="POST",
            headers={"Authorization": "Bearer some-token"},
        )
        self.assertTrue(self.csrf.validate_request(request))

    def test_json_content_type_without_tokens_allowed(self):
        request = self._make_request(
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        self.assertTrue(self.csrf.validate_request(request))

    def test_json_with_matching_tokens_valid(self):
        token = self.csrf.generate_token()
        request = self._make_request(
            method="POST",
            headers={"Content-Type": "application/json", "x-csrf-token": token},
            cookies={"csrf_token": token},
        )
        self.assertTrue(self.csrf.validate_request(request))

    def test_json_with_mismatched_tokens_invalid(self):
        request = self._make_request(
            method="POST",
            headers={"Content-Type": "application/json", "x-csrf-token": "token-a"},
            cookies={"csrf_token": "token-b"},
        )
        self.assertFalse(self.csrf.validate_request(request))

    def test_form_post_with_matching_tokens_valid(self):
        token = self.csrf.generate_token()
        request = self._make_request(
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "x-csrf-token": token},
            cookies={"csrf_token": token},
        )
        self.assertTrue(self.csrf.validate_request(request))

    def test_form_post_missing_cookie_invalid(self):
        request = self._make_request(
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "x-csrf-token": "token"},
            cookies={},
        )
        self.assertFalse(self.csrf.validate_request(request))

    def test_form_post_missing_header_invalid(self):
        request = self._make_request(
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            cookies={"csrf_token": "token"},
        )
        self.assertFalse(self.csrf.validate_request(request))

    def test_form_post_mismatched_tokens_invalid(self):
        request = self._make_request(
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "x-csrf-token": "aaa"},
            cookies={"csrf_token": "bbb"},
        )
        self.assertFalse(self.csrf.validate_request(request))

    def _make_request(self, method="GET", headers=None, cookies=None):
        """Create a mock Request object."""
        request = MagicMock()
        request.method = method
        _headers = headers or {}
        request.headers = MagicMock()
        request.headers.get = lambda key, default="": _headers.get(key, default)
        request.cookies = cookies or {}
        return request


# ==================== Rate Limiter Tests ====================


class TestRateLimiter(unittest.TestCase):
    """Test RateLimiter class."""

    def test_under_limit_allows(self):
        limiter = RateLimiter(default_rpm=5)
        allowed, headers = limiter.check("192.168.1.1")
        self.assertTrue(allowed)
        self.assertEqual(headers["X-RateLimit-Limit"], "5")

    def test_at_limit_blocks(self):
        limiter = RateLimiter(default_rpm=3)
        for _ in range(3):
            limiter.check("192.168.1.1")
        allowed, headers = limiter.check("192.168.1.1")
        self.assertFalse(allowed)
        self.assertEqual(headers["X-RateLimit-Remaining"], "0")

    def test_different_ips_independent(self):
        limiter = RateLimiter(default_rpm=1)
        limiter.check("192.168.1.1")
        allowed, _ = limiter.check("192.168.1.2")
        self.assertTrue(allowed)

    def test_write_category_uses_write_rpm(self):
        limiter = RateLimiter(default_rpm=100, write_rpm=2)
        for _ in range(2):
            limiter.check("10.0.0.1", category="write")
        allowed, headers = limiter.check("10.0.0.1", category="write")
        self.assertFalse(allowed)
        self.assertEqual(headers["X-RateLimit-Limit"], "2")

    def test_burst_category_uses_burst_rpm(self):
        limiter = RateLimiter(default_rpm=1, burst_rpm=5)
        for _ in range(3):
            limiter.check("10.0.0.1", category="burst")
        allowed, _ = limiter.check("10.0.0.1", category="burst")
        self.assertTrue(allowed)

    def test_remaining_decrements(self):
        limiter = RateLimiter(default_rpm=10)
        # Remaining is calculated before the request is added
        _, h1 = limiter.check("10.0.0.1")
        self.assertEqual(h1["X-RateLimit-Remaining"], "10")
        _, h2 = limiter.check("10.0.0.1")
        self.assertEqual(h2["X-RateLimit-Remaining"], "9")

    def test_get_client_ip_direct(self):
        limiter = RateLimiter()
        request = MagicMock()
        request.client.host = "1.2.3.4"
        request.headers = MagicMock()
        request.headers.get = lambda *a, **kw: ""
        self.assertEqual(limiter.get_client_ip(request), "1.2.3.4")

    def test_get_client_ip_with_trust_proxy(self):
        limiter = RateLimiter(trust_proxy=True)
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.get = lambda key, default="": ("10.0.0.1, 172.16.0.1" if key == "x-forwarded-for" else default)
        request.client.host = "127.0.0.1"
        self.assertEqual(limiter.get_client_ip(request), "10.0.0.1")

    def test_get_client_ip_no_client(self):
        limiter = RateLimiter()
        request = MagicMock()
        request.client = None
        request.headers = MagicMock()
        request.headers.get = lambda *a, **kw: ""
        self.assertEqual(limiter.get_client_ip(request), "unknown")


# ==================== WebSocket Manager Tests ====================


class TestWebSocketManager(unittest.IsolatedAsyncioTestCase):
    """Test WebSocketManager class (async)."""

    async def test_connect_accepts(self):
        manager = WebSocketManager(max_connections=5)
        ws = AsyncMock()
        result = await manager.connect(ws)
        self.assertTrue(result)
        ws.accept.assert_called_once()
        self.assertIn(ws, manager.active_connections)

    async def test_connect_rejects_at_limit(self):
        manager = WebSocketManager(max_connections=1)
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await manager.connect(ws1)
        result = await manager.connect(ws2)
        self.assertFalse(result)
        ws2.close.assert_called_once_with(code=1013, reason="Too many connections")

    async def test_disconnect_removes(self):
        manager = WebSocketManager()
        ws = AsyncMock()
        await manager.connect(ws)
        self.assertIn(ws, manager.active_connections)
        await manager.disconnect(ws)
        self.assertNotIn(ws, manager.active_connections)

    async def test_disconnect_unknown_no_error(self):
        manager = WebSocketManager()
        ws = AsyncMock()
        # Should not raise for unknown websocket
        await manager.disconnect(ws)

    async def test_broadcast_sends_to_all(self):
        manager = WebSocketManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)

        msg = {"type": "update", "data": {}}
        await manager.broadcast(msg)

        ws1.send_json.assert_called_once_with(msg)
        ws2.send_json.assert_called_once_with(msg)

    async def test_broadcast_removes_dead_connections(self):
        manager = WebSocketManager()
        ws_good = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = ConnectionError("gone")

        await manager.connect(ws_good)
        await manager.connect(ws_dead)
        self.assertEqual(len(manager.active_connections), 2)

        await manager.broadcast({"type": "test"})

        # Dead connection should be removed
        self.assertNotIn(ws_dead, manager.active_connections)
        self.assertIn(ws_good, manager.active_connections)

    async def test_broadcast_update_includes_timestamp(self):
        manager = WebSocketManager()
        ws = AsyncMock()
        await manager.connect(ws)

        await manager.broadcast_update("node_update", {"node_id": "!abc"})

        call_args = ws.send_json.call_args[0][0]
        self.assertEqual(call_args["type"], "node_update")
        self.assertIn("timestamp", call_args)
        self.assertIn("data", call_args)


if __name__ == "__main__":
    unittest.main()

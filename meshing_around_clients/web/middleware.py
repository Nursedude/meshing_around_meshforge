"""Reusable middleware and utility classes for the web application.

Extracted from app.py to keep route definitions separate from
cross-cutting concerns (CSRF, rate limiting, WebSocket management).
"""

import hmac
import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple

try:
    from fastapi import Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
except ImportError:
    # Stubs so the module can be imported even when FastAPI is absent.
    class _Stub:
        pass

    Request = WebSocket = WebSocketDisconnect = _Stub  # type: ignore[misc,assignment]
    JSONResponse = _Stub  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


# ==================== CSRF Protection ====================


class CSRFProtection:
    """Double-submit cookie CSRF protection.

    Generates a CSRF token stored in a cookie and expected as a header
    (X-CSRF-Token) on state-changing requests (POST/PUT/DELETE/PATCH).
    Requests with API key or Bearer auth headers are exempt since those
    cannot be forged by cross-origin form submissions.
    """

    COOKIE_NAME = "csrf_token"
    HEADER_NAME = "x-csrf-token"
    TOKEN_LENGTH = 32  # 256-bit token

    def __init__(self):
        pass

    def generate_token(self) -> str:
        """Generate a cryptographically random CSRF token."""
        return secrets.token_hex(self.TOKEN_LENGTH)

    def validate_request(self, request: Request) -> bool:
        """Validate CSRF token for state-changing requests.

        Returns True if the request is valid (safe method, has valid token,
        or is an API-key/Bearer authenticated request).
        """
        # Safe methods don't need CSRF protection
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True

        # API key or Bearer auth requests are not CSRF-vulnerable
        if request.headers.get("X-API-Key"):
            return True
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return True

        # JSON API requests with explicit Content-Type are low-risk
        # (browsers won't send JSON cross-origin without CORS preflight)
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            # Defense-in-depth: validate if both cookie and header are present
            cookie_token = request.cookies.get(self.COOKIE_NAME)
            header_token = request.headers.get(self.HEADER_NAME)
            if cookie_token and header_token:
                return hmac.compare_digest(cookie_token, header_token)
            # JSON requests are CORS-protected — allow without CSRF token
            return True

        # For form submissions: require matching cookie and header/form token
        cookie_token = request.cookies.get(self.COOKIE_NAME)
        header_token = request.headers.get(self.HEADER_NAME)

        if not cookie_token or not header_token:
            return False

        return hmac.compare_digest(cookie_token, header_token)

    def set_cookie(self, response: JSONResponse, token: str) -> None:
        """Set CSRF cookie on a response."""
        response.set_cookie(
            key=self.COOKIE_NAME,
            value=token,
            httponly=False,  # Must be readable by JavaScript for double-submit cookie pattern
            samesite="strict",
            secure=False,  # Set True if using HTTPS
            max_age=3600,
        )


# ==================== Rate Limiting ====================


class RateLimiter:
    """Token-bucket rate limiter for API endpoints.

    Tracks request counts per client IP with configurable limits
    for different endpoint categories.
    """

    def __init__(
        self,
        default_rpm: int = 60,
        burst_rpm: int = 120,
        write_rpm: int = 20,
    ):
        self.default_rpm = default_rpm
        self.burst_rpm = burst_rpm
        self.write_rpm = write_rpm
        # {ip: [(timestamp, count)]} — sliding window
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._window = 60.0  # 1-minute window

    def _cleanup(self, ip: str) -> None:
        """Remove expired entries outside the window."""
        cutoff = time.monotonic() - self._window
        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]

    def check(self, ip: str, category: str = "default") -> Tuple[bool, dict]:
        """Check if request is allowed.

        Returns (allowed, headers) where headers contain rate limit info.
        """
        self._cleanup(ip)

        limit = self.default_rpm
        if category == "write":
            limit = self.write_rpm
        elif category == "burst":
            limit = self.burst_rpm

        current = len(self._requests[ip])
        remaining = max(0, limit - current)

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(time.time() + self._window)),
        }

        if current >= limit:
            return False, headers

        self._requests[ip].append(time.monotonic())
        return True, headers


# ==================== WebSocket Management ====================


class WebSocketManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self, max_connections: int = 100):
        self.active_connections: List[WebSocket] = []
        self._max_connections = max_connections

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept and track a WebSocket connection.

        Returns False if the connection limit has been reached.
        """
        if len(self.active_connections) >= self._max_connections:
            await websocket.close(code=1013, reason="Too many connections")
            return False
        await websocket.accept()
        self.active_connections.append(websocket)
        return True

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except (WebSocketDisconnect, RuntimeError, ConnectionError, OSError):
                dead_connections.append(connection)
            except Exception as e:
                # Catch-all for unexpected transport errors to prevent
                # zombie connections from accumulating
                dead_connections.append(connection)
                logger.debug("Unexpected %s broadcasting to WebSocket client", type(e).__name__)
        for dead in dead_connections:
            self.disconnect(dead)

    async def broadcast_update(self, update_type: str, data: dict):
        """Broadcast an update event."""
        await self.broadcast({"type": update_type, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data})

#!/usr/bin/env python3
"""
Meshing-Around Web Application
A FastAPI-based web interface for monitoring and managing Meshtastic mesh networks.

Features:
- Real-time dashboard with WebSocket updates
- REST API for integration
- Modern responsive UI
- Alert management
- Message history and sending
"""

import asyncio
import json
import logging
import secrets
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Check for required libraries - do NOT auto-install (PEP 668 compliance)
try:
    import uvicorn
    from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Only exit when run directly — allow imports to succeed so callers
    # (e.g. mesh_client.py) can check FASTAPI_AVAILABLE gracefully
    if __name__ == "__main__":
        print("Error: Web dependencies not found.")
        print("Please install them with: pip install fastapi uvicorn jinja2 python-multipart")
        print("  or run: python3 mesh_client.py --install-deps")
        sys.exit(1)

import hashlib  # noqa: E402
import hmac  # noqa: E402

logger = logging.getLogger(__name__)

# WebSocket heartbeat interval (seconds)
WS_HEARTBEAT_INTERVAL = 30
# WebSocket receive timeout (seconds) - should be > heartbeat interval
WS_RECEIVE_TIMEOUT = 90
# Maximum concurrent WebSocket connections
MAX_WS_CONNECTIONS = 100
# Maximum request body size (bytes) — 1 MB
MAX_REQUEST_BODY_SIZE = 1_048_576

from meshing_around_clients.core import Alert, Config, MeshtasticAPI, Message  # noqa: E402
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI  # noqa: E402

# Version
VERSION = "0.5.0-beta"

# Get paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


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
            "X-RateLimit-Reset": str(int(time.monotonic() + self._window)),
        }

        if current >= limit:
            return False, headers

        self._requests[ip].append(time.monotonic())
        return True, headers


# Pydantic models for API
class SendMessageRequest(BaseModel):
    text: str
    destination: str = "^all"
    channel: int = 0


class AlertAcknowledgeRequest(BaseModel):
    alert_id: str


class ConfigUpdateRequest(BaseModel):
    section: str
    key: str
    value: str


class WebSocketManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept and track a WebSocket connection.

        Returns False if the connection limit has been reached.
        """
        if len(self.active_connections) >= MAX_WS_CONNECTIONS:
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


class WebApplication:
    """
    Main web application for Meshing-Around.
    Provides REST API and WebSocket support.
    """

    def __init__(self, config: Optional[Config] = None, demo_mode: bool = False):
        self.config = config or Config()
        self.demo_mode = demo_mode

        # Initialize API
        if demo_mode:
            self.api = MockMeshtasticAPI(self.config)
        else:
            self.api = MeshtasticAPI(self.config)

        # WebSocket manager
        self.ws_manager = WebSocketManager()

        # Security: CSRF protection and rate limiting
        self.csrf = CSRFProtection()
        self.rate_limiter = RateLimiter()

        # Event loop reference for cross-thread async scheduling
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        # Buffer for coroutines scheduled before event loop is available
        self._pending_coros: List = []

        # Create FastAPI app
        self.app = self._create_app()

        # Register callbacks
        self._register_callbacks()

    def _create_app(self) -> FastAPI:
        """Create and configure the FastAPI application."""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup — capture event loop for cross-thread async scheduling
            self._event_loop = asyncio.get_running_loop()
            # Flush any coroutines that were buffered before the loop was ready
            for coro in self._pending_coros:
                self._event_loop.create_task(coro)
            self._pending_coros.clear()
            success = self.api.connect()
            if not success and not self.demo_mode:
                logger.warning(
                    "Device connection failed: %s. "
                    "Dashboard will show no data until connection succeeds. "
                    "Use POST /api/connect to retry or restart with --demo.",
                    self.api.connection_info.error_message,
                )
            yield
            # Shutdown
            self._event_loop = None
            self.api.disconnect()

        app = FastAPI(
            title="Meshing-Around Web Client",
            description="Web interface for Meshtastic mesh network management",
            version=VERSION,
            lifespan=lifespan,
        )

        # ---- Middleware: Security Headers ----
        @app.middleware("http")
        async def security_headers_middleware(request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response

        # ---- Middleware: Request Body Size Limit ----
        @app.middleware("http")
        async def body_size_limit_middleware(request: Request, call_next):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > MAX_REQUEST_BODY_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
            return await call_next(request)

        # ---- Middleware: Rate Limiting ----
        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            client_ip = request.client.host if request.client else "unknown"
            # Determine rate limit category
            category = "default"
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                category = "write"

            allowed, headers = self.rate_limiter.check(client_ip, category)
            if not allowed:
                resp = JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again later."},
                )
                for k, v in headers.items():
                    resp.headers[k] = v
                resp.headers["Retry-After"] = "60"
                return resp

            response = await call_next(request)
            for k, v in headers.items():
                response.headers[k] = v
            return response

        # ---- Middleware: CSRF Protection ----
        @app.middleware("http")
        async def csrf_middleware(request: Request, call_next):
            # Validate CSRF on state-changing requests
            if not self.csrf.validate_request(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing or invalid"},
                )

            response = await call_next(request)

            # Set CSRF cookie if not present on the inbound request AND the
            # route handler hasn't already set one (e.g. /api/csrf-token).
            if not request.cookies.get(CSRFProtection.COOKIE_NAME):
                already_set = any(
                    name == b"set-cookie" and value.startswith(CSRFProtection.COOKIE_NAME.encode() + b"=")
                    for name, value in response.raw_headers
                )
                if not already_set:
                    token = self.csrf.generate_token()
                    response.set_cookie(
                        key=CSRFProtection.COOKIE_NAME,
                        value=token,
                        httponly=False,
                        samesite="strict",
                        max_age=3600,
                    )

            return response

        # Mount static files
        if STATIC_DIR.exists():
            app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        # Setup templates
        if TEMPLATES_DIR.exists():
            templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        else:
            templates = None

        # Store references
        app.state.web_app = self
        app.state.templates = templates

        # Register routes
        self._register_routes(app, templates)

        return app

    def _schedule_async(self, coro):
        """Safely schedule a coroutine from any thread.

        If the event loop is not yet available (during startup),
        the coroutine is buffered and will be flushed once the
        lifespan startup completes.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # Called from a non-async thread — use thread-safe scheduling
            if self._event_loop and self._event_loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, self._event_loop)
            else:
                # Event loop not ready yet — buffer for later
                self._pending_coros.append(coro)

    def _register_callbacks(self):
        """Register API callbacks for real-time updates."""

        def on_message(message: Message):
            self._schedule_async(self.ws_manager.broadcast_update("message", message.to_dict()))

        def on_alert(alert: Alert):
            self._schedule_async(self.ws_manager.broadcast_update("alert", alert.to_dict()))

        def on_node_update(node_id: str, is_new: bool):
            node = self.api.network.nodes.get(node_id)
            if node:
                self._schedule_async(
                    self.ws_manager.broadcast_update("node_new" if is_new else "node_update", node.to_dict())
                )

        self.api.register_callback("on_message", on_message)
        self.api.register_callback("on_alert", on_alert)
        self.api.register_callback("on_node_update", on_node_update)

    def _check_api_auth(self, request: Request) -> None:
        """Check API authentication if enabled in config."""
        if not self.config.web.enable_auth:
            return
        # Check API key in header or query param
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if self.config.web.api_key and api_key:
            if hmac.compare_digest(api_key, self.config.web.api_key):
                return
        # Check basic auth via username/password_hash
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            import base64

            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                username, password = decoded.split(":", 1)
                pw_hash = hashlib.sha256(password.encode()).hexdigest()
                if (
                    hmac.compare_digest(username, self.config.web.username)
                    and self.config.web.password_hash
                    and hmac.compare_digest(pw_hash, self.config.web.password_hash)
                ):
                    return
            except (ValueError, UnicodeDecodeError):
                pass
        client_host = request.client.host if request.client else "unknown"
        logger.info("Authentication failed for API request from %s", client_host)
        raise HTTPException(status_code=401, detail="Unauthorized")

    def _register_routes(self, app: FastAPI, templates):
        """Register all routes."""

        # Auth dependency for API routes
        async def require_auth(request: Request):
            self._check_api_auth(request)

        # ==================== HTML Routes ====================

        @app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            """Main dashboard page."""
            if templates:
                return templates.TemplateResponse(
                    "index.html", {"request": request, "version": VERSION, "demo_mode": self.demo_mode}
                )
            return HTMLResponse(self._get_fallback_html())

        @app.get("/nodes", response_class=HTMLResponse)
        async def nodes_page(request: Request):
            """Nodes list page."""
            if templates:
                return templates.TemplateResponse("nodes.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_fallback_html())

        @app.get("/messages", response_class=HTMLResponse)
        async def messages_page(request: Request):
            """Messages page."""
            if templates:
                return templates.TemplateResponse("messages.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_fallback_html())

        @app.get("/alerts", response_class=HTMLResponse)
        async def alerts_page(request: Request):
            """Alerts page."""
            if templates:
                return templates.TemplateResponse("alerts.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_fallback_html())

        @app.get("/topology", response_class=HTMLResponse)
        async def topology_page(request: Request):
            """Topology visualization page."""
            if templates:
                return templates.TemplateResponse("topology.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_fallback_html("Topology"))

        @app.get("/map", response_class=HTMLResponse)
        async def map_page(request: Request):
            """Map visualization page with Leaflet.js."""
            if templates:
                return templates.TemplateResponse(
                    "map.html",
                    {"request": request, "version": VERSION, "demo_mode": self.demo_mode},
                )
            return HTMLResponse(self._get_fallback_html("Map"))

        # ==================== API Routes ====================

        @app.get("/api/csrf-token")
        async def api_csrf_token(request: Request):
            """Get a CSRF token for state-changing requests.

            The token is also set as a cookie. Include it in the
            X-CSRF-Token header on POST/PUT/DELETE requests.
            """
            token = self.csrf.generate_token()
            response = JSONResponse(content={"csrf_token": token})
            self.csrf.set_cookie(response, token)
            return response

        @app.get("/api/status")
        async def api_status():
            """Get connection and network status."""
            return {
                "connected": self.api.is_connected,
                "interface_type": self.api.connection_info.interface_type,
                "device_path": self.api.connection_info.device_path,
                "my_node_id": self.api.network.my_node_id,
                "node_count": len(self.api.network.nodes),
                "online_nodes": len(self.api.network.online_nodes),
                "message_count": self.api.network.total_messages,
                "unread_alerts": len(self.api.network.unread_alerts),
                "demo_mode": self.demo_mode,
            }

        @app.get("/api/network")
        async def api_network():
            """Get full network state."""
            return self.api.network.to_dict()

        @app.get("/api/nodes")
        async def api_nodes():
            """Get all nodes."""
            nodes = []
            for n in self.api.get_nodes():
                try:
                    nodes.append(n.to_dict())
                except (AttributeError, TypeError, ValueError) as e:
                    logger.warning("Failed to serialize node %s: %s", getattr(n, "node_id", "?"), e)
            return {
                "nodes": nodes,
                "total": len(self.api.network.nodes),
                "online": len(self.api.network.online_nodes),
            }

        @app.get("/api/nodes/{node_id}")
        async def api_node(node_id: str):
            """Get specific node."""
            node = self.api.network.get_node(node_id)
            if not node:
                raise HTTPException(status_code=404, detail="Node not found")
            return node.to_dict()

        @app.get("/api/messages")
        async def api_messages(
            channel: Optional[int] = None,
            limit: int = 100,
            search: Optional[str] = None,
            sender: Optional[str] = None,
            since: Optional[str] = None,
        ):
            """Get messages with optional search/filter.

            Query parameters:
                channel: Filter by channel number (0-7)
                limit: Max messages to return (default 100)
                search: Full-text search in message text (case-insensitive)
                sender: Filter by sender name or ID (case-insensitive substring)
                since: ISO timestamp — only messages after this time
            """
            messages = self.api.get_messages(channel=channel, limit=limit)
            serialized = []

            # Parse 'since' filter
            since_dt = None
            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail="Invalid 'since' timestamp format")

            search_lower = search.lower().strip() if search else None
            sender_lower = sender.lower().strip() if sender else None

            for m in messages:
                try:
                    d = m.to_dict()
                except (AttributeError, TypeError, ValueError) as e:
                    logger.warning("Failed to serialize message: %s", e)
                    continue

                # Apply text search filter
                if search_lower:
                    text = (d.get("text") or "").lower()
                    if search_lower not in text:
                        continue

                # Apply sender filter
                if sender_lower:
                    s_name = (d.get("sender_name") or "").lower()
                    s_id = (d.get("sender_id") or "").lower()
                    if sender_lower not in s_name and sender_lower not in s_id:
                        continue

                # Apply time filter
                if since_dt:
                    msg_time = d.get("timestamp")
                    if msg_time:
                        try:
                            msg_dt = datetime.fromisoformat(str(msg_time).replace("Z", "+00:00"))
                            if msg_dt < since_dt:
                                continue
                        except (ValueError, TypeError):
                            pass

                serialized.append(d)

            return {"messages": serialized, "total": len(serialized)}

        @app.post("/api/messages/send", dependencies=[Depends(require_auth)])
        async def api_send_message(request: SendMessageRequest):
            """Send a message with input validation."""
            # Validate message text
            if not request.text or not request.text.strip():
                raise HTTPException(status_code=400, detail="Message text cannot be empty")
            if len(request.text) > 228:  # Meshtastic max message length
                raise HTTPException(status_code=400, detail="Message too long (max 228 chars)")
            # Validate channel range
            if request.channel < 0 or request.channel > 7:
                raise HTTPException(status_code=400, detail="Channel must be 0-7")
            success = self.api.send_message(request.text.strip(), request.destination, request.channel)
            if success:
                return {"status": "sent", "message": request.text.strip()}
            raise HTTPException(status_code=500, detail="Failed to send message")

        @app.get("/api/alerts")
        async def api_alerts(unread_only: bool = False):
            """Get alerts."""
            alerts = self.api.get_alerts(unread_only=unread_only)
            serialized = []
            for a in alerts:
                try:
                    serialized.append(a.to_dict())
                except (AttributeError, TypeError, ValueError) as e:
                    logger.warning("Failed to serialize alert: %s", e)
            return {
                "alerts": serialized,
                "total": len(serialized),
                "unread": len(self.api.network.unread_alerts),
            }

        @app.post("/api/alerts/acknowledge", dependencies=[Depends(require_auth)])
        async def api_acknowledge_alert(request: AlertAcknowledgeRequest):
            """Acknowledge an alert."""
            success = self.api.acknowledge_alert(request.alert_id)
            if success:
                return {"status": "acknowledged", "alert_id": request.alert_id}
            raise HTTPException(status_code=404, detail="Alert not found")

        @app.post("/api/connect", dependencies=[Depends(require_auth)])
        async def api_connect():
            """Connect to device."""
            success = self.api.connect()
            return {"status": "connected" if success else "failed"}

        @app.post("/api/disconnect", dependencies=[Depends(require_auth)])
        async def api_disconnect():
            """Disconnect from device."""
            self.api.disconnect()
            return {"status": "disconnected"}

        @app.get("/api/config", dependencies=[Depends(require_auth)])
        async def api_config():
            """Get current configuration."""
            return self.config.to_dict()

        # ==================== Topology API ====================

        @app.get("/api/topology")
        async def api_topology():
            """Get mesh topology data including nodes, routes, and relationships."""
            network = self.api.network
            nodes_data = []

            for node in network.nodes.values():
                node_info = {
                    "id": node.node_id,
                    "name": node.display_name,
                    "is_online": node.is_online,
                    "hop_count": node.hop_count,
                    "neighbors": node.neighbors,
                    "heard_by": node.heard_by,
                    "link_quality": node.link_quality.to_dict() if node.link_quality else None,
                }
                nodes_data.append(node_info)

            routes_data = []
            for route in network.routes.values():
                try:
                    routes_data.append(route.to_dict())
                except (AttributeError, TypeError, ValueError) as e:
                    logger.warning("Failed to serialize route: %s", e)

            # Build edges from neighbor relationships
            edges = []
            seen_edges = set()
            for node in network.nodes.values():
                for neighbor_id in node.neighbors:
                    edge_key = tuple(sorted([node.node_id, neighbor_id]))
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({"source": node.node_id, "target": neighbor_id, "type": "neighbor"})

            return {
                "nodes": nodes_data,
                "routes": routes_data,
                "edges": edges,
                "total_nodes": len(network.nodes),
                "online_nodes": len(network.online_nodes),
            }

        @app.get("/api/health")
        async def api_mesh_health():
            """Get mesh network health metrics."""
            return self.api.network.mesh_health

        @app.get("/api/channels")
        async def api_channels():
            """Get channel configurations and activity."""
            network = self.api.network
            channels_data = []

            for idx, channel in sorted(network.channels.items()):
                channels_data.append(channel.to_dict())

            return {"channels": channels_data, "active_count": len(network.get_active_channels())}

        @app.get("/api/routes")
        async def api_routes():
            """Get known mesh routes."""
            routes = []
            for route in self.api.network.routes.values():
                try:
                    routes.append(route.to_dict())
                except (AttributeError, TypeError, ValueError) as e:
                    logger.warning("Failed to serialize route: %s", e)
            return {
                "routes": routes,
                "total": len(routes),
            }

        @app.get("/api/nodes/{node_id}/neighbors")
        async def api_node_neighbors(node_id: str):
            """Get neighbors for a specific node."""
            node = self.api.network.get_node(node_id)
            if not node:
                raise HTTPException(status_code=404, detail="Node not found")
            return {
                "node_id": node_id,
                "neighbors": node.neighbors,
                "heard_by": node.heard_by,
                "link_quality": node.link_quality.to_dict() if node.link_quality else None,
            }

        @app.get("/api/geojson")
        async def api_geojson():
            """Get GeoJSON FeatureCollection of nodes with positions.

            Compatible with Leaflet.js for map visualization.
            From meshforge's map cache pattern.
            """
            if hasattr(self.api, "get_geojson"):
                return self.api.get_geojson()
            # Fallback: build GeoJSON from network nodes
            features = []
            for node in self.api.network.nodes.values():
                if node.position and node.position.is_valid():
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [node.position.longitude, node.position.latitude],
                            },
                            "properties": {
                                "node_id": node.node_id,
                                "name": node.display_name,
                                "is_online": node.is_online,
                            },
                        }
                    )
            return {"type": "FeatureCollection", "features": features}

        @app.get("/api/congestion")
        async def api_congestion():
            """Get nodes with high channel utilization."""
            congested = []
            for node in self.api.network.nodes.values():
                if node.telemetry and node.telemetry.channel_utilization > 0:
                    congested.append(
                        {
                            "node_id": node.node_id,
                            "name": node.display_name,
                            "channel_utilization": node.telemetry.channel_utilization,
                            "air_util_tx": node.telemetry.air_util_tx,
                            "status": node.telemetry.channel_utilization_status,
                        }
                    )
            congested.sort(key=lambda x: x["channel_utilization"], reverse=True)
            return {"nodes": congested, "total": len(congested)}

        @app.get("/api/traceroute")
        async def api_traceroute():
            """Get discovered traceroute data with position info for map visualization.

            Returns routes enriched with node positions so the frontend can
            draw route lines on the map.
            """
            network = self.api.network
            routes_data = []
            for route in network.routes.values():
                route_info = route.to_dict()
                # Enrich hops with position data for map drawing
                enriched_hops = []
                for hop in route.hops:
                    hop_info = hop.to_dict() if hasattr(hop, "to_dict") else {"node_id": hop.node_id, "snr": hop.snr}
                    node = network.get_node(hop.node_id)
                    if node and node.position and node.position.is_valid():
                        hop_info["latitude"] = node.position.latitude
                        hop_info["longitude"] = node.position.longitude
                    enriched_hops.append(hop_info)
                route_info["enriched_hops"] = enriched_hops
                # Add destination position
                dest_node = network.get_node(route.destination_id)
                if dest_node and dest_node.position and dest_node.position.is_valid():
                    route_info["destination_position"] = {
                        "latitude": dest_node.position.latitude,
                        "longitude": dest_node.position.longitude,
                    }
                routes_data.append(route_info)
            return {"routes": routes_data, "total": len(routes_data)}

        # ==================== WebSocket ====================

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket endpoint for real-time updates."""
            # Authenticate before accepting the connection
            if self.config.web.enable_auth:
                api_key = websocket.query_params.get("api_key")
                auth_ok = False
                if self.config.web.api_key and api_key:
                    auth_ok = hmac.compare_digest(api_key, self.config.web.api_key)
                if not auth_ok:
                    # Check Authorization header (some WS clients support it)
                    auth_header = websocket.headers.get("authorization", "")
                    if auth_header.startswith("Basic "):
                        import base64

                        try:
                            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                            username, password = decoded.split(":", 1)
                            pw_hash = hashlib.sha256(password.encode()).hexdigest()
                            if (
                                hmac.compare_digest(username, self.config.web.username)
                                and self.config.web.password_hash
                                and hmac.compare_digest(pw_hash, self.config.web.password_hash)
                            ):
                                auth_ok = True
                        except (ValueError, UnicodeDecodeError):
                            pass
                if not auth_ok:
                    client_host = websocket.client.host if websocket.client else "unknown"
                    logger.info("Authentication failed for WebSocket from %s", client_host)
                    await websocket.close(code=1008, reason="Unauthorized")
                    return

            accepted = await self.ws_manager.connect(websocket)
            if not accepted:
                return  # Connection limit reached
            try:
                # Send initial state
                await websocket.send_json({"type": "init", "data": self.api.network.to_dict()})

                while True:
                    try:
                        # Use timeout to detect dead connections
                        data = await asyncio.wait_for(websocket.receive_text(), timeout=WS_RECEIVE_TIMEOUT)
                        try:
                            msg = json.loads(data)
                            await self._handle_ws_message(websocket, msg)
                        except json.JSONDecodeError:
                            logger.debug("Invalid JSON from WebSocket client")
                    except asyncio.TimeoutError:
                        # No message received within timeout - send ping to check liveness
                        try:
                            await websocket.send_json({"type": "ping"})
                        except (WebSocketDisconnect, RuntimeError, ConnectionError):
                            break  # Client gone

            except WebSocketDisconnect:
                pass
            finally:
                self.ws_manager.disconnect(websocket)

    async def _handle_ws_message(self, websocket: WebSocket, msg: dict):
        """Handle incoming WebSocket message with input validation."""
        msg_type = msg.get("type")

        if msg_type == "ping":
            await websocket.send_json({"type": "pong"})

        elif msg_type == "send_message":
            text = msg.get("text", "")
            dest = msg.get("destination", "^all")
            channel = msg.get("channel", 0)
            # Validate inputs
            if not text or not text.strip():
                await websocket.send_json({"type": "message_status", "success": False, "error": "Empty message"})
                return
            if len(text) > 228:
                await websocket.send_json(
                    {"type": "message_status", "success": False, "error": "Message too long (max 228)"}
                )
                return
            if not isinstance(channel, int) or channel < 0 or channel > 7:
                channel = 0
            success = self.api.send_message(text.strip(), dest, channel)
            await websocket.send_json({"type": "message_status", "success": success})

        elif msg_type == "refresh":
            await websocket.send_json({"type": "refresh", "data": self.api.network.to_dict()})

    def _get_fallback_html(self, page_name: str = "Dashboard") -> str:
        """Return minimal fallback HTML when templates are not available."""
        return f"""<!DOCTYPE html>
<html><head><title>Meshing-Around - {page_name}</title>
<style>body{{font-family:system-ui;background:#0a0a0a;color:#e0e0e0;padding:40px;text-align:center}}
h1{{color:#00d4ff}}a{{color:#00d4ff}}</style></head>
<body><h1>Meshing-Around Web Client</h1>
<p>Templates not found. Ensure the templates directory is present alongside app.py.</p>
<p>API is still available at <a href="/api/status">/api/status</a></p></body></html>"""

    def run(self, host: str = "127.0.0.1", port: int = 8080):
        """Run the web application."""
        uvicorn.run(self.app, host=host, port=port)


def create_app(config: Optional[Config] = None, demo_mode: bool = False) -> FastAPI:
    """Factory function to create the FastAPI app."""
    web_app = WebApplication(config=config, demo_mode=demo_mode)
    return web_app.app


def main():
    """Main entry point for the web application."""
    import argparse

    parser = argparse.ArgumentParser(description="Meshing-Around Web Client")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode without hardware")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    # Load config
    config = Config(args.config) if args.config else Config()
    config.web.host = args.host
    config.web.port = args.port

    print(f"""
    ╔══════════════════════════════════════════════════╗
    ║     Meshing-Around Web Client v{VERSION}            ║
    ╠══════════════════════════════════════════════════╣
    ║  Starting web server...                          ║
    ║  URL: http://{args.host}:{args.port}                      ║
    ║  Demo Mode: {str(args.demo).ljust(36)}║
    ╚══════════════════════════════════════════════════╝
    """)

    # Create and run application
    web_app = WebApplication(config=config, demo_mode=args.demo)

    if args.reload:
        uvicorn.run(
            "meshing_around_clients.web.app:create_app", host=args.host, port=args.port, reload=True, factory=True
        )
    else:
        web_app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()

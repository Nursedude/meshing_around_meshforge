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
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Check for required libraries - do NOT auto-install (PEP 668 compliance)
try:
    import uvicorn
    from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
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

from meshing_around_clients.core import Alert, Config, MeshtasticAPI, Message, MessageHandler  # noqa: E402
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI  # noqa: E402

# Version
VERSION = "0.5.0-beta"

# Get paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


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


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except (WebSocketDisconnect, RuntimeError, ConnectionError):
                dead_connections.append(connection)
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

        # Message handler
        self.message_handler = MessageHandler(self.config)

        # WebSocket manager
        self.ws_manager = ConnectionManager()

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
            if self.demo_mode:
                self.api.connect()
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
            return HTMLResponse(self._get_embedded_html())

        @app.get("/nodes", response_class=HTMLResponse)
        async def nodes_page(request: Request):
            """Nodes list page."""
            if templates:
                return templates.TemplateResponse("nodes.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_embedded_html())

        @app.get("/messages", response_class=HTMLResponse)
        async def messages_page(request: Request):
            """Messages page."""
            if templates:
                return templates.TemplateResponse("messages.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_embedded_html())

        @app.get("/alerts", response_class=HTMLResponse)
        async def alerts_page(request: Request):
            """Alerts page."""
            if templates:
                return templates.TemplateResponse("alerts.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_embedded_html())

        @app.get("/topology", response_class=HTMLResponse)
        async def topology_page(request: Request):
            """Topology visualization page."""
            if templates:
                return templates.TemplateResponse("topology.html", {"request": request, "version": VERSION})
            return HTMLResponse(self._get_topology_html())

        @app.get("/map", response_class=HTMLResponse)
        async def map_page(request: Request):
            """Map visualization page with Leaflet.js."""
            if templates:
                return templates.TemplateResponse(
                    "map.html",
                    {"request": request, "version": VERSION, "demo_mode": self.demo_mode},
                )
            return HTMLResponse(self._get_map_html())

        # ==================== API Routes ====================

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
            return {
                "nodes": [n.to_dict() for n in self.api.get_nodes()],
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
        async def api_messages(channel: Optional[int] = None, limit: int = 100):
            """Get messages."""
            messages = self.api.get_messages(channel=channel, limit=limit)
            return {"messages": [m.to_dict() for m in messages], "total": len(messages)}

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
            return {
                "alerts": [a.to_dict() for a in alerts],
                "total": len(alerts),
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

            routes_data = [route.to_dict() for route in network.routes.values()]

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
            return {
                "routes": [route.to_dict() for route in self.api.network.routes.values()],
                "total": len(self.api.network.routes),
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

            await self.ws_manager.connect(websocket)
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

    def _get_embedded_html(self) -> str:
        """Return embedded HTML when templates are not available."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Meshing-Around Web Client</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: system-ui, -apple-system, sans-serif; background: #0a0a0a; color: #e0e0e0; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        header {
            background: linear-gradient(135deg, #1a1a2e 0%, #0a0a1a 100%);
            padding: 20px; border-radius: 8px; margin-bottom: 20px;
        }
        h1 { color: #00d4ff; font-size: 24px; }
        .grid {
            display: grid; gap: 20px;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        }
        .card { background: #1a1a2e; border-radius: 8px; padding: 20px; border: 1px solid #2a2a4e; }
        .card h2 {
            color: #00d4ff; font-size: 16px; margin-bottom: 15px;
            border-bottom: 1px solid #2a2a4e; padding-bottom: 10px;
        }
        .stat {
            display: flex; justify-content: space-between;
            padding: 10px 0; border-bottom: 1px solid #1a1a2e;
        }
        .stat-label { color: #888; }
        .stat-value { color: #00d4ff; font-weight: bold; }
        .status-connected { color: #00ff88; }
        .status-disconnected { color: #ff4444; }
        #messages, #nodes, #alerts { max-height: 400px; overflow-y: auto; }
        .message, .node, .alert {
            padding: 10px; margin: 5px 0; background: #0a0a1a;
            border-radius: 4px; font-size: 14px;
        }
        .message .time { color: #666; font-size: 12px; }
        .message .sender { color: #00d4ff; }
        .alert.severity-4 { border-left: 3px solid #ff4444; }
        .alert.severity-3 { border-left: 3px solid #ff8800; }
        .alert.severity-2 { border-left: 3px solid #ffcc00; }
        .alert.severity-1 { border-left: 3px solid #00d4ff; }
        .send-form { margin-top: 15px; display: flex; gap: 10px; }
        .send-form input {
            flex: 1; padding: 10px; background: #0a0a1a;
            border: 1px solid #2a2a4e; border-radius: 4px; color: #e0e0e0;
        }
        .send-form button {
            padding: 10px 20px; background: #00d4ff; color: #000;
            border: none; border-radius: 4px; cursor: pointer;
        }
        .send-form button:hover { background: #00a8cc; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Meshing-Around Web Client</h1>
            <p id="connection-status" class="status-disconnected">Connecting...</p>
        </header>

        <div class="grid">
            <div class="card">
                <h2>Network Status</h2>
                <div class="stat"><span class="stat-label">Status</span>
                    <span class="stat-value" id="status">--</span></div>
                <div class="stat"><span class="stat-label">My Node</span>
                    <span class="stat-value" id="my-node">--</span></div>
                <div class="stat"><span class="stat-label">Nodes Online</span>
                    <span class="stat-value" id="nodes-online">--</span></div>
                <div class="stat"><span class="stat-label">Messages</span>
                    <span class="stat-value" id="msg-count">--</span></div>
                <div class="stat"><span class="stat-label">Unread Alerts</span>
                    <span class="stat-value" id="alert-count">--</span></div>
            </div>

            <div class="card">
                <h2>Nodes</h2>
                <div id="nodes"></div>
            </div>

            <div class="card">
                <h2>Messages</h2>
                <div id="messages"></div>
                <div class="send-form">
                    <input type="text" id="message-input" placeholder="Type a message...">
                    <button onclick="sendMessage()">Send</button>
                </div>
            </div>

            <div class="card">
                <h2>Alerts</h2>
                <div id="alerts"></div>
            </div>
        </div>
    </div>

    <script>
        let ws;

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function connect() {
            ws = new WebSocket(`ws://${window.location.host}/ws`);

            ws.onopen = () => {
                document.getElementById('connection-status').textContent = 'Connected';
                document.getElementById('connection-status').className = 'status-connected';
            };

            ws.onclose = () => {
                document.getElementById('connection-status').textContent = 'Disconnected - Reconnecting...';
                document.getElementById('connection-status').className = 'status-disconnected';
                setTimeout(connect, 3000);
            };

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                handleMessage(msg);
            };
        }

        function handleMessage(msg) {
            if (msg.type === 'init' || msg.type === 'refresh') {
                updateDashboard(msg.data);
            } else if (msg.type === 'message') {
                addMessage(msg.data);
            } else if (msg.type === 'alert') {
                addAlert(msg.data);
            } else if (msg.type === 'node_update' || msg.type === 'node_new') {
                updateNode(msg.data);
            }
        }

        function updateDashboard(data) {
            document.getElementById('status').textContent = data.connection_status || 'unknown';
            document.getElementById('my-node').textContent = data.my_node_id || 'N/A';
            document.getElementById('nodes-online').textContent =
                `${data.online_node_count || 0}/${data.total_node_count || 0}`;
            document.getElementById('msg-count').textContent = data.messages?.length || 0;
            document.getElementById('alert-count').textContent = data.unread_alert_count || 0;

            // Update nodes
            const nodesDiv = document.getElementById('nodes');
            nodesDiv.innerHTML = '';
            Object.values(data.nodes || {}).slice(0, 10).forEach(node => {
                const div = document.createElement('div');
                div.className = 'node';
                div.innerHTML = `<strong>${escapeHtml(node.display_name)}</strong>`
                    + ` - ${escapeHtml(node.time_since_heard)}`;
                nodesDiv.appendChild(div);
            });

            // Update messages
            const msgsDiv = document.getElementById('messages');
            msgsDiv.innerHTML = '';
            (data.messages || []).slice(-10).reverse().forEach(msg => {
                addMessageElement(msgsDiv, msg);
            });

            // Update alerts
            const alertsDiv = document.getElementById('alerts');
            alertsDiv.innerHTML = '';
            (data.alerts || []).slice(-5).reverse().forEach(alert => {
                addAlertElement(alertsDiv, alert);
            });
        }

        function addMessage(msg) {
            const msgsDiv = document.getElementById('messages');
            addMessageElement(msgsDiv, msg, true);
        }

        function addMessageElement(container, msg, prepend = false) {
            const div = document.createElement('div');
            div.className = 'message';
            div.innerHTML =
                `<span class="time">${escapeHtml(msg.time_formatted)}</span> `
                + `<span class="sender">${escapeHtml(msg.sender_name || msg.sender_id)}</span>`
                + `: ${escapeHtml(msg.text)}`;
            if (prepend) {
                container.insertBefore(div, container.firstChild);
            } else {
                container.appendChild(div);
            }
        }

        function addAlert(alert) {
            const alertsDiv = document.getElementById('alerts');
            addAlertElement(alertsDiv, alert, true);
            document.getElementById('alert-count').textContent =
                parseInt(document.getElementById('alert-count').textContent) + 1;
        }

        function addAlertElement(container, alert, prepend = false) {
            const div = document.createElement('div');
            div.className = `alert severity-${alert.severity}`;
            div.innerHTML = `<strong>${escapeHtml(alert.title)}</strong><br>${escapeHtml(alert.message)}`;
            if (prepend) {
                container.insertBefore(div, container.firstChild);
            } else {
                container.appendChild(div);
            }
        }

        function updateNode(node) {
            // Refresh to update node list
            fetch('/api/status').then(r => r.json()).then(data => {
                document.getElementById('nodes-online').textContent = `${data.online_nodes}/${data.node_count}`;
            });
        }

        function sendMessage() {
            const input = document.getElementById('message-input');
            const text = input.value.trim();
            if (text && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'send_message',
                    text: text,
                    destination: '^all',
                    channel: 0
                }));
                input.value = '';
            }
        }

        document.getElementById('message-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });

        connect();
    </script>
</body>
</html>
        """

    def _get_topology_html(self) -> str:
        """Return embedded HTML for topology visualization."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mesh Topology - Meshing-Around</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: system-ui, -apple-system, sans-serif; background: #0a0a0a; color: #e0e0e0; }
        .container { max-width: 1600px; margin: 0 auto; padding: 20px; }
        header {
            background: linear-gradient(135deg, #1a1a2e 0%, #0a0a1a 100%);
            padding: 20px; border-radius: 8px; margin-bottom: 20px;
            display: flex; justify-content: space-between;
            align-items: center;
        }
        h1 { color: #00d4ff; font-size: 24px; }
        nav a { color: #00d4ff; text-decoration: none; margin-left: 20px; }
        nav a:hover { text-decoration: underline; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; }
        .card { background: #1a1a2e; border-radius: 8px; padding: 20px; border: 1px solid #2a2a4e; }
        .card h2 {
            color: #00d4ff; font-size: 16px; margin-bottom: 15px;
            border-bottom: 1px solid #2a2a4e; padding-bottom: 10px;
        }
        .health-bar { height: 20px; background: #0a0a1a; border-radius: 10px; overflow: hidden; margin: 10px 0; }
        .health-fill { height: 100%; transition: width 0.3s; }
        .health-excellent { background: linear-gradient(90deg, #00ff88, #00cc66); }
        .health-good { background: linear-gradient(90deg, #00cc66, #88cc00); }
        .health-fair { background: linear-gradient(90deg, #ffcc00, #ff8800); }
        .health-poor { background: linear-gradient(90deg, #ff8800, #ff4444); }
        .health-critical { background: linear-gradient(90deg, #ff4444, #cc0000); }
        .stat { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #1a1a2e; }
        .stat-label { color: #888; }
        .stat-value { color: #00d4ff; font-weight: bold; }
        .node-tree { font-family: monospace; font-size: 13px; }
        .node-tree .branch { margin-left: 20px; border-left: 1px solid #2a2a4e; padding-left: 15px; }
        .node-tree .node { padding: 5px 0; display: flex; align-items: center; gap: 8px; }
        .node-tree .online { color: #00ff88; }
        .node-tree .offline { color: #ff4444; }
        .node-tree .quality { font-size: 11px; padding: 2px 6px; border-radius: 4px; }
        .quality-high { background: #00442244; color: #00ff88; }
        .quality-med { background: #44440022; color: #ffcc00; }
        .quality-low { background: #44000022; color: #ff4444; }
        .hop-label { font-size: 12px; color: #888; font-weight: bold; margin: 10px 0 5px 0; }
        .hop-0 { color: #00ff88; }
        .hop-1 { color: #ffcc00; }
        .hop-multi { color: #ff8844; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #2a2a4e; }
        th { color: #00d4ff; font-weight: 600; }
        .channel-primary { color: #00ff88; }
        .channel-secondary { color: #00d4ff; }
        .encrypted { color: #00ff88; }
        .unencrypted { color: #ffcc00; }
        #routes-list, #channels-list { max-height: 300px; overflow-y: auto; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Mesh Topology</h1>
            <nav>
                <a href="/">Dashboard</a>
                <a href="/nodes">Nodes</a>
                <a href="/messages">Messages</a>
                <a href="/alerts">Alerts</a>
                <a href="/topology">Topology</a>
            </nav>
        </header>

        <div class="grid">
            <div class="card">
                <h2>Mesh Health</h2>
                <div id="health-status">Loading...</div>
                <div class="health-bar">
                    <div id="health-fill" class="health-fill health-good" style="width: 0%"></div>
                </div>
                <div id="health-stats">
                    <div class="stat">
                        <span class="stat-label">Online Nodes</span>
                        <span class="stat-value" id="online-nodes">-</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Average SNR</span>
                        <span class="stat-value" id="avg-snr">-</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Channel Utilization</span>
                        <span class="stat-value" id="channel-util">-</span>
                    </div>
                </div>
            </div>

            <div class="card">
                <h2>Network Topology</h2>
                <div id="topology-tree" class="node-tree">Loading...</div>
            </div>

            <div class="card">
                <h2>Known Routes</h2>
                <div id="routes-list">
                    <table>
                        <thead>
                            <tr><th>Destination</th><th>Hops</th><th>Avg SNR</th><th>Via</th></tr>
                        </thead>
                        <tbody id="routes-body"></tbody>
                    </table>
                </div>
            </div>

            <div class="card">
                <h2>Channels</h2>
                <div id="channels-list">
                    <table>
                        <thead>
                            <tr><th>Ch</th><th>Name</th><th>Role</th><th>Encrypted</th><th>Messages</th></tr>
                        </thead>
                        <tbody id="channels-body"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function loadHealth() {
            try {
                const resp = await fetch('/api/health');
                const health = await resp.json();

                document.getElementById('health-status').innerHTML =
                    '<span style="font-size: 24px; font-weight: bold; '
                    + 'color: ' + getStatusColor(health.status) + '">'
                    + health.status.toUpperCase() + '</span> '
                    + '<span style="color: #888; margin-left: 10px;">'
                    + health.score + '%</span>';

                const fill = document.getElementById('health-fill');
                fill.style.width = health.score + '%';
                fill.className = 'health-fill health-' + health.status;

                document.getElementById('online-nodes').textContent = `${health.online_nodes} / ${health.total_nodes}`;
                document.getElementById('avg-snr').textContent = `${health.avg_snr.toFixed(1)} dB`;
                document.getElementById('channel-util').textContent = `${health.avg_channel_utilization.toFixed(1)}%`;
            } catch (e) {
                console.error('Failed to load health:', e);
            }
        }

        function getStatusColor(status) {
            const colors = {
                'excellent': '#00ff88',
                'good': '#00cc66',
                'fair': '#ffcc00',
                'poor': '#ff8800',
                'critical': '#ff4444',
                'unknown': '#888'
            };
            return colors[status] || '#888';
        }

        async function loadTopology() {
            try {
                const resp = await fetch('/api/topology');
                const data = await resp.json();

                const tree = document.getElementById('topology-tree');
                tree.innerHTML = '';

                // Group nodes by hop count
                const groups = { 0: [], 1: [], multi: [] };
                data.nodes.forEach(node => {
                    if (node.hop_count === 0) groups[0].push(node);
                    else if (node.hop_count === 1) groups[1].push(node);
                    else groups.multi.push(node);
                });

                if (groups[0].length > 0) {
                    tree.innerHTML += '<div class="hop-label hop-0">Direct (0 hops)</div>';
                    tree.innerHTML += '<div class="branch">' + groups[0].map(n => renderNode(n)).join('') + '</div>';
                }
                if (groups[1].length > 0) {
                    tree.innerHTML += '<div class="hop-label hop-1">1 Hop</div>';
                    tree.innerHTML += '<div class="branch">' + groups[1].map(n => renderNode(n)).join('') + '</div>';
                }
                if (groups.multi.length > 0) {
                    tree.innerHTML += '<div class="hop-label hop-multi">Multi-hop</div>';
                    tree.innerHTML += '<div class="branch">' + groups.multi.map(n => renderNode(n)).join('') + '</div>';
                }

                if (data.nodes.length === 0) {
                    tree.innerHTML = '<div style="color: #888;">No nodes discovered yet</div>';
                }
            } catch (e) {
                console.error('Failed to load topology:', e);
            }
        }

        function renderNode(node) {
            const status = node.is_online ? '<span class="online">●</span>' : '<span class="offline">●</span>';
            let quality = '';
            if (node.link_quality && node.link_quality.packet_count > 0) {
                const pct = node.link_quality.quality_percent;
                const cls = pct >= 70 ? 'quality-high' : pct >= 40 ? 'quality-med' : 'quality-low';
                quality = `<span class="quality ${cls}">${pct}%</span>`;
            }
            let neighbors = '';
            if (node.neighbors && node.neighbors.length > 0) {
                const list = node.neighbors.slice(0, 3).map(n => n.slice(-6)).join(', ');
                const more = node.neighbors.length > 3 ? ` +${node.neighbors.length - 3}` : '';
                neighbors = '<div style="font-size: 11px; color: #666; '
                    + 'margin-left: 28px;">Hears: '
                    + escapeHtml(list) + more + '</div>';
            }
            return `<div class="node">${status} ${escapeHtml(node.name)} ${quality}</div>${neighbors}`;
        }

        async function loadRoutes() {
            try {
                const resp = await fetch('/api/routes');
                const data = await resp.json();
                const tbody = document.getElementById('routes-body');
                tbody.innerHTML = '';

                if (data.routes.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" style="color: #888;">No routes discovered</td></tr>';
                    return;
                }

                data.routes.forEach(route => {
                    const hopStyle = route.hop_count <= 1
                        ? 'color: #00ff88' : route.hop_count <= 3
                        ? 'color: #ffcc00' : 'color: #ff8844';
                    const snrStyle = route.avg_snr > 0
                        ? 'color: #00ff88' : route.avg_snr > -10
                        ? 'color: #ffcc00' : 'color: #ff4444';
                    const via = route.hops && route.hops.length > 0 ? `via ${route.hops[0].node_id.slice(-6)}` : '-';

                    tbody.innerHTML += `<tr>
                        <td>${escapeHtml(route.destination_id.slice(-8))}</td>
                        <td style="${hopStyle}">${route.hop_count}</td>
                        <td style="${snrStyle}">${route.avg_snr.toFixed(1)} dB</td>
                        <td style="color: #888;">${escapeHtml(via)}</td>
                    </tr>`;
                });
            } catch (e) {
                console.error('Failed to load routes:', e);
            }
        }

        async function loadChannels() {
            try {
                const resp = await fetch('/api/channels');
                const data = await resp.json();
                const tbody = document.getElementById('channels-body');
                tbody.innerHTML = '';

                data.channels.filter(ch => ch.role !== 'DISABLED').forEach(ch => {
                    const roleClass = ch.role === 'PRIMARY' ? 'channel-primary' : 'channel-secondary';
                    const encClass = ch.is_encrypted ? 'encrypted' : 'unencrypted';
                    const encText = ch.is_encrypted ? 'Yes' : 'No';

                    tbody.innerHTML += `<tr>
                        <td>${ch.index}</td>
                        <td>${escapeHtml(ch.display_name)}</td>
                        <td class="${roleClass}">${ch.role}</td>
                        <td class="${encClass}">${encText}</td>
                        <td>${ch.message_count}</td>
                    </tr>`;
                });

                if (tbody.innerHTML === '') {
                    tbody.innerHTML = '<tr><td colspan="5" style="color: #888;">No active channels</td></tr>';
                }
            } catch (e) {
                console.error('Failed to load channels:', e);
            }
        }

        // Initial load
        loadHealth();
        loadTopology();
        loadRoutes();
        loadChannels();

        // Refresh periodically
        setInterval(() => {
            loadHealth();
            loadTopology();
            loadRoutes();
            loadChannels();
        }, 5000);
    </script>
</body>
</html>
        """

    def _get_map_html(self) -> str:
        """Return embedded HTML for map visualization when templates are unavailable."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Node Map - Meshing-Around</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin="" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: system-ui, -apple-system, sans-serif; background: #0a0a0a; color: #e0e0e0; }
        .container { max-width: 1600px; margin: 0 auto; padding: 20px; }
        header {
            background: linear-gradient(135deg, #1a1a2e 0%, #0a0a1a 100%);
            padding: 20px; border-radius: 8px; margin-bottom: 20px;
            display: flex; justify-content: space-between; align-items: center;
        }
        h1 { color: #00d4ff; font-size: 24px; }
        nav a { color: #00d4ff; text-decoration: none; margin-left: 20px; }
        nav a:hover { text-decoration: underline; }
        #map { width: 100%; height: calc(100vh - 150px); border-radius: 8px; border: 1px solid #2a2a4e; }
        .leaflet-popup-content-wrapper { background: #1a1a2e; color: #e0e0e0; border: 1px solid #2a2a4e; }
        .leaflet-popup-tip { background: #1a1a2e; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Node Map</h1>
            <nav>
                <a href="/">Dashboard</a>
                <a href="/nodes">Nodes</a>
                <a href="/topology">Topology</a>
                <a href="/map">Map</a>
            </nav>
        </header>
        <div id="map"></div>
    </div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""></script>
    <script>
        function escapeHtml(t){if(!t)return'';const d=document.createElement('div');d.textContent=t;return d.innerHTML;}
        const map = L.map('map').setView([39.8283, -98.5795], 4);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OSM &copy; CARTO', subdomains: 'abcd', maxZoom: 19
        }).addTo(map);
        const mg = L.featureGroup().addTo(map);
        async function load() {
            try {
                const r = await fetch('/api/geojson');
                const gj = await r.json();
                mg.clearLayers();
                (gj.features || []).forEach(f => {
                    const p = f.properties, c = f.geometry.coordinates;
                    L.circleMarker([c[1], c[0]], {
                        radius: p.is_online ? 8 : 5,
                        fillColor: p.is_online ? '#00ff88' : '#ff4444',
                        color: p.is_online ? '#00cc66' : '#cc3333',
                        weight: 2, opacity: 0.9, fillOpacity: p.is_online ? 0.8 : 0.5
                    }).bindPopup('<b>' + escapeHtml(p.name) + '</b><br>' + escapeHtml(p.node_id))
                      .addTo(mg);
                });
                if (gj.features.length > 0 && mg.getBounds().isValid()) map.fitBounds(mg.getBounds().pad(0.15));
            } catch(e) { console.error('Map load failed:', e); }
        }
        load();
        setInterval(load, 30000);
    </script>
</body>
</html>
        """

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

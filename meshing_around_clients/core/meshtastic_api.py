"""
Meshtastic API layer for Meshing-Around Clients.
Provides interface to communicate with Meshtastic devices.
"""

import logging
import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Connection timeout for serial/TCP/BLE interfaces (seconds)
CONNECT_TIMEOUT_SECONDS = 30.0

from .config import Config  # noqa: E402
from .models import (  # noqa: E402
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

# Try to import meshtastic
try:
    import meshtastic
    import meshtastic.ble_interface
    import meshtastic.http_interface
    import meshtastic.serial_interface
    import meshtastic.tcp_interface
    from pubsub import pub

    MESHTASTIC_AVAILABLE = True
except ImportError:
    MESHTASTIC_AVAILABLE = False


@dataclass
class ConnectionInfo:
    """Connection information and status."""

    connected: bool = False
    interface_type: str = ""
    device_path: str = ""
    error_message: str = ""
    my_node_id: str = ""
    my_node_num: int = 0


class MeshtasticAPI:
    """
    API layer for Meshtastic device communication.
    Provides a unified interface for serial, TCP, and BLE connections.
    """

    def __init__(self, config: Config):
        self.config = config
        self.interface = None
        self.network = MeshNetwork()
        self.connection_info = ConnectionInfo()
        self._message_queue: queue.Queue = queue.Queue()
        self._callbacks: Dict[str, List[Callable]] = {
            "on_connect": [],
            "on_disconnect": [],
            "on_message": [],
            "on_node_update": [],
            "on_alert": [],
            "on_position": [],
            "on_telemetry": [],
        }
        self._running = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._auto_save_thread: Optional[threading.Thread] = None
        self._last_save_time: Optional[datetime] = None
        self._save_lock = threading.Lock()  # Guard against overlapping saves

        # Load persisted state if enabled
        self._load_persisted_state()

    @property
    def is_connected(self) -> bool:
        return self.connection_info.connected

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for an event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, *args, **kwargs) -> None:
        """Trigger all callbacks for an event."""
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    callback(*args, **kwargs)
                except (TypeError, ValueError, AttributeError) as e:
                    logger.warning("Callback error for %s (%s): %s", event, type(e).__name__, e)

    # ==================== Persistence Methods ====================

    def _load_persisted_state(self) -> None:
        """Load network state from persistent storage."""
        if not hasattr(self.config, "storage") or not self.config.storage.enabled:
            return

        state_path = self.config.get_state_file_path()
        if state_path.exists():
            loaded = MeshNetwork.load_from_file(state_path)
            if loaded and loaded.nodes:
                # Merge loaded nodes with empty network
                self.network = loaded
                self.network.connection_status = "disconnected"  # Reset status
                logger.info("Loaded %d nodes from %s", len(self.network.nodes), state_path)

    def _save_state(self) -> bool:
        """Save network state to persistent storage.

        Uses a guard flag to skip if a previous save is still in progress,
        preventing overlapping writes under slow I/O conditions.
        """
        if not hasattr(self.config, "storage") or not self.config.storage.enabled:
            return False
        if not self._save_lock.acquire(blocking=False):
            logger.debug("Skipping save — previous save still in progress")
            return False

        try:
            state_path = self.config.get_state_file_path()
            self.network.last_update = datetime.now(timezone.utc)
            success = self.network.save_to_file(state_path)
            if success:
                self._last_save_time = datetime.now(timezone.utc)
            return success
        finally:
            self._save_lock.release()

    def _start_auto_save(self) -> None:
        """Start background auto-save thread."""
        if not hasattr(self.config, "storage"):
            return
        if self.config.storage.auto_save_interval <= 0:
            return

        def auto_save_loop():
            interval = self.config.storage.auto_save_interval
            while not self._stop_event.is_set():
                # Wait for interval or until stop is signaled
                if self._stop_event.wait(timeout=interval):
                    break  # Stop event was set
                if self.connection_info.connected:
                    self._save_state()

        self._auto_save_thread = threading.Thread(target=auto_save_loop, daemon=True)
        self._auto_save_thread.start()

    def _create_interface(self, interface_type: str):
        """Create and return the appropriate Meshtastic interface."""
        if interface_type == "serial":
            port = self.config.interface.port if self.config.interface.port else None
            self.connection_info.device_path = port or "auto"
            return meshtastic.serial_interface.SerialInterface(port, connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS)
        elif interface_type == "tcp":
            hostname = self.config.interface.hostname
            if not hostname:
                raise ValueError("TCP hostname not configured")
            self.connection_info.device_path = hostname
            return meshtastic.tcp_interface.TCPInterface(hostname, connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS)
        elif interface_type == "http":
            base_url = self.config.interface.http_url
            if not base_url:
                hostname = self.config.interface.hostname
                if not hostname:
                    raise ValueError("HTTP URL not configured (set http_url or hostname)")
                base_url = f"http://{hostname}"
            self.connection_info.device_path = base_url
            return meshtastic.http_interface.HTTPInterface(base_url, connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS)
        elif interface_type == "ble":
            mac = self.config.interface.mac
            if not mac:
                raise ValueError("BLE MAC address not configured")
            self.connection_info.device_path = mac
            return meshtastic.ble_interface.BLEInterface(mac)
        else:
            raise ValueError(f"Unknown interface type: {interface_type}")

    def _start_worker_thread(self) -> None:
        """Stop any previous worker thread and start a fresh one."""
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        # Drain stale messages from previous session
        while not self._message_queue.empty():
            try:
                self._message_queue.get_nowait()
            except queue.Empty:
                break

        self._stop_event.clear()
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def connect(self) -> bool:
        """Connect to the Meshtastic device."""
        if not MESHTASTIC_AVAILABLE:
            self.connection_info.error_message = "Meshtastic library not installed"
            return False

        try:
            # Subscribe to meshtastic events
            pub.subscribe(self._on_receive, "meshtastic.receive")
            pub.subscribe(self._on_connection, "meshtastic.connection.established")
            pub.subscribe(self._on_disconnect_event, "meshtastic.connection.lost")

            interface_type = self.config.interface.type
            self.interface = self._create_interface(interface_type)

            self.connection_info.interface_type = interface_type
            self.connection_info.connected = True
            self.network.connection_status = "connected"

            # Get my node info
            if self.interface.myInfo:
                self.connection_info.my_node_id = hex(self.interface.myInfo.my_node_num)
                self.connection_info.my_node_num = self.interface.myInfo.my_node_num
                self.network.my_node_id = self.connection_info.my_node_id

            # Load initial node database
            self._load_node_database()

            self._start_worker_thread()

            # Start auto-save thread
            self._start_auto_save()

            self._trigger_callbacks("on_connect", self.connection_info)
            return True

        except (OSError, ConnectionError, TimeoutError) as e:
            self.connection_info.error_message = f"Connection failed: {e}"
            self.connection_info.connected = False
            self.network.connection_status = "error"
            return False
        except (ValueError, AttributeError) as e:
            self.connection_info.error_message = f"Configuration error: {e}"
            self.connection_info.connected = False
            self.network.connection_status = "error"
            return False

    def disconnect(self) -> None:
        """Disconnect from the Meshtastic device."""
        # Save state before disconnecting
        if self.connection_info.connected:
            self._save_state()

        self._running = False
        self._stop_event.set()

        # Wait for worker threads to finish (with timeout to avoid hangs)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        if self._auto_save_thread and self._auto_save_thread.is_alive():
            self._auto_save_thread.join(timeout=5)

        if self.interface:
            try:
                pub.unsubscribe(self._on_receive, "meshtastic.receive")
                pub.unsubscribe(self._on_connection, "meshtastic.connection.established")
                pub.unsubscribe(self._on_disconnect_event, "meshtastic.connection.lost")
                self.interface.close()
            except (OSError, AttributeError, RuntimeError):
                pass  # Ignore cleanup errors during disconnect

        self.interface = None
        self.connection_info.connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _load_node_database(self) -> None:
        """Load the node database from the connected device."""
        if not self.interface or not hasattr(self.interface, "nodes"):
            return

        for node_id, node_info in self.interface.nodes.items():
            node = self._parse_node_info(node_id, node_info)
            if node:
                self.network.add_node(node)

    def _parse_node_info(self, node_id: str, node_info: dict) -> Optional[Node]:
        """Parse node info from Meshtastic to our model."""
        try:
            user = node_info.get("user", {})
            position = node_info.get("position", {})
            device_metrics = node_info.get("deviceMetrics", {})

            # Parse position
            pos = Position(
                latitude=position.get("latitude", 0.0),
                longitude=position.get("longitude", 0.0),
                altitude=position.get("altitude", 0),
                time=datetime.fromtimestamp(position["time"], tz=timezone.utc) if position.get("time") else None,
            )

            # Parse telemetry
            telemetry = NodeTelemetry(
                battery_level=device_metrics.get("batteryLevel", 0),
                voltage=device_metrics.get("voltage", 0.0),
                channel_utilization=device_metrics.get("channelUtilization", 0.0),
                air_util_tx=device_metrics.get("airUtilTx", 0.0),
                uptime_seconds=device_metrics.get("uptimeSeconds", 0),
            )

            # Parse role
            role_str = user.get("role", "CLIENT")
            try:
                role = NodeRole[role_str.upper()]
            except (KeyError, AttributeError):
                logger.debug("Unknown node role '%s', defaulting to CLIENT", role_str)
                role = NodeRole.CLIENT

            # Determine if favorite/admin
            node_num_str = str(node_info.get("num", ""))
            is_favorite = node_num_str in self.config.favorite_nodes
            is_admin = node_num_str in self.config.admin_nodes

            # Last heard
            last_heard = None
            if node_info.get("lastHeard"):
                last_heard = datetime.fromtimestamp(node_info["lastHeard"], tz=timezone.utc)

            # SNR/RSSI
            if "snr" in node_info:
                telemetry.snr = node_info["snr"]
            if "rssi" in node_info:
                telemetry.rssi = node_info["rssi"]

            return Node(
                node_id=node_id,
                node_num=node_info.get("num", 0),
                short_name=user.get("shortName", ""),
                long_name=user.get("longName", ""),
                hardware_model=user.get("hwModel", "UNKNOWN"),
                role=role,
                position=pos,
                telemetry=telemetry,
                last_heard=last_heard,
                is_favorite=is_favorite,
                is_admin=is_admin,
                hop_count=node_info.get("hopsAway", 0),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Error parsing node info (%s): %s", type(e).__name__, e)
            return None

    def _on_receive(self, packet: dict, interface: Any) -> None:
        """Handle received packet from Meshtastic."""
        self._message_queue.put(("receive", packet))

    def _on_connection(self, interface: Any, topic: Any = None) -> None:
        """Handle connection established event."""
        self.connection_info.connected = True
        self.network.connection_status = "connected"
        self._load_node_database()
        self._trigger_callbacks("on_connect", self.connection_info)

    def _on_disconnect_event(self, interface: Any, topic: Any = None) -> None:
        """Handle connection lost event."""
        self.connection_info.connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _worker_loop(self) -> None:
        """Worker thread to process incoming messages."""
        while self._running:
            try:
                event_type, data = self._message_queue.get(timeout=0.5)
                if event_type == "receive":
                    self._process_packet(data)
            except queue.Empty:
                continue
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                logger.warning("Worker error (%s): %s", type(e).__name__, e)

    def _process_packet(self, packet: dict) -> None:
        """Process a received packet."""
        try:
            decoded = packet.get("decoded", {})
            portnum = decoded.get("portnum", "")

            # Update sender node last heard
            sender_id = packet.get("fromId", "")
            if sender_id and sender_id in self.network.nodes:
                self.network.nodes[sender_id].last_heard = datetime.now(timezone.utc)
                self.network.nodes[sender_id].is_online = True

            # Handle different packet types
            if portnum == "TEXT_MESSAGE_APP":
                self._handle_text_message(packet)
            elif portnum == "POSITION_APP":
                self._handle_position(packet)
            elif portnum == "TELEMETRY_APP":
                self._handle_telemetry(packet)
            elif portnum == "NODEINFO_APP":
                self._handle_nodeinfo(packet)

        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as e:
            logger.warning("Error processing packet (%s): %s", type(e).__name__, e)

    def _handle_text_message(self, packet: dict) -> None:
        """Handle incoming text message."""
        decoded = packet.get("decoded", {})
        text = decoded.get("text", decoded.get("payload", b"").decode("utf-8", errors="replace"))

        sender_id = packet.get("fromId", "")
        sender_name = ""
        if sender_id in self.network.nodes:
            sender_name = self.network.nodes[sender_id].display_name

        message = Message(
            id=str(uuid.uuid4()),
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_id=packet.get("toId", ""),
            channel=packet.get("channel", 0),
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            hop_count=max(0, packet.get("hopStart", 0) - packet.get("hopLimit", 0)),
            snr=packet.get("snr", 0.0),
            rssi=packet.get("rssi", 0),
            is_incoming=True,
        )

        self.network.add_message(message)
        self._trigger_callbacks("on_message", message)

        # Check for emergency keywords
        if self.config.alerts.enabled:
            text_lower = text.lower()
            for keyword in self.config.alerts.emergency_keywords:
                if keyword.lower() in text_lower:
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.EMERGENCY,
                        title="Emergency Keyword Detected",
                        message=f"{sender_name}: {text}",
                        severity=4,
                        source_node=sender_id,
                        metadata={"keyword": keyword},
                    )
                    self.network.add_alert(alert)
                    self._trigger_callbacks("on_alert", alert)
                    break

    def _handle_position(self, packet: dict) -> None:
        """Handle position update."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        position_data = decoded.get("position", {})

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            lat = position_data.get("latitude")
            if lat is None:
                lat_i = position_data.get("latitudeI", 0)
                lat = lat_i / 1e7 if lat_i else 0.0
            lon = position_data.get("longitude")
            if lon is None:
                lon_i = position_data.get("longitudeI", 0)
                lon = lon_i / 1e7 if lon_i else 0.0
            node.position = Position(
                latitude=lat, longitude=lon, altitude=position_data.get("altitude", 0), time=datetime.now(timezone.utc)
            )
            node.last_heard = datetime.now(timezone.utc)
            self._trigger_callbacks("on_position", sender_id, node.position)

    def _handle_telemetry(self, packet: dict) -> None:
        """Handle telemetry update."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        telemetry_data = decoded.get("telemetry", {})
        device_metrics = telemetry_data.get("deviceMetrics", {})

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            node.telemetry = NodeTelemetry(
                battery_level=device_metrics.get("batteryLevel", node.telemetry.battery_level),
                voltage=device_metrics.get("voltage", node.telemetry.voltage),
                channel_utilization=device_metrics.get("channelUtilization", node.telemetry.channel_utilization),
                air_util_tx=device_metrics.get("airUtilTx", node.telemetry.air_util_tx),
                uptime_seconds=device_metrics.get("uptimeSeconds", node.telemetry.uptime_seconds),
                last_updated=datetime.now(timezone.utc),
            )
            node.last_heard = datetime.now(timezone.utc)
            self._trigger_callbacks("on_telemetry", sender_id, node.telemetry)

            # Check battery alert
            if self.config.alerts.enabled and node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.BATTERY,
                    title="Low Battery Alert",
                    message=f"{node.display_name} battery at {node.telemetry.battery_level}%",
                    severity=2,
                    source_node=sender_id,
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)

    def _handle_nodeinfo(self, packet: dict) -> None:
        """Handle node info update."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        user = decoded.get("user", {})

        is_new = sender_id not in self.network.nodes

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            node.short_name = user.get("shortName", node.short_name)
            node.long_name = user.get("longName", node.long_name)
            node.hardware_model = user.get("hwModel", node.hardware_model)
            node.last_heard = datetime.now(timezone.utc)
        else:
            # New node
            node_num = packet.get("from", 0)
            node = Node(
                node_id=sender_id,
                node_num=node_num,
                short_name=user.get("shortName", ""),
                long_name=user.get("longName", ""),
                hardware_model=user.get("hwModel", "UNKNOWN"),
                last_heard=datetime.now(timezone.utc),
            )
            self.network.add_node(node)

        self._trigger_callbacks("on_node_update", sender_id, is_new)

        # New node alert
        if is_new and self.config.alerts.enabled:
            alert = Alert(
                id=str(uuid.uuid4()),
                alert_type=AlertType.NEW_NODE,
                title="New Node Joined",
                message=f"New node joined the mesh: {node.display_name}",
                severity=1,
                source_node=sender_id,
            )
            self.network.add_alert(alert)
            self._trigger_callbacks("on_alert", alert)

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Send a text message."""
        if not self.interface:
            return False

        try:
            if destination == "^all":
                self.interface.sendText(text, channelIndex=channel)
            else:
                # Parse destination node number
                dest_num = int(destination.lstrip("!"), 16) if destination.startswith("!") else int(destination)
                self.interface.sendText(text, destinationId=dest_num, channelIndex=channel)

            # Log outgoing message
            message = Message(
                id=str(uuid.uuid4()),
                sender_id=self.network.my_node_id,
                sender_name=self.config.bot_name,
                recipient_id=destination,
                channel=channel,
                text=text,
                message_type=MessageType.TEXT,
                timestamp=datetime.now(timezone.utc),
                is_incoming=False,
            )
            self.network.add_message(message)
            return True

        except (OSError, AttributeError, ValueError) as e:
            logger.error("Error sending message (%s): %s", type(e).__name__, e)
            return False

    def get_nodes(self) -> List[Node]:
        """Get all known nodes."""
        return list(self.network.nodes.values())

    def get_messages(self, channel: Optional[int] = None, limit: int = 100) -> List[Message]:
        """Get messages, optionally filtered by channel."""
        messages = list(self.network.messages)
        if channel is not None:
            messages = [m for m in messages if m.channel == channel]
        return messages[-limit:]

    def get_alerts(self, unread_only: bool = False) -> List[Alert]:
        """Get alerts."""
        if unread_only:
            return self.network.unread_alerts
        return self.network.alerts

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self.network.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                return True
        return False


class MockMeshtasticAPI(MeshtasticAPI):
    """
    Mock API for testing without actual Meshtastic hardware.
    Generates fake nodes and messages for development.
    """

    def __init__(self, config: Config):
        super().__init__(config)
        self._demo_mode = True

    def connect(self) -> bool:
        """Simulate connection."""
        self.connection_info.connected = True
        self.connection_info.interface_type = "mock"
        self.connection_info.device_path = "demo"
        self.connection_info.my_node_id = "!deadbeef"
        self.connection_info.my_node_num = 0xDEADBEEF
        self.network.connection_status = "connected (demo)"
        self.network.my_node_id = self.connection_info.my_node_id

        # Generate demo nodes
        demo_nodes = [
            ("!abc12345", 0xABC12345, "BaseStation", "HQ Base Station", "TBEAM"),
            ("!def67890", 0xDEF67890, "Mobile1", "Field Unit Alpha", "TLORA"),
            ("!fed98765", 0xFED98765, "Relay", "Mountain Repeater", "HELTEC"),
            ("!123abcde", 0x123ABCDE, "Solar1", "Solar Powered Node", "RAK4631"),
            ("!456f0e1a", 0x456F0E1A, "Router", "Community Router", "TBEAM"),
        ]

        for node_id, node_num, short, long, hw in demo_nodes:
            node = Node(
                node_id=node_id,
                node_num=node_num,
                short_name=short,
                long_name=long,
                hardware_model=hw,
                role=NodeRole.CLIENT if "Router" not in short else NodeRole.ROUTER,
                last_heard=datetime.now(timezone.utc),
                is_online=True,
            )
            node.telemetry.battery_level = 75 + (node_num % 25)
            node.telemetry.snr = 5.0 + (node_num % 10)
            self.network.add_node(node)

        self._running = True
        self._trigger_callbacks("on_connect", self.connection_info)
        return True

    def disconnect(self) -> None:
        """Simulate disconnect."""
        self._running = False
        self.connection_info.connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Simulate sending a message."""
        message = Message(
            id=str(uuid.uuid4()),
            sender_id=self.network.my_node_id,
            sender_name="Me",
            recipient_id=destination,
            channel=channel,
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            is_incoming=False,
            ack_received=True,
        )
        self.network.add_message(message)
        return True

"""
Meshtastic API layer for Meshing-Around Clients.
Provides interface to communicate with Meshtastic devices.
"""

import importlib
import logging
import queue
import random
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_message_logger = logging.getLogger("mesh.messages")

# Connection timeout for serial/TCP/BLE interfaces (seconds)
CONNECT_TIMEOUT_SECONDS = 30.0

# Hostname validation: alphanumeric, dots, hyphens, underscores, optional port
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9._-]+(:\d{1,5})?$")

from .callbacks import CallbackMixin, extract_position, safe_float, safe_int  # noqa: E402
from .config import Config  # noqa: E402
from .models import (  # noqa: E402
    MAX_MESSAGE_BYTES,
    Alert,
    AlertType,
    ConnectionInfo,
    MeshNetwork,
    Message,
    MessageType,
    Node,
    NodeRole,
    NodeTelemetry,
    Position,
)

# Core meshtastic + pubsub (required for any hardware connection)
try:
    importlib.import_module("meshtastic")
    from pubsub import pub

    MESHTASTIC_AVAILABLE = True
except ImportError:
    MESHTASTIC_AVAILABLE = False

# Interface sub-modules (each may have platform-specific deps, e.g. bleak for BLE)
_INTERFACE_MODULES: dict = {}
for _mod_name in ("serial_interface", "tcp_interface", "http_interface", "ble_interface"):
    try:
        _INTERFACE_MODULES[_mod_name] = importlib.import_module(f"meshtastic.{_mod_name}")
    except Exception as _exc:
        _INTERFACE_MODULES[_mod_name] = None
        if not isinstance(_exc, ImportError):
            logger.info("meshtastic.%s import failed (%s): %s", _mod_name, type(_exc).__name__, _exc)

# Maps config interface type to sub-module name
_INTERFACE_TYPE_MAP = {
    "serial": "serial_interface",
    "tcp": "tcp_interface",
    "http": "http_interface",
    "ble": "ble_interface",
}


def refresh_meshtastic_availability() -> bool:
    """Re-check whether the meshtastic library is importable (e.g. after pip install)."""
    global MESHTASTIC_AVAILABLE
    try:
        importlib.import_module("meshtastic")
        importlib.import_module("pubsub")
        MESHTASTIC_AVAILABLE = True
    except ImportError:
        MESHTASTIC_AVAILABLE = False

    # Re-probe interface sub-modules
    for mod_name in ("serial_interface", "tcp_interface", "http_interface", "ble_interface"):
        try:
            _INTERFACE_MODULES[mod_name] = importlib.import_module(f"meshtastic.{mod_name}")
        except Exception as exc:
            _INTERFACE_MODULES[mod_name] = None
            if not isinstance(exc, ImportError):
                logger.info("meshtastic.%s import failed (%s): %s", mod_name, type(exc).__name__, exc)

    return MESHTASTIC_AVAILABLE


class MeshtasticAPI(CallbackMixin):
    """
    API layer for Meshtastic device communication.
    Provides a unified interface for serial, TCP, and BLE connections.
    """

    def __init__(self, config: Config):
        self.config = config
        self.interface = None
        self.network = MeshNetwork()
        self.connection_info = ConnectionInfo()
        self._message_queue: queue.Queue = queue.Queue(maxsize=5000)
        self._messages_dropped = 0
        self._init_callbacks()
        self._running = threading.Event()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._leaked_thread_count = 0
        self._auto_save_thread: Optional[threading.Thread] = None
        self._last_save_time: Optional[datetime] = None
        self._save_lock = threading.Lock()  # Guard against overlapping saves
        self._last_logged_health: str = ""

        # Load persisted state if enabled
        self._load_persisted_state()

    @property
    def is_connected(self) -> bool:
        return self.connection_info.connected

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

    @staticmethod
    def _try_create(cls, *args, **kwargs):
        """Instantiate a meshtastic interface, dropping unsupported kwargs."""
        try:
            return cls(*args, **kwargs)
        except TypeError:
            # Older/newer meshtastic versions may not accept all kwargs;
            # drop optional kwargs and retry.
            for key in ("connectTimeoutSeconds", "portNumber", "noNodes"):
                kwargs.pop(key, None)
            return cls(*args, **kwargs)

    def _create_interface(self, interface_type: str):
        """Create and return the appropriate Meshtastic interface."""
        target = (
            self.config.interface.port
            or self.config.interface.hostname
            or self.config.interface.http_url
            or self.config.interface.mac
            or "auto"
        )
        logger.info("Creating %s interface (target: %s)", interface_type, target)
        mod_name = _INTERFACE_TYPE_MAP.get(interface_type)
        if mod_name is None:
            raise ValueError(f"Unknown interface type: {interface_type}")
        mod = _INTERFACE_MODULES.get(mod_name)
        if mod is None:
            raise ImportError(f"meshtastic.{mod_name} not available — install its dependencies")

        if interface_type == "serial":
            port = self.config.interface.port if self.config.interface.port else None
            self.connection_info.device_path = port or "auto"
            return self._try_create(mod.SerialInterface, port, connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS)
        elif interface_type == "tcp":
            hostname = self.config.interface.hostname
            if not hostname:
                raise ValueError("TCP hostname not configured")
            if not _HOSTNAME_RE.match(hostname):
                raise ValueError(f"Invalid TCP hostname: {hostname!r}")
            self.connection_info.device_path = hostname
            host, tcp_port = hostname.rsplit(":", 1) if ":" in hostname else (hostname, "4403")
            return self._try_create(
                mod.TCPInterface,
                host,
                portNumber=int(tcp_port),
                connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS,
                noNodes=True,
            )
        elif interface_type == "http":
            base_url = self.config.interface.http_url
            if not base_url:
                hostname = self.config.interface.hostname
                if not hostname:
                    raise ValueError("HTTP URL not configured (set http_url or hostname)")
                if not _HOSTNAME_RE.match(hostname):
                    raise ValueError(f"Invalid HTTP hostname: {hostname!r}")
                base_url = f"http://{hostname}"
            self.connection_info.device_path = base_url
            return self._try_create(mod.HTTPInterface, base_url, connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS)
        elif interface_type == "ble":
            mac = self.config.interface.mac
            if not mac:
                raise ValueError("BLE MAC address not configured")
            self.connection_info.device_path = mac
            return mod.BLEInterface(mac)

    def _start_worker_thread(self) -> None:
        """Stop any previous worker thread and start a fresh one."""
        # Signal old thread to stop BEFORE joining
        self._stop_event.set()
        self._running.clear()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
            if self._worker_thread.is_alive():
                self._leaked_thread_count += 1
                logger.warning(
                    "Previous worker thread did not stop within 5s " "(leaked threads: %d)",
                    self._leaked_thread_count,
                )
                if self._leaked_thread_count > 2:
                    logger.error(
                        "Too many leaked worker threads (%d), refusing new connection", self._leaked_thread_count
                    )
                    return
            else:
                self._leaked_thread_count = 0

        # Drain stale messages from previous session
        while not self._message_queue.empty():
            try:
                self._message_queue.get_nowait()
            except queue.Empty:
                break

        self._stop_event.clear()
        self._running.set()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def is_healthy(self) -> bool:
        """Check if the API worker thread is alive and running.

        Returns True if the worker is active and processing messages.
        TUI/Web layers can poll this to detect connection degradation.
        """
        if not self._running.is_set():
            return False
        if self._worker_thread and not self._worker_thread.is_alive():
            return False
        return self.connection_info.connected

    @property
    def connection_health(self) -> Dict[str, Any]:
        """Get connection health metrics.

        Returns a dict compatible with MQTTMeshtasticClient.connection_health,
        allowing the TUI to use a single code path regardless of connection mode.
        """
        connected = self.is_connected
        healthy = self.is_healthy()

        if not connected:
            status = "disconnected"
        elif not healthy:
            status = "degraded"
        else:
            status = "healthy"

        if status != self._last_logged_health:
            old = self._last_logged_health or "initial"
            self._last_logged_health = status
            if status in ("disconnected", "degraded"):
                logger.warning("Connection health: %s → %s", old, status)
            else:
                logger.info("Connection health: %s → %s", old, status)

        return {
            "status": status,
            "connected": connected,
            "interface_type": self.connection_info.interface_type,
            "device_path": self.connection_info.device_path,
            "queue_size": self._message_queue.qsize(),
            "queue_maxsize": self._message_queue.maxsize,
            "messages_dropped": self._messages_dropped,
        }

    def _close_interface(self) -> None:
        """Close and discard the current interface if one exists."""
        if self.interface:
            try:
                self.interface.close()
            except (OSError, AttributeError, RuntimeError):
                pass
            self.interface = None

    def connect(self) -> bool:
        """Connect to the Meshtastic device."""
        if not MESHTASTIC_AVAILABLE:
            self.connection_info.error_message = "Meshtastic library not installed"
            return False

        # Clean up any previous connection (e.g. from a failed retry)
        self._close_interface()

        try:
            interface_type = self.config.interface.type
            self.interface = self._create_interface(interface_type)

            # Subscribe to meshtastic events AFTER interface creation
            # to prevent leaked subscriptions if creation fails.
            # Wrapped in try/except to clean up subscriptions if subsequent
            # setup steps (_load_node_database, _start_worker_thread, etc.) fail.
            pub.subscribe(self._on_receive, "meshtastic.receive")
            pub.subscribe(self._on_connection, "meshtastic.connection.established")
            pub.subscribe(self._on_disconnect_event, "meshtastic.connection.lost")

            try:
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
                logger.info(
                    "Connected via %s to %s",
                    self.connection_info.interface_type,
                    self.connection_info.device_path,
                )
                return True

            except (OSError, ConnectionError, RuntimeError, AttributeError):
                # Clean up subscriptions and interface on partial setup failure
                for topic, handler in [
                    ("meshtastic.receive", self._on_receive),
                    ("meshtastic.connection.established", self._on_connection),
                    ("meshtastic.connection.lost", self._on_disconnect_event),
                ]:
                    try:
                        pub.unsubscribe(handler, topic)
                    except (ValueError, RuntimeError):
                        pass
                self._close_interface()
                self.connection_info.connected = False
                self.network.connection_status = "error"
                raise

        except Exception as e:
            # Catch-all includes meshtastic's MeshInterfaceError (inherits
            # directly from Exception, not from OSError/TimeoutError).
            if isinstance(e, (ValueError, AttributeError)):
                self.connection_info.error_message = f"Configuration error ({type(e).__name__}): {e}"
            else:
                self.connection_info.error_message = f"Connection failed ({type(e).__name__}): {e}"
            self.connection_info.connected = False
            self.network.connection_status = "error"
            logger.error("Interface connection failed: %s", self.connection_info.error_message)
            return False

    def connect_with_retry(
        self,
        max_retries: int = 3,
        base_delay: float = 5.0,
        max_delay: float = 60.0,
        on_retry: Optional[callable] = None,
    ) -> bool:
        """Connect with exponential backoff and jitter.

        Args:
            max_retries: Maximum number of retry attempts.
            base_delay: Initial delay between retries in seconds.
            max_delay: Maximum delay between retries in seconds.
            on_retry: Optional callback(attempt, delay, error_msg) called before each retry sleep.

        Returns:
            True if connection succeeded.
        """
        for attempt in range(1, max_retries + 1):
            if self.connect():
                return True

            # Fail fast for non-transient errors (no point retrying)
            if not MESHTASTIC_AVAILABLE:
                return False
            err = self.connection_info.error_message
            if "Configuration error" in err or "not available" in err:
                return False

            if attempt >= max_retries:
                break

            # Exponential backoff with ±25% jitter
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            jitter = delay * random.uniform(-0.25, 0.25)
            delay = max(1.0, delay + jitter)

            error_msg = self.connection_info.error_message
            logger.warning(
                "Connection attempt %d/%d failed: %s. Retrying in %.1fs", attempt, max_retries, error_msg, delay
            )

            if on_retry:
                on_retry(attempt, delay, error_msg)

            time.sleep(delay)

        return False

    def disconnect(self) -> None:
        """Disconnect from the Meshtastic device."""
        # Save state before disconnecting
        if self.connection_info.connected:
            self._save_state()

        self._running.clear()
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
        try:
            self._message_queue.put_nowait(("receive", packet))
        except queue.Full:
            self._messages_dropped += 1
            logger.warning(
                "Message queue full (maxsize=%d), dropping packet (total dropped: %d)",
                self._message_queue.maxsize,
                self._messages_dropped,
            )

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
        try:
            while self._running.is_set():
                try:
                    event_type, data = self._message_queue.get(timeout=0.5)
                    if event_type == "receive":
                        self._process_packet(data)
                except queue.Empty:
                    continue
                except (KeyError, TypeError, ValueError, AttributeError) as e:
                    logger.warning("Worker error (%s): %s", type(e).__name__, e)
        except Exception as e:
            logger.error("Worker thread crashed: %s", e)
            self._running.clear()
            self.connection_info.connected = False
            self.connection_info.error_message = f"Worker crashed: {e}"
            self.network.connection_status = "error"
            # Notify UI layer about the crash
            self._trigger_callbacks("on_disconnect")

    def _process_packet(self, packet: dict) -> None:
        """Process a received packet."""
        try:
            decoded = packet.get("decoded", {})
            portnum = decoded.get("portnum", "")

            # Update sender node last heard
            sender_id = packet.get("fromId", "")
            if sender_id:
                node = self.network.get_node(sender_id)
                if node:
                    node.last_heard = datetime.now(timezone.utc)
                    node.is_online = True

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
        _message_logger.info("ch%d %s (%s): %s", message.channel, sender_name, sender_id, text)
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
        """Handle position update with coordinate validation."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        position_data = decoded.get("position", {})

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            pos = extract_position(position_data)
            if pos is not None:
                node.position = pos
            node.last_heard = datetime.now(timezone.utc)
            self._trigger_callbacks("on_position", sender_id, node.position)

    def _handle_telemetry(self, packet: dict) -> None:
        """Handle telemetry update with input validation."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        telemetry_data = decoded.get("telemetry", {})
        device_metrics = telemetry_data.get("deviceMetrics", {})

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            # Validate all numeric fields (matching MQTT client robustness)
            battery = safe_int(device_metrics.get("batteryLevel"), 0, 101)
            voltage = safe_float(device_metrics.get("voltage"), 0.0, 10.0)
            ch_util = safe_float(device_metrics.get("channelUtilization"), 0.0, 100.0)
            air_util = safe_float(device_metrics.get("airUtilTx"), 0.0, 100.0)
            uptime = safe_int(device_metrics.get("uptimeSeconds"), 0, 2**31)
            node.telemetry = NodeTelemetry(
                battery_level=battery if battery is not None else node.telemetry.battery_level,
                voltage=voltage if voltage is not None else node.telemetry.voltage,
                channel_utilization=ch_util if ch_util is not None else node.telemetry.channel_utilization,
                air_util_tx=air_util if air_util is not None else node.telemetry.air_util_tx,
                uptime_seconds=uptime if uptime is not None else node.telemetry.uptime_seconds,
                last_updated=datetime.now(timezone.utc),
            )
            node.last_heard = datetime.now(timezone.utc)
            self._trigger_callbacks("on_telemetry", sender_id, node.telemetry)

            # Check battery alert (with per-node cooldown to prevent alert fatigue)
            if self.config.alerts.enabled and node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
                if not self._is_alert_cooled_down(sender_id, "battery"):
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

        node, is_new = self._ensure_node(
            sender_id,
            packet.get("from", 0),
            short_name=user.get("shortName", ""),
            long_name=user.get("longName", ""),
            hardware_model=user.get("hwModel", "UNKNOWN"),
        )
        if not is_new and node:
            # Update existing node fields from nodeinfo
            node.short_name = user.get("shortName", node.short_name)
            node.long_name = user.get("longName", node.long_name)
            node.hardware_model = user.get("hwModel", node.hardware_model)
            self._trigger_callbacks("on_node_update", sender_id, False)

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
        """Send a text message with byte-length validation."""
        if not self.interface:
            return False

        msg_bytes = len(text.encode("utf-8"))
        if msg_bytes > MAX_MESSAGE_BYTES:
            logger.warning("Message too long (%d/%d bytes), rejecting", msg_bytes, MAX_MESSAGE_BYTES)
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
        return list(self.network.alerts)

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

    # Sample chat lines for demo traffic
    _DEMO_MESSAGES = [
        "Anyone copy?",
        "Signal check - how's my SNR?",
        "Heading to the trailhead, back in 2h",
        "Weather looks clear from up here",
        "Battery swap complete, back online",
        "Repeater seems solid today",
        "New firmware is working great",
        "Copy that, loud and clear",
        "Roger, standing by",
        "Testing range from the ridge",
        "Good morning mesh!",
        "Check your channel utilization",
        "Solar panel keeping me at 100%",
        "Lost GPS fix briefly, back now",
        "Anyone else seeing packet loss?",
    ]

    # Additional demo nodes that can be "discovered" during demo mode
    _EXTRA_DEMO_NODES = [
        ("!77aa1122", 0x77AA1122, "Hiker1", "Backcountry Hiker", "TBEAM"),
        ("!88bb3344", 0x88BB3344, "SAR", "Search & Rescue", "RAK4631"),
        ("!99cc5566", 0x99CC5566, "Sensor", "Weather Station", "HELTEC"),
        ("!aaddee77", 0xAADDEE77, "Drone1", "Survey Drone", "TLORA"),
        ("!bbff0088", 0xBBFF0088, "Marina", "Harbor Master", "TBEAM"),
    ]
    _MAX_DEMO_NODES = 10

    def __init__(self, config: Config):
        super().__init__(config)
        self._demo_mode = True
        self._demo_thread: Optional[threading.Thread] = None

    def connect(self) -> bool:
        """Simulate connection and start generating demo traffic."""
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

        self._running.set()
        self._trigger_callbacks("on_connect", self.connection_info)

        # Start background demo traffic
        self._stop_event.clear()
        self._demo_thread = threading.Thread(target=self._demo_traffic_loop, daemon=True, name="demo-traffic")
        self._demo_thread.start()
        return True

    def disconnect(self) -> None:
        """Stop demo traffic and simulate disconnect."""
        self._running.clear()
        self._stop_event.set()
        if self._demo_thread and self._demo_thread.is_alive():
            self._demo_thread.join(timeout=2)
        self.connection_info.connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _demo_traffic_loop(self) -> None:
        """Background loop that simulates incoming mesh traffic."""
        while not self._stop_event.is_set():
            # Wait 5-15 seconds between events (realistic mesh cadence)
            if self._stop_event.wait(timeout=random.uniform(5.0, 15.0)):
                break
            try:
                self._generate_demo_event()
            except Exception:
                logger.debug("Demo traffic error", exc_info=True)

    def _generate_demo_event(self) -> None:
        """Generate a single random demo event (message, telemetry, or node discovery)."""
        nodes = list(self.network.nodes.values())
        if not nodes:
            return

        now = datetime.now(timezone.utc)

        # 5% chance: discover a new node (if under cap)
        if random.random() < 0.05 and len(self.network.nodes) < self._MAX_DEMO_NODES:
            available = [n for n in self._EXTRA_DEMO_NODES if n[0] not in self.network.nodes]
            if available:
                node_id, node_num, short, long, hw = random.choice(available)
                new_node = Node(
                    node_id=node_id,
                    node_num=node_num,
                    short_name=short,
                    long_name=long,
                    hardware_model=hw,
                    role=NodeRole.CLIENT,
                    last_heard=now,
                    is_online=True,
                )
                new_node.telemetry.battery_level = 50 + random.randint(0, 50)
                new_node.telemetry.snr = round(random.uniform(-2.0, 8.0), 1)
                self.network.add_node(new_node)
                self._trigger_callbacks("on_node_update", node_id, True)

                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.NEW_NODE,
                    title="New Node Discovered",
                    message=f"{long} ({short}) joined the mesh",
                    severity=1,
                    source_node=node_id,
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)
                return

        node = random.choice(nodes)

        # 60% chance: incoming text message, 40% chance: telemetry update
        if random.random() < 0.6:
            message = Message(
                id=str(uuid.uuid4()),
                sender_id=node.node_id,
                sender_name=node.short_name or node.long_name,
                recipient_id="^all",
                channel=random.choice([0, 0, 0, 1]),  # mostly ch0
                text=random.choice(self._DEMO_MESSAGES),
                message_type=MessageType.TEXT,
                timestamp=now,
                hop_count=random.randint(0, 3),
                snr=round(random.uniform(-5.0, 10.0), 1),
                rssi=random.randint(-120, -60),
                is_incoming=True,
            )
            self.network.add_message(message)
            node.last_heard = now
            self._trigger_callbacks("on_message", message)
        else:
            # Telemetry drift: battery slowly drains, SNR fluctuates
            node.telemetry.battery_level = max(0, node.telemetry.battery_level + random.randint(-2, 1))
            node.telemetry.snr = round(node.telemetry.snr + random.uniform(-1.0, 1.0), 1)
            node.telemetry.channel_utilization = round(max(0.0, min(100.0, random.uniform(5.0, 35.0))), 1)
            node.telemetry.last_updated = now
            node.last_heard = now
            self._trigger_callbacks("on_telemetry", node)

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Simulate sending a message with byte-length validation."""
        msg_bytes = len(text.encode("utf-8"))
        if msg_bytes > MAX_MESSAGE_BYTES:
            logger.warning("Message too long (%d/%d bytes), rejecting", msg_bytes, MAX_MESSAGE_BYTES)
            return False
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

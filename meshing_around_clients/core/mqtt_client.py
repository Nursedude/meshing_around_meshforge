"""
MQTT Client for Meshing-Around
Connects to Meshtastic MQTT broker for radio-less operation.

Supports:
- Public broker (mqtt.meshtastic.org)
- Private/local MQTT brokers
- TLS encryption
- Message sending and receiving
- Node discovery via MQTT
- Stale node cleanup and bounded memory usage
- Relay node discovery (Meshtastic 2.6+)
- GeoJSON export for map visualization
"""

import atexit
import json
import logging
import random
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .models import (
    CHUTIL_CRITICAL_THRESHOLD,
    CHUTIL_WARNING_THRESHOLD,
    VALID_LAT_RANGE,
    VALID_LON_RANGE,
    VALID_RSSI_RANGE,
    VALID_SNR_RANGE,
    Alert,
    AlertType,
    MeshNetwork,
    MeshRoute,
    Message,
    MessageType,
    Node,
    NodeTelemetry,
    Position,
    RouteHop,
)

logger = logging.getLogger(__name__)

# --- Robustness limits (from meshforge) ---
MAX_PAYLOAD_BYTES = 65536  # 64 KB max per MQTT message
DEFAULT_PORT_TLS = 8883  # Standard MQTT TLS port
STALE_CLEANUP_INTERVAL = 600  # Check every 10 minutes
MAP_CACHE_INTERVAL = 30  # Write GeoJSON cache every 30 seconds

# Try to import paho-mqtt (handles both v1 and v2 API)
try:
    import paho.mqtt.client as mqtt

    MQTT_AVAILABLE = True
    # Detect paho-mqtt v2 (CallbackAPIVersion enum exists in v2+)
    _PAHO_V2 = hasattr(mqtt, "CallbackAPIVersion")
except ImportError:
    MQTT_AVAILABLE = False
    _PAHO_V2 = False

# Try to import mesh crypto module
try:
    from .mesh_crypto import (
        CRYPTO_AVAILABLE,
        PROTOBUF_AVAILABLE,
        MeshPacketProcessor,
        node_num_to_id,
    )

    MESH_CRYPTO_AVAILABLE = True
except (ImportError, OSError, Exception):
    # Catch any exception including pyo3 panics from cryptography backend
    MESH_CRYPTO_AVAILABLE = False
    CRYPTO_AVAILABLE = False
    PROTOBUF_AVAILABLE = False


@dataclass
class MQTTConfig:
    """MQTT connection configuration."""

    broker: str = "mqtt.meshtastic.org"
    port: int = 1883
    use_tls: bool = False
    username: str = "meshdev"
    password: str = "large4cats"
    topic_root: str = "msh/US"
    channel: str = "LongFast"
    node_id: str = ""  # Our node ID for sending
    client_id: str = ""
    encryption_key: str = ""  # Base64 encoded encryption key
    qos: int = 1  # MQTT QoS level
    reconnect_delay: int = 5
    max_reconnect_delay: int = 300  # Max delay between reconnect attempts
    max_reconnect_attempts: int = 10

    @classmethod
    def from_config(cls, config: Config) -> "MQTTConfig":
        """Create MQTTConfig from Config object."""
        return cls(
            broker=config.mqtt.broker,
            port=config.mqtt.port,
            use_tls=config.mqtt.use_tls,
            username=config.mqtt.username,
            password=config.mqtt.password,
            topic_root=config.mqtt.topic_root,
            channel=config.mqtt.channel,
            node_id=config.mqtt.node_id,
            client_id=config.mqtt.client_id,
            encryption_key=config.mqtt.encryption_key,
            qos=config.mqtt.qos,
            reconnect_delay=config.mqtt.reconnect_delay,
            max_reconnect_attempts=config.mqtt.max_reconnect_attempts,
        )


class MQTTMeshtasticClient:
    """
    MQTT client for Meshtastic mesh networks.
    Allows monitoring and participating in mesh without a radio.
    """

    # Supported region prefixes for topic parsing
    REGIONS = ["US", "EU_868", "EU_433", "CN", "JP", "ANZ", "KR", "TW", "RU", "IN", "NZ_865", "TH", "LORA_24"]

    def __init__(self, config: Config, mqtt_config: Optional[MQTTConfig] = None):
        if not MQTT_AVAILABLE:
            raise ImportError("paho-mqtt not installed. Run: pip install paho-mqtt")

        self.config = config
        # Use provided config or build from Config object
        if mqtt_config:
            self.mqtt_config = mqtt_config
        else:
            self.mqtt_config = MQTTConfig.from_config(config)

        # MQTT client
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._reconnect_count = 0
        self._intentional_disconnect = False  # Track intentional vs unexpected disconnects

        # Network state
        self.network = MeshNetwork()

        # Callbacks
        self._callbacks: Dict[str, List[Callable]] = {
            "on_connect": [],
            "on_disconnect": [],
            "on_message": [],
            "on_node_update": [],
            "on_alert": [],
            "on_position": [],
            "on_telemetry": [],
        }

        # Connection health tracking
        self._last_message_time: Optional[datetime] = None
        self._message_count = 0
        self._connection_start: Optional[datetime] = None

        # Thread-safe stats tracking (from meshforge patterns)
        self._stats_lock = threading.Lock()
        self._stats = {
            "messages_received": 0,
            "messages_rejected": 0,
            "nodes_discovered": 0,
            "nodes_pruned": 0,
            "reconnections": 0,
            "telemetry_updates": 0,
            "position_updates": 0,
        }

        # Stale node cleanup
        self._last_cleanup: float = 0
        self._cleanup_interval = STALE_CLEANUP_INTERVAL
        self._cleanup_thread: Optional[threading.Thread] = None

        # Reconnection state
        self._reconnect_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Generate client ID if not set
        if not self.mqtt_config.client_id:
            self.mqtt_config.client_id = f"meshforge-{uuid.uuid4().hex[:8]}"

        # Initialize packet processor for encryption/protobuf decoding
        self._packet_processor: Optional[MeshPacketProcessor] = None
        if MESH_CRYPTO_AVAILABLE:
            self._packet_processor = MeshPacketProcessor(encryption_key=self.mqtt_config.encryption_key)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> Dict[str, Any]:
        """Get subscriber statistics (thread-safe)."""
        with self._stats_lock:
            return dict(self._stats)

    # --- Input validation helpers (from meshforge robustness patterns) ---

    @staticmethod
    def _safe_float(value: Any, min_val: float, max_val: float) -> Optional[float]:
        """Safely extract and validate a float value within range."""
        if value is None:
            return None
        try:
            f = float(value)
            if min_val <= f <= max_val:
                return f
        except (TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _safe_int(value: Any, min_val: int, max_val: int) -> Optional[int]:
        """Safely extract and validate an int value within range."""
        if value is None:
            return None
        try:
            i = int(value)
            if min_val <= i <= max_val:
                return i
        except (TypeError, ValueError):
            pass
        return None

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for an event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, *args, **kwargs) -> None:
        """Trigger all callbacks for an event."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except (TypeError, ValueError, AttributeError) as e:
                logger.warning("MQTT callback error (%s): %s", type(e).__name__, e)

    def _create_mqtt_client(self):
        """Create MQTT client with paho v1/v2 API compatibility."""
        if _PAHO_V2:
            # paho-mqtt v2: requires CallbackAPIVersion
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=self.mqtt_config.client_id,
                protocol=mqtt.MQTTv311,
            )
        else:
            # paho-mqtt v1: original API
            client = mqtt.Client(
                client_id=self.mqtt_config.client_id,
                protocol=mqtt.MQTTv311,
            )
        return client

    def connect(self) -> bool:
        """Connect to MQTT broker."""
        try:
            self._intentional_disconnect = False
            self._stop_event.clear()

            # Create MQTT client (v1/v2 compatible)
            self._client = self._create_mqtt_client()

            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            # Authentication
            if self.mqtt_config.username:
                self._client.username_pw_set(self.mqtt_config.username, self.mqtt_config.password)

            # TLS (auto-detect port 8883)
            if self.mqtt_config.use_tls or self.mqtt_config.port == DEFAULT_PORT_TLS:
                import ssl

                self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

            # Enable paho's built-in reconnect with exponential backoff
            self._client.reconnect_delay_set(
                min_delay=self.mqtt_config.reconnect_delay,
                max_delay=self.mqtt_config.max_reconnect_delay,
            )

            # Connect
            self._client.connect(self.mqtt_config.broker, self.mqtt_config.port, keepalive=60)

            # Start network loop in background
            self._client.loop_start()

            # Register atexit cleanup (from meshforge)
            atexit.register(self._atexit_cleanup)

            # Wait for connection
            timeout = 10
            start = time.time()
            while not self._connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            if self._connected:
                self.network.connection_status = "connected (MQTT)"
                self.network.my_node_id = self.mqtt_config.node_id or "mqtt-client"
                self._connection_start = datetime.now(timezone.utc)
                self._message_count = 0
                with self._stats_lock:
                    self._stats["messages_received"] = 0
                    self._stats["messages_rejected"] = 0
                # Start background stale node cleanup thread
                self._start_cleanup_thread()
                return True
            else:
                # Connection timed out - stop the background loop thread
                self._client.loop_stop()
                return False

        except (OSError, ConnectionError, TimeoutError) as e:
            logger.error("MQTT connection error (%s): %s", type(e).__name__, e)
            return False
        except ValueError as e:
            logger.error("MQTT config error: %s", e)
            return False

    def _atexit_cleanup(self) -> None:
        """Ensure clean disconnect on process exit."""
        try:
            self.disconnect()
        except (OSError, RuntimeError):
            pass

    def _start_cleanup_thread(self) -> None:
        """Start background thread for periodic stale node cleanup.

        Ensures stale nodes are pruned even when no messages are arriving.
        Uses stop_event for clean shutdown instead of polling _connected.
        """

        def cleanup_loop():
            while not self._stop_event.is_set():
                # Use event wait instead of sleep for responsive shutdown
                if self._stop_event.wait(timeout=self._cleanup_interval):
                    break  # Stop event was set
                if not self._connected:
                    break
                pruned = self.network.cleanup_stale_nodes()
                if pruned:
                    with self._stats_lock:
                        self._stats["nodes_pruned"] += pruned
                    logger.info("Background cleanup pruned %d stale nodes", pruned)

        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True, name="mqtt-stale-cleanup")
        self._cleanup_thread.start()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self._intentional_disconnect = True
        self._connected = False  # Signal threads to stop first
        self._stop_event.set()

        # Wait for cleanup thread to finish
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

        # Wait for reconnect thread to finish
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=5)

        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except (OSError, RuntimeError):
                pass  # Already disconnected or broken pipe
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection."""
        if rc == 0:
            was_reconnect = self._connected is False and self._reconnect_count > 0
            self._connected = True
            self._reconnect_count = 0
            if was_reconnect:
                logger.info("Reconnected to MQTT broker: %s", self.mqtt_config.broker)
                with self._stats_lock:
                    self._stats["reconnections"] += 1
            else:
                logger.info("Connected to MQTT broker: %s", self.mqtt_config.broker)

            self.network.connection_status = "connected (MQTT)"

            # Re-subscribe on every connect (handles reconnection)
            self._subscribe_topics()

            self._trigger_callbacks("on_connect")
        else:
            rc_messages = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized",
            }
            reason = rc_messages.get(rc, f"unknown code {rc}")
            logger.error("MQTT connection refused: %s", reason)

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self._connected = False
        self.network.connection_status = "disconnected"

        if rc == 0 or self._intentional_disconnect:
            logger.info("Disconnected from MQTT broker (clean)")
        else:
            logger.warning("Unexpected MQTT disconnect (rc=%d), paho will auto-reconnect", rc)
            # paho's built-in reconnect (enabled via reconnect_delay_set) handles this
            # We track the count for health reporting
            self._reconnect_count += 1

        self._trigger_callbacks("on_disconnect")

    def _subscribe_topics(self):
        """Subscribe to Meshtastic MQTT topics."""
        root = self.mqtt_config.topic_root
        channel = self.mqtt_config.channel
        qos = self.mqtt_config.qos

        # Build comprehensive topic list
        topics = [
            # Primary channel topics
            f"{root}/{channel}/#",  # All messages on configured channel
            # JSON formatted messages (easier to parse)
            f"{root}/2/json/#",  # JSON on default public channel
            f"{root}/+/json/#",  # JSON on any channel
            # Encrypted messages (channel 2 is often public)
            f"{root}/2/e/#",
            # Stats and service messages
            f"{root}/2/stat/#",
        ]

        # If using a specific channel, also subscribe to it explicitly
        if channel and channel != "LongFast":
            topics.append(f"{root}/{channel}/json/#")
            topics.append(f"{root}/{channel}/e/#")

        # Deduplicate and subscribe
        seen = set()
        for topic in topics:
            if topic not in seen:
                seen.add(topic)
                _ = self._client.subscribe(topic, qos=qos)
                logger.info("Subscribed to: %s (qos=%d)", topic, qos)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT message."""
        try:
            topic = msg.topic
            payload = msg.payload

            # Reject oversized payloads (robustness)
            if len(payload) > MAX_PAYLOAD_BYTES:
                with self._stats_lock:
                    self._stats["messages_rejected"] += 1
                return

            # Update message stats
            self._last_message_time = datetime.now(timezone.utc)
            self._message_count += 1
            with self._stats_lock:
                self._stats["messages_received"] += 1
            self.network.last_update = datetime.now(timezone.utc)

            # Note: stale node cleanup handled by background thread
            # (_start_cleanup_thread) to avoid blocking message processing

            # Parse topic to extract metadata
            topic_info = self._parse_topic(topic)

            # Determine message type from topic
            if "/json/" in topic or topic.endswith("/json"):
                self._handle_json_message(topic, payload, topic_info)
            elif "/e/" in topic:
                self._handle_encrypted_message(topic, payload, topic_info)
            elif "/stat/" in topic:
                self._handle_stat_message(topic, payload, topic_info)
            else:
                self._handle_protobuf_message(topic, payload, topic_info)

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Malformed MQTT message on %s: %s", topic, e)
            with self._stats_lock:
                self._stats["messages_rejected"] += 1
        except (KeyError, ValueError, TypeError, struct.error) as e:
            logger.warning("Error parsing MQTT message (%s): %s", type(e).__name__, e)

    def _parse_topic(self, topic: str) -> Dict[str, Any]:
        """Parse MQTT topic to extract metadata."""
        # Topic format: msh/REGION/CHANNEL/TYPE/NODE_ID
        # Examples:
        #   msh/US/LongFast/json/!12345678
        #   msh/US/2/e/!abcdef12
        #   msh/EU_868/2/json/!fedcba98
        parts = topic.split("/")
        info = {"region": "", "channel": "", "msg_type": "", "node_id": "", "raw_topic": topic}

        if len(parts) >= 2:
            info["region"] = parts[1] if parts[1] in self.REGIONS else ""
        if len(parts) >= 3:
            info["channel"] = parts[2]
        if len(parts) >= 4:
            info["msg_type"] = parts[3]  # json, e, stat, etc.
        if len(parts) >= 5:
            info["node_id"] = parts[4]

        return info

    def _handle_stat_message(self, topic: str, payload: bytes, topic_info: Dict[str, Any]):
        """Handle statistics/status messages."""
        try:
            # Stat messages often contain node online/offline status
            _ = json.loads(payload.decode("utf-8"))
            # These can indicate node presence
            node_id = topic_info.get("node_id", "")
            if node_id and node_id.startswith("!"):
                node = self.network.get_node(node_id)
                if node:
                    node.last_heard = datetime.now(timezone.utc)
                    node.is_online = True
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Malformed stat message: %s", e)

    def _handle_json_message(self, topic: str, payload: bytes, topic_info: Dict[str, Any] = None):
        """Handle JSON formatted Meshtastic message."""
        try:
            data = json.loads(payload.decode("utf-8"))
            topic_info = topic_info or {}

            # Extract message info
            sender = data.get("from", 0)
            sender_id = f"!{sender:08x}" if isinstance(sender, int) else str(sender)
            msg_type = data.get("type", "")

            # Generate a message ID for deduplication
            msg_id = data.get("id", "")
            if not msg_id:
                # Generate from sender + timestamp + content hash
                import hashlib

                content = json.dumps(data.get("payload", {}), sort_keys=True)
                msg_id = hashlib.md5(f"{sender_id}{content}".encode()).hexdigest()[:16]

            # Check for duplicate
            if self.network.is_duplicate_message(msg_id):
                return  # Skip duplicate

            # Extract SNR/RSSI with validation (from meshforge patterns)
            snr = self._safe_float(data.get("snr", data.get("rxSnr")), *VALID_SNR_RANGE) or 0.0
            rssi = self._safe_int(data.get("rssi", data.get("rxRssi")), *VALID_RSSI_RANGE) or 0
            hop_limit = self._safe_int(data.get("hopLimit"), 0, 15) or 3
            hop_start = self._safe_int(data.get("hopStart"), 0, 15) or 3
            hop_count = max(0, hop_start - hop_limit)

            # Update node last seen and link quality
            is_new_node = sender_id not in self.network.nodes
            if is_new_node:
                node = Node(
                    node_id=sender_id,
                    node_num=sender if isinstance(sender, int) else 0,
                    last_heard=datetime.now(timezone.utc),
                    first_seen=datetime.now(timezone.utc),
                )
                self.network.add_node(node)
                with self._stats_lock:
                    self._stats["nodes_discovered"] += 1
                self._trigger_callbacks("on_node_update", sender_id, True)
            else:
                node = self.network.get_node(sender_id)
                if node:
                    node.last_heard = datetime.now(timezone.utc)
                    node.is_online = True

            # Update link quality
            if snr or rssi:
                self.network.update_link_quality(sender_id, float(snr), int(rssi), hop_count)

            # Track via node for routing info
            via = data.get("via", data.get("relay", ""))
            if via and sender_id in self.network.nodes:
                via_id = f"!{via:08x}" if isinstance(via, int) else str(via)
                self.network.update_neighbor_relationship(via_id, sender_id)

            # Handle different message types
            if msg_type == "text" or "text" in data.get("payload", {}):
                self._handle_text_from_json(data, sender_id, msg_id)
            elif msg_type == "position" or "position" in data.get("payload", {}):
                self._handle_position_from_json(data, sender_id)
            elif msg_type == "telemetry" or "telemetry" in data.get("payload", {}):
                self._handle_telemetry_from_json(data, sender_id)
            elif msg_type == "nodeinfo" or "user" in data.get("payload", {}):
                self._handle_nodeinfo_from_json(data, sender_id)
            elif msg_type == "traceroute":
                self._handle_traceroute_from_json(data, sender_id)

        except json.JSONDecodeError as e:
            logger.debug("Malformed JSON message on %s: %s", topic, e)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("JSON message parse error (%s): %s", type(e).__name__, e)

    def _handle_text_from_json(self, data: dict, sender_id: str, msg_id: str = ""):
        """Handle text message from JSON."""
        payload = data.get("payload", {})
        text = payload.get("text", "") if isinstance(payload, dict) else str(payload)

        if not text:
            return

        sender_name = ""
        node = self.network.get_node(sender_id)
        if node:
            sender_name = node.display_name

        # Extract signal info for the message
        snr = data.get("snr", data.get("rxSnr", 0.0))
        rssi = data.get("rssi", data.get("rxRssi", 0))
        hop_limit = data.get("hopLimit", 3)
        hop_start = data.get("hopStart", 3)
        hop_count = max(0, hop_start - hop_limit)

        message = Message(
            id=msg_id or str(uuid.uuid4()),
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_id=str(data.get("to", "")),
            channel=data.get("channel", 0),
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            hop_count=hop_count,
            snr=float(snr) if snr else 0.0,
            rssi=int(rssi) if rssi else 0,
            is_incoming=True,
        )

        self.network.add_message(message)
        self._trigger_callbacks("on_message", message)

        # Check for emergency keywords
        self._check_emergency_keywords(message)

    def _handle_traceroute_from_json(self, data: dict, sender_id: str):
        """Handle traceroute response message."""
        try:
            payload = data.get("payload", {})
            route_data = payload.get("route", payload.get("traceroute", []))

            if not route_data:
                return

            # Build route from traceroute response
            hops = []
            for hop in route_data:
                if isinstance(hop, dict):
                    hop_id = hop.get("node", hop.get("from", ""))
                    hop_snr = hop.get("snr", 0.0)
                else:
                    hop_id = f"!{hop:08x}" if isinstance(hop, int) else str(hop)
                    hop_snr = 0.0

                hops.append(RouteHop(node_id=hop_id, snr=hop_snr, timestamp=datetime.now(timezone.utc)))

            if hops:
                route = MeshRoute(
                    destination_id=sender_id,
                    hops=hops,
                    discovered=datetime.now(timezone.utc),
                    last_used=datetime.now(timezone.utc),
                    is_preferred=True,
                )
                self.network.update_route(sender_id, route)

        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Traceroute handling error (%s): %s", type(e).__name__, e)

    def _handle_position_from_json(self, data: dict, sender_id: str):
        """Handle position update from JSON with coordinate validation."""
        payload = data.get("payload", {})
        pos_data = payload.get("position", payload)

        node = self.network.get_node(sender_id)
        if node:

            # Validate coordinates (from meshforge robustness patterns)
            lat = self._safe_float(pos_data.get("latitude"), *VALID_LAT_RANGE)
            if lat is None:
                lat_i = pos_data.get("latitudeI", 0)
                lat = lat_i / 1e7 if lat_i else None
                if lat is not None:
                    lat = self._safe_float(lat, *VALID_LAT_RANGE)

            lon = self._safe_float(pos_data.get("longitude"), *VALID_LON_RANGE)
            if lon is None:
                lon_i = pos_data.get("longitudeI", 0)
                lon = lon_i / 1e7 if lon_i else None
                if lon is not None:
                    lon = self._safe_float(lon, *VALID_LON_RANGE)

            # Only update position if coordinates are valid
            if lat is not None and lon is not None:
                node.position = Position(
                    latitude=lat, longitude=lon, altitude=pos_data.get("altitude", 0), time=datetime.now(timezone.utc)
                )
            node.last_heard = datetime.now(timezone.utc)

    def _handle_telemetry_from_json(self, data: dict, sender_id: str):
        """Handle telemetry from JSON with input validation."""
        payload = data.get("payload", {})
        telemetry = payload.get("telemetry", payload)
        device_metrics = telemetry.get("deviceMetrics", telemetry)

        node = self.network.get_node(sender_id)
        if node:

            # Validate device metrics (from meshforge patterns)
            battery = self._safe_int(device_metrics.get("batteryLevel"), 0, 101) or 0
            voltage = self._safe_float(device_metrics.get("voltage"), 0.0, 10.0) or 0.0
            ch_util = self._safe_float(device_metrics.get("channelUtilization"), 0.0, 100.0) or 0.0
            air_util = self._safe_float(device_metrics.get("airUtilTx"), 0.0, 100.0) or 0.0

            # Environment metrics (BME280, BME680, BMP280)
            env_metrics = telemetry.get("environmentMetrics", {})
            temperature = self._safe_float(env_metrics.get("temperature"), -50.0, 100.0)
            humidity = self._safe_float(env_metrics.get("relativeHumidity"), 0.0, 100.0)
            pressure = self._safe_float(env_metrics.get("barometricPressure"), 300.0, 1200.0)
            gas_resistance = self._safe_float(env_metrics.get("gasResistance"), 0.0, 1000000.0)

            node.telemetry = NodeTelemetry(
                battery_level=battery,
                voltage=voltage,
                channel_utilization=ch_util,
                air_util_tx=air_util,
                last_updated=datetime.now(timezone.utc),
                temperature=temperature,
                humidity=humidity,
                pressure=pressure,
                gas_resistance=gas_resistance,
            )
            node.last_heard = datetime.now(timezone.utc)

            # Battery alert
            if node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.BATTERY,
                    title="Low Battery (MQTT)",
                    message=f"{node.display_name} at {node.telemetry.battery_level}%",
                    severity=2,
                    source_node=sender_id,
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)

            # Channel congestion alert (from meshforge thresholds)
            if ch_util >= CHUTIL_CRITICAL_THRESHOLD:
                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.CUSTOM,
                    title="Channel Congestion (MQTT)",
                    message=f"{node.display_name} channel utilization {ch_util:.1f}%",
                    severity=3,
                    source_node=sender_id,
                    metadata={"channel_utilization": ch_util},
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)
            elif ch_util >= CHUTIL_WARNING_THRESHOLD:
                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.CUSTOM,
                    title="Channel Utilization Warning",
                    message=f"{node.display_name} channel utilization {ch_util:.1f}%",
                    severity=2,
                    source_node=sender_id,
                    metadata={"channel_utilization": ch_util},
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)

    def _handle_nodeinfo_from_json(self, data: dict, sender_id: str):
        """Handle node info from JSON."""
        payload = data.get("payload", {})
        user = payload.get("user", payload)

        node = self.network.get_node(sender_id)
        if not node:
            node = Node(
                node_id=sender_id,
                node_num=data.get("from", 0),
            )
            self.network.add_node(node)

        node.short_name = user.get("shortName", node.short_name)
        node.long_name = user.get("longName", node.long_name)
        node.hardware_model = user.get("hwModel", node.hardware_model)
        node.last_heard = datetime.now(timezone.utc)

        self._trigger_callbacks("on_node_update", sender_id, False)

    def _handle_encrypted_message(self, topic: str, payload: bytes, topic_info: Dict[str, Any] = None):
        """Handle encrypted Meshtastic message with full decryption support."""
        try:
            topic_info = topic_info or self._parse_topic(topic)
            node_id = topic_info.get("node_id", "")

            # Try to decrypt and decode using packet processor
            if self._packet_processor and CRYPTO_AVAILABLE:
                result = self._packet_processor.process_encrypted_packet(payload)

                if result.success and result.decoded:
                    # Successfully decrypted - process the decoded content
                    sender_id = node_num_to_id(result.sender) if result.sender else node_id
                    self._process_decoded_packet(result, sender_id, topic_info)
                    return

            # Fallback: Extract metadata from topic and header
            if node_id and node_id.startswith("!"):
                # Update that we've seen this node
                existing = self.network.get_node(node_id)
                if existing:
                    existing.last_heard = datetime.now(timezone.utc)
                    existing.is_online = True
                else:
                    # Create minimal node entry
                    try:
                        node_num = int(node_id[1:], 16)
                    except ValueError:
                        node_num = 0
                    node = Node(
                        node_id=node_id,
                        node_num=node_num,
                        last_heard=datetime.now(timezone.utc),
                        first_seen=datetime.now(timezone.utc),
                    )
                    self.network.add_node(node)
                    self._trigger_callbacks("on_node_update", node_id, True)

            # Try to extract basic packet info from protobuf header
            if len(payload) >= 16:
                self._parse_encrypted_header(payload, node_id)

        except (ValueError, struct.error, KeyError, TypeError) as e:
            logger.warning("Encrypted message handling error (%s): %s", type(e).__name__, e)

    def _parse_encrypted_header(self, payload: bytes, node_id: str):
        """Parse the unencrypted header of an encrypted message."""
        # Meshtastic packet structure has some unencrypted fields
        # First 4 bytes: destination node (little-endian)
        # Next 4 bytes: sender node (little-endian)
        # Next 4 bytes: packet id
        try:
            if len(payload) < 12:
                return

            sender = struct.unpack("<I", payload[4:8])[0]

            sender_id = f"!{sender:08x}"
            node = self.network.get_node(sender_id)
            if node:
                node.last_heard = datetime.now(timezone.utc)

        except struct.error:
            pass

    def _handle_protobuf_message(self, topic: str, payload: bytes, topic_info: Dict[str, Any] = None):
        """Handle protobuf Meshtastic message with full decoding."""
        topic_info = topic_info or self._parse_topic(topic)
        node_id = topic_info.get("node_id", "")

        # Try full protobuf decoding
        if self._packet_processor and PROTOBUF_AVAILABLE:
            result = self._packet_processor.process_encrypted_packet(payload)

            if result.success and result.decoded:
                sender_id = node_num_to_id(result.sender) if result.sender else node_id
                self._process_decoded_packet(result, sender_id, topic_info)
                return

        # Fallback: update node last seen
        if node_id and node_id.startswith("!"):
            existing = self.network.get_node(node_id)
            if existing:
                existing.last_heard = datetime.now(timezone.utc)
                existing.is_online = True
            else:
                # Create minimal node entry
                try:
                    node_num = int(node_id[1:], 16)
                except ValueError:
                    node_num = 0
                node = Node(
                    node_id=node_id,
                    node_num=node_num,
                    last_heard=datetime.now(timezone.utc),
                    first_seen=datetime.now(timezone.utc),
                )
                self.network.add_node(node)
                self._trigger_callbacks("on_node_update", node_id, True)

    def _process_decoded_packet(self, result, sender_id: str, topic_info: Dict[str, Any]):
        """Process a fully decoded packet from the packet processor."""
        decoded = result.decoded
        portnum = result.portnum
        msg_type = decoded.get("type", "")

        # Generate message ID for deduplication
        msg_id = str(result.packet_id) if result.packet_id else ""
        if msg_id and self.network.is_duplicate_message(msg_id):
            return  # Skip duplicate

        # Update/create node
        existing_node = self.network.get_node(sender_id)
        if not existing_node:
            new_node = Node(
                node_id=sender_id,
                node_num=result.sender,
                last_heard=datetime.now(timezone.utc),
                first_seen=datetime.now(timezone.utc),
            )
            self.network.add_node(new_node)
            self._trigger_callbacks("on_node_update", sender_id, True)
        else:
            existing_node.last_heard = datetime.now(timezone.utc)
            existing_node.is_online = True

        # Extract SNR/RSSI if available
        snr = decoded.get("rx_snr", 0)
        rssi = decoded.get("rx_rssi", 0)
        hop_limit = decoded.get("hop_limit", 3)
        hop_count = max(0, 3 - hop_limit)  # Estimate hops

        if snr or rssi:
            self.network.update_link_quality(sender_id, float(snr), int(rssi), hop_count)

        # Handle relay node (Meshtastic 2.6+)
        relay_node = decoded.get("relay_node", 0)
        if relay_node:
            self._handle_relay_node(relay_node, sender_id)

        # Handle by type
        if msg_type == "text" or portnum == 1:
            text = decoded.get("text", "")
            if text:
                self._handle_decoded_text(text, sender_id, msg_id, decoded, topic_info)

        elif msg_type == "position" or portnum == 3:
            pos_data = decoded.get("position", {})
            node = self.network.get_node(sender_id)
            if pos_data and node:
                # Validate coordinates (consistent with JSON path)
                lat = self._safe_float(pos_data.get("latitude"), *VALID_LAT_RANGE)
                lon = self._safe_float(pos_data.get("longitude"), *VALID_LON_RANGE)
                if lat is not None and lon is not None:
                    node.position = Position(
                        latitude=lat,
                        longitude=lon,
                        altitude=pos_data.get("altitude", 0),
                        time=datetime.now(timezone.utc),
                    )
                    with self._stats_lock:
                        self._stats["position_updates"] += 1
                    self._trigger_callbacks("on_position", sender_id)

        elif msg_type == "telemetry" or portnum == 67:
            telemetry_data = decoded.get("telemetry", {})
            device_metrics = telemetry_data.get("device_metrics", {})
            node = self.network.get_node(sender_id)
            if device_metrics and node:
                node.telemetry = NodeTelemetry(
                    battery_level=device_metrics.get("battery_level", 0),
                    voltage=device_metrics.get("voltage", 0),
                    channel_utilization=device_metrics.get("channel_utilization", 0),
                    air_util_tx=device_metrics.get("air_util_tx", 0),
                    uptime_seconds=device_metrics.get("uptime_seconds", 0),
                    last_updated=datetime.now(timezone.utc),
                )
                with self._stats_lock:
                    self._stats["telemetry_updates"] += 1
                self._trigger_callbacks("on_telemetry", sender_id)

                # Battery alert
                if node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.BATTERY,
                        title="Low Battery",
                        message=f"{node.display_name} at {node.telemetry.battery_level}%",
                        severity=2,
                        source_node=sender_id,
                    )
                    self.network.add_alert(alert)
                    self._trigger_callbacks("on_alert", alert)

        elif msg_type == "nodeinfo" or portnum == 4:
            user_data = decoded.get("user", {})
            node = self.network.get_node(sender_id)
            if user_data and node:
                node.short_name = user_data.get("short_name", node.short_name)
                node.long_name = user_data.get("long_name", node.long_name)
                hw_model = user_data.get("hw_model", 0)
                if hw_model:
                    node.hardware_model = str(hw_model)
                self._trigger_callbacks("on_node_update", sender_id, False)

        elif msg_type == "traceroute" or portnum == 70:
            traceroute_data = decoded.get("traceroute", {})
            route_list = traceroute_data.get("route", [])
            snr_list = traceroute_data.get("snr_towards", [])
            if route_list:
                hops = []
                for i, hop_id in enumerate(route_list):
                    hop_snr = snr_list[i] if i < len(snr_list) else 0.0
                    hop_node_id = node_num_to_id(hop_id) if isinstance(hop_id, int) else str(hop_id)
                    hops.append(RouteHop(node_id=hop_node_id, snr=float(hop_snr), timestamp=datetime.now(timezone.utc)))
                if hops:
                    route = MeshRoute(
                        destination_id=sender_id,
                        hops=hops,
                        discovered=datetime.now(timezone.utc),
                        last_used=datetime.now(timezone.utc),
                        is_preferred=True,
                    )
                    self.network.update_route(sender_id, route)

        elif msg_type == "neighborinfo" or portnum == 71:
            neighbor_data = decoded.get("neighborinfo", {})
            neighbors = neighbor_data.get("neighbors", [])
            for neighbor in neighbors:
                neighbor_id = neighbor.get("node_id", 0)
                if neighbor_id:
                    neighbor_node_id = node_num_to_id(neighbor_id) if isinstance(neighbor_id, int) else str(neighbor_id)
                    self.network.update_neighbor_relationship(sender_id, neighbor_node_id)
                    # Update link quality between sender and neighbor
                    neighbor_snr = neighbor.get("snr", 0)
                    if neighbor_snr and self.network.get_node(neighbor_node_id):
                        self.network.update_link_quality(neighbor_node_id, float(neighbor_snr), 0, 1)

    def _handle_relay_node(self, relay_node: int, sender_id: str) -> None:
        """Handle relay node discovery (Meshtastic 2.6+).

        When relay_node contains only the last byte of a node ID,
        we create a placeholder entry that can be merged later.
        From meshforge's MQTTNodelessSubscriber pattern.
        """
        if not relay_node:
            return

        if relay_node > 0xFFFF:
            # Full node number
            relay_id = f"!{relay_node:08x}"
        else:
            # Partial relay node (last 1-2 bytes) - create placeholder
            relay_id = f"!????{relay_node:04x}"

        relay_existing = self.network.get_node(relay_id)
        if not relay_existing:
            relay_existing = Node(
                node_id=relay_id,
                node_num=relay_node,
                last_heard=datetime.now(timezone.utc),
                first_seen=datetime.now(timezone.utc),
            )
            self.network.add_node(relay_existing)

        relay_existing.last_heard = datetime.now(timezone.utc)
        relay_existing.is_online = True

        # Track routing relationship
        self.network.update_neighbor_relationship(relay_id, sender_id)

    def _handle_decoded_text(self, text: str, sender_id: str, msg_id: str, decoded: Dict, topic_info: Dict):
        """Handle decoded text message."""
        sender_name = ""
        node = self.network.get_node(sender_id)
        if node:
            sender_name = node.display_name

        snr = decoded.get("rx_snr", 0)
        rssi = decoded.get("rx_rssi", 0)
        hop_limit = decoded.get("hop_limit", 3)
        hop_count = max(0, 3 - hop_limit)
        channel = decoded.get("channel", 0)

        message = Message(
            id=msg_id or str(uuid.uuid4()),
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_id=str(decoded.get("to", "")),
            channel=channel,
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            hop_count=hop_count,
            snr=float(snr) if snr else 0.0,
            rssi=int(rssi) if rssi else 0,
            is_incoming=True,
        )

        self.network.add_message(message)
        self._trigger_callbacks("on_message", message)
        self._check_emergency_keywords(message)

    def _check_emergency_keywords(self, message: Message):
        """Check message for emergency keywords."""
        if not self.config.alerts.enabled:
            return

        text_lower = message.text.lower()
        for keyword in self.config.alerts.emergency_keywords:
            if keyword.lower() in text_lower:
                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.EMERGENCY,
                    title="Emergency Keyword (MQTT)",
                    message=f"{message.sender_name}: {message.text}",
                    severity=4,
                    source_node=message.sender_id,
                    metadata={"keyword": keyword},
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)
                break

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Send a message via MQTT."""
        if not self._connected or not self._client:
            return False

        if not self.mqtt_config.node_id:
            logger.warning("Cannot send: no node_id configured for MQTT")
            return False

        try:
            # Build JSON message
            message = {
                "from": self.mqtt_config.node_id,
                "to": destination,
                "channel": channel,
                "type": "text",
                "payload": {"text": text},
            }

            # Publish to appropriate topic
            topic = f"{self.mqtt_config.topic_root}/{self.mqtt_config.channel}/json/{self.mqtt_config.node_id}"
            self._client.publish(topic, json.dumps(message))

            # Log outgoing message
            out_msg = Message(
                id=str(uuid.uuid4()),
                sender_id=self.mqtt_config.node_id,
                sender_name="Me (MQTT)",
                recipient_id=destination,
                channel=channel,
                text=text,
                message_type=MessageType.TEXT,
                timestamp=datetime.now(timezone.utc),
                is_incoming=False,
            )
            self.network.add_message(out_msg)

            return True

        except (OSError, ConnectionError, ValueError, TypeError) as e:
            logger.error("MQTT send error (%s): %s", type(e).__name__, e)
            return False

    def get_nodes(self) -> List[Node]:
        """Get all known nodes."""
        return list(self.network.nodes.values())

    def get_messages(self, channel: Optional[int] = None, limit: int = 100) -> List[Message]:
        """Get messages."""
        messages = list(self.network.messages)
        if channel is not None:
            messages = [m for m in messages if m.channel == channel]
        return messages[-limit:]

    def get_alerts(self, unread_only: bool = False) -> List[Alert]:
        """Get alerts."""
        if unread_only:
            return self.network.unread_alerts
        return self.network.alerts

    @property
    def connection_health(self) -> Dict[str, Any]:
        """Get connection health metrics."""
        now = datetime.now(timezone.utc)

        # Calculate uptime
        uptime_seconds = 0
        if self._connection_start and self._connected:
            uptime_seconds = (now - self._connection_start).total_seconds()

        # Calculate message rate (messages per minute)
        msg_rate = 0.0
        if uptime_seconds > 0:
            msg_rate = (self._message_count / uptime_seconds) * 60

        # Time since last message
        last_msg_ago = None
        if self._last_message_time:
            last_msg_ago = (now - self._last_message_time).total_seconds()

        # Determine health status
        if not self._connected:
            status = "disconnected"
        elif last_msg_ago is None:
            status = "connected_no_traffic"
        elif last_msg_ago > 300:  # 5 minutes
            status = "stale"
        elif last_msg_ago > 60:
            status = "slow"
        else:
            status = "healthy"

        with self._stats_lock:
            stats_copy = dict(self._stats)

        return {
            "status": status,
            "connected": self._connected,
            "broker": self.mqtt_config.broker,
            "uptime_seconds": int(uptime_seconds),
            "message_count": self._message_count,
            "messages_per_minute": round(msg_rate, 2),
            "last_message_ago_seconds": int(last_msg_ago) if last_msg_ago else None,
            "reconnect_count": self._reconnect_count,
            "stats": stats_copy,
        }

    def get_geojson(self) -> Dict[str, Any]:
        """Export nodes with positions as GeoJSON FeatureCollection.

        Compatible with meshforge's map cache format for Leaflet.js visualization.
        """
        features = []
        for node in self.get_nodes():
            if node.position and node.position.is_valid():
                properties = {
                    "node_id": node.node_id,
                    "name": node.display_name,
                    "short_name": node.short_name,
                    "long_name": node.long_name,
                    "hardware_model": node.hardware_model,
                    "is_online": node.is_online,
                    "last_heard": node.last_heard.isoformat() if node.last_heard else None,
                    "altitude": node.position.altitude,
                }
                if node.telemetry:
                    properties["battery_level"] = node.telemetry.battery_level
                    properties["channel_utilization"] = node.telemetry.channel_utilization
                if node.link_quality and node.link_quality.packet_count > 0:
                    properties["snr"] = round(node.link_quality.snr_avg, 2)
                    properties["quality_percent"] = node.link_quality.quality_percent

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [node.position.longitude, node.position.latitude],
                        },
                        "properties": properties,
                    }
                )

        return {"type": "FeatureCollection", "features": features}

    def get_nodes_with_position(self) -> List[Node]:
        """Get nodes that have valid position data."""
        return [n for n in self.get_nodes() if n.position and n.position.is_valid()]

    def get_online_nodes(self) -> List[Node]:
        """Get only online nodes."""
        return [n for n in self.get_nodes() if n.is_online]

    def get_congested_nodes(self, threshold: float = CHUTIL_WARNING_THRESHOLD) -> List[Node]:
        """Get nodes reporting channel utilization above threshold."""
        return [
            n
            for n in self.get_nodes()
            if n.telemetry and n.telemetry.channel_utilization >= threshold
        ]


class MQTTConnectionManager:
    """
    Manages MQTT connection with automatic reconnection.

    Uses exponential backoff for reconnection attempts (from meshforge patterns).
    """

    def __init__(self, client: MQTTMeshtasticClient, reconnect_delay: int = 5, max_reconnect_delay: int = 300):
        self.client = client
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0

    def start(self):
        """Start connection manager."""
        self._running = True
        self._consecutive_failures = 0
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop connection manager."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _monitor_loop(self):
        """Monitor connection and reconnect with exponential backoff."""
        while self._running:
            if not self.client.is_connected:
                # Exponential backoff with jitter to prevent thundering herd
                base_delay = min(self.reconnect_delay * (1.5**self._consecutive_failures), self.max_reconnect_delay)
                # Add +/-25% jitter
                delay = base_delay * (0.75 + random.random() * 0.5)
                logger.info("MQTT disconnected, reconnecting in %.0fs...", delay)
                time.sleep(delay)

                if not self._running:
                    break

                if self.client.connect():
                    self._consecutive_failures = 0
                    logger.info("MQTT reconnected successfully")
                else:
                    self._consecutive_failures += 1
                    logger.warning("MQTT reconnect failed (attempt %d)", self._consecutive_failures)
            else:
                self._consecutive_failures = 0
                time.sleep(self.reconnect_delay)

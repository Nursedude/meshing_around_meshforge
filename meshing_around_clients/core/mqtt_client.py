"""
MQTT Client for Meshing-Around
Connects to Meshtastic MQTT broker for radio-less operation.

Supports:
- Public broker (mqtt.meshtastic.org)
- Private/local MQTT brokers
- TLS encryption
- Message sending and receiving
- Node discovery via MQTT
"""

import json
import time
import uuid
import base64
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, List, Any
from dataclasses import dataclass
import struct

from .models import (
    Node, Message, Alert, MeshNetwork, Position, NodeTelemetry,
    NodeRole, MessageType, AlertType, LinkQuality, RouteHop, MeshRoute
)
from .config import Config, MQTTConfig as ConfigMQTTConfig

# Try to import paho-mqtt
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# Try to import mesh crypto module
try:
    from .mesh_crypto import (
        MeshCrypto, ProtobufDecoder, MeshPacketProcessor,
        node_id_to_num, node_num_to_id, CRYPTO_AVAILABLE, PROTOBUF_AVAILABLE
    )
    MESH_CRYPTO_AVAILABLE = True
except ImportError:
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
            max_reconnect_attempts=config.mqtt.max_reconnect_attempts
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

        # Generate client ID if not set
        if not self.mqtt_config.client_id:
            self.mqtt_config.client_id = f"meshforge-{uuid.uuid4().hex[:8]}"

        # Initialize packet processor for encryption/protobuf decoding
        self._packet_processor: Optional[MeshPacketProcessor] = None
        if MESH_CRYPTO_AVAILABLE:
            self._packet_processor = MeshPacketProcessor(
                encryption_key=self.mqtt_config.encryption_key
            )

    @property
    def is_connected(self) -> bool:
        return self._connected

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for an event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, *args, **kwargs) -> None:
        """Trigger all callbacks for an event."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"MQTT callback error: {e}")

    def connect(self) -> bool:
        """Connect to MQTT broker."""
        try:
            # Create MQTT client
            self._client = mqtt.Client(
                client_id=self.mqtt_config.client_id,
                protocol=mqtt.MQTTv311
            )

            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            # Authentication
            if self.mqtt_config.username:
                self._client.username_pw_set(
                    self.mqtt_config.username,
                    self.mqtt_config.password
                )

            # TLS
            if self.mqtt_config.use_tls:
                self._client.tls_set()

            # Connect
            self._client.connect(
                self.mqtt_config.broker,
                self.mqtt_config.port,
                keepalive=60
            )

            # Start network loop in background
            self._client.loop_start()

            # Wait for connection
            timeout = 10
            start = time.time()
            while not self._connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            if self._connected:
                self.network.connection_status = "connected (MQTT)"
                self.network.my_node_id = self.mqtt_config.node_id or "mqtt-client"
                self._connection_start = datetime.now()
                self._message_count = 0
                return True
            else:
                # Connection timed out — stop the background loop thread
                self._client.loop_stop()
                return False

        except Exception as e:
            print(f"MQTT connection error: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        self._connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection."""
        if rc == 0:
            self._connected = True
            print(f"Connected to MQTT broker: {self.mqtt_config.broker}")

            # Subscribe to topics
            self._subscribe_topics()

            self._trigger_callbacks("on_connect")
        else:
            print(f"MQTT connection failed with code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self._connected = False
        self.network.connection_status = "disconnected"
        print(f"Disconnected from MQTT broker (rc={rc})")
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
                result = self._client.subscribe(topic, qos=qos)
                print(f"Subscribed to: {topic} (qos={qos})")

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT message."""
        try:
            topic = msg.topic
            payload = msg.payload

            # Update message stats
            self._last_message_time = datetime.now()
            self._message_count += 1
            self.network.last_update = datetime.now()

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

        except Exception as e:
            print(f"Error handling MQTT message: {e}")

    def _parse_topic(self, topic: str) -> Dict[str, Any]:
        """Parse MQTT topic to extract metadata."""
        # Topic format: msh/REGION/CHANNEL/TYPE/NODE_ID
        # Examples:
        #   msh/US/LongFast/json/!12345678
        #   msh/US/2/e/!abcdef12
        #   msh/EU_868/2/json/!fedcba98
        parts = topic.split("/")
        info = {
            "region": "",
            "channel": "",
            "msg_type": "",
            "node_id": "",
            "raw_topic": topic
        }

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
            data = json.loads(payload.decode('utf-8'))
            # These can indicate node presence
            node_id = topic_info.get("node_id", "")
            if node_id and node_id.startswith("!"):
                if node_id in self.network.nodes:
                    self.network.nodes[node_id].last_heard = datetime.now()
                    self.network.nodes[node_id].is_online = True
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    def _handle_json_message(self, topic: str, payload: bytes, topic_info: Dict[str, Any] = None):
        """Handle JSON formatted Meshtastic message."""
        try:
            data = json.loads(payload.decode('utf-8'))
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

            # Extract SNR/RSSI if available (for link quality)
            snr = data.get("snr", data.get("rxSnr", 0.0))
            rssi = data.get("rssi", data.get("rxRssi", 0))
            hop_limit = data.get("hopLimit", 3)
            hop_start = data.get("hopStart", 3)
            hop_count = max(0, hop_start - hop_limit)

            # Update node last seen and link quality
            is_new_node = sender_id not in self.network.nodes
            if is_new_node:
                node = Node(
                    node_id=sender_id,
                    node_num=sender if isinstance(sender, int) else 0,
                    last_heard=datetime.now(),
                    first_seen=datetime.now()
                )
                self.network.add_node(node)
                self._trigger_callbacks("on_node_update", sender_id, True)
            else:
                self.network.nodes[sender_id].last_heard = datetime.now()
                self.network.nodes[sender_id].is_online = True

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

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"JSON message error: {e}")

    def _handle_text_from_json(self, data: dict, sender_id: str, msg_id: str = ""):
        """Handle text message from JSON."""
        payload = data.get("payload", {})
        text = payload.get("text", "") if isinstance(payload, dict) else str(payload)

        if not text:
            return

        sender_name = ""
        if sender_id in self.network.nodes:
            sender_name = self.network.nodes[sender_id].display_name

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
            timestamp=datetime.now(),
            hop_count=hop_count,
            snr=float(snr) if snr else 0.0,
            rssi=int(rssi) if rssi else 0,
            is_incoming=True
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

                hops.append(RouteHop(
                    node_id=hop_id,
                    snr=hop_snr,
                    timestamp=datetime.now()
                ))

            if hops:
                route = MeshRoute(
                    destination_id=sender_id,
                    hops=hops,
                    discovered=datetime.now(),
                    last_used=datetime.now(),
                    is_preferred=True
                )
                self.network.update_route(sender_id, route)

        except Exception as e:
            print(f"Traceroute handling error: {e}")

    def _handle_position_from_json(self, data: dict, sender_id: str):
        """Handle position update from JSON."""
        payload = data.get("payload", {})
        pos_data = payload.get("position", payload)

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            lat = pos_data.get("latitude")
            if lat is None:
                lat_i = pos_data.get("latitudeI", 0)
                lat = lat_i / 1e7 if lat_i else 0.0
            lon = pos_data.get("longitude")
            if lon is None:
                lon_i = pos_data.get("longitudeI", 0)
                lon = lon_i / 1e7 if lon_i else 0.0
            node.position = Position(
                latitude=lat,
                longitude=lon,
                altitude=pos_data.get("altitude", 0),
                time=datetime.now()
            )
            node.last_heard = datetime.now()

    def _handle_telemetry_from_json(self, data: dict, sender_id: str):
        """Handle telemetry from JSON."""
        payload = data.get("payload", {})
        telemetry = payload.get("telemetry", payload)
        device_metrics = telemetry.get("deviceMetrics", telemetry)

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            node.telemetry = NodeTelemetry(
                battery_level=device_metrics.get("batteryLevel", 0),
                voltage=device_metrics.get("voltage", 0),
                channel_utilization=device_metrics.get("channelUtilization", 0),
                air_util_tx=device_metrics.get("airUtilTx", 0),
                last_updated=datetime.now()
            )
            node.last_heard = datetime.now()

            # Battery alert
            if node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.BATTERY,
                    title="Low Battery (MQTT)",
                    message=f"{node.display_name} at {node.telemetry.battery_level}%",
                    severity=2,
                    source_node=sender_id
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)

    def _handle_nodeinfo_from_json(self, data: dict, sender_id: str):
        """Handle node info from JSON."""
        payload = data.get("payload", {})
        user = payload.get("user", payload)

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
        else:
            node = Node(
                node_id=sender_id,
                node_num=data.get("from", 0),
            )
            self.network.add_node(node)

        node.short_name = user.get("shortName", node.short_name)
        node.long_name = user.get("longName", node.long_name)
        node.hardware_model = user.get("hwModel", node.hardware_model)
        node.last_heard = datetime.now()

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
                if node_id in self.network.nodes:
                    self.network.nodes[node_id].last_heard = datetime.now()
                    self.network.nodes[node_id].is_online = True
                else:
                    # Create minimal node entry
                    try:
                        node_num = int(node_id[1:], 16)
                    except ValueError:
                        node_num = 0
                    node = Node(
                        node_id=node_id,
                        node_num=node_num,
                        last_heard=datetime.now(),
                        first_seen=datetime.now()
                    )
                    self.network.add_node(node)
                    self._trigger_callbacks("on_node_update", node_id, True)

            # Try to extract basic packet info from protobuf header
            if len(payload) >= 16:
                self._parse_encrypted_header(payload, node_id)

        except Exception as e:
            print(f"Encrypted message handling error: {e}")

    def _parse_encrypted_header(self, payload: bytes, node_id: str):
        """Parse the unencrypted header of an encrypted message."""
        # Meshtastic packet structure has some unencrypted fields
        # First 4 bytes: destination node (little-endian)
        # Next 4 bytes: sender node (little-endian)
        # Next 4 bytes: packet id
        try:
            if len(payload) < 12:
                return

            dest = struct.unpack('<I', payload[0:4])[0]
            sender = struct.unpack('<I', payload[4:8])[0]
            packet_id = struct.unpack('<I', payload[8:12])[0]

            sender_id = f"!{sender:08x}"
            if sender_id in self.network.nodes:
                self.network.nodes[sender_id].last_heard = datetime.now()

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
            if node_id in self.network.nodes:
                self.network.nodes[node_id].last_heard = datetime.now()
                self.network.nodes[node_id].is_online = True
            else:
                # Create minimal node entry
                try:
                    node_num = int(node_id[1:], 16)
                except ValueError:
                    node_num = 0
                node = Node(
                    node_id=node_id,
                    node_num=node_num,
                    last_heard=datetime.now(),
                    first_seen=datetime.now()
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
        is_new_node = sender_id not in self.network.nodes
        if is_new_node:
            node = Node(
                node_id=sender_id,
                node_num=result.sender,
                last_heard=datetime.now(),
                first_seen=datetime.now()
            )
            self.network.add_node(node)
            self._trigger_callbacks("on_node_update", sender_id, True)
        else:
            self.network.nodes[sender_id].last_heard = datetime.now()
            self.network.nodes[sender_id].is_online = True

        # Extract SNR/RSSI if available
        snr = decoded.get("rx_snr", 0)
        rssi = decoded.get("rx_rssi", 0)
        hop_limit = decoded.get("hop_limit", 3)
        hop_count = max(0, 3 - hop_limit)  # Estimate hops

        if snr or rssi:
            self.network.update_link_quality(sender_id, float(snr), int(rssi), hop_count)

        # Handle by type
        if msg_type == "text" or portnum == 1:
            text = decoded.get("text", "")
            if text:
                self._handle_decoded_text(text, sender_id, msg_id, decoded, topic_info)

        elif msg_type == "position" or portnum == 3:
            pos_data = decoded.get("position", {})
            if pos_data and sender_id in self.network.nodes:
                node = self.network.nodes[sender_id]
                node.position = Position(
                    latitude=pos_data.get("latitude", 0),
                    longitude=pos_data.get("longitude", 0),
                    altitude=pos_data.get("altitude", 0),
                    time=datetime.now()
                )
                self._trigger_callbacks("on_position", sender_id)

        elif msg_type == "telemetry" or portnum == 67:
            telemetry_data = decoded.get("telemetry", {})
            device_metrics = telemetry_data.get("device_metrics", {})
            if device_metrics and sender_id in self.network.nodes:
                node = self.network.nodes[sender_id]
                node.telemetry = NodeTelemetry(
                    battery_level=device_metrics.get("battery_level", 0),
                    voltage=device_metrics.get("voltage", 0),
                    channel_utilization=device_metrics.get("channel_utilization", 0),
                    air_util_tx=device_metrics.get("air_util_tx", 0),
                    uptime_seconds=device_metrics.get("uptime_seconds", 0),
                    last_updated=datetime.now()
                )
                self._trigger_callbacks("on_telemetry", sender_id)

                # Battery alert
                if node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.BATTERY,
                        title="Low Battery",
                        message=f"{node.display_name} at {node.telemetry.battery_level}%",
                        severity=2,
                        source_node=sender_id
                    )
                    self.network.add_alert(alert)
                    self._trigger_callbacks("on_alert", alert)

        elif msg_type == "nodeinfo" or portnum == 4:
            user_data = decoded.get("user", {})
            if user_data and sender_id in self.network.nodes:
                node = self.network.nodes[sender_id]
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
                    hops.append(RouteHop(
                        node_id=hop_node_id,
                        snr=float(hop_snr),
                        timestamp=datetime.now()
                    ))
                if hops:
                    route = MeshRoute(
                        destination_id=sender_id,
                        hops=hops,
                        discovered=datetime.now(),
                        last_used=datetime.now(),
                        is_preferred=True
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
                    if neighbor_snr and neighbor_node_id in self.network.nodes:
                        self.network.update_link_quality(neighbor_node_id, float(neighbor_snr), 0, 1)

    def _handle_decoded_text(self, text: str, sender_id: str, msg_id: str, decoded: Dict, topic_info: Dict):
        """Handle decoded text message."""
        sender_name = ""
        if sender_id in self.network.nodes:
            sender_name = self.network.nodes[sender_id].display_name

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
            timestamp=datetime.now(),
            hop_count=hop_count,
            snr=float(snr) if snr else 0.0,
            rssi=int(rssi) if rssi else 0,
            is_incoming=True
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
                    metadata={"keyword": keyword}
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)
                break

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Send a message via MQTT."""
        if not self._connected or not self._client:
            return False

        if not self.mqtt_config.node_id:
            print("Cannot send: no node_id configured for MQTT")
            return False

        try:
            # Build JSON message
            message = {
                "from": self.mqtt_config.node_id,
                "to": destination,
                "channel": channel,
                "type": "text",
                "payload": {
                    "text": text
                }
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
                timestamp=datetime.now(),
                is_incoming=False
            )
            self.network.add_message(out_msg)

            return True

        except Exception as e:
            print(f"MQTT send error: {e}")
            return False

    def get_nodes(self) -> List[Node]:
        """Get all known nodes."""
        return list(self.network.nodes.values())

    def get_messages(self, channel: Optional[int] = None, limit: int = 100) -> List[Message]:
        """Get messages."""
        messages = self.network.messages
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
        now = datetime.now()

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

        return {
            "status": status,
            "connected": self._connected,
            "broker": self.mqtt_config.broker,
            "uptime_seconds": int(uptime_seconds),
            "message_count": self._message_count,
            "messages_per_minute": round(msg_rate, 2),
            "last_message_ago_seconds": int(last_msg_ago) if last_msg_ago else None,
            "reconnect_count": self._reconnect_count
        }


class MQTTConnectionManager:
    """
    Manages MQTT connection with automatic reconnection.
    """

    def __init__(self, client: MQTTMeshtasticClient, reconnect_delay: int = 5):
        self.client = client
        self.reconnect_delay = reconnect_delay
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start connection manager."""
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop connection manager."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _monitor_loop(self):
        """Monitor connection and reconnect if needed."""
        while self._running:
            if not self.client.is_connected:
                print("MQTT disconnected, attempting reconnect...")
                self.client.connect()

            time.sleep(self.reconnect_delay)

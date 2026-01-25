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
    NodeRole, MessageType, AlertType
)
from .config import Config

# Try to import paho-mqtt
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


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


class MQTTMeshtasticClient:
    """
    MQTT client for Meshtastic mesh networks.
    Allows monitoring and participating in mesh without a radio.
    """

    def __init__(self, config: Config, mqtt_config: Optional[MQTTConfig] = None):
        if not MQTT_AVAILABLE:
            raise ImportError("paho-mqtt not installed. Run: pip install paho-mqtt")

        self.config = config
        self.mqtt_config = mqtt_config or MQTTConfig()

        # MQTT client
        self._client: Optional[mqtt.Client] = None
        self._connected = False

        # Network state
        self.network = MeshNetwork()

        # Callbacks
        self._callbacks: Dict[str, List[Callable]] = {
            "on_connect": [],
            "on_disconnect": [],
            "on_message": [],
            "on_node_update": [],
            "on_alert": [],
        }

        # Generate client ID if not set
        if not self.mqtt_config.client_id:
            self.mqtt_config.client_id = f"mesh-client-{uuid.uuid4().hex[:8]}"

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
                return True
            else:
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

        # Subscribe to various topics
        topics = [
            f"{root}/{channel}/#",  # All messages on channel
            f"{root}/+/+/json/#",   # JSON formatted messages
            f"{root}/2/json/#",     # JSON on channel 2
            f"{root}/2/e/#",        # Encrypted on channel 2
        ]

        for topic in topics:
            self._client.subscribe(topic)
            print(f"Subscribed to: {topic}")

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT message."""
        try:
            topic = msg.topic
            payload = msg.payload

            # Determine message type from topic
            if "/json/" in topic or topic.endswith("/json"):
                self._handle_json_message(topic, payload)
            elif "/e/" in topic:
                self._handle_encrypted_message(topic, payload)
            else:
                self._handle_protobuf_message(topic, payload)

        except Exception as e:
            print(f"Error handling MQTT message: {e}")

    def _handle_json_message(self, topic: str, payload: bytes):
        """Handle JSON formatted Meshtastic message."""
        try:
            data = json.loads(payload.decode('utf-8'))

            # Extract message info
            sender = data.get("from", 0)
            sender_id = f"!{sender:08x}" if isinstance(sender, int) else str(sender)
            msg_type = data.get("type", "")

            # Update node last seen
            if sender_id not in self.network.nodes:
                node = Node(
                    node_id=sender_id,
                    node_num=sender if isinstance(sender, int) else 0,
                    last_heard=datetime.now()
                )
                self.network.add_node(node)
                self._trigger_callbacks("on_node_update", sender_id, True)
            else:
                self.network.nodes[sender_id].last_heard = datetime.now()

            # Handle different message types
            if msg_type == "text" or "text" in data.get("payload", {}):
                self._handle_text_from_json(data, sender_id)
            elif msg_type == "position" or "position" in data.get("payload", {}):
                self._handle_position_from_json(data, sender_id)
            elif msg_type == "telemetry" or "telemetry" in data.get("payload", {}):
                self._handle_telemetry_from_json(data, sender_id)
            elif msg_type == "nodeinfo" or "user" in data.get("payload", {}):
                self._handle_nodeinfo_from_json(data, sender_id)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"JSON message error: {e}")

    def _handle_text_from_json(self, data: dict, sender_id: str):
        """Handle text message from JSON."""
        payload = data.get("payload", {})
        text = payload.get("text", "") if isinstance(payload, dict) else str(payload)

        if not text:
            return

        sender_name = ""
        if sender_id in self.network.nodes:
            sender_name = self.network.nodes[sender_id].display_name

        message = Message(
            id=str(uuid.uuid4()),
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_id=str(data.get("to", "")),
            channel=data.get("channel", 0),
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(),
            is_incoming=True
        )

        self.network.add_message(message)
        self._trigger_callbacks("on_message", message)

        # Check for emergency keywords
        self._check_emergency_keywords(message)

    def _handle_position_from_json(self, data: dict, sender_id: str):
        """Handle position update from JSON."""
        payload = data.get("payload", {})
        pos_data = payload.get("position", payload)

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            node.position = Position(
                latitude=pos_data.get("latitude", 0) or pos_data.get("latitudeI", 0) / 1e7,
                longitude=pos_data.get("longitude", 0) or pos_data.get("longitudeI", 0) / 1e7,
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

    def _handle_encrypted_message(self, topic: str, payload: bytes):
        """Handle encrypted Meshtastic message (limited processing)."""
        # Encrypted messages can't be fully decoded without the key
        # But we can still extract metadata from the topic
        try:
            parts = topic.split("/")
            # Topic format: msh/region/channel/e/nodeId
            if len(parts) >= 5:
                # Just log that we received something
                pass
        except Exception:
            pass

    def _handle_protobuf_message(self, topic: str, payload: bytes):
        """Handle protobuf Meshtastic message."""
        # Would need meshtastic protobuf definitions to fully decode
        # For now, just acknowledge receipt
        pass

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

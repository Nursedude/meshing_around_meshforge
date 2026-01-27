"""
Data models for Meshing-Around Clients.
Defines the core data structures used across TUI and Web clients.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
import json


class NodeRole(Enum):
    """Node role types in the mesh network."""
    CLIENT = "CLIENT"
    CLIENT_MUTE = "CLIENT_MUTE"
    ROUTER = "ROUTER"
    ROUTER_CLIENT = "ROUTER_CLIENT"
    REPEATER = "REPEATER"


class AlertType(Enum):
    """Types of alerts supported by the system."""
    EMERGENCY = "emergency"
    PROXIMITY = "proximity"
    ALTITUDE = "altitude"
    WEATHER = "weather"
    IPAWS = "ipaws"
    VOLCANO = "volcano"
    BATTERY = "battery"
    NOISY_NODE = "noisy_node"
    NEW_NODE = "new_node"
    SNR = "snr"
    DISCONNECT = "disconnect"
    CUSTOM = "custom"


class MessageType(Enum):
    """Types of messages in the mesh network."""
    TEXT = "text"
    POSITION = "position"
    TELEMETRY = "telemetry"
    NODEINFO = "nodeinfo"
    ROUTING = "routing"
    ADMIN = "admin"
    TRACEROUTE = "traceroute"
    WAYPOINT = "waypoint"


@dataclass
class Position:
    """Geographic position data."""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: int = 0
    time: Optional[datetime] = None
    precision_bits: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
            "time": self.time.isoformat() if self.time else None,
            "precision_bits": self.precision_bits
        }


@dataclass
class NodeTelemetry:
    """Telemetry data from a node."""
    battery_level: int = 0
    voltage: float = 0.0
    channel_utilization: float = 0.0
    air_util_tx: float = 0.0
    uptime_seconds: int = 0
    snr: float = 0.0
    rssi: int = 0
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "battery_level": self.battery_level,
            "voltage": self.voltage,
            "channel_utilization": self.channel_utilization,
            "air_util_tx": self.air_util_tx,
            "uptime_seconds": self.uptime_seconds,
            "snr": self.snr,
            "rssi": self.rssi,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
        }


@dataclass
class Node:
    """Represents a node in the mesh network."""
    node_id: str
    node_num: int
    short_name: str = ""
    long_name: str = ""
    hardware_model: str = "UNKNOWN"
    role: NodeRole = NodeRole.CLIENT
    position: Optional[Position] = None
    telemetry: Optional[NodeTelemetry] = None
    last_heard: Optional[datetime] = None
    is_favorite: bool = False
    is_admin: bool = False
    is_online: bool = True
    hop_count: int = 0

    def __post_init__(self):
        if self.position is None:
            self.position = Position()
        if self.telemetry is None:
            self.telemetry = NodeTelemetry()

    @property
    def display_name(self) -> str:
        """Return the best display name for the node."""
        if self.long_name:
            return self.long_name
        if self.short_name:
            return self.short_name
        node_suffix = self.node_id.lstrip("!")[-4:]
        return f"!{node_suffix}"

    @property
    def time_since_heard(self) -> str:
        """Return human-readable time since last heard."""
        if not self.last_heard:
            return "Never"
        delta = datetime.now() - self.last_heard
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return f"{delta.seconds}s ago"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_num": self.node_num,
            "short_name": self.short_name,
            "long_name": self.long_name,
            "hardware_model": self.hardware_model,
            "role": self.role.value,
            "position": self.position.to_dict() if self.position else None,
            "telemetry": self.telemetry.to_dict() if self.telemetry else None,
            "last_heard": self.last_heard.isoformat() if self.last_heard else None,
            "is_favorite": self.is_favorite,
            "is_admin": self.is_admin,
            "is_online": self.is_online,
            "hop_count": self.hop_count,
            "display_name": self.display_name,
            "time_since_heard": self.time_since_heard
        }


@dataclass
class Message:
    """Represents a message in the mesh network."""
    id: str
    sender_id: str
    sender_name: str = ""
    recipient_id: str = ""  # Empty for broadcast
    channel: int = 0
    text: str = ""
    message_type: MessageType = MessageType.TEXT
    timestamp: Optional[datetime] = None
    hop_count: int = 0
    snr: float = 0.0
    rssi: int = 0
    is_encrypted: bool = False
    is_incoming: bool = True
    ack_received: bool = False

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    @property
    def is_broadcast(self) -> bool:
        return not self.recipient_id or self.recipient_id == "^all"

    @property
    def time_formatted(self) -> str:
        if self.timestamp:
            return self.timestamp.strftime("%H:%M:%S")
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "recipient_id": self.recipient_id,
            "channel": self.channel,
            "text": self.text,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "hop_count": self.hop_count,
            "snr": self.snr,
            "rssi": self.rssi,
            "is_encrypted": self.is_encrypted,
            "is_incoming": self.is_incoming,
            "ack_received": self.ack_received,
            "is_broadcast": self.is_broadcast,
            "time_formatted": self.time_formatted
        }


@dataclass
class Alert:
    """Represents an alert in the system."""
    id: str
    alert_type: AlertType
    title: str
    message: str
    severity: int = 1  # 1=low, 2=medium, 3=high, 4=critical
    source_node: Optional[str] = None
    timestamp: Optional[datetime] = None
    acknowledged: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    @property
    def severity_label(self) -> str:
        labels = {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}
        return labels.get(self.severity, "Unknown")

    @property
    def severity_color(self) -> str:
        colors = {1: "blue", 2: "yellow", 3: "orange", 4: "red"}
        return colors.get(self.severity, "white")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "alert_type": self.alert_type.value,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "severity_label": self.severity_label,
            "source_node": self.source_node,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "acknowledged": self.acknowledged,
            "metadata": self.metadata
        }


@dataclass
class MeshNetwork:
    """Represents the overall mesh network state.

    Thread-safe: all mutating operations are protected by a lock.
    """
    nodes: Dict[str, Node] = field(default_factory=dict)
    messages: List[Message] = field(default_factory=list)
    alerts: List[Alert] = field(default_factory=list)
    my_node_id: str = ""
    connection_status: str = "disconnected"
    channel_count: int = 8

    def __post_init__(self):
        self._lock = threading.Lock()

    @property
    def online_nodes(self) -> List[Node]:
        with self._lock:
            return [n for n in self.nodes.values() if n.is_online]

    @property
    def favorite_nodes(self) -> List[Node]:
        with self._lock:
            return [n for n in self.nodes.values() if n.is_favorite]

    @property
    def unread_alerts(self) -> List[Alert]:
        with self._lock:
            return [a for a in self.alerts if not a.acknowledged]

    @property
    def total_messages(self) -> int:
        with self._lock:
            return len(self.messages)

    def get_node(self, node_id: str) -> Optional[Node]:
        with self._lock:
            return self.nodes.get(node_id)

    def add_node(self, node: Node) -> None:
        with self._lock:
            self.nodes[node.node_id] = node

    def add_message(self, message: Message, max_history: int = 1000) -> None:
        with self._lock:
            self.messages.append(message)
            if len(self.messages) > max_history:
                self.messages = self.messages[-max_history:]

    def add_alert(self, alert: Alert, max_history: int = 500) -> None:
        with self._lock:
            self.alerts.append(alert)
            if len(self.alerts) > max_history:
                self.alerts = self.alerts[-max_history:]

    def get_messages_for_channel(self, channel: int) -> List[Message]:
        with self._lock:
            return [m for m in self.messages if m.channel == channel]

    def get_messages_for_node(self, node_id: str) -> List[Message]:
        with self._lock:
            return [m for m in self.messages
                    if m.sender_id == node_id or m.recipient_id == node_id]

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
                "messages": [m.to_dict() for m in self.messages[-100:]],
                "alerts": [a.to_dict() for a in self.alerts[-50:]],
                "my_node_id": self.my_node_id,
                "connection_status": self.connection_status,
                "channel_count": self.channel_count,
                "online_node_count": len([n for n in self.nodes.values() if n.is_online]),
                "total_node_count": len(self.nodes),
                "unread_alert_count": len([a for a in self.alerts if not a.acknowledged])
            }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

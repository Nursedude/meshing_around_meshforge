"""
Data models for Meshing-Around Clients.
Defines the core data structures used across TUI and Web clients.
"""

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
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


class ChannelRole(Enum):
    """Role of a channel in the mesh."""
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    DISABLED = "DISABLED"


@dataclass
class Channel:
    """Represents a Meshtastic channel configuration."""
    index: int  # Channel index (0-7)
    name: str = ""  # Human-readable name
    role: ChannelRole = ChannelRole.DISABLED
    # Pre-shared key (PSK) - empty for default, "none" for unencrypted
    psk: str = ""
    # Uplink/downlink enabled for MQTT
    uplink_enabled: bool = False
    downlink_enabled: bool = False
    # Message statistics
    message_count: int = 0
    last_activity: Optional[datetime] = None

    @property
    def is_encrypted(self) -> bool:
        """Check if channel uses encryption."""
        return self.psk != "none" and self.psk != ""

    @property
    def display_name(self) -> str:
        """Get display name for channel."""
        if self.name:
            return self.name
        if self.index == 0:
            return "Primary"
        return f"Channel {self.index}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "display_name": self.display_name,
            "role": self.role.value,
            "is_encrypted": self.is_encrypted,
            "uplink_enabled": self.uplink_enabled,
            "downlink_enabled": self.downlink_enabled,
            "message_count": self.message_count,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None
        }


@dataclass
class LinkQuality:
    """Signal quality metrics for a link between nodes."""
    snr: float = 0.0  # Signal-to-noise ratio in dB
    rssi: int = 0  # Received signal strength indicator
    hop_count: int = 0  # Number of hops to reach this node
    last_seen: Optional[datetime] = None
    # Rolling average of SNR over recent packets
    snr_avg: float = 0.0
    # Number of packets used for averaging
    packet_count: int = 0
    # Packet loss estimation (0.0 to 1.0)
    packet_loss: float = 0.0

    def update(self, snr: float, rssi: int, hop_count: int = 0) -> None:
        """Update link quality with new measurement."""
        self.last_seen = datetime.now()
        self.rssi = rssi
        self.hop_count = hop_count
        self.packet_count += 1
        # Exponential moving average for SNR
        alpha = 0.3  # Weight for new values
        if self.packet_count == 1:
            self.snr_avg = snr
        else:
            self.snr_avg = alpha * snr + (1 - alpha) * self.snr_avg
        self.snr = snr

    @property
    def quality_percent(self) -> int:
        """Estimate link quality as percentage (0-100)."""
        # Based on typical Meshtastic SNR ranges (-20 to +10 dB)
        if self.snr_avg >= 10:
            return 100
        elif self.snr_avg <= -15:
            return 0
        else:
            # Linear interpolation
            return int(((self.snr_avg + 15) / 25) * 100)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snr": self.snr,
            "rssi": self.rssi,
            "hop_count": self.hop_count,
            "snr_avg": round(self.snr_avg, 2),
            "packet_count": self.packet_count,
            "packet_loss": round(self.packet_loss, 3),
            "quality_percent": self.quality_percent,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None
        }


@dataclass
class RouteHop:
    """Single hop in a mesh route."""
    node_id: str
    snr: float = 0.0
    timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "snr": self.snr,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }


@dataclass
class MeshRoute:
    """A route through the mesh network to a destination."""
    destination_id: str
    hops: List[RouteHop] = field(default_factory=list)
    discovered: Optional[datetime] = None
    last_used: Optional[datetime] = None
    # Is this the preferred route?
    is_preferred: bool = True

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    @property
    def avg_snr(self) -> float:
        if not self.hops:
            return 0.0
        return sum(h.snr for h in self.hops) / len(self.hops)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "destination_id": self.destination_id,
            "hops": [h.to_dict() for h in self.hops],
            "hop_count": self.hop_count,
            "avg_snr": round(self.avg_snr, 2),
            "discovered": self.discovered.isoformat() if self.discovered else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "is_preferred": self.is_preferred
        }


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
    # Link quality from our perspective to this node
    link_quality: Optional[LinkQuality] = None
    # Nodes that have reported hearing this node (neighbor relationships)
    heard_by: List[str] = field(default_factory=list)
    # Nodes that this node has reported hearing
    neighbors: List[str] = field(default_factory=list)
    # Known routes to reach this node
    routes: List[MeshRoute] = field(default_factory=list)
    # First seen timestamp
    first_seen: Optional[datetime] = None

    def __post_init__(self):
        if self.position is None:
            self.position = Position()
        if self.telemetry is None:
            self.telemetry = NodeTelemetry()
        if self.link_quality is None:
            self.link_quality = LinkQuality()
        if self.first_seen is None:
            self.first_seen = datetime.now()

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
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "is_favorite": self.is_favorite,
            "is_admin": self.is_admin,
            "is_online": self.is_online,
            "hop_count": self.hop_count,
            "display_name": self.display_name,
            "time_since_heard": self.time_since_heard,
            "link_quality": self.link_quality.to_dict() if self.link_quality else None,
            "heard_by": self.heard_by,
            "neighbors": self.neighbors,
            "routes": [r.to_dict() for r in self.routes] if self.routes else []
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
    # Channel configurations
    channels: Dict[int, Channel] = field(default_factory=dict)
    # Message deduplication: maps message_id -> timestamp
    _seen_messages: Dict[str, datetime] = field(default_factory=dict)
    # Known routes in the mesh
    routes: Dict[str, MeshRoute] = field(default_factory=dict)
    # Channel utilization history (for mesh health)
    channel_utilization_history: List[float] = field(default_factory=list)
    # Timestamp when network state was last updated
    last_update: Optional[datetime] = None

    def __post_init__(self):
        self._lock = threading.Lock()
        # Initialize default channels
        if not self.channels:
            for i in range(self.channel_count):
                role = ChannelRole.PRIMARY if i == 0 else ChannelRole.DISABLED
                self.channels[i] = Channel(index=i, role=role)

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
            # Keep message history bounded
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

    def get_channel(self, index: int) -> Optional[Channel]:
        """Get channel by index."""
        with self._lock:
            return self.channels.get(index)

    def set_channel(self, channel: Channel) -> None:
        """Set or update a channel configuration."""
        with self._lock:
            self.channels[channel.index] = channel

    def get_active_channels(self) -> List[Channel]:
        """Get all non-disabled channels."""
        with self._lock:
            return [c for c in self.channels.values() if c.role != ChannelRole.DISABLED]

    def update_channel_activity(self, channel_index: int) -> None:
        """Update channel activity timestamp and message count."""
        with self._lock:
            if channel_index in self.channels:
                self.channels[channel_index].message_count += 1
                self.channels[channel_index].last_activity = datetime.now()

    def get_messages_for_node(self, node_id: str) -> List[Message]:
        with self._lock:
            return [m for m in self.messages
                    if m.sender_id == node_id or m.recipient_id == node_id]

    def is_duplicate_message(self, message_id: str, window_seconds: int = 60) -> bool:
        """Check if message is a duplicate within the time window."""
        with self._lock:
            now = datetime.now()
            # Clean old entries
            cutoff = now.replace(second=now.second - window_seconds) if now.second >= window_seconds else now
            self._seen_messages = {
                mid: ts for mid, ts in self._seen_messages.items()
                if (now - ts).total_seconds() < window_seconds
            }
            # Check and add
            if message_id in self._seen_messages:
                return True
            self._seen_messages[message_id] = now
            return False

    def update_neighbor_relationship(self, reporter_id: str, heard_id: str) -> None:
        """Update neighbor relationships based on who heard whom."""
        with self._lock:
            # Reporter heard the heard_id node
            if reporter_id in self.nodes:
                if heard_id not in self.nodes[reporter_id].neighbors:
                    self.nodes[reporter_id].neighbors.append(heard_id)
            # heard_id was heard by reporter
            if heard_id in self.nodes:
                if reporter_id not in self.nodes[heard_id].heard_by:
                    self.nodes[heard_id].heard_by.append(reporter_id)

    def update_route(self, destination_id: str, route: MeshRoute) -> None:
        """Update or add a route to a destination."""
        with self._lock:
            self.routes[destination_id] = route
            if destination_id in self.nodes:
                # Update node's routes list
                existing = [r for r in self.nodes[destination_id].routes
                           if r.destination_id != destination_id]
                existing.append(route)
                self.nodes[destination_id].routes = existing[-5:]  # Keep last 5 routes

    def update_link_quality(self, node_id: str, snr: float, rssi: int, hop_count: int = 0) -> None:
        """Update link quality metrics for a node."""
        with self._lock:
            if node_id in self.nodes:
                self.nodes[node_id].link_quality.update(snr, rssi, hop_count)

    @property
    def mesh_health(self) -> Dict[str, Any]:
        """Calculate overall mesh health metrics."""
        with self._lock:
            if not self.nodes:
                return {"status": "unknown", "score": 0}

            online_count = len([n for n in self.nodes.values() if n.is_online])
            total_count = len(self.nodes)

            # Average SNR across all nodes with link quality data
            snr_values = [
                n.link_quality.snr_avg for n in self.nodes.values()
                if n.link_quality and n.link_quality.packet_count > 0
            ]
            avg_snr = sum(snr_values) / len(snr_values) if snr_values else 0

            # Average channel utilization
            util_values = [
                n.telemetry.channel_utilization for n in self.nodes.values()
                if n.telemetry and n.telemetry.channel_utilization > 0
            ]
            avg_utilization = sum(util_values) / len(util_values) if util_values else 0

            # Calculate health score (0-100)
            online_score = (online_count / total_count * 40) if total_count > 0 else 0
            snr_score = min(30, max(0, (avg_snr + 10) * 2))  # -10 to +5 dB -> 0 to 30
            util_score = max(0, 30 - (avg_utilization * 0.3))  # Lower utilization is better

            health_score = int(online_score + snr_score + util_score)

            if health_score >= 80:
                status = "excellent"
            elif health_score >= 60:
                status = "good"
            elif health_score >= 40:
                status = "fair"
            elif health_score >= 20:
                status = "poor"
            else:
                status = "critical"

            return {
                "status": status,
                "score": health_score,
                "online_nodes": online_count,
                "total_nodes": total_count,
                "avg_snr": round(avg_snr, 2),
                "avg_channel_utilization": round(avg_utilization, 2)
            }

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            # Calculate health inline to avoid lock recursion
            online_count = len([n for n in self.nodes.values() if n.is_online])
            total_count = len(self.nodes)

            return {
                "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
                "messages": [m.to_dict() for m in self.messages[-100:]],
                "alerts": [a.to_dict() for a in self.alerts[-50:]],
                "my_node_id": self.my_node_id,
                "connection_status": self.connection_status,
                "channel_count": self.channel_count,
                "channels": {k: v.to_dict() for k, v in self.channels.items()},
                "online_node_count": online_count,
                "total_node_count": total_count,
                "unread_alert_count": len([a for a in self.alerts if not a.acknowledged]),
                "routes": {k: v.to_dict() for k, v in self.routes.items()},
                "last_update": self.last_update.isoformat() if self.last_update else None
            }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MeshNetwork':
        """Create MeshNetwork from dictionary (restore state).

        Note: This restores essential state (nodes, channels) but not
        transient data (messages, alerts, seen_messages) which will be
        empty on restore.
        """
        network = cls()

        # Restore basic state
        network.my_node_id = data.get('my_node_id', '')
        network.connection_status = data.get('connection_status', 'disconnected')
        network.channel_count = data.get('channel_count', 0)

        # Restore last_update
        last_update = data.get('last_update')
        if last_update:
            try:
                network.last_update = datetime.fromisoformat(last_update)
            except (ValueError, TypeError):
                network.last_update = None

        # Restore nodes
        nodes_data = data.get('nodes', {})
        for node_id, node_dict in nodes_data.items():
            try:
                # Get role, handling both string and missing values
                role_str = node_dict.get('role', 'CLIENT')
                try:
                    role = NodeRole(role_str) if role_str else NodeRole.CLIENT
                except ValueError:
                    role = NodeRole.CLIENT

                node = Node(
                    node_id=node_dict.get('node_id', node_id),
                    node_num=node_dict.get('node_num', 0),
                    short_name=node_dict.get('short_name', ''),
                    long_name=node_dict.get('long_name', ''),
                    hardware_model=node_dict.get('hardware_model', node_dict.get('hardware', 'UNKNOWN')),
                    is_online=node_dict.get('is_online', False),
                    role=role
                )
                # Restore timestamps
                last_heard = node_dict.get('last_heard')
                if last_heard:
                    try:
                        node.last_heard = datetime.fromisoformat(last_heard)
                    except (ValueError, TypeError):
                        pass
                first_seen = node_dict.get('first_seen')
                if first_seen:
                    try:
                        node.first_seen = datetime.fromisoformat(first_seen)
                    except (ValueError, TypeError):
                        pass
                network.nodes[node_id] = node
            except (KeyError, ValueError, TypeError):
                continue  # Skip invalid node data

        # Restore channels
        channels_data = data.get('channels', {})
        for idx_str, ch_dict in channels_data.items():
            try:
                idx = int(idx_str)
                channel = Channel(
                    index=idx,
                    name=ch_dict.get('name', ''),
                    role=ChannelRole(ch_dict.get('role', 'DISABLED')),
                    uplink_enabled=ch_dict.get('uplink_enabled', False),
                    downlink_enabled=ch_dict.get('downlink_enabled', False),
                    message_count=ch_dict.get('message_count', 0)
                )
                last_activity = ch_dict.get('last_activity')
                if last_activity:
                    try:
                        channel.last_activity = datetime.fromisoformat(last_activity)
                    except (ValueError, TypeError):
                        pass
                network.channels[idx] = channel
            except (KeyError, ValueError, TypeError):
                continue  # Skip invalid channel data

        return network

    @classmethod
    def from_json(cls, json_str: str) -> 'MeshNetwork':
        """Create MeshNetwork from JSON string."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError:
            return cls()  # Return empty network on invalid JSON

    def save_to_file(self, path: Union[str, Path]) -> bool:
        """Save network state to file.

        Args:
            path: Path to save state file

        Returns:
            True if saved successfully, False otherwise
        """
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                f.write(self.to_json())
            # Set restrictive permissions
            os.chmod(path, 0o600)
            return True
        except OSError:
            return False

    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> 'MeshNetwork':
        """Load network state from file.

        Args:
            path: Path to state file

        Returns:
            MeshNetwork instance (empty if file doesn't exist or is invalid)
        """
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            with open(path, 'r') as f:
                return cls.from_json(f.read())
        except (OSError, json.JSONDecodeError):
            return cls()

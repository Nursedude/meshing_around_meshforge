"""
Data models for Meshing-Around Clients.
Defines the core data structures used across TUI and Web clients.
"""

import json
import os
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Union

# --- Mesh congestion thresholds (from Meshtastic ROUTER_LATE documentation) ---
# See: https://meshtastic.org/blog/demystifying-router-late/
CHUTIL_WARNING_THRESHOLD = 25.0  # Channel utilization warning at 25%
CHUTIL_CRITICAL_THRESHOLD = 40.0  # Channel utilization critical at 40%
AIRUTILTX_WARNING_THRESHOLD = 7.0  # TX airtime warning at 7-8%
AIRUTILTX_CRITICAL_THRESHOLD = 10.0  # TX airtime critical at 10%

# --- Robustness limits ---
STALE_NODE_HOURS = 72  # Nodes not seen in 72h considered stale
MAX_NODES = 10000  # Maximum tracked nodes before pruning
MAX_ROUTES = 5000  # Maximum tracked routes before pruning
MAX_CHANNEL_UTIL_HISTORY = 1000  # Maximum channel utilization history entries
MAX_NEIGHBORS_PER_NODE = 200  # Maximum neighbor/heard_by entries per node
VALID_LAT_RANGE = (-90.0, 90.0)
VALID_LON_RANGE = (-180.0, 180.0)
VALID_SNR_RANGE = (-50.0, 50.0)  # dB
VALID_RSSI_RANGE = (-200, 0)  # dBm

# UTC-aware minimum datetime for sort sentinels
DATETIME_MIN_UTC = datetime.min.replace(tzinfo=timezone.utc)

# --- Message/alert history bounds for deque ---
MESSAGE_HISTORY_MAX = 1000
ALERT_HISTORY_MAX = 500


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
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
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
        self.last_seen = datetime.now(timezone.utc)
        self.rssi = rssi
        self.hop_count = hop_count
        self.packet_count += 1
        # Clamp SNR to valid range to prevent quality_percent going out of bounds
        snr = max(VALID_SNR_RANGE[0], min(VALID_SNR_RANGE[1], snr))
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
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
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
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
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
            "is_preferred": self.is_preferred,
        }


@dataclass
class Position:
    """Geographic position data."""

    latitude: float = 0.0
    longitude: float = 0.0
    altitude: int = 0
    time: Optional[datetime] = None
    precision_bits: int = 0

    def is_valid(self) -> bool:
        """Check if position has valid coordinates.

        Note: (0.0, 0.0) is treated as invalid because Meshtastic uses it
        as the default/unset position marker. This is standard Meshtastic
        convention, not a geographic exclusion of Null Island.
        """
        return (
            (self.latitude != 0.0 or self.longitude != 0.0)
            and -90 <= self.latitude <= 90
            and -180 <= self.longitude <= 180
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
            "time": self.time.isoformat() if self.time else None,
            "precision_bits": self.precision_bits,
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
    # Environment metrics (BME280/BME680/BMP280 sensors)
    temperature: Optional[float] = None  # Celsius
    humidity: Optional[float] = None  # 0-100%
    pressure: Optional[float] = None  # hPa (barometric)
    gas_resistance: Optional[float] = None  # Ohms (BME680 VOC)

    @property
    def has_environment_data(self) -> bool:
        """Check if any environment sensor data is present."""
        return any([self.temperature, self.humidity, self.pressure, self.gas_resistance])

    @property
    def channel_utilization_status(self) -> str:
        """Classify channel utilization per Meshtastic ROUTER_LATE thresholds.

        See: https://meshtastic.org/blog/demystifying-router-late/
        """
        if self.channel_utilization >= 40.0:
            return "critical"
        elif self.channel_utilization >= 25.0:
            return "warning"
        return "normal"

    @property
    def air_util_tx_status(self) -> str:
        """Classify TX airtime per Meshtastic congestion thresholds."""
        if self.air_util_tx >= 10.0:
            return "critical"
        elif self.air_util_tx >= 7.0:
            return "warning"
        return "normal"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "battery_level": self.battery_level,
            "voltage": self.voltage,
            "channel_utilization": self.channel_utilization,
            "air_util_tx": self.air_util_tx,
            "uptime_seconds": self.uptime_seconds,
            "snr": self.snr,
            "rssi": self.rssi,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "channel_utilization_status": self.channel_utilization_status,
            "air_util_tx_status": self.air_util_tx_status,
        }
        # Include environment data only when present
        if self.has_environment_data:
            result["environment"] = {
                k: v
                for k, v in {
                    "temperature": self.temperature,
                    "humidity": self.humidity,
                    "pressure": self.pressure,
                    "gas_resistance": self.gas_resistance,
                }.items()
                if v is not None
            }
        return result


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
            self.first_seen = datetime.now(timezone.utc)

    @property
    def display_name(self) -> str:
        """Return the best display name for the node."""
        if self.long_name:
            return self.long_name
        if self.short_name:
            return self.short_name
        node_suffix = (self.node_id.lstrip("!") or "unknown")[-4:]
        return f"!{node_suffix}"

    @property
    def time_since_heard(self) -> str:
        """Return human-readable time since last heard."""
        if not self.last_heard:
            return "Never"
        delta = datetime.now(timezone.utc) - self.last_heard
        seconds = delta.total_seconds()
        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds / 3600)}h ago"
        else:
            return f"{int(seconds / 86400)}d ago"

    def is_recently_heard(self, threshold_minutes: int = 15) -> bool:
        """Check if node was heard within threshold (default 15 min).

        Matches meshforge's MQTTNode.is_online() semantics.
        """
        if not self.last_heard:
            return False
        delta = datetime.now(timezone.utc) - self.last_heard
        return delta.total_seconds() < threshold_minutes * 60

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
            "routes": [r.to_dict() for r in self.routes] if self.routes else [],
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
            self.timestamp = datetime.now(timezone.utc)

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
            "time_formatted": self.time_formatted,
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
            self.timestamp = datetime.now(timezone.utc)

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
            "metadata": self.metadata,
        }


@dataclass
class MeshNetwork:
    """Represents the overall mesh network state.

    Thread-safe: all mutating operations are protected by a lock.
    """

    nodes: Dict[str, Node] = field(default_factory=dict)
    messages: Deque[Message] = field(default_factory=lambda: deque(maxlen=MESSAGE_HISTORY_MAX))
    alerts: Deque[Alert] = field(default_factory=lambda: deque(maxlen=ALERT_HISTORY_MAX))
    my_node_id: str = ""
    connection_status: str = "disconnected"
    channel_count: int = 8
    # Channel configurations
    channels: Dict[int, Channel] = field(default_factory=dict)
    # Message deduplication: maps message_id -> timestamp (ordered for O(1) pruning)
    _seen_messages: OrderedDict = field(default_factory=OrderedDict)
    # Known routes in the mesh
    routes: Dict[str, MeshRoute] = field(default_factory=dict)
    # Channel utilization history (for mesh health) — bounded to prevent unbounded growth
    channel_utilization_history: Deque[float] = field(default_factory=lambda: deque(maxlen=MAX_CHANNEL_UTIL_HISTORY))
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

    def add_message(self, message: Message) -> None:
        with self._lock:
            self.messages.append(message)
            # deque(maxlen=MESSAGE_HISTORY_MAX) handles bounding automatically
            # Update channel activity tracking
            ch = self.channels.get(message.channel)
            if ch is not None:
                ch.message_count += 1
                ch.last_activity = datetime.now(timezone.utc)

    def add_alert(self, alert: Alert) -> None:
        with self._lock:
            self.alerts.append(alert)
            # deque(maxlen=ALERT_HISTORY_MAX) handles bounding automatically

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

    def get_messages_for_node(self, node_id: str) -> List[Message]:
        with self._lock:
            return [m for m in self.messages if m.sender_id == node_id or m.recipient_id == node_id]

    # Maximum seen messages to prevent unbounded memory growth
    _MAX_SEEN_MESSAGES = 10000

    def is_duplicate_message(self, message_id: str, window_seconds: int = 60) -> bool:
        """Check if message is a duplicate within the time window.

        Uses OrderedDict for O(1) oldest-entry removal instead of
        sorting the entire dict when the size limit is exceeded.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(seconds=window_seconds)
            # Evict expired entries from the front (oldest first)
            while self._seen_messages:
                oldest_key = next(iter(self._seen_messages))
                if self._seen_messages[oldest_key] <= cutoff:
                    del self._seen_messages[oldest_key]
                else:
                    break
            # Enforce hard size limit by popping oldest entries — O(1) per pop
            while len(self._seen_messages) > self._MAX_SEEN_MESSAGES:
                self._seen_messages.popitem(last=False)
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
                    # Bound neighbors list
                    if len(self.nodes[reporter_id].neighbors) > MAX_NEIGHBORS_PER_NODE:
                        self.nodes[reporter_id].neighbors = self.nodes[reporter_id].neighbors[-MAX_NEIGHBORS_PER_NODE:]
            # heard_id was heard by reporter
            if heard_id in self.nodes:
                if reporter_id not in self.nodes[heard_id].heard_by:
                    self.nodes[heard_id].heard_by.append(reporter_id)
                    if len(self.nodes[heard_id].heard_by) > MAX_NEIGHBORS_PER_NODE:
                        self.nodes[heard_id].heard_by = self.nodes[heard_id].heard_by[-MAX_NEIGHBORS_PER_NODE:]

    def update_route(self, destination_id: str, route: MeshRoute) -> None:
        """Update or add a route to a destination."""
        with self._lock:
            self.routes[destination_id] = route
            # Prune routes if over limit — evict oldest discovered routes
            if len(self.routes) > MAX_ROUTES:
                oldest_key = min(
                    self.routes,
                    key=lambda k: self.routes[k].discovered or DATETIME_MIN_UTC,
                )
                del self.routes[oldest_key]
            if destination_id in self.nodes:
                # Update node's routes list
                existing = [r for r in self.nodes[destination_id].routes if r.destination_id != destination_id]
                existing.append(route)
                self.nodes[destination_id].routes = existing[-5:]  # Keep last 5 routes

    def update_link_quality(self, node_id: str, snr: float, rssi: int, hop_count: int = 0) -> None:
        """Update link quality metrics for a node."""
        with self._lock:
            if node_id in self.nodes:
                self.nodes[node_id].link_quality.update(snr, rssi, hop_count)

    def cleanup_stale_nodes(self, stale_hours: int = STALE_NODE_HOURS, max_nodes: int = MAX_NODES) -> int:
        """Remove nodes not seen within stale_hours, or prune to max_nodes.

        Returns number of nodes removed.
        """
        removed = 0
        now = datetime.now(timezone.utc)
        with self._lock:
            stale_ids = [
                nid
                for nid, node in self.nodes.items()
                if node.last_heard and (now - node.last_heard).total_seconds() > stale_hours * 3600
            ]
            for nid in stale_ids:
                del self.nodes[nid]
                removed += 1

            # If still over limit, prune oldest
            if len(self.nodes) > max_nodes:
                sorted_nodes = sorted(self.nodes.items(), key=lambda x: x[1].last_heard or DATETIME_MIN_UTC)
                to_remove = len(self.nodes) - max_nodes
                for nid, _ in sorted_nodes[:to_remove]:
                    del self.nodes[nid]
                    removed += 1

        return removed

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
                n.link_quality.snr_avg
                for n in self.nodes.values()
                if n.link_quality and n.link_quality.packet_count > 0
            ]
            avg_snr = sum(snr_values) / len(snr_values) if snr_values else 0

            # Average channel utilization
            util_values = [
                n.telemetry.channel_utilization
                for n in self.nodes.values()
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
                "avg_channel_utilization": round(avg_utilization, 2),
            }

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            # Calculate health inline to avoid lock recursion
            online_count = len([n for n in self.nodes.values() if n.is_online])
            total_count = len(self.nodes)

            return {
                "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
                "messages": [m.to_dict() for m in list(self.messages)[-100:]],
                "alerts": [a.to_dict() for a in list(self.alerts)[-50:]],
                "my_node_id": self.my_node_id,
                "connection_status": self.connection_status,
                "channel_count": self.channel_count,
                "channels": {k: v.to_dict() for k, v in self.channels.items()},
                "online_node_count": online_count,
                "total_node_count": total_count,
                "unread_alert_count": len([a for a in self.alerts if not a.acknowledged]),
                "routes": {k: v.to_dict() for k, v in self.routes.items()},
                "last_update": self.last_update.isoformat() if self.last_update else None,
            }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeshNetwork":
        """Create MeshNetwork from dictionary (restore state).

        Restores nodes, channels, messages, and alerts from persisted data.
        Messages and alerts are restored for crash recovery so outgoing
        messages and alert history survive restarts.
        """
        network = cls()

        # Restore basic state
        network.my_node_id = data.get("my_node_id", "")
        network.connection_status = data.get("connection_status", "disconnected")
        network.channel_count = data.get("channel_count", 0)

        # Restore last_update
        last_update = data.get("last_update")
        if last_update:
            try:
                dt = datetime.fromisoformat(last_update)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                network.last_update = dt
            except (ValueError, TypeError):
                network.last_update = None

        # Restore nodes
        nodes_data = data.get("nodes", {})
        for node_id, node_dict in nodes_data.items():
            try:
                # Get role, handling both string and missing values
                role_str = node_dict.get("role", "CLIENT")
                try:
                    role = NodeRole(role_str) if role_str else NodeRole.CLIENT
                except ValueError:
                    role = NodeRole.CLIENT

                node = Node(
                    node_id=node_dict.get("node_id", node_id),
                    node_num=node_dict.get("node_num", 0),
                    short_name=node_dict.get("short_name", ""),
                    long_name=node_dict.get("long_name", ""),
                    hardware_model=node_dict.get("hardware_model", node_dict.get("hardware", "UNKNOWN")),
                    is_online=node_dict.get("is_online", False),
                    role=role,
                )
                # Restore timestamps
                last_heard = node_dict.get("last_heard")
                if last_heard:
                    try:
                        dt = datetime.fromisoformat(last_heard)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        node.last_heard = dt
                    except (ValueError, TypeError):
                        pass
                first_seen = node_dict.get("first_seen")
                if first_seen:
                    try:
                        dt = datetime.fromisoformat(first_seen)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        node.first_seen = dt
                    except (ValueError, TypeError):
                        pass
                network.nodes[node_id] = node
            except (KeyError, ValueError, TypeError):
                continue  # Skip invalid node data

        # Restore channels
        channels_data = data.get("channels", {})
        for idx_str, ch_dict in channels_data.items():
            try:
                idx = int(idx_str)
                channel = Channel(
                    index=idx,
                    name=ch_dict.get("name", ""),
                    role=ChannelRole(ch_dict.get("role", "DISABLED")),
                    uplink_enabled=ch_dict.get("uplink_enabled", False),
                    downlink_enabled=ch_dict.get("downlink_enabled", False),
                    message_count=ch_dict.get("message_count", 0),
                )
                last_activity = ch_dict.get("last_activity")
                if last_activity:
                    try:
                        dt = datetime.fromisoformat(last_activity)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        channel.last_activity = dt
                    except (ValueError, TypeError):
                        pass
                network.channels[idx] = channel
            except (KeyError, ValueError, TypeError):
                continue  # Skip invalid channel data

        # Restore messages (crash recovery for outgoing messages)
        messages_data = data.get("messages", [])
        for msg_dict in messages_data:
            try:
                # Parse message type
                msg_type_str = msg_dict.get("message_type", "text")
                try:
                    msg_type = MessageType(msg_type_str)
                except ValueError:
                    msg_type = MessageType.TEXT

                msg = Message(
                    id=msg_dict.get("id", ""),
                    sender_id=msg_dict.get("sender_id", ""),
                    sender_name=msg_dict.get("sender_name", ""),
                    recipient_id=msg_dict.get("recipient_id", ""),
                    channel=msg_dict.get("channel", 0),
                    text=msg_dict.get("text", ""),
                    message_type=msg_type,
                    hop_count=msg_dict.get("hop_count", 0),
                    snr=msg_dict.get("snr", 0.0),
                    rssi=msg_dict.get("rssi", 0),
                    is_encrypted=msg_dict.get("is_encrypted", False),
                    is_incoming=msg_dict.get("is_incoming", True),
                    ack_received=msg_dict.get("ack_received", False),
                )
                # Restore timestamp
                ts = msg_dict.get("timestamp")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        msg.timestamp = dt
                    except (ValueError, TypeError):
                        pass
                network.messages.append(msg)
            except (KeyError, ValueError, TypeError):
                continue  # Skip invalid message data

        # Restore alerts (crash recovery for alert history)
        alerts_data = data.get("alerts", [])
        for alert_dict in alerts_data:
            try:
                alert_type_str = alert_dict.get("alert_type", "custom")
                try:
                    alert_type = AlertType(alert_type_str)
                except ValueError:
                    alert_type = AlertType.CUSTOM

                alert = Alert(
                    id=alert_dict.get("id", ""),
                    alert_type=alert_type,
                    title=alert_dict.get("title", ""),
                    message=alert_dict.get("message", ""),
                    severity=alert_dict.get("severity", 1),
                    source_node=alert_dict.get("source_node"),
                    acknowledged=alert_dict.get("acknowledged", False),
                    metadata=alert_dict.get("metadata", {}),
                )
                # Restore timestamp
                ts = alert_dict.get("timestamp")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        alert.timestamp = dt
                    except (ValueError, TypeError):
                        pass
                network.alerts.append(alert)
            except (KeyError, ValueError, TypeError):
                continue  # Skip invalid alert data

        return network

    @classmethod
    def from_json(cls, json_str: str) -> "MeshNetwork":
        """Create MeshNetwork from JSON string."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError:
            return cls()  # Return empty network on invalid JSON

    def save_to_file(self, path: Union[str, Path]) -> bool:
        """Save network state to file atomically.

        Uses temp file + rename to prevent corruption on crash.
        From meshforge's atomic write pattern.

        Args:
            path: Path to save state file

        Returns:
            True if saved successfully, False otherwise
        """
        import tempfile

        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to temp file first, then atomic rename
            fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".meshforge_")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(self.to_json())
                # Set restrictive permissions before moving into place
                os.chmod(tmp_path, 0o600)
                # Atomic rename (on same filesystem)
                os.replace(tmp_path, str(path))
                return True
            except OSError:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                return False
        except OSError:
            return False

    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> "MeshNetwork":
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
            with open(path, "r") as f:
                return cls.from_json(f.read())
        except (OSError, json.JSONDecodeError):
            return cls()

"""
Alert detection system for Meshing-Around Clients.
Provides detection logic for various alert types including:
- Disconnect timeout alerts
- Noisy node detection
- Proximity alerts (geofencing)
- SNR alerts
"""

import math
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from .config import Config
from .models import Alert, AlertType, Message, Node, Position


@dataclass
class ProximityZone:
    """Defines a geographic zone for proximity alerts."""

    name: str
    latitude: float
    longitude: float
    radius_meters: float
    alert_on_enter: bool = True
    alert_on_exit: bool = False


@dataclass
class AlertDetectorConfig:
    """Configuration for alert detection."""

    # Disconnect detection
    disconnect_enabled: bool = True
    disconnect_timeout_seconds: int = 600  # 10 minutes

    # Noisy node detection
    noisy_node_enabled: bool = True
    noisy_node_threshold: int = 20  # messages per time period
    noisy_node_period_seconds: int = 60  # 1 minute window

    # Proximity detection
    proximity_enabled: bool = False
    proximity_zones: List[ProximityZone] = field(default_factory=list)

    # SNR detection
    snr_enabled: bool = False
    snr_threshold: float = -10.0  # Alert if SNR drops below this


class AlertDetector:
    """
    Monitors mesh network state and generates alerts based on configurable rules.

    Thread-safe implementation for use with async/multi-threaded connections.
    """

    def __init__(self, config: Config, detector_config: Optional[AlertDetectorConfig] = None):
        self.config = config
        self.detector_config = detector_config or AlertDetectorConfig()

        self._lock = threading.Lock()

        # Tracking state
        self._node_last_seen: Dict[str, datetime] = {}
        self._node_in_zone: Dict[str, Dict[str, bool]] = defaultdict(dict)  # node_id -> zone_name -> in_zone
        self._message_counts: Dict[str, List[datetime]] = defaultdict(list)  # node_id -> [timestamps]
        self._alerted_disconnects: set = set()  # Nodes we've already alerted for disconnect
        self._alerted_noisy: Dict[str, datetime] = {}  # node_id -> last alert time
        self._alerted_snr: Dict[str, datetime] = {}  # node_id -> last SNR alert time
        self._snr_cooldown_seconds: int = 300  # 5 minute cooldown per node for SNR alerts

        # Callbacks
        self._alert_callbacks: List[Callable[[Alert], None]] = []

    def register_alert_callback(self, callback: Callable[[Alert], None]) -> None:
        """Register a callback to be called when alerts are generated."""
        with self._lock:
            self._alert_callbacks.append(callback)

    def _emit_alert(self, alert: Alert) -> None:
        """Emit an alert to all registered callbacks."""
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except (ValueError, TypeError, AttributeError, KeyError, RuntimeError):
                # ValueError: Invalid alert data in callback
                # TypeError: Type mismatch in callback
                # AttributeError: Missing attributes on callback objects
                # KeyError: Missing expected keys
                # RuntimeError: General runtime issues
                # Don't let callback errors break detection
                pass

    # ==================== Haversine Distance ====================

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate the great-circle distance between two points on Earth.

        Args:
            lat1, lon1: First point coordinates in decimal degrees
            lat2, lon2: Second point coordinates in decimal degrees

        Returns:
            Distance in meters
        """
        R = 6371000  # Earth's radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    # ==================== Node Tracking ====================

    def update_node_seen(self, node_id: str, timestamp: Optional[datetime] = None) -> None:
        """Update the last seen time for a node."""
        with self._lock:
            self._node_last_seen[node_id] = timestamp or datetime.now(timezone.utc)
            # Clear disconnect alert flag since node is back
            self._alerted_disconnects.discard(node_id)

    def record_message(self, node_id: str, timestamp: Optional[datetime] = None) -> Optional[Alert]:
        """
        Record a message from a node and check for noisy node alerts.

        Returns an Alert if the node is being noisy, None otherwise.
        """
        if not self.detector_config.noisy_node_enabled:
            return None

        ts = timestamp or datetime.now(timezone.utc)

        with self._lock:
            # Update last seen
            self._node_last_seen[node_id] = ts
            self._alerted_disconnects.discard(node_id)

            # Add to message count
            self._message_counts[node_id].append(ts)

            # Clean old entries outside the time window
            cutoff = ts - timedelta(seconds=self.detector_config.noisy_node_period_seconds)
            self._message_counts[node_id] = [t for t in self._message_counts[node_id] if t > cutoff]

            # Check threshold
            count = len(self._message_counts[node_id])
            if count >= self.detector_config.noisy_node_threshold:
                # Check cooldown (don't alert again within the period)
                last_alert = self._alerted_noisy.get(node_id)
                if last_alert and (ts - last_alert).total_seconds() < self.detector_config.noisy_node_period_seconds:
                    return None

                self._alerted_noisy[node_id] = ts

                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.NOISY_NODE,
                    title="Noisy Node Detected",
                    message=f"Node {node_id[-6:]} sent {count} messages in "
                    f"{self.detector_config.noisy_node_period_seconds}s",
                    severity=2,
                    source_node=node_id,
                    metadata={"message_count": count, "period_seconds": self.detector_config.noisy_node_period_seconds},
                )
                self._emit_alert(alert)
                return alert

        return None

    # ==================== Disconnect Detection ====================

    def check_disconnects(self) -> List[Alert]:
        """
        Check for nodes that haven't been seen within the timeout period.

        Should be called periodically (e.g., every 30 seconds).

        Returns a list of disconnect alerts for newly-disconnected nodes.
        """
        if not self.detector_config.disconnect_enabled:
            return []

        alerts = []
        now = datetime.now(timezone.utc)
        timeout = timedelta(seconds=self.detector_config.disconnect_timeout_seconds)

        with self._lock:
            for node_id, last_seen in list(self._node_last_seen.items()):
                if node_id in self._alerted_disconnects:
                    continue

                if now - last_seen > timeout:
                    self._alerted_disconnects.add(node_id)

                    minutes = int((now - last_seen).total_seconds() / 60)
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.DISCONNECT,
                        title="Node Disconnected",
                        message=f"Node {node_id[-6:]} not seen for {minutes} minutes",
                        severity=2,
                        source_node=node_id,
                        metadata={
                            "last_seen": last_seen.isoformat(),
                            "timeout_seconds": self.detector_config.disconnect_timeout_seconds,
                        },
                    )
                    alerts.append(alert)
                    self._emit_alert(alert)

        return alerts

    # ==================== Proximity Detection ====================

    def add_proximity_zone(self, zone: ProximityZone) -> None:
        """Add a proximity monitoring zone."""
        with self._lock:
            self.detector_config.proximity_zones.append(zone)

    def check_proximity(self, node_id: str, position: Position) -> List[Alert]:
        """
        Check if a node's position triggers any proximity alerts.

        Args:
            node_id: The node identifier
            position: The node's current position

        Returns:
            List of proximity alerts (enter/exit zones)
        """
        if not self.detector_config.proximity_enabled:
            return []

        if position.latitude == 0 and position.longitude == 0:
            return []  # Invalid position

        alerts = []

        with self._lock:
            for zone in self.detector_config.proximity_zones:
                distance = self.haversine_distance(position.latitude, position.longitude, zone.latitude, zone.longitude)

                in_zone = distance <= zone.radius_meters
                was_in_zone = self._node_in_zone[node_id].get(zone.name, False)

                # Update state
                self._node_in_zone[node_id][zone.name] = in_zone

                # Check for zone transitions
                if in_zone and not was_in_zone and zone.alert_on_enter:
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.PROXIMITY,
                        title=f"Entered Zone: {zone.name}",
                        message=f"Node {node_id[-6:]} entered {zone.name} " f"({distance:.0f}m from center)",
                        severity=2,
                        source_node=node_id,
                        metadata={"zone_name": zone.name, "distance_meters": distance, "event": "enter"},
                    )
                    alerts.append(alert)
                    self._emit_alert(alert)

                elif not in_zone and was_in_zone and zone.alert_on_exit:
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.PROXIMITY,
                        title=f"Exited Zone: {zone.name}",
                        message=f"Node {node_id[-6:]} left {zone.name}",
                        severity=1,
                        source_node=node_id,
                        metadata={"zone_name": zone.name, "distance_meters": distance, "event": "exit"},
                    )
                    alerts.append(alert)
                    self._emit_alert(alert)

        return alerts

    # ==================== SNR Detection ====================

    def check_snr(self, node_id: str, snr: float) -> Optional[Alert]:
        """
        Check if SNR is below threshold.

        Uses per-node cooldown to prevent alert fatigue from repeated
        low-SNR readings from the same node.

        Args:
            node_id: The node identifier
            snr: Signal-to-noise ratio in dB

        Returns:
            Alert if SNR is below threshold and not in cooldown, None otherwise
        """
        if not self.detector_config.snr_enabled:
            return None

        if snr < self.detector_config.snr_threshold:
            with self._lock:
                now = datetime.now(timezone.utc)
                last_alert = self._alerted_snr.get(node_id)
                if last_alert and (now - last_alert).total_seconds() < self._snr_cooldown_seconds:
                    return None  # Still in cooldown — suppress

                self._alerted_snr[node_id] = now

            alert = Alert(
                id=str(uuid.uuid4()),
                alert_type=AlertType.SNR,
                title="Low SNR Detected",
                message=f"Node {node_id[-6:]} has low SNR: {snr:.1f}dB",
                severity=1,
                source_node=node_id,
                metadata={"snr": snr, "threshold": self.detector_config.snr_threshold},
            )
            self._emit_alert(alert)
            return alert

        return None

    # ==================== Batch Processing ====================

    def process_node_update(self, node: Node) -> List[Alert]:
        """
        Process a node update and check for all applicable alerts.

        Convenience method that checks proximity and SNR.

        Args:
            node: The updated node

        Returns:
            List of any generated alerts
        """
        alerts = []

        # Update tracking
        self.update_node_seen(node.node_id, node.last_heard)

        # Check proximity if position available
        if node.position and (node.position.latitude != 0 or node.position.longitude != 0):
            alerts.extend(self.check_proximity(node.node_id, node.position))

        # Check SNR if telemetry available
        if node.telemetry and node.telemetry.snr != 0:
            snr_alert = self.check_snr(node.node_id, node.telemetry.snr)
            if snr_alert:
                alerts.append(snr_alert)

        return alerts

    def process_message(self, message: Message) -> List[Alert]:
        """
        Process a message and check for noisy node alerts.

        Args:
            message: The received message

        Returns:
            List of any generated alerts
        """
        alerts = []

        noisy_alert = self.record_message(message.sender_id, message.timestamp)
        if noisy_alert:
            alerts.append(noisy_alert)

        return alerts

    # ==================== State Management ====================

    def get_tracked_nodes(self) -> Dict[str, datetime]:
        """Get all tracked nodes and their last seen times."""
        with self._lock:
            return dict(self._node_last_seen)

    def clear_state(self) -> None:
        """Clear all tracking state."""
        with self._lock:
            self._node_last_seen.clear()
            self._node_in_zone.clear()
            self._message_counts.clear()
            self._alerted_disconnects.clear()
            self._alerted_noisy.clear()
            self._alerted_snr.clear()

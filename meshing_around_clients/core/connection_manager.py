"""
Unified Connection Manager for Meshing-Around Clients.

Supports multiple connection types with automatic fallback:
- Serial (direct USB connection)
- TCP (remote device)
- MQTT (broker-based, no radio)
- BLE (Bluetooth)
- Demo (simulated)

Includes connection cooldown and ConnectionBusy handling
(patterns from meshforge's meshtasticd connection manager).
"""

import logging
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .models import Alert, MeshNetwork, Message, Node

logger = logging.getLogger(__name__)

# Cooldown between connections (devices/brokers need time to cleanup)
CONNECTION_COOLDOWN = 1.0  # seconds


class ConnectionType(Enum):
    """Available connection types."""

    SERIAL = "serial"
    TCP = "tcp"
    MQTT = "mqtt"
    BLE = "ble"
    DEMO = "demo"
    AUTO = "auto"


class ConnectionBusy(Exception):
    """Raised when connection is busy and non-blocking mode requested."""

    pass


@dataclass
class ConnectionStatus:
    """Current connection status."""

    connected: bool = False
    connection_type: ConnectionType = ConnectionType.DEMO
    device_info: str = ""
    error_message: str = ""
    last_connected: Optional[datetime] = None
    last_disconnected: Optional[datetime] = None
    reconnect_attempts: int = 0


class ConnectionManager:
    """
    Unified connection manager for all Meshtastic connection types.

    Provides:
    - Automatic connection type detection
    - Fallback between connection types
    - Automatic reconnection
    - Unified API for all connection types
    - Multi-interface support (uses first enabled interface by default)
    """

    def __init__(self, config: Config, interface_index: int = 0):
        """
        Initialize connection manager.

        Args:
            config: Configuration object
            interface_index: Which interface to use (0-based index).
                           Ignored if config only has one interface.
        """
        self.config = config
        self._interface_index = interface_index
        self._api: Optional[Any] = None
        self._status = ConnectionStatus()
        self._callbacks: Dict[str, List[Callable]] = {
            "on_connect": [],
            "on_disconnect": [],
            "on_message": [],
            "on_node_update": [],
            "on_alert": [],
            "on_status_change": [],
        }

        # Reconnection settings
        self._auto_reconnect = True
        self._reconnect_delay = 5
        self._max_reconnect_attempts = 10
        self._reconnect_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_close_time: float = 0.0  # For connection cooldown

    @property
    def current_interface_index(self) -> int:
        """Get current interface index."""
        return self._interface_index

    @property
    def available_interfaces(self) -> int:
        """Get number of available interfaces."""
        if hasattr(self.config, "interfaces"):
            return len(self.config.interfaces)
        return 1

    def switch_interface(self, index: int) -> bool:
        """
        Switch to a different interface.

        Args:
            index: Interface index to switch to (0-based)

        Returns:
            True if switch was successful
        """
        if not hasattr(self.config, "interfaces"):
            return index == 0

        if index < 0 or index >= len(self.config.interfaces):
            return False

        was_connected = self._status.connected
        if was_connected:
            self.disconnect()

        self._interface_index = index
        self._status = ConnectionStatus()

        if was_connected:
            return self.connect()
        return True

    @property
    def is_connected(self) -> bool:
        return self._status.connected

    @property
    def status(self) -> ConnectionStatus:
        return self._status

    @property
    def network(self) -> Optional[MeshNetwork]:
        if self._api:
            return self._api.network
        return None

    def get_connection_info(self) -> Dict[str, Any]:
        """Get current connection info for debugging/introspection.

        From meshforge's connection manager pattern.
        """
        return {
            "connected": self._status.connected,
            "connection_type": self._status.connection_type.value,
            "device_info": self._status.device_info,
            "error_message": self._status.error_message,
            "reconnect_attempts": self._status.reconnect_attempts,
            "last_connected": (self._status.last_connected.isoformat() if self._status.last_connected else None),
            "last_disconnected": (
                self._status.last_disconnected.isoformat() if self._status.last_disconnected else None
            ),
            "interface_index": self._interface_index,
            "available_interfaces": self.available_interfaces,
            "auto_reconnect": self._auto_reconnect,
        }

    def _wait_for_cooldown(self) -> None:
        """Wait for connection cooldown period.

        Devices (especially meshtasticd) need time between disconnect and
        reconnect to clean up resources.
        """
        elapsed = time.monotonic() - self._last_close_time
        if elapsed < CONNECTION_COOLDOWN:
            time.sleep(CONNECTION_COOLDOWN - elapsed)

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for an event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, *args, **kwargs) -> None:
        """Trigger all callbacks for an event."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except (ValueError, TypeError, AttributeError, KeyError, RuntimeError) as e:
                logger.warning("Callback error (%s): %s", event, e)

    def _get_current_interface(self):
        """Get the current interface config."""
        if hasattr(self.config, "interfaces") and self.config.interfaces:
            if self._interface_index < len(self.config.interfaces):
                return self.config.interfaces[self._interface_index]
        return self.config.interface

    def _detect_connection_type(self) -> ConnectionType:
        """Auto-detect the best available connection type."""
        iface = self._get_current_interface()
        requested = iface.type.lower()

        if requested != "auto":
            try:
                return ConnectionType(requested)
            except ValueError:
                pass  # Unknown type, continue to auto-detect

        # Try to detect serial ports
        import glob

        serial_ports = []
        for pattern in ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyAMA*"]:
            serial_ports.extend(glob.glob(pattern))

        if serial_ports:
            return ConnectionType.SERIAL

        # Check for TCP host configured
        if iface.hostname:
            return ConnectionType.TCP

        # Check if MQTT is enabled in config
        if self.config.mqtt.enabled:
            return ConnectionType.MQTT

        # Fall back to demo mode
        return ConnectionType.DEMO

    def connect(self, connection_type: Optional[ConnectionType] = None) -> bool:
        """
        Connect to mesh network using specified or auto-detected type.

        Tries connection types in order of preference with fallback.
        """
        if connection_type is None:
            connection_type = self._detect_connection_type()

        self._status.connection_type = connection_type

        # Define fallback order
        fallback_order = [ConnectionType.SERIAL, ConnectionType.TCP, ConnectionType.MQTT, ConnectionType.DEMO]

        # Start from requested type
        if connection_type in fallback_order:
            start_idx = fallback_order.index(connection_type)
            fallback_order = fallback_order[start_idx:]

        for conn_type in fallback_order:
            logger.info("Trying %s connection...", conn_type.value)

            # Respect cooldown between connection attempts
            self._wait_for_cooldown()

            if self._try_connect(conn_type):
                self._status.connected = True
                self._status.connection_type = conn_type
                self._status.last_connected = datetime.now(timezone.utc)
                self._status.reconnect_attempts = 0
                self._trigger_callbacks("on_connect", self._status)
                self._trigger_callbacks("on_status_change", self._status)

                # Start reconnection monitor
                self._start_reconnect_monitor()

                return True

            logger.info("%s connection failed, trying next...", conn_type.value)

        self._status.connected = False
        self._status.error_message = "All connection types failed"
        self._trigger_callbacks("on_status_change", self._status)
        return False

    def _try_connect(self, conn_type: ConnectionType) -> bool:
        """Attempt connection with specific type."""
        try:
            if conn_type == ConnectionType.SERIAL:
                return self._connect_serial()
            elif conn_type == ConnectionType.TCP:
                return self._connect_tcp()
            elif conn_type == ConnectionType.MQTT:
                return self._connect_mqtt()
            elif conn_type == ConnectionType.BLE:
                return self._connect_ble()
            elif conn_type == ConnectionType.DEMO:
                return self._connect_demo()
            else:
                return False
        except (OSError, ConnectionError, TimeoutError, ValueError, AttributeError) as e:
            # OSError: Network/device access errors
            # ConnectionError: Connection refused, reset, etc.
            # TimeoutError: Connection timeout
            # ValueError: Invalid configuration values
            # AttributeError: API mismatch or missing attributes
            self._status.error_message = str(e)
            logger.warning("Connection error: %s", e)
            return False

    def _connect_serial(self) -> bool:
        """Connect via serial/USB."""
        try:
            from .meshtastic_api import MeshtasticAPI

            self.config.interface.type = "serial"
            self._api = MeshtasticAPI(self.config)

            if self._api.connect():
                self._status.device_info = f"Serial: {self._api.connection_info.device_path}"
                self._forward_callbacks()
                return True
            return False
        except ImportError:
            logger.warning("Meshtastic library not available for serial connection")
            return False

    def _connect_tcp(self) -> bool:
        """Connect via TCP."""
        try:
            from .meshtastic_api import MeshtasticAPI

            if not self.config.interface.hostname:
                return False

            self.config.interface.type = "tcp"
            self._api = MeshtasticAPI(self.config)

            if self._api.connect():
                self._status.device_info = f"TCP: {self.config.interface.hostname}"
                self._forward_callbacks()
                return True
            return False
        except ImportError:
            logger.warning("Meshtastic library not available for TCP connection")
            return False

    def _connect_mqtt(self) -> bool:
        """Connect via MQTT broker."""
        try:
            from .mqtt_client import MQTTConfig, MQTTMeshtasticClient

            # Build MQTT config from Config object's mqtt settings
            mqtt_config = MQTTConfig.from_config(self.config)

            self._api = MQTTMeshtasticClient(self.config, mqtt_config)

            if self._api.connect():
                self._status.device_info = f"MQTT: {mqtt_config.broker}"
                self._forward_callbacks()
                return True
            return False
        except ImportError:
            logger.warning("paho-mqtt not available for MQTT connection")
            return False

    def _connect_ble(self) -> bool:
        """Connect via Bluetooth LE."""
        try:
            from .meshtastic_api import MeshtasticAPI

            if not self.config.interface.mac:
                return False

            self.config.interface.type = "ble"
            self._api = MeshtasticAPI(self.config)

            if self._api.connect():
                self._status.device_info = f"BLE: {self.config.interface.mac}"
                self._forward_callbacks()
                return True
            return False
        except ImportError:
            logger.warning("BLE libraries not available")
            return False

    def _connect_demo(self) -> bool:
        """Connect in demo mode (simulated)."""
        from .meshtastic_api import MockMeshtasticAPI

        self._api = MockMeshtasticAPI(self.config)

        if self._api.connect():
            self._status.device_info = "Demo Mode"
            self._forward_callbacks()
            return True
        return False

    def _forward_callbacks(self):
        """Forward API callbacks to our callbacks."""
        if not self._api:
            return

        def on_message(msg):
            self._trigger_callbacks("on_message", msg)

        def on_alert(alert):
            self._trigger_callbacks("on_alert", alert)

        def on_node_update(node_id, is_new):
            self._trigger_callbacks("on_node_update", node_id, is_new)

        self._api.register_callback("on_message", on_message)
        self._api.register_callback("on_alert", on_alert)
        self._api.register_callback("on_node_update", on_node_update)

    def disconnect(self) -> None:
        """Disconnect from mesh network."""
        self._running = False

        # Wait for reconnect monitor thread to finish
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=10)

        if self._api:
            self._api.disconnect()
            self._api = None

        self._status.connected = False
        self._status.last_disconnected = datetime.now(timezone.utc)
        self._last_close_time = time.monotonic()
        self._trigger_callbacks("on_disconnect")
        self._trigger_callbacks("on_status_change", self._status)

    def _start_reconnect_monitor(self):
        """Start background reconnection monitor."""
        if not self._auto_reconnect:
            return

        self._running = True
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        """Monitor connection and reconnect if needed."""
        while self._running:
            time.sleep(self._reconnect_delay)

            if not self._running:
                break

            # Check if still connected
            if self._api and hasattr(self._api, "is_connected"):
                if not self._api.is_connected:
                    self._handle_disconnect()

    def _handle_disconnect(self):
        """Handle unexpected disconnection with exponential backoff.

        Note: This runs inside _reconnect_loop, so we must NOT call
        self.connect() which would spawn another reconnect monitor thread.
        Instead, we directly attempt reconnection inline.
        """
        if not self._auto_reconnect:
            return

        self._status.connected = False
        self._status.last_disconnected = datetime.now(timezone.utc)
        self._last_close_time = time.monotonic()
        self._status.reconnect_attempts += 1
        self._trigger_callbacks("on_disconnect")
        self._trigger_callbacks("on_status_change", self._status)

        if self._status.reconnect_attempts <= self._max_reconnect_attempts:
            # Exponential backoff with jitter to prevent thundering herd
            base_delay = min(self._reconnect_delay * (1.5 ** (self._status.reconnect_attempts - 1)), 300)
            # Add +/-25% jitter
            delay = base_delay * (0.75 + random.random() * 0.5)
            logger.info(
                "Reconnecting in %.0fs (attempt %d/%d)...",
                delay,
                self._status.reconnect_attempts,
                self._max_reconnect_attempts,
            )
            time.sleep(delay)

            if not self._running:
                return

            # Reconnect directly without spawning a new monitor thread
            self._wait_for_cooldown()
            conn_type = self._status.connection_type
            if self._try_connect(conn_type):
                self._status.connected = True
                self._status.last_connected = datetime.now(timezone.utc)
                self._status.reconnect_attempts = 0
                self._trigger_callbacks("on_connect", self._status)
                self._trigger_callbacks("on_status_change", self._status)
                logger.info("Reconnected successfully")
            else:
                logger.warning("Reconnection failed")
        else:
            logger.error("Max reconnection attempts (%d) reached", self._max_reconnect_attempts)

    # Forwarded API methods

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Send a message."""
        if self._api:
            return self._api.send_message(text, destination, channel)
        return False

    def get_nodes(self) -> List[Node]:
        """Get all nodes."""
        if self._api:
            return self._api.get_nodes()
        return []

    def get_messages(self, channel: Optional[int] = None, limit: int = 100) -> List[Message]:
        """Get messages."""
        if self._api:
            return self._api.get_messages(channel, limit)
        return []

    def get_alerts(self, unread_only: bool = False) -> List[Alert]:
        """Get alerts."""
        if self._api:
            return self._api.get_alerts(unread_only)
        return []

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        if self._api and hasattr(self._api, "acknowledge_alert"):
            return self._api.acknowledge_alert(alert_id)
        return False

    @property
    def connection_health(self) -> Dict[str, Any]:
        """Get connection health metrics."""
        iface = self._get_current_interface()
        health = {
            "status": "disconnected",
            "connection_type": self._status.connection_type.value,
            "device_info": self._status.device_info,
            "reconnect_attempts": self._status.reconnect_attempts,
            "last_connected": self._status.last_connected.isoformat() if self._status.last_connected else None,
            "interface_index": self._interface_index,
            "available_interfaces": self.available_interfaces,
            "interface_type": iface.type if hasattr(iface, "type") else "unknown",
        }

        if self._api and hasattr(self._api, "connection_health"):
            # Get detailed health from the underlying API
            api_health = self._api.connection_health
            health.update(api_health)
        elif self._status.connected:
            health["status"] = "connected"

        return health

    @property
    def mesh_health(self) -> Dict[str, Any]:
        """Get overall mesh network health metrics."""
        if self.network:
            return self.network.mesh_health
        return {"status": "unknown", "score": 0}

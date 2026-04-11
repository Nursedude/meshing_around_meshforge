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
import hashlib
import json
import logging
import random
import struct
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .callbacks import CallbackMixin, extract_position, safe_float, safe_int
from .config import Config, MQTTConfig, MQTT_PUBLIC_USERNAME, MQTT_PUBLIC_PASSWORD
from .models import (
    CHUTIL_CRITICAL_THRESHOLD,
    CHUTIL_WARNING_THRESHOLD,
    MAX_MESSAGE_BYTES,
    VALID_RSSI_RANGE,
    VALID_SNR_RANGE,
    Alert,
    AlertType,
    ConnectionInfo,
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
_message_logger = logging.getLogger("mesh.messages")

# --- Robustness limits (from meshforge) ---
MAX_PAYLOAD_BYTES = 65536  # 64 KB max per MQTT message
DEFAULT_PORT_TLS = 8883  # Standard MQTT TLS port
STALE_CLEANUP_INTERVAL = 600  # Check every 10 minutes

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
except Exception as _crypto_exc:
    # Broad catch needed: pyo3 Rust panics from cryptography backend raise
    # non-standard exceptions that don't inherit from ImportError/OSError.
    MESH_CRYPTO_AVAILABLE = False
    CRYPTO_AVAILABLE = False
    PROTOBUF_AVAILABLE = False
    logger.info(
        "Mesh crypto unavailable (%s: %s). "
        "Encrypted packet decoding disabled — install 'cryptography' and "
        "'meshtastic' packages to enable.",
        type(_crypto_exc).__name__,
        _crypto_exc,
    )


# Connection health thresholds (seconds)
HEALTH_STALE_TIMEOUT = 300  # 5 minutes without messages = stale
HEALTH_SLOW_TIMEOUT = 60  # 1 minute without messages = slow
# Alert cooldown pruning
MAX_ALERT_COOLDOWNS = 1000  # Prune oldest entries when exceeded


class MQTTMeshtasticClient(CallbackMixin):
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
        self.mqtt_config = mqtt_config or config.mqtt

        # Connection info (mirrors MeshtasticAPI interface)
        self.connection_info = ConnectionInfo(
            interface_type="mqtt",
            device_path=f"{self.mqtt_config.broker}:{self.mqtt_config.port}",
        )

        # MQTT client
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._reconnect_count = 0
        self._intentional_disconnect = False  # Track intentional vs unexpected disconnects

        # Network state
        self.network = MeshNetwork()

        # Callbacks and alert cooldowns (from CallbackMixin)
        self._init_callbacks()
        # Wire INI cooldown_period to runtime (default 300s)
        self._alert_cooldown_seconds = config.alerts.cooldown_period

        # Chunk reassembly buffer (bot splits long responses into ~160-char chunks)
        from .meshtastic_api import _ChunkBuffer
        self._chunk_buffer = _ChunkBuffer(timeout=config.chunk_reassembly_timeout)
        self._chunk_buffer._flush_callback = self._emit_reassembled_message

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
        self._cleanup_interval = STALE_CLEANUP_INTERVAL
        self._cleanup_thread: Optional[threading.Thread] = None

        self._stop_event = threading.Event()

        # Persistence (mirrors MeshtasticAPI pattern)
        self._auto_save_thread: Optional[threading.Thread] = None
        self._last_save_time: Optional[datetime] = None
        self._last_logged_health: str = ""
        self._save_lock = threading.Lock()

        # Malformed message rejection rate tracking (SEC-14)
        self._rejection_window_start: float = time.monotonic()
        self._rejection_window_count: int = 0

        # Load persisted state if enabled
        self._load_persisted_state()

        # Generate client ID if not set
        if not self.mqtt_config.client_id:
            self.mqtt_config.client_id = f"meshforge-{uuid.uuid4().hex[:8]}"

        # Initialize packet processor for encryption/protobuf decoding
        self._packet_processor: Optional[MeshPacketProcessor] = None
        if MESH_CRYPTO_AVAILABLE:
            self._packet_processor = MeshPacketProcessor(encryption_key=self.mqtt_config.encryption_key)

    # ==================== Persistence Methods ====================

    def _load_persisted_state(self) -> None:
        """Load network state from persistent storage."""
        if not hasattr(self.config, "storage") or not self.config.storage.enabled:
            return

        state_path = self.config.get_state_file_path()
        if state_path.exists():
            loaded = MeshNetwork.load_from_file(state_path)
            if loaded and loaded.nodes:
                self.network = loaded
                self.network.connection_status = "disconnected"
                logger.info("MQTT: Loaded %d nodes from %s", len(self.network.nodes), state_path)

    def _save_state(self) -> bool:
        """Save network state to persistent storage.

        Uses a non-blocking lock to skip if a previous save is still in progress.
        """
        if not hasattr(self.config, "storage") or not self.config.storage.enabled:
            return False
        if not self._save_lock.acquire(blocking=False):
            logger.debug("MQTT: Skipping save — previous save still in progress")
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
        """Start background auto-save thread for crash-safe persistence."""
        if not hasattr(self.config, "storage"):
            return
        if self.config.storage.auto_save_interval <= 0:
            return

        def auto_save_loop():
            interval = self.config.storage.auto_save_interval
            while not self._stop_event.is_set():
                if self._stop_event.wait(timeout=interval):
                    break
                if self.is_connected:
                    self._save_state()

        self._auto_save_thread = threading.Thread(target=auto_save_loop, daemon=True, name="mqtt-auto-save")
        self._auto_save_thread.start()

    @property
    def is_connected(self) -> bool:
        with self._stats_lock:
            return self._connected

    @property
    def stats(self) -> Dict[str, Any]:
        """Get subscriber statistics (thread-safe)."""
        with self._stats_lock:
            return dict(self._stats)

    # Input validation: uses shared safe_float() / safe_int() from callbacks module.
    # Alert cooldown: uses base CallbackMixin._is_alert_cooled_down().

    def _check_battery_alert(self, node: "Node", sender_id: str) -> None:
        """Fire a low-battery alert if level is critical (with per-node cooldown)."""
        if node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
            if not self._is_alert_cooled_down(sender_id, "battery"):
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
                self._dispatch_alert_actions(alert)

    def _extract_position(self, pos_data: dict) -> Optional["Position"]:
        """Extract and validate a Position from a dict with latitude/latitudeI keys."""
        return extract_position(pos_data)

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
        logger.info(
            "Connecting to MQTT broker %s:%d (TLS: %s)",
            self.mqtt_config.broker,
            self.mqtt_config.port,
            self.mqtt_config.use_tls or self.mqtt_config.port == DEFAULT_PORT_TLS,
        )
        try:
            with self._stats_lock:
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

                # SEC-07: Warn when non-default credentials are sent without TLS
                _is_default_creds = self.mqtt_config.username == MQTT_PUBLIC_USERNAME and self.mqtt_config.password == MQTT_PUBLIC_PASSWORD
                if not _is_default_creds and not self.mqtt_config.use_tls and self.mqtt_config.port != DEFAULT_PORT_TLS:
                    logger.warning(
                        "Non-default MQTT credentials configured without TLS (port %d). "
                        "Credentials will be sent in cleartext. Consider enabling TLS (port 8883).",
                        self.mqtt_config.port,
                    )

            # TLS (auto-detect port 8883)
            if self.mqtt_config.use_tls or self.mqtt_config.port == DEFAULT_PORT_TLS:
                import ssl

                tls_kwargs = {"cert_reqs": ssl.CERT_REQUIRED}
                # Use PROTOCOL_TLS_CLIENT (the recommended constant since Python 3.10;
                # the generic PROTOCOL_TLS was deprecated in favor of this).
                if hasattr(ssl, "PROTOCOL_TLS_CLIENT"):
                    tls_kwargs["tls_version"] = ssl.PROTOCOL_TLS_CLIENT
                self._client.tls_set(**tls_kwargs)

            # Enable paho's built-in reconnect with exponential backoff
            self._client.reconnect_delay_set(
                min_delay=self.mqtt_config.reconnect_delay,
                max_delay=self.mqtt_config.max_reconnect_delay,
            )

            # Parse embedded port from broker hostname (e.g. "host:1884")
            broker = self.mqtt_config.broker
            port = self.mqtt_config.port
            if ":" in broker:
                parts = broker.rsplit(":", 1)
                try:
                    port = int(parts[1])
                    broker = parts[0]
                except ValueError:
                    pass  # Not a port number, keep as-is

            # Connect
            self._client.connect(broker, port, keepalive=60)

            # Start network loop in background
            self._client.loop_start()

            try:
                # Register atexit cleanup (from meshforge)
                atexit.register(self._atexit_cleanup)

                # Wait for connection (monotonic clock avoids wall-clock jumps)
                timeout = self.mqtt_config.connect_timeout
                start = time.monotonic()
                while not self.is_connected and (time.monotonic() - start) < timeout:
                    time.sleep(0.1)

                if self.is_connected:
                    self.network.connection_status = "connected (MQTT)"
                    self.network.my_node_id = self.mqtt_config.node_id or "mqtt-client"
                    self._connection_start = datetime.now(timezone.utc)
                    self._message_count = 0
                    with self._stats_lock:
                        self._stats["messages_received"] = 0
                        self._stats["messages_rejected"] = 0
                    self.connection_info.connected = True
                    self.connection_info.error_message = ""
                    self.connection_info.my_node_id = self.mqtt_config.node_id or "mqtt-client"
                    # Start background threads
                    self._start_cleanup_thread()
                    self._start_auto_save()
                    return True
                else:
                    # Connection timed out - stop the background loop thread
                    self.connection_info.connected = False
                    self.connection_info.error_message = (
                        f"Connection timed out after {self.mqtt_config.connect_timeout}s "
                        f"to {self.mqtt_config.broker}:{self.mqtt_config.port}"
                    )
                    logger.warning(
                        "MQTT connection timed out after %ds to %s:%d",
                        self.mqtt_config.connect_timeout,
                        self.mqtt_config.broker,
                        self.mqtt_config.port,
                    )
                    self._client.loop_stop()
                    return False
            except (OSError, RuntimeError):
                # Ensure the background loop is stopped if anything goes wrong
                self._client.loop_stop()
                raise

        except (OSError, ConnectionError, TimeoutError) as e:
            self.connection_info.connected = False
            self.connection_info.error_message = f"MQTT connection error ({type(e).__name__}): {e}"
            logger.error("MQTT connection error (%s): %s", type(e).__name__, e)
            return False
        except ValueError as e:
            self.connection_info.connected = False
            self.connection_info.error_message = f"MQTT config error: {e}"
            logger.error("MQTT config error: %s", e)
            return False

    def _atexit_cleanup(self) -> None:
        """Ensure state is saved and connection is cleaned up on process exit."""
        try:
            self._save_state()
        except (OSError, RuntimeError) as e:
            logger.debug("atexit save error: %s", e)
        try:
            self.disconnect()
        except (OSError, RuntimeError) as e:
            logger.debug("atexit cleanup error: %s", e)

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
                if not self.is_connected:
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
        self._chunk_buffer.cancel_all()
        # Save state before disconnecting
        self._save_state()

        with self._stats_lock:
            self._intentional_disconnect = True
            self._connected = False  # Signal threads to stop first
        self._stop_event.set()

        # Wait for background threads to finish
        if self._auto_save_thread and self._auto_save_thread.is_alive():
            self._auto_save_thread.join(timeout=5)
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except (OSError, RuntimeError):
                pass  # Already disconnected or broken pipe
        self.network.connection_status = "disconnected"
        self.connection_info.connected = False
        self._trigger_callbacks("on_disconnect")

    def _on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection."""
        if rc == 0:
            with self._stats_lock:
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
            self.connection_info.connected = True
            self.connection_info.error_message = ""

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
            self.connection_info.connected = False
            self.connection_info.error_message = f"MQTT connection refused: {reason}"
            logger.error("MQTT connection refused: %s", reason)

            # Permanent auth failures: stop reconnecting to avoid hammering broker
            if rc in (4, 5):
                logger.error(
                    "Authentication failure (rc=%d) — stopping reconnection. "
                    "Check MQTT username/password in config.",
                    rc,
                )
                with self._stats_lock:
                    self._intentional_disconnect = True
                    self._connected = False
                self.network.connection_status = f"auth_error: {reason}"
                if self._client:
                    try:
                        self._client.loop_stop()
                    except (OSError, RuntimeError):
                        pass
                self._trigger_callbacks("on_disconnect")

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        with self._stats_lock:
            self._connected = False
            intentional = self._intentional_disconnect
        self.network.connection_status = "disconnected"
        self.connection_info.connected = False

        if rc == 0 or intentional:
            logger.info("Disconnected from MQTT broker (clean)")
            with self._stats_lock:
                self._reconnect_count = 0
        else:
            # paho's built-in reconnect (enabled via reconnect_delay_set) handles this
            # We track the count for health reporting and add jitter to prevent
            # thundering herd when multiple clients reconnect simultaneously.
            with self._stats_lock:
                self._reconnect_count += 1
                count = self._reconnect_count

            # Apply jitter: randomize next reconnect delay within ±25%
            if self._client:
                base = min(
                    self.mqtt_config.reconnect_delay * (2 ** min(count - 1, 6)),
                    self.mqtt_config.max_reconnect_delay,
                )
                jitter = base * random.uniform(-0.25, 0.25)
                jittered = max(1, int(base + jitter))
                try:
                    self._client.reconnect_delay_set(min_delay=jittered, max_delay=self.mqtt_config.max_reconnect_delay)
                except (AttributeError, ValueError):
                    pass  # paho API may not support dynamic update

            # Log every 5th attempt at WARNING for visibility
            if count % 5 == 0:
                logger.warning(
                    "MQTT reconnect attempt %d (rc=%d), still trying...",
                    count,
                    rc,
                )
            else:
                logger.info("Unexpected MQTT disconnect (rc=%d), paho will auto-reconnect (attempt %d)", rc, count)

            # Enforce max reconnect attempts if configured
            max_attempts = getattr(self.mqtt_config, "max_reconnect_attempts", 0)
            if max_attempts > 0 and count >= max_attempts:
                logger.error(
                    "Max reconnect attempts (%d) reached — giving up. "
                    "Check broker availability and network connection.",
                    max_attempts,
                )
                with self._stats_lock:
                    self._intentional_disconnect = True
                self.network.connection_status = "max_reconnects_exceeded"
                if self._client:
                    try:
                        self._client.loop_stop()
                    except (OSError, RuntimeError):
                        pass

        self._trigger_callbacks("on_disconnect")

    @staticmethod
    def _validate_mqtt_topic_component(value: str, name: str) -> str:
        """Validate an MQTT topic component (topic_root or channel).

        Rejects null bytes, control characters, and MQTT wildcard characters
        that should not appear in user-configured topic components.
        """
        if not value:
            return value
        # Reject null bytes and control characters (except forward slash in topic_root)
        for ch in value:
            if ch == "\x00":
                raise ValueError(f"MQTT {name} must not contain null bytes")
            if ord(ch) < 0x20 and ch not in ("\t",):
                raise ValueError(f"MQTT {name} contains control character: {ch!r}")
        # Reject wildcard characters in user-supplied components
        if "#" in value or "+" in value:
            raise ValueError(f"MQTT {name} must not contain wildcard characters (# or +)")
        return value

    def _channel_name_to_index(self, channel_name: str) -> int:
        """Map a channel name back to its index in the configured channels list.

        Used to display incoming messages with a stable per-channel index for
        the TUI.  When channels='*' (wildcard) or the name isn't in the list,
        falls back to checking if the name matches the singular `channel`
        field (the outbound default), in which case returns 0 as a sensible
        default for "the channel mesh_client cares about".
        """
        if not channel_name:
            return 0

        channels_str = getattr(self.mqtt_config, "channels", "") or ""
        channel_list = [c.strip() for c in channels_str.split(",") if c.strip() and c.strip() != "*"]

        # Try direct match in the configured list
        for i, name in enumerate(channel_list):
            if name == channel_name:
                return i

        # Wildcard or not in list — check the outbound default
        if channel_name == (self.mqtt_config.channel or ""):
            return 0

        # Unknown channel — assign a stable hash-based index in 1-7 range
        # so different unknown channels appear distinct in the TUI without
        # colliding with the configured ones at index 0.
        return (hash(channel_name) % 7) + 1

    def _resolve_channel_name(self, channel_index: int) -> str:
        """Map a channel index to a channel name from the configured channels list.

        Args:
            channel_index: Numeric channel index (0-based).

        Returns:
            Channel name string for use in MQTT topic paths.
        """
        channels_str = getattr(self.mqtt_config, "channels", "") or self.mqtt_config.channel
        channel_list = [c.strip() for c in channels_str.split(",") if c.strip()]
        if not channel_list or "*" in channel_list:
            return self.mqtt_config.channel or "LongFast"
        if 0 <= channel_index < len(channel_list):
            return channel_list[channel_index]
        return channel_list[0]

    def _subscribe_topics(self):
        """Subscribe to Meshtastic MQTT topics for all configured channels."""
        root = self._validate_mqtt_topic_component(self.mqtt_config.topic_root, "topic_root")
        qos = self.mqtt_config.qos

        # Parse multi-channel list (comma-separated), fall back to single channel
        channels_str = getattr(self.mqtt_config, "channels", "") or self.mqtt_config.channel
        channel_list = [c.strip() for c in channels_str.split(",") if c.strip()]
        if not channel_list:
            channel_list = [self.mqtt_config.channel or "LongFast"]

        # Wildcard mode: subscribe to all channels under topic_root
        # Intended for local/private brokers where channel names are unknown
        if "*" in channel_list:
            topics = [f"{root}/#"]
            logger.info("Wildcard channel subscription: %s/#", root)
        else:
            # Build topic list from configured channels
            topics = []
            for ch in channel_list:
                ch = self._validate_mqtt_topic_component(ch, "channel")
                topics.append(f"{root}/{ch}/#")
                topics.append(f"{root}/{ch}/json/#")
                topics.append(f"{root}/{ch}/e/#")
                topics.append(f"{root}/{ch}/stat/#")

        # Deduplicate and subscribe
        seen = set()
        for topic in topics:
            if topic not in seen:
                seen.add(topic)
                sub_result = self._client.subscribe(topic, qos=qos)
                # paho-mqtt returns (rc, mid) tuple; check rc if available
                if isinstance(sub_result, tuple) and len(sub_result) >= 1 and sub_result[0] != 0:
                    logger.warning("Subscribe failed for %s (rc=%d)", topic, sub_result[0])
                else:
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

            # Update message stats (all under lock for consistent reads)
            with self._stats_lock:
                self._last_message_time = datetime.now(timezone.utc)
                self._message_count += 1
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
            # SEC-14: Escalate to WARNING if rejection rate is high (thread-safe)
            with self._stats_lock:
                self._rejection_window_count += 1
                now = time.monotonic()
                if now - self._rejection_window_start > 60:
                    if self._rejection_window_count > 10:
                        logger.warning(
                            "High malformed message rate: %d rejected in last 60s",
                            self._rejection_window_count,
                        )
                    self._rejection_window_start = now
                    self._rejection_window_count = 0
        except (KeyError, ValueError, TypeError, struct.error) as e:
            logger.warning("Error parsing MQTT message (%s): %s", type(e).__name__, e)

    def _parse_topic(self, topic: str) -> Dict[str, Any]:
        """Parse MQTT topic to extract metadata.

        Handles both Meshtastic v1 and v2 topic formats:

        v2 (current, used by firmware 2.x):
            msh/{region}/{subregion}/{version}/{e|json|stat}/{channel}/{node}
            e.g. msh/US/HI/2/e/meshforge/!a2e95ba4
            e.g. msh/US/TX/2/e/LongFast/!fa6ba854

        v1 (legacy):
            msh/{region}/{channel}/{e|json|stat}/{node}
            e.g. msh/US/LongFast/json/!12345678
        """
        parts = topic.split("/")
        info = {
            "region": "", "subregion": "", "channel": "",
            "msg_type": "", "node_id": "", "version": "", "raw_topic": topic,
        }

        # Detect v2 format: 7 parts with parts[3] in {"2"} (protocol version)
        # and parts[4] in known message types.
        if len(parts) >= 7 and parts[3] in ("2",) and parts[4] in ("e", "json", "stat"):
            # v2: msh/{region}/{subregion}/{version}/{type}/{channel}/{node}
            info["region"] = parts[1]
            info["subregion"] = parts[2]
            info["version"] = parts[3]
            info["msg_type"] = parts[4]
            info["channel"] = parts[5]
            info["node_id"] = parts[6]
        elif len(parts) >= 5 and parts[3] in ("e", "json", "stat"):
            # v1: msh/{region}/{channel}/{type}/{node}
            info["region"] = parts[1] if parts[1] in self.REGIONS else parts[1]
            info["channel"] = parts[2]
            info["msg_type"] = parts[3]
            info["node_id"] = parts[4]
        else:
            # Best-effort: just extract what we can from positional parts
            if len(parts) >= 2:
                info["region"] = parts[1]
            if len(parts) >= 3:
                info["channel"] = parts[2]
            if len(parts) >= 4:
                info["msg_type"] = parts[3]
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
                # Generate from sender + content hash for deduplication
                content = json.dumps(data.get("payload", {}), sort_keys=True)
                msg_id = hashlib.sha256(f"{sender_id}{content}".encode()).hexdigest()[:16]

            # Check for duplicate
            if self.network.is_duplicate_message(msg_id):
                return  # Skip duplicate

            # Extract SNR/RSSI with validation (None = absent, 0.0 = valid reading)
            snr = safe_float(data.get("snr", data.get("rxSnr")), *VALID_SNR_RANGE)
            rssi = safe_int(data.get("rssi", data.get("rxRssi")), *VALID_RSSI_RANGE)
            hop_limit = safe_int(data.get("hopLimit"), 0, 15) or 3
            hop_start = safe_int(data.get("hopStart"), 0, 15) or 3
            hop_count = max(0, hop_start - hop_limit)

            # Update node last seen and link quality
            node, is_new_node = self._ensure_node(sender_id, sender if isinstance(sender, int) else 0)
            if is_new_node:
                with self._stats_lock:
                    self._stats["nodes_discovered"] += 1

            # Update link quality (use is not None to preserve valid 0.0 dB readings)
            if snr is not None or rssi is not None:
                self.network.update_link_quality(
                    sender_id, float(snr if snr is not None else 0), int(rssi if rssi is not None else 0), hop_count
                )

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

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # Binary payload on a /json/ topic — usually a misrouted encrypted
            # message or a gateway that publishes protobuf under /json/.  Not
            # actionable; log at debug only.
            logger.debug("Malformed JSON message on %s: %s", topic, e)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("JSON message parse error (%s): %s", type(e).__name__, e)

    def _emit_mqtt_message(self, text: str, meta: dict) -> None:
        """Create and store a Message from MQTT metadata, check commands/keywords."""
        sender_id = meta.get("sender_id", "")
        sender_name = ""
        node = self.network.get_node(sender_id)
        if node:
            sender_name = node.display_name

        message = Message(
            id=meta.get("msg_id") or str(uuid.uuid4()),
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_id=str(meta.get("recipient_id", "")),
            channel=meta.get("channel", 0),
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            hop_count=meta.get("hop_count", 0),
            snr=float(meta.get("snr") or 0),
            rssi=int(meta.get("rssi") or 0),
            is_incoming=True,
        )

        self.network.add_message(message)
        _message_logger.info("ch%d %s (%s): %s", message.channel, sender_name, sender_id, text)
        self._trigger_callbacks("on_message", message)

        if not self._handle_command(message):
            self._check_emergency_keywords(message)

    def _emit_reassembled_message(self, combined_text: str, meta: dict, chunk_count: int) -> None:
        """Called by _ChunkBuffer when a buffered sequence is complete."""
        logger.info("Reassembled %d MQTT chunks (%d chars)", chunk_count, len(combined_text))
        self._emit_mqtt_message(combined_text, meta)

    def _handle_text_from_json(self, data: dict, sender_id: str, msg_id: str = ""):
        """Handle text message from JSON."""
        payload = data.get("payload", {})
        text = payload.get("text", "") if isinstance(payload, dict) else str(payload)

        if not text:
            return

        # Extract signal info with validation
        snr = safe_float(data.get("snr", data.get("rxSnr")), *VALID_SNR_RANGE)
        rssi = safe_int(data.get("rssi", data.get("rxRssi")), *VALID_RSSI_RANGE)
        hop_limit = safe_int(data.get("hopLimit"), 0, 15) or 3
        hop_start = safe_int(data.get("hopStart"), 0, 15) or 3
        hop_count = max(0, hop_start - hop_limit)
        channel = data.get("channel", 0)

        meta = {
            "sender_id": sender_id, "msg_id": msg_id, "channel": channel,
            "snr": snr, "rssi": rssi, "hop_count": hop_count,
            "recipient_id": str(data.get("to", "")),
        }

        # Try chunk reassembly — buffers long messages that may be chunks
        if self._chunk_buffer.add(sender_id, channel, text, meta):
            logger.debug("MQTT buffered chunk from %s ch%d (%d bytes)", sender_id, channel, len(text))
            return

        self._emit_mqtt_message(text, meta)

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
            position = self._extract_position(pos_data)
            if position:
                node.position = position
            node.last_heard = datetime.now(timezone.utc)

    def _handle_telemetry_from_json(self, data: dict, sender_id: str):
        """Handle telemetry from JSON with input validation."""
        payload = data.get("payload", {})
        telemetry = payload.get("telemetry", payload)
        device_metrics = telemetry.get("deviceMetrics", telemetry)

        node = self.network.get_node(sender_id)
        if node:

            # Validate device metrics (from meshforge patterns)
            battery = safe_int(device_metrics.get("batteryLevel"), 0, 101) or 0
            voltage = safe_float(device_metrics.get("voltage"), 0.0, 10.0) or 0.0
            ch_util = safe_float(device_metrics.get("channelUtilization"), 0.0, 100.0) or 0.0
            air_util = safe_float(device_metrics.get("airUtilTx"), 0.0, 100.0) or 0.0

            # Environment metrics (BME280, BME680, BMP280)
            env_metrics = telemetry.get("environmentMetrics", {})
            temperature = safe_float(env_metrics.get("temperature"), -50.0, 100.0)
            humidity = safe_float(env_metrics.get("relativeHumidity"), 0.0, 100.0)
            pressure = safe_float(env_metrics.get("barometricPressure"), 300.0, 1200.0)
            gas_resistance = safe_float(env_metrics.get("gasResistance"), 0.0, 1000000.0)

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

            self._check_battery_alert(node, sender_id)

            # Channel congestion alert (with per-node cooldown)
            if ch_util >= CHUTIL_CRITICAL_THRESHOLD:
                if not self._is_alert_cooled_down(sender_id, "congestion_critical"):
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
                    self._dispatch_alert_actions(alert)
            elif ch_util >= CHUTIL_WARNING_THRESHOLD:
                if not self._is_alert_cooled_down(sender_id, "congestion_warning"):
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
                    self._dispatch_alert_actions(alert)

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
                try:
                    node_num = int(node_id[1:], 16)
                except ValueError:
                    node_num = 0
                self._ensure_node(node_id, node_num)

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
            try:
                node_num = int(node_id[1:], 16)
            except ValueError:
                node_num = 0
            self._ensure_node(node_id, node_num)

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
        self._ensure_node(sender_id, result.sender if result.sender is not None else 0)

        # Extract SNR/RSSI if available (use None sentinel so 0.0 dB isn't dropped)
        snr = decoded.get("rx_snr")
        rssi = decoded.get("rx_rssi")
        try:
            hop_limit = int(decoded.get("hop_limit", 3))
        except (TypeError, ValueError):
            hop_limit = 3
        hop_count = max(0, 3 - hop_limit)  # Estimate hops

        if snr is not None or rssi is not None:
            self.network.update_link_quality(sender_id, float(snr or 0), int(rssi or 0), hop_count)

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
                position = self._extract_position(pos_data)
                if position:
                    node.position = position
                    with self._stats_lock:
                        self._stats["position_updates"] += 1
                    self._trigger_callbacks("on_position", sender_id)

        elif msg_type == "telemetry" or portnum == 67:
            telemetry_data = decoded.get("telemetry", {})
            device_metrics = telemetry_data.get("device_metrics", {})
            env_metrics = telemetry_data.get("environment_metrics", {})
            node = self.network.get_node(sender_id)
            if node and (device_metrics or env_metrics):
                node.telemetry = NodeTelemetry(
                    battery_level=device_metrics.get("battery_level", 0),
                    voltage=device_metrics.get("voltage", 0),
                    channel_utilization=device_metrics.get("channel_utilization", 0),
                    air_util_tx=device_metrics.get("air_util_tx", 0),
                    uptime_seconds=device_metrics.get("uptime_seconds", 0),
                    last_updated=datetime.now(timezone.utc),
                    temperature=env_metrics.get("temperature") or None,
                    humidity=env_metrics.get("relative_humidity") or None,
                    pressure=env_metrics.get("barometric_pressure") or None,
                    gas_resistance=env_metrics.get("gas_resistance") or None,
                )
                with self._stats_lock:
                    self._stats["telemetry_updates"] += 1
                self._trigger_callbacks("on_telemetry", sender_id, node.telemetry)

                self._check_battery_alert(node, sender_id)

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
                    neighbor_snr = neighbor.get("snr")
                    if neighbor_snr is not None and self.network.get_node(neighbor_node_id):
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
            # Partial relay node (last 1-2 bytes) — zero-pad as placeholder.
            # These may be merged later when full node info arrives.
            relay_id = f"!0000{relay_node:04x}"

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
        snr = decoded.get("rx_snr")
        rssi = decoded.get("rx_rssi")
        hop_limit = decoded.get("hop_limit", 3)
        hop_count = max(0, 3 - hop_limit)

        # The 'channel' field in MeshPacket is the XOR hash (0-255), not a
        # display index.  Use the channel NAME from the topic when available
        # and look up the corresponding index from the configured channels list.
        channel = self._channel_name_to_index(topic_info.get("channel", ""))

        meta = {
            "sender_id": sender_id, "msg_id": msg_id, "channel": channel,
            "channel_name": topic_info.get("channel", ""),
            "snr": snr, "rssi": rssi, "hop_count": hop_count,
            "recipient_id": str(decoded.get("to", "")),
        }

        # Try chunk reassembly
        if self._chunk_buffer.add(sender_id, channel, text, meta):
            logger.debug("MQTT buffered decoded chunk from %s ch%d (%d bytes)", sender_id, channel, len(text))
            return

        self._emit_mqtt_message(text, meta)

    # Public Meshtastic MQTT brokers — auto_respond MUST be off for these
    _PUBLIC_BROKERS = {"mqtt.meshtastic.org"}

    def _handle_command(self, message: Message) -> bool:
        """Check if message is a recognized command. Returns True if handled.

        When a message matches a known command, it is treated as a command
        rather than checked for emergency keywords. Auto-respond is blocked
        on public MQTT brokers — only private/local brokers may send responses.
        """
        if not self.config.commands.enabled:
            return False

        text_stripped = message.text.strip().lower()
        recognized = [c.lower() for c in self.config.commands.commands]

        if text_stripped not in recognized:
            return False

        logger.info("Command received via MQTT: %s from %s", text_stripped, message.sender_name)
        self._trigger_callbacks("on_command", message, text_stripped)

        # Auto-respond only on private brokers
        if self.config.commands.auto_respond:
            broker = self.mqtt_config.broker
            if broker in self._PUBLIC_BROKERS:
                logger.warning(
                    "auto_respond blocked: %s is a public broker. "
                    "Bot responses are not allowed on public MQTT.",
                    broker,
                )
            else:
                response = self._get_command_response(text_stripped)
                if response:
                    self.send_message(response, message.sender_id, message.channel)

        return True

    def _get_command_response(self, command: str) -> str:
        """Generate response text for a recognized command.

        For data-source commands (weather, tsunami, etc.), fetches live data
        from the URL configured in [data_sources]. All sources and codes
        are driven by mesh_client.ini.
        """
        from meshing_around_clients import __version__
        from .meshtastic_api import _fetch_data_source

        if command in ("cmd", "help"):
            cmds = ", ".join(self.config.commands.commands)
            return f"MeshForge v{__version__} commands: {cmds}"
        elif command == "ping":
            return "pong"
        elif command == "version":
            return f"MeshForge v{__version__}"
        elif command == "nodes":
            count = len(self.network.nodes)
            return f"Tracking {count} node{'s' if count != 1 else ''}"
        elif command == "status":
            connected = "connected" if self.is_connected else "disconnected"
            nodes = len(self.network.nodes)
            msgs = len(self.network.messages)
            return f"Status: {connected} | {nodes} nodes | {msgs} msgs"
        elif command == "info":
            return f"MeshForge v{__version__} mesh monitor"
        elif command == "uptime":
            if self._connection_start:
                delta = datetime.now(timezone.utc) - self._connection_start
                hours, rem = divmod(int(delta.total_seconds()), 3600)
                mins, secs = divmod(rem, 60)
                return f"Uptime: {hours}h {mins}m {secs}s"
            return "Uptime: unknown"

        # Check data sources for this command
        sources = self.config.data_sources.get_enabled_sources()
        if command in sources:
            return _fetch_data_source(sources[command])

        return ""

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
                self._dispatch_alert_actions(alert)
                break

    def _parse_destination(self, destination: Any) -> int:
        """Parse a destination (^all / !hex / int / str) into a uint32 node number.

        Returns 0xFFFFFFFF for broadcast.
        """
        if destination in ("^all", None, 0, "0"):
            return 0xFFFFFFFF
        if isinstance(destination, int):
            return destination & 0xFFFFFFFF
        if isinstance(destination, str):
            if destination.startswith("!"):
                return int(destination[1:], 16) & 0xFFFFFFFF
            return int(destination) & 0xFFFFFFFF
        return 0xFFFFFFFF

    def _build_encrypted_envelope(
        self,
        text: str,
        channel_name: str,
        destination: Any = "^all",
    ) -> Optional[bytes]:
        """Build a ServiceEnvelope protobuf containing an encrypted text packet.

        This is the format that Meshtastic radios with MQTT downlink enabled
        subscribe to.  When published to `msh/{root}/{channel}/e/{node_id}`,
        the radio decrypts the inner Data payload using the channel PSK and
        re-transmits the message over LoRa.

        Returns serialized envelope bytes, or None if the envelope cannot be
        built (missing deps, invalid node_id, encryption failure).
        """
        if not PROTOBUF_AVAILABLE or not CRYPTO_AVAILABLE:
            return None

        try:
            from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2
            from meshtastic.util import generate_channel_hash
        except ImportError:
            logger.debug("meshtastic protobuf modules not available")
            return None

        # Parse sender node ID from config (must be !hex format)
        sender_str = self.mqtt_config.node_id or ""
        if not sender_str.startswith("!"):
            logger.warning(
                "Cannot build encrypted envelope: node_id must be Meshtastic hex format (!12345678), got %r",
                sender_str,
            )
            return None
        try:
            sender_node = int(sender_str[1:], 16)
        except ValueError:
            logger.warning("Cannot build encrypted envelope: invalid node_id %r", sender_str)
            return None

        if not self._packet_processor:
            logger.warning("Cannot build encrypted envelope: MeshPacketProcessor not initialized")
            return None

        # Generate a random packet ID (uint32, non-zero)
        packet_id = random.randint(1, 0xFFFFFFFF)

        # Build Data payload (portnum + text)
        data = mesh_pb2.Data()
        data.portnum = portnums_pb2.TEXT_MESSAGE_APP
        data.payload = text.encode("utf-8")
        data_bytes = data.SerializeToString()

        # Encrypt Data with AES-CTR using channel PSK (from mqtt_config.encryption_key)
        encrypted = self._packet_processor.crypto.encrypt(data_bytes, packet_id, sender_node)
        if not encrypted:
            logger.warning("Encryption failed — check encryption_key in config")
            return None

        # Parse destination into uint32
        try:
            dest_node = self._parse_destination(destination)
        except (ValueError, AttributeError) as e:
            logger.warning("Invalid destination %r: %s", destination, e)
            return None

        # Compute the Meshtastic channel hash (XOR-fold of name + PSK).
        # The firmware uses this to identify which channel a packet belongs
        # to when it arrives.  Without it, receivers can't match the packet
        # to the right channel for decryption.
        try:
            ch_hash = generate_channel_hash(channel_name, self.mqtt_config.encryption_key)
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("Could not compute channel hash for %r: %s", channel_name, e)
            ch_hash = 0

        # Build MeshPacket
        packet = mesh_pb2.MeshPacket()
        setattr(packet, "from", sender_node)
        packet.to = dest_node
        packet.id = packet_id
        packet.channel = ch_hash  # XOR hash of channel name + PSK
        packet.hop_limit = 3
        packet.hop_start = 3
        packet.want_ack = False
        packet.priority = mesh_pb2.MeshPacket.Priority.RELIABLE
        packet.encrypted = encrypted

        # Wrap in ServiceEnvelope
        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.packet.CopyFrom(packet)
        envelope.channel_id = channel_name
        envelope.gateway_id = sender_str

        return envelope.SerializeToString()

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Send a message via MQTT.

        Publishes to the encrypted downlink topic format that Meshtastic
        radios subscribe to — `msh/{root}/{channel}/e/{node_id}`.  Radios
        with MQTT downlink enabled decrypt and re-transmit over LoRa.

        Falls back to the legacy JSON format if protobuf or crypto deps
        are unavailable (visible to other MQTT clients but won't reach
        radios).
        """
        if not self.is_connected or not self._client:
            return False

        if not self.mqtt_config.node_id:
            logger.warning("Cannot send: no node_id configured for MQTT")
            return False

        # Warn if node_id doesn't look like a virtual ID (e.g., !c0deba5e).
        # Real hardware IDs are derived from chip serial numbers and rarely
        # start with 'c0de' or other distinctive prefixes.  If the configured
        # node_id matches a real radio's ID, the firmware filters it as
        # loopback and never retransmits.
        nid_lower = self.mqtt_config.node_id.lower().lstrip("!")
        if nid_lower and not (nid_lower.startswith("c0de") or nid_lower.startswith("feed") or nid_lower.startswith("dead")):
            if not getattr(self, "_node_id_warned", False):
                logger.warning(
                    "node_id %r looks like a real hardware ID, not a virtual one. "
                    "If it matches the connected radio, downlink messages will be "
                    "filtered as loopback. Use a !c0de... prefix or re-run the "
                    "WiFi Radio wizard to auto-generate a safe virtual ID.",
                    self.mqtt_config.node_id,
                )
                self._node_id_warned = True

        msg_bytes = len(text.encode("utf-8"))
        if msg_bytes > MAX_MESSAGE_BYTES:
            logger.warning("Message too long (%d/%d bytes), rejecting", msg_bytes, MAX_MESSAGE_BYTES)
            return False

        # Validate destination
        if destination != "^all":
            try:
                int(destination.lstrip("!"), 16) if destination.startswith("!") else int(destination)
            except ValueError:
                logger.warning("Invalid destination '%s': must be ^all, a node number, or !hex_id", destination)
                return False

        try:
            channel_name = self._resolve_channel_name(channel)

            # Prefer encrypted downlink (reaches radios via MQTT subscription)
            envelope_bytes = self._build_encrypted_envelope(text, channel_name, destination)

            if envelope_bytes:
                # Meshtastic MQTT protocol v2 topic format:
                # {root}/2/e/{channel_name}/{node_id}
                # The "2" is the protocol version, "e" means encrypted.
                # Radios with downlink_enabled=True on the channel subscribe
                # to {root}/2/e/{channel_name}/# and re-transmit over LoRa.
                topic = f"{self.mqtt_config.topic_root}/2/e/{channel_name}/{self.mqtt_config.node_id}"
                self._client.publish(topic, envelope_bytes)
                logger.info(
                    "Sent encrypted downlink: %s (%d bytes payload)",
                    topic,
                    len(envelope_bytes),
                )
            else:
                # Legacy JSON fallback — visible to other MQTT clients but
                # won't be transmitted over LoRa by radios.
                message = {
                    "from": self.mqtt_config.node_id,
                    "to": destination,
                    "channel": channel,
                    "type": "text",
                    "payload": {"text": text},
                }
                topic = f"{self.mqtt_config.topic_root}/2/json/{channel_name}/{self.mqtt_config.node_id}"
                self._client.publish(topic, json.dumps(message))
                logger.warning(
                    "Sent JSON fallback to %s — encrypted envelope build failed, message will NOT reach LoRa radios",
                    topic,
                )

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
        return list(self.network.alerts)

    @property
    def connection_health(self) -> Dict[str, Any]:
        """Get connection health metrics."""
        now = datetime.now(timezone.utc)

        # Snapshot lock-protected values
        with self._stats_lock:
            message_count = self._message_count
            stats_copy = dict(self._stats)
            reconnect_count = self._reconnect_count

        # Calculate uptime
        uptime_seconds = 0
        connected = self.is_connected
        if self._connection_start and connected:
            uptime_seconds = (now - self._connection_start).total_seconds()

        # Calculate message rate (messages per minute)
        msg_rate = 0.0
        if uptime_seconds > 0:
            msg_rate = (message_count / uptime_seconds) * 60

        # Time since last message
        last_msg_ago = None
        if self._last_message_time:
            last_msg_ago = (now - self._last_message_time).total_seconds()

        # Determine health status
        if not connected:
            status = "disconnected"
        elif last_msg_ago is None:
            status = "connected_no_traffic"
        elif last_msg_ago > HEALTH_STALE_TIMEOUT:
            status = "stale"
        elif last_msg_ago > HEALTH_SLOW_TIMEOUT:
            status = "slow"
        else:
            status = "healthy"

        if status != self._last_logged_health:
            old = self._last_logged_health or "initial"
            self._last_logged_health = status
            if status in ("disconnected", "stale"):
                logger.warning("MQTT health: %s → %s", old, status)
            else:
                logger.info("MQTT health: %s → %s", old, status)

        return {
            "status": status,
            "connected": connected,
            "broker": self.mqtt_config.broker,
            "uptime_seconds": int(uptime_seconds),
            "message_count": message_count,
            "messages_per_minute": round(msg_rate, 2),
            "last_message_ago_seconds": int(last_msg_ago) if last_msg_ago else None,
            "reconnect_count": reconnect_count,
            "messages_dropped": stats_copy.get("messages_rejected", 0),
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

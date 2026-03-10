"""
Configuration management for Meshing-Around Clients.
Handles loading and saving client configuration.
"""

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class InterfaceConfig:
    """Interface connection configuration."""

    type: str = "serial"  # serial, tcp, http, ble, mqtt
    port: str = ""  # Auto-detect if empty
    hostname: str = ""
    mac: str = ""
    baudrate: int = 115200
    enabled: bool = True  # For multi-interface support
    http_url: str = ""  # Base URL for meshtasticd HTTP API (e.g. http://meshtastic.local)
    hardware_model: str = ""  # Radio model (e.g. TBEAM, RAK4631, HELTEC)
    label: str = ""  # User-friendly label for this interface

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InterfaceConfig":
        """Create from dictionary."""
        return cls(
            type=str(data.get("type", "serial")).lower(),
            port=str(data.get("port", "")),
            hostname=str(data.get("hostname", "")),
            mac=str(data.get("mac", "")),
            baudrate=int(data.get("baudrate", 115200)),
            enabled=_str_to_bool(data.get("enabled", True)),
            http_url=str(data.get("http_url", "")),
            hardware_model=str(data.get("hardware_model", "")),
            label=str(data.get("label", "")),
        )


def _str_to_bool(value: Any) -> bool:
    """Convert string to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "on")
    return bool(value)


@dataclass
class AlertConfig:
    """Alert system configuration."""

    enabled: bool = True
    emergency_keywords: List[str] = field(
        default_factory=lambda: [
            "emergency",
            "911",
            "112",
            "999",
            "police",
            "fire",
            "ambulance",
            "rescue",
            "help",
            "sos",
            "mayday",
        ]
    )
    alert_channel: int = 2
    play_sound: bool = False
    cooldown_period: int = 300


@dataclass
class WebConfig:
    """Web client configuration."""

    host: str = "127.0.0.1"
    port: int = 9090
    debug: bool = False
    api_key: str = ""
    enable_auth: bool = False
    username: str = "admin"
    password_hash: str = ""
    trust_proxy: bool = False  # Trust X-Forwarded-For for client IP (behind reverse proxy)
    cors_origins: str = ""  # Comma-separated allowed origins, empty = same-origin only


@dataclass
class TuiConfig:
    """TUI client configuration."""

    refresh_rate: float = 1.0
    color_scheme: str = "default"
    show_timestamps: bool = True
    message_history: int = 500
    alert_sound: bool = True
    space_weather: bool = True


@dataclass
class StorageConfig:
    """Persistent storage configuration."""

    enabled: bool = True
    state_file: str = ""  # Auto-generate if empty
    auto_save_interval: int = 300  # Save every 5 minutes (0 = disable)
    max_message_history: int = 1000
    max_node_history_days: int = 30  # Keep nodes not seen for this many days


@dataclass
class LoggingConfig:
    """Logging configuration with rotation support."""

    enabled: bool = True
    level: str = "INFO"
    file: str = "mesh_client.log"
    max_size_mb: int = 10
    backup_count: int = 3


@dataclass
class MQTTConfig:
    """MQTT connection configuration for radio-less operation."""

    enabled: bool = False
    broker: str = "mqtt.meshtastic.org"
    port: int = 1883
    use_tls: bool = False
    # Public credentials for mqtt.meshtastic.org (see meshtastic.org/docs/software/mqtt).
    # These are intentionally public and shared by all Meshtastic clients.
    username: str = "meshdev"
    password: str = "large4cats"
    topic_root: str = "msh/US"
    channel: str = "LongFast"
    channels: str = "LongFast"  # Comma-separated channel list, e.g. "LongFast,meshforge,2"
    node_id: str = ""  # Virtual node ID for sending
    client_id: str = ""  # MQTT client ID (auto-generated if empty)
    # Encryption key for decrypting channel messages (base64 encoded)
    encryption_key: str = ""
    # QoS level for subscriptions (0, 1, or 2)
    qos: int = 1
    # Connection timeout (seconds to wait for MQTT broker connection)
    connect_timeout: int = 10
    # Reconnect settings
    reconnect_delay: int = 5
    max_reconnect_delay: int = 300  # Max backoff between reconnect attempts
    max_reconnect_attempts: int = 10


class Config:
    """Main configuration class for Meshing-Around Clients.

    Supports multiple interfaces (up to 9) for compatibility with upstream
    meshing-around config format. The `interface` property returns the first
    enabled interface for backward compatibility.
    """

    DEFAULT_CONFIG_PATHS = [
        Path.home() / ".config" / "meshing-around-clients" / "config.ini",
        Path.cwd() / "client_config.ini",
        Path.cwd() / "mesh_client.ini",
        Path("/etc/meshing-around-clients/config.ini"),
    ]

    # Upstream meshing-around config paths
    UPSTREAM_CONFIG_PATHS = [
        Path.home() / "meshing-around" / "config.ini",
        Path.cwd() / "config.ini",
        Path("/opt/meshing-around/config.ini"),
    ]

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else self._find_config()
        self._parser = configparser.ConfigParser()

        # Multi-interface support (up to 9)
        self._interfaces: List[InterfaceConfig] = [InterfaceConfig()]

        # Configuration sections
        self.alerts = AlertConfig()
        self.web = WebConfig()
        self.tui = TuiConfig()
        self.mqtt = MQTTConfig()
        self.storage = StorageConfig()
        self.logging = LoggingConfig()

        # Bot connection info
        self.bot_name = "MeshBot"
        self.admin_nodes: List[str] = []
        self.favorite_nodes: List[str] = []

        # Config format tracking
        self.config_format = "meshforge"  # or "upstream"

        if self.config_path and self.config_path.exists():
            self.load()

    @property
    def interface(self) -> InterfaceConfig:
        """Get primary (first enabled) interface for backward compatibility."""
        for iface in self._interfaces:
            if iface.enabled:
                return iface
        return self._interfaces[0] if self._interfaces else InterfaceConfig()

    @interface.setter
    def interface(self, value: InterfaceConfig) -> None:
        """Set primary interface."""
        if self._interfaces:
            self._interfaces[0] = value
        else:
            self._interfaces = [value]

    @property
    def interfaces(self) -> List[InterfaceConfig]:
        """Get all configured interfaces."""
        return self._interfaces

    def get_enabled_interfaces(self) -> List[InterfaceConfig]:
        """Get only enabled interfaces."""
        return [iface for iface in self._interfaces if iface.enabled]

    def add_interface(self, interface: InterfaceConfig) -> bool:
        """Add an interface (max 9)."""
        if len(self._interfaces) >= 9:
            return False
        self._interfaces.append(interface)
        return True

    def _find_config(self) -> Optional[Path]:
        """Find an existing config file, checking MeshForge paths first."""
        # Check MeshForge paths first
        for path in self.DEFAULT_CONFIG_PATHS:
            if path.exists():
                return path
        # Check upstream paths
        for path in self.UPSTREAM_CONFIG_PATHS:
            if path.exists():
                return path
        return self.DEFAULT_CONFIG_PATHS[0]  # Default path for new config

    def _detect_config_format(self) -> str:
        """Detect if config is upstream meshing-around or MeshForge format."""
        sections = self._parser.sections()
        # Upstream has 'bbs', 'sentry', 'emergencyHandler' with specific keys
        if "bbs" in sections or "sentry" in sections:
            return "upstream"
        # Check for upstream-style interface keys (SentryEnabled, etc.)
        if self._parser.has_section("sentry"):
            if self._parser.has_option("sentry", "sentryenabled"):
                return "upstream"
        return "meshforge"

    def _load_interfaces(self) -> None:
        """Load interface configurations (supports 1-9 interfaces)."""
        self._interfaces = []

        # Try MeshForge format: [interface], [interface.2], etc.
        # Also try upstream format: [interface], [interface2], etc.
        for i in range(1, 10):
            data = None

            if i == 1:
                # First interface can be [interface], [interface.1], or [interface1]
                for section in ["interface", "interface.1", "interface1"]:
                    if self._parser.has_section(section):
                        data = dict(self._parser.items(section))
                        break
            else:
                # Additional interfaces: [interface.N] or [interfaceN]
                for section in [f"interface.{i}", f"interface{i}"]:
                    if self._parser.has_section(section):
                        data = dict(self._parser.items(section))
                        break

            if data:
                iface = InterfaceConfig.from_dict(data)
                # First interface is always enabled unless explicitly disabled
                if i == 1 and "enabled" not in data:
                    iface.enabled = True
                self._interfaces.append(iface)

        # Ensure at least one interface exists
        if not self._interfaces:
            self._interfaces = [InterfaceConfig()]

    def load(self) -> bool:
        """Load configuration from file.

        Supports both MeshForge and upstream meshing-around formats.
        Automatically detects format and loads multi-interface configs.
        """
        if not self.config_path or not self.config_path.exists():
            return False

        try:
            self._parser.read(self.config_path)

            # Detect config format
            self.config_format = self._detect_config_format()

            # Load interfaces (supports 1-9)
            self._load_interfaces()

            # General
            if self._parser.has_section("general"):
                self.bot_name = self._parser.get("general", "bot_name", fallback="MeshBot")
                admin_str = self._parser.get("general", "bbs_admin_list", fallback="")
                self.admin_nodes = [n.strip() for n in admin_str.split(",") if n.strip()]
                fav_str = self._parser.get("general", "favoriteNodeList", fallback="")
                self.favorite_nodes = [n.strip() for n in fav_str.split(",") if n.strip()]

            # Alerts
            if self._parser.has_section("emergencyHandler"):
                self.alerts.enabled = self._parser.getboolean("emergencyHandler", "enabled", fallback=True)
                keywords_str = self._parser.get("emergencyHandler", "emergency_keywords", fallback="")
                if keywords_str:
                    self.alerts.emergency_keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
                self.alerts.alert_channel = self._parser.getint("emergencyHandler", "alert_channel", fallback=2)
                self.alerts.play_sound = self._parser.getboolean("emergencyHandler", "play_sound", fallback=False)
                self.alerts.cooldown_period = self._parser.getint("emergencyHandler", "cooldown_period", fallback=300)

            # Web
            if self._parser.has_section("web"):
                self.web.host = self._parser.get("web", "host", fallback="127.0.0.1")
                raw_port = self._parser.getint("web", "port", fallback=9090)
                self.web.port = max(1, min(raw_port, 65535))
                self.web.debug = self._parser.getboolean("web", "debug", fallback=False)
                self.web.api_key = self._parser.get("web", "api_key", fallback="")
                self.web.enable_auth = self._parser.getboolean("web", "enable_auth", fallback=False)
                self.web.username = self._parser.get("web", "username", fallback="admin")
                self.web.trust_proxy = self._parser.getboolean("web", "trust_proxy", fallback=False)
                self.web.cors_origins = self._parser.get("web", "cors_origins", fallback="")

            # TUI
            if self._parser.has_section("tui"):
                self.tui.refresh_rate = self._parser.getfloat("tui", "refresh_rate", fallback=1.0)
                self.tui.color_scheme = self._parser.get("tui", "color_scheme", fallback="default")
                self.tui.show_timestamps = self._parser.getboolean("tui", "show_timestamps", fallback=True)
                self.tui.message_history = max(
                    10, min(self._parser.getint("tui", "message_history", fallback=500), 10000)
                )
                self.tui.alert_sound = self._parser.getboolean("tui", "alert_sound", fallback=True)
                self.tui.space_weather = self._parser.getboolean("tui", "space_weather", fallback=True)

            # MQTT
            if self._parser.has_section("mqtt"):
                self.mqtt.enabled = self._parser.getboolean("mqtt", "enabled", fallback=False)
                self.mqtt.broker = self._parser.get("mqtt", "broker", fallback="mqtt.meshtastic.org")
                self.mqtt.port = self._parser.getint("mqtt", "port", fallback=1883)
                self.mqtt.use_tls = self._parser.getboolean("mqtt", "use_tls", fallback=False)
                self.mqtt.username = self._parser.get("mqtt", "username", fallback="meshdev")
                self.mqtt.password = self._parser.get("mqtt", "password", fallback="large4cats")
                self.mqtt.topic_root = self._parser.get("mqtt", "topic_root", fallback="msh/US")
                self.mqtt.channel = self._parser.get("mqtt", "channel", fallback="LongFast")
                self.mqtt.channels = self._parser.get("mqtt", "channels", fallback=self.mqtt.channel)
                self.mqtt.node_id = self._parser.get("mqtt", "node_id", fallback="")
                self.mqtt.client_id = self._parser.get("mqtt", "client_id", fallback="")
                self.mqtt.encryption_key = self._parser.get("mqtt", "encryption_key", fallback="")
                raw_qos = self._parser.getint("mqtt", "qos", fallback=1)
                self.mqtt.qos = raw_qos if raw_qos in (0, 1, 2) else 1
                self.mqtt.connect_timeout = max(
                    1, min(self._parser.getint("mqtt", "connect_timeout", fallback=10), 300)
                )
                self.mqtt.reconnect_delay = max(
                    1, min(self._parser.getint("mqtt", "reconnect_delay", fallback=5), 3600)
                )
                self.mqtt.max_reconnect_delay = max(
                    self.mqtt.reconnect_delay,
                    min(self._parser.getint("mqtt", "max_reconnect_delay", fallback=300), 86400),
                )
                self.mqtt.max_reconnect_attempts = self._parser.getint("mqtt", "max_reconnect_attempts", fallback=10)

            # Storage
            if self._parser.has_section("storage"):
                self.storage.enabled = self._parser.getboolean("storage", "enabled", fallback=True)
                self.storage.state_file = self._parser.get("storage", "state_file", fallback="")
                self.storage.auto_save_interval = max(
                    0, min(self._parser.getint("storage", "auto_save_interval", fallback=300), 86400)
                )
                self.storage.max_message_history = self._parser.getint("storage", "max_message_history", fallback=1000)
                self.storage.max_node_history_days = self._parser.getint(
                    "storage", "max_node_history_days", fallback=30
                )

            # Logging
            if self._parser.has_section("logging"):
                self.logging.enabled = self._parser.getboolean("logging", "enabled", fallback=True)
                self.logging.level = self._parser.get("logging", "level", fallback="INFO").upper()
                self.logging.file = self._parser.get("logging", "file", fallback="mesh_client.log")
                self.logging.max_size_mb = max(1, min(self._parser.getint("logging", "max_size_mb", fallback=10), 1000))
                self.logging.backup_count = max(0, min(self._parser.getint("logging", "backup_count", fallback=3), 100))

            # Apply environment variable overrides (highest priority)
            self._apply_env_overrides()

            return True
        except (configparser.Error, OSError) as e:
            print(f"Error loading config: {e}")
            return False

    # Explicit allowlist of environment variable overrides.
    # Convention: MESHFORGE_SECTION_KEY -> dataclass attribute.
    _ENV_OVERRIDE_MAP: Dict[str, tuple] = {
        # [interface]
        "MESHFORGE_INTERFACE_TYPE": ("interface", "type"),
        "MESHFORGE_INTERFACE_PORT": ("interface", "port"),
        "MESHFORGE_INTERFACE_HOSTNAME": ("interface", "hostname"),
        # [mqtt]
        "MESHFORGE_MQTT_ENABLED": ("mqtt", "enabled"),
        "MESHFORGE_MQTT_BROKER": ("mqtt", "broker"),
        "MESHFORGE_MQTT_PORT": ("mqtt", "port"),
        "MESHFORGE_MQTT_USERNAME": ("mqtt", "username"),
        "MESHFORGE_MQTT_PASSWORD": ("mqtt", "password"),
        "MESHFORGE_MQTT_TOPIC_ROOT": ("mqtt", "topic_root"),
        "MESHFORGE_MQTT_CHANNEL": ("mqtt", "channel"),
        "MESHFORGE_MQTT_ENCRYPTION_KEY": ("mqtt", "encryption_key"),
        # [web]
        "MESHFORGE_WEB_HOST": ("web", "host"),
        "MESHFORGE_WEB_PORT": ("web", "port"),
        "MESHFORGE_WEB_API_KEY": ("web", "api_key"),
        "MESHFORGE_WEB_CORS_ORIGINS": ("web", "cors_origins"),
        # [tui]
        "MESHFORGE_TUI_REFRESH_RATE": ("tui", "refresh_rate"),
        # [logging]
        "MESHFORGE_LOGGING_LEVEL": ("logging", "level"),
        "MESHFORGE_LOGGING_FILE": ("logging", "file"),
    }

    def _apply_env_overrides(self) -> None:
        """Apply MESHFORGE_* environment variable overrides to config.

        Env vars take highest priority, overriding both INI file values and defaults.
        Uses an explicit allowlist for safety and predictability.
        """
        section_map = {
            "interface": self.interface,
            "mqtt": self.mqtt,
            "web": self.web,
            "tui": self.tui,
            "storage": self.storage,
            "logging": self.logging,
        }
        for env_var, (section_name, field_name) in self._ENV_OVERRIDE_MAP.items():
            value = os.environ.get(env_var)
            if value is None:
                continue

            target = section_map.get(section_name)
            if target is None or not hasattr(target, field_name):
                continue

            current = getattr(target, field_name)
            try:
                if isinstance(current, bool):
                    setattr(target, field_name, _str_to_bool(value))
                elif isinstance(current, int):
                    setattr(target, field_name, int(value))
                elif isinstance(current, float):
                    setattr(target, field_name, float(value))
                else:
                    setattr(target, field_name, value)
            except (ValueError, TypeError):
                pass  # Skip invalid env var values silently

    def save(self) -> bool:
        """Save configuration to file.

        Saves all interfaces using [interface.1], [interface.2], etc. format.
        """
        try:
            # Ensure directory exists
            if self.config_path:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Remove old interface sections first
            for section in list(self._parser.sections()):
                if section.startswith("interface"):
                    self._parser.remove_section(section)

            # Save all interfaces
            for i, iface in enumerate(self._interfaces, 1):
                section = f"interface.{i}"
                self._parser.add_section(section)
                self._parser.set(section, "enabled", str(iface.enabled))
                self._parser.set(section, "type", iface.type)
                self._parser.set(section, "port", iface.port)
                self._parser.set(section, "hostname", iface.hostname)
                self._parser.set(section, "mac", iface.mac)
                self._parser.set(section, "baudrate", str(iface.baudrate))
                self._parser.set(section, "http_url", iface.http_url)

            # General
            if not self._parser.has_section("general"):
                self._parser.add_section("general")
            self._parser.set("general", "bot_name", self.bot_name)
            self._parser.set("general", "bbs_admin_list", ",".join(self.admin_nodes))
            self._parser.set("general", "favoriteNodeList", ",".join(self.favorite_nodes))

            # Alerts
            if not self._parser.has_section("emergencyHandler"):
                self._parser.add_section("emergencyHandler")
            self._parser.set("emergencyHandler", "enabled", str(self.alerts.enabled))
            self._parser.set("emergencyHandler", "emergency_keywords", ",".join(self.alerts.emergency_keywords))
            self._parser.set("emergencyHandler", "alert_channel", str(self.alerts.alert_channel))
            self._parser.set("emergencyHandler", "play_sound", str(self.alerts.play_sound))
            self._parser.set("emergencyHandler", "cooldown_period", str(self.alerts.cooldown_period))

            # Web
            if not self._parser.has_section("web"):
                self._parser.add_section("web")
            self._parser.set("web", "host", self.web.host)
            self._parser.set("web", "port", str(self.web.port))
            self._parser.set("web", "debug", str(self.web.debug))
            self._parser.set("web", "api_key", self.web.api_key)
            self._parser.set("web", "enable_auth", str(self.web.enable_auth))
            self._parser.set("web", "username", self.web.username)
            self._parser.set("web", "trust_proxy", str(self.web.trust_proxy))
            self._parser.set("web", "cors_origins", self.web.cors_origins)

            # TUI
            if not self._parser.has_section("tui"):
                self._parser.add_section("tui")
            self._parser.set("tui", "refresh_rate", str(self.tui.refresh_rate))
            self._parser.set("tui", "color_scheme", self.tui.color_scheme)
            self._parser.set("tui", "show_timestamps", str(self.tui.show_timestamps))
            self._parser.set("tui", "message_history", str(self.tui.message_history))
            self._parser.set("tui", "alert_sound", str(self.tui.alert_sound))
            self._parser.set("tui", "space_weather", str(self.tui.space_weather))

            # MQTT
            if not self._parser.has_section("mqtt"):
                self._parser.add_section("mqtt")
            self._parser.set("mqtt", "enabled", str(self.mqtt.enabled))
            self._parser.set("mqtt", "broker", self.mqtt.broker)
            self._parser.set("mqtt", "port", str(self.mqtt.port))
            self._parser.set("mqtt", "use_tls", str(self.mqtt.use_tls))
            self._parser.set("mqtt", "username", self.mqtt.username)
            self._parser.set("mqtt", "password", self.mqtt.password)
            self._parser.set("mqtt", "topic_root", self.mqtt.topic_root)
            self._parser.set("mqtt", "channel", self.mqtt.channel)
            self._parser.set("mqtt", "channels", self.mqtt.channels)
            self._parser.set("mqtt", "node_id", self.mqtt.node_id)
            self._parser.set("mqtt", "client_id", self.mqtt.client_id)
            self._parser.set("mqtt", "encryption_key", self.mqtt.encryption_key)
            self._parser.set("mqtt", "qos", str(self.mqtt.qos))
            self._parser.set("mqtt", "connect_timeout", str(self.mqtt.connect_timeout))
            self._parser.set("mqtt", "reconnect_delay", str(self.mqtt.reconnect_delay))
            self._parser.set("mqtt", "max_reconnect_delay", str(self.mqtt.max_reconnect_delay))
            self._parser.set("mqtt", "max_reconnect_attempts", str(self.mqtt.max_reconnect_attempts))

            # Storage
            if not self._parser.has_section("storage"):
                self._parser.add_section("storage")
            self._parser.set("storage", "enabled", str(self.storage.enabled))
            self._parser.set("storage", "state_file", self.storage.state_file)
            self._parser.set("storage", "auto_save_interval", str(self.storage.auto_save_interval))
            self._parser.set("storage", "max_message_history", str(self.storage.max_message_history))
            self._parser.set("storage", "max_node_history_days", str(self.storage.max_node_history_days))

            # Logging
            if not self._parser.has_section("logging"):
                self._parser.add_section("logging")
            self._parser.set("logging", "enabled", str(self.logging.enabled))
            self._parser.set("logging", "level", self.logging.level)
            self._parser.set("logging", "file", self.logging.file)
            self._parser.set("logging", "max_size_mb", str(self.logging.max_size_mb))
            self._parser.set("logging", "backup_count", str(self.logging.backup_count))

            if self.config_path:
                with open(self.config_path, "w") as f:
                    self._parser.write(f)
                # Restrict permissions — config may contain credentials
                os.chmod(self.config_path, 0o600)

            return True
        except (configparser.Error, OSError) as e:
            print(f"Error saving config: {e}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "config_format": self.config_format,
            "interfaces": [
                {
                    "enabled": iface.enabled,
                    "type": iface.type,
                    "port": iface.port,
                    "hostname": iface.hostname,
                    "mac": iface.mac,
                    "baudrate": iface.baudrate,
                    "http_url": iface.http_url,
                }
                for iface in self._interfaces
            ],
            # Backward compatibility: include primary interface
            "interface": {
                "type": self.interface.type,
                "port": self.interface.port,
                "hostname": self.interface.hostname,
                "mac": self.interface.mac,
                "baudrate": self.interface.baudrate,
                "http_url": self.interface.http_url,
            },
            "general": {
                "bot_name": self.bot_name,
                "admin_nodes": self.admin_nodes,
                "favorite_nodes": self.favorite_nodes,
            },
            "alerts": {
                "enabled": self.alerts.enabled,
                "emergency_keywords": self.alerts.emergency_keywords,
                "alert_channel": self.alerts.alert_channel,
                "play_sound": self.alerts.play_sound,
                "cooldown_period": self.alerts.cooldown_period,
            },
            "web": {
                "host": self.web.host,
                "port": self.web.port,
                "debug": self.web.debug,
                "enable_auth": self.web.enable_auth,
                "cors_origins": self.web.cors_origins,
            },
            "tui": {
                "refresh_rate": self.tui.refresh_rate,
                "color_scheme": self.tui.color_scheme,
                "show_timestamps": self.tui.show_timestamps,
                "message_history": self.tui.message_history,
                "alert_sound": self.tui.alert_sound,
                "space_weather": self.tui.space_weather,
            },
            "mqtt": {
                "enabled": self.mqtt.enabled,
                "broker": self.mqtt.broker,
                "port": self.mqtt.port,
                "use_tls": self.mqtt.use_tls,
                "topic_root": self.mqtt.topic_root,
                "channel": self.mqtt.channel,
                "node_id": self.mqtt.node_id,
                "qos": self.mqtt.qos,
            },
            "logging": {
                "enabled": self.logging.enabled,
                "level": self.logging.level,
                "file": self.logging.file,
                "max_size_mb": self.logging.max_size_mb,
                "backup_count": self.logging.backup_count,
            },
        }

    @classmethod
    def from_upstream(cls, path: str) -> "Config":
        """Load configuration from upstream meshing-around config.ini."""
        config = cls(config_path=path)
        config.config_format = "upstream"
        return config

    def find_upstream_config(self) -> Optional[Path]:
        """Find upstream meshing-around config file."""
        for path in self.UPSTREAM_CONFIG_PATHS:
            if path.exists():
                return path
        return None

    def _validate_mqtt(self, issues: List[str]) -> None:
        """Validate MQTT configuration, appending any issues found."""
        if not self.mqtt.enabled:
            return

        if not self.mqtt.broker:
            issues.append("MQTT enabled but no broker configured")
        if self.mqtt.port < 1 or self.mqtt.port > 65535:
            issues.append(f"MQTT port {self.mqtt.port} out of valid range (1-65535)")
        if not self.mqtt.topic_root:
            issues.append("MQTT enabled but no topic_root configured")

        # TLS consistency check
        is_default_creds = self.mqtt.username == "meshdev" and self.mqtt.password == "large4cats"
        if not is_default_creds and not self.mqtt.use_tls and self.mqtt.port != 8883:
            issues.append("Non-default MQTT credentials configured without TLS — credentials sent in cleartext")

        # Broker DNS check (with timeout)
        if self.mqtt.broker:
            import socket

            try:
                socket.getaddrinfo(self.mqtt.broker, self.mqtt.port, socket.AF_UNSPEC, socket.SOCK_STREAM)
            except socket.gaierror:
                issues.append(f"MQTT broker {self.mqtt.broker!r} cannot be resolved (DNS lookup failed)")

    def validate(self) -> List[str]:
        """Validate configuration and return list of issues (empty = valid).

        Checks port ranges, hostname formats, MQTT broker reachability,
        TLS consistency, and auth credential presence.
        """
        issues: List[str] = []

        # Interface validation
        valid_types = ("serial", "tcp", "http", "ble", "mqtt")
        iface = self.interface
        if iface.type not in valid_types:
            issues.append(f"Unknown interface type: {iface.type!r} (expected one of {valid_types})")
        if iface.type == "tcp" and not iface.hostname:
            issues.append("TCP interface selected but no hostname configured")
        if iface.type == "http" and not iface.http_url and not iface.hostname:
            issues.append("HTTP interface selected but no http_url or hostname configured")
        if iface.type == "ble" and not iface.mac:
            issues.append("BLE interface selected but no MAC address configured")

        # MQTT validation
        self._validate_mqtt(issues)

        # Web validation
        if self.web.port < 1 or self.web.port > 65535:
            issues.append(f"Web port {self.web.port} out of valid range (1-65535)")
        if self.web.enable_auth and not self.web.api_key and not self.web.password_hash:
            issues.append("Web auth enabled but no api_key or password_hash configured")
        if self.web.cors_origins == "*" and not self.web.enable_auth:
            issues.append(
                "CORS allows all origins (*) without authentication — " "consider restricting origins or enabling auth"
            )

        return issues

    def get_state_file_path(self) -> Path:
        """Get path for network state persistence file."""
        if self.storage.state_file:
            return Path(self.storage.state_file)
        # Default: ~/.config/meshing-around-clients/network_state.json
        return Path.home() / ".config" / "meshing-around-clients" / "network_state.json"

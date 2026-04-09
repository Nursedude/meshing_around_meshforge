"""
Configuration management for Meshing-Around Clients.
Handles loading and saving client configuration.
"""

import configparser
import logging
import os
import pathlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_user_home() -> Path:
    """Return the real user's home directory, even under sudo.

    When running with ``sudo``, ``Path.home()`` returns ``/root`` instead of
    the invoking user's home.  This checks ``SUDO_USER`` first (MF001).
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return pathlib.Path(f"/home/{sudo_user}")
    return pathlib.Path.home()


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
            "sos",
            "mayday",
        ]
    )
    alert_channel: int = 2
    play_sound: bool = False
    sound_file: str = ""
    cooldown_period: int = 300
    log_to_file: bool = False
    log_file: str = ""


@dataclass
class CommandConfig:
    """Bot command configuration for mesh command responses."""

    enabled: bool = True
    # Whether to auto-respond to commands received from the mesh
    auto_respond: bool = False
    # Recognized command prefixes (messages starting with these are commands, not emergencies)
    commands: List[str] = field(
        default_factory=lambda: [
            "cmd",
            "help",
            "ping",
            "info",
            "nodes",
            "status",
            "version",
            "uptime",
        ]
    )


@dataclass
class DataSourceEntry:
    """A single external data source tied to a command keyword."""

    name: str = ""
    enabled: bool = False
    url: str = ""
    command: str = ""  # The command keyword that triggers this source
    station: str = ""  # Station/location code (e.g., NOAA station ID)
    zone: str = ""  # Zone code (e.g., NOAA weather zone)
    region: str = ""  # Region identifier
    api_key: str = ""  # Optional API key
    lat: float = 0.0  # Latitude for proximity filtering
    lon: float = 0.0  # Longitude for proximity filtering


@dataclass
class DataSourceConfig:
    """External data source configuration for command responses.

    Each source maps a command keyword to an external URL that provides
    live data. Sources are configured in the [data_sources] INI section
    with user-specific codes (station IDs, zones, API keys).
    """

    weather_enabled: bool = False
    weather_station: str = ""
    weather_zone: str = ""
    weather_url: str = "https://api.weather.gov"

    tsunami_enabled: bool = False
    tsunami_url: str = "https://www.tsunami.gov/events/xml/PAAQAtom.xml"
    tsunami_region: str = ""

    volcano_enabled: bool = False
    volcano_url: str = "https://volcanoes.usgs.gov/hans-public/api/volcano/getCapElevated"
    volcano_lat: float = 0.0
    volcano_lon: float = 0.0

    def get_enabled_sources(self) -> Dict[str, "DataSourceEntry"]:
        """Return a dict of command_name -> DataSourceEntry for enabled sources."""
        sources: Dict[str, DataSourceEntry] = {}
        if self.weather_enabled and self.weather_station:
            sources["weather"] = DataSourceEntry(
                name="NOAA Weather",
                enabled=True,
                url=self.weather_url,
                command="weather",
                station=self.weather_station,
                zone=self.weather_zone,
            )
        if self.tsunami_enabled:
            sources["tsunami"] = DataSourceEntry(
                name="Tsunami Warning Center",
                enabled=True,
                url=self.tsunami_url,
                command="tsunami",
                region=self.tsunami_region,
            )
        if self.volcano_enabled:
            sources["volcano"] = DataSourceEntry(
                name="USGS Volcano Alerts",
                enabled=True,
                url=self.volcano_url,
                command="volcano",
                lat=self.volcano_lat,
                lon=self.volcano_lon,
            )
        return sources


@dataclass
class NetworkConfig:
    """Network behavior configuration."""

    default_channel: int = 0
    monitored_channels: List[int] = field(default_factory=lambda: [0, 1, 2])
    message_history: int = 500
    max_message_length: int = 200


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
class MapsConfig:
    """meshforge-maps server connection (local or remote)."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8808

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


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
    file: str = "logs/mesh_client.log"
    max_size_mb: int = 10
    backup_count: int = 3


# Public Meshtastic MQTT broker defaults (see meshtastic.org/docs/software/mqtt).
# Defined as named constants so credentials never appear as scattered string literals.
MQTT_PUBLIC_USERNAME: str = "meshdev"
MQTT_PUBLIC_PASSWORD: str = "large4cats"


@dataclass
class MQTTConfig:
    """MQTT connection configuration for radio-less operation."""

    enabled: bool = False
    broker: str = "mqtt.meshtastic.org"
    port: int = 1883
    use_tls: bool = False
    # Public credentials for mqtt.meshtastic.org — see constants above.
    username: str = MQTT_PUBLIC_USERNAME
    password: str = MQTT_PUBLIC_PASSWORD
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MQTTConfig":
        """Create from dictionary, handling string-to-type conversion.

        Used by config_schema.ConfigLoader to parse INI section data.
        """
        return cls(
            enabled=_str_to_bool(data.get("enabled", False)),
            broker=str(data.get("broker", "mqtt.meshtastic.org")),
            port=int(data.get("port", 1883)),
            use_tls=_str_to_bool(data.get("use_tls", False)),
            username=str(data.get("username", MQTT_PUBLIC_USERNAME)),
            password=str(data.get("password", MQTT_PUBLIC_PASSWORD)),
            topic_root=str(data.get("topic_root", "msh/US")),
            channel=str(data.get("channel", "LongFast")),
            channels=str(data.get("channels", data.get("channel", "LongFast"))),
            node_id=str(data.get("node_id", "")),
            client_id=str(data.get("client_id", "")),
            encryption_key=str(data.get("encryption_key", "")),
            qos=int(data.get("qos", 1)),
            connect_timeout=int(data.get("connect_timeout", 10)),
            reconnect_delay=int(data.get("reconnect_delay", 5)),
            max_reconnect_delay=int(data.get("max_reconnect_delay", 300)),
            max_reconnect_attempts=int(data.get("max_reconnect_attempts", 10)),
        )


class Config:
    """Main configuration class for Meshing-Around Clients.

    Supports multiple interfaces (up to 9) for compatibility with upstream
    meshing-around config format. The `interface` property returns the first
    enabled interface for backward compatibility.
    """

    @staticmethod
    def _get_default_config_paths() -> "List[Path]":
        """Build client config search paths at call time (not import time)."""
        return [
            get_user_home() / ".config" / "meshing-around-clients" / "config.ini",
            Path.cwd() / "client_config.ini",
            Path.cwd() / "mesh_client.ini",
            Path("/etc/meshing-around-clients/config.ini"),
        ]

    @staticmethod
    def _get_upstream_config_paths() -> "List[Path]":
        """Build upstream config search paths at call time (not import time).

        Evaluates get_user_home() and Path.cwd() fresh each call so they
        reflect the actual runtime environment.
        """
        return [
            Path("/opt/meshing-around/config.ini"),
            get_user_home() / "meshing-around" / "config.ini",
            Path.cwd() / "config.ini",
        ]

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else self._find_config()
        self._parser = configparser.ConfigParser()

        # Multi-interface support (up to 9)
        self._interfaces: List[InterfaceConfig] = [InterfaceConfig()]

        # Configuration sections
        self.alerts = AlertConfig()
        self.commands = CommandConfig()
        self.data_sources = DataSourceConfig()
        self.network_cfg = NetworkConfig()
        self.tui = TuiConfig()
        self.mqtt = MQTTConfig()
        self.storage = StorageConfig()
        self.maps = MapsConfig()
        self.logging = LoggingConfig()

        # Bot connection info
        self.bot_name = "MeshBot"
        self.admin_nodes: List[str] = []
        self.favorite_nodes: List[str] = []

        # Advanced settings
        self.chunk_reassembly_timeout: float = 8.0  # seconds; 0 disables

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
        for path in self._get_default_config_paths():
            if path.exists():
                return path
        # Check upstream paths
        for path in self._get_upstream_config_paths():
            if path.exists():
                return path
        return self._get_default_config_paths()[0]  # Default path for new config

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

            # Alerts — support both [alerts] (meshforge default) and
            # [emergencyHandler] (upstream meshing-around format)
            alerts_section = None
            if self._parser.has_section("alerts"):
                alerts_section = "alerts"
            elif self._parser.has_section("emergencyHandler"):
                alerts_section = "emergencyHandler"

            if alerts_section:
                self.alerts.enabled = self._parser.getboolean(alerts_section, "enabled", fallback=True)
                keywords_str = self._parser.get(alerts_section, "emergency_keywords", fallback="")
                if keywords_str:
                    self.alerts.emergency_keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
                self.alerts.alert_channel = self._parser.getint(alerts_section, "alert_channel", fallback=2)
                self.alerts.play_sound = self._parser.getboolean(alerts_section, "play_sound", fallback=False)
                self.alerts.sound_file = self._parser.get(alerts_section, "sound_file", fallback="")
                self.alerts.cooldown_period = self._parser.getint(alerts_section, "cooldown_period", fallback=300)
                self.alerts.log_to_file = self._parser.getboolean(alerts_section, "log_to_file", fallback=False)
                self.alerts.log_file = self._parser.get(alerts_section, "log_file", fallback="")

            # Commands
            if self._parser.has_section("commands"):
                self.commands.enabled = self._parser.getboolean("commands", "enabled", fallback=True)
                self.commands.auto_respond = self._parser.getboolean("commands", "auto_respond", fallback=False)
                cmds_str = self._parser.get("commands", "commands", fallback="")
                if cmds_str:
                    self.commands.commands = [c.strip() for c in cmds_str.split(",") if c.strip()]

            # Data Sources
            if self._parser.has_section("data_sources"):
                ds = self.data_sources
                ds.weather_enabled = self._parser.getboolean("data_sources", "weather_enabled", fallback=False)
                ds.weather_station = self._parser.get("data_sources", "weather_station", fallback="")
                ds.weather_zone = self._parser.get("data_sources", "weather_zone", fallback="")
                ds.weather_url = self._parser.get("data_sources", "weather_url", fallback=ds.weather_url)
                ds.tsunami_enabled = self._parser.getboolean("data_sources", "tsunami_enabled", fallback=False)
                ds.tsunami_url = self._parser.get("data_sources", "tsunami_url", fallback=ds.tsunami_url)
                ds.tsunami_region = self._parser.get("data_sources", "tsunami_region", fallback="")
                ds.volcano_enabled = self._parser.getboolean("data_sources", "volcano_enabled", fallback=False)
                ds.volcano_url = self._parser.get("data_sources", "volcano_url", fallback=ds.volcano_url)
                ds.volcano_lat = self._parser.getfloat("data_sources", "volcano_lat", fallback=0.0)
                ds.volcano_lon = self._parser.getfloat("data_sources", "volcano_lon", fallback=0.0)

            # Network
            if self._parser.has_section("network"):
                self.network_cfg.default_channel = self._parser.getint(
                    "network", "default_channel", fallback=0
                )
                mc_str = self._parser.get("network", "monitored_channels", fallback="")
                if mc_str:
                    self.network_cfg.monitored_channels = [
                        int(c.strip()) for c in mc_str.split(",") if c.strip().isdigit()
                    ]
                self.network_cfg.message_history = self._parser.getint(
                    "network", "message_history", fallback=500
                )
                self.network_cfg.max_message_length = self._parser.getint(
                    "network", "max_message_length", fallback=200
                )

            # NOTE: default_channel is USER-configured, not auto-synced from
            # upstream bot. The bot's defaultchannel + ignoredefaultchannel
            # means the bot may IGNORE commands on its default channel.
            # Users set their channel in mesh_client.ini [network] section.

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

            # Maps (meshforge-maps server)
            if self._parser.has_section("maps"):
                self.maps.enabled = self._parser.getboolean("maps", "enabled", fallback=True)
                self.maps.host = self._parser.get("maps", "host", fallback="127.0.0.1")
                self.maps.port = self._parser.getint("maps", "port", fallback=8808)

            # MQTT
            if self._parser.has_section("mqtt"):
                self.mqtt.enabled = self._parser.getboolean("mqtt", "enabled", fallback=False)
                self.mqtt.broker = self._parser.get("mqtt", "broker", fallback="mqtt.meshtastic.org")
                self.mqtt.port = self._parser.getint("mqtt", "port", fallback=1883)
                # Parse embedded port from broker (e.g. "host:1884")
                if ":" in self.mqtt.broker:
                    _parts = self.mqtt.broker.rsplit(":", 1)
                    try:
                        self.mqtt.port = int(_parts[1])
                        self.mqtt.broker = _parts[0]
                    except ValueError:
                        pass  # Not a port number, keep as-is
                self.mqtt.use_tls = self._parser.getboolean("mqtt", "use_tls", fallback=False)
                self.mqtt.username = self._parser.get("mqtt", "username", fallback=MQTT_PUBLIC_USERNAME)
                self.mqtt.password = self._parser.get("mqtt", "password", fallback=MQTT_PUBLIC_PASSWORD)
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

            # Advanced
            if self._parser.has_section("advanced"):
                self.chunk_reassembly_timeout = max(
                    0.0, self._parser.getfloat("advanced", "chunk_reassembly_timeout", fallback=5.0)
                )

            # Fall back to bot's config.ini for shared settings
            self._load_upstream_interface_fallback()
            self._load_upstream_channel_fallback()

            # Apply environment variable overrides (highest priority)
            self._apply_env_overrides()

            return True
        except (configparser.Error, OSError) as e:
            print(f"Error loading config: {e}")
            return False

    def _load_upstream_interface_fallback(self) -> None:
        """Fall back to bot's config.ini for interface settings if not configured.

        If mesh_client.ini has default interface (type=auto, no hostname/port),
        read from the bot's config.ini instead. This avoids config drift.
        """
        iface = self.interface
        # Only fall back if mesh_client.ini has default/empty settings
        if iface.type != "auto" or iface.hostname or iface.port:
            return  # User explicitly configured mesh_client.ini

        upstream_path = self.find_upstream_config()
        if not upstream_path:
            return

        upstream = configparser.ConfigParser()
        try:
            upstream.read(str(upstream_path))
        except configparser.Error:
            return

        if not upstream.has_section("interface"):
            return

        up_type = upstream.get("interface", "type", fallback="serial")
        up_host = upstream.get("interface", "hostname", fallback="")
        up_port = upstream.get("interface", "port", fallback="")
        up_mac = upstream.get("interface", "mac", fallback="")

        if up_type != "serial" or up_host or up_port:
            iface.type = up_type
            iface.hostname = up_host
            iface.port = up_port
            iface.mac = up_mac
            logger.info("Interface from bot config.ini: type=%s host=%s", up_type, up_host)

    def _load_upstream_channel_fallback(self) -> None:
        """Use bot's defaultchannel if client default_channel is 0 (unset)."""
        if self.network_cfg.default_channel != 0:
            return  # User explicitly set a channel

        try:
            upstream_settings = self.read_upstream_settings()
        except Exception as e:
            logger.debug("Failed to read upstream settings for channel fallback: %s", e)
            return
        if not upstream_settings:
            return

        bot_channel = upstream_settings.get("defaultchannel")
        if bot_channel is not None and bot_channel != 0:
            self.network_cfg.default_channel = int(bot_channel)
            logger.info("default_channel from bot config.ini: %d", bot_channel)

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
        "MESHFORGE_MQTT_USE_TLS": ("mqtt", "use_tls"),
        "MESHFORGE_MQTT_USERNAME": ("mqtt", "username"),
        "MESHFORGE_MQTT_PASSWORD": ("mqtt", "password"),
        "MESHFORGE_MQTT_TOPIC_ROOT": ("mqtt", "topic_root"),
        "MESHFORGE_MQTT_CHANNEL": ("mqtt", "channel"),
        "MESHFORGE_MQTT_ENCRYPTION_KEY": ("mqtt", "encryption_key"),
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

            # Alerts — save to whichever section name exists, default [alerts]
            if self._parser.has_section("emergencyHandler"):
                _alert_sec = "emergencyHandler"
            else:
                _alert_sec = "alerts"
                if not self._parser.has_section(_alert_sec):
                    self._parser.add_section(_alert_sec)
            self._parser.set(_alert_sec, "enabled", str(self.alerts.enabled))
            self._parser.set(_alert_sec, "emergency_keywords", ",".join(self.alerts.emergency_keywords))
            self._parser.set(_alert_sec, "alert_channel", str(self.alerts.alert_channel))
            self._parser.set(_alert_sec, "play_sound", str(self.alerts.play_sound))
            self._parser.set(_alert_sec, "sound_file", self.alerts.sound_file)
            self._parser.set(_alert_sec, "cooldown_period", str(self.alerts.cooldown_period))
            self._parser.set(_alert_sec, "log_to_file", str(self.alerts.log_to_file))
            self._parser.set(_alert_sec, "log_file", self.alerts.log_file)

            # Commands
            if not self._parser.has_section("commands"):
                self._parser.add_section("commands")
            self._parser.set("commands", "enabled", str(self.commands.enabled))
            self._parser.set("commands", "auto_respond", str(self.commands.auto_respond))
            self._parser.set("commands", "commands", ",".join(self.commands.commands))

            # Data Sources
            if not self._parser.has_section("data_sources"):
                self._parser.add_section("data_sources")
            ds = self.data_sources
            self._parser.set("data_sources", "weather_enabled", str(ds.weather_enabled))
            self._parser.set("data_sources", "weather_station", ds.weather_station)
            self._parser.set("data_sources", "weather_zone", ds.weather_zone)
            self._parser.set("data_sources", "weather_url", ds.weather_url)
            self._parser.set("data_sources", "tsunami_enabled", str(ds.tsunami_enabled))
            self._parser.set("data_sources", "tsunami_url", ds.tsunami_url)
            self._parser.set("data_sources", "tsunami_region", ds.tsunami_region)
            self._parser.set("data_sources", "volcano_enabled", str(ds.volcano_enabled))
            self._parser.set("data_sources", "volcano_url", ds.volcano_url)
            self._parser.set("data_sources", "volcano_lat", str(ds.volcano_lat))
            self._parser.set("data_sources", "volcano_lon", str(ds.volcano_lon))

            # TUI
            if not self._parser.has_section("tui"):
                self._parser.add_section("tui")
            self._parser.set("tui", "refresh_rate", str(self.tui.refresh_rate))
            self._parser.set("tui", "color_scheme", self.tui.color_scheme)
            self._parser.set("tui", "show_timestamps", str(self.tui.show_timestamps))
            self._parser.set("tui", "message_history", str(self.tui.message_history))
            self._parser.set("tui", "alert_sound", str(self.tui.alert_sound))
            self._parser.set("tui", "space_weather", str(self.tui.space_weather))

            # Maps
            if not self._parser.has_section("maps"):
                self._parser.add_section("maps")
            self._parser.set("maps", "enabled", str(self.maps.enabled))
            self._parser.set("maps", "host", self.maps.host)
            self._parser.set("maps", "port", str(self.maps.port))

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
                # Atomic open with restricted permissions (TOCTOU-safe)
                fd = os.open(str(self.config_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    self._parser.write(f)

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
                "sound_file": self.alerts.sound_file,
                "cooldown_period": self.alerts.cooldown_period,
                "log_to_file": self.alerts.log_to_file,
                "log_file": self.alerts.log_file,
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
        # Hardcoded primary check — most common install location
        primary = Path("/opt/meshing-around/config.ini")
        try:
            if primary.exists():
                logger.debug("Upstream config found at primary path: %s", primary)
                return primary
        except Exception as e:
            logger.debug("Upstream config check failed for %s: %s", primary, e)

        # Dynamic path search
        try:
            paths = self._get_upstream_config_paths()
        except Exception as e:
            logger.debug("Failed to get upstream config paths: %s", e)
            paths = [primary]
        for path in paths:
            try:
                if path.exists():
                    logger.debug("Upstream config found: %s", path)
                    return path
                logger.debug("Upstream config not at: %s", path)
            except (OSError, PermissionError) as e:
                logger.debug("Upstream config check failed for %s: %s", path, e)
        logger.debug("No upstream config found in %d paths", len(paths))
        return None

    def get_upstream_template_path(self) -> Optional[Path]:
        """Find config.template in upstream paths (fallback when config.ini missing)."""
        # Hardcoded primary check
        primary = Path("/opt/meshing-around/config.template")
        try:
            if primary.exists():
                return primary
        except Exception as e:
            logger.debug("Template check failed for %s: %s", primary, e)

        for path in self._get_upstream_config_paths():
            template_path = path.with_name("config.template")
            try:
                if template_path.exists():
                    return template_path
            except (OSError, PermissionError):
                continue
        return None

    def get_client_template_path(self) -> Optional[Path]:
        """Find the mesh_client.ini.template file (canonical client template).

        Searches next to the loaded config, then in the project root.
        """
        # Same directory as loaded config
        if self.config_path:
            template = self.config_path.with_name("mesh_client.ini.template")
            try:
                if template.exists():
                    return template
            except (OSError, PermissionError):
                pass
        # Project root (relative to this source file)
        project_root = Path(__file__).resolve().parent.parent.parent
        template = project_root / "mesh_client.ini.template"
        try:
            if template.exists():
                return template
        except (OSError, PermissionError):
            pass
        return None

    def find_client_profiles(self) -> "List[tuple]":
        """Find client regional profiles (not *_bot.ini) in the profiles directory.

        Returns list of (name, Path) tuples.
        """
        profiles_dir = Path(__file__).resolve().parent.parent.parent / "profiles"
        profiles: list = []
        try:
            if not profiles_dir.is_dir():
                return profiles
            for p in sorted(profiles_dir.glob("*.ini")):
                if p.name.endswith("_bot.ini"):
                    continue  # Bot profiles are separate
                parser = configparser.ConfigParser()
                try:
                    parser.read(str(p))
                    name = parser.get("profile", "name", fallback=p.stem)
                except configparser.Error:
                    name = p.stem
                profiles.append((name, p))
        except (OSError, PermissionError):
            pass
        return profiles

    def read_upstream_commands(self) -> Dict[str, bool]:
        """Read upstream meshing-around config to discover enabled bot commands.

        Returns a dict of command_display_name -> enabled status.
        Read-only — never modifies the upstream config.
        """
        upstream_path = self.find_upstream_config()
        logger.debug("read_upstream_commands: upstream_path=%s", upstream_path)
        if not upstream_path or not upstream_path.exists():
            return {}

        parser = configparser.ConfigParser()
        try:
            parser.read(str(upstream_path))
        except configparser.Error:
            return {}

        features: Dict[str, bool] = {}

        # [general] section feature flags → display names
        if parser.has_section("general"):
            general_map = {
                "dadjokes": "joke",
                "spaceweather": "solar",
                "rssenable": "rss",
                "wikipedia": "wiki",
                "ollama": "llm",
                "whoami": "whoami",
                "storeforward": "store-fwd",
                "enableecho": "echo",
            }
            for key, cmd in general_map.items():
                if parser.has_option("general", key):
                    features[cmd] = parser.getboolean("general", key, fallback=False)

        # [location] section
        if parser.has_section("location"):
            features["location"] = parser.getboolean("location", "enabled", fallback=False)
            if parser.getboolean("location", "ipawsalertenabled", fallback=False):
                features["iPAWS"] = True
            if parser.getboolean("location", "volcanoalertbroadcastenabled", fallback=False):
                features["valert"] = True

        # [bbs] section
        if parser.has_section("bbs"):
            features["bbs"] = parser.getboolean("bbs", "enabled", fallback=False)

        # [sentry] section
        if parser.has_section("sentry"):
            features["sentry"] = parser.getboolean("sentry", "sentryenabled", fallback=False)

        # [emergencyHandler] section
        if parser.has_section("emergencyHandler"):
            features["emergency"] = parser.getboolean("emergencyHandler", "enabled", fallback=False)

        # [scheduler] section
        if parser.has_section("scheduler"):
            features["scheduler"] = parser.getboolean("scheduler", "enabled", fallback=False)

        # [radioMon] section
        if parser.has_section("radioMon"):
            features["radioMon"] = parser.getboolean("radioMon", "enabled", fallback=False)
            if parser.getboolean("radioMon", "dxspotter_enabled", fallback=False):
                features["dxspotter"] = True

        logger.debug("read_upstream_commands: found %d features", len(features))
        return features

    def read_upstream_settings(self) -> Dict[str, Any]:
        """Read location and channel settings from upstream meshing-around config.

        Returns a dict with lat, lon, defaultchannel, and other useful settings.
        Read-only — never modifies the upstream config.
        """
        upstream_path = self.find_upstream_config()
        if not upstream_path or not upstream_path.exists():
            return {}

        parser = configparser.ConfigParser()
        try:
            parser.read(str(upstream_path))
        except configparser.Error:
            return {}

        settings: Dict[str, Any] = {}

        if parser.has_section("location"):
            settings["lat"] = parser.getfloat("location", "lat", fallback=0.0)
            settings["lon"] = parser.getfloat("location", "lon", fallback=0.0)
            settings["usemetric"] = parser.getboolean("location", "usemetric", fallback=False)
            settings["noaaforecastduration"] = parser.getint("location", "noaaforecastduration", fallback=3)
            settings["myfipslist"] = parser.get("location", "myfipslist", fallback="")

        if parser.has_section("general"):
            settings["defaultchannel"] = parser.getint("general", "defaultchannel", fallback=0)

        return settings

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

        # Wildcard subscription on non-local broker
        if self.mqtt.channels.strip() == "*":
            is_local = self.mqtt.broker in ("localhost", "127.0.0.1", "::1")
            if not is_local:
                issues.append(
                    "MQTT channels = * (wildcard subscription) is intended for local brokers only. "
                    "On public brokers, specify channel names explicitly to limit noise."
                )

        # TLS consistency check
        is_default_creds = self.mqtt.username == MQTT_PUBLIC_USERNAME and self.mqtt.password == MQTT_PUBLIC_PASSWORD
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

        return issues

    def get_state_file_path(self) -> Path:
        """Get path for network state persistence file."""
        if self.storage.state_file:
            return Path(self.storage.state_file)
        # Default: ~/.config/meshing-around-clients/network_state.json
        return get_user_home() / ".config" / "meshing-around-clients" / "network_state.json"

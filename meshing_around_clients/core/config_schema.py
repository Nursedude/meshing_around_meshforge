"""
Unified Configuration Schema for MeshForge.

This module provides a centralized, type-safe configuration system that:
- Uses dataclasses for validation and type hints
- Maps between upstream meshing-around config.ini and MeshForge formats
- Supports multi-interface configuration (interface1-9)
- Provides defaults aligned with both upstream and MeshForge expectations

Compatible with:
- SpudGunMan/meshing-around config.ini format
- MeshForge config.enhanced.ini format
- MeshForge core/config.py dataclass format
"""

import os
import configparser
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum


class ConnectionType(Enum):
    """Supported connection types."""
    SERIAL = "serial"
    TCP = "tcp"
    BLE = "ble"
    MQTT = "mqtt"
    DEMO = "demo"


class AlertPriority(Enum):
    """Alert priority levels."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# =============================================================================
# Interface Configuration
# =============================================================================

@dataclass
class InterfaceConfig:
    """Single interface connection configuration.

    Compatible with upstream [interface], [interface2], etc. sections.
    """
    enabled: bool = True
    type: ConnectionType = ConnectionType.SERIAL
    port: str = ""  # Auto-detect if empty
    hostname: str = ""  # For TCP: host:port
    mac: str = ""  # For BLE
    baudrate: int = 115200

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InterfaceConfig':
        """Create from dictionary, handling type conversion."""
        conn_type = data.get('type', 'serial')
        if isinstance(conn_type, str):
            try:
                conn_type = ConnectionType(conn_type.lower())
            except ValueError:
                conn_type = ConnectionType.SERIAL

        return cls(
            enabled=_str_to_bool(data.get('enabled', True)),
            type=conn_type,
            port=str(data.get('port', '')),
            hostname=str(data.get('hostname', '')),
            mac=str(data.get('mac', '')),
            baudrate=int(data.get('baudrate', 115200))
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for INI serialization."""
        return {
            'enabled': str(self.enabled),
            'type': self.type.value,
            'port': self.port,
            'hostname': self.hostname,
            'mac': self.mac,
            'baudrate': str(self.baudrate)
        }

    def validate(self) -> List[str]:
        """Validate configuration, return list of errors."""
        errors = []
        if self.type == ConnectionType.BLE and self.mac:
            if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', self.mac):
                errors.append(f"Invalid BLE MAC address format: {self.mac}")
        if self.type == ConnectionType.TCP and not self.hostname:
            errors.append("TCP connection requires hostname")
        return errors


# =============================================================================
# Alert Configurations
# =============================================================================

@dataclass
class EmergencyAlertConfig:
    """Emergency keyword detection configuration.

    Maps to: [emergencyHandler] in both upstream and MeshForge.
    """
    enabled: bool = True
    keywords: List[str] = field(default_factory=lambda: [
        "emergency", "911", "112", "999", "police", "fire",
        "ambulance", "rescue", "help", "sos", "mayday"
    ])
    alert_channel: int = 2
    alert_interface: int = 1
    play_sound: bool = False
    sound_file: str = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
    send_email: bool = False
    send_sms: bool = False
    cooldown_period: int = 300
    log_to_file: bool = True
    log_file: str = "logs/emergency_alerts.log"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EmergencyAlertConfig':
        keywords = data.get('emergency_keywords', data.get('keywords', ''))
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(',') if k.strip()]
        elif not keywords:
            keywords = cls.__dataclass_fields__['keywords'].default_factory()

        return cls(
            enabled=_str_to_bool(data.get('enabled', True)),
            keywords=keywords,
            alert_channel=int(data.get('alert_channel', 2)),
            alert_interface=int(data.get('alert_interface', 1)),
            play_sound=_str_to_bool(data.get('play_sound', False)),
            sound_file=str(data.get('sound_file', '')),
            send_email=_str_to_bool(data.get('send_email', False)),
            send_sms=_str_to_bool(data.get('send_sms', False)),
            cooldown_period=int(data.get('cooldown_period', 300)),
            log_to_file=_str_to_bool(data.get('log_to_file', True)),
            log_file=str(data.get('log_file', 'logs/emergency_alerts.log'))
        )


@dataclass
class SentryConfig:
    """Proximity/sentry detection configuration.

    Maps to: [sentry] in upstream, [proximityAlert] in MeshForge.
    """
    enabled: bool = False
    interface: int = 1
    channel: int = 2
    radius_meters: int = 100
    holdoff_multiplier: int = 9  # Upstream: holdoff * 20 seconds
    target_latitude: float = 0.0
    target_longitude: float = 0.0
    ignore_list: List[str] = field(default_factory=list)
    watch_list: List[str] = field(default_factory=list)
    email_alerts: bool = False
    detection_sensor: bool = False
    run_script: bool = False
    script_near: str = "sentry_alert_near.sh"
    script_away: str = "sentry_alert_away.sh"
    check_interval: int = 60
    node_cooldown: int = 600
    log_to_file: bool = True
    log_file: str = "logs/proximity_alerts.log"

    @classmethod
    def from_upstream(cls, data: Dict[str, Any]) -> 'SentryConfig':
        """Create from upstream [sentry] section format."""
        ignore_str = data.get('sentryIgnoreList', '')
        watch_str = data.get('sentryWatchList', '')

        return cls(
            enabled=_str_to_bool(data.get('SentryEnabled', False)),
            interface=int(data.get('SentryInterface', 1)),
            channel=int(data.get('SentryChannel', 2)),
            radius_meters=int(data.get('SentryRadius', 100)),
            holdoff_multiplier=int(data.get('SentryHoldoff', 9)),
            ignore_list=_str_to_list(ignore_str),
            watch_list=_str_to_list(watch_str),
            email_alerts=_str_to_bool(data.get('emailSentryAlerts', False)),
            detection_sensor=_str_to_bool(data.get('detectionSensorAlert', False)),
            run_script=_str_to_bool(data.get('cmdShellSentryAlerts', False)),
            script_near=str(data.get('sentryAlertNear', 'sentry_alert_near.sh')),
            script_away=str(data.get('sentryAlertAway', 'sentry_alert_away.sh'))
        )

    @classmethod
    def from_meshforge(cls, data: Dict[str, Any]) -> 'SentryConfig':
        """Create from MeshForge [proximityAlert] section format."""
        return cls(
            enabled=_str_to_bool(data.get('enabled', False)),
            target_latitude=float(data.get('target_latitude', 0.0)),
            target_longitude=float(data.get('target_longitude', 0.0)),
            radius_meters=int(data.get('radius_meters', 100)),
            channel=int(data.get('alert_channel', 0)),
            check_interval=int(data.get('check_interval', 60)),
            run_script=_str_to_bool(data.get('run_script', False)),
            script_near=str(data.get('script_path', '')),
            email_alerts=_str_to_bool(data.get('send_email', False)),
            node_cooldown=int(data.get('node_cooldown', 600)),
            log_to_file=_str_to_bool(data.get('log_to_file', True)),
            log_file=str(data.get('log_file', 'logs/proximity_alerts.log'))
        )


@dataclass
class AltitudeAlertConfig:
    """High altitude detection configuration.

    Maps to: [sentry].highFlyingAlert in upstream, [altitudeAlert] in MeshForge.
    """
    enabled: bool = False
    min_altitude: int = 1000  # meters
    check_openskynetwork: bool = True
    interface: int = 1
    channel: int = 2
    ignore_list: List[str] = field(default_factory=list)
    check_interval: int = 120
    cooldown_period: int = 300
    log_to_file: bool = True
    log_file: str = "logs/altitude_alerts.log"

    @classmethod
    def from_upstream(cls, sentry_data: Dict[str, Any]) -> 'AltitudeAlertConfig':
        """Create from upstream [sentry] section (high flying fields)."""
        ignore_str = sentry_data.get('highFlyingIgnoreList', '')

        return cls(
            enabled=_str_to_bool(sentry_data.get('highFlyingAlert', False)),
            min_altitude=int(sentry_data.get('highFlyingAlertAltitude', 2000)),
            check_openskynetwork=_str_to_bool(sentry_data.get('highflyOpenskynetwork', True)),
            interface=int(sentry_data.get('highFlyingAlertInterface', 1)),
            channel=int(sentry_data.get('highFlyingAlertChannel', 2)),
            ignore_list=_str_to_list(ignore_str)
        )


@dataclass
class WeatherAlertConfig:
    """Weather/NOAA alert configuration."""
    enabled: bool = False
    location: str = ""  # lat,lon
    severity_levels: List[str] = field(default_factory=lambda: ["Extreme", "Severe"])
    check_interval_minutes: int = 30
    alert_channel: int = 2
    send_dm: bool = False
    dm_recipients: List[str] = field(default_factory=list)
    play_sound: bool = False
    sound_file: str = "/usr/share/sounds/freedesktop/stereo/bell.oga"
    log_to_file: bool = True
    log_file: str = "logs/weather_alerts.log"


@dataclass
class BatteryAlertConfig:
    """Low battery alert configuration."""
    enabled: bool = False
    threshold_percent: int = 20
    check_interval_minutes: int = 30
    alert_channel: int = 0
    monitor_nodes: List[str] = field(default_factory=list)  # Empty = all
    node_cooldown_minutes: int = 180
    log_to_file: bool = True
    log_file: str = "logs/battery_alerts.log"


@dataclass
class NewNodeAlertConfig:
    """New node welcome/alert configuration."""
    enabled: bool = True
    welcome_message: str = "Welcome to the mesh, {node_name}!"
    send_as_dm: bool = True
    announce_to_channel: bool = False
    announcement_channel: int = 0
    welcome_delay: int = 5
    log_to_file: bool = True
    log_file: str = "logs/new_nodes.log"


@dataclass
class NoisyNodeAlertConfig:
    """Noisy/chatty node detection configuration."""
    enabled: bool = False
    message_threshold: int = 50
    time_period_minutes: int = 10
    alert_channel: int = 0
    auto_mute: bool = False
    mute_duration_minutes: int = 60
    whitelist: List[str] = field(default_factory=list)
    log_to_file: bool = True
    log_file: str = "logs/noisy_node_alerts.log"


@dataclass
class DisconnectAlertConfig:
    """Node disconnect/offline alert configuration."""
    enabled: bool = False
    offline_threshold_minutes: int = 60
    monitor_nodes: List[str] = field(default_factory=list)  # Empty = all
    alert_channel: int = 0
    send_admin_dm: bool = False
    log_to_file: bool = True
    log_file: str = "logs/disconnect_alerts.log"


@dataclass
class GlobalAlertConfig:
    """Global alert settings."""
    enabled: bool = True
    quiet_hours: str = ""  # HH:MM-HH:MM format
    max_alerts_per_hour: int = 20
    emergency_priority: AlertPriority = AlertPriority.CRITICAL
    weather_priority: AlertPriority = AlertPriority.HIGH
    proximity_priority: AlertPriority = AlertPriority.MEDIUM
    general_priority: AlertPriority = AlertPriority.LOW


# =============================================================================
# MQTT Configuration
# =============================================================================

@dataclass
class MQTTConfig:
    """MQTT broker configuration for radio-less operation."""
    enabled: bool = False
    broker: str = "mqtt.meshtastic.org"
    port: int = 1883
    use_tls: bool = False
    username: str = "meshdev"
    password: str = "large4cats"
    topic_root: str = "msh/US"
    channel: str = "LongFast"
    node_id: str = ""
    client_id: str = ""
    encryption_key: str = ""
    qos: int = 1
    reconnect_delay: int = 5
    max_reconnect_attempts: int = 10

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MQTTConfig':
        return cls(
            enabled=_str_to_bool(data.get('enabled', False)),
            broker=str(data.get('broker', 'mqtt.meshtastic.org')),
            port=int(data.get('port', 1883)),
            use_tls=_str_to_bool(data.get('use_tls', False)),
            username=str(data.get('username', 'meshdev')),
            password=str(data.get('password', 'large4cats')),
            topic_root=str(data.get('topic_root', 'msh/US')),
            channel=str(data.get('channel', 'LongFast')),
            node_id=str(data.get('node_id', '')),
            client_id=str(data.get('client_id', '')),
            encryption_key=str(data.get('encryption_key', '')),
            qos=int(data.get('qos', 1)),
            reconnect_delay=int(data.get('reconnect_delay', 5)),
            max_reconnect_attempts=int(data.get('max_reconnect_attempts', 10))
        )


# =============================================================================
# Notification Configuration
# =============================================================================

@dataclass
class SMTPConfig:
    """Email/SMTP notification configuration."""
    enabled: bool = False
    enable_imap: bool = False
    server: str = "smtp.gmail.com"
    port: int = 587
    use_auth: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    subject: str = "Meshtastic Alert"
    sysop_emails: List[str] = field(default_factory=list)


@dataclass
class SMSConfig:
    """SMS notification configuration."""
    enabled: bool = False
    gateway: str = ""  # e.g., @txt.att.net
    phone_numbers: List[str] = field(default_factory=list)


# =============================================================================
# Auto-Update Configuration
# =============================================================================

@dataclass
class AutoUpdateConfig:
    """Auto-update configuration for MeshForge and upstream."""
    enabled: bool = False  # Opt-in
    check_meshforge: bool = True
    check_upstream: bool = True
    schedule: str = "weekly"  # weekly, monthly, daily
    notify_only: bool = True  # Just notify, don't auto-apply
    branch: str = "main"
    last_check: str = ""


# =============================================================================
# General/Bot Configuration
# =============================================================================

@dataclass
class GeneralConfig:
    """General bot settings.

    Maps to: [general] in upstream.
    """
    bot_name: str = "MeshBot"
    respond_by_dm_only: bool = True
    auto_ping_in_channel: bool = False
    default_channel: int = 0
    ignore_default_channel: bool = False
    ignore_channels: List[int] = field(default_factory=list)
    cmd_bang: bool = False
    explicit_cmd: bool = True
    favorite_nodes: List[str] = field(default_factory=list)
    admin_nodes: List[str] = field(default_factory=list)
    motd: str = "Thanks for using MeshBOT! Have a good day!"
    welcome_message: str = "MeshBot, here for you like a friend who is not. Try sending: ping @foo or, cmd"
    zulu_time: bool = False
    url_timeout: int = 15
    log_messages: bool = False
    syslog_to_file: bool = True
    syslog_level: str = "DEBUG"
    log_backup_count: int = 32


# =============================================================================
# TUI/Web Configuration
# =============================================================================

@dataclass
class TUIConfig:
    """Terminal UI configuration."""
    refresh_rate: float = 1.0
    color_scheme: str = "default"
    show_timestamps: bool = True
    message_history: int = 500
    alert_sound: bool = True


@dataclass
class WebConfig:
    """Web dashboard configuration."""
    host: str = "127.0.0.1"
    port: int = 8080
    debug: bool = False
    api_key: str = ""
    enable_auth: bool = False
    username: str = "admin"
    password_hash: str = ""


# =============================================================================
# Unified Configuration
# =============================================================================

@dataclass
class UnifiedConfig:
    """Complete unified configuration for MeshForge.

    Combines all configuration sections into a single, validated structure.
    Supports loading from both upstream and MeshForge config formats.
    """
    # Interfaces (supports up to 9)
    interfaces: List[InterfaceConfig] = field(default_factory=lambda: [InterfaceConfig()])

    # General settings
    general: GeneralConfig = field(default_factory=GeneralConfig)

    # Alert configurations
    emergency: EmergencyAlertConfig = field(default_factory=EmergencyAlertConfig)
    sentry: SentryConfig = field(default_factory=SentryConfig)
    altitude: AltitudeAlertConfig = field(default_factory=AltitudeAlertConfig)
    weather: WeatherAlertConfig = field(default_factory=WeatherAlertConfig)
    battery: BatteryAlertConfig = field(default_factory=BatteryAlertConfig)
    new_node: NewNodeAlertConfig = field(default_factory=NewNodeAlertConfig)
    noisy_node: NoisyNodeAlertConfig = field(default_factory=NoisyNodeAlertConfig)
    disconnect: DisconnectAlertConfig = field(default_factory=DisconnectAlertConfig)
    global_alerts: GlobalAlertConfig = field(default_factory=GlobalAlertConfig)

    # Connection configurations
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)

    # Notifications
    smtp: SMTPConfig = field(default_factory=SMTPConfig)
    sms: SMSConfig = field(default_factory=SMSConfig)

    # Client configurations
    tui: TUIConfig = field(default_factory=TUIConfig)
    web: WebConfig = field(default_factory=WebConfig)

    # Auto-update
    auto_update: AutoUpdateConfig = field(default_factory=AutoUpdateConfig)

    # Metadata
    config_path: Optional[Path] = None
    config_format: str = "meshforge"  # "meshforge" or "upstream"

    def validate(self) -> List[str]:
        """Validate entire configuration, return list of errors."""
        errors = []

        for i, iface in enumerate(self.interfaces):
            iface_errors = iface.validate()
            errors.extend([f"Interface {i+1}: {e}" for e in iface_errors])

        if self.mqtt.enabled and not self.mqtt.broker:
            errors.append("MQTT enabled but no broker specified")

        if self.smtp.enabled and not self.smtp.server:
            errors.append("SMTP enabled but no server specified")

        return errors

    def get_active_interfaces(self) -> List[Tuple[int, InterfaceConfig]]:
        """Get list of enabled interfaces with their indices."""
        return [(i, iface) for i, iface in enumerate(self.interfaces) if iface.enabled]


# =============================================================================
# Config Loading/Saving
# =============================================================================

class ConfigLoader:
    """Handles loading and saving configuration from various formats."""

    @staticmethod
    def load(path: Path) -> UnifiedConfig:
        """Load configuration from file, auto-detecting format."""
        if not path.exists():
            return UnifiedConfig(config_path=path)

        parser = configparser.ConfigParser()
        parser.read(path)

        # Detect format based on section names
        sections = parser.sections()
        is_upstream = 'bbs' in sections or 'sentry' in sections

        if is_upstream:
            return ConfigLoader._load_upstream(parser, path)
        else:
            return ConfigLoader._load_meshforge(parser, path)

    @staticmethod
    def _load_upstream(parser: configparser.ConfigParser, path: Path) -> UnifiedConfig:
        """Load upstream meshing-around config format."""
        config = UnifiedConfig(config_path=path, config_format="upstream")

        # Load interfaces (interface, interface2, ..., interface9)
        interfaces = []
        for i in range(1, 10):
            section = 'interface' if i == 1 else f'interface{i}'
            if parser.has_section(section):
                data = dict(parser.items(section))
                iface = InterfaceConfig.from_dict(data)
                # interface1 is always enabled if present
                if i > 1 and not _str_to_bool(data.get('enabled', False)):
                    iface.enabled = False
                interfaces.append(iface)

        if interfaces:
            config.interfaces = interfaces

        # Load general
        if parser.has_section('general'):
            data = dict(parser.items('general'))
            config.general = GeneralConfig(
                bot_name=data.get('bot_name', 'MeshBot'),
                respond_by_dm_only=_str_to_bool(data.get('respond_by_dm_only', True)),
                auto_ping_in_channel=_str_to_bool(data.get('autopinginchannel', False)),
                default_channel=int(data.get('defaultchannel', 0)),
                ignore_default_channel=_str_to_bool(data.get('ignoredefaultchannel', False)),
                ignore_channels=_str_to_int_list(data.get('ignorechannels', '')),
                cmd_bang=_str_to_bool(data.get('cmdbang', False)),
                explicit_cmd=_str_to_bool(data.get('explicitcmd', True)),
                favorite_nodes=_str_to_list(data.get('favoritenodelist', '')),
                admin_nodes=_str_to_list(data.get('bbs_admin_list', '')),
                motd=data.get('motd', ''),
                welcome_message=data.get('welcome_message', ''),
                zulu_time=_str_to_bool(data.get('zulutime', False)),
                url_timeout=int(data.get('urltimeout', 15)),
                log_messages=_str_to_bool(data.get('logmessagestofile', False)),
                syslog_to_file=_str_to_bool(data.get('syslogtofile', True)),
                syslog_level=data.get('sysloglevel', 'DEBUG'),
                log_backup_count=int(data.get('log_backup_count', 32))
            )

        # Load emergency handler
        if parser.has_section('emergencyHandler'):
            data = dict(parser.items('emergencyHandler'))
            config.emergency = EmergencyAlertConfig.from_dict(data)

        # Load sentry (maps to proximity/sentry)
        if parser.has_section('sentry'):
            data = dict(parser.items('sentry'))
            config.sentry = SentryConfig.from_upstream(data)
            config.altitude = AltitudeAlertConfig.from_upstream(data)

        return config

    @staticmethod
    def _load_meshforge(parser: configparser.ConfigParser, path: Path) -> UnifiedConfig:
        """Load MeshForge config format."""
        config = UnifiedConfig(config_path=path, config_format="meshforge")

        # Load interface
        if parser.has_section('interface'):
            data = dict(parser.items('interface'))
            config.interfaces = [InterfaceConfig.from_dict(data)]

        # Load general
        if parser.has_section('general'):
            data = dict(parser.items('general'))
            config.general.bot_name = data.get('bot_name', 'MeshBot')
            config.general.favorite_nodes = _str_to_list(data.get('favoritenodelist', ''))
            config.general.admin_nodes = _str_to_list(data.get('bbs_admin_list', ''))

        # Load emergency handler
        if parser.has_section('emergencyHandler'):
            data = dict(parser.items('emergencyHandler'))
            config.emergency = EmergencyAlertConfig.from_dict(data)

        # Load proximity alert
        if parser.has_section('proximityAlert'):
            data = dict(parser.items('proximityAlert'))
            config.sentry = SentryConfig.from_meshforge(data)

        # Load altitude alert
        if parser.has_section('altitudeAlert'):
            data = dict(parser.items('altitudeAlert'))
            config.altitude = AltitudeAlertConfig(
                enabled=_str_to_bool(data.get('enabled', False)),
                min_altitude=int(data.get('min_altitude', 1000)),
                channel=int(data.get('alert_channel', 0)),
                check_interval=int(data.get('check_interval', 120)),
                cooldown_period=int(data.get('cooldown_period', 300)),
                log_to_file=_str_to_bool(data.get('log_to_file', True)),
                log_file=data.get('log_file', 'logs/altitude_alerts.log')
            )

        # Load MQTT
        if parser.has_section('mqtt'):
            data = dict(parser.items('mqtt'))
            config.mqtt = MQTTConfig.from_dict(data)

        # Load TUI
        if parser.has_section('tui'):
            data = dict(parser.items('tui'))
            config.tui = TUIConfig(
                refresh_rate=float(data.get('refresh_rate', 1.0)),
                color_scheme=data.get('color_scheme', 'default'),
                show_timestamps=_str_to_bool(data.get('show_timestamps', True)),
                message_history=int(data.get('message_history', 500)),
                alert_sound=_str_to_bool(data.get('alert_sound', True))
            )

        # Load Web
        if parser.has_section('web'):
            data = dict(parser.items('web'))
            config.web = WebConfig(
                host=data.get('host', '127.0.0.1'),
                port=int(data.get('port', 8080)),
                debug=_str_to_bool(data.get('debug', False)),
                api_key=data.get('api_key', ''),
                enable_auth=_str_to_bool(data.get('enable_auth', False)),
                username=data.get('username', 'admin')
            )

        # Load auto-update
        if parser.has_section('auto_update'):
            data = dict(parser.items('auto_update'))
            config.auto_update = AutoUpdateConfig(
                enabled=_str_to_bool(data.get('enabled', False)),
                check_meshforge=_str_to_bool(data.get('check_meshforge', True)),
                check_upstream=_str_to_bool(data.get('check_upstream', True)),
                schedule=data.get('schedule', 'weekly'),
                notify_only=_str_to_bool(data.get('notify_only', True)),
                branch=data.get('branch', 'main'),
                last_check=data.get('last_check', '')
            )

        return config

    @staticmethod
    def save(config: UnifiedConfig, path: Optional[Path] = None) -> bool:
        """Save configuration to file."""
        path = path or config.config_path
        if not path:
            return False

        parser = configparser.ConfigParser()

        # Save interfaces
        for i, iface in enumerate(config.interfaces):
            section = 'interface' if i == 0 else f'interface{i+1}'
            parser.add_section(section)
            for key, value in iface.to_dict().items():
                parser.set(section, key, str(value))

        # Save general
        parser.add_section('general')
        parser.set('general', 'bot_name', config.general.bot_name)
        parser.set('general', 'favoriteNodeList', ','.join(config.general.favorite_nodes))
        parser.set('general', 'bbs_admin_list', ','.join(config.general.admin_nodes))

        # Save emergency handler
        parser.add_section('emergencyHandler')
        parser.set('emergencyHandler', 'enabled', str(config.emergency.enabled))
        parser.set('emergencyHandler', 'emergency_keywords', ','.join(config.emergency.keywords))
        parser.set('emergencyHandler', 'alert_channel', str(config.emergency.alert_channel))
        parser.set('emergencyHandler', 'cooldown_period', str(config.emergency.cooldown_period))

        # Save MQTT
        parser.add_section('mqtt')
        parser.set('mqtt', 'enabled', str(config.mqtt.enabled))
        parser.set('mqtt', 'broker', config.mqtt.broker)
        parser.set('mqtt', 'port', str(config.mqtt.port))
        parser.set('mqtt', 'username', config.mqtt.username)
        parser.set('mqtt', 'password', config.mqtt.password)
        parser.set('mqtt', 'topic_root', config.mqtt.topic_root)
        parser.set('mqtt', 'channel', config.mqtt.channel)

        # Save auto-update
        parser.add_section('auto_update')
        parser.set('auto_update', 'enabled', str(config.auto_update.enabled))
        parser.set('auto_update', 'check_meshforge', str(config.auto_update.check_meshforge))
        parser.set('auto_update', 'check_upstream', str(config.auto_update.check_upstream))
        parser.set('auto_update', 'schedule', config.auto_update.schedule)
        parser.set('auto_update', 'notify_only', str(config.auto_update.notify_only))

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                parser.write(f)
            # Secure permissions for config with credentials
            os.chmod(path, 0o600)
            return True
        except OSError as e:
            print(f"Error saving config: {e}")
            return False


# =============================================================================
# Helper Functions
# =============================================================================

def _str_to_bool(value: Any) -> bool:
    """Convert string to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', 'yes', '1', 'on')
    return bool(value)


def _str_to_list(value: str) -> List[str]:
    """Convert comma-separated string to list."""
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def _str_to_int_list(value: str) -> List[int]:
    """Convert comma-separated string to list of ints."""
    if not value:
        return []
    result = []
    for item in value.split(','):
        item = item.strip()
        if item:
            try:
                result.append(int(item))
            except ValueError:
                pass
    return result

"""
Configuration management for Meshing-Around Clients.
Handles loading and saving client configuration.
"""

import os
import configparser
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class InterfaceConfig:
    """Interface connection configuration."""
    type: str = "serial"  # serial, tcp, ble
    port: str = ""  # Auto-detect if empty
    hostname: str = ""
    mac: str = ""
    baudrate: int = 115200


@dataclass
class AlertConfig:
    """Alert system configuration."""
    enabled: bool = True
    emergency_keywords: List[str] = field(default_factory=lambda: [
        "emergency", "911", "112", "999", "police", "fire",
        "ambulance", "rescue", "help", "sos", "mayday"
    ])
    alert_channel: int = 2
    play_sound: bool = False
    cooldown_period: int = 300


@dataclass
class WebConfig:
    """Web client configuration."""
    host: str = "127.0.0.1"
    port: int = 8080
    debug: bool = False
    api_key: str = ""
    enable_auth: bool = False
    username: str = "admin"
    password_hash: str = ""


@dataclass
class TuiConfig:
    """TUI client configuration."""
    refresh_rate: float = 1.0
    color_scheme: str = "default"
    show_timestamps: bool = True
    message_history: int = 500
    alert_sound: bool = True


@dataclass
class MQTTConfig:
    """MQTT connection configuration for radio-less operation."""
    enabled: bool = False
    broker: str = "mqtt.meshtastic.org"
    port: int = 1883
    use_tls: bool = False
    username: str = "meshdev"
    password: str = "large4cats"
    topic_root: str = "msh/US"
    channel: str = "LongFast"
    node_id: str = ""  # Virtual node ID for sending
    client_id: str = ""  # MQTT client ID (auto-generated if empty)
    # Encryption key for decrypting channel messages (base64 encoded)
    encryption_key: str = ""
    # QoS level for subscriptions (0, 1, or 2)
    qos: int = 1
    # Reconnect settings
    reconnect_delay: int = 5
    max_reconnect_attempts: int = 10


class Config:
    """Main configuration class for Meshing-Around Clients."""

    DEFAULT_CONFIG_PATHS = [
        Path.home() / ".config" / "meshing-around-clients" / "config.ini",
        Path.cwd() / "client_config.ini",
        Path("/etc/meshing-around-clients/config.ini")
    ]

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else self._find_config()
        self._parser = configparser.ConfigParser()

        # Configuration sections
        self.interface = InterfaceConfig()
        self.alerts = AlertConfig()
        self.web = WebConfig()
        self.tui = TuiConfig()
        self.mqtt = MQTTConfig()

        # Bot connection info
        self.bot_name = "MeshBot"
        self.admin_nodes: List[str] = []
        self.favorite_nodes: List[str] = []

        if self.config_path and self.config_path.exists():
            self.load()

    def _find_config(self) -> Optional[Path]:
        """Find an existing config file."""
        for path in self.DEFAULT_CONFIG_PATHS:
            if path.exists():
                return path
        return self.DEFAULT_CONFIG_PATHS[0]  # Default path for new config

    def load(self) -> bool:
        """Load configuration from file."""
        if not self.config_path or not self.config_path.exists():
            return False

        try:
            self._parser.read(self.config_path)

            # Interface
            if self._parser.has_section('interface'):
                self.interface.type = self._parser.get('interface', 'type', fallback='serial')
                self.interface.port = self._parser.get('interface', 'port', fallback='')
                self.interface.hostname = self._parser.get('interface', 'hostname', fallback='')
                self.interface.mac = self._parser.get('interface', 'mac', fallback='')
                self.interface.baudrate = self._parser.getint('interface', 'baudrate', fallback=115200)

            # General
            if self._parser.has_section('general'):
                self.bot_name = self._parser.get('general', 'bot_name', fallback='MeshBot')
                admin_str = self._parser.get('general', 'bbs_admin_list', fallback='')
                self.admin_nodes = [n.strip() for n in admin_str.split(',') if n.strip()]
                fav_str = self._parser.get('general', 'favoriteNodeList', fallback='')
                self.favorite_nodes = [n.strip() for n in fav_str.split(',') if n.strip()]

            # Alerts
            if self._parser.has_section('emergencyHandler'):
                self.alerts.enabled = self._parser.getboolean('emergencyHandler', 'enabled', fallback=True)
                keywords_str = self._parser.get('emergencyHandler', 'emergency_keywords', fallback='')
                if keywords_str:
                    self.alerts.emergency_keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
                self.alerts.alert_channel = self._parser.getint('emergencyHandler', 'alert_channel', fallback=2)
                self.alerts.play_sound = self._parser.getboolean('emergencyHandler', 'play_sound', fallback=False)
                self.alerts.cooldown_period = self._parser.getint('emergencyHandler', 'cooldown_period', fallback=300)

            # Web
            if self._parser.has_section('web'):
                self.web.host = self._parser.get('web', 'host', fallback='127.0.0.1')
                self.web.port = self._parser.getint('web', 'port', fallback=8080)
                self.web.debug = self._parser.getboolean('web', 'debug', fallback=False)
                self.web.api_key = self._parser.get('web', 'api_key', fallback='')
                self.web.enable_auth = self._parser.getboolean('web', 'enable_auth', fallback=False)
                self.web.username = self._parser.get('web', 'username', fallback='admin')

            # TUI
            if self._parser.has_section('tui'):
                self.tui.refresh_rate = self._parser.getfloat('tui', 'refresh_rate', fallback=1.0)
                self.tui.color_scheme = self._parser.get('tui', 'color_scheme', fallback='default')
                self.tui.show_timestamps = self._parser.getboolean('tui', 'show_timestamps', fallback=True)
                self.tui.message_history = self._parser.getint('tui', 'message_history', fallback=500)
                self.tui.alert_sound = self._parser.getboolean('tui', 'alert_sound', fallback=True)

            # MQTT
            if self._parser.has_section('mqtt'):
                self.mqtt.enabled = self._parser.getboolean('mqtt', 'enabled', fallback=False)
                self.mqtt.broker = self._parser.get('mqtt', 'broker', fallback='mqtt.meshtastic.org')
                self.mqtt.port = self._parser.getint('mqtt', 'port', fallback=1883)
                self.mqtt.use_tls = self._parser.getboolean('mqtt', 'use_tls', fallback=False)
                self.mqtt.username = self._parser.get('mqtt', 'username', fallback='meshdev')
                self.mqtt.password = self._parser.get('mqtt', 'password', fallback='large4cats')
                self.mqtt.topic_root = self._parser.get('mqtt', 'topic_root', fallback='msh/US')
                self.mqtt.channel = self._parser.get('mqtt', 'channel', fallback='LongFast')
                self.mqtt.node_id = self._parser.get('mqtt', 'node_id', fallback='')
                self.mqtt.client_id = self._parser.get('mqtt', 'client_id', fallback='')
                self.mqtt.encryption_key = self._parser.get('mqtt', 'encryption_key', fallback='')
                self.mqtt.qos = self._parser.getint('mqtt', 'qos', fallback=1)
                self.mqtt.reconnect_delay = self._parser.getint('mqtt', 'reconnect_delay', fallback=5)
                self.mqtt.max_reconnect_attempts = self._parser.getint('mqtt', 'max_reconnect_attempts', fallback=10)

            return True
        except (configparser.Error, OSError) as e:
            print(f"Error loading config: {e}")
            return False

    def save(self) -> bool:
        """Save configuration to file."""
        try:
            # Ensure directory exists
            if self.config_path:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Interface
            if not self._parser.has_section('interface'):
                self._parser.add_section('interface')
            self._parser.set('interface', 'type', self.interface.type)
            self._parser.set('interface', 'port', self.interface.port)
            self._parser.set('interface', 'hostname', self.interface.hostname)
            self._parser.set('interface', 'mac', self.interface.mac)
            self._parser.set('interface', 'baudrate', str(self.interface.baudrate))

            # General
            if not self._parser.has_section('general'):
                self._parser.add_section('general')
            self._parser.set('general', 'bot_name', self.bot_name)
            self._parser.set('general', 'bbs_admin_list', ','.join(self.admin_nodes))
            self._parser.set('general', 'favoriteNodeList', ','.join(self.favorite_nodes))

            # Alerts
            if not self._parser.has_section('emergencyHandler'):
                self._parser.add_section('emergencyHandler')
            self._parser.set('emergencyHandler', 'enabled', str(self.alerts.enabled))
            self._parser.set('emergencyHandler', 'emergency_keywords', ','.join(self.alerts.emergency_keywords))
            self._parser.set('emergencyHandler', 'alert_channel', str(self.alerts.alert_channel))
            self._parser.set('emergencyHandler', 'play_sound', str(self.alerts.play_sound))
            self._parser.set('emergencyHandler', 'cooldown_period', str(self.alerts.cooldown_period))

            # Web
            if not self._parser.has_section('web'):
                self._parser.add_section('web')
            self._parser.set('web', 'host', self.web.host)
            self._parser.set('web', 'port', str(self.web.port))
            self._parser.set('web', 'debug', str(self.web.debug))
            self._parser.set('web', 'api_key', self.web.api_key)
            self._parser.set('web', 'enable_auth', str(self.web.enable_auth))
            self._parser.set('web', 'username', self.web.username)

            # TUI
            if not self._parser.has_section('tui'):
                self._parser.add_section('tui')
            self._parser.set('tui', 'refresh_rate', str(self.tui.refresh_rate))
            self._parser.set('tui', 'color_scheme', self.tui.color_scheme)
            self._parser.set('tui', 'show_timestamps', str(self.tui.show_timestamps))
            self._parser.set('tui', 'message_history', str(self.tui.message_history))
            self._parser.set('tui', 'alert_sound', str(self.tui.alert_sound))

            # MQTT
            if not self._parser.has_section('mqtt'):
                self._parser.add_section('mqtt')
            self._parser.set('mqtt', 'enabled', str(self.mqtt.enabled))
            self._parser.set('mqtt', 'broker', self.mqtt.broker)
            self._parser.set('mqtt', 'port', str(self.mqtt.port))
            self._parser.set('mqtt', 'use_tls', str(self.mqtt.use_tls))
            self._parser.set('mqtt', 'username', self.mqtt.username)
            self._parser.set('mqtt', 'password', self.mqtt.password)
            self._parser.set('mqtt', 'topic_root', self.mqtt.topic_root)
            self._parser.set('mqtt', 'channel', self.mqtt.channel)
            self._parser.set('mqtt', 'node_id', self.mqtt.node_id)
            self._parser.set('mqtt', 'client_id', self.mqtt.client_id)
            self._parser.set('mqtt', 'encryption_key', self.mqtt.encryption_key)
            self._parser.set('mqtt', 'qos', str(self.mqtt.qos))
            self._parser.set('mqtt', 'reconnect_delay', str(self.mqtt.reconnect_delay))
            self._parser.set('mqtt', 'max_reconnect_attempts', str(self.mqtt.max_reconnect_attempts))

            if self.config_path:
                with open(self.config_path, 'w') as f:
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
            "interface": {
                "type": self.interface.type,
                "port": self.interface.port,
                "hostname": self.interface.hostname,
                "mac": self.interface.mac,
                "baudrate": self.interface.baudrate
            },
            "general": {
                "bot_name": self.bot_name,
                "admin_nodes": self.admin_nodes,
                "favorite_nodes": self.favorite_nodes
            },
            "alerts": {
                "enabled": self.alerts.enabled,
                "emergency_keywords": self.alerts.emergency_keywords,
                "alert_channel": self.alerts.alert_channel,
                "play_sound": self.alerts.play_sound,
                "cooldown_period": self.alerts.cooldown_period
            },
            "web": {
                "host": self.web.host,
                "port": self.web.port,
                "debug": self.web.debug,
                "enable_auth": self.web.enable_auth
            },
            "tui": {
                "refresh_rate": self.tui.refresh_rate,
                "color_scheme": self.tui.color_scheme,
                "show_timestamps": self.tui.show_timestamps,
                "message_history": self.tui.message_history,
                "alert_sound": self.tui.alert_sound
            },
            "mqtt": {
                "enabled": self.mqtt.enabled,
                "broker": self.mqtt.broker,
                "port": self.mqtt.port,
                "use_tls": self.mqtt.use_tls,
                "topic_root": self.mqtt.topic_root,
                "channel": self.mqtt.channel,
                "node_id": self.mqtt.node_id,
                "qos": self.mqtt.qos
            }
        }

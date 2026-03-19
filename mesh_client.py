#!/usr/bin/env python3
"""
Meshing-Around Standalone Client
================================
Zero-dependency bootstrap launcher for mesh network monitoring.

Supports:
- Direct radio connection (serial/USB)
- TCP connection to remote Meshtastic device (protobuf port)
- HTTP connection to meshtasticd HTTP API
- MQTT connection (no radio required)
- BLE connection

Works on:
- Raspberry Pi (Zero 2W, 3, 4, 5)
- Any Linux system
- Headless/SSH environments

Usage:
    python3 mesh_client.py              # Auto-detect and run
    python3 mesh_client.py --tui        # Force TUI mode
    python3 mesh_client.py --setup      # Run interactive setup
    python3 mesh_client.py --check      # Check dependencies only
    python3 mesh_client.py --profile hawaii  # Apply a regional profile
    python3 mesh_client.py --list-profiles   # List available profiles

Configuration:
    Edit mesh_client.ini for all options
"""

import logging as _logging
import os
import shutil
import socket
import subprocess
import sys
import time
from configparser import ConfigParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# ENCODING FIX — ensure UTF-8 stdout/stderr before any Unicode output
# =============================================================================
def _ensure_utf8_stdio():
    """Reconfigure stdout/stderr to UTF-8 if needed for Unicode output."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


_ensure_utf8_stdio()

# Version
VERSION = "0.5.0-beta"

# Paths
SCRIPT_DIR = Path(__file__).parent.absolute()
CONFIG_FILE = SCRIPT_DIR / "mesh_client.ini"
VENV_DIR = SCRIPT_DIR / ".venv"
LOG_FILE = SCRIPT_DIR / "logs" / "mesh_client.log"

# =============================================================================
# ZERO-DEPENDENCY UTILITIES (stdlib only)
# =============================================================================


class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    DIM = "\033[2m"

    @classmethod
    def disable(cls):
        """Disable colors for non-TTY output."""
        for attr in ["RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "CYAN"]:
            setattr(cls, attr, "")


_bootstrap_logger = _logging.getLogger("meshforge.bootstrap")

# True once setup_logging() has been called
_logging_configured = False


def log(msg: str, level: str = "INFO"):
    """Log a message — delegates to standard logging when configured, falls back to direct I/O."""
    if _logging_configured:
        level_map = {"INFO": "info", "OK": "info", "WARN": "warning", "ERROR": "error"}
        getattr(_bootstrap_logger, level_map.get(level, "info"))(msg)
        return

    # Bootstrap fallback — direct file append + colored stdout
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [{level}] {msg}"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_msg + "\n")
    except OSError:
        pass

    color = {"INFO": Colors.CYAN, "OK": Colors.GREEN, "WARN": Colors.YELLOW, "ERROR": Colors.RED}.get(
        level, Colors.RESET
    )
    print(f"{color}[{level}]{Colors.RESET} {msg}")


def setup_logging(config: ConfigParser) -> None:
    """Configure centralized logging with rotation.

    Reads [logging] section from config and sets up RotatingFileHandler
    plus colored console output. All modules using logging.getLogger(__name__)
    will automatically get file rotation.

    Also configures a dedicated ``mesh.messages`` logger for mesh traffic,
    inspired by the upstream meshing-around dual-logger pattern.  This keeps
    message history in a separate file with daily rotation so long-running
    deployments on Pi don't lose traffic logs when the system log rotates.
    """
    global _logging_configured
    from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

    enabled = config.getboolean("logging", "enabled", fallback=True)
    level_str = config.get("logging", "level", fallback="INFO").upper()
    log_file = config.get("logging", "file", fallback="logs/mesh_client.log")
    max_size_mb = config.getint("logging", "max_size_mb", fallback=10)
    backup_count = config.getint("logging", "backup_count", fallback=3)

    # Message log settings
    msg_log_enabled = config.getboolean("logging", "message_log_enabled", fallback=True)
    msg_log_file = config.get("logging", "message_log_file", fallback="logs/mesh_messages.log")
    msg_log_backup_count = config.getint("logging", "message_log_backup_count", fallback=7)

    # Resolve relative paths against script directory
    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = SCRIPT_DIR / log_path

    msg_log_path = Path(msg_log_file)
    if not msg_log_path.is_absolute():
        msg_log_path = SCRIPT_DIR / msg_log_path

    level = getattr(_logging, level_str, _logging.INFO)

    root_logger = _logging.getLogger()
    root_logger.setLevel(level)
    # Clear existing handlers to prevent duplicates on re-init
    root_logger.handlers.clear()

    # Rotating file handler (system log)
    if enabled:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                str(log_path),
                maxBytes=max_size_mb * 1024 * 1024,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_formatter = _logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        except OSError as e:
            print(f"{Colors.YELLOW}[WARN]{Colors.RESET} Could not set up log file: {e}")

    # Dedicated message logger (mesh traffic only, daily rotation)
    msg_logger = _logging.getLogger("mesh.messages")
    msg_logger.handlers.clear()
    msg_logger.propagate = False  # Don't duplicate into system log
    msg_logger.setLevel(_logging.INFO)

    if enabled and msg_log_enabled:
        try:
            msg_log_path.parent.mkdir(parents=True, exist_ok=True)
            msg_handler = TimedRotatingFileHandler(
                str(msg_log_path),
                when="midnight",
                backupCount=msg_log_backup_count,
                encoding="utf-8",
            )
            msg_handler.setLevel(_logging.INFO)
            msg_formatter = _logging.Formatter(
                "[%(asctime)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            msg_handler.setFormatter(msg_formatter)
            msg_logger.addHandler(msg_handler)
        except OSError as e:
            print(f"{Colors.YELLOW}[WARN]{Colors.RESET} Could not set up message log file: {e}")

    # Colored console handler (only if TTY)
    if sys.stdout.isatty():

        class _ColoredFormatter(_logging.Formatter):
            _LEVEL_COLORS = {
                "DEBUG": Colors.BLUE,
                "INFO": Colors.CYAN,
                "WARNING": Colors.YELLOW,
                "ERROR": Colors.RED,
                "CRITICAL": Colors.RED,
            }

            def format(self, record: _logging.LogRecord) -> str:
                color = self._LEVEL_COLORS.get(record.levelname, Colors.RESET)
                return f"{color}[{record.levelname}]{Colors.RESET} {record.getMessage()}"

        console_handler = _logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(_ColoredFormatter())
        root_logger.addHandler(console_handler)

    _logging_configured = True
    if enabled:
        log(f"Logging to {log_path}", "OK")


def print_banner():
    """Print startup banner."""
    # Box is 64 chars wide: ║ + 2-space indent + 60-char content area + ║
    title = "MESHING-AROUND CLIENT"
    subtitle = "Standalone Mesh Network Monitor"
    ver = f"Version {VERSION}"
    banner = (
        f"\n{Colors.CYAN}"
        f"╔══════════════════════════════════════════════════════════════╗\n"
        f"║  {Colors.BOLD}{title:<60}{Colors.RESET}{Colors.CYAN}║\n"
        f"║  {subtitle:<60}║\n"
        f"║  {ver:<60}║\n"
        f"╚══════════════════════════════════════════════════════════════╝"
        f"{Colors.RESET}\n"
    )
    try:
        print(banner)
    except UnicodeEncodeError:
        # Fallback for terminals that don't support Unicode (e.g. latin-1 locale)
        ascii_banner = (
            f"\n{Colors.CYAN}"
            f"+--------------------------------------------------------------+\n"
            f"|  {Colors.BOLD}{title:<60}{Colors.RESET}{Colors.CYAN}|\n"
            f"|  {subtitle:<60}|\n"
            f"|  {ver:<60}|\n"
            f"+--------------------------------------------------------------+"
            f"{Colors.RESET}\n"
        )
        print(ascii_banner)


def run_cmd(cmd: List[str], capture: bool = True, timeout: int = 300) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except OSError as e:
        return -1, "", str(e)


def check_internet() -> bool:
    """Check if we have internet connectivity.

    Tries multiple DNS resolvers to avoid false negatives behind
    restrictive routers/firewalls that block specific providers.
    """
    for host in ("8.8.8.8", "1.1.1.1", "9.9.9.9"):
        try:
            socket.create_connection((host, 53), timeout=3)
            return True
        except OSError:
            continue
    return False


def check_python_version() -> bool:
    """Check Python version is 3.8+."""
    return sys.version_info >= (3, 8)


# =============================================================================
# DEPENDENCY MANAGEMENT
# =============================================================================

# Core dependencies (always needed)
CORE_DEPS = [
    "rich",  # TUI
]

# Optional dependencies based on features
OPTIONAL_DEPS = {
    "mqtt": ["paho-mqtt"],
    "meshtastic": ["meshtastic[cli]", "pypubsub", "pyopenssl>=25.3.0", "cryptography>=45.0.7,<47"],
    "ble": ["bleak"],
}


# Mapping from pip package names to importable module names
_IMPORT_NAME_MAP = {
    "paho-mqtt": "paho.mqtt.client",
    "python-multipart": "multipart",
    "pypubsub": "pubsub",
    "pyopenssl": "OpenSSL",
}


def check_dependency(package: str) -> bool:
    """Check if a Python package is installed."""
    try:
        # Strip version specifiers (>=, <=, etc.) and extras ([...]) from package name
        base_name = package
        for sep in [">=", "<=", "!=", "~=", "==", ">", "<", "["]:
            base_name = base_name.split(sep)[0]
        import_name = _IMPORT_NAME_MAP.get(base_name, base_name.replace("-", "_"))
        __import__(import_name)
        return True
    except ImportError:
        return False


def get_missing_deps(config: ConfigParser) -> List[str]:
    """Get list of missing dependencies based on config."""
    missing = []

    # Always need core deps
    for dep in CORE_DEPS:
        if not check_dependency(dep):
            missing.append(dep)

    # Check optional deps based on config
    conn_type = config.get("interface", "type", fallback="auto")

    if conn_type == "mqtt" or config.getboolean("mqtt", "enabled", fallback=False):
        for dep in OPTIONAL_DEPS["mqtt"]:
            if not check_dependency(dep):
                missing.append(dep)

    if conn_type in ["serial", "tcp", "http", "auto"]:
        for dep in OPTIONAL_DEPS["meshtastic"]:
            if not check_dependency(dep):
                missing.append(dep)

    if conn_type == "ble":
        for dep in OPTIONAL_DEPS["ble"]:
            if not check_dependency(dep):
                missing.append(dep)

    return list(set(missing))


def install_dependencies(deps: List[str], use_venv: bool = True) -> bool:
    """Install missing dependencies."""
    if not deps:
        return True

    log(f"Installing dependencies: {', '.join(deps)}", "INFO")

    pip_cmd = [sys.executable, "-m", "pip", "install", "--quiet"]

    # Check if we need --break-system-packages (PEP 668)
    if not use_venv:
        # Check for externally managed environment
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        managed_file = Path(f"/usr/lib/python{py_ver}/EXTERNALLY-MANAGED")
        if managed_file.exists():
            pip_cmd.append("--break-system-packages")

    pip_cmd.extend(deps)

    ret, stdout, stderr = run_cmd(pip_cmd)

    if ret != 0:
        if any("cryptography" in d for d in deps):
            log(
                "Cryptography build failed. Install build deps: "
                "sudo apt-get install -y libssl-dev build-essential pkg-config python3-dev",
                "WARN",
            )
        log(f"Failed to install dependencies: {stderr}", "ERROR")
        return False

    log("Dependencies installed successfully", "OK")
    return True


def setup_venv() -> bool:
    """Setup virtual environment if needed."""
    if VENV_DIR.exists():
        return True

    log("Creating virtual environment...", "INFO")

    ret, _, stderr = run_cmd([sys.executable, "-m", "venv", str(VENV_DIR)])

    if ret != 0:
        log(f"Failed to create venv: {stderr}", "ERROR")
        return False

    log(f"Virtual environment created at {VENV_DIR}", "OK")
    return True


def activate_venv():
    """Activate virtual environment and re-exec if needed."""
    if VENV_DIR.exists():
        venv_python = VENV_DIR / "bin" / "python"
        if venv_python.exists() and sys.executable != str(venv_python):
            log("Activating virtual environment...", "INFO")
            os.execv(str(venv_python), [str(venv_python)] + sys.argv)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CONFIG = """
# ============================================================================
# MESHING-AROUND CLIENT CONFIGURATION
# ============================================================================
# This file controls all aspects of the mesh client.
# Edit this file to customize your setup.
# ============================================================================

[interface]
# Connection type: auto, serial, tcp, http, mqtt, ble
# - auto: Try serial first, then tcp, then http, then mqtt
# - serial: Direct USB/serial connection to radio
# - tcp: TCP connection to Meshtastic device
# - http: HTTP connection to Meshtastic device API
# - mqtt: MQTT broker connection (no radio needed)
# - ble: Bluetooth LE connection
type = auto

# Serial port (for type=serial or auto)
# Set to specific port like /dev/ttyUSB0, /dev/ttyACM0, or leave empty for auto-detect
port =

# Serial baudrate
baudrate = 115200

# TCP hostname (for type=tcp)
# Use 127.0.0.1 for local meshtasticd, host:port for remote (default port 4403)
# Do NOT use the node's web interface port (9443) - that is for browsers only
hostname =

# HTTP URL for meshtasticd HTTP API (for type=http)
# e.g. http://meshtastic.local or http://192.168.1.100
# If empty and type=http, falls back to http://<hostname>
http_url =

# BLE MAC address (for type=ble)
# MAC address like AA:BB:CC:DD:EE:FF or "scan" for discovery
mac =

# Radio hardware model (for reference and device management)
# Options: TBEAM, TLORA, TECHO, TDECK, HELTEC, RAK4631, STATION_G2
hardware_model =

# Connection behavior
auto_reconnect = true
reconnect_delay = 5
connection_timeout = 30

[mqtt]
# MQTT broker connection (no radio needed)
# Enable MQTT mode
enabled = false

# Broker settings
broker = mqtt.meshtastic.org
port = 1883
use_tls = false

# Authentication (default public broker credentials)
username = meshdev
password = large4cats

# Topic configuration
topic_root = msh/US
channel = LongFast
# Subscribe to multiple channels (comma-separated)
# Add your own channels here (e.g., LongFast,meshforge,MyLab)
channels = LongFast

# Your node ID for MQTT (leave empty to receive only)
node_id =

# Connection settings
qos = 1
reconnect_delay = 5
max_reconnect_attempts = 10

[features]
# Main interface mode: tui, headless
mode = tui

# TUI settings
tui_enabled = true
tui_refresh_rate = 1.0
tui_mouse_support = false
tui_color_scheme = default

# Features to enable/disable
messages_enabled = true
nodes_enabled = true
alerts_enabled = true
location_enabled = true
telemetry_enabled = true

[commands]
# Bot command processing
# When enabled, recognized commands (cmd, help, ping, etc.) are handled
# instead of triggering emergency keyword alerts
enabled = true

# Auto-respond to commands received from the mesh
# When true, the client will send command responses back to the mesh
auto_respond = false

# Recognized commands (comma-separated)
# Messages matching these are treated as commands, not emergency keywords
commands = cmd,help,ping,info,nodes,status,version,uptime

[data_sources]
# External data sources for command responses.
# Each source is tied to a command keyword and fetches live data.
# Set enabled = true and configure the URL/codes for your area.

# NOAA Weather (requires station code for your area)
# Find your station: https://www.weather.gov/
weather_enabled = false
weather_station =
weather_zone =
weather_url = https://api.weather.gov

# Tsunami alerts (Pacific Tsunami Warning Center)
tsunami_enabled = false
tsunami_url = https://www.tsunami.gov/events/xml/PAAQAtom.xml
tsunami_region =

# USGS Volcano alerts
volcano_enabled = false
volcano_url = https://volcanoes.usgs.gov/vsc/api/volcanoApi/

# Custom data source (user-defined)
# custom_enabled = false
# custom_name = MySource
# custom_url =
# custom_command = mysource

[alerts]
# Master alert enable
enabled = true

# Emergency keyword detection
emergency_enabled = true
emergency_keywords = emergency,911,112,999,sos,mayday

# Alert types
battery_alerts = true
battery_threshold = 20

new_node_alerts = true
disconnect_alerts = true
disconnect_timeout = 3600

# Notification settings
sound_enabled = false
sound_file = /usr/share/sounds/freedesktop/stereo/bell.oga

# Logging
log_alerts = true
log_file = logs/alerts.log

[network]
# Node filtering
favorite_nodes =
admin_nodes =
blocked_nodes =
# Comma-separated node IDs or numbers

# Channel settings
default_channel = 0
monitored_channels = 0,1,2

# Message settings
message_history = 500
max_message_length = 200

[display]
# Display preferences
show_timestamps = true
show_node_ids = false
show_snr = true
show_battery = true
show_position = false

# Time format: 12h or 24h
time_format = 24h

# Node name display: short, long, both
node_name_style = long

[logging]
# Logging configuration
enabled = true
level = INFO
# Levels: DEBUG, INFO, WARNING, ERROR
file = logs/mesh_client.log
max_size_mb = 10
backup_count = 3

# Log specific events
log_messages = true
log_nodes = true
log_telemetry = false

[advanced]
# Advanced settings - modify with care

# Use virtual environment for dependencies
use_venv = true

# Auto-install missing dependencies (set to true to skip prompts)
auto_install_deps = false

# Demo mode (no real connection, simulated data)
demo_mode = false

# Startup behavior
check_updates = false
show_splash = true

# Performance
update_interval = 1.0
node_timeout = 3600

# Debug
debug_mode = false
verbose = false
"""


def _migrate_connection_section(config: ConfigParser) -> bool:
    """Migrate legacy [connection] section to [interface] + [mqtt].

    Early versions of mesh_client.ini used a single [connection] section
    for all connection settings including MQTT. The canonical format uses
    [interface] for device settings and [mqtt] for broker settings.

    Returns True if migration was performed.
    """
    if not config.has_section("connection"):
        return False

    log("Migrating legacy [connection] config to [interface] + [mqtt]...", "INFO")

    # Map [connection] keys to [interface] section
    if not config.has_section("interface"):
        config.add_section("interface")

    key_map_interface = {
        "type": "type",
        "serial_port": "port",
        "serial_baud": "baudrate",
        "tcp_host": "hostname",
        "http_url": "http_url",
        "ble_address": "mac",
        "auto_reconnect": "auto_reconnect",
        "reconnect_delay": "reconnect_delay",
        "connection_timeout": "connection_timeout",
    }

    for old_key, new_key in key_map_interface.items():
        if config.has_option("connection", old_key):
            value = config.get("connection", old_key)
            # Skip "auto" for serial_port — canonical format uses empty string
            if old_key == "serial_port" and value.lower() == "auto":
                value = ""
            if not config.has_option("interface", new_key):
                config.set("interface", new_key, value)

    # Map [connection] MQTT keys to [mqtt] section
    if not config.has_section("mqtt"):
        config.add_section("mqtt")

    key_map_mqtt = {
        "mqtt_enabled": "enabled",
        "mqtt_broker": "broker",
        "mqtt_port": "port",
        "mqtt_use_tls": "use_tls",
        "mqtt_username": "username",
        "mqtt_password": "password",
        "mqtt_topic_root": "topic_root",
        "mqtt_channel": "channel",
        "mqtt_node_id": "node_id",
    }

    for old_key, new_key in key_map_mqtt.items():
        if config.has_option("connection", old_key):
            value = config.get("connection", old_key)
            if not config.has_option("mqtt", new_key):
                config.set("mqtt", new_key, value)

    # Remove the legacy section
    config.remove_section("connection")

    log("Config migrated to [interface] + [mqtt] format", "OK")
    return True


def load_config() -> ConfigParser:
    """Load or create configuration file."""
    config = ConfigParser()

    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
        log(f"Loaded config from {CONFIG_FILE}", "OK")

        # Migrate legacy [connection] section if present
        if _migrate_connection_section(config):
            save_config(config)
    else:
        # Create default config
        config.read_string(DEFAULT_CONFIG)
        save_config(config)
        log(f"Created default config at {CONFIG_FILE}", "OK")

    return config


def save_config(config: ConfigParser):
    """Save configuration to file with restricted permissions (atomic write)."""
    tmp_path = str(CONFIG_FILE) + ".tmp"
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            config.write(f)
        os.replace(tmp_path, str(CONFIG_FILE))
    except OSError:
        # Fallback: direct write if atomic rename fails (e.g. cross-device)
        with open(CONFIG_FILE, "w") as f:
            config.write(f)
        os.chmod(CONFIG_FILE, 0o600)
    log(f"Saved config to {CONFIG_FILE}", "OK")


# =============================================================================
# REGIONAL PROFILES
# =============================================================================

# Profiles directory: bundled with the project
PROFILES_DIR = Path(__file__).parent / "profiles"


def list_profiles() -> List[Dict[str, str]]:
    """List available regional profiles from the profiles/ directory.

    Returns a list of dicts with keys: id, name, description, path.
    """
    profiles = []
    if not PROFILES_DIR.is_dir():
        return profiles

    for ini_file in sorted(PROFILES_DIR.glob("*.ini")):
        parser = ConfigParser()
        try:
            parser.read(ini_file)
        except Exception:
            continue

        if parser.has_section("profile"):
            profiles.append(
                {
                    "id": ini_file.stem,
                    "name": parser.get("profile", "name", fallback=ini_file.stem),
                    "description": parser.get("profile", "description", fallback=""),
                    "region": parser.get("profile", "region", fallback="US"),
                    "path": str(ini_file),
                }
            )

    return profiles


def load_profile(profile_id: str) -> Optional[ConfigParser]:
    """Load a profile INI file by its ID (filename without extension).

    Returns a ConfigParser with the profile values, or None if not found.
    """
    profile_path = PROFILES_DIR / f"{profile_id}.ini"
    if not profile_path.is_file():
        log(f"Profile not found: {profile_id}", "WARN")
        return None

    parser = ConfigParser()
    try:
        parser.read(profile_path)
    except Exception as e:
        log(f"Error loading profile {profile_id}: {e}", "ERROR")
        return None

    return parser


def apply_profile(config: ConfigParser, profile: ConfigParser) -> None:
    """Apply a profile's settings onto an existing config.

    Merges profile sections into config, overwriting matching keys.
    Skips the [profile] and [notes] metadata sections.
    """
    skip_sections = {"profile", "notes"}

    for section in profile.sections():
        if section in skip_sections:
            continue

        if not config.has_section(section):
            config.add_section(section)

        for key, value in profile.items(section):
            config.set(section, key, value)

    log("Profile applied to configuration", "OK")


# =============================================================================
# CONNECTION DETECTION
# =============================================================================


def detect_serial_ports() -> List[str]:
    """Detect available serial ports."""
    ports = []

    # Common USB serial patterns
    patterns = [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/ttyAMA*",
        "/dev/serial*",
    ]

    import glob

    for pattern in patterns:
        ports.extend(glob.glob(pattern))

    return sorted(set(ports))


def detect_connection_type(config: ConfigParser) -> str:
    """Auto-detect the best connection type."""
    conn_type = config.get("interface", "type", fallback="auto")

    if conn_type != "auto":
        return conn_type

    log("Auto-detecting connection type...", "INFO")

    # Check for serial ports first
    ports = detect_serial_ports()
    if ports:
        log(f"Found serial ports: {ports}", "OK")
        return "serial"

    # Check for HTTP URL configured (meshtasticd HTTP API)
    http_url = config.get("interface", "http_url", fallback="")
    if http_url:
        log(f"HTTP URL configured: {http_url}", "INFO")
        return "http"

    # Check for TCP host configured
    tcp_host = config.get("interface", "hostname", fallback="")
    if tcp_host:
        log(f"TCP host configured: {tcp_host}", "INFO")
        return "tcp"

    # Fall back to MQTT if enabled
    if config.getboolean("mqtt", "enabled", fallback=False):
        log("Falling back to MQTT connection", "INFO")
        return "mqtt"

    # Demo mode as last resort
    log("No connection available, using demo mode", "WARN")
    return "demo"


# =============================================================================
# CONFIG IMPORT
# =============================================================================


def import_upstream_config(source_path: str):
    """Import configuration from upstream meshing-around config.ini.

    Converts upstream format to MeshForge format and saves to mesh_client.ini.

    Args:
        source_path: Path to upstream config.ini file
    """
    from pathlib import Path

    source = Path(source_path)
    if not source.exists():
        log(f"Config file not found: {source_path}", "ERROR")
        return

    log(f"Importing config from: {source_path}", "INFO")

    try:
        # Try to use the config_schema module for proper conversion
        from meshing_around_clients.setup.config_schema import ConfigLoader, UnifiedConfig

        SCHEMA_AVAILABLE = True
    except ImportError:
        SCHEMA_AVAILABLE = False

    if SCHEMA_AVAILABLE:
        # Use schema-based import
        config = ConfigLoader.load(source)

        if config.config_format == "upstream":
            log("Detected upstream meshing-around format", "OK")
        else:
            log("Config appears to be MeshForge format already", "WARN")

        # Save to MeshForge format
        dest = Path(CONFIG_FILE)
        config.config_format = "meshforge"

        if ConfigLoader.save(config, dest):
            log(f"Config imported to: {dest}", "OK")
            log(f"  Interfaces: {len(config.interfaces)}", "INFO")
            log(f"  Bot name: {config.general.bot_name}", "INFO")
            log(f"  MQTT enabled: {config.mqtt.enabled}", "INFO")
            log("Run 'python3 mesh_client.py' to start with imported config", "INFO")
        else:
            log("Failed to save imported config", "ERROR")
    else:
        # Fallback: simple INI copy with minimal conversion
        import configparser

        parser = configparser.ConfigParser()
        parser.read(source)

        # Create new config with basic conversion
        new_parser = configparser.ConfigParser()

        # Copy interface section
        if parser.has_section("interface"):
            new_parser.add_section("interface.1")
            for key, value in parser.items("interface"):
                new_parser.set("interface.1", key, value)

        # Copy general section
        if parser.has_section("general"):
            new_parser.add_section("general")
            for key, value in parser.items("general"):
                new_parser.set("general", key, value)

        # Copy MQTT if present
        for section in ["mqtt", "emergencyHandler"]:
            if parser.has_section(section):
                new_parser.add_section(section)
                for key, value in parser.items(section):
                    new_parser.set(section, key, value)

        # Save
        dest = Path(CONFIG_FILE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w") as f:
            new_parser.write(f)

        log(f"Config imported (basic) to: {dest}", "OK")
        log("Note: Install dependencies for full format conversion", "INFO")


# =============================================================================
# INTERACTIVE SETUP
# =============================================================================


def interactive_setup():
    """Run interactive setup wizard.

    Uses whiptail dialogs on Raspberry Pi, falls back to numbered menus.
    """
    from meshing_around_clients.setup.whiptail import (
        inputbox,
        menu,
        msgbox,
        radiolist,
    )

    print_banner()

    config = load_config()

    # Platform detection
    pi_info = ""
    try:
        from meshing_around_clients.setup.pi_utils import (
            get_pi_model,
            get_recommended_connection_mode,
            is_raspberry_pi,
        )

        if is_raspberry_pi():
            model = get_pi_model()
            rec_mode = get_recommended_connection_mode()
            pi_info = f"Detected: {model}\nRecommended connection: {rec_mode}"
            log(pi_info, "INFO")
    except ImportError:
        pass

    # Regional profile selection
    profiles = list_profiles()
    if profiles:
        profile_items = [
            (p["id"], f"{p['name']} - {p['description']}")
            for p in profiles
        ]
        profile_items.append(("skip", "Skip - configure manually"))

        profile_choice = menu("Select Your Region", profile_items, default="skip")

        if profile_choice and profile_choice != "skip":
            profile = load_profile(profile_choice)
            if profile:
                apply_profile(config, profile)
                # Show what was applied
                profile_name = profile.get("profile", "name", fallback=profile_choice)
                rec_hw = profile.get("profile", "recommended_hardware", fallback="")
                topic = profile.get("mqtt", "topic_root", fallback="msh/US")
                channels = profile.get("mqtt", "channels", fallback="LongFast")
                msgbox(
                    f"Profile: {profile_name}\n"
                    f"Topic root: {topic}\n"
                    f"Channels: {channels}\n"
                    + (f"Recommended hardware: {rec_hw}\n" if rec_hw else "")
                    + "\nYou can customize further in the next steps.",
                    title="Profile Applied",
                )

    # Hardware selection
    # Pre-select recommended hardware from profile if available
    rec_hw_list = []
    if config.has_option("interface", "hardware_model"):
        rec_hw_list = [config.get("interface", "hardware_model")]
    elif profiles and profile_choice and profile_choice != "skip":
        profile = load_profile(profile_choice)
        if profile and profile.has_option("profile", "recommended_hardware"):
            rec_hw_list = [
                h.strip()
                for h in profile.get("profile", "recommended_hardware").split(",")
            ]

    hw_items = [
        ("TBEAM", "LILYGO T-Beam (ESP32, GPS)", "TBEAM" in rec_hw_list),
        ("TLORA", "LILYGO T-Lora (ESP32, compact)", "TLORA" in rec_hw_list),
        ("TECHO", "LILYGO T-Echo (nRF52840, e-ink)", "TECHO" in rec_hw_list),
        ("TDECK", "LILYGO T-Deck (ESP32-S3, keyboard)", "TDECK" in rec_hw_list),
        ("HELTEC", "Heltec LoRa 32 (ESP32, OLED)", "HELTEC" in rec_hw_list),
        ("RAK4631", "RAK WisBlock 4631 (nRF52840)", "RAK4631" in rec_hw_list),
        ("STATION_G2", "Station G2 (ESP32-S3, high-power)", "STATION_G2" in rec_hw_list),
        ("none", "No radio hardware (MQTT/Demo)", False),
        ("other", "Other / not sure", not rec_hw_list),
    ]

    hw_choice = radiolist("Select Your Radio Hardware", hw_items)
    if hw_choice is None:
        return

    if hw_choice not in ("none", "other"):
        config.set("interface", "hardware_model", hw_choice)

    # Set connection type default based on hardware
    if hw_choice == "none":
        conn_default = "mqtt"
    elif hw_choice == "other":
        conn_default = "auto"
    else:
        conn_default = "serial"

    # Connection type
    conn_items = [
        ("serial", "Serial (USB radio connected)", conn_default == "serial"),
        ("tcp", "TCP (Remote device, protobuf port)", False),
        ("http", "HTTP (meshtasticd HTTP API)", False),
        ("mqtt", "MQTT (No radio, connect via broker)", conn_default == "mqtt"),
        ("auto", "Auto-detect", conn_default == "auto"),
    ]

    conn_type = radiolist("Connection Type", conn_items)
    if conn_type is None:
        return
    config.set("interface", "type", conn_type)

    if conn_type == "serial":
        ports = detect_serial_ports()
        if ports:
            log(f"Detected ports: {', '.join(ports)}", "INFO")
        port = inputbox("Serial port", default="auto-detect")
        if port and port != "auto-detect":
            config.set("interface", "port", port)

    elif conn_type == "tcp":
        tcp_items = [
            ("local", "Local meshtasticd (127.0.0.1:4403)"),
            ("remote", "Remote device via HTTP (no interference with web UI)"),
        ]
        tcp_target = menu("TCP Target", tcp_items, default="local")
        if tcp_target == "remote":
            host = inputbox(
                "Remote device IP or hostname",
                default="192.168.1.1",
            )
            if host:
                # Use HTTP for remote nodes — stateless, won't interfere with web UI
                config.set("interface", "type", "http")
                config.set("interface", "hostname", host)
                config.set("interface", "http_url", f"http://{host}")
        else:
            host = "127.0.0.1"
            config.set("interface", "hostname", host)

    elif conn_type == "http":
        url = inputbox("meshtasticd HTTP URL", default="http://meshtastic.local")
        if url:
            config.set("interface", "http_url", url)

    elif conn_type == "mqtt":
        config.set("mqtt", "enabled", "true")

        # Use profile defaults if a profile was applied, otherwise use standard defaults
        default_broker = config.get("mqtt", "broker", fallback="mqtt.meshtastic.org")
        default_topic = config.get("mqtt", "topic_root", fallback="msh/US")
        default_channels = config.get("mqtt", "channels", fallback="LongFast,meshforge")

        broker = inputbox("MQTT broker", default=default_broker)
        if broker:
            config.set("mqtt", "broker", broker)

        topic = inputbox("MQTT topic root", default=default_topic)
        if topic:
            config.set("mqtt", "topic_root", topic)

        channels = inputbox("MQTT channels (comma-separated)", default=default_channels)
        if channels:
            config.set("mqtt", "channels", channels)
            first_channel = channels.split(",")[0].strip()
            config.set("mqtt", "channel", first_channel)

    # Interface mode
    mode_items = [
        ("tui", "TUI (Terminal)", True),
        ("headless", "Headless (API only)", False),
    ]

    mode = radiolist("Interface Mode", mode_items)
    if mode is None:
        return
    config.set("features", "mode", mode)

    # Save config with restrictive permissions
    save_config(config)

    msgbox(
        f"Configuration saved to {CONFIG_FILE}\n\nRun 'python3 mesh_client.py' to start.",
        title="Setup Complete",
    )


# =============================================================================
# CONFIG EDITOR & UPDATE MENUS
# =============================================================================


def _find_editor() -> str:
    """Find an available text editor, preferring nano."""
    for editor in ("nano", "vi", "vim"):
        if shutil.which(editor):
            return editor
    return ""


def _has_systemd_service() -> bool:
    """Check if mesh-client.service is installed in systemd."""
    return Path("/etc/systemd/system/mesh-client.service").exists()


def _view_logs() -> None:
    """View logs using journalctl (preferred) or fall back to less/tail on log file."""
    if _has_systemd_service() and shutil.which("journalctl"):
        log("Opening service logs via journalctl...", "INFO")
        less = shutil.which("less")
        if less:
            subprocess.run(["bash", "-c", "journalctl -u mesh-client.service --no-pager -n 200 | less"])
        else:
            subprocess.run(["journalctl", "-u", "mesh-client.service", "--no-pager", "-n", "200"])
    else:
        log_path = LOG_FILE
        if not log_path.exists():
            log("No log file found yet. Run the client first.", "WARN")
            return
        less = shutil.which("less")
        if less:
            subprocess.run([less, str(log_path)])
        else:
            subprocess.run(["tail", "-n", "200", str(log_path)])


def _follow_logs() -> None:
    """Follow live logs using journalctl -f or fall back to tail -f."""
    if _has_systemd_service() and shutil.which("journalctl"):
        log("Following service logs (Ctrl+C to stop)...", "INFO")
        try:
            subprocess.run(["journalctl", "-u", "mesh-client.service", "-f"])
        except KeyboardInterrupt:
            pass
    else:
        log_path = LOG_FILE
        if not log_path.exists():
            log("No log file found yet. Run the client first.", "WARN")
            return
        log("Following log file (Ctrl+C to stop)...", "INFO")
        try:
            subprocess.run(["tail", "-f", str(log_path)])
        except KeyboardInterrupt:
            pass


def logs_menu(config: ConfigParser):
    """Interactive submenu for log viewing and logging settings.

    Changes are saved to mesh_client.ini and applied immediately.
    Returns "exit" if user chose exit, None otherwise.
    """
    from meshing_around_clients.setup.whiptail import menu as wt_menu, msgbox, radiolist, yesno

    while True:
        items = [
            ("view", "View logging settings"),
            ("level", "Change log level"),
            ("toggle", "Toggle logging on/off"),
            ("system", "View system log"),
            ("messages", "View message log"),
            ("journal", "View service logs (journalctl)"),
            ("follow", "Follow live logs (journalctl -f)"),
            ("e", "Exit"),
        ]
        choice = wt_menu("Logs", items)

        if choice is None:
            return None
        if choice == "e":
            return "exit"

        if choice == "view":
            enabled = config.get("logging", "enabled", fallback="true")
            level = config.get("logging", "level", fallback="INFO")
            log_file = config.get("logging", "file", fallback="logs/mesh_client.log")
            max_size = config.get("logging", "max_size_mb", fallback="10")
            backups = config.get("logging", "backup_count", fallback="3")
            msg_enabled = config.get("logging", "message_log_enabled", fallback="true")
            msg_file = config.get("logging", "message_log_file", fallback="logs/mesh_messages.log")

            info = (
                f"Logging enabled:  {enabled}\n"
                f"Log level:        {level}\n"
                f"Log file:         {log_file}\n"
                f"Max size:         {max_size} MB\n"
                f"Backup count:     {backups}\n"
                f"Message log:      {msg_enabled}\n"
                f"Message log file: {msg_file}"
            )
            msgbox(info, title="Current Logging Settings")

        elif choice == "level":
            current = config.get("logging", "level", fallback="INFO").upper()
            level_items = [
                ("DEBUG", "Verbose debug output", current == "DEBUG"),
                ("INFO", "Normal operation (default)", current == "INFO"),
                ("WARNING", "Warnings and errors only", current == "WARNING"),
                ("ERROR", "Errors only", current == "ERROR"),
            ]
            selected = radiolist("Log Level", level_items)
            if selected is not None:
                config.set("logging", "level", selected)
                save_config(config)
                setup_logging(config)
                log(f"Log level changed to {selected}", "OK")

        elif choice == "toggle":
            current = config.getboolean("logging", "enabled", fallback=True)
            result = yesno(
                "Enable logging?" if not current else "Logging is currently ON. Disable it?",
                default_yes=not current,
            )
            if result is not None:
                new_value = "true" if result else "false"
                # If logging was ON and user confirmed disable, turn off
                # If logging was OFF and user confirmed enable, turn on
                if current:
                    # Question was "disable it?" — yes means disable
                    new_value = "false" if result else "true"
                else:
                    # Question was "enable?" — yes means enable
                    new_value = "true" if result else "false"
                config.set("logging", "enabled", new_value)
                save_config(config)
                setup_logging(config)
                state = "enabled" if new_value == "true" else "disabled"
                log(f"Logging {state}", "OK")

        elif choice == "system":
            log_path = Path(config.get("logging", "file", fallback="logs/mesh_client.log"))
            if not log_path.is_absolute():
                log_path = SCRIPT_DIR / log_path
            if not log_path.exists():
                log("No system log found yet. Run the client first.", "WARN")
            else:
                less = shutil.which("less")
                if less:
                    subprocess.run([less, str(log_path)])
                else:
                    subprocess.run(["tail", "-n", "200", str(log_path)])

        elif choice == "messages":
            msg_path = Path(config.get("logging", "message_log_file", fallback="logs/mesh_messages.log"))
            if not msg_path.is_absolute():
                msg_path = SCRIPT_DIR / msg_path
            if not msg_path.exists():
                log("No message log found yet. Run the client first.", "WARN")
            else:
                less = shutil.which("less")
                if less:
                    subprocess.run([less, str(msg_path)])
                else:
                    subprocess.run(["tail", "-n", "200", str(msg_path)])

        elif choice == "journal":
            _view_logs()

        elif choice == "follow":
            _follow_logs()


def update_menu(config: ConfigParser):
    """Interactive menu for updating/reinstalling meshing_around_meshforge and meshing-around.

    Uses whiptail dialogs on Raspberry Pi, falls back to numbered menus.
    Returns "exit" if user chose exit, None otherwise.
    """
    from meshing_around_clients.setup.whiptail import menu as wt_menu, yesno

    items = [
        ("check", "Check for updates"),
        ("update", "Update (git pull)"),
        ("rollback", "Rollback to previous version"),
        ("deps", "Reinstall dependencies"),
        ("upstream", "Update meshing-around (upstream)"),
        ("clone", "Install meshing-around (clone)"),
        ("remove", "Remove meshing-around"),
        ("e", "Exit"),
    ]

    while True:
        choice = wt_menu("Update / Reinstall", items)

        if choice is None:
            return None
        if choice == "e":
            return "exit"

        # Most options need system_maintenance imports
        if choice in ("check", "update", "rollback", "upstream", "clone", "remove"):
            try:
                from meshing_around_clients.setup.system_maintenance import (
                    check_for_updates,
                    clone_meshing_around,
                    find_meshing_around,
                    list_recent_versions,
                    rollback_to_version,
                    update_meshforge,
                    update_upstream,
                )
            except ImportError:
                log("Cannot import update modules — dependencies may not be installed.", "ERROR")
                log("Use 'Reinstall dependencies' first.", "INFO")
                continue

        if choice == "check":
            log("Checking for updates...", "INFO")
            has_updates, message, commits = check_for_updates(SCRIPT_DIR)
            if has_updates:
                log(f"Updates available: {message}", "WARN")
            else:
                log(message, "OK")

        elif choice == "update":
            log("Updating meshing_around_meshforge...", "INFO")
            result = update_meshforge(SCRIPT_DIR)
            if result.success:
                log(result.message, "OK")
                if result.requires_restart:
                    log("Restart recommended to apply changes.", "WARN")
            else:
                log(result.message, "ERROR")
                for err in result.errors:
                    log(f"  {err[:100]}", "ERROR")

        elif choice == "rollback":
            versions = list_recent_versions(SCRIPT_DIR, count=10)
            if not versions:
                log("Could not retrieve version history.", "ERROR")
                continue
            # Build menu items: hash — date — subject
            ver_items = []
            for short_hash, date_str, subject in versions:
                label = short_hash
                desc = f"{date_str}  {subject[:50]}"
                ver_items.append((label, desc))
            selected = wt_menu("Select version to rollback to", ver_items)
            if selected is None:
                continue
            if not yesno(
                f"Roll back to {selected}? You can return to latest with 'Update (git pull)'.",
                default_yes=False,
            ):
                continue
            log(f"Rolling back to {selected}...", "INFO")
            result = rollback_to_version(SCRIPT_DIR, selected)
            if result.success:
                log(result.message, "OK")
                if result.requires_restart:
                    log("Restart recommended to apply changes.", "WARN")
                log("To return to the latest version, use 'Update (git pull)'.", "INFO")
            else:
                log(result.message, "ERROR")
                for err in result.errors:
                    log(f"  {err[:100]}", "ERROR")

        elif choice == "deps":
            missing = get_missing_deps(config)
            if missing:
                log(f"Installing missing: {', '.join(missing)}", "INFO")
                use_venv = config.getboolean("advanced", "use_venv", fallback=True)
                if install_dependencies(missing, use_venv):
                    log("Dependencies installed.", "OK")
                else:
                    log("Installation failed.", "ERROR")
            else:
                if yesno("All dependencies present. Reinstall all?", default_yes=False):
                    all_deps = list(CORE_DEPS)
                    for dep_list in OPTIONAL_DEPS.values():
                        all_deps.extend(dep_list)
                    all_deps = list(set(all_deps))
                    log(f"Reinstalling: {', '.join(all_deps)}", "INFO")
                    use_venv = config.getboolean("advanced", "use_venv", fallback=True)
                    if install_dependencies(all_deps, use_venv):
                        log("Dependencies reinstalled.", "OK")
                    else:
                        log("Reinstallation failed.", "ERROR")

        elif choice == "upstream":
            log("Updating meshing-around...", "INFO")
            result = update_upstream()
            if result.success:
                log(result.message, "OK")
            else:
                log(result.message, "ERROR")

        elif choice == "clone":
            log("Installing meshing-around...", "INFO")
            result = clone_meshing_around()
            if result.success:
                log(result.message, "OK")
            else:
                log(result.message, "ERROR")

        elif choice == "remove":
            ma_path = find_meshing_around()
            if ma_path is None:
                log("meshing-around installation not found.", "WARN")
                continue
            log(f"Found meshing-around at: {ma_path}", "INFO")
            if yesno(f"Remove {ma_path}? This cannot be undone.", default_yes=False):
                try:
                    shutil.rmtree(str(ma_path))
                    log("meshing-around removed.", "OK")
                except OSError as e:
                    log(f"Failed to remove: {e}", "ERROR")


# =============================================================================
# LAUNCHER MENU
# =============================================================================


def _ensure_local_broker() -> None:
    """Check if a local MQTT broker (Mosquitto) is running; offer to install."""
    # Quick connectivity check on localhost:1883
    try:
        with socket.create_connection(("localhost", 1883), timeout=2):
            return  # Broker is already running
    except (ConnectionRefusedError, OSError):
        pass

    log("No local MQTT broker detected on localhost:1883", "WARN")

    # Check if mosquitto is installed but not running
    mosquitto_bin = shutil.which("mosquitto")
    if mosquitto_bin:
        log("Mosquitto is installed but not running", "INFO")
        try:
            from meshing_around_clients.setup.whiptail import yesno

            if yesno("Start Mosquitto service?"):
                subprocess.run(
                    ["sudo", "systemctl", "start", "mosquitto"], timeout=30
                )
                time.sleep(1)
                try:
                    with socket.create_connection(("localhost", 1883), timeout=2):
                        log("Mosquitto started", "OK")
                        return
                except (ConnectionRefusedError, OSError):
                    log("Mosquitto started but port not ready — check config", "WARN")
        except ImportError:
            log("Run: sudo systemctl start mosquitto", "INFO")
        return

    # Not installed — offer to install (Debian/Ubuntu only)
    if not shutil.which("apt-get"):
        log("Install a MQTT broker (e.g. mosquitto) to use local mode", "INFO")
        return

    try:
        from meshing_around_clients.setup.whiptail import yesno

        if yesno("Install Mosquitto MQTT broker?"):
            log("Installing mosquitto...", "INFO")
            result = subprocess.run(
                ["sudo", "apt-get", "install", "-y", "mosquitto", "mosquitto-clients"],
                timeout=120,
            )
            if result.returncode != 0:
                log("Failed to install mosquitto", "ERROR")
                return
            subprocess.run(["sudo", "systemctl", "enable", "mosquitto"], timeout=30)
            subprocess.run(["sudo", "systemctl", "start", "mosquitto"], timeout=30)
            time.sleep(1)
            try:
                with socket.create_connection(("localhost", 1883), timeout=2):
                    log("Mosquitto installed and running", "OK")
            except (ConnectionRefusedError, OSError):
                log("Mosquitto installed — may need a reboot to start", "WARN")
    except ImportError:
        log("Run: sudo apt-get install -y mosquitto mosquitto-clients", "INFO")


def standalone_install(config: ConfigParser) -> None:
    """Full standalone install: all deps, config, log dirs."""
    use_venv = config.getboolean("advanced", "use_venv", fallback=True)

    print(f"\n{Colors.CYAN}{Colors.BOLD}Standalone Install{Colors.RESET}\n")

    # 1. Install ALL dependencies
    all_deps: list = list(CORE_DEPS)
    for dep_list in OPTIONAL_DEPS.values():
        all_deps.extend(dep_list)
    all_deps = list(set(all_deps))
    missing = [d for d in all_deps if not check_dependency(d)]
    if missing:
        log(f"Installing {len(missing)} packages: {', '.join(missing)}", "INFO")
        if not install_dependencies(missing, use_venv):
            log("Dependency installation failed", "ERROR")
            return
        log("All dependencies installed", "OK")
    else:
        log("All dependencies already installed", "OK")

    # 2. Generate config if missing
    if not CONFIG_FILE.exists():
        config.read_string(DEFAULT_CONFIG)
        save_config(config)
        log(f"Created config: {CONFIG_FILE}", "OK")
    else:
        log(f"Config exists: {CONFIG_FILE}", "OK")

    # 3. Create logs directory
    log_dir = SCRIPT_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    log(f"Log directory: {log_dir}", "OK")

    log("Standalone install complete — ready to run", "OK")


def launcher_menu(config: ConfigParser) -> bool:
    """Interactive launcher menu - shown when no mode flag is passed.

    Uses whiptail dialogs on Raspberry Pi, falls back to numbered menus.
    Returns True if the user selected a mode and the app ran, False to exit.
    """
    from meshing_around_clients.setup.whiptail import inputbox, menu as wt_menu

    items = [
        ("tui", "TUI Client (Terminal UI)"),
        ("mqtt", "MQTT Monitor"),
        ("mqtt-local", "MQTT Local Broker (no auth)"),
        ("demo", "Demo Mode"),
        ("profile", "Switch Regional Profile"),
        ("ini", "Edit mesh_client.ini"),
        ("logs", "Logs"),
        ("setup", "Setup Wizard"),
        ("update", "Update / Reinstall"),
        ("install", "Install Everything"),
        ("e", "Exit"),
    ]

    while True:
        choice = wt_menu("Meshing Around MeshForge", items, default="tui")

        if choice is None or choice == "e":
            return True

        if choice == "tui":
            config.set("features", "mode", "tui")
        elif choice == "mqtt":
            config.set("features", "mode", "tui")
            config.set("mqtt", "enabled", "true")
            config.set("interface", "type", "mqtt")
            broker = inputbox(
                "MQTT broker",
                default=config.get("mqtt", "broker", fallback="mqtt.meshtastic.org"),
            )
            if broker:
                # Parse embedded port from hostname (e.g. "host:1884")
                if ":" in broker:
                    parts = broker.rsplit(":", 1)
                    try:
                        port = int(parts[1])
                        config.set("mqtt", "broker", parts[0])
                        config.set("mqtt", "port", str(port))
                    except ValueError:
                        config.set("mqtt", "broker", broker)
                else:
                    config.set("mqtt", "broker", broker)
            topic = inputbox(
                "Topic root",
                default=config.get("mqtt", "topic_root", fallback="msh/US"),
            )
            if topic:
                config.set("mqtt", "topic_root", topic)
            channel = inputbox(
                "Channel",
                default=config.get("mqtt", "channel", fallback="LongFast"),
            )
            if channel:
                config.set("mqtt", "channel", channel)
        elif choice == "mqtt-local":
            config.set("features", "mode", "tui")
            config.set("mqtt", "enabled", "true")
            config.set("interface", "type", "mqtt")
            config.set("mqtt", "use_tls", "false")
            config.set("mqtt", "username", "")
            config.set("mqtt", "password", "")
            # Check if Mosquitto is installed and running locally
            _ensure_local_broker()
            broker = inputbox("MQTT broker", default="localhost")
            if broker:
                if ":" in broker:
                    parts = broker.rsplit(":", 1)
                    try:
                        port = int(parts[1])
                        config.set("mqtt", "broker", parts[0])
                        config.set("mqtt", "port", str(port))
                    except ValueError:
                        config.set("mqtt", "broker", broker)
                else:
                    config.set("mqtt", "broker", broker)
            port_str = inputbox("Port", default="1883")
            if port_str:
                config.set("mqtt", "port", port_str)
            topic = inputbox("Topic root", default="msh/local")
            if topic:
                config.set("mqtt", "topic_root", topic)
            channel = inputbox("Channel", default="meshforge")
            if channel:
                config.set("mqtt", "channel", channel)
        elif choice == "demo":
            config.set("advanced", "demo_mode", "true")
            config.set("features", "mode", "tui")
        elif choice == "profile":
            from meshing_around_clients.setup.whiptail import menu as profile_menu, msgbox as profile_msgbox

            profiles = list_profiles()
            if not profiles:
                profile_msgbox("No profiles found in profiles/ directory.", title="Profiles")
            else:
                profile_items = [
                    (p["id"], f"{p['name']} - {p['description']}")
                    for p in profiles
                ]
                pick = profile_menu("Select Regional Profile", profile_items)
                if pick:
                    profile = load_profile(pick)
                    if profile:
                        apply_profile(config, profile)
                        save_config(config)
                        pname = profile.get("profile", "name", fallback=pick)
                        profile_msgbox(
                            f"Profile '{pname}' applied and saved.\n"
                            f"Topic: {config.get('mqtt', 'topic_root', fallback='msh/US')}\n"
                            f"Channels: {config.get('mqtt', 'channels', fallback='LongFast')}",
                            title="Profile Applied",
                        )
            continue
        elif choice == "ini":
            editor = _find_editor()
            if not editor:
                log("No text editor found (nano, vi, vim). Install nano: sudo apt install nano", "ERROR")
            else:
                ini_path = CONFIG_FILE
                if not ini_path.exists():
                    from meshing_around_clients.setup.whiptail import yesno

                    log(f"{ini_path} not found.", "WARN")
                    if yesno("Create from default template?"):
                        try:
                            ini_path.write_text(DEFAULT_CONFIG)
                            os.chmod(str(ini_path), 0o600)
                            log(f"Created {ini_path}", "OK")
                        except OSError as e:
                            log(f"Failed to create config: {e}", "ERROR")
                            continue
                    else:
                        continue
                subprocess.run([editor, str(ini_path)])
            continue
        elif choice == "setup":
            interactive_setup()
            return True
        elif choice == "update":
            result = update_menu(config)
            if result == "exit":
                return True
            continue
        elif choice == "install":
            standalone_install(config)
            continue
        elif choice == "logs":
            result = logs_menu(config)
            if result == "exit":
                return True
            continue

        # For TUI modes: prompt for connection type
        if choice == "tui":
            from meshing_around_clients.setup.whiptail import radiolist

            current_type = config.get("interface", "type", fallback="auto")
            conn_items = [
                ("auto", "Auto-detect", current_type == "auto"),
                ("mqtt", "MQTT (No radio needed)", current_type == "mqtt"),
                ("serial", "Serial (USB radio)", current_type == "serial"),
                ("tcp", "TCP (Remote device)", current_type == "tcp"),
                ("http", "HTTP (Remote device API)", current_type == "http"),
                ("demo", "Demo mode (simulated)", False),
            ]
            selected = radiolist("Connection Type", conn_items)
            if selected is None:
                continue  # back to main menu
            if selected == "mqtt":
                config.set("interface", "type", "mqtt")
                config.set("mqtt", "enabled", "true")
            elif selected == "http":
                config.set("interface", "type", "http")
                hostname = config.get("interface", "hostname", fallback="")
                if hostname:
                    config.set("interface", "http_url", f"http://{hostname}")
            elif selected == "demo":
                config.set("interface", "type", "demo")
                config.set("advanced", "demo_mode", "true")
            else:
                config.set("interface", "type", selected)

        # Run the selected mode, then loop back to the launcher menu.
        try:
            run_application(config)
        except (KeyboardInterrupt, SystemExit):
            pass  # Ctrl+C returns to menu
        # Flush stale terminal input so the menu doesn't auto-select
        try:
            import termios as _termios

            _termios.tcflush(sys.stdin, _termios.TCIFLUSH)
        except (ImportError, OSError, ValueError):
            pass
        continue


# =============================================================================
# MAIN APPLICATION
# =============================================================================


def check_system():
    """Check system requirements."""
    log("Checking system requirements...", "INFO")

    # Python version
    if not check_python_version():
        log(f"Python 3.8+ required, found {sys.version}", "ERROR")
        return False
    log(f"Python {sys.version.split()[0]}", "OK")

    # Platform
    import platform

    log(f"Platform: {platform.system()} {platform.release()}", "OK")

    # Check for Pi
    try:
        with open("/proc/cpuinfo", "r") as f:
            if "Raspberry Pi" in f.read():
                log("Running on Raspberry Pi", "OK")
    except OSError:
        pass

    return True


def run_application(config: ConfigParser):
    """Run the main application."""
    mode = config.get("features", "mode", fallback="tui")
    log(f"Starting in {mode} mode...", "INFO")
    demo_mode = config.getboolean("advanced", "demo_mode", fallback=False)

    # Detect connection type
    conn_type = detect_connection_type(config)
    log(f"Connection type: {conn_type}", "INFO")

    # Import and run appropriate interface
    try:
        # Add package to path
        sys.path.insert(0, str(SCRIPT_DIR))

        from meshing_around_clients.core.config import Config
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI, MockMeshtasticAPI

        # Create config object from ini
        app_config = Config(str(CONFIG_FILE))

        # Update config from ini
        app_config.interface.type = conn_type
        if conn_type == "serial":
            port = config.get("interface", "port", fallback="")
            app_config.interface.port = port
        elif conn_type == "tcp":
            app_config.interface.hostname = config.get("interface", "hostname", fallback="")
        elif conn_type == "http":
            app_config.interface.http_url = config.get("interface", "http_url", fallback="")
            # Also set hostname as fallback
            app_config.interface.hostname = config.get("interface", "hostname", fallback="")

        # Determine if demo mode
        if demo_mode or conn_type == "demo":
            demo_mode = True

        if mode == "tui":
            force_whiptail = config.getboolean("features", "force_whiptail", fallback=False)
            if force_whiptail:
                from meshing_around_clients.tui.whiptail_tui import WhiptailTUI

                tui = WhiptailTUI(config=app_config, demo_mode=demo_mode)
            else:
                try:
                    from meshing_around_clients.tui.app import MeshingAroundTUI

                    tui = MeshingAroundTUI(config=app_config, demo_mode=demo_mode)
                except ImportError:
                    from meshing_around_clients.tui.whiptail_tui import WhiptailTUI

                    tui = WhiptailTUI(config=app_config, demo_mode=demo_mode)
            tui.run_interactive()

        elif mode == "headless":
            # Just run the API and keep alive
            log("Running in headless mode (API only)", "INFO")
            if demo_mode:
                api = MockMeshtasticAPI(app_config)
            else:
                api = MeshtasticAPI(app_config)

            api.connect()
            log("Connected. Press Ctrl+C to exit.", "OK")

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                api.disconnect()

    except ImportError as e:
        log(f"Missing dependency for {mode} mode: {e}", "ERROR")
        log("Try running with --setup or --check", "INFO")
        return False
    except SystemExit:
        log(f"{mode} mode exited", "INFO")
        return True
    except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
        log(f"{mode} mode error: {e}", "ERROR")
        import traceback

        traceback.print_exc()
        return False

    return True


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Meshing-Around Standalone Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 mesh_client.py              # Auto-detect and run
  python3 mesh_client.py --tui        # Force TUI mode
  python3 mesh_client.py --setup      # Interactive setup
  python3 mesh_client.py --demo       # Demo mode (no hardware)
  python3 mesh_client.py --check      # Check dependencies only
  python3 mesh_client.py --profile hawaii     # Apply regional profile
  python3 mesh_client.py --list-profiles      # List available profiles
  python3 mesh_client.py --import-config /path/to/config.ini  # Import upstream config
        """,
    )

    parser.add_argument("--setup", action="store_true", help="Run interactive setup")
    parser.add_argument("--check", action="store_true", help="Check dependencies only")
    parser.add_argument("--tui", action="store_true", help="Force TUI mode")
    parser.add_argument("--whiptail", action="store_true", help="Force whiptail TUI mode (Pi-style)")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode")
    parser.add_argument("--no-venv", action="store_true", help="Don't use virtual environment")
    parser.add_argument("--install-deps", action="store_true", help="Install dependencies and exit")
    parser.add_argument("--import-config", metavar="PATH", help="Import config from upstream meshing-around config.ini")
    parser.add_argument("--profile", metavar="NAME", help="Apply a regional profile (e.g., hawaii, europe, local_broker)")
    parser.add_argument("--list-profiles", action="store_true", help="List available regional profiles")
    parser.add_argument("--check-config", action="store_true", help="Validate config file and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    args = parser.parse_args()

    # Disable colors if not a TTY
    if not sys.stdout.isatty():
        Colors.disable()

    # Show banner
    print_banner()

    # Check Python version
    if not check_python_version():
        log(f"Python 3.8+ required, found {sys.version}", "ERROR")
        sys.exit(1)

    # Interactive setup
    if args.setup:
        interactive_setup()
        sys.exit(0)

    # List available profiles
    if args.list_profiles:
        profiles = list_profiles()
        if not profiles:
            log("No profiles found in profiles/ directory", "WARN")
        else:
            log(f"Available profiles ({len(profiles)}):", "INFO")
            for p in profiles:
                print(f"  {p['id']:20s} {p['name']} - {p['description']}")
        sys.exit(0)

    # Apply a profile
    if args.profile:
        config = load_config()
        profile = load_profile(args.profile)
        if profile:
            apply_profile(config, profile)
            save_config(config)
            profile_name = profile.get("profile", "name", fallback=args.profile)
            log(f"Profile '{profile_name}' applied to {CONFIG_FILE}", "OK")
        else:
            log(f"Profile '{args.profile}' not found. Use --list-profiles to see options.", "ERROR")
            sys.exit(1)
        sys.exit(0)

    # Import upstream config
    if args.import_config:
        import_upstream_config(args.import_config)
        sys.exit(0)

    # Load config
    config = load_config()

    # Set up centralized logging with rotation
    setup_logging(config)

    # Config validation (--check-config)
    if args.check_config:
        try:
            from meshing_around_clients.core.config import Config as TypedConfig

            typed_config = TypedConfig(config_path=config.get("advanced", "config_path", fallback=None))
            issues = typed_config.validate()
            if issues:
                log("Config validation found issues:", "WARN")
                for issue in issues:
                    log(f"  - {issue}", "WARN")
                sys.exit(1)
            else:
                log("Config validation passed — no issues found", "OK")
                sys.exit(0)
        except (ImportError, Exception) as e:
            log(f"Config validation error: {e}", "ERROR")
            sys.exit(1)

    # Virtual environment handling
    use_venv = config.getboolean("advanced", "use_venv", fallback=True) and not args.no_venv

    if use_venv and not os.environ.get("VIRTUAL_ENV"):
        if setup_venv():
            activate_venv()

    # Check dependencies
    missing = get_missing_deps(config)

    if args.check:
        if missing:
            log(f"Missing dependencies: {', '.join(missing)}", "WARN")
            log("Run with --install-deps to install", "INFO")
        else:
            log("All dependencies satisfied", "OK")
        sys.exit(0 if not missing else 1)

    # Install dependencies if needed
    if missing:
        auto_install = config.getboolean("advanced", "auto_install_deps", fallback=False)

        if args.install_deps or auto_install:
            if not check_internet():
                log("No internet connection for dependency installation", "ERROR")
                sys.exit(1)

            if not install_dependencies(missing, use_venv):
                log("Failed to install dependencies", "ERROR")
                sys.exit(1)
        elif sys.stdin.isatty():
            # Interactive prompt — let user decide
            log(f"Missing dependencies: {', '.join(missing)}", "WARN")
            try:
                answer = input(f"{Colors.CYAN}Install now? [Y/n]:{Colors.RESET} ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print()
                sys.exit(1)
            if answer in ("", "y", "yes"):
                if not check_internet():
                    log("No internet connection for dependency installation", "ERROR")
                    sys.exit(1)
                if not install_dependencies(missing, use_venv):
                    log("Failed to install dependencies", "ERROR")
                    sys.exit(1)
            else:
                log("Skipping — select 'Install Everything' from the launcher", "INFO")
        else:
            log(f"Missing dependencies: {', '.join(missing)}", "ERROR")
            log("Run with --install-deps to install", "INFO")
            sys.exit(1)

    if args.install_deps:
        log("Dependencies installed. Run without --install-deps to start.", "OK")
        sys.exit(0)

    # Apply command line overrides
    has_mode_flag = args.tui or args.whiptail or args.demo

    if args.demo:
        config.set("advanced", "demo_mode", "true")

    if args.tui or args.whiptail:
        config.set("features", "mode", "tui")

    if args.whiptail:
        config.set("features", "force_whiptail", "true")

    # Run system checks
    if not check_system():
        sys.exit(1)

    # Show launcher menu if no mode flag was passed and we have a TTY
    try:
        is_interactive = sys.stdin.isatty()
    except (ValueError, OSError):
        is_interactive = False

    log(f"Terminal detection: stdin.isatty={is_interactive}", "INFO")

    if is_interactive:
        # Always show the launcher menu for interactive terminals.
        # CLI flags (--tui, --web, --demo) pre-set config defaults but
        # the menu still appears so users can change their mind.
        log("Loading launcher menu...", "INFO")
        try:
            success = launcher_menu(config)
            sys.exit(0 if success else 1)
        except KeyboardInterrupt:
            log("Interrupted by user", "INFO")
            sys.exit(0)
    else:
        # Non-interactive (piped, cron, systemd) — launch directly
        if not has_mode_flag:
            # On Pi Zero 2W, auto-default to MQTT/TUI mode (recommended
            # for resource-constrained boards without a display).
            try:
                from meshing_around_clients.setup.pi_utils import is_pi_zero_2w

                if is_pi_zero_2w():
                    log("Pi Zero 2W detected — defaulting to MQTT/TUI mode", "INFO")
                    config.set("features", "mode", "tui")
                    config.set("interface", "type", "mqtt")
                    config.set("mqtt", "enabled", "true")
                    has_mode_flag = True
            except ImportError:
                pass

            if not has_mode_flag:
                log("No TTY detected — skipping launcher menu (use --tui or --demo)", "WARN")

        try:
            success = run_application(config)
            sys.exit(0 if success else 1)
        except KeyboardInterrupt:
            log("Interrupted by user", "INFO")
            sys.exit(0)


if __name__ == "__main__":
    main()

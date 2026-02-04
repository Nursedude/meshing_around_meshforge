#!/usr/bin/env python3
"""
Meshing-Around Standalone Client
================================
Zero-dependency bootstrap launcher for mesh network monitoring.

Supports:
- Direct radio connection (serial/USB)
- TCP connection to remote Meshtastic device
- MQTT connection (no radio required)
- BLE connection

Works on:
- Raspberry Pi (Zero 2W, 3, 4, 5)
- Any Linux system
- Headless/SSH environments

Usage:
    python3 mesh_client.py              # Auto-detect and run
    python3 mesh_client.py --tui        # Force TUI mode
    python3 mesh_client.py --web        # Force Web mode
    python3 mesh_client.py --setup      # Run interactive setup
    python3 mesh_client.py --check      # Check dependencies only

Configuration:
    Edit mesh_client.ini for all options
"""

import os
import sys
import subprocess
import socket
import time
from pathlib import Path
from configparser import ConfigParser
from typing import Optional, Dict, List, Tuple, Any

# Version
VERSION = "0.5.0-beta"

# Paths
SCRIPT_DIR = Path(__file__).parent.absolute()
CONFIG_FILE = SCRIPT_DIR / "mesh_client.ini"
VENV_DIR = SCRIPT_DIR / ".venv"
LOG_FILE = SCRIPT_DIR / "mesh_client.log"

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

    @classmethod
    def disable(cls):
        """Disable colors for non-TTY output."""
        for attr in ['RESET', 'BOLD', 'RED', 'GREEN', 'YELLOW', 'BLUE', 'CYAN']:
            setattr(cls, attr, '')


def log(msg: str, level: str = "INFO"):
    """Simple logging to file and stdout."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [{level}] {msg}"

    # Write to log file
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_msg + "\n")
    except OSError:
        pass

    # Print to stdout with colors
    color = {
        "INFO": Colors.CYAN,
        "OK": Colors.GREEN,
        "WARN": Colors.YELLOW,
        "ERROR": Colors.RED
    }.get(level, Colors.RESET)

    print(f"{color}[{level}]{Colors.RESET} {msg}")


def print_banner():
    """Print startup banner."""
    banner = f"""
{Colors.CYAN}╔══════════════════════════════════════════════════════════════╗
║  {Colors.BOLD}MESHING-AROUND CLIENT{Colors.RESET}{Colors.CYAN}                                       ║
║  Standalone Mesh Network Monitor                               ║
║  Version {VERSION}                                                 ║
╚══════════════════════════════════════════════════════════════╝{Colors.RESET}
"""
    print(banner)


def run_cmd(cmd: List[str], capture: bool = True, timeout: int = 300) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except OSError as e:
        return -1, "", str(e)


def check_internet() -> bool:
    """Check if we have internet connectivity."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
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
    "web": ["fastapi", "uvicorn", "jinja2", "python-multipart"],
    "mqtt": ["paho-mqtt"],
    "meshtastic": ["meshtastic", "pypubsub"],
    "ble": ["bleak"],
}


# Mapping from pip package names to importable module names
_IMPORT_NAME_MAP = {
    "paho-mqtt": "paho.mqtt.client",
    "python-multipart": "multipart",
    "pypubsub": "pubsub",
}



def check_dependency(package: str) -> bool:
    """Check if a Python package is installed."""
    try:
        import_name = _IMPORT_NAME_MAP.get(package, package.replace("-", "_").split("[")[0])
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
    if config.getboolean("features", "web_server", fallback=False):
        for dep in OPTIONAL_DEPS["web"]:
            if not check_dependency(dep):
                missing.append(dep)

    conn_type = config.get("connection", "type", fallback="auto")

    if conn_type == "mqtt" or config.getboolean("connection", "mqtt_enabled", fallback=False):
        for dep in OPTIONAL_DEPS["mqtt"]:
            if not check_dependency(dep):
                missing.append(dep)

    if conn_type in ["serial", "tcp", "auto"]:
        if config.getboolean("connection", "meshtastic_enabled", fallback=True):
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

[connection]
# Connection type: auto, serial, tcp, mqtt, ble
# - auto: Try serial first, then tcp, then mqtt
# - serial: Direct USB/serial connection to radio
# - tcp: TCP connection to remote Meshtastic device
# - mqtt: MQTT broker connection (no radio needed)
# - ble: Bluetooth LE connection
type = auto

# Serial settings (for type=serial or auto)
serial_port = auto
# Set to specific port like /dev/ttyUSB0, /dev/ttyACM0, or "auto" for detection
serial_baud = 115200

# TCP settings (for type=tcp)
tcp_host =
tcp_port = 4403

# MQTT settings (for type=mqtt or mqtt_enabled=true)
mqtt_enabled = false
mqtt_broker = mqtt.meshtastic.org
mqtt_port = 1883
mqtt_use_tls = false
mqtt_username = meshdev
mqtt_password = large4cats
mqtt_topic_root = msh/US
mqtt_channel = LongFast
# Your node ID for MQTT (leave empty to receive only)
mqtt_node_id =

# BLE settings (for type=ble)
ble_address =
# MAC address like AA:BB:CC:DD:EE:FF or "scan" for discovery

# Connection behavior
auto_reconnect = true
reconnect_delay = 5
connection_timeout = 30

# Enable meshtastic library (disable for MQTT-only mode)
meshtastic_enabled = true

[features]
# Main interface mode: tui, web, both, headless
mode = tui

# TUI settings
tui_enabled = true
tui_refresh_rate = 1.0
tui_mouse_support = false
tui_color_scheme = default

# Web server settings
web_server = false
web_host = 127.0.0.1
web_port = 8080
web_api_enabled = true
web_auth_enabled = false
web_username = admin
web_password =

# Features to enable/disable
messages_enabled = true
nodes_enabled = true
alerts_enabled = true
location_enabled = true
telemetry_enabled = true

[alerts]
# Master alert enable
enabled = true

# Emergency keyword detection
emergency_enabled = true
emergency_keywords = emergency,911,112,999,sos,help,mayday

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
file = mesh_client.log
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

# Auto-install missing dependencies
auto_install_deps = true

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


def load_config() -> ConfigParser:
    """Load or create configuration file."""
    config = ConfigParser()

    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
        log(f"Loaded config from {CONFIG_FILE}", "OK")
    else:
        # Create default config
        config.read_string(DEFAULT_CONFIG)
        save_config(config)
        log(f"Created default config at {CONFIG_FILE}", "OK")

    return config


def save_config(config: ConfigParser):
    """Save configuration to file with restricted permissions."""
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)
    os.chmod(CONFIG_FILE, 0o600)
    log(f"Saved config to {CONFIG_FILE}", "OK")


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
    conn_type = config.get("connection", "type", fallback="auto")

    if conn_type != "auto":
        return conn_type

    log("Auto-detecting connection type...", "INFO")

    # Check for serial ports first
    ports = detect_serial_ports()
    if ports:
        log(f"Found serial ports: {ports}", "OK")
        return "serial"

    # Check for TCP host configured
    tcp_host = config.get("connection", "tcp_host", fallback="")
    if tcp_host:
        log(f"TCP host configured: {tcp_host}", "INFO")
        return "tcp"

    # Fall back to MQTT if enabled
    if config.getboolean("connection", "mqtt_enabled", fallback=False):
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
        from meshing_around_clients.core.config_schema import ConfigLoader, UnifiedConfig
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
        dest = Path(CONFIG_PATH)
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
        if parser.has_section('interface'):
            new_parser.add_section('interface.1')
            for key, value in parser.items('interface'):
                new_parser.set('interface.1', key, value)

        # Copy general section
        if parser.has_section('general'):
            new_parser.add_section('general')
            for key, value in parser.items('general'):
                new_parser.set('general', key, value)

        # Copy MQTT if present
        for section in ['mqtt', 'emergencyHandler']:
            if parser.has_section(section):
                new_parser.add_section(section)
                for key, value in parser.items(section):
                    new_parser.set(section, key, value)

        # Save
        dest = Path(CONFIG_PATH)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, 'w') as f:
            new_parser.write(f)

        log(f"Config imported (basic) to: {dest}", "OK")
        log("Note: Install dependencies for full format conversion", "INFO")


# =============================================================================
# INTERACTIVE SETUP
# =============================================================================

def interactive_setup():
    """Run interactive setup wizard."""
    print_banner()
    print(f"{Colors.CYAN}Interactive Setup Wizard{Colors.RESET}\n")

    config = load_config()

    # Connection type
    print("Connection Options:")
    print("  1. Serial (USB radio connected)")
    print("  2. TCP (Remote Meshtastic device)")
    print("  3. MQTT (No radio, connect via broker)")
    print("  4. Auto-detect")

    choice = input("\nSelect connection type [4]: ").strip() or "4"

    conn_map = {"1": "serial", "2": "tcp", "3": "mqtt", "4": "auto"}
    conn_type = conn_map.get(choice, "auto")
    config.set("connection", "type", conn_type)

    if conn_type == "serial":
        ports = detect_serial_ports()
        if ports:
            print(f"\nDetected ports: {', '.join(ports)}")
        port = input("Serial port [auto]: ").strip() or "auto"
        config.set("connection", "serial_port", port)

    elif conn_type == "tcp":
        host = input("TCP host [192.168.1.1]: ").strip() or "192.168.1.1"
        config.set("connection", "tcp_host", host)

    elif conn_type == "mqtt":
        config.set("connection", "mqtt_enabled", "true")
        config.set("connection", "meshtastic_enabled", "false")

        broker = input("MQTT broker [mqtt.meshtastic.org]: ").strip() or "mqtt.meshtastic.org"
        config.set("connection", "mqtt_broker", broker)

        topic = input("MQTT topic root [msh/US]: ").strip() or "msh/US"
        config.set("connection", "mqtt_topic_root", topic)

    # Interface mode
    print("\nInterface Mode:")
    print("  1. TUI (Terminal)")
    print("  2. Web (Browser)")
    print("  3. Both")
    print("  4. Headless (API only)")

    mode_choice = input("\nSelect mode [1]: ").strip() or "1"
    mode_map = {"1": "tui", "2": "web", "3": "both", "4": "headless"}
    mode = mode_map.get(mode_choice, "tui")
    config.set("features", "mode", mode)

    if mode in ["web", "both"]:
        config.set("features", "web_server", "true")
        port = input("Web port [8080]: ").strip() or "8080"
        config.set("features", "web_port", port)

    # Save config with restrictive permissions
    save_config(config)

    print(f"\n{Colors.GREEN}Configuration saved to {CONFIG_FILE}{Colors.RESET}")
    print("Run 'python3 mesh_client.py' to start the client.")


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
            port = config.get("connection", "serial_port", fallback="auto")
            app_config.interface.port = "" if port == "auto" else port
        elif conn_type == "tcp":
            app_config.interface.hostname = config.get("connection", "tcp_host", fallback="")

        # Determine if demo mode
        if demo_mode or conn_type == "demo":
            demo_mode = True

        if mode == "tui":
            from meshing_around_clients.tui.app import MeshingAroundTUI
            tui = MeshingAroundTUI(config=app_config, demo_mode=demo_mode)
            tui.run_interactive()

        elif mode == "web":
            from meshing_around_clients.web.app import WebApplication
            web_app = WebApplication(config=app_config, demo_mode=demo_mode)
            host = config.get("features", "web_host", fallback="127.0.0.1")
            port = config.getint("features", "web_port", fallback=8080)
            web_app.run(host=host, port=port)

        elif mode == "both":
            # Run web in background, TUI in foreground
            # NOTE: WebApplication and MeshingAroundTUI each create their own
            # API instances internally. A shared API is not yet supported.
            import threading
            from meshing_around_clients.web.app import WebApplication
            from meshing_around_clients.tui.app import MeshingAroundTUI

            # Start web server in thread
            web_app = WebApplication(config=app_config, demo_mode=demo_mode)
            host = config.get("features", "web_host", fallback="127.0.0.1")
            port = config.getint("features", "web_port", fallback=8080)

            def run_web():
                import uvicorn
                uvicorn.run(web_app.app, host=host, port=port, log_level="warning")

            web_thread = threading.Thread(target=run_web, daemon=True)
            web_thread.start()
            log(f"Web server started on http://{host}:{port}", "OK")

            # Run TUI in main thread
            tui = MeshingAroundTUI(config=app_config, demo_mode=demo_mode)
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
        log(f"Import error: {e}", "ERROR")
        log("Try running with --setup or --check", "INFO")
        return False
    except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
        log(f"Application error: {e}", "ERROR")
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
  python3 mesh_client.py --web        # Force Web mode
  python3 mesh_client.py --setup      # Interactive setup
  python3 mesh_client.py --demo       # Demo mode (no hardware)
  python3 mesh_client.py --check      # Check dependencies only
  python3 mesh_client.py --import-config /path/to/config.ini  # Import upstream config
        """
    )

    parser.add_argument("--setup", action="store_true", help="Run interactive setup")
    parser.add_argument("--check", action="store_true", help="Check dependencies only")
    parser.add_argument("--tui", action="store_true", help="Force TUI mode")
    parser.add_argument("--web", action="store_true", help="Force Web mode")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode")
    parser.add_argument("--no-venv", action="store_true", help="Don't use virtual environment")
    parser.add_argument("--install-deps", action="store_true", help="Install dependencies and exit")
    parser.add_argument("--import-config", metavar="PATH",
                        help="Import config from upstream meshing-around config.ini")
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

    # Import upstream config
    if args.import_config:
        import_upstream_config(args.import_config)
        sys.exit(0)

    # Load config
    config = load_config()

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
        auto_install = config.getboolean("advanced", "auto_install_deps", fallback=True)

        if args.install_deps or auto_install:
            if not check_internet():
                log("No internet connection for dependency installation", "ERROR")
                sys.exit(1)

            if not install_dependencies(missing, use_venv):
                log("Failed to install dependencies", "ERROR")
                sys.exit(1)
        else:
            log(f"Missing dependencies: {', '.join(missing)}", "ERROR")
            log("Run with --install-deps to install", "INFO")
            sys.exit(1)

    if args.install_deps:
        log("Dependencies installed. Run without --install-deps to start.", "OK")
        sys.exit(0)

    # Apply command line overrides
    if args.demo:
        config.set("advanced", "demo_mode", "true")

    if args.tui:
        config.set("features", "mode", "tui")
    elif args.web:
        config.set("features", "mode", "web")
        config.set("features", "web_server", "true")

    # Run system checks
    if not check_system():
        sys.exit(1)

    # Run application
    try:
        success = run_application(config)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log("Interrupted by user", "INFO")
        sys.exit(0)


if __name__ == "__main__":
    main()

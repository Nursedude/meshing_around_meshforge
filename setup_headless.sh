#!/bin/bash
# ============================================================================
# Meshing-Around Headless Setup Script
# ============================================================================
# This script sets up the mesh client for headless/SSH operation on
# Raspberry Pi or other Linux systems.
#
# Supports:
#   - Raspberry Pi Zero 2W (no radio, MQTT mode)
#   - Raspberry Pi 3/4/5 (with or without radio)
#   - Any Debian/Ubuntu system
#
# Usage:
#   chmod +x setup_headless.sh
#   ./setup_headless.sh
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/mesh_client.ini"
SERVICE_FILE="/etc/systemd/system/mesh-client.service"

# Functions
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

print_banner() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  MESHING-AROUND HEADLESS SETUP                               ║"
    echo "║  For Raspberry Pi and Linux Systems                          ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_warn "Running as root is not recommended."
        log_warn "Config files and venv will be owned by root, not your user."
        read -p "Continue as root? [y/N]: " ROOT_CONTINUE
        if [[ ! "$ROOT_CONTINUE" =~ ^[Yy]$ ]]; then
            log_info "Exiting. Re-run as a regular user."
            exit 1
        fi
    fi
}

detect_platform() {
    log_info "Detecting platform..."

    if [ -f /proc/cpuinfo ]; then
        if grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
            PI_MODEL=$(cat /proc/cpuinfo | grep "Model" | cut -d: -f2 | xargs)
            log_ok "Detected: $PI_MODEL"
            IS_PI=true
        else
            log_ok "Detected: Standard Linux"
            IS_PI=false
        fi
    fi

    # Get OS info
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        log_ok "OS: $PRETTY_NAME"
    fi
}

check_python() {
    log_info "Checking Python..."

    if command -v python3 &> /dev/null; then
        PY_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
        log_ok "Python $PY_VERSION found"

        # Check version is 3.8+
        PY_MAJOR=$(echo $PY_VERSION | cut -d. -f1)
        PY_MINOR=$(echo $PY_VERSION | cut -d. -f2)

        if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]); then
            log_error "Python 3.8+ required, found $PY_VERSION"
            exit 1
        fi
    else
        log_error "Python3 not found. Please install: sudo apt install python3"
        exit 1
    fi
}

install_system_deps() {
    log_info "Installing system dependencies..."

    if command -v apt-get &> /dev/null; then
        if ! sudo apt-get update -qq; then
            log_error "apt-get update failed — check network or sources"
            exit 1
        fi
        if ! sudo apt-get install -y -qq python3-pip python3-venv git \
                libssl-dev build-essential pkg-config python3-dev; then
            log_error "Failed to install required packages (python3-pip, python3-venv, git, libssl-dev)"
            exit 1
        fi
        log_ok "System dependencies installed"
    else
        log_warn "apt-get not found, skipping system dependencies"
    fi
}

setup_venv() {
    log_info "Setting up Python virtual environment..."

    VENV_DIR="$SCRIPT_DIR/.venv"

    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
        log_ok "Virtual environment created"
    else
        log_ok "Virtual environment exists"
    fi

    # Activate venv
    source "$VENV_DIR/bin/activate"

    # Upgrade pip
    pip install --upgrade pip --retries 5 --timeout 120 -q
    log_ok "Pip upgraded"
}

install_python_deps() {
    log_info "Installing Python dependencies..."

    # Network resilience for slow/flaky connections (Pi Zero, satellite, etc.)
    PIP_OPTS="--retries 5 --timeout 120"

    # Core deps
    pip install $PIP_OPTS rich -q
    log_ok "Installed: rich (TUI)"

    # MQTT deps
    pip install $PIP_OPTS paho-mqtt -q
    log_ok "Installed: paho-mqtt (MQTT support)"

    # Meshtastic (radio support)
    log_info "Installing meshtastic (this may take a few minutes)..."
    pip install $PIP_OPTS "meshtastic[cli]" pypubsub -q
    log_ok "Installed: meshtastic (Radio support)"

    # Cryptography / SSL (pin to resolve pyopenssl conflict)
    log_info "Installing cryptography (may take 10+ minutes on ARM if building from source)..."
    pip install $PIP_OPTS 'pyopenssl>=25.3.0' 'cryptography>=45.0.7,<47'
    log_ok "Installed: cryptography (SSL/encryption)"
}

generate_config() {
    log_info "Generating configuration file..."

    # Export variables for safe use in Python (avoids shell injection via heredoc)
    export _CFG_CONN_TYPE="$CONN_TYPE"
    export _CFG_TCP_HOST="${TCP_HOST:-}"
    export _CFG_MQTT_ENABLED="$( [ "$CONN_TYPE" = "mqtt" ] && echo "true" || echo "false" )"
    export _CFG_MQTT_BROKER="${MQTT_BROKER:-mqtt.meshtastic.org}"
    export _CFG_MQTT_TOPIC="${MQTT_TOPIC:-msh/US}"
    export _CFG_MESHTASTIC_ENABLED="$( [ "$INSTALL_MESHTASTIC" = true ] && echo "true" || echo "false" )"
    export _CFG_CONFIG_FILE="$CONFIG_FILE"

    # Run Python with quoted heredoc to prevent shell interpolation
    python3 << 'EOF'
import configparser
import os

config = configparser.ConfigParser()

# Interface (canonical format — no legacy [connection] section)
config['interface'] = {
    'type': os.environ.get('_CFG_CONN_TYPE', 'serial'),
    'port': '',
    'baudrate': '115200',
    'hostname': os.environ.get('_CFG_TCP_HOST', ''),
    'http_url': '',
    'mac': '',
    'auto_reconnect': 'true',
    'reconnect_delay': '5',
    'connection_timeout': '30',
}

# MQTT
config['mqtt'] = {
    'enabled': os.environ.get('_CFG_MQTT_ENABLED', 'false'),
    'broker': os.environ.get('_CFG_MQTT_BROKER', 'mqtt.meshtastic.org'),
    'port': '1883',
    'use_tls': 'false',
    'username': 'meshdev',
    'password': 'large4cats',
    'topic_root': os.environ.get('_CFG_MQTT_TOPIC', 'msh/US'),
    'channel': 'LongFast',
    'node_id': '',
    'qos': '1',
    'reconnect_delay': '5',
    'max_reconnect_attempts': '10',
}

# Features
config['features'] = {
    'mode': 'tui',
    'tui_enabled': 'true',
    'tui_refresh_rate': '1.0',
    'tui_mouse_support': 'false',
    'tui_color_scheme': 'default',
    'messages_enabled': 'true',
    'nodes_enabled': 'true',
    'alerts_enabled': 'true',
    'location_enabled': 'true',
    'telemetry_enabled': 'true',
}

# Alerts
config['alerts'] = {
    'enabled': 'true',
    'emergency_enabled': 'true',
    'emergency_keywords': 'emergency,911,112,999,sos,help,mayday',
    'battery_alerts': 'true',
    'battery_threshold': '20',
    'new_node_alerts': 'true',
    'disconnect_alerts': 'true',
    'disconnect_timeout': '3600',
    'sound_enabled': 'false',
    'log_alerts': 'true',
    'log_file': 'logs/alerts.log',
}

# Network
config['network'] = {
    'favorite_nodes': '',
    'admin_nodes': '',
    'blocked_nodes': '',
    'default_channel': '0',
    'monitored_channels': '0,1,2',
    'message_history': '500',
    'max_message_length': '200',
}

# Display
config['display'] = {
    'show_timestamps': 'true',
    'show_node_ids': 'false',
    'show_snr': 'true',
    'show_battery': 'true',
    'show_position': 'false',
    'time_format': '24h',
    'node_name_style': 'long',
}

# Logging
config['logging'] = {
    'enabled': 'true',
    'level': 'INFO',
    'file': 'mesh_client.log',
    'max_size_mb': '10',
    'backup_count': '3',
    'log_messages': 'true',
    'log_nodes': 'true',
    'log_telemetry': 'false',
}

# Advanced
config['advanced'] = {
    'use_venv': 'true',
    'auto_install_deps': 'true',
    'demo_mode': 'false',
    'check_updates': 'false',
    'show_splash': 'true',
    'update_interval': '1.0',
    'node_timeout': '3600',
    'debug_mode': 'false',
    'verbose': 'false',
}

config_file = os.environ.get('_CFG_CONFIG_FILE', 'mesh_client.ini')
with open(config_file, 'w') as f:
    config.write(f)
os.chmod(config_file, 0o600)

print(f"Configuration saved to {config_file}")
EOF

    log_ok "Configuration file created"
}

setup_systemd_service() {
    log_info "Setting up systemd service..."

    read -p "Install as systemd service for auto-start? [y/N]: " INSTALL_SERVICE

    if [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
        # Create service file - use envsubst for safe variable substitution
        SERVICE_USER="$USER"
        SERVICE_WORKDIR="$SCRIPT_DIR"
        SERVICE_EXEC="\"$SCRIPT_DIR/.venv/bin/python\" \"$SCRIPT_DIR/mesh_client.py\""
        sudo tee "$SERVICE_FILE" > /dev/null <<SVCEOF
[Unit]
Description=Meshing-Around Mesh Client
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${SERVICE_WORKDIR}
ExecStart=${SERVICE_EXEC}
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF

        sudo systemctl daemon-reload
        sudo systemctl enable mesh-client
        log_ok "Systemd service installed and enabled"
        log_info "Start with: sudo systemctl start mesh-client"
        log_info "View logs: sudo journalctl -u mesh-client -f"
    else
        log_info "Skipping systemd service installation"
    fi
}

setup_bot_service() {
    log_info "Setting up mesh_bot systemd service..."

    # Find the upstream meshing-around install (check multiple paths)
    BOT_DIR=""
    for dir in /opt/meshing-around /opt/meshing_around "$HOME/meshing-around" "$HOME/meshing_around"; do
        if [[ -f "$dir/mesh_bot.py" ]]; then
            BOT_DIR="$dir"
            break
        fi
    done
    # Also check SUDO_USER home (when running with sudo, $HOME may be /root)
    if [[ -z "$BOT_DIR" && -n "$SUDO_USER" ]]; then
        for dir in "/home/$SUDO_USER/meshing-around" "/home/$SUDO_USER/meshing_around"; do
            if [[ -f "$dir/mesh_bot.py" ]]; then
                BOT_DIR="$dir"
                break
            fi
        done
    fi

    if [[ -z "$BOT_DIR" ]]; then
        log_warn "meshing-around not found — skipping bot service install"
        return 1
    fi

    log_ok "Found meshing-around at: $BOT_DIR"

    read -p "Install mesh_bot as systemd service? [y/N]: " INSTALL_BOT
    if [[ ! "$INSTALL_BOT" =~ ^[Yy]$ ]]; then
        log_info "Skipping bot service installation"
        return 0
    fi

    # Determine service user
    SERVICE_USER="${SUDO_USER:-$USER}"

    # Use launch.sh which handles venv activation and SSL certs
    sudo tee /etc/systemd/system/mesh_bot.service > /dev/null <<BOTEOF
[Unit]
Description=Meshing-Around Mesh Bot (mesh_bot.py)
Documentation=https://github.com/SpudGunMan/meshing-around
After=network.target meshtasticd.service
Wants=meshtasticd.service

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${BOT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash ${BOT_DIR}/launch.sh mesh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
BOTEOF

    sudo systemctl daemon-reload
    sudo systemctl enable mesh_bot.service
    log_ok "mesh_bot.service installed and enabled"
    log_info "Start with: sudo systemctl start mesh_bot"
    log_info "View logs:  sudo journalctl -u mesh_bot -f"
}

install_local_broker() {
    echo ""
    read -p "Install local MQTT broker (Mosquitto)? Recommended for MQTT mode [y/N]: " INSTALL_MOSQUITTO

    if [[ "$INSTALL_MOSQUITTO" =~ ^[Yy]$ ]]; then
        log_info "Installing Mosquitto MQTT broker..."

        if command -v apt-get &> /dev/null; then
            if ! sudo apt-get install -y -qq mosquitto mosquitto-clients; then
                log_error "Failed to install mosquitto"
                return
            fi

            # Enable and start the service
            sudo systemctl enable mosquitto
            sudo systemctl start mosquitto

            if systemctl is-active --quiet mosquitto; then
                log_ok "Mosquitto installed and running on port 1883"
            else
                log_warn "Mosquitto installed but failed to start — check: sudo systemctl status mosquitto"
            fi
        else
            log_warn "apt-get not found — install mosquitto manually"
        fi
    else
        log_info "Skipping local MQTT broker"
    fi
}

setup_serial_permissions() {
    if [ "$CONN_TYPE" = "serial" ] || [ "$CONN_TYPE" = "auto" ]; then
        log_info "Setting up serial port permissions..."

        if ! groups | grep -q dialout; then
            sudo usermod -a -G dialout $USER
            log_ok "Added $USER to dialout group"
            log_warn "You may need to logout and login for group changes to take effect"
        else
            log_ok "Already in dialout group"
        fi
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  SETUP COMPLETE                                              ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Configuration saved to: $CONFIG_FILE"
    echo ""
    echo "To start the client:"
    echo "  source $SCRIPT_DIR/.venv/bin/activate"
    echo "  python3 mesh_client.py"
    echo ""
    echo "The launcher menu lets you choose your connection mode"
    echo "(MQTT, Serial, TCP, etc.) and interface at runtime."
    echo ""
    echo "Quick start:"
    echo "  python3 mesh_client.py --demo    # Demo mode (no hardware)"
    echo "  python3 mesh_client.py --tui     # TUI interface"
    echo "  python3 mesh_client.py --setup   # Interactive setup wizard"
    echo ""

    if [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
        echo "Service management:"
        echo "  sudo systemctl start mesh-client   # Start"
        echo "  sudo systemctl stop mesh-client    # Stop"
        echo "  sudo systemctl status mesh-client  # Status"
        echo "  sudo journalctl -u mesh-client -f  # Logs"
        echo ""
    fi
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    print_banner
    check_root
    detect_platform
    check_python

    echo ""
    read -p "Continue with setup? [Y/n]: " CONTINUE
    if [[ "$CONTINUE" =~ ^[Nn]$ ]]; then
        log_info "Setup cancelled"
        exit 0
    fi

    install_system_deps

    # Defaults — connection mode is chosen at runtime via the launcher menu
    CONN_TYPE="auto"
    INSTALL_MESHTASTIC=true
    MQTT_BROKER="mqtt.meshtastic.org"
    MQTT_TOPIC="msh/US"

    setup_venv
    install_python_deps
    generate_config

    # Create logs directory
    mkdir -p "$SCRIPT_DIR/logs"
    log_ok "Log directory created"

    install_local_broker
    setup_serial_permissions
    setup_systemd_service
    setup_bot_service
    print_summary
}

main "$@"

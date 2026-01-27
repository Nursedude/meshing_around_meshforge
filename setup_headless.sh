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
        log_warn "Running as root. Some features may need adjustment."
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
        sudo apt-get update -qq
        sudo apt-get install -y -qq \
            python3-pip \
            python3-venv \
            git \
            || log_warn "Some packages may have failed"
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
    pip install --upgrade pip -q
    log_ok "Pip upgraded"
}

install_python_deps() {
    log_info "Installing Python dependencies..."

    # Core deps
    pip install rich -q
    log_ok "Installed: rich (TUI)"

    # Web deps
    pip install fastapi uvicorn jinja2 python-multipart -q
    log_ok "Installed: FastAPI (Web server)"

    # MQTT deps
    pip install paho-mqtt -q
    log_ok "Installed: paho-mqtt (MQTT support)"

    # Meshtastic (optional)
    if [ "$INSTALL_MESHTASTIC" = true ]; then
        pip install meshtastic pypubsub -q
        log_ok "Installed: meshtastic (Radio support)"
    fi
}

configure_connection() {
    log_info "Configuring connection..."

    echo ""
    echo "How will this device connect to the mesh?"
    echo ""
    echo "  1) Serial/USB - Radio connected directly to this device"
    echo "  2) TCP - Remote Meshtastic device on network"
    echo "  3) MQTT - No radio, connect via MQTT broker"
    echo "  4) Auto-detect"
    echo ""
    read -p "Select option [3]: " CONN_CHOICE
    CONN_CHOICE=${CONN_CHOICE:-3}

    case $CONN_CHOICE in
        1)
            CONN_TYPE="serial"
            INSTALL_MESHTASTIC=true
            # Detect serial ports
            if ls /dev/ttyUSB* 2>/dev/null || ls /dev/ttyACM* 2>/dev/null; then
                log_ok "Serial ports detected"
            else
                log_warn "No serial ports detected. Connect radio and restart."
            fi
            ;;
        2)
            CONN_TYPE="tcp"
            INSTALL_MESHTASTIC=true
            read -p "Enter TCP host [192.168.1.1]: " TCP_HOST
            TCP_HOST=${TCP_HOST:-192.168.1.1}
            ;;
        3)
            CONN_TYPE="mqtt"
            INSTALL_MESHTASTIC=false
            read -p "Enter MQTT broker [mqtt.meshtastic.org]: " MQTT_BROKER
            MQTT_BROKER=${MQTT_BROKER:-mqtt.meshtastic.org}
            read -p "Enter MQTT topic root [msh/US]: " MQTT_TOPIC
            MQTT_TOPIC=${MQTT_TOPIC:-msh/US}
            ;;
        4)
            CONN_TYPE="auto"
            INSTALL_MESHTASTIC=true
            ;;
        *)
            CONN_TYPE="mqtt"
            INSTALL_MESHTASTIC=false
            ;;
    esac

    log_ok "Connection type: $CONN_TYPE"
}

configure_interface() {
    log_info "Configuring interface..."

    echo ""
    echo "Select interface mode:"
    echo ""
    echo "  1) TUI - Terminal interface (good for SSH)"
    echo "  2) Web - Browser interface"
    echo "  3) Both - TUI + Web server"
    echo "  4) Headless - API only (for automation)"
    echo ""
    read -p "Select option [1]: " MODE_CHOICE
    MODE_CHOICE=${MODE_CHOICE:-1}

    case $MODE_CHOICE in
        1) INTERFACE_MODE="tui" ;;
        2) INTERFACE_MODE="web" ;;
        3) INTERFACE_MODE="both" ;;
        4) INTERFACE_MODE="headless" ;;
        *) INTERFACE_MODE="tui" ;;
    esac

    if [ "$INTERFACE_MODE" = "web" ] || [ "$INTERFACE_MODE" = "both" ]; then
        read -p "Enter web port [8080]: " WEB_PORT
        WEB_PORT=${WEB_PORT:-8080}
    fi

    log_ok "Interface mode: $INTERFACE_MODE"
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
    export _CFG_INTERFACE_MODE="$INTERFACE_MODE"
    export _CFG_WEB_SERVER="$( [ "$INTERFACE_MODE" = "web" ] || [ "$INTERFACE_MODE" = "both" ] && echo "true" || echo "false" )"
    export _CFG_WEB_PORT="${WEB_PORT:-8080}"
    export _CFG_CONFIG_FILE="$CONFIG_FILE"

    # Run Python with quoted heredoc to prevent shell interpolation
    python3 << 'EOF'
import configparser
import os

config = configparser.ConfigParser()

# Connection
config['connection'] = {
    'type': os.environ.get('_CFG_CONN_TYPE', 'serial'),
    'serial_port': 'auto',
    'serial_baud': '115200',
    'tcp_host': os.environ.get('_CFG_TCP_HOST', ''),
    'tcp_port': '4403',
    'mqtt_enabled': os.environ.get('_CFG_MQTT_ENABLED', 'false'),
    'mqtt_broker': os.environ.get('_CFG_MQTT_BROKER', 'mqtt.meshtastic.org'),
    'mqtt_port': '1883',
    'mqtt_use_tls': 'false',
    'mqtt_username': 'meshdev',
    'mqtt_password': 'large4cats',
    'mqtt_topic_root': os.environ.get('_CFG_MQTT_TOPIC', 'msh/US'),
    'mqtt_channel': 'LongFast',
    'mqtt_node_id': '',
    'ble_address': '',
    'auto_reconnect': 'true',
    'reconnect_delay': '5',
    'connection_timeout': '30',
    'meshtastic_enabled': os.environ.get('_CFG_MESHTASTIC_ENABLED', 'false'),
}

# Features
config['features'] = {
    'mode': os.environ.get('_CFG_INTERFACE_MODE', 'tui'),
    'tui_enabled': 'true',
    'tui_refresh_rate': '1.0',
    'tui_mouse_support': 'false',
    'tui_color_scheme': 'default',
    'web_server': os.environ.get('_CFG_WEB_SERVER', 'false'),
    'web_host': '127.0.0.1',
    'web_port': os.environ.get('_CFG_WEB_PORT', '8080'),
    'web_api_enabled': 'true',
    'web_auth_enabled': 'false',
    'web_username': 'admin',
    'web_password': '',
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
        SERVICE_EXEC="$SCRIPT_DIR/.venv/bin/python $SCRIPT_DIR/mesh_client.py"
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
    echo "Or with options:"
    echo "  python3 mesh_client.py --demo    # Demo mode"
    echo "  python3 mesh_client.py --web     # Web interface"
    echo "  python3 mesh_client.py --tui     # TUI interface"
    echo ""

    if [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
        echo "Service management:"
        echo "  sudo systemctl start mesh-client   # Start"
        echo "  sudo systemctl stop mesh-client    # Stop"
        echo "  sudo systemctl status mesh-client  # Status"
        echo "  sudo journalctl -u mesh-client -f  # Logs"
        echo ""
    fi

    if [ "$INTERFACE_MODE" = "web" ] || [ "$INTERFACE_MODE" = "both" ]; then
        echo "Web interface will be available at:"
        echo "  http://$(hostname -I | awk '{print $1}'):${WEB_PORT:-8080}"
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
    configure_connection
    configure_interface
    setup_venv
    install_python_deps
    generate_config
    setup_serial_permissions
    setup_systemd_service
    print_summary
}

main "$@"

# Meshing-Around Clients

TUI (Terminal User Interface) and Web clients for the [meshing-around](https://github.com/SpudGunMan/meshing-around) Meshtastic bot system.

Built using the **MeshForge Foundation** principles:
- Modularity: Each component is independently configurable
- User-friendly: Interactive interfaces with sensible defaults
- Multi-platform: Works across different systems
- Robustness: Fallback mechanisms and error handling
- **Zero dependencies boot**: Starts with stdlib only, auto-installs as needed
- **100% configurable**: Every feature can be toggled via config file

## Connection Modes

| Mode | Radio Required | Use Case |
|------|----------------|----------|
| **Serial** | Yes (USB) | Direct connection to Meshtastic device |
| **TCP** | Remote | Connect to Meshtastic device on network |
| **MQTT** | No | Connect via MQTT broker (e.g., mqtt.meshtastic.org) |
| **BLE** | Yes (Bluetooth) | Bluetooth LE connection |
| **Auto** | Depends | Auto-detect best available connection |
| **Demo** | No | Simulated data for testing |

## Quick Start

### Standalone Launcher (Recommended)

The standalone launcher handles everything automatically:

```bash
# First run - auto-installs dependencies
python3 mesh_client.py

# Interactive setup wizard
python3 mesh_client.py --setup

# Specific modes
python3 mesh_client.py --tui      # Terminal interface
python3 mesh_client.py --web      # Web interface
python3 mesh_client.py --demo     # Demo mode (no hardware)
```

### Headless Setup (Raspberry Pi)

For Pi Zero 2W or other headless systems:

```bash
chmod +x setup_headless.sh
./setup_headless.sh
```

This will:
1. Install system dependencies
2. Set up Python virtual environment
3. Configure connection type (MQTT for no-radio setups)
4. Optionally install as systemd service for auto-start

### Example: Pi Zero 2W with MQTT (No Radio)

```bash
# Run setup
./setup_headless.sh

# Select:
#   Connection: 3 (MQTT)
#   Interface: 1 (TUI) or 3 (Both)

# Start manually
source .venv/bin/activate
python3 mesh_client.py

# Or if installed as service
sudo systemctl start mesh-client
```

## Features

### TUI Client
- Real-time mesh network monitoring
- Node status with battery, SNR, and position data
- Message history with channel filtering
- Alert system with severity levels
- Send messages directly from terminal
- Works over SSH for headless systems

### Web Client
- Modern responsive dashboard
- Real-time updates via WebSocket
- REST API for integration
- Node details and management
- Message composition and history
- Alert acknowledgment system

### MQTT Mode (No Radio)
- Connect to public broker (mqtt.meshtastic.org)
- Connect to private/local MQTT brokers
- Receive mesh messages without hardware
- Send messages (with node ID configured)

## Configuration

All settings are in `mesh_client.ini`:

```ini
[interface]
# Connection type: auto, serial, tcp, mqtt, ble
type = auto

# Serial settings
serial_port = auto
serial_baud = 115200

# TCP settings
tcp_host = 192.168.1.100
tcp_port = 4403

[mqtt]
# MQTT settings (for radio-less operation)
enabled = true
broker = mqtt.meshtastic.org
port = 1883
username = meshdev
password = large4cats
topic_root = msh/US
channel = LongFast

[features]
# Interface mode: tui, web, both, headless
mode = tui

# Web server
web_server = false
web_host = 127.0.0.1
web_port = 8080

# Feature toggles
messages_enabled = true
nodes_enabled = true
alerts_enabled = true

[alerts]
enabled = true
emergency_enabled = true
emergency_keywords = emergency,911,sos,help,mayday
battery_alerts = true
battery_threshold = 20

[advanced]
# Auto-install missing dependencies
auto_install_deps = true

# Demo mode (simulated data)
demo_mode = false
```

## Architecture

```
meshing_around_meshforge/
├── mesh_client.py              # Standalone launcher (zero-dep bootstrap)
├── mesh_client.ini             # Master configuration file
├── configure_bot.py            # Bot setup wizard
├── setup_headless.sh           # Headless/Pi setup script
│
└── meshing_around_clients/
    ├── core/
    │   ├── config.py            # Configuration management
    │   ├── models.py            # Data models (Node, Message, Alert, MeshNetwork)
    │   ├── meshtastic_api.py    # Device API + MockAPI (Serial/TCP/HTTP/BLE)
    │   ├── mqtt_client.py       # MQTT broker connection
    │   └── mesh_crypto.py       # AES-256-CTR decryption (optional deps)
    ├── setup/                   # Setup-only modules (configure_bot.py)
    │   ├── cli_utils.py         # Terminal colors, input helpers
    │   ├── pi_utils.py          # Pi detection, serial ports
    │   ├── system_maintenance.py # Updates, systemd
    │   ├── alert_configurators.py # Alert wizards
    │   └── config_schema.py     # Upstream format conversion
    ├── tui/
    │   └── app.py               # Rich-based terminal UI
    └── web/
        ├── app.py               # FastAPI application
        ├── templates/           # HTML templates
        └── static/              # CSS/JS assets
```

## Command Line Options

```
python3 mesh_client.py [OPTIONS]

Options:
  --setup         Interactive configuration wizard
  --check         Check dependencies only
  --install-deps  Install dependencies and exit
  --tui           Force TUI mode
  --web           Force Web mode
  --demo          Demo mode (no hardware)
  --no-venv       Don't use virtual environment
  --version       Show version
```

## TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Dashboard view |
| `2` | Nodes view |
| `3` | Messages view |
| `4` | Alerts view |
| `s` | Send message |
| `r` | Refresh data |
| `c` | Connect/Disconnect |
| `?` | Help |
| `q` | Quit / Back |

## REST API

The web client provides a REST API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Connection status |
| `/api/network` | GET | Full network state |
| `/api/nodes` | GET | All nodes |
| `/api/nodes/{id}` | GET | Specific node |
| `/api/messages` | GET | Message history |
| `/api/messages/send` | POST | Send message |
| `/api/alerts` | GET | All alerts |
| `/api/alerts/acknowledge` | POST | Acknowledge alert |
| `/api/connect` | POST | Connect to device |
| `/api/disconnect` | POST | Disconnect |

## WebSocket

Real-time updates via WebSocket at `ws://host:port/ws`:

```javascript
const ws = new WebSocket('ws://localhost:8080/ws');

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    // msg.type: 'init', 'message', 'alert', 'node_update'
};

// Send message
ws.send(JSON.stringify({
    type: 'send_message',
    text: 'Hello mesh!',
    destination: '^all',
    channel: 0
}));
```

## Systemd Service

Auto-start on boot:

```bash
# Enable service (done by setup_headless.sh)
sudo systemctl enable mesh-client

# Manual control
sudo systemctl start mesh-client
sudo systemctl stop mesh-client
sudo systemctl status mesh-client

# View logs
sudo journalctl -u mesh-client -f
```

## Use Cases

### 1. Pi Zero 2W Monitoring Station (No Radio)

```
Hardware: Raspberry Pi Zero 2W
Connection: MQTT (mqtt.meshtastic.org)
Interface: Web server
Access: SSH + Browser
```

Configuration:
```ini
[interface]
type = mqtt

[mqtt]
enabled = true
broker = mqtt.meshtastic.org

[features]
mode = web
web_server = true
web_port = 8080
```

### 2. Desktop with Radio

```
Hardware: Desktop + Meshtastic USB device
Connection: Serial (auto-detect)
Interface: TUI
```

Configuration:
```ini
[interface]
type = serial
serial_port = auto

[features]
mode = tui
```

### 3. Remote Monitoring Server

```
Hardware: Linux server
Connection: TCP to remote Meshtastic device
Interface: Web + API
```

Configuration:
```ini
[interface]
type = tcp
tcp_host = 192.168.1.50

[features]
mode = both
web_server = true
```

## Troubleshooting

### No serial ports detected
```bash
# Check if device is connected
ls -la /dev/ttyUSB* /dev/ttyACM*

# Add user to dialout group
sudo usermod -a -G dialout $USER
# Then logout and login
```

### MQTT connection fails
```bash
# Test MQTT broker connectivity
python3 -c "import socket; socket.create_connection(('mqtt.meshtastic.org', 1883), 5); print('OK')"

# Check credentials in config
# Default: meshdev / large4cats
```

### Dependencies won't install
```bash
# Check internet
ping -c 1 8.8.8.8

# Manual install
pip install rich fastapi uvicorn paho-mqtt

# Or use --break-system-packages on newer Debian
pip install --break-system-packages rich
```

## License

GPL-3.0 License - See LICENSE file for details.

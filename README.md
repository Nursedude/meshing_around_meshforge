# MeshForge

**MeshForge** is a comprehensive toolkit for the [meshing-around](https://github.com/SpudGunMan/meshing-around) Meshtastic bot system. It provides configuration tools, TUI/Web monitoring clients, and multi-platform deployment support.

[![Version](https://img.shields.io/badge/version-3.0.0-blue.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-yellow.svg)](https://python.org)

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            MESHFORGE v3.0.0                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐   │
│   │  Configuration   │   │   TUI Client     │   │   Web Client     │   │
│   │      Tool        │   │                  │   │                  │   │
│   │                  │   │  Real-time       │   │  Dashboard       │   │
│   │  12 Alert Types  │   │  Terminal UI     │   │  REST API        │   │
│   │  Interactive     │   │  SSH Ready       │   │  WebSocket       │   │
│   │  Setup Wizard    │   │  Rich Library    │   │  FastAPI         │   │
│   └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘   │
│            │                      │                      │             │
│            └──────────────────────┼──────────────────────┘             │
│                                   │                                     │
│                    ┌──────────────┴──────────────┐                     │
│                    │     Connection Manager      │                     │
│                    │                             │                     │
│                    │  Serial │ TCP │ MQTT │ BLE  │                     │
│                    └──────────────────────────────┘                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Features

### Configuration Tool
- Interactive setup wizard for meshing-around bot
- 12 configurable alert types
- Email/SMS notification integration
- Raspberry Pi auto-detection and setup

### Meshing-Around Clients
- **TUI Client** - Rich terminal interface for SSH/headless operation
- **Web Client** - Modern browser dashboard with real-time updates
- **MQTT Mode** - No radio required, connect via MQTT broker
- **REST API** - Integration endpoint for automation

### MeshForge Principles
- **Modularity** - Independent, configurable components
- **Rich UI** - Beautiful terminal interfaces with fallback
- **Robust** - Specific exception handling, graceful degradation
- **PEP 668** - Virtual environment compliance for modern systems
- **Configurable** - 100% INI-file based configuration

## Supported Platforms

- Raspberry Pi OS Bookworm/Trixie (Debian 12/13)
- Ubuntu 22.04/24.04 (Jammy/Noble)
- Standard Debian/Linux systems
- Any Python 3.8+ environment

## Quick Start

### Option 1: Standalone Client (Recommended)

```bash
# Clone repository
git clone https://github.com/Nursedude/meshing_around_meshforge.git
cd meshing_around_meshforge

# Run - auto-installs dependencies
python3 mesh_client.py

# Or with options
python3 mesh_client.py --demo    # Demo mode (no hardware)
python3 mesh_client.py --setup   # Interactive setup
python3 mesh_client.py --web     # Web interface
```

### Option 2: Configuration Tool

```bash
# Run the bot configuration wizard
python3 configure_bot.py
```

### Option 3: Headless/Pi Setup

```bash
# Interactive setup for Pi Zero 2W or headless systems
chmod +x setup_headless.sh
./setup_headless.sh
```

## Connection Modes

| Mode | Radio Required | Description |
|------|----------------|-------------|
| **Serial** | Yes (USB) | Direct connection to Meshtastic device |
| **TCP** | Remote | Network connection to Meshtastic device |
| **MQTT** | No | Connect via mqtt.meshtastic.org or private broker |
| **BLE** | Yes (Bluetooth) | Bluetooth LE connection |
| **Auto** | Depends | Auto-detect best available |
| **Demo** | No | Simulated data for testing |

## Project Structure

```
meshing_around_meshforge/
├── mesh_client.py              # Standalone launcher (start here)
├── mesh_client.ini             # Master configuration
├── configure_bot.py            # Bot configuration tool
├── configure_bot_improved.py   # Enhanced UI version
├── setup_headless.sh           # Pi/headless setup script
│
├── meshing_around_clients/     # Client applications
│   ├── core/                   # Shared functionality
│   │   ├── models.py           # Data models
│   │   ├── config.py           # Configuration
│   │   ├── meshtastic_api.py   # Device communication
│   │   ├── mqtt_client.py      # MQTT connection
│   │   ├── connection_manager.py # Multi-mode connections
│   │   └── message_handler.py  # Message processing
│   ├── tui/                    # Terminal UI
│   │   └── app.py              # Rich-based TUI
│   └── web/                    # Web interface
│       ├── app.py              # FastAPI application
│       ├── templates/          # HTML templates
│       └── static/             # CSS/JS assets
│
├── Documentation/              # Additional docs
├── config.enhanced.ini         # Alert configuration template
├── CHANGELOG.md                # Version history
└── LICENSE                     # GPL-3.0
```

## Configuration

All settings are in `mesh_client.ini`:

```ini
[connection]
type = auto                      # auto, serial, tcp, mqtt, ble
serial_port = auto               # /dev/ttyUSB0 or auto
mqtt_enabled = true              # Enable MQTT mode
mqtt_broker = mqtt.meshtastic.org

[features]
mode = tui                       # tui, web, both, headless
web_server = true
web_port = 8080

[alerts]
enabled = true
emergency_keywords = emergency,911,sos,help
battery_threshold = 20

[advanced]
auto_install_deps = true
demo_mode = false
```

See [Documentation/CLIENTS_README.md](Documentation/CLIENTS_README.md) for full configuration reference.

## 12 Alert Types

| # | Alert | Description |
|---|-------|-------------|
| 1 | Emergency | Keyword detection (911, SOS, etc.) |
| 2 | Proximity | Geofencing and location triggers |
| 3 | Altitude | High-altitude node detection |
| 4 | Weather | NOAA/weather service integration |
| 5 | iPAWS/EAS | FEMA emergency alerts |
| 6 | Volcano | USGS volcano monitoring |
| 7 | Battery | Low battery detection |
| 8 | Noisy Node | Spam prevention, auto-muting |
| 9 | New Node | Welcome messages |
| 10 | SNR | Signal quality monitoring |
| 11 | Disconnect | Offline node detection |
| 12 | Custom | User-defined keyword triggers |

## TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Dashboard |
| `2` | Nodes |
| `3` | Messages |
| `4` | Alerts |
| `s` | Send message |
| `?` | Help |
| `q` | Quit/Back |

## REST API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Connection status |
| `/api/nodes` | GET | All nodes |
| `/api/messages` | GET | Message history |
| `/api/messages/send` | POST | Send message |
| `/api/alerts` | GET | All alerts |

## Use Cases

### Pi Zero 2W Monitoring (No Radio)
```ini
[connection]
type = mqtt
mqtt_broker = mqtt.meshtastic.org

[features]
mode = web
web_port = 8080
```

### Desktop with Radio
```ini
[connection]
type = serial
serial_port = auto

[features]
mode = tui
```

### Remote Server
```ini
[connection]
type = tcp
tcp_host = 192.168.1.50

[features]
mode = both
```

## Version History

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

| Version | Highlights |
|---------|------------|
| 3.0.0 | TUI/Web clients, MQTT, standalone launcher |
| 2.2.0 | Rich UI integration |
| 2.0.0 | 12 alert types |
| 1.0.0 | Initial release |

## Contributing

Contributions welcome! Please follow MeshForge principles:

1. **Modularity** - Keep components independent
2. **Rich UI** - Use Rich library with fallback for no-Rich environments
3. **Exception handling** - No bare `except:` clauses, use specific exceptions
4. **Configuration** - Use INI files, make features toggleable
5. **Documentation** - Update docs with changes

## License

GPL-3.0 License - See [LICENSE](LICENSE)

## Acknowledgments

- [SpudGunMan](https://github.com/SpudGunMan) - Original meshing-around project
- [Meshtastic](https://meshtastic.org) - Mesh networking platform
- The Meshtastic community

## Links

- [meshing-around](https://github.com/SpudGunMan/meshing-around) - Main bot project
- [Meshtastic](https://meshtastic.org) - Platform documentation
- [Issues](https://github.com/Nursedude/meshing_around_meshforge/issues) - Report bugs

---

**MeshForge v3.0.0** - Tools for the Meshtastic mesh network ecosystem

# MeshForge Clients

**Companion toolkit for [MeshForge NOC](https://github.com/Nursedude/meshforge)** - TUI/Web monitoring clients, MQTT integration, and headless deployment for Meshtastic mesh networks.

[![Version](https://img.shields.io/badge/version-0.5.0--beta-orange.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![CI](https://github.com/Nursedude/meshing_around_meshforge/actions/workflows/ci.yml/badge.svg)](https://github.com/Nursedude/meshing_around_meshforge/actions)

## What is this?

This toolkit serves two purposes:

1. **Extension for MeshForge NOC** - Integrates with [MeshForge NOC](https://github.com/Nursedude/meshforge) via MQTT for coordinated mesh network monitoring across private encrypted channels.

2. **Standalone Client** - Works independently as a TUI/Web client for monitoring any Meshtastic mesh network via Serial, TCP, MQTT, or BLE.

> **BETA SOFTWARE** - Under active development. Some features are incomplete or untested. See [Feature Status](#feature-status) below.

## Feature Status

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#4a9eff', 'primaryTextColor': '#fff', 'primaryBorderColor': '#2980b9', 'lineColor': '#666', 'secondaryColor': '#27ae60', 'tertiaryColor': '#e74c3c'}}}%%
graph LR
    subgraph "Working"
        TUI[TUI Client]
        DEMO[Demo Mode]
        CFG[Config System]
        MODELS[Data Models]
        ALERTS[Alert Detection]
    end

    subgraph "Partial"
        WEB[Web Client]
        MQTT[MQTT Mode]
        NOTIFY[Notifications]
        CMDS[Bot Commands]
    end

    subgraph "Untested"
        SERIAL[Serial Mode]
        TCP[TCP Mode]
        BLE[BLE Mode]
        SMS[SMS Gateway]
    end

    style TUI fill:#27ae60,color:#fff
    style DEMO fill:#27ae60,color:#fff
    style CFG fill:#27ae60,color:#fff
    style MODELS fill:#27ae60,color:#fff
    style ALERTS fill:#27ae60,color:#fff
    style WEB fill:#f39c12,color:#fff
    style MQTT fill:#f39c12,color:#fff
    style NOTIFY fill:#f39c12,color:#fff
    style CMDS fill:#f39c12,color:#fff
    style SERIAL fill:#e74c3c,color:#fff
    style TCP fill:#e74c3c,color:#fff
    style BLE fill:#e74c3c,color:#fff
    style SMS fill:#e74c3c,color:#fff
```

| Feature | Status | Notes |
|---------|--------|-------|
| **TUI Client** | Working | 6 screens, keyboard navigation |
| **Demo Mode** | Working | Simulated data for testing |
| **Config System** | Working | INI-based configuration |
| **Data Models** | Working | Node, Message, Alert, MeshNetwork |
| **Alert Detection** | Working | Emergency keywords, proximity |
| **Web Client** | Partial | API works, templates need testing |
| **MQTT Mode** | Partial | Connects but limited testing |
| **Notifications** | Partial | Email framework exists, untested |
| **Bot Commands** | Partial | Parser exists, handlers incomplete |
| **Serial Mode** | Untested | Requires hardware testing |
| **TCP Mode** | Untested | Requires network device |
| **BLE Mode** | Untested | Requires Bluetooth setup |
| **SMS Gateway** | Untested | Requires carrier configuration |

## Architecture

```mermaid
graph TB
    subgraph "Entry Points"
        MC[mesh_client.py<br/>Zero-dep Launcher]
        CB[configure_bot.py<br/>Setup Wizard]
        SH[setup_headless.sh<br/>Pi Installer]
    end

    subgraph "meshing_around_clients"
        subgraph "core/"
            CFG[config.py]
            CONN[connection_manager.py]
            API[meshtastic_api.py]
            MSG[message_handler.py]
            ALERT[alert_detector.py]
            NOTIF[notifications.py]
            MDL[models.py]
        end

        subgraph "tui/"
            TUIAPP[app.py<br/>Rich Terminal UI]
        end

        subgraph "web/"
            WEBAPP[app.py<br/>FastAPI Server]
            TPL[templates/]
            STATIC[static/]
        end
    end

    subgraph "Connections"
        SER[Serial/USB]
        TCPCON[TCP/IP]
        MQTTCON[MQTT Broker]
        BLECON[Bluetooth LE]
    end

    MC --> TUIAPP
    MC --> WEBAPP
    CB --> CFG
    SH --> MC

    TUIAPP --> API
    WEBAPP --> API
    API --> CONN
    API --> MSG
    API --> ALERT
    ALERT --> NOTIF
    CONN --> CFG

    CONN --> SER
    CONN --> TCPCON
    CONN --> MQTTCON
    CONN --> BLECON

    style MC fill:#4a9eff,color:#fff
    style TUIAPP fill:#9b59b6,color:#fff
    style WEBAPP fill:#27ae60,color:#fff
    style ALERT fill:#e67e22,color:#fff
    style NOTIF fill:#e74c3c,color:#fff
```

## Quick Start

```bash
# Clone
git clone https://github.com/Nursedude/meshing_around_meshforge.git
cd meshing_around_meshforge

# Install dependencies
pip install rich paho-mqtt

# Try demo mode (no hardware needed)
python3 mesh_client.py --demo

# Interactive setup
python3 mesh_client.py --setup
```

## Connection Modes

```mermaid
flowchart TD
    START{Have a<br/>Meshtastic radio?}

    START -->|Yes| LOCAL{Connected to<br/>THIS machine?}
    START -->|No| MQTT[MQTT Mode<br/>via broker]

    LOCAL -->|Yes, USB| SERIAL[Serial Mode]
    LOCAL -->|Yes, BT| BLE[BLE Mode]
    LOCAL -->|No, network| TCP[TCP Mode]

    SERIAL --> READY[Monitor mesh]
    BLE --> READY
    TCP --> READY
    MQTT --> READY

    START -.->|Testing?| DEMO[Demo Mode]
    DEMO --> READY

    style START fill:#f39c12,color:#fff
    style READY fill:#27ae60,color:#fff
    style MQTT fill:#3498db,color:#fff
    style DEMO fill:#9b59b6,color:#fff
    style SERIAL fill:#e74c3c,color:#fff
    style BLE fill:#e74c3c,color:#fff
    style TCP fill:#e74c3c,color:#fff
```

| Mode | Radio Required | Status |
|------|----------------|--------|
| Demo | No | **Working** |
| MQTT | No | Partial |
| Serial | Yes (USB) | Untested |
| TCP | No | Untested |
| BLE | Yes | Untested |

## Configuration

All settings in `mesh_client.ini`:

```ini
[connection]
type = mqtt                    # demo, mqtt, serial, tcp, ble
mqtt_broker = mqtt.meshtastic.org
mqtt_topic_root = msh/US

[features]
mode = tui                     # tui, web, both
web_port = 8080
```

## TUI Screens

```mermaid
graph LR
    D[Dashboard<br/>Key: 1] --> N[Nodes<br/>Key: 2]
    N --> M[Messages<br/>Key: 3]
    M --> A[Alerts<br/>Key: 4]
    A --> H[Help<br/>Key: ?]
    H --> D

    style D fill:#4a9eff,color:#fff
    style N fill:#27ae60,color:#fff
    style M fill:#9b59b6,color:#fff
    style A fill:#e74c3c,color:#fff
    style H fill:#f39c12,color:#fff
```

| Key | Action |
|-----|--------|
| `1-4` | Switch screens |
| `s` | Send message |
| `r` | Refresh |
| `?` | Help |
| `q` | Quit |

## Alert System

| Alert Type | Trigger | Severity |
|------------|---------|----------|
| Emergency | Keywords (911, SOS, HELP) | Critical |
| Disconnect | Node timeout | Medium |
| New Node | First seen | Low |
| Battery | Below 20% | Medium |
| Proximity | Geofence enter/exit | Medium |

## API Endpoints (Web)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Connection info |
| `/api/nodes` | GET | Node list |
| `/api/messages` | GET | Message history |
| `/api/messages/send` | POST | Send message |
| `/ws` | WebSocket | Real-time updates |

## Project Structure

```
meshing_around_meshforge/
├── mesh_client.py          # Main launcher (zero-dep bootstrap)
├── mesh_client.ini         # Configuration
├── configure_bot.py        # Bot setup wizard
├── setup_headless.sh       # Pi/headless installer
└── meshing_around_clients/
    ├── core/               # Shared modules
    │   ├── config.py       # Config management
    │   ├── connection_manager.py
    │   ├── meshtastic_api.py
    │   ├── message_handler.py
    │   ├── alert_detector.py
    │   ├── notifications.py
    │   └── models.py       # Node, Message, Alert
    ├── tui/
    │   └── app.py          # Rich terminal UI
    └── web/
        ├── app.py          # FastAPI server
        ├── templates/
        └── static/
```

## MeshForge NOC Integration

This toolkit integrates with [MeshForge NOC](https://github.com/Nursedude/meshforge) for coordinated mesh monitoring:

```
┌─────────────────────┐         ┌─────────────────────┐
│   MeshForge NOC     │◄───────►│  MeshForge Clients  │
│   (Primary App)     │  MQTT   │  (This Toolkit)     │
│   - Gateway         │  Sync   │  - TUI/Web UI       │
│   - Node Tracker    │         │  - Alert System     │
└─────────────────────┘         └─────────────────────┘
          │                              │
          ▼                              ▼
┌─────────────────────────────────────────────────────┐
│          Private MQTT Channel (256-bit PSK)         │
│              msh/{region}/meshforge/#               │
└─────────────────────────────────────────────────────┘
```

See [Documentation/MQTT_INTEGRATION.md](Documentation/MQTT_INTEGRATION.md) for setup details.

## Known Issues

- **Serial/TCP/BLE modes**: Not tested with real hardware (scheduled for testing)
- **Web templates**: May have rendering issues
- **CI Tests**: Test suite needs investigation (lint/syntax pass)
- **Notifications**: Email/SMS sending untested

## Dependencies

**Core:**
- `rich` - TUI interface
- `paho-mqtt` - MQTT client

**Web (optional):**
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `jinja2` - Templates

**Hardware (optional):**
- `meshtastic` - Device API

## Contributing

Issues and PRs welcome. Please:
- Use specific exception types (no bare `except:`)
- Maintain PEP 668 compliance
- Provide Rich library fallbacks
- Test with `--demo` before hardware

## Compatibility

| Project | Relationship | Notes |
|---------|-------------|-------|
| [MeshForge NOC](https://github.com/Nursedude/meshforge) | Primary app | MQTT integration for coordinated monitoring |
| [meshing-around](https://github.com/SpudGunMan/meshing-around) | Upstream | Config format compatible, multi-interface support |
| [Meshtastic](https://meshtastic.org) | Platform | Works with any Meshtastic device |

### Feature Comparison

| Feature | meshing-around | MeshForge Clients |
|---------|---------------|-------------------|
| Purpose | Bot server | Monitoring client |
| Interfaces | Up to 9 | Up to 9 (compatible) |
| Config | `config.ini` | `mesh_client.ini` / `config.enhanced.ini` |
| Focus | Commands/games | Visualization + alerts |
| MQTT | Basic | 256-bit PSK encryption |

## Links

- **[MeshForge NOC](https://github.com/Nursedude/meshforge)** - Primary mesh monitoring application
- [meshing-around](https://github.com/SpudGunMan/meshing-around) - Bot framework (upstream)
- [Meshtastic](https://meshtastic.org) - Platform documentation
- [Issues](https://github.com/Nursedude/meshing_around_meshforge/issues)

---

*Built for the Meshtastic community by WH6GXZ*

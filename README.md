# MeshForge 🔧

Companion tools for [meshing-around](https://github.com/SpudGunMan/meshing-around) - configuration wizards, TUI/Web monitoring clients, and headless deployment scripts for your Meshtastic mesh network.

[![Version](https://img.shields.io/badge/version-0.1.0--beta-orange.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)

> ⚠️ **Beta Software** - This is early-stage code. Test thoroughly before deploying!

## Architecture Overview

```mermaid
graph TB
    subgraph "MeshForge"
        ML[mesh_client.py<br/>Launcher]
        CB[configure_bot.py<br/>Setup Wizard]

        subgraph "Interfaces"
            TUI[TUI Client<br/>Terminal]
            WEB[Web Client<br/>Browser]
        end

        subgraph "Core Layer"
            CM[Connection Manager]
            MH[Message Handler]
            CFG[Config Manager]
        end
    end

    subgraph "Connections"
        SER[Serial/USB]
        TCP[TCP/IP]
        MQTT[MQTT Broker]
        BLE[Bluetooth LE]
    end

    subgraph "External"
        RADIO[Meshtastic Radio]
        BROKER[mqtt.meshtastic.org]
        MESH((Mesh Network))
    end

    ML --> TUI
    ML --> WEB
    TUI --> CM
    WEB --> CM
    CM --> MH
    CM --> CFG

    CM --> SER
    CM --> TCP
    CM --> MQTT
    CM --> BLE

    SER --> RADIO
    TCP --> RADIO
    BLE --> RADIO
    MQTT --> BROKER

    RADIO --> MESH
    BROKER --> MESH

    style ML fill:#4a9eff,color:#fff
    style TUI fill:#9b59b6,color:#fff
    style WEB fill:#27ae60,color:#fff
    style MESH fill:#e74c3c,color:#fff
```

## TLDR

- **Configure meshing-around bot**: `python3 configure_bot.py`
- **Monitor your mesh (TUI)**: `python3 mesh_client.py --demo`
- **Web dashboard**: `python3 mesh_client.py --web --demo`
- **No radio? Use MQTT**: Works with mqtt.meshtastic.org

## What's This For?

Whether you're setting up a new meshing-around bot, want to monitor your mesh from SSH, or need a web dashboard for your Pi Zero 2W (no radio attached) - MeshForge has you covered.

**🔧 Configuration Tool** - Interactive setup wizard for meshing-around bot with 12 alert types, email/SMS notifications, and Pi auto-detection.

**📺 TUI Client** - Rich terminal interface that works great over SSH. See nodes, messages, alerts in real-time.

**🌐 Web Client** - Browser-based dashboard with WebSocket updates and REST API for automation.

**📡 MQTT Mode** - No radio required! Connect via mqtt.meshtastic.org and monitor the mesh from anywhere.

## Quick Start

```sh
# Clone it
git clone https://github.com/Nursedude/meshing_around_meshforge.git
cd meshing_around_meshforge

# Try demo mode first (no hardware needed)
python3 mesh_client.py --demo

# Or dive into setup
python3 mesh_client.py --setup
```

### Connection Options

```mermaid
flowchart TD
    START{Do you have a<br/>Meshtastic radio?}

    START -->|Yes| LOCAL{Is it connected<br/>to THIS machine?}
    START -->|No| MQTT_MODE[Use MQTT Mode<br/>Connect via broker]

    LOCAL -->|Yes, USB| SERIAL[Serial Mode]
    LOCAL -->|Yes, Bluetooth| BLE[BLE Mode]
    LOCAL -->|No, on network| TCP[TCP Mode]

    SERIAL --> READY[Ready to monitor!]
    BLE --> READY
    TCP --> READY
    MQTT_MODE --> READY

    TEST{Just want to<br/>test things?}
    START -.->|"Not sure"| TEST
    TEST -->|Yes| DEMO[Demo Mode]
    DEMO --> READY

    style START fill:#f39c12,color:#fff
    style READY fill:#27ae60,color:#fff
    style MQTT_MODE fill:#3498db,color:#fff
    style DEMO fill:#9b59b6,color:#fff
```

| Mode | Need Radio? | Use Case |
|------|-------------|----------|
| Serial | Yes (USB) | Radio plugged into this machine |
| TCP | No | Radio on another machine (network) |
| MQTT | No | No radio at all - broker only |
| BLE | Yes | Bluetooth connection |
| Demo | No | Testing/development |

## Configuration

Everything lives in `mesh_client.ini`:

```ini
[connection]
type = mqtt                    # or serial, tcp, ble, auto
mqtt_broker = mqtt.meshtastic.org
mqtt_topic_root = msh/US

[features]
mode = tui                     # tui, web, both, headless
web_port = 8080
```

Run `python3 mesh_client.py --setup` for interactive configuration.

## Pi Zero 2W Setup (Headless, No Radio)

Perfect for a monitoring station using MQTT:

```mermaid
flowchart LR
    A[Run setup_headless.sh] --> B[Install Dependencies]
    B --> C[Create Virtual Env]
    C --> D[Configure MQTT]
    D --> E{Install as Service?}
    E -->|Yes| F[Enable systemd]
    E -->|No| G[Manual Start]
    F --> H[Auto-start on boot]
    G --> H
    H --> I[Access Web UI<br/>:8080]

    style A fill:#e74c3c,color:#fff
    style I fill:#27ae60,color:#fff
```

```sh
chmod +x setup_headless.sh
./setup_headless.sh
```

This sets up:
- Virtual environment (PEP 668 compliant)
- MQTT connection to public broker
- Optional systemd service for auto-start
- Web interface on port 8080

## Keyboard Shortcuts (TUI)

| Key | Action |
|-----|--------|
| `1-4` | Switch screens |
| `s` | Send message |
| `?` | Help |
| `q` | Quit |

## API Endpoints (Web)

| Endpoint | What it does |
|----------|--------------|
| `GET /api/status` | Connection info |
| `GET /api/nodes` | Node list |
| `GET /api/messages` | Message history |
| `POST /api/messages/send` | Send a message |

## How It Works

```mermaid
sequenceDiagram
    participant User
    participant MeshForge
    participant Connection
    participant Mesh as Mesh Network

    User->>MeshForge: Start client
    MeshForge->>MeshForge: Load config
    MeshForge->>Connection: Initialize (Serial/TCP/MQTT/BLE)
    Connection->>Mesh: Connect

    loop Real-time Updates
        Mesh->>Connection: New message/node data
        Connection->>MeshForge: Process & format
        MeshForge->>User: Display in TUI/Web
    end

    User->>MeshForge: Send message
    MeshForge->>Connection: Route message
    Connection->>Mesh: Transmit
    Mesh-->>User: Delivery confirmed
```

## Project Layout

```mermaid
graph LR
    subgraph "Entry Points"
        A[mesh_client.py]
        B[configure_bot.py]
        C[setup_headless.sh]
    end

    subgraph "Clients Package"
        D[core/]
        E[tui/]
        F[web/]
    end

    subgraph "Core Modules"
        G[config.py]
        H[connection_manager.py]
        I[message_handler.py]
        J[models.py]
    end

    A --> D
    A --> E
    A --> F
    D --> G
    D --> H
    D --> I
    D --> J

    style A fill:#4a9eff,color:#fff
    style B fill:#27ae60,color:#fff
    style C fill:#9b59b6,color:#fff
```

```
├── mesh_client.py          # Start here - main launcher
├── mesh_client.ini         # Your configuration
├── configure_bot.py        # Bot setup wizard
├── setup_headless.sh       # Pi/headless installer
└── meshing_around_clients/ # TUI & Web apps
    ├── core/               # Shared code
    ├── tui/                # Terminal interface
    └── web/                # Web dashboard
```

## Requirements

- Python 3.8+
- Dependencies auto-install on first run (or use `--install-deps`)
- For serial: user in `dialout` group

## Contributing

PRs welcome! Please follow these principles:

- **No bare `except:`** - Use specific exception types
- **PEP 668** - Don't auto-install outside venv
- **Rich fallback** - UI should work without Rich library
- **INI config** - Keep everything configurable

## Credits

- [SpudGunMan](https://github.com/SpudGunMan) - meshing-around creator
- [Meshtastic](https://meshtastic.org) - The platform that makes this possible

## Links

- 📦 [meshing-around](https://github.com/SpudGunMan/meshing-around) - The bot this tools supports
- 📚 [Meshtastic Docs](https://meshtastic.org/docs/)
- 🐛 [Report Issues](https://github.com/Nursedude/meshing_around_meshforge/issues)

---

🥔 *Built with care for the Meshtastic community*

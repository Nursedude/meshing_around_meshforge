# CLAUDE.md - MeshForge Project Context

## Repository Ownership & Workflow

**Owner:** Nursedude ([@Nursedude](https://github.com/Nursedude))
**Repository:** `Nursedude/meshing_around_meshforge`

### Session Workflow

1. **Pull to Sync:** User will ask to "pull from meshforge/nursedude" to sync new features
2. **Analyze & Improve:** Review changes, implement improvements for mesh networking domain
3. **MQTT Integration:** This project connects to Meshtastic MQTT brokers to integrate with mesh channels
4. **Session Entropy:** Watch for context degradation - stop and create session notes when this happens
5. **Systematic Work:** Always maintain a task list using TodoWrite

### Key Understanding

- This is Nursedude's repository - not affiliated with external meshforge.org
- Primary focus: Meshtastic mesh network monitoring and integration
- MQTT mode allows participation in mesh networks without radio hardware

---

## Project Overview

MeshForge is a companion toolkit for [meshing-around](https://github.com/SpudGunMan/meshing-around), providing configuration wizards, TUI/Web monitoring clients, and headless deployment scripts for Meshtastic mesh networks.

**Current Version:** 0.5.0-beta
**License:** GPL-3.0
**Python:** 3.8+

## Quick Reference

```bash
# Run the client (auto-detects mode)
python3 mesh_client.py

# Demo mode (no hardware needed)
python3 mesh_client.py --demo

# Interactive setup wizard
python3 mesh_client.py --setup

# Force specific interface
python3 mesh_client.py --tui
python3 mesh_client.py --web

# Configure the meshing-around bot
python3 configure_bot.py

# Headless Pi setup
./setup_headless.sh
```

## Architecture

```
meshing_around_meshforge/
├── mesh_client.py              # Main entry point (zero-dep bootstrap)
├── mesh_client.ini             # Configuration file
├── configure_bot.py            # Bot setup wizard
├── setup_headless.sh           # Pi/headless installer
│
└── meshing_around_clients/     # Main package
    ├── core/                   # Shared components
    │   ├── config.py           # Config management
    │   ├── connection_manager.py # Unified connection handling
    │   ├── meshtastic_api.py   # Direct device API
    │   ├── mqtt_client.py      # MQTT broker connection
    │   ├── message_handler.py  # Message processing
    │   └── models.py           # Data models (Node, Message, Alert)
    ├── tui/
    │   └── app.py              # Rich-based terminal UI
    └── web/
        └── app.py              # FastAPI web dashboard
```

## Connection Modes

| Mode | Radio Required | Use Case |
|------|----------------|----------|
| Serial | Yes (USB) | Direct connection to Meshtastic device |
| TCP | Remote | Connect to device on network |
| MQTT | No | Connect via broker (mqtt.meshtastic.org) |
| BLE | Yes | Bluetooth LE connection |
| Demo | No | Simulated data for testing |

## Code Style Guidelines

### Must Follow

1. **No bare `except:`** - Always use specific exception types
   ```python
   # Bad
   try:
       something()
   except:
       pass

   # Good
   try:
       something()
   except (ValueError, ConnectionError) as e:
       log(f"Error: {e}", "ERROR")
   ```

2. **PEP 668 Compliance** - Never auto-install packages outside virtual environment
   - Use `--break-system-packages` only when user explicitly consents
   - Prefer venv creation via `setup_headless.sh` or `--install-deps`

3. **Rich Library Fallback** - UI must work without Rich installed
   - Check `HAS_RICH` before using Rich features
   - Provide plain-text fallback for all UI elements

4. **INI Configuration** - All features configurable via `mesh_client.ini`
   - No hardcoded values for user-facing settings
   - Use sensible defaults

5. **Zero-dependency Bootstrap** - `mesh_client.py` must start with stdlib only
   - Auto-install dependencies after user consent
   - Never fail on import if deps missing

### Preferences

- Type hints for function signatures
- Docstrings for public functions
- Keep functions focused and small
- Log important operations with appropriate levels (INFO, WARN, ERROR, OK)

## Key Files to Know

| File | Purpose | Notes |
|------|---------|-------|
| `mesh_client.py` | Main launcher | Zero-dep bootstrap, handles venv/deps |
| `mesh_client.ini` | User config | All settings live here |
| `configure_bot.py` | Bot wizard | 12 alert types, email/SMS support |
| `core/connection_manager.py` | Connection logic | Handles all connection types |
| `core/models.py` | Data models | Node, Message, Alert, NetworkState |
| `tui/app.py` | Terminal UI | Rich-based, 4 screens |
| `web/app.py` | Web UI | FastAPI + WebSocket |

## Testing

```bash
# Demo mode tests UI without hardware
python3 mesh_client.py --demo

# Check dependencies without running
python3 mesh_client.py --check

# Test MQTT connectivity
python3 -c "import socket; socket.create_connection(('mqtt.meshtastic.org', 1883), 5); print('OK')"
```

## Common Tasks

### Adding a New Alert Type
1. Add to `configure_bot.py` alert types list
2. Add config section in template
3. Update `ALERT_CONFIG_README.md`

### Adding a New Connection Type
1. Create handler in `core/` (like `mqtt_client.py`)
2. Register in `connection_manager.py`
3. Add config options to `mesh_client.ini` template
4. Update connection mode table in docs

### Modifying the TUI
- Main app in `tui/app.py`
- Uses Rich library with fallback
- 4 screens: Dashboard, Nodes, Messages, Alerts

### Modifying the Web UI
- FastAPI app in `web/app.py`
- Templates in `web/templates/`
- Static files in `web/static/`
- WebSocket at `/ws`

## MQTT Default Credentials

For mqtt.meshtastic.org (public broker):
- Username: `meshdev`
- Password: `large4cats`
- Topic root: `msh/US`

## Raspberry Pi Notes

- Pi Zero 2W: Use MQTT mode (no direct serial recommended)
- Add user to `dialout` group for serial: `sudo usermod -a -G dialout $USER`
- Systemd service installed by `setup_headless.sh`

## Dependencies

Core:
- `rich` - TUI interface
- `paho-mqtt` - MQTT client
- `meshtastic` - Device API

Web:
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `jinja2` - Templates

## Links

- [meshing-around](https://github.com/SpudGunMan/meshing-around) - Parent project
- [Meshtastic Docs](https://meshtastic.org/docs/)
- [Issues](https://github.com/Nursedude/meshing_around_meshforge/issues)

## Version History

- **0.1.0-beta** (2025-01-25) - Initial beta release
  - TUI and Web clients
  - MQTT support (no radio needed)
  - Multi-mode connection manager
  - Headless Pi setup

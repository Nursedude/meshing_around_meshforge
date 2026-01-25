# Changelog

All notable changes to MeshForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0-beta] - 2025-01-25

> ⚠️ **Beta Release** - First public beta. Not fully tested.

### Added
- **TUI Client** - Rich-based terminal interface
  - Dashboard, nodes, messages, alerts screens
  - Keyboard navigation
  - Works over SSH

- **Web Client** - FastAPI-based dashboard
  - Real-time WebSocket updates
  - REST API endpoints
  - Dark theme UI

- **MQTT Support** - Radio-less operation
  - Connect via mqtt.meshtastic.org
  - No hardware required

- **Connection Manager** - Multi-mode connections
  - Serial, TCP, MQTT, BLE support
  - Auto-detection and fallback
  - Reconnection with backoff

- **Standalone Launcher** (`mesh_client.py`)
  - Zero-dependency bootstrap
  - Auto-installs deps on first run
  - Virtual environment support
  - Interactive setup (`--setup`)

- **Headless Setup** (`setup_headless.sh`)
  - Pi Zero 2W support
  - Systemd service integration

- **Configuration Tool** (`configure_bot.py`)
  - 12 alert types
  - Rich UI with fallback
  - PEP 668 compliant

### Fixed
- PEP 668 violations removed (no auto-install outside venv)
- Replaced bare `except:` with specific exceptions
- Fixed `save_config()` bug that wrote template instead of actual config

---

[Unreleased]: https://github.com/Nursedude/meshing_around_meshforge/compare/v0.1.0-beta...HEAD
[0.1.0-beta]: https://github.com/Nursedude/meshing_around_meshforge/releases/tag/v0.1.0-beta

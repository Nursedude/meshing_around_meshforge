# Changelog

All notable changes to MeshForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.0.0] - 2025-01-25

### Added - Meshing-Around Clients
- **TUI Client** (`meshing_around_clients/tui/`)
  - Rich-based terminal interface with real-time monitoring
  - Dashboard, nodes, messages, and alerts screens
  - Keyboard navigation and message sending
  - Works over SSH for headless systems

- **Web Client** (`meshing_around_clients/web/`)
  - FastAPI-based web dashboard
  - Real-time WebSocket updates
  - REST API for integration
  - Modern responsive dark theme UI

- **Core Module** (`meshing_around_clients/core/`)
  - Data models for Node, Message, Alert, MeshNetwork
  - Meshtastic API layer with serial, TCP, BLE support
  - Message handler with command parsing
  - Configuration management

- **MQTT Support** (`mqtt_client.py`)
  - Radio-less operation via MQTT broker
  - Connect to mqtt.meshtastic.org or private brokers
  - Send and receive mesh messages without hardware

- **Unified Connection Manager** (`connection_manager.py`)
  - Auto-detection of best connection type
  - Automatic fallback: serial → TCP → MQTT → demo
  - Reconnection with exponential backoff

- **Standalone Launcher** (`mesh_client.py`)
  - Zero-dependency bootstrap (stdlib only at start)
  - Auto-installs dependencies on first run
  - Virtual environment support
  - Interactive setup wizard (`--setup`)

- **Headless Setup Script** (`setup_headless.sh`)
  - Raspberry Pi Zero 2W support
  - Systemd service integration
  - Interactive configuration

- **Master Configuration File** (`mesh_client.ini`)
  - 100% configurable via INI file
  - Connection, features, alerts, display, logging sections
  - All features can be toggled on/off

### Changed
- Updated documentation with new client features
- Enhanced requirements.txt with categorized dependencies

## [2.2.0] - 2025-01-24

### Added
- Rich library integration for improved terminal UI
- Beautiful panels, tables, and progress indicators
- Color-coded status messages and menus

### Fixed
- Replaced 6 bare `except:` clauses with specific exception types
- Improved error handling throughout codebase

### Changed
- Refactored UI helper functions for Rich compatibility
- Added graceful fallback when Rich is unavailable

## [2.1.0] - 2025-01-23

### Added
- PEP 668 compliance for Debian 12+ systems
- Virtual environment auto-setup
- Serial port auto-detection
- Raspberry Pi hardware detection

### Fixed
- Package name corrections (pubsub → PyPubSub)
- Permission handling for serial ports

## [2.0.0] - 2025-01-22

### Added
- **12 Alert Types** fully configurable:
  1. Emergency Alerts
  2. Proximity Alerts
  3. Altitude Alerts
  4. Weather Alerts
  5. iPAWS/EAS Alerts
  6. Volcano Alerts
  7. Battery Alerts
  8. Noisy Node Detection
  9. New Node Welcomes
  10. SNR Alerts
  11. Disconnect Alerts
  12. Custom Alerts

- Global alert settings (quiet hours, rate limiting, priority levels)
- Email/SMS notification integration
- Sound alert support
- Comprehensive logging per alert type

### Changed
- Complete rewrite of configuration system
- Enhanced INI file structure

## [1.0.0] - 2025-01-20

### Added
- Initial release
- Interactive configuration tool (`configure_bot.py`)
- Enhanced config template (`config.enhanced.ini`)
- Basic alert configuration
- Raspberry Pi support
- Documentation

---

## Version History Summary

| Version | Date | Highlights |
|---------|------|------------|
| 3.0.0 | 2025-01-25 | TUI/Web clients, MQTT support, standalone launcher |
| 2.2.0 | 2025-01-24 | Rich UI integration, exception handling fixes |
| 2.1.0 | 2025-01-23 | PEP 668 compliance, venv support |
| 2.0.0 | 2025-01-22 | 12 alert types, notifications |
| 1.0.0 | 2025-01-20 | Initial release |

[Unreleased]: https://github.com/Nursedude/meshing_around_meshforge/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/Nursedude/meshing_around_meshforge/compare/v2.2.0...v3.0.0
[2.2.0]: https://github.com/Nursedude/meshing_around_meshforge/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/Nursedude/meshing_around_meshforge/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/Nursedude/meshing_around_meshforge/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/Nursedude/meshing_around_meshforge/releases/tag/v1.0.0

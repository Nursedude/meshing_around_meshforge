# Changelog

All notable changes to MeshForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Shared CallbackMixin for callback/cooldown logic (`core/callbacks.py`)
- TUI helper utilities module (`tui/helpers.py`)
- Web security middleware — CSRF, rate limiting (`web/middleware.py`)
- HTTP connection type support in meshtastic_api.py

### Changed
- Deleted dead modules: message_handler.py, connection_manager.py (~3,300 LOC removed)
- Refactored alert config fallbacks to data-driven approach
- Simplified models.py with parse helpers
- Removed duplicate MQTTConfig wrapper class
- Removed unused imports (flake8 F401 cleanup)
- Consolidated Documentation/ into root — deleted CLIENTS_README.md, moved MQTT_INTEGRATION.md

### Fixed
- Resource leaks on partial connection failure
- WebSocket race condition in web/app.py
- Decoded telemetry path wiring in mqtt_client.py
- Channel activity auto-updates

### Security
- **Full security audit** — 22 findings documented in SECURITY_REVIEW.md, 6 fixed
- Fixed WebSocket auth bypass when credentials not configured (CRITICAL)
- Bounded message queue to prevent memory exhaustion on high traffic
- Added MQTT topic component validation (reject null bytes, wildcards, control chars)
- Fixed deprecated `ssl.PROTOCOL_TLS_CLIENT` for Python 3.10+ compatibility
- Added hostname validation for TCP/HTTP interface connections
- Added config validation bounds for port, save interval, reconnect delays
- Hardened web auth, added CSP headers
- Pinned pyopenssl and cryptography to resolve version conflicts
- Improved gitignore and dependency bounds

### Documentation
- Deleted 7+ stale markdown files, consolidated session archives
- Rewrote CODE_REVIEW.md as focused tech debt tracker
- Updated architecture docs to match actual codebase
- Populated CHANGELOG.md [Unreleased] (was empty despite 15+ sessions of work)
- Fixed stale links, dates, and config references across all markdown files

## [0.5.0-beta] - 2026-02-01

> **Beta Release** - Significant improvements over 0.1.0. See Feature Status in README.

### Added
- **Alert Detection System** - Emergency keywords, proximity zones, battery alerts
- **Notification Framework** - Email/SMTP support (untested), SMS gateway structure
- **Command Handler** - Bot command parsing (!ping, !help, etc.)
- **Mermaid Diagrams** - Architecture and feature status visualization in README
- **Upstream Analysis** - Documented interoperability with meshing-around v1.9.9.x

### Changed
- **Honest Version Bump** - Version now reflects actual development state
- **README Overhaul** - Feature status table, working/partial/untested indicators
- **Architecture Docs** - Clear separation of working vs planned features

### Security
- **WebSocket Authentication** - Added token-based authentication for WebSocket connections
- **Localhost-only Binding** - Web server now binds to 127.0.0.1 by default (configurable)
- **Secure Temp Files** - Replaced predictable temp file paths with `tempfile.mkstemp()`
- **Thread-safe Logging** - Added locks to prevent race conditions in log handlers
- **Input Validation** - Hardened message handling and config parsing
- **Connection Security** - Fixed race conditions in connection manager
- **Proper Exception Handling** - Replaced broad exception catches with specific types

### Fixed
- Fixed 32+ code quality and security issues across 14 files (PRs #13, #14, #16)
- Race condition in file logging handler
- Potential security issues in default network bindings
- Thread safety issues in message handler and connection manager
- Memory leaks in long-running WebSocket connections

### Known Issues
- Serial/TCP/BLE modes untested with real hardware
- Web templates may have rendering issues
- MQTT reconnection has limited retry logic
- Email/SMS notifications not tested end-to-end
- Single interface only (upstream supports 9)

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

[Unreleased]: https://github.com/Nursedude/meshing_around_meshforge/compare/v0.5.0-beta...HEAD
[0.5.0-beta]: https://github.com/Nursedude/meshing_around_meshforge/compare/v0.1.0-beta...v0.5.0-beta
[0.1.0-beta]: https://github.com/Nursedude/meshing_around_meshforge/releases/tag/v0.1.0-beta

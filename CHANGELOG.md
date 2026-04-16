# Changelog

All notable changes to MeshForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Shared CallbackMixin for callback/cooldown logic (`core/callbacks.py`)
- `extract_position()` shared helper in `callbacks.py` — validates lat/lon from position data
- `_ensure_node()` DRY helper in `CallbackMixin` — get-or-create node pattern
- `play_alert_sound()` stub in `callbacks.py` — platform audio playback (paplay/aplay/afplay)
- Dynamic demo node discovery in `MockMeshtasticAPI` — 5% chance per event, up to 10 nodes
- TUI helper utilities module (`tui/helpers.py`)
- HTTP connection type support in meshtastic_api.py
- Bot command system with INI-driven `[commands]` config
- Regional profile system (`profiles/`) with `--profile` and `--list-profiles`
- External data source config `[data_sources]` for weather/tsunami/volcano lookups
- Auto-upgrade config on load (adds new INI sections without overwriting)

### Changed
- DRY refactored position extraction — replaced duplicate logic in mqtt_client.py and meshtastic_api.py
- DRY refactored node creation — replaced ~8 duplicate get-or-create patterns with `_ensure_node()`
- Raised CI coverage threshold from 50% to 65% (`ci.yml`)
- Deleted dead modules: message_handler.py, connection_manager.py (~3,300 LOC removed)
- Refactored alert config fallbacks to data-driven approach
- Simplified models.py with parse helpers
- Removed duplicate MQTTConfig wrapper class
- Removed unused imports (flake8 F401 cleanup)
- Consolidated Documentation/ into root — deleted CLIENTS_README.md, moved MQTT_INTEGRATION.md

### Fixed
- Resource leaks on partial connection failure
- Decoded telemetry path wiring in mqtt_client.py
- "cmd"/"help" no longer triggers false emergency alerts (command handler intercepts first)
- Channel activity auto-updates
- **Critical: infinite recursion in `configure_bot.py` fallback `get_user_home()`**
  when core modules failed to import and `SUDO_USER` was unset (PR #154)
- **High: broken USB serial port detection** — `subprocess.run(["ls", "/dev/ttyUSB*"])`
  never shell-expanded the glob, silently returning zero ports.  Switched to
  `glob.glob()` (PR #157)
- Unguarded `int()` / `float()` casts on INI values in `core/config.py` (7 sites,
  PR #154) and `setup/config_schema.py` (20 sites, PR #155) — hand-edited
  `port=abc` no longer crashes config load
- Unguarded `int(stdout)` on `git rev-list --count` output in `check_for_updates`
  (PR #157)
- Four bare `except Exception:` in `mesh_client.py` swallowing file / INI errors
  as "profile not available" (PR #154)
- Silent protobuf decode failures in `mesh_crypto.py` now log at DEBUG (PR #154)
- Silent AES-CTR decrypt / encrypt failures in `mesh_crypto.py` now log at DEBUG
  (PR #155)
- Silent `broker=host:abc` typo in MQTT config now logs WARNING with the
  offending value (PR #155)
- Command responses larger than `MAX_MESSAGE_BYTES` (228) — `lheard`, `leaderboard`
  etc. — were silently rejected by `send_message`.  Now truncated with an
  ellipsis at the dispatch site (PR #157)
- Emergency keyword alerts now honor `_is_alert_cooled_down` (PR #157) —
  previously "MAYDAY MAYDAY MAYDAY" produced one Alert per message
- `MeshNetwork.load_from_file` now logs WARNING on corrupted state JSON instead
  of silently returning an empty network (PR #157)

### Security
- **Full security audit** — 22 findings documented in SECURITY_REVIEW.md, 6 fixed
- Bounded message queue to prevent memory exhaustion on high traffic
- Hard guard: auto_respond blocked on public MQTT brokers even if misconfigured
- Added MQTT topic component validation (reject null bytes, wildcards, control chars)
- Fixed deprecated `ssl.PROTOCOL_TLS_CLIENT` for Python 3.10+ compatibility
- Added hostname validation for TCP/HTTP interface connections
- Added config validation bounds for port, save interval, reconnect delays
- Pinned pyopenssl and cryptography to resolve version conflicts
- Improved gitignore and dependency bounds
- **URL fetch size cap** (1 MiB) in `meshtastic_api._fetch_url` and
  `_fetch_data_source` — prevents OOM on Pi Zero from a misconfigured or
  malicious `data_sources.url` (PR #157)

### CI / Lint
- `.flake8` per-file-ignores tightened — `F401` (unused imports), `F541` (empty
  f-strings), `F841` (unused locals) are no longer silenced on `mesh_client.py`
  or `configure_bot.py`.  Kept `F811` for intentional
  `if not MODULES_AVAILABLE:` fallback redefinitions, and `C901` for naturally
  complex dispatchers.  This was the root cause of the `F821 Config` bug sitting
  latent in main for months (PR #156)
- Tee pytest output to `/tmp/pytest.log` and post failure summaries as PR
  comments on `test` job (PRs #153, #155)
- `codecov.yml` — project and patch checks set to `informational: true` so
  codecov reports without blocking merges; the hard coverage gate remains
  `--cov-fail-under=65` in the workflow itself (PR #153)
- 54 new tests across 7 test modules pinning all the behavior changes above

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
- **Secure Temp Files** - Replaced predictable temp file paths with `tempfile.mkstemp()`
- **Thread-safe Logging** - Added locks to prevent race conditions in log handlers
- **Input Validation** - Hardened message handling and config parsing
- **Connection Security** - Fixed race conditions in connection manager
- **Proper Exception Handling** - Replaced broad exception catches with specific types

### Fixed
- Fixed 32+ code quality and security issues across 14 files (PRs #13, #14, #16)
- Race condition in file logging handler
- Thread safety issues in connection handling

### Known Issues
- Serial/TCP/BLE modes untested with real hardware
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

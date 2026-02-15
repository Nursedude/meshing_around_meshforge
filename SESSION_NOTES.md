# MeshForge Session Notes

**Purpose:** Memory for Claude to maintain continuity across sessions.
**Last Updated:** 2026-02-15 (Code Trim & Deep Review Session)
**Version:** 0.5.0-beta

---

## Quick Reference

```bash
# Run demo mode
python3 mesh_client.py --demo

# Run tests
python3 -m pytest tests/ -v --ignore=tests/test_web_app.py

# Check linting
python3 -m flake8 meshing_around_clients/
python3 -m isort --check-only --diff meshing_around_clients/
```

---

## Current State

### Repository
- **Owner:** Nursedude (`Nursedude/meshing_around_meshforge`)
- **Upstream:** SpudGunMan/meshing-around (v1.9.9.5)
- **Current Version:** 0.5.0-beta
- **Test Status:** 228 tests passing, 49 skipped (MQTT integration, web/fastapi)
- **Branch:** `claude/trim-code-tests-xT3jh`

### Directory Structure (Post-Restructure)

```
meshing_around_meshforge/
├── mesh_client.py              # Main entry point (1045 lines)
├── configure_bot.py            # Bot setup wizard (2003 lines)
├── meshing_around_clients/
│   ├── core/                   # RUNTIME modules only
│   │   ├── __init__.py         # 55 lines, 15 exports
│   │   ├── config.py           # Config loading (533 lines) ✅ SOLID
│   │   ├── models.py           # Data models (1039 lines) ⚠️ 40% dead
│   │   ├── mqtt_client.py      # MQTT connection (1334 lines) ⚠️ 30% dead
│   │   ├── meshtastic_api.py   # Device API (695 lines) ⚠️ some dead
│   │   ├── connection_manager.py # Connection logic (646 lines) ❌ NEVER USED
│   │   ├── message_handler.py  # Command handling (561 lines) ❌ NEVER USED
│   │   └── mesh_crypto.py      # Encryption (713 lines) ❌ 0% EXERCISED
│   ├── setup/                  # SETUP-ONLY modules (configure_bot.py)
│   │   ├── __init__.py         # Docstring only
│   │   ├── cli_utils.py        # Terminal colors, input helpers
│   │   ├── pi_utils.py         # Pi detection, serial ports
│   │   ├── system_maintenance.py # Updates, systemd
│   │   ├── alert_configurators.py # Alert wizards
│   │   └── config_schema.py    # Upstream format conversion
│   ├── tui/app.py              # Terminal UI (1150 lines)
│   └── web/app.py              # Web dashboard (1034 lines)
└── tests/                      # 4848 lines, 12 test files
```

---

## Code Review Findings (2026-02-15)

### Critical Architecture Problem

TUI and Web **bypass ConnectionManager entirely**:
```python
# What TUI/Web actually do:
self.api = MeshtasticAPI(self.config)  # or MockMeshtasticAPI for demo

# What was designed but never used:
manager = ConnectionManager(config)  # NEVER INSTANTIATED
manager.connect()  # fallback chain: serial → TCP → HTTP → MQTT → demo
```

The fallback chain, circuit breaker, reconnect monitor — all theoretical.

### Module-by-Module Status

#### ❌ `message_handler.py` (561 LOC) — 100% DEAD CODE
- Created by TUI (line 835) and Web (line 282) but **never called**
- `process_message()`, `check_alerts()`, `parse_command()` — zero invocations
- Emergency keyword checking done directly in `mqtt_client.py:1156`, not through MessageHandler
- BBSHandler, GameHandler, CommandType, ParsedCommand — all orphaned
- **RECOMMENDATION: Delete entire module**

#### ❌ `connection_manager.py` (646 LOC) — NEVER INSTANTIATED
- `grep -r "ConnectionManager(" meshing_around_clients/` → zero results
- web/app.py defines its own unrelated `ConnectionManager` for WebSocket connections (name collision)
- Fallback chain, `switch_interface()`, circuit breaker, `acknowledge_alert()` — all dead
- **RECOMMENDATION: Delete or actually wire into TUI/Web**

#### ❌ `mesh_crypto.py` (713 LOC) — 0% EXERCISED AT RUNTIME
- `CRYPTO_AVAILABLE = False` (cryptography lib has broken pyo3 backend)
- `PROTOBUF_AVAILABLE = False` (meshtastic package not installed)
- All decryption/decoding paths never entered
- mqtt_client.py always takes fallback path (header-only extraction)
- Code is correct (real AES-256-CTR spec) but never runs
- **RECOMMENDATION: Keep if planning to install deps, otherwise delete**

#### ⚠️ `models.py` (1039 LOC) — ~40% DEAD
Dead code within models:
- `MessageType` enum: 8 values, only `TEXT` ever used
- `AlertType`: 12 values, only 4 instantiated (EMERGENCY, BATTERY, NEW_NODE, CUSTOM)
- `LinkQuality.update()`: never called (EMA calculation dead)
- `Node.heard_by`, `Node.neighbors`, `update_neighbor_relationship()`: never populated
- `Node.routes`: redundant with `MeshNetwork.routes`
- `is_duplicate_message()`, `update_channel_activity()`: never called
- `NodeTelemetry.pressure`, `.gas_resistance`: never displayed
- `Position.precision_bits`: never used
- `VALID_LAT/LON/SNR/RSSI_RANGE` constants: never enforced
- Thread safety concern: `to_dict()` acquires lock, then may recurse into `mesh_health` which also acquires lock → potential deadlock

#### ⚠️ `mqtt_client.py` (1334 LOC) — ~70% FUNCTIONAL
Dead code:
- `get_nodes_with_position()`, `get_online_nodes()`, `get_congested_nodes()`: never called
- `_reconnect_thread`: declared but never started
- `MAP_CACHE_INTERVAL`, `_last_cleanup`: unused
- Encryption handling (~40 lines): always falls through to fallback

Working well:
- JSON message handling, thread safety, paho v1/v2 compat, GeoJSON export

#### ⚠️ `meshtastic_api.py` (695 LOC) — LIMITED
- `meshtastic` library not installed → `connect()` always returns `False`
- TUI handles failure (prompts demo mode)
- Web does NOT handle failure (silent, blank dashboard)
- `MockMeshtasticAPI` works for demo mode
- Dead: `request_position()`, `unregister_callback()`

#### ✅ `config.py` (533 LOC) — SOLID
Cleanest module. Well-used, well-tested, no dead code.

---

## What Was Done This Session (2026-02-15)

### Phase 1: Code & Test Trimming (+180 / -3,999 lines)

**Deleted dead modules:**
- `notifications.py` (527 LOC) — NotificationManager never instantiated
- `alert_detector.py` (397 LOC) — AlertDetector never instantiated outside tests

**Deleted orphaned files:**
- `configure_bot_improved.py` (773 LOC) — unreferenced
- `README_IMPROVEMENTS.md`, `UI_IMPROVEMENTS.md`, `VISUAL_COMPARISON.md` — companion docs
- `run_tui.py`, `run_web.py` — redundant launchers

**Restructured: core/ → setup/**
- Moved 5 setup-only modules to `meshing_around_clients/setup/`:
  `alert_configurators.py`, `cli_utils.py`, `config_schema.py`, `pi_utils.py`, `system_maintenance.py`
- `core/__init__.py` trimmed from 201 lines / 70+ exports to 55 lines / 15 exports
- Updated imports in `configure_bot.py` and `mesh_client.py`

**Test trimming:**
- Deleted `test_module_integration.py` (211 LOC, 90% duplication)
- Deleted `test_alert_detector.py` (507 LOC, tested deleted module)
- Trimmed type-check filler from `test_pi_utils.py` (214→99)
- Removed TestColors/TestPrintFunctions from `test_cli_utils.py` (192→125)
- Removed signature inspection from `test_alert_configurators.py` (234→143)
- Removed enum existence test from `test_message_handler.py`
- Removed AlertDetector tests from `test_persistence_and_dedup.py`
- **91 filler tests removed. 228 pass, 49 skip.**

### Phase 2: Deep Code Review (findings above)

---

## Pending Tasks — Next Session

### P0 — Delete Dead Core Modules (~1,900 LOC removal)
- [ ] Delete `message_handler.py` (561 LOC, 100% dead)
  - Remove `MessageHandler` creation from tui/app.py:835 and web/app.py:282
  - Delete `test_message_handler.py` (644 LOC)
- [ ] Delete or integrate `connection_manager.py` (646 LOC, never instantiated)
  - Delete `test_http_connection.py` if removing ConnectionManager
  - Rename web/app.py's local `ConnectionManager` to `WebSocketManager` to avoid confusion
- [ ] Decide on `mesh_crypto.py` (713 LOC, 0% exercised)
  - Keep only if planning to install cryptography + meshtastic deps

### P1 — Trim Dead Code in Remaining Modules
- [ ] models.py: Remove dead enums, unused fields, uncalled methods (~250 LOC)
  - Remove: `MessageType` enum (or reduce to TEXT only)
  - Remove: unused `AlertType` values
  - Remove: `Node.heard_by`, `Node.neighbors`, `Node.routes`, `update_neighbor_relationship()`
  - Remove: `is_duplicate_message()`, `update_channel_activity()`
  - Remove: `NodeTelemetry.pressure`, `.gas_resistance`, `Position.precision_bits`
  - Remove: unused constants (`VALID_*_RANGE`, threshold docstring-only constants)
  - Fix: `to_dict()` lock recursion with `mesh_health`
- [ ] mqtt_client.py: Remove dead utility methods (~15 LOC)
  - Remove: `get_nodes_with_position()`, `get_online_nodes()`, `get_congested_nodes()`
  - Remove: `_reconnect_thread` declaration and join
  - Remove: `MAP_CACHE_INTERVAL`, `_last_cleanup`
- [ ] meshtastic_api.py: Remove dead methods
  - Remove: `request_position()`, `unregister_callback()`

### P2 — Fix Reliability Issues
- [ ] Web app: Handle `api.connect()` failure (currently silent → blank dashboard)
- [ ] Add warning log when mesh_crypto deps fail (currently silent BaseException catch)

### P3 — Future Architecture Decision
- [ ] Should TUI/Web use ConnectionManager's fallback chain?
  - Current: TUI/Web create MeshtasticAPI directly, manual demo fallback
  - Alternative: Wire ConnectionManager in, get auto-fallback serial→TCP→HTTP→MQTT→demo
  - This is a design decision for the owner, not a code fix

---

## Architecture Notes (Updated)

### Module Import Pattern (Updated)
```python
# configure_bot.py uses try/except with fallback
try:
    from meshing_around_clients.setup.cli_utils import (...)
    from meshing_around_clients.setup.pi_utils import (...)
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False
```

### Actual Runtime Object Graph
```
mesh_client.py
  └── creates MeshtasticAPI or MockMeshtasticAPI directly
        └── TUI/Web poll api.network for nodes/messages/alerts
              └── MQTT: api is MQTTMeshtasticClient (if configured)
              └── Demo: api is MockMeshtasticAPI (generates fake data)
              └── Serial/TCP/HTTP: api is MeshtasticAPI (needs meshtastic lib)
```

ConnectionManager, MessageHandler, and mesh_crypto are NOT in this chain.

### Files Quick Reference (Updated)

| File | Purpose | Status |
|------|---------|--------|
| `mesh_client.py` | Main entry, zero-dep bootstrap | ✅ |
| `configure_bot.py` | Bot setup wizard (~2000 lines) | ✅ |
| `core/config.py` | INI config management | ✅ Solid |
| `core/models.py` | Node, Message, Alert, MeshNetwork | ⚠️ 40% dead |
| `core/mqtt_client.py` | MQTT broker connection | ⚠️ 30% dead |
| `core/meshtastic_api.py` | Device API + MockAPI | ⚠️ Some dead |
| `core/connection_manager.py` | Fallback chain (unused) | ❌ Dead |
| `core/message_handler.py` | Command parsing (unused) | ❌ Dead |
| `core/mesh_crypto.py` | AES-256-CTR (no deps available) | ❌ Dead |
| `tui/app.py` | Rich-based terminal UI | ✅ |
| `web/app.py` | FastAPI web dashboard | ✅ |

---

## Key Decisions

1. **0.5.0-beta version** - Reflects actual development state
2. **setup/ package** - Setup-only modules separated from runtime core/
3. **PEP 668 compliance** - Never auto-install outside venv
4. **Specific exceptions** - No bare except: or except Exception:
5. **core/__init__.py minimal** - Only 15 runtime exports, no setup bloat

---

## Session Workflow

1. **Start:** Read SESSION_NOTES.md to restore context
2. **Work:** Use TodoWrite to track tasks systematically
3. **Monitor:** Watch for session entropy (confusion, repetition, lost context)
4. **End:** Update SESSION_NOTES.md with new state, pending tasks

### Entropy Signals
- Repeating already-completed work
- Losing track of file changes
- Forgetting earlier decisions
- Confusion about codebase structure

**When entropy detected:** Stop immediately, update notes, start new session.

---

## Work History (Summary)

### 2026-02-15 (Code Trim & Deep Review)
- **Phase 1:** Deleted 8 files, moved 5 modules to setup/, trimmed 5 test files
- **Net:** +180 / -3,999 lines. 91 filler tests removed. 228 pass, 49 skip.
- **Phase 2:** Deep review of all 7 remaining core/ modules
- **Finding:** 3 modules (message_handler, connection_manager, mesh_crypto) are 100% dead at runtime (~1,920 LOC)
- **Finding:** models.py and mqtt_client.py have ~40% and ~30% dead code respectively
- Branch: `claude/trim-code-tests-xT3jh`

### 2026-02-12 (meshtasticd HTTP API)
- Added HTTP connection type support via HTTPInterface
- 18 new tests, 320 tests passing
- Branch: `claude/fix-meshtasticd-api-iuLpP`

### 2026-02-12 (TUI Improvements)
- Dashboard stats, pagination, severity filtering, acknowledgment
- Branch: `claude/improve-meshforge-tui-jwCHI`

### 2026-02-12 (Config Unification)
- `[connection]` → `[interface]` + `[mqtt]` sections
- Branch: `claude/unify-config-mqtt-test-ie7a1`

### 2026-02-12 (Code Review & Accessibility)
- 5 bugs fixed (2 critical)
- Branch: `claude/code-review-accessibility-kSLI6`

### 2026-02-11 (CI Fix & Integration Tests)
- httpx, stats test, CSRF double-cookie
- Branch: `claude/integration-tests-failover-EBrRD`

### Earlier Sessions (2026-02-01 through 2026-02-09)
- CSRF, rate limiting, map clustering, MQTT reliability, topology, mesh_crypto
- See git history for details

---

## Commits Reference (This Session)

```
8b656e2 Remove unused re-exports from setup/__init__.py
d7b024e Fix isort formatting in setup/__init__.py
7cf5740 Trim dead code, restructure setup-only modules, prune tests
```

---

*End of session notes - update after each session*

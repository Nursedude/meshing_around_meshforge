# MeshForge Session Notes

**Purpose:** Memory for Claude to maintain continuity across sessions.
**Last Updated:** 2026-02-15 (Architecture Docs & Wiring Session)
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
- **Test Status:** 147 tests passing, 44 skipped (MQTT integration, web/fastapi)
- **Branch:** `claude/update-architecture-docs-IMWQV`

### Directory Structure (Current)

```
meshing_around_meshforge/
├── mesh_client.py              # Main entry point (1045 lines)
├── configure_bot.py            # Bot setup wizard (2003 lines)
├── meshing_around_clients/
│   ├── core/                   # RUNTIME modules only
│   │   ├── __init__.py         # 48 lines, 11 exports
│   │   ├── config.py           # Config loading (533 lines) ✅ SOLID
│   │   ├── models.py           # Data models (1032 lines) ✅ CLEANED
│   │   ├── mqtt_client.py      # MQTT connection (1321 lines) ✅ CLEANED
│   │   ├── meshtastic_api.py   # Device API (678 lines) ✅ CLEANED
│   │   └── mesh_crypto.py      # Encryption (713 lines) ⏳ UPGRADE PATH
│   ├── setup/                  # SETUP-ONLY modules (configure_bot.py)
│   │   ├── __init__.py         # Docstring only
│   │   ├── cli_utils.py        # Terminal colors, input helpers
│   │   ├── pi_utils.py         # Pi detection, serial ports
│   │   ├── system_maintenance.py # Updates, systemd
│   │   ├── alert_configurators.py # Alert wizards
│   │   └── config_schema.py    # Upstream format conversion
│   ├── tui/app.py              # Terminal UI (~1147 lines)
│   └── web/app.py              # Web dashboard (~1034 lines)
└── tests/                      # 3784 lines, 10 test files
```

---

## Architecture Notes

### Actual Runtime Object Graph
```
mesh_client.py
  └── creates MeshtasticAPI or MockMeshtasticAPI directly
        └── TUI/Web poll api.network for nodes/messages/alerts
              └── MQTT: api is MQTTMeshtasticClient (if configured)
              └── Demo: api is MockMeshtasticAPI (generates fake data)
              └── Serial/TCP/HTTP: api is MeshtasticAPI (needs meshtastic lib)
```

mesh_crypto is wired into mqtt_client.py via conditional import — activates
when cryptography + meshtastic deps become available.

### Module Import Pattern
```python
# configure_bot.py uses try/except with fallback
try:
    from meshing_around_clients.setup.cli_utils import (...)
    from meshing_around_clients.setup.pi_utils import (...)
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False
```

### Files Quick Reference

| File | Purpose | Status |
|------|---------|--------|
| `mesh_client.py` | Main entry, zero-dep bootstrap | ✅ |
| `configure_bot.py` | Bot setup wizard (~2000 lines) | ✅ |
| `core/config.py` | INI config management | ✅ Solid |
| `core/models.py` | Node, Message, Alert, MeshNetwork | ✅ Cleaned |
| `core/mqtt_client.py` | MQTT broker connection | ✅ Cleaned |
| `core/meshtastic_api.py` | Device API + MockAPI | ✅ Cleaned |
| `core/mesh_crypto.py` | AES-256-CTR (upgrade path) | ⏳ Waiting on deps |
| `tui/app.py` | Rich-based terminal UI | ✅ |
| `web/app.py` | FastAPI web dashboard | ✅ Fixed |

---

## Key Decisions

1. **0.5.0-beta version** - Reflects actual development state
2. **setup/ package** - Setup-only modules separated from runtime core/
3. **PEP 668 compliance** - Never auto-install outside venv
4. **Specific exceptions** - No bare except: or except Exception:
5. **core/__init__.py minimal** - Only 11 runtime exports, no setup bloat
6. **mesh_crypto kept** - Legitimate upgrade path; mqtt_client.py already has conditional wiring
7. **WebSocketManager rename** - web/app.py's WS connection class renamed from ConnectionManager

---

## Pending Tasks — Future Sessions

### Remaining Opportunities
- [x] Wire `update_channel_activity()` — now auto-updates in `MeshNetwork.add_message()`
- [x] Wire gas_resistance into decoded telemetry path — `_process_decoded_packet()` now extracts environment_metrics
- [x] Update CLAUDE.md architecture section — matches actual codebase
- [x] Update README.md architecture diagram — matches actual codebase
- [ ] MessageType enum: only TEXT is assigned because only text packets create Message objects.
  Position/telemetry/nodeinfo update Node fields directly. Other enum values exist for future use
  if non-text packets need to be logged as messages. Not a bug — leave as-is unless requirements change.

### P3 — Architecture Decision: Connection Fallback Chain
- **Decision: Don't add one.** Current explicit approach is correct.
  - TUI: prompts user for demo mode on connection failure — clear, user-driven
  - Web: logs warning, retries via POST /api/connect — appropriate for headless
  - A fallback chain (Serial→TCP→MQTT→Demo) would silently connect to a different mode
    than intended. For a monitoring tool, users should know exactly what they're connected to.
  - If owner wants auto-fallback in the future, it should be opt-in via config.

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

### 2026-02-15 (Architecture Docs & Wiring — Session 3)
- **Docs:** Updated CLAUDE.md architecture tree, key files table, connection type instructions
  - Removed references to deleted modules (connection_manager, message_handler, alert_detector, notifications)
  - Added setup/ package, mesh_crypto.py, corrected file purposes
- **Docs:** Updated README.md mermaid architecture diagram and project structure tree
  - Diagram now shows actual module relationships (API→Serial/TCP/BLE, MQTT→broker, crypto→mqtt)
  - setup/ package included in structure
- **Bug fix:** Decoded telemetry path (`_process_decoded_packet`) now extracts environment_metrics
  - Was only reading device_metrics, skipping temperature/humidity/pressure/gas_resistance
  - JSON path was correct; protobuf path was missing env metrics entirely
- **Wiring:** `MeshNetwork.add_message()` now auto-updates channel activity
  - Increments `Channel.message_count` and sets `Channel.last_activity` on every message add
  - No separate call needed — tracked automatically inside the lock
- **P3 decision:** Documented recommendation against connection fallback chain
- **MessageType:** Confirmed TEXT-only assignment is correct (non-text packets don't create Message objects)
- **Tests:** 147 pass, 44 skip — no regressions
- Branch: `claude/update-architecture-docs-IMWQV`

### 2026-02-15 (Dead Module Removal & Reliability — Session 2)
- **P0:** Deleted `message_handler.py` (561 LOC) + refs from tui/web + test (644 LOC)
- **P0:** Deleted `connection_manager.py` (646 LOC) + `test_http_connection.py` (275 LOC)
- **P0:** Kept `mesh_crypto.py` (713 LOC) — legitimate upgrade path, already wired
- **P0:** Renamed web/app.py `ConnectionManager` → `WebSocketManager`
- **P0:** Removed `TestConnectionManagerFailoverIntegration` from integration tests (145 LOC)
- **P1:** Trimmed `models.py`: removed `update_channel_activity()` (7 LOC)
  - Previous review was wrong: most "dead" items (is_duplicate_message, update_neighbor_relationship, update_link_quality, update_route, heard_by, neighbors, VALID_*_RANGE, precision_bits) are actually used by mqtt_client.py
- **P1:** Trimmed `mqtt_client.py`: removed 3 dead utility methods, dead attributes, unused constant (29 LOC)
- **P1:** Trimmed `meshtastic_api.py`: removed `request_position()`, `unregister_callback()` (17 LOC)
- **P2:** Fixed web app silent failure — now attempts connect on startup, logs warning on failure
- **P2:** Added info log when mesh_crypto deps unavailable (was silent)
- **core/__init__.py:** Trimmed from 55→48 lines, 15→11 exports
- **Net:** +23 / -2,337 lines. 147 pass, 44 skip.
- Branch: `claude/trim-code-tests-xT3jh`

### 2026-02-15 (Code Trim & Deep Review — Session 1)
- **Phase 1:** Deleted 8 files, moved 5 modules to setup/, trimmed 5 test files
- **Net:** +180 / -3,999 lines. 91 filler tests removed. 228 pass, 49 skip.
- **Phase 2:** Deep review of all 7 remaining core/ modules
- **Finding:** 3 modules (message_handler, connection_manager, mesh_crypto) are 100% dead at runtime
- **Finding:** Previous dead code estimates for models.py were significantly overstated
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

*End of session notes - update after each session*

# MeshForge Session Notes

**Purpose:** Memory for Claude to maintain continuity across sessions.
**Last Updated:** 2026-02-21 (Markdown Cleanup Session)
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

### Directory Structure (Current)

```
meshing_around_meshforge/
├── mesh_client.py              # Main entry point (1045 lines)
├── configure_bot.py            # Bot setup wizard (2003 lines)
├── meshing_around_clients/
│   ├── core/                   # RUNTIME modules only
│   │   ├── __init__.py         # 48 lines, 11 exports
│   │   ├── config.py           # Config loading (533 lines)
│   │   ├── models.py           # Data models (1032 lines)
│   │   ├── mqtt_client.py      # MQTT connection (1321 lines)
│   │   ├── meshtastic_api.py   # Device API (678 lines)
│   │   ├── mesh_crypto.py      # Encryption (713 lines) — upgrade path
│   │   └── callbacks.py        # Shared callback/cooldown mixin (65 lines)
│   ├── setup/                  # SETUP-ONLY modules (configure_bot.py)
│   │   ├── __init__.py         # Docstring only
│   │   ├── cli_utils.py        # Terminal colors, input helpers
│   │   ├── pi_utils.py         # Pi detection, serial ports
│   │   ├── system_maintenance.py # Updates, systemd
│   │   ├── alert_configurators.py # Alert wizards
│   │   └── config_schema.py    # Upstream format conversion
│   ├── tui/
│   │   ├── app.py              # Terminal UI (~1147 lines, 6 screens)
│   │   └── helpers.py          # TUI helper utilities (62 lines)
│   └── web/
│       ├── app.py              # Web dashboard (~1034 lines)
│       └── middleware.py       # CSRF, rate limiting, security (214 lines)
└── tests/                      # 3784 lines, 10 test files
```

---

## Architecture Notes

### Runtime Object Graph
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
| `mesh_client.py` | Main entry, zero-dep bootstrap | Solid |
| `configure_bot.py` | Bot setup wizard (~2000 lines) | Working |
| `core/config.py` | INI config management | Solid |
| `core/models.py` | Node, Message, Alert, MeshNetwork | Cleaned |
| `core/mqtt_client.py` | MQTT broker connection | Cleaned |
| `core/meshtastic_api.py` | Device API + MockAPI | Cleaned |
| `core/mesh_crypto.py` | AES-256-CTR (upgrade path) | Waiting on deps |
| `core/callbacks.py` | Shared callback/cooldown mixin | Working |
| `tui/app.py` | Rich-based terminal UI (6 screens) | Working |
| `tui/helpers.py` | TUI helper utilities | Working |
| `web/app.py` | FastAPI web dashboard | Fixed |
| `web/middleware.py` | CSRF, rate limiting, security | Working |

---

## Key Decisions

1. **0.5.0-beta version** - Reflects actual development state
2. **setup/ package** - Setup-only modules separated from runtime core/
3. **PEP 668 compliance** - Never auto-install outside venv
4. **Specific exceptions** - No bare except: or except Exception:
5. **core/__init__.py minimal** - Only 11 runtime exports, no setup bloat
6. **mesh_crypto kept** - Legitimate upgrade path; mqtt_client.py already has conditional wiring
7. **WebSocketManager rename** - web/app.py's WS connection class renamed from ConnectionManager
8. **No connection fallback chain** - Current explicit approach is correct. Users should know exactly what they're connected to. Auto-fallback would be opt-in via config if ever added.

---

## Pending Tasks — Future Sessions

- [ ] MessageType enum: only TEXT is assigned because only text packets create Message objects.
  Position/telemetry/nodeinfo update Node fields directly. Other enum values exist for future use.
  Not a bug — leave as-is unless requirements change.
- [ ] TUI Rich fallback: CLAUDE.md requires plain-text fallback but TUI exits without Rich (see CODE_REVIEW.md)
- [ ] Remaining broad `except Exception` in configure_bot.py, meshtastic_api.py, mqtt_client.py

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

## Work History

### 2026-02-21 (Markdown Cleanup)
- Deleted QUICK_REFERENCE.md (obsolete), 6 session archive files
- Rewrote CODE_REVIEW.md as focused tech debt tracker (338→~90 lines)
- Updated RELIABILITY_ROADMAP.md, SESSION_NOTES.md, CLIENTS_README.md
- Session archives consolidated — all useful info now in this file

### 2026-02-15 (Architecture Docs & Wiring — 3 sessions)
- Updated CLAUDE.md and README.md architecture to match actual codebase
- Deleted dead modules: message_handler.py, connection_manager.py (+tests, ~3,300 LOC)
- Kept mesh_crypto.py (legitimate upgrade path)
- Fixed decoded telemetry path, wired channel activity auto-updates
- Net: +23 / -2,337 lines. 147 pass, 44 skip.

### 2026-02-12 (4 sessions)
- HTTP connection type support, TUI improvements, config unification, code review fixes

### 2026-02-04 (2 sessions)
- configure_bot.py decomposition, 4 new setup/ modules, exception handling fixes

### 2026-02-01 (2 sessions)
- Version bump to 0.5.0-beta, README rewrite with Mermaid diagrams, upstream analysis

### Earlier (2026-01-25 through 2026-01-31)
- Initial beta, CSRF, rate limiting, map clustering, MQTT reliability, topology, mesh_crypto

---

*End of session notes — update after each session*

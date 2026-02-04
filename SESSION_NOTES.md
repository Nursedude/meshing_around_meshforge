# MeshForge Session Notes

**Purpose:** Memory for Claude to maintain continuity across sessions.
**Last Updated:** 2026-02-04
**Version:** 0.5.0-beta

---

## Quick Reference

```bash
# Run demo mode
python3 mesh_client.py --demo

# Run tests
python3 -m pytest tests/ -v

# Check for broad exceptions
grep -rn "except Exception\|except:" meshing_around_clients/

# Validate Python syntax
python3 -m py_compile configure_bot.py
```

---

## Current State

### Repository
- **Owner:** Nursedude (`Nursedude/meshing_around_meshforge`)
- **Upstream:** SpudGunMan/meshing-around (v1.9.9.5)
- **Current Version:** 0.5.0-beta
- **Test Status:** 240 tests passing

### Code Health
- All broad `except Exception` fixed in core modules
- configure_bot.py decomposed (2307 → ~2000 lines)
- New modular architecture with fallback support

### Recent P1-P2 Improvements (Completed)
- **Multi-interface support** - Up to 9 interfaces in config.py and connection_manager.py
- **Persistent storage** - Network state saved/loaded from ~/.config/meshing-around-clients/
- **Upstream config import** - `--import-config` CLI option for migration
- **Web topology template** - topology.html created and fixed
- **Crypto degradation** - mesh_crypto.py and mqtt_client.py handle missing crypto gracefully
- **MQTT Integration** - Documentation/MQTT_INTEGRATION.md from MeshForge NOC
- **CI/CD Pipeline** - GitHub Actions workflow (.github/workflows/ci.yml)
  - Python 3.8-3.12 test matrix
  - pytest with coverage
  - flake8/black/isort linting

### Key Modules
| Module | Purpose | Lines |
|--------|---------|-------|
| `config_schema.py` | Unified config with upstream support | ~500 |
| `pi_utils.py` | Raspberry Pi detection, PEP 668 | ~350 |
| `system_maintenance.py` | Auto-update, git, systemd | ~450 |
| `cli_utils.py` | Terminal colors, menus, validation | ~400 |
| `alert_configurators.py` | Alert setup wizards | ~300 |
| `mesh_crypto.py` | AES-256-CTR, protobuf decoding | ~450 |

---

## Pending Tasks

### High Priority (P1) - Ready for Physical Testing
- [ ] Hardware testing - Serial mode with real Meshtastic device
- [ ] MQTT testing - Verify mqtt.meshtastic.org connectivity with private channel
- [ ] Integration testing - configure_bot.py modules vs fallback

### Medium Priority (P2) - Code Complete
- [x] Multi-interface support (up to 9 interfaces)
- [x] Upstream config compatibility (ConfigLoader._load_upstream())
- [ ] Web templates - verify all render correctly
- [x] Persistent storage - network state auto-saved
- [ ] CI/CD - GitHub Actions workflow (tests failing, needs investigation)

### Low Priority (P3)
- [ ] Email/SMS notification testing
- [ ] Map visualization for nodes
- [ ] Active traceroute command

---

## Architecture Notes

### Module Import Pattern
```python
# configure_bot.py uses try/except with fallback
try:
    from meshing_around_clients.core.cli_utils import (...)
    from meshing_around_clients.core.pi_utils import (...)
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False
    # Define fallback functions here
```

### Config Schema Design
```
UnifiedConfig
├── interfaces: List[InterfaceConfig]  # 1-9 supported
├── general: GeneralConfig
├── mqtt: MQTTConfig
├── emergency/sentry/altitude/weather/battery alerts
├── smtp/sms: Notification configs
├── tui/web: UI configs
└── auto_update: AutoUpdateConfig
```

### Mesh Topology Tracking
```
MeshNetwork
├── nodes: Dict[str, Node]
├── channels: Dict[int, Channel]
├── routes: Dict[str, MeshRoute]
├── _seen_messages: Set  # Deduplication
└── mesh_health property  # Status, score, avg_snr
```

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

### 2026-02-04 (Today)
- Fixed 6 remaining exception handlers in configure_bot.py
- Decomposed configure_bot.py (removed 307 lines of duplicates)
- All 226 tests passing
- Consolidated session notes

### 2026-02-03
- Added mesh_crypto.py (AES-256-CTR, protobuf decoding)
- Added topology tracking (LinkQuality, MeshRoute, Channel)
- Added TUI TopologyScreen and Web /topology page
- MQTT client now decrypts and decodes messages

### 2026-02-01
- Version bump to 0.5.0-beta
- README rewrite with Mermaid diagrams
- Created RELIABILITY_ROADMAP.md
- Upstream analysis (SpudGunMan/meshing-around)

---

## Key Decisions

1. **0.5.0-beta version** - Reflects actual development state
2. **Fallback architecture** - Modules work with or without new imports
3. **PEP 668 compliance** - Never auto-install outside venv
4. **Specific exceptions** - No bare except: or except Exception:
5. **Upstream compatibility** - Config loader supports both formats

---

## Files Quick Reference

| File | Purpose |
|------|---------|
| `mesh_client.py` | Main entry, zero-dep bootstrap |
| `configure_bot.py` | Bot setup wizard (~2000 lines) |
| `core/mqtt_client.py` | MQTT broker connection |
| `core/mesh_crypto.py` | Encryption, protobuf decode |
| `core/models.py` | Node, Message, Alert, MeshNetwork |
| `core/config.py` | INI config management |
| `tui/app.py` | Rich-based terminal UI |
| `web/app.py` | FastAPI web dashboard |

---

## Commits Reference (Recent)

```
2e0e5c1 Fix remaining exception handling in configure_bot.py
707c695 Decompose configure_bot.py, fix remaining exception handling
ce5c976 Add mesh networking improvements: protobuf, encryption, topology
425824d Bump version to 0.5.0-beta with honest feature assessment
```

---

*End of session notes - update after each session*

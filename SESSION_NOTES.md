# MeshForge Session Notes

**Purpose:** Memory for Claude to maintain continuity across sessions.
**Last Updated:** 2026-02-08
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
- **Test Status:** 295 tests passing (3 skipped: MQTT integration)
- **Meshforge Remote:** `meshforge` → `Nursedude/meshforge` (733+ PRs, `src/` architecture)

### Code Health
- All broad `except Exception` fixed in core modules
- configure_bot.py decomposed (2307 → ~2000 lines)
- New modular architecture with fallback support
- Meshforge robustness patterns synced (input validation, stale cleanup, congestion thresholds)
- **CI/CD linting passes:** black, isort, flake8 all clean
- **configure_bot.py integration bugs fixed** (SerialPortInfo, run_command signatures)
- **Web templates verified** (topology field names, nav link added)

### Recent P1-P2 Improvements (Completed)
- **Multi-interface support** - Up to 9 interfaces in config.py and connection_manager.py
- **Persistent storage** - Network state saved/loaded from ~/.config/meshing-around-clients/
- **Upstream config import** - `--import-config` CLI option for migration
- **Web topology template** - topology.html created and fixed
- **Crypto degradation** - mesh_crypto.py and mqtt_client.py handle missing crypto gracefully
- **MQTT Integration** - Documentation/MQTT_INTEGRATION.md from MeshForge NOC
- **CI/CD Pipeline** - GitHub Actions workflow (.github/workflows/ci.yml)
  - Python 3.9-3.12 test matrix
  - pytest with coverage
  - flake8/black/isort linting (all passing, no longer masked by continue-on-error)

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
- [x] Integration testing - configure_bot.py modules vs fallback (fixed 2 crash bugs)

### Medium Priority (P2) - Code Complete
- [x] Multi-interface support (up to 9 interfaces)
- [x] Upstream config compatibility (ConfigLoader._load_upstream())
- [x] Web templates - verified, field names fixed, topology nav added
- [x] Persistent storage - network state auto-saved
- [x] CI/CD - GitHub Actions linting fixed (black/isort/flake8 all passing)

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
├── cleanup_stale_nodes()  # Prune nodes > 72h, cap at 10k
└── mesh_health property  # Status, score, avg_snr
```

### Robustness Constants (from meshforge)
```
CHUTIL_WARNING_THRESHOLD = 25.0%   # Channel util warning
CHUTIL_CRITICAL_THRESHOLD = 40.0%  # Channel util critical
AIRUTILTX_WARNING_THRESHOLD = 7.0% # TX airtime warning
STALE_NODE_HOURS = 72              # Prune after 72h
MAX_NODES = 10000                  # Memory cap
MAX_PAYLOAD_BYTES = 65536          # Reject oversized MQTT
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

### 2026-02-08
- **Bug fixes:** 2 runtime crash bugs in configure_bot.py
  - `get_serial_ports()` returns SerialPortInfo objects, not strings - crash on `', '.join(ports)`
  - `run_command(desc=...)` param doesn't exist in real module - crash on git clone
- **Web template fixes:** topology.html field names (`snr_avg`→`avg_snr`, `last_update`→`last_used`)
- **Navigation:** Added /topology link to base.html navbar
- **CI/CD pipeline fixed:**
  - Ran isort + black on all 20 files
  - Removed 49 unused imports across 11 files
  - Fixed 4 unused variables, 1 f-string without placeholders, 22 long lines
  - Added `noqa: E402` for intentional post-try/except imports
  - Created pyproject.toml + .flake8 config files
  - Removed `continue-on-error: true` and `--exit-zero` from CI workflow
  - All 3 linters now pass cleanly and CI will fail on violations
- 295 tests passing (3 skipped)
- Branch: `claude/session-management-entropy-DgYug`

### 2026-02-07
- Synced meshforge robustness patterns into core modules (3 files, +395/-54 lines)
- **models.py**: Position.is_valid(), environment metrics, congestion thresholds, stale cleanup
- **mqtt_client.py**: Payload limits, _safe_float/_safe_int validation, stats, atexit, exponential backoff
- **connection_manager.py**: ConnectionBusy, cooldown, connection info, logging
- All 284 tests passing
- Branch: `claude/sync-meshforge-improvements-v5d19`

### 2026-02-04
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
6. **Meshforge patterns** - Input validation (_safe_float/_safe_int), stale node cleanup, congestion thresholds from Meshtastic ROUTER_LATE docs

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
7d1df2a Sync meshforge robustness patterns into core modules
da49678 Merge pull request #36 from Nursedude/claude/review-nursedude-repo-vZ3qB
2e0e5c1 Fix remaining exception handling in configure_bot.py
707c695 Decompose configure_bot.py, fix remaining exception handling
ce5c976 Add mesh networking improvements: protobuf, encryption, topology
```

---

*End of session notes - update after each session*

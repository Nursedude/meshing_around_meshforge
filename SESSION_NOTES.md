# MeshForge Session Notes

**Purpose:** Memory for Claude to maintain continuity across sessions.
**Last Updated:** 2026-04-16 (Sweep Sessions 1-3: post-merge audits + lint hardening + docs)
**Version:** 0.6.0

---

## Quick Reference

```bash
# Run demo mode
python3 mesh_client.py --demo

# Run tests
python3 -m pytest tests/ -v

# Check linting
python3 -m flake8 meshing_around_clients/
python3 -m isort --check-only --diff meshing_around_clients/
```

---

## Current State

### Repository
- **Owner:** Nursedude (`Nursedude/meshing_around_meshforge`)
- **Upstream:** SpudGunMan/meshing-around (v1.9.9.5)
- **Current Version:** 0.6.0 (`__version__` already bumped; release tag pending — see Pending Tasks)
- **Test Status:** 843 tests passing (+54 in PRs #154-#157), 15 skipped
- **Code Coverage:** 67.6% (CI threshold: 65%)
- **Lint Gate:** flake8 F401/F541/F841 now enforced on production code (PR #156)

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
│   │   └── callbacks.py        # Shared callback/cooldown mixin + helpers (223 lines)
│   ├── setup/                  # SETUP-ONLY modules (configure_bot.py)
│   │   ├── __init__.py         # Docstring only
│   │   ├── cli_utils.py        # Terminal colors, input helpers
│   │   ├── pi_utils.py         # Pi detection, serial ports
│   │   ├── system_maintenance.py # Updates, systemd
│   │   ├── alert_configurators.py # Alert wizards
│   │   └── config_schema.py    # Upstream format conversion
│   └── tui/
│       ├── app.py              # Terminal UI (7 screens)
│       └── helpers.py          # TUI helper utilities
├── profiles/                   # Regional config templates (hawaii, europe, etc.)
└── tests/                      # 743 tests across 17 files
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
| `tui/app.py` | Rich-based terminal UI (7 screens) | Working |
| `tui/helpers.py` | TUI helper utilities | Working |

---

## Key Decisions

1. **0.5.0-beta version** - Reflects actual development state
2. **setup/ package** - Setup-only modules separated from runtime core/
3. **PEP 668 compliance** - Never auto-install outside venv
4. **Specific exceptions** - No bare except: or except Exception:
5. **core/__init__.py minimal** - Only 11 runtime exports, no setup bloat
6. **mesh_crypto kept** - Legitimate upgrade path; mqtt_client.py already has conditional wiring
7. **No connection fallback chain** - Current explicit approach is correct. Users should know exactly what they're connected to. Auto-fallback would be opt-in via config if ever added.

---

## Pending Tasks — Future Sessions

### Carried over from sweep sessions (2026-04-16, PRs #154-#158)

- [ ] **Clean up 47 pre-existing pyflakes warnings in `tests/`.** PR #156 tightened
  `.flake8` per-file-ignores on production code (mesh_client.py, configure_bot.py)
  but explicitly left `tests/*.py:E402,F401,F841,C901` relaxed because there are
  47 unused-import / unused-local violations across 14 test files that pre-date
  the audit.  Suggested approach: peel off per-file in 5-10 small commits so each
  is reviewable, then drop F401/F841 from the tests/*.py per-file-ignores.
  Current distribution: test_integration_failover_and_ws_load.py (11),
  test_config_schema.py (10 — likely false positives from late-binding imports),
  test_mqtt_client.py (7), test_tui_app.py (6), conftest.py (4),
  test_persistence_and_dedup.py (3), one each in 7 other files.
- [ ] **Cut 0.6.0 release tag.** `meshing_around_clients/__init__.py` already says
  `__version__ = "0.6.0"`; CHANGELOG `[Unreleased]` is now substantial after
  PRs #154-#158.  Move that block to `[0.6.0] - 2026-04-16` and tag the merge
  commit so users have a stable reference.  CLAUDE.md Version History already
  documents the 0.6.0 entry — just needs the tag.
- [ ] **Sandbox cffi gap (operational, not code).**
  `tests/test_mqtt_client.py::TestMQTTEncryptedDownlink` (5 tests) consistently
  fail in the Anthropic sandbox because `_cffi_backend` isn't installed; they
  pass on every Python version in CI.  No code fix needed — but if a new
  contributor runs the suite locally without the cryptography binary deps,
  they'll see the same 5 failures.  Could add a clearer skip marker that
  detects missing cffi at collection time.

### Older carry-overs (still valid)

- [ ] MessageType enum: only TEXT is assigned because only text packets create Message objects.
  Position/telemetry/nodeinfo update Node fields directly. Other enum values exist for future use.
  Not a bug — leave as-is unless requirements change.
- [ ] TUI Rich fallback: CLAUDE.md requires plain-text fallback but TUI exits without Rich (see CODE_REVIEW.md)
- [ ] ~~Remaining broad `except Exception` in configure_bot.py~~ — covered by PR #156 lint hardening; F-series is enforced now.
- **Session 2 plan:** TUI message search, connection health indicator, log rotation, env var config overrides
- ~~**Session 3 plan:** Test coverage push (65%+), DRY refactors, sound alert stub, dynamic demo nodes, doc updates~~ **Done**

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

### 2026-04-16 (Sweep Sessions 1-3: post-merge audits + lint hardening + docs)

**Five PRs landed in one extended session:**

- **PR #153** — diagnostic CI step: tee pytest output to `/tmp/pytest.log`,
  post failure summary as PR comment via `actions/github-script`, grant
  `pull-requests: write` on the test job.  Added `codecov.yml` setting
  patch/project checks to `informational: true`.
- **PR #154** — first sweep, fixed:
  - **Critical:** infinite recursion in `configure_bot.py:102` fallback
    `get_user_home()` (recursed into itself when `SUDO_USER` unset).
  - **High:** 7 unguarded `int(data.get(...))` casts in `core/config.py`
    `InterfaceConfig.from_dict` and `MQTTConfig.from_dict` (port, baudrate,
    qos, timeouts).  Added `_coerce_int(value, default)` helper.
  - 4 bare `except Exception:` in `mesh_client.py` swallowing INI/file errors.
  - 3 unused typing imports in production code (mesh_client.py:40 `Any`,
    mesh_client.py:1027 `UnifiedConfig`, configure_bot.py:32 `Dict`).
  - Added 16 tests pinning the recursion fix and int coercion behavior.
- **PR #155** — second sweep, found same coercion bug class in a different
  module: 17 `int()` + 3 `float()` casts in `setup/config_schema.py`.  Added
  local `_coerce_int`/`_coerce_float` (kept self-contained, no cross-module
  import).  Also added DEBUG logging to two silent except blocks in
  `core/mesh_crypto.py` and a WARNING log when `mqtt.broker=host:abc` typo
  silently falls back.  11 new tests.
- **PR #156** — root-cause CI fix: `.flake8` per-file-ignores were silencing
  F401 / F541 / F841 for `mesh_client.py` and `configure_bot.py`.  This is
  why the latent F821 bug PR #154 surfaced sat in main for months.  Tightened
  per-file-ignores to keep only `C901` (complexity) and `F811` (intentional
  fallback redefinitions in configure_bot.py).  Fixed the 9 pyflakes
  violations the change exposed in configure_bot.py.
- **PR #157** — third sweep targeting `setup/pi_utils.py`, `setup/system_maintenance.py`
  subprocess flows, and `core/meshtastic_api.py` command handler.  Found:
  - **High:** `pi_utils.get_serial_ports` ran `subprocess.run(["ls", "/dev/ttyUSB*"])`.
    Argv isn't shell-expanded, so ls always exited "no such file" — **USB
    device detection was completely broken**.  Switched to `glob.glob()`.
  - Unguarded `int(stdout.strip())` on `git rev-list --count` output in
    `check_for_updates`.
  - URL fetch had no size cap — a malicious `data_sources.url` could OOM a
    Pi Zero before the 228-byte mesh limit applied.  Cap at 1 MiB.
  - Multi-line command responses (`lheard`, `leaderboard`) routinely
    exceeded 228-byte mesh limit and were silently rejected.  Truncate at
    the dispatch site with ellipsis.
  - Emergency keyword alerts didn't call `_is_alert_cooled_down` —
    "MAYDAY MAYDAY MAYDAY" produced one Alert per message.  Now matches
    battery/congestion alert paths.
  - `MeshNetwork.load_from_file` silently returned empty network on
    `JSONDecodeError`.  Now logs WARNING with path + exception class.
  - 11 new tests, including a UTF-8 boundary truncation test.
- **PR #158** — pure docs.  Recorded the 10 latent-bug patterns in
  `CLAUDE.md`, added MF005 (INI coercion) and MF006 (glob expansion) to
  `.claude/rules/security.md` matching MF001-MF004 format, bumped tests
  badge 806→843 in README, appended sweep findings to CHANGELOG `[Unreleased]`.

**Session totals:** 1 critical + 1 high + 5 medium + 5 low findings fixed,
54 new tests, 0 HIGH bandit, coverage steady at 67.6%, lint gate now catches
the class of bug that was hidden for months.

**Key lesson:** the *root cause* of multiple latent defects was not the
defects themselves — it was `.flake8 per-file-ignores` silencing the lint
rules that would have caught them.  Once #156 lifted those ignores, the
class of bug becomes self-preventing on every future PR.  Worth more than
any individual fix.

### 2026-03-04 (Session 3: Test Coverage + Code Quality + Polish)
- **DRY refactors:** Extracted `extract_position()` shared helper to `callbacks.py` (replaced duplicate in `mqtt_client.py` and `meshtastic_api.py`). Added `_ensure_node()` to `CallbackMixin` (replaced ~8 duplicate get-or-create patterns).
- **Sound alert stub:** Added `play_alert_sound()` to `callbacks.py` — uses platform CLI tools (paplay/aplay/afplay). No new dependencies.
- **Dynamic demo nodes:** `MockMeshtasticAPI._generate_demo_event()` now has 5% chance to discover new nodes (up to 10 total) during demo mode, with alert callbacks.
- **Test coverage push:** 490 → 665 tests passing. Coverage 61% → 67%. Expanded: `test_callbacks.py` (extract_position, _ensure_node, play_alert_sound), `test_models.py` (export, mesh_health, routes), `test_meshtastic_api.py` (dynamic nodes, send_message), `test_cli_utils.py` (print functions), `test_system_maintenance.py` (system_update, install_python_dependencies, manage_service, clone, etc.)
- **CI threshold raised:** `--cov-fail-under=50` → `--cov-fail-under=65`
- **Flake8 cleanup:** Removed unused VALID_LAT_RANGE/VALID_LON_RANGE imports from `mqtt_client.py` and `meshtastic_api.py` (leftover from DRY refactor)
- 665 tests passing, 11 skipped. All lint checks pass (except pre-existing C901 in config.py).

### 2026-03-04 (Session 1: MQTT Reliability + Message Export)
- **MQTT reconnection hardening:** Auth failures (rc=4/5) stop infinite retry, thread-safe `_connected` and rejection window stats, max reconnect attempt enforcement with periodic WARNING logging
- **Worker thread crash detection:** `_running` now uses `threading.Event` for thread-safe reads, worker crash triggers `on_disconnect` callback, `is_healthy()` method for TUI/Web polling, SEC-21 leak mitigation (signal stop before join, track/limit leaked threads)
- **Callback fixes:** Cooldown key separator changed from `:` to `|` (prevents BLE MAC collision), added `unregister_callback()` and `clear_callbacks()` methods
- **Message export feature:** `MeshNetwork.export_messages()` and `export_nodes()` (JSON/CSV), TUI 'e' key on MessagesScreen, Web `/api/messages/export` and `/api/nodes/export` endpoints
- **Config validation dry-run:** `Config.validate()` method checks ports, hostnames, MQTT broker DNS, TLS consistency, auth credential presence; `--check-config` CLI flag
- Updated existing worker thread crash tests for `threading.Event` pattern
- 490 tests passing, 11 skipped. All lint checks pass.

### 2026-02-21 (Security Review Session)
- Created SECURITY_REVIEW.md — full security audit (22 findings, 6 fixed, 6 positive)
- Fixed HIGH: Bounded message queue to 5000 (meshtastic_api.py) — prevents memory exhaustion
- Fixed HIGH: MQTT topic validation — rejects null bytes, wildcards, control chars (mqtt_client.py)
- Fixed HIGH: Deprecated ssl.PROTOCOL_TLS_CLIENT — conditional via hasattr (mqtt_client.py)
- Fixed HIGH: Hostname validation for TCP/HTTP interfaces (meshtastic_api.py)
- Fixed MEDIUM: Config validation bounds for port, save interval, reconnect delays (config.py)
- Updated CODE_REVIEW.md with new code quality findings
- Updated CHANGELOG.md, CLAUDE.md, RELIABILITY_ROADMAP.md

### 2026-02-21 (Markdown Cleanup — Round 2)
- Deleted Documentation/CLIENTS_README.md (redundant with README.md), merged unique content
- Moved Documentation/MQTT_INTEGRATION.md to root, removed Documentation/ directory
- README.md: expanded CLI options, systemd section
- CHANGELOG.md: populated empty [Unreleased] with 3 weeks of missing work
- RELIABILITY_ROADMAP.md: fixed stale progress metrics, removed outdated section, checked off items
- ALERT_CONFIG_README.md: fixed support link, log dates, config file reference
- HARDWARE_TESTING.md: fixed unittest→pytest, trimmed redundant troubleshooting
- MQTT_INTEGRATION.md: fixed Python example (MQTTClient→MQTTMeshtasticClient, correct imports)
- CODE_REVIEW.md: resolved CLIENTS_README documentation issue

### 2026-02-21 (Markdown Cleanup — Round 1)
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
- Initial beta, MQTT reliability, topology, mesh_crypto

---

*End of session notes — update after each session*

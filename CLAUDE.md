# CLAUDE.md - meshing_around_meshforge Project Context

## Repository Ownership & Workflow

**Owner:** Nursedude ([@Nursedude](https://github.com/Nursedude))
**Repository:** `Nursedude/meshing_around_meshforge`

### Session Workflow

1. **Pull to Sync:** User will ask to "pull from meshforge/nursedude" to sync new features
2. **Analyze & Improve:** Review changes, implement improvements for mesh networking domain
3. **MQTT Integration:** This project connects to Meshtastic MQTT brokers to integrate with mesh channels
4. **Session Entropy:** Watch for context degradation - stop and create session notes when this happens
5. **Systematic Work:** Always maintain a task list using TodoWrite

### Key Understanding

- This is Nursedude's repository - not affiliated with external meshforge.org
- Primary focus: Meshtastic mesh network monitoring and integration
- MQTT mode allows participation in mesh networks without radio hardware

---

## Project Overview

meshing_around_meshforge is a companion toolkit for [meshing-around](https://github.com/SpudGunMan/meshing-around), providing configuration wizards, TUI monitoring client, and headless deployment scripts for Meshtastic mesh networks.

**Current Version:** 0.6.0
**License:** GPL-3.0
**Python:** 3.9+ (CI matrix: 3.9, 3.10, 3.11, 3.12, 3.13)

## Quick Reference

```bash
# Run the client (auto-detects mode)
python3 mesh_client.py

# Demo mode (no hardware needed)
python3 mesh_client.py --demo

# Interactive setup wizard (includes regional profile picker)
python3 mesh_client.py --setup

# Apply a regional profile (hawaii, europe, local_broker, etc.)
python3 mesh_client.py --profile hawaii
python3 mesh_client.py --list-profiles

# Upgrade config after pulling new code (adds new sections, keeps your values)
python3 mesh_client.py --upgrade-config

# Force TUI mode
python3 mesh_client.py --tui

# Configure the meshing-around bot
python3 configure_bot.py

# Headless Pi setup
./setup_headless.sh
```

## Architecture

```
meshing_around_meshforge/
├── mesh_client.py              # Main entry point (zero-dep bootstrap)
├── mesh_client.ini             # Configuration file
├── configure_bot.py            # Bot setup wizard
├── setup_headless.sh           # Pi/headless installer
├── profiles/                   # Regional config templates
│   ├── hawaii.ini              # Hawaii (tsunami/volcano/hurricane keywords)
│   ├── default_us.ini          # Continental US defaults
│   ├── europe.ini              # EU 868 MHz band
│   ├── australia_nz.ini        # ANZ (bushfire/cyclone keywords)
│   └── local_broker.ini        # Local Mosquitto (auto_respond enabled)
│
└── meshing_around_clients/     # Main package
    ├── core/                   # Runtime modules
    │   ├── config.py           # Config management (INI loading, profiles)
    │   ├── meshtastic_api.py   # Device API + MockAPI + command handler
    │   ├── mqtt_client.py      # MQTT broker connection (no radio needed)
    │   ├── mesh_crypto.py      # AES-256-CTR decryption (optional deps)
    │   ├── callbacks.py        # Shared callback/cooldown mixin
    │   └── models.py           # Data models (Node, Message, Alert, MeshNetwork)
    ├── setup/                  # Setup-only modules (used by configure_bot.py)
    │   ├── cli_utils.py        # Terminal colors, input helpers
    │   ├── pi_utils.py         # Pi detection, serial ports
    │   ├── whiptail.py         # Whiptail dialog helpers + text fallback
    │   ├── system_maintenance.py # Updates, systemd
    │   ├── alert_configurators.py # Alert wizards
    │   └── config_schema.py    # Upstream format conversion
    └── tui/
        ├── app.py              # Rich-based terminal UI (7 screens)
        └── helpers.py          # TUI helper utilities
```

## Connection Modes

| Mode | Radio Required | Use Case |
|------|----------------|----------|
| Serial | Yes (USB) | Direct connection to Meshtastic device |
| TCP | Remote | Connect to device on network |
| MQTT | No | Connect via broker (mqtt.meshtastic.org) |
| BLE | Yes | Bluetooth LE connection |
| Demo | No | Simulated data for testing |

## Code Style Guidelines

### Must Follow

1. **No bare `except:`** - Always use specific exception types
   ```python
   # Bad
   try:
       something()
   except:
       pass

   # Good
   try:
       something()
   except (ValueError, ConnectionError) as e:
       log(f"Error: {e}", "ERROR")
   ```

2. **PEP 668 Compliance** - Never auto-install packages outside virtual environment
   - Use `--break-system-packages` only when user explicitly consents
   - Prefer venv creation via `setup_headless.sh` or `--install-deps`

3. **Rich Library Fallback** - UI must work without Rich installed
   - Check `HAS_RICH` before using Rich features
   - Provide plain-text fallback for all UI elements

4. **INI Configuration** - All features configurable via `mesh_client.ini`
   - No hardcoded values for user-facing settings
   - Use sensible defaults

5. **Zero-dependency Bootstrap** - `mesh_client.py` must start with stdlib only
   - Auto-install dependencies after user consent
   - Never fail on import if deps missing

6. **INI int/float coercion** - Never call `int(data.get("key", default))` on
   raw INI values — a hand-edited `port=abc` would crash config load.
   Use the local helpers:
   - `core/config.py` → `_coerce_int(value, default)`
   - `setup/config_schema.py` → `_coerce_int` / `_coerce_float`

   ```python
   # Bad
   port = int(data.get("port", 1883))

   # Good
   port = _coerce_int(data.get("port", 1883), 1883)
   ```

7. **No subprocess for glob expansion** - `subprocess.run(["ls", "/dev/ttyUSB*"])`
   does NOT expand globs (argv is not shell-parsed).  Use `glob.glob()`
   instead:

   ```python
   # Bad — silently finds zero ports because ls gets the literal "*"
   subprocess.run(["ls", "/dev/ttyUSB*"], ...)

   # Good
   import glob
   for port in glob.glob("/dev/ttyUSB*"):
       ...
   ```

### Preferences

- Type hints for function signatures
- Docstrings for public functions
- Keep functions focused and small
- Log important operations with appropriate levels (INFO, WARN, ERROR, OK)

## Key Files to Know

| File | Purpose | Notes |
|------|---------|-------|
| `mesh_client.py` | Main launcher | Zero-dep bootstrap, handles venv/deps |
| `mesh_client.ini` | User config | All settings live here |
| `configure_bot.py` | Bot wizard | 12 alert types, email/SMS support |
| `core/config.py` | Config management | INI loading, search paths |
| `core/models.py` | Data models | Node, Message, Alert, MeshNetwork |
| `core/mqtt_client.py` | MQTT connection | Broker connection, packet decode |
| `core/meshtastic_api.py` | Device API | Serial/TCP/HTTP/BLE + MockAPI + command handler |
| `core/mesh_crypto.py` | Encryption | AES-256-CTR, optional deps |
| `tui/app.py` | Terminal UI | Rich-based, 7 screens |
| `setup/whiptail.py` | Dialog helpers | Whiptail menus + print/input fallback |
| `profiles/*.ini` | Regional templates | Hawaii, US, Europe, ANZ, Local Broker |
| `SECURITY_REVIEW.md` | Security audit | 22 findings, severity-rated, remediation status |

## Testing

```bash
# Demo mode tests UI without hardware
python3 mesh_client.py --demo

# Check dependencies without running
python3 mesh_client.py --check

# Test MQTT connectivity
python3 -c "import socket; socket.create_connection(('mqtt.meshtastic.org', 1883), 5); print('OK')"
```

## Common Tasks

### Adding a New Alert Type
1. Add to `configure_bot.py` alert types list
2. Add config section in template
3. Update `ALERT_CONFIG_README.md`

### Adding a New Connection Type
1. Create handler in `core/` (like `mqtt_client.py`)
2. Wire into `meshtastic_api.py` or `mesh_client.py` startup logic
3. Add config options to `mesh_client.ini` template
4. Update connection mode table in docs

### Modifying the TUI
- Main app in `tui/app.py`
- Uses Rich library with fallback
- 7 screens: Dashboard, Nodes, Messages, Alerts, Topology, Devices, Help
- **Launcher menus** (in `mesh_client.py`) use `setup/whiptail.py` — not Rich

### Adding a Regional Profile
1. Create `profiles/your_region.ini` (copy `default_us.ini` as template)
2. Set `[profile]` name, description, region, recommended_hardware
3. Configure `[mqtt]` topic_root, `[alerts]` emergency_keywords, `[data_sources]`
4. Users apply with `--profile your_region` or via setup wizard

### Bot Commands & Data Sources
- Commands configured in `[commands]` INI section
- Data sources (weather, tsunami, volcano) in `[data_sources]` section
- `auto_respond` MUST be false on public MQTT brokers
- Each data source needs user-specific codes (station ID, zone, etc.)

## MQTT Default Credentials

For mqtt.meshtastic.org (public broker):
- Username: `meshdev`
- Password: `large4cats`
- Topic root: `msh/US`

## Raspberry Pi Notes

- Pi Zero 2W: Use MQTT mode (no direct serial recommended)
- Add user to `dialout` group for serial: `sudo usermod -a -G dialout $USER`
- Systemd service installed by `setup_headless.sh`

## Dependencies

Core:
- `rich` - TUI interface
- `paho-mqtt` - MQTT client
- `meshtastic` - Device API

## Links

- [meshing-around](https://github.com/SpudGunMan/meshing-around) - Parent project
- [Meshtastic Docs](https://meshtastic.org/docs/)
- [Issues](https://github.com/Nursedude/meshing_around_meshforge/issues)

## Common Latent-Bug Patterns to Watch

Patterns that produced real defects in this codebase — check for these when
reviewing new code.  All caught and fixed during the sweep audits (PRs
#154–#157):

1. **`.flake8 per-file-ignores` hiding F-series rules.**  Silencing F401
   (unused imports), F541 (empty f-strings), or F841 (unused locals) for
   production code lets real bugs accumulate.  `configure_bot.py` used to
   ignore all three; that masked `F821 undefined name 'Config'` in
   `mesh_client.py` for months because the whole flake8 run was considered
   "noisy."  The project now limits per-file ignores to `C901` (complexity)
   and `F811` (the intentional `if not MODULES_AVAILABLE:` fallback
   redefinitions).

2. **`subprocess.run(["ls", "/dev/ttyUSB*"])`.**  Argv is not shell-parsed;
   `ls` receives the literal `*` and returns "No such file or directory"
   every time.  Used `glob.glob()` — detection was silently broken.

3. **`int(data.get("key", default))` on INI data.**  A user who edits
   `mesh_client.ini` and types a non-numeric port/baudrate/qos would crash
   config load with an uncaught `ValueError` before the UI or logger was
   up.  Always route through `_coerce_int`/`_coerce_float`.

4. **`except Exception: pass` swallowing real errors.**  Four places in
   `mesh_client.py` turned permission errors + corrupted INIs into silent
   "profile not available" returns.  Narrow the catch list to what each
   block can actually produce, and log at DEBUG level so operators have a
   breadcrumb.

5. **Silent crypto failures.**  `mesh_crypto.decrypt()` / `.encrypt()`
   returned `b""` on bad nonce/key — indistinguishable from "successfully
   decrypted an empty payload."  Add `logger.debug("... failed: %s",
   type(e).__name__)` even on narrow catches.

6. **Fallback helpers that recurse on themselves.**  `configure_bot.py`'s
   `if not MODULES_AVAILABLE:` fallback defined `get_user_home()` with
   `return get_user_home()` instead of `Path.home()` — infinite recursion
   whenever `SUDO_USER` wasn't set.  Every fallback helper needs a
   non-recursive base case.

7. **Response length > mesh payload limit.**  `_get_command_response` can
   return 300-400 bytes; `MAX_MESSAGE_BYTES` is 228.  `send_message`
   silently rejected oversize strings with only a WARNING log, leaving
   the sender staring at silence.  Truncate at the dispatch site with an
   ellipsis.

8. **Alert cooldowns not applied to every alert type.**  Battery and
   congestion paths used `_is_alert_cooled_down`; the emergency-keyword
   path didn't — so "MAYDAY MAYDAY MAYDAY" spam produced one Alert per
   message.  New alert paths MUST call the cooldown check.

9. **Unbounded `urlopen().read()`.**  A misconfigured or malicious
   `data_sources.url` pointing at a multi-GB endpoint could OOM a Pi Zero.
   Cap at `_MAX_FETCH_BYTES` (1 MiB) in `meshtastic_api._fetch_url` and
   `_fetch_data_source`.

10. **Silent state-file corruption.**  `MeshNetwork.load_from_file` used
    to return an empty network on `JSONDecodeError` with no log —
    indistinguishable from "file doesn't exist."  Always log at WARNING
    with path + exception class.

## Version History

- **0.6.0** (2026-04-16) — Stability + security hardening sweep
  - Critical: fixed `configure_bot.py:102` infinite recursion in
    `get_user_home()` fallback (PR #154)
  - High: fixed `pi_utils.get_serial_ports` returning zero USB ports
    because `subprocess.run(["ls", "/dev/ttyUSB*"])` never expanded the
    glob (PR #157)
  - Added `_coerce_int` / `_coerce_float` helpers in `core/config.py`
    and `setup/config_schema.py`; routed 27 INI int/float casts through
    them (PRs #154, #155)
  - Narrowed 4 bare `except Exception:` in `mesh_client.py` and added
    `logger.debug` breadcrumbs to 4 silent failure paths in
    `mesh_crypto.py` / `mqtt_client.py` (PRs #154, #155)
  - Capped URL fetch response size to 1 MiB to prevent OOM on Pi Zero
    (PR #157)
  - Truncate oversize command responses to fit `MAX_MESSAGE_BYTES` so
    senders see a clipped reply instead of silence (PR #157)
  - Apply `_is_alert_cooled_down` to emergency keyword detection,
    matching the battery/congestion alert paths (PR #157)
  - Log `JSONDecodeError` in `MeshNetwork.load_from_file` instead of
    silently returning empty (PR #157)
  - CI: lifted `.flake8` per-file-ignores on production code — F401 /
    F541 / F841 now enforced on `mesh_client.py` and `configure_bot.py`
    (PR #156)
  - CI: tee pytest output + post failure summary as PR comment;
    `codecov.yml` set to informational (PRs #153, #155)
  - Tests: 843 passing (+54 new), 67.6% coverage, 0 HIGH bandit
- **0.1.0-beta** (2025-01-25) - Initial beta release
  - TUI client
  - MQTT support (no radio needed)
  - Multi-mode connection manager
  - Headless Pi setup

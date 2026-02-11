# MeshForge Session Notes

**Purpose:** Memory for Claude to maintain continuity across sessions.
**Last Updated:** 2026-02-11
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
- **Test Status:** 410 tests passing (14 skipped: MQTT integration)
- **Meshforge Remote:** `meshforge` → `Nursedude/meshforge` (733+ PRs, `src/` architecture)

### Code Health
- All broad `except Exception` fixed in core modules
- configure_bot.py decomposed (2307 → ~2000 lines)
- New modular architecture with fallback support
- Meshforge robustness patterns synced (input validation, stale cleanup, congestion thresholds)
- **CI/CD pipeline green:** black, isort, flake8 all clean; httpx in test deps
- **configure_bot.py integration bugs fixed** (SerialPortInfo, run_command signatures)
- **Web templates verified** (topology field names, nav link added)
- **MQTT reliability overhaul:** paho v2 compat, thread-safe stats, reconnection, relay nodes
- **Atomic writes:** save_to_file() crash-safe with tempfile + os.replace()
- **Connection health:** double-tap verification pattern from meshforge
- **GeoJSON export:** /api/geojson endpoint + MQTTMeshtasticClient.get_geojson()

### Recent Improvements (2026-02-11)
- **CI Fix: httpx dependency** — Starlette TestClient requires httpx at import time; added to CI pip install
- **CSRF double-cookie bug fix** (web/app.py):
  - `/api/csrf-token` endpoint and CSRF middleware both generated independent tokens
  - Middleware now checks `response.raw_headers` before setting cookie, avoids overwrite
- **Integration test fixes** (test_integration_failover_and_ws_load.py):
  - `test_stats_accumulate_across_session`: was calling `_handle_json_message()` directly
    which skips the stats pipeline; fixed to call `_on_message()` with mock msg object
  - `_on_disconnect` race condition fix: consolidated lock acquisition
  - `_save_in_progress` race condition fix in persistence layer
- **New integration tests**: failover behavior, WebSocket load, MQTT broker reconnection
- **black formatting fix**: line wrapping in CSRF middleware generator expression
- 410 tests passing (14 skipped), 0 lint errors
- Branch: `claude/integration-tests-failover-EBrRD` (PR #51)

### Previous Improvements (2026-02-09)
- **CSRF Protection:** Double-submit cookie middleware on all POST/PUT/DELETE
  - Token generated per session, validated via X-CSRF-Token header
  - JSON requests CORS-protected; form submissions require token
  - API key and Bearer auth requests exempt (not CSRF-vulnerable)
  - `/api/csrf-token` endpoint for frontend token retrieval
- **API Rate Limiting:** Sliding-window per-IP rate limiter middleware
  - 60 RPM default, 20 RPM for write (POST) endpoints
  - X-RateLimit-* headers on all responses
  - 429 Too Many Requests with Retry-After header
- **Message Search/Filter:** Enhanced `/api/messages` with query params
  - `search=` full-text search in message text (case-insensitive)
  - `sender=` filter by sender name or ID (substring match)
  - `since=` ISO timestamp filter for time-based queries
  - Search UI in messages.html with debounced input
- **Map Marker Clustering:** Leaflet.markercluster for 100+ nodes
  - Dark theme cluster styling (cyan/yellow/red by cluster size)
  - Configurable cluster radius, spiderfy on max zoom
  - Chunked loading for performance with large datasets
  - Applied to both template map and embedded fallback map
- **Web Endpoint Test Coverage:** 68 new tests (test_web_app.py)
  - All HTML pages, all API endpoints
  - CSRF token generation/validation (10 unit tests)
  - Rate limiter logic (5 unit tests)
  - Auth-required endpoints (8 tests)
  - Message search/filter (5 tests)
  - Rate limit middleware (2 integration tests)
  - CSRF middleware (3 integration tests)

### Previous P1-P2 Improvements (Completed)
- **Multi-interface support** - Up to 9 interfaces in config.py and connection_manager.py
- **Persistent storage** - Network state saved/loaded from ~/.config/meshing-around-clients/
  - Now uses atomic writes (tempfile + os.replace) for crash safety
- **Upstream config import** - `--import-config` CLI option for migration
- **Web topology template** - topology.html created and fixed
- **Crypto degradation** - mesh_crypto.py and mqtt_client.py handle missing crypto gracefully
- **MQTT Integration** - Documentation/MQTT_INTEGRATION.md from MeshForge NOC
- **CI/CD Pipeline** - GitHub Actions workflow (.github/workflows/ci.yml)
  - Python 3.9-3.12 test matrix
  - pytest with coverage
  - flake8/black/isort linting (all passing, no longer masked by continue-on-error)
- **MQTT Reliability** - paho v2 compat, auto-reconnect, thread-safe stats, relay nodes
- **GeoJSON/Map API** - /api/geojson endpoint for Leaflet.js visualization
- **Connection Health** - Double-tap verification, stale traffic detection
- **Input Validation** - Message length limits (228 chars), channel range (0-7)
- **Relay Node Discovery** - Meshtastic 2.6+ partial node ID handling

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
- [x] Map visualization for nodes (Leaflet.js at /map, GeoJSON markers, route lines)
- [x] Traceroute API endpoint (/api/traceroute with enriched position data)
- [x] CSRF protection (double-submit cookie pattern)
- [x] API rate limiting (sliding-window per-IP)
- [x] Message search/filter (text, sender, time)
- [x] Map marker clustering (Leaflet.markercluster, 100+ nodes)
- [x] Web endpoint test coverage (68 tests)

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

### 2026-02-11 (CI Fix & Integration Test Session)
- **CI failures diagnosed and fixed** across 3 commits:
  1. `httpx` missing from CI pip install — TestClient import fails without it
  2. `test_stats_accumulate_across_session` — called `_handle_json_message()` directly,
     but `messages_received` counter only incremented in `_on_message()` (the MQTT callback);
     fixed to route through `_on_message()` with a mock mqtt message
  3. `test_json_post_with_valid_csrf` — double-cookie conflict: both the `/api/csrf-token`
     route handler and the CSRF middleware generated independent tokens and both called
     `response.set_cookie()`; middleware token (last Set-Cookie header) overwrote route's,
     causing cookie/header mismatch on subsequent POST; fixed middleware to check
     `response.raw_headers` before adding its own cookie
  4. `black` formatting: generator expression line-wrapping preference
- **Root cause pattern**: stats tracking (`_on_message` → `_handle_json_message` dispatch)
  means tests must go through the full callback chain to see counter increments
- **CSRF architecture note**: middleware auto-sets cookie on first visit, but must yield
  to route-level cookie setting when `/api/csrf-token` is explicitly called
- 410 tests passing (14 skipped), all linters clean
- Branch: `claude/integration-tests-failover-EBrRD` (PR #51)

### 2026-02-09 (CSRF, Rate Limit, Search, Clustering Session)
- **CSRF Protection** (web/app.py: CSRFProtection class + middleware):
  - Double-submit cookie pattern with hmac.compare_digest validation
  - JSON requests exempt (CORS-protected), form POSTs require token
  - API key and Bearer auth requests exempt
  - `/api/csrf-token` endpoint + cookie auto-set on first GET
  - Frontend getCsrfToken() helper in app.js
- **Rate Limiting** (web/app.py: RateLimiter class + middleware):
  - Sliding-window per-IP tracking with configurable RPM limits
  - 60 RPM default, 20 RPM write, 120 RPM burst categories
  - X-RateLimit-Limit/Remaining/Reset headers on all responses
  - 429 response with Retry-After when exceeded
- **Message Search/Filter** (web/app.py + messages.html):
  - `/api/messages?search=&sender=&since=` query parameters
  - Case-insensitive text search and sender substring match
  - ISO timestamp `since` filter with proper error handling
  - Debounced search UI with clear button in messages template
- **Map Marker Clustering** (map.html, embedded map in app.py):
  - Leaflet.markercluster@1.5.3 integration
  - Dark theme cluster styling (cyan/yellow/red gradient)
  - `maxClusterRadius: 50`, `disableClusteringAtZoom: 16`, `chunkedLoading: true`
  - Applied to both template-based and embedded fallback maps
- **Web Endpoint Tests** (test_web_app.py: 68 tests):
  - CSRFProtection unit tests (10): token generation, validation logic
  - RateLimiter unit tests (5): limits, categories, IP isolation
  - API endpoint tests (38): all HTML pages, all REST endpoints
  - Auth tests (8): unauthorized, authorized, wrong key
  - Search/filter tests (5): text, sender, since, invalid
  - Middleware integration tests (5): rate limit 429, CSRF cookie
  - Factory function tests (2)
- 363 tests passing (3 skipped), 0 lint errors
- Branch: `claude/csrf-rate-limit-search-eyRLu`

### 2026-02-08 (Map & Traceroute Session)
- **Map Visualization** (new: map.html, web/app.py changes):
  - Leaflet.js map page at `/map` with dark CartoDB tile layer
  - GeoJSON markers from existing `/api/geojson` endpoint
  - Online/offline node coloring with popups (battery, SNR, hardware, altitude)
  - Route line visualization between nodes with known routes
  - Auto-refresh every 30 seconds, fit-to-bounds control
  - Embedded fallback HTML for template-less mode
  - Nav link added to base.html
- **Traceroute API** (`/api/traceroute` endpoint):
  - Returns routes enriched with node positions for map drawing
  - Hop-level lat/lon for route line visualization
  - Destination position included when available
- 284 tests passing (14 skipped), 0 lint errors
- Branch: `claude/test-meshtastic-hardware-mqtt-W97ne`

### 2026-02-08 (Reliability Session)
- **MQTT Reliability Overhaul** (mqtt_client.py, +310/-79 lines):
  - Paho-mqtt v1/v2 API compatibility (`_create_mqtt_client()`, `_PAHO_V2` detection)
  - Built-in reconnection via `reconnect_delay_set()` + proper `_on_disconnect` handling
  - Thread-safe stats with `_stats_lock` (all `_stats` mutations protected)
  - Safe node access: all `self.network.nodes[id]` replaced with `self.network.get_node(id)`
  - Relay node discovery (Meshtastic 2.6+): `_handle_relay_node()` with partial ID placeholders
  - GeoJSON export: `get_geojson()` for Leaflet.js map visualization
  - New methods: `get_online_nodes()`, `get_nodes_with_position()`, `get_congested_nodes()`
  - Clean shutdown: `_stop_event` threading.Event for responsive thread cleanup
  - Intentional vs unexpected disconnect tracking (`_intentional_disconnect` flag)
  - Enriched stats: reconnections, telemetry_updates, position_updates counters
  - MQTT RC code messages for better error logging
- **Atomic File Writes** (models.py):
  - `save_to_file()` now uses tempfile + `os.replace()` for crash-safe persistence
- **Connection Health Double-Check** (connection_manager.py):
  - `_check_connection_health()` implements meshforge's double-tap pattern
  - First tap: is_connected flag, Second tap: traffic flow verification
  - Auto-reconnect when stale >10 minutes without traffic
- **TUI Error Resilience** (tui/app.py):
  - Added error guards in both Live mode and interactive mode render loops
  - Catches transient data issues (AttributeError, KeyError, TypeError, IndexError)
- **Web App Improvements** (web/app.py):
  - `/api/geojson` endpoint for map visualization
  - `/api/congestion` endpoint for channel utilization monitoring
  - Input validation on send_message: empty text, max 228 chars, channel 0-7
  - WebSocket message validation with error responses
- 284 tests passing (14 skipped), 0 lint errors
- Branch: `claude/improve-reliability-features-9jgUT`

### 2026-02-08 (Earlier)
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
2a7420e Fix black formatting in CSRF middleware
6641951 Fix stats test and CSRF token double-cookie conflict
97004e2 Add httpx to CI test dependencies
9d3fbf6 Fix black formatting for CI lint check
bad72b6 Consolidate _on_disconnect lock and fix _save_in_progress race condition
c95fabe Add integration tests for failover/WebSocket load and fix _intentional_disconnect race
```

---

*End of session notes - update after each session*

# MeshForge — Known Issues & Tech Debt

**Last Updated:** 2026-02-21 (Security Review Session)
**Version:** 0.5.0-beta

This document tracks open issues and technical debt. Resolved findings from the original code review (2026-01-27) have been removed — see git history for the full report.

---

## Open Issues

### HIGH

#### TUI exits without Rich — no fallback

**File:** `tui/app.py:1116-1124`

The TUI `sys.exit(1)`s when Rich is not installed. CLAUDE.md requires: *"Rich Library Fallback — UI must work without Rich installed. Provide plain-text fallback for all UI elements."* The exit message suggests `--web` as an alternative, but does not meet the documented requirement.

#### Broad `except Exception` in source files

Several files use `except Exception` where specific types would be better per the project style guide:

| File | Line(s) |
|------|---------|
| `configure_bot.py` | 2007 |
| `meshtastic_api.py` | 230, 239, 716 |
| `mqtt_client.py` | 283 |
| `web/middleware.py` | 203 |

#### Alert cooldown race condition in base class

**File:** `callbacks.py:50-65`

`_is_alert_cooled_down()` reads and writes `_alert_cooldowns` dict without a lock. The MQTT client subclass overrides with locking, but the base class is unprotected. Any future subclass that calls from multiple threads would hit a race.

#### Thread resource leak in worker thread restart

**File:** `meshtastic_api.py:174-188`

`_start_worker_thread()` joins the previous thread with a 5-second timeout. If the thread hangs past the timeout, a new thread starts alongside the old one. Under sustained hangs, threads accumulate.

---

### MEDIUM

#### MQTT credentials hardcoded as fallback defaults

**Files:** `mqtt_client.py`, `mesh_client.py`

The public Meshtastic broker credentials (`meshdev`/`large4cats`) are hardcoded as fallback defaults. These are well-known public credentials, but hardcoding normalizes a pattern that is dangerous when users add private credentials. Config file permissions are set to 0o600 which mitigates the risk.

---

### LOW

#### Deprecated `ssl.PROTOCOL_TLS_CLIENT` usage

**File:** `mqtt_client.py:244`

~~`ssl.PROTOCOL_TLS_CLIENT` is deprecated in Python 3.10+ and will eventually be removed, breaking TLS connections.~~ **Fixed** — now conditionally applied via `hasattr()` check.

#### Missing hostname validation for HTTP/TCP interface

**File:** `meshtastic_api.py:156-168`

~~Hostnames from config were used directly in URL construction without validation.~~ **Fixed** — added regex validation for hostname characters and optional port.

---

### LOW

#### DRY violations in TUI

**File:** `tui/app.py`

- Duplicated battery/SNR rendering logic between DashboardScreen and NodesScreen
- Duplicated severity-to-color mappings between DashboardScreen and AlertsScreen

#### TUI render loop inefficiency

**File:** `tui/app.py`

`run_interactive()` clears and re-renders the full screen every 500ms, causing visible flicker on slower terminals.

---

## Documentation Issues

| Issue | Location | Status |
|-------|----------|--------|
| No security warning about default network binding | README.md | Open |
| ~~CLIENTS_README.md stale config~~ | ~~Documentation/~~ | Resolved — file deleted, content merged into README.md |

---

## Resolved Since Original Review

The following categories of issues were fixed in PRs #13, #14, #16, the security review (2026-02-21), and subsequent sessions:

- Shell injection in `setup_headless.sh` (CRITICAL)
- XSS in web UI (CRITICAL)
- Zero authentication on web API (CRITICAL)
- Web server `0.0.0.0` default binding → now `127.0.0.1`
- WebSocket endpoint authentication added
- `_schedule_async` startup race condition fixed (coroutine buffering)
- Thread safety locks on shared state
- `asyncio.create_task()` from non-async threads
- Position parsing `0 or latitudeI / 1e7` bug
- Config file permissions (0o600)
- Dead WebSocket connections accumulating
- Dead `_schedule_coroutine` helper removed
- Orphaned `configure_bot_improved.py` deleted
- `configure_bot.py` partially decomposed (2307 → 2000 lines)
- 16 additional findings from the original 25-item review
- WebSocket auth bypass when credentials misconfigured (CRITICAL — security review)
- Unbounded message queue in MeshtasticAPI (HIGH — security review)
- Unvalidated MQTT topic components (HIGH — security review)
- Missing config validation bounds for port, intervals, delays (MEDIUM — security review)
- Hostname validation for HTTP/TCP interfaces (HIGH — security review)
- Deprecated SSL constant in MQTT TLS setup (HIGH — security review)

---

*See SECURITY_REVIEW.md for the full security audit.*
*See RELIABILITY_ROADMAP.md for the full development tracking list.*

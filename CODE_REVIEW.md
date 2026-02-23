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

~~Several files used `except Exception` where specific types would be better.~~ **Fixed** — `meshtastic_api.py` and `mqtt_client.py` narrowed to specific exception types. `configure_bot.py:2007` (top-level CLI wizard) and `web/middleware.py:203` (broadcast catch-all) are intentional.

#### Alert cooldown race condition in base class

**File:** `callbacks.py:50-65`

~~`_is_alert_cooled_down()` read and wrote `_alert_cooldowns` dict without a lock.~~ **Fixed** — Added `threading.Lock` (`_cooldown_lock`) to the base `CallbackMixin` class. The MQTT client no longer needs its override.

#### Thread resource leak in worker thread restart

**File:** `meshtastic_api.py:174-188`

~~`_start_worker_thread()` joined the previous thread with a 5-second timeout with no indication if it failed.~~ **Fixed** — Added a warning log when the previous worker thread doesn't stop within the timeout.

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
- Subprocess username validation (HIGH — security hardening session)
- MQTT non-default credentials TLS warning (HIGH — security hardening session)
- Proxy-aware rate limiting (MEDIUM — security hardening session)
- Basic auth non-HTTPS warning (MEDIUM — security hardening session)
- Adaptive malformed MQTT message logging (MEDIUM — security hardening session)
- Broad `except Exception` narrowed in API and MQTT (MEDIUM — security hardening session)
- Alert cooldown race condition in CallbackMixin (HIGH — security hardening session)
- Thread resource leak warning in worker restart (HIGH — security hardening session)

---

*See SECURITY_REVIEW.md for the full security audit.*
*See RELIABILITY_ROADMAP.md for the full development tracking list.*

# MeshForge Security Review

**Date:** 2026-02-21 (updated 2026-04-15)
**Version:** 0.5.0-beta
**Scope:** Full codebase audit — credential handling, network security, input validation, cryptography, subprocess safety, concurrency
**Methodology:** Manual code review of all source files with security-focused analysis

---

## Executive Summary

MeshForge demonstrates solid security fundamentals: restrictive file permissions on config files (0o600), proper input validation on MQTT topics, and bounded queues for resource-constrained devices. Several critical issues from earlier reviews (shell injection, unbounded queues) have been resolved.

**Note:** The web module (`web/app.py`, `web/middleware.py`) was removed from the codebase. All web-related findings (SEC-01, SEC-08, SEC-09, SEC-10, SEC-12, SEC-17) are no longer applicable and have been marked N/A.

| Severity | Count | Key Areas |
|----------|-------|-----------|
| High | 6 | Input validation, TLS config, subprocess args, unbounded queue |
| Medium | 4 | Config bounds, JSON error handling, exception specificity, alert text |
| Low | 5 | Debug logging, timeouts, message size limits, thread leak, dict iteration |
| Informational | 3 | Good practices documented |

**Fixes applied:** 12 targeted code changes across multiple sessions

---

## Findings

### HIGH

#### SEC-02: Unbounded message queue — memory exhaustion

**File:** `meshtastic_api.py`
**Status:** Fixed

`queue.Queue()` was created without a `maxsize`, meaning a burst of messages or a slow consumer could grow the queue without limit, exhausting memory on Pi Zero 2W.

**Fix:** Set `maxsize=5000` and handle `queue.Full` in the enqueue path with a logged warning.

---

#### SEC-03: Unvalidated MQTT topic components

**File:** `mqtt_client.py`
**Status:** Fixed

`topic_root` and `channel` from user config were used directly in MQTT topic strings without validation. Null bytes, embedded wildcards (`#`, `+`), or control characters could cause unexpected broker behavior.

**Fix:** Added `_validate_mqtt_topic_component()` that rejects null bytes, control characters, and MQTT wildcard characters.

---

#### SEC-04: Deprecated SSL protocol constant

**File:** `mqtt_client.py`
**Status:** Fixed

`ssl.PROTOCOL_TLS_CLIENT` is deprecated in Python 3.10+ and may be removed in future versions.

**Fix:** Made `tls_version` parameter conditional on availability via `hasattr()` check.

---

#### SEC-05: Missing hostname validation for HTTP interface

**File:** `meshtastic_api.py`
**Status:** Fixed

No validation on hostname config values used to construct HTTP URLs.

**Fix:** Added regex-based hostname validation accepting only `[a-zA-Z0-9._:-]` characters and optional port number.

---

#### SEC-06: Unvalidated subprocess arguments from config

**Files:** `setup/pi_utils.py`, `setup/system_maintenance.py`
**Status:** Fixed

Username from config passed to `subprocess.run()` without character validation.

**Fix:** Added POSIX username regex validation (`^[a-z_][a-z0-9_-]{0,31}$`) before passing to `sudo usermod`.

---

#### SEC-07: MQTT credentials over unencrypted connection

**File:** `mqtt_client.py`
**Status:** Fixed

MQTT username/password sent in cleartext when TLS not enabled.

**Fix:** Added warning log when non-default credentials are configured without TLS. Public broker credentials (`meshdev`/`large4cats`) excluded from warning.

---

### MEDIUM

#### SEC-11: Missing config validation bounds

**File:** `config.py`
**Status:** Fixed

Several config values had no range validation (`auto_save_interval`, `mqtt.port`, `mqtt.reconnect_delay`).

**Fix:** Added clamping with sensible bounds.

---

#### SEC-14: Weak JSON parsing error handling

**File:** `mqtt_client.py`
**Status:** Fixed

Malformed MQTT messages logged at DEBUG level only. High volumes could go unnoticed.

**Fix:** Added sliding-window rejection rate tracker. WARNING-level summary logged when >10 rejections occur within 60 seconds.

---

#### SEC-15: Broad exception handling in critical paths

**Files:** `meshtastic_api.py`, `mqtt_client.py`
**Status:** Fixed

Several `except Exception` catches where more specific types would be appropriate.

**Fix:** Narrowed to specific exception types. `configure_bot.py` top-level catch is intentional.

---

#### SEC-16: Alert message text not sanitized

**File:** `tui/app.py`
**Status:** Fixed

User-controlled message text included directly in alert metadata. Alerts are consumed by the TUI (Rich-rendered) which handles untrusted content safely.

**Fix:** Added `rich.markup.escape()` to sanitize user-controlled `title` and `message` fields in `_on_alert_received()` before storing in the flash banner. Defense-in-depth against future refactoring that might pass the text to markup-interpreting APIs.

---

### LOW

#### SEC-18: Debug logging may include message content

**File:** `mqtt_client.py`
**Status:** Fixed

Malformed messages logged at DEBUG level with exception details that may include content. Not a risk in production (DEBUG disabled).

**Fix:** Truncated exception details to 80 characters in all three debug log sites. Logs now show exception type and a bounded repr, preventing message content from leaking into log files even when DEBUG is enabled.

---

#### SEC-19: Hardcoded 10-second MQTT connection timeout

**File:** `mqtt_client.py`
**Status:** Fixed

**Fix:** `connect_timeout` is now configurable in `config.py` with validation bounds (1-300s).

---

#### SEC-20: Missing input size limits on MQTT text messages

**File:** `mqtt_client.py`
**Status:** Fixed

**Fix:** Incoming payloads rejected if they exceed `MAX_PAYLOAD_BYTES` (65,536 bytes). Outgoing `send_message()` validates against `MAX_MESSAGE_BYTES` (228 bytes).

---

#### SEC-21: Thread resource leak potential

**File:** `meshtastic_api.py`
**Status:** Fixed

`_start_worker_thread()` joins the previous thread with a 5-second timeout. If the thread hangs, a new thread starts while the old one continues.

**Fix:** Worker threads already use `daemon=True` (cleaned up on process exit). Upgraded leaked-thread logging from WARNING to ERROR with thread name and ident for debugging. The leaked-thread counter (cap at 2) prevents unbounded accumulation. Worker loop checks `_running` event every 0.5s via `queue.get(timeout=0.5)`.

---

#### SEC-22: Node dictionary modification during iteration

**File:** `models.py`
**Status:** Fixed (by design)

`cleanup_stale_nodes()` builds a snapshot list first, then removes in a separate pass under lock. This is the correct pattern — snapshot-then-delete under lock is safe and avoids RuntimeError from dict modification during iteration.

---

### INFORMATIONAL (Positive Findings)

#### SEC-P2: Restrictive config file permissions

Config files are created with `0o600` (owner read/write only). This protects credentials stored in the INI file.

#### SEC-P5: No unsafe serialization

The codebase does not use `pickle`, `eval()`, `exec()`, or other unsafe deserialization. JSON is used for all data interchange.

#### SEC-P7: Public MQTT bot guard

`auto_respond` is hard-blocked on public MQTT brokers (`mqtt.meshtastic.org`) even if misconfigured in the INI. This prevents accidental bot spam on the shared public mesh.

---

## Remediation Status

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| SEC-01 | ~~Critical~~ | ~~WebSocket auth bypass~~ | **N/A** (web module removed) |
| SEC-02 | High | Unbounded message queue | **Fixed** |
| SEC-03 | High | Unvalidated MQTT topics | **Fixed** |
| SEC-04 | High | Deprecated SSL constant | **Fixed** |
| SEC-05 | High | Missing hostname validation | **Fixed** |
| SEC-06 | High | Unvalidated subprocess args | **Fixed** |
| SEC-07 | High | MQTT creds over cleartext | **Fixed** |
| SEC-08 | ~~Medium~~ | ~~Permissive CSP~~ | **N/A** (web module removed) |
| SEC-09 | ~~Medium~~ | ~~Rate limiter not proxy-aware~~ | **N/A** (web module removed) |
| SEC-10 | ~~Medium~~ | ~~Missing CORS config~~ | **N/A** (web module removed) |
| SEC-11 | Medium | Missing config bounds | **Fixed** |
| SEC-12 | ~~Medium~~ | ~~Basic auth over HTTP~~ | **N/A** (web module removed) |
| SEC-13 | Medium | Config path traversal | Open (low risk) |
| SEC-14 | Medium | Weak JSON error handling | **Fixed** |
| SEC-15 | Medium | Broad exception handling | **Fixed** |
| SEC-16 | Medium | Alert text not sanitized | **Fixed** |
| SEC-17 | ~~Medium~~ | ~~CSRF HttpOnly=false~~ | **N/A** (web module removed) |
| SEC-18 | Low | Debug logging exposure | **Fixed** |
| SEC-19 | Low | Hardcoded timeout | **Fixed** |
| SEC-20 | Low | No MQTT msg size limit | **Fixed** |
| SEC-21 | Low | Thread resource leak | **Fixed** |
| SEC-22 | Low | Dict iteration safety | **Fixed** (by design) |

**Fixed:** 16 of 22 original findings (all High, 4 of 10 Medium, 4 of 5 Low)
**N/A:** 6 findings (web module removed from codebase)

---

## Audit 2 — 2026-04-15

Security review of recent PRs and full codebase re-scan. Findings below are new (SEC-23+).

### NEW FINDINGS

#### SEC-23: Dynamic code generation in subprocess (f-string script injection)

**File:** `meshtastic_api.py`
**Severity:** Medium
**Status:** Fixed

`_call_upstream_cmd()` built a Python script via f-string interpolation with `{lat}`, `{lon}`, `{module}`, `{func}` values and executed it with `subprocess.run([python, "-c", script])`. While all values came from hardcoded dicts and validated floats, the pattern was fragile and hard to audit.

**Fix:** Refactored to pass all variable data via environment variables (`MESHFORGE_LAT`, `MESHFORGE_LON`, `MESHFORGE_MODULE`, `MESHFORGE_FUNC`). The `-c` script is now a static string constant (`_UPSTREAM_SCRIPT`) with no interpolation. Added explicit `isinstance()` type guards for lat/lon.

---

#### SEC-24: Unvalidated upstream venv path permissions

**File:** `meshtastic_api.py`
**Severity:** Medium
**Status:** Fixed

`_UPSTREAM_VENV_PYTHON = Path("/opt/meshing-around/venv/bin/python3")` was used without verifying file permissions. A world-writable path at this location would allow arbitrary code execution.

**Fix:** Added `_check_venv_path_safe()` that rejects world-writable paths (`st_mode & S_IWOTH`) before executing via subprocess. Returns empty string if check fails.

---

#### SEC-25: No SAST or dependency scanning in CI

**File:** `.github/workflows/ci.yml`
**Severity:** Medium
**Status:** Fixed

CI pipeline had no static analysis security testing (SAST) and no dependency vulnerability scanning.

**Fix:** Added `security` job to CI with:
- Bandit SAST (HIGH severity blocking, MEDIUM+ informational)
- pip-audit dependency scan (informational, non-blocking)
- Bandit config in `pyproject.toml`

---

#### SEC-26: Coverage enforcement only on single Python version

**File:** `.github/workflows/ci.yml`
**Severity:** Low
**Status:** Fixed

Coverage threshold (65%) was only enforced on Python 3.11. Version-specific code paths on other versions could regress without detection.

**Fix:** Extended coverage enforcement to Python 3.9 (oldest supported) in addition to 3.11.

---

#### SEC-27: setup_headless.sh runs as root without confirmation

**File:** `setup_headless.sh`
**Severity:** Low
**Status:** Fixed

The setup script only warned when running as root but did not require confirmation. This could lead to config files owned by root instead of the target user.

**Fix:** `check_root()` now requires explicit y/N confirmation when EUID=0, defaulting to exit.

---

### Audit 2 — Remediation Status

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| SEC-23 | Medium | f-string script injection in subprocess | **Fixed** |
| SEC-24 | Medium | Unvalidated upstream venv permissions | **Fixed** |
| SEC-25 | Medium | No SAST/dependency scanning in CI | **Fixed** |
| SEC-26 | Low | Coverage enforcement gap | **Fixed** |
| SEC-27 | Low | Root execution without confirmation | **Fixed** |

**All 5 new findings fixed in this audit.**

### Recommendations (Not Yet Implemented)

- **Lock file for reproducible builds:** Generate `requirements.lock` from `pip freeze` for Pi deployments
- **SBOM generation:** Add CycloneDX to CI for software bill of materials
- **Branch protection:** Configure GitHub required status checks and PR reviews for `main`
- **Dependabot:** Enable automated dependency update PRs

---

*See CODE_REVIEW.md for code quality (non-security) findings.*
*See RELIABILITY_ROADMAP.md for the full development tracking list.*

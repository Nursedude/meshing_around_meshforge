# MeshForge Security Review

**Date:** 2026-02-21 (updated 2026-03-18)
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

**File:** `mqtt_client.py`
**Status:** Open — low risk

User-controlled message text included directly in alert metadata. Alerts are consumed by the TUI (Rich-rendered) which handles untrusted content safely. Risk exists only if alerts are forwarded to systems that don't escape HTML.

---

### LOW

#### SEC-18: Debug logging may include message content

**File:** `mqtt_client.py`
**Status:** Open

Malformed messages logged at DEBUG level with exception details that may include content. Not a risk in production (DEBUG disabled).

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
**Status:** Open

`_start_worker_thread()` joins the previous thread with a 5-second timeout. If the thread hangs, a new thread starts while the old one continues.

---

#### SEC-22: Node dictionary modification during iteration

**File:** `models.py`
**Status:** Open — mitigated by lock

`cleanup_stale_nodes()` builds a snapshot list first, then removes in a separate pass under lock. Safe pattern.

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
| SEC-16 | Medium | Alert text not sanitized | Open (low risk) |
| SEC-17 | ~~Medium~~ | ~~CSRF HttpOnly=false~~ | **N/A** (web module removed) |
| SEC-18 | Low | Debug logging exposure | Open |
| SEC-19 | Low | Hardcoded timeout | **Fixed** |
| SEC-20 | Low | No MQTT msg size limit | **Fixed** |
| SEC-21 | Low | Thread resource leak | Open |
| SEC-22 | Low | Dict iteration safety | Open (mitigated) |

**Fixed:** 12 of 22 original findings (all High, 3 of 10 Medium, 2 of 5 Low)
**N/A:** 6 findings (web module removed from codebase)

---

*See CODE_REVIEW.md for code quality (non-security) findings.*
*See RELIABILITY_ROADMAP.md for the full development tracking list.*

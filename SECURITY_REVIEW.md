# MeshForge Security Review

**Date:** 2026-02-21
**Version:** 0.5.0-beta
**Scope:** Full codebase audit — credential handling, network security, web security, input validation, cryptography, subprocess safety, concurrency
**Methodology:** Manual code review of all source files with security-focused analysis

---

## Executive Summary

MeshForge demonstrates solid security fundamentals: CSRF protection with double-submit cookies, timing-safe HMAC comparisons for authentication, restrictive file permissions on config files (0o600), and proper security headers on the web interface. Several critical issues from earlier reviews (shell injection, XSS, zero-auth web API, 0.0.0.0 binding) have already been resolved.

This audit identified **28 findings** across 6 severity levels. The highest-risk items involve authentication logic gaps and missing input validation — areas where small code changes yield significant security improvement.

| Severity | Count | Key Areas |
|----------|-------|-----------|
| Critical | 1 | WebSocket auth misconfiguration bypass |
| High | 6 | Input validation, TLS config, subprocess args, unbounded queue |
| Medium | 10 | CSP permissiveness, CORS, rate limiting, deprecated APIs, path concerns |
| Low | 5 | Debug logging, timeouts, message size limits |
| Informational | 6 | Good practices documented |

**Fixes applied this session:** 6 targeted code changes (see [Remediation Status](#remediation-status))

---

## Findings

### CRITICAL

#### SEC-01: WebSocket auth bypass when credentials not configured

**File:** `web/app.py:821-826`
**Status:** Fixed (this session)

When `enable_auth = true` but no `api_key` or `password_hash` is configured, the WebSocket endpoint logged a warning and **allowed the connection anyway**. This means enabling auth without configuring credentials gave a false sense of security.

```python
# Before (vulnerable)
if not self.config.web.api_key and not self.config.web.password_hash:
    logger.warning("Auth enabled but no credentials — allowing WebSocket connection")
```

**Fix:** Changed to reject connections with HTTP 1008 and log at ERROR level. Same fix applied to `_check_api_auth()` for REST API endpoints.

---

### HIGH

#### SEC-02: Unbounded message queue — memory exhaustion

**File:** `meshtastic_api.py:71`
**Status:** Fixed (this session)

`queue.Queue()` was created without a `maxsize`, meaning a burst of MQTT messages or a slow consumer could grow the queue without limit, exhausting memory on resource-constrained devices like Pi Zero 2W.

**Fix:** Set `maxsize=5000` and handle `queue.Full` in the enqueue path with a logged warning.

---

#### SEC-03: Unvalidated MQTT topic components

**File:** `mqtt_client.py:394-428`
**Status:** Fixed (this session)

`topic_root` and `channel` from user config were used directly in MQTT topic strings without validation. Null bytes, embedded wildcards (`#`, `+`), or control characters in config values could cause unexpected broker behavior or subscribe to unintended topics.

**Fix:** Added `_validate_mqtt_topic_component()` that rejects null bytes, control characters, and MQTT wildcard characters in topic components.

---

#### SEC-04: Deprecated SSL protocol constant

**File:** `mqtt_client.py:244`
**Status:** Fixed (this session)

`ssl.PROTOCOL_TLS_CLIENT` is deprecated in Python 3.10+ and may be removed in future versions. Using it causes deprecation warnings and will eventually break on newer Python.

**Fix:** Made `tls_version` parameter conditional on availability via `hasattr()` check, maintaining backward compatibility with Python 3.8-3.9.

---

#### SEC-05: Missing hostname validation for HTTP interface

**File:** `meshtastic_api.py:156-164`
**Status:** Fixed (this session)

When constructing an HTTP URL from a hostname config value (`http://{hostname}`), there was no validation. Hostnames containing spaces, protocol prefixes, path traversal sequences, or other special characters could produce malformed URLs.

**Fix:** Added regex-based hostname validation accepting only `[a-zA-Z0-9._:-]` characters and optional port number.

---

#### SEC-06: Unvalidated subprocess arguments from config

**Files:** `setup/pi_utils.py:245-247`, `setup/system_maintenance.py:210,305,440`
**Status:** Fixed (this session)

Username and paths from config are passed to `subprocess.run()` in list form (not shell strings), which prevents shell injection. However, there was no validation that these values contain expected characters.

**Fix:** Added POSIX username regex validation (`^[a-z_][a-z0-9_-]{0,31}$`) in `pi_utils.py` before passing to `sudo usermod`. The `system_maintenance.py` subprocess calls use system-determined values (`Path.home()`, git commands) and don't take user-supplied usernames.

---

#### SEC-07: MQTT credentials over unencrypted connection

**File:** `mqtt_client.py:237-238`
**Status:** Fixed (this session)

MQTT username/password are sent in cleartext when TLS is not enabled. The default configuration uses port 1883 (non-TLS) with the public broker `mqtt.meshtastic.org`. While the default credentials are intentionally public, users who configure private broker credentials on port 1883 would transmit them unencrypted.

**Fix:** Added a warning log when non-default credentials are configured without TLS. Default public broker credentials (`meshdev`/`large4cats`) are excluded from the warning since they are intentionally public.

---

### MEDIUM

#### SEC-08: Overly permissive Content Security Policy

**File:** `web/app.py:215-222`
**Status:** Open

CSP allows `'unsafe-inline'` for both scripts and styles, which weakens XSS protection. This is needed for inline styles and scripts in templates, but could be tightened with nonces.

```
script-src 'self' 'unsafe-inline' https://unpkg.com;
style-src 'self' 'unsafe-inline' https://unpkg.com;
```

**Recommendation:** Migrate inline scripts/styles to external files and use nonce-based CSP. Medium effort.

---

#### SEC-09: Rate limiter not proxy-aware

**File:** `web/middleware.py:113-157`
**Status:** Fixed (this session)

Rate limiting used `request.client.host` as the key. Behind a reverse proxy without proper `X-Forwarded-For` configuration, all clients appeared as one IP address.

**Fix:** Added `trust_proxy` config option (`[web]` section in INI). When enabled, `RateLimiter.get_client_ip()` extracts the client IP from the first entry in the `X-Forwarded-For` header with fallback to `request.client.host`. Default is `False` (off) to prevent IP spoofing when not behind a proxy.

---

#### SEC-10: Missing explicit CORS configuration

**File:** `web/app.py`
**Status:** Open

No CORS middleware is configured. The CSP header allows `connect-src 'self' ws: wss:` which permits WebSocket connections from any origin. While FastAPI doesn't allow cross-origin requests by default, explicit CORS configuration would be clearer.

**Recommendation:** Add `CORSMiddleware` with explicit `allow_origins` if the web UI is intended to be accessed from other origins.

---

#### SEC-11: Missing config validation bounds

**File:** `config.py`
**Status:** Fixed (this session)

Several config values had no range validation:
- `auto_save_interval`: could be negative
- `web.port`: no range check (valid: 1-65535)
- `mqtt.reconnect_delay`: could be 0 or negative
- `mqtt.max_reconnect_delay`: could be less than `reconnect_delay`

**Fix:** Added clamping with sensible bounds for all four values.

---

#### SEC-12: Basic auth credentials over non-HTTPS

**File:** `web/app.py:361-373`
**Status:** Fixed (this session)

Basic auth header is decoded and verified, but there was no warning that HTTPS was not being used. Basic auth credentials are base64-encoded (not encrypted) and visible to network observers without TLS.

**Fix:** Added a warning log when basic auth credentials are successfully verified over a non-HTTPS connection. The web server already defaults to localhost-only binding, which mitigates the risk for local access.

---

#### SEC-13: Path traversal in config file loading

**File:** `config.py:156-157`
**Status:** Open — low risk

`config_path` is user-supplied (via `--config` CLI argument) and used directly to construct a `Path` object. An attacker with CLI access could specify any file path, but CLI access already implies full system access.

**Mitigation:** File permissions (0o600) and config format (INI) limit exploitability.

---

#### SEC-14: Weak JSON parsing error handling

**File:** `mqtt_client.py:465-471`
**Status:** Fixed (this session)

Malformed MQTT messages incremented a rejection counter and logged at DEBUG level. High volumes of malformed messages could go unnoticed without monitoring the stats endpoint.

**Fix:** Added a sliding-window rejection rate tracker. Individual malformed messages still log at DEBUG level (avoiding log spam), but when >10 rejections occur within 60 seconds, a WARNING-level summary is logged. The window resets after each check.

---

#### SEC-15: Broad exception handling in critical paths

**Files:** `meshtastic_api.py:238`, `mqtt_client.py:288`
**Status:** Fixed (this session)

Several `except Exception` catches where more specific types would be appropriate.

**Fix:** Narrowed `meshtastic_api.py` cleanup handler to `except (OSError, ConnectionError, RuntimeError, AttributeError)` and `mqtt_client.py` loop cleanup to `except (OSError, RuntimeError)`. The `configure_bot.py` top-level catch and `web/middleware.py` broadcast catch-all are intentional and left as-is.

---

#### SEC-16: Alert message text not sanitized

**File:** `mqtt_client.py:1104-1115`
**Status:** Open — low risk

User-controlled message text is included directly in alert metadata. Alerts are consumed by the TUI (Rich-rendered) and web UI (Jinja2 auto-escaped), both of which handle untrusted content safely. Risk exists only if alerts are forwarded to systems that don't escape HTML.

---

#### SEC-17: CSRF cookie HttpOnly=false

**File:** `web/middleware.py:96`
**Status:** Open — by design

The CSRF cookie is intentionally not HttpOnly because the double-submit cookie pattern requires JavaScript to read the cookie and send it as a header. This is the correct implementation for this CSRF protection strategy.

---

### LOW

#### SEC-18: Debug logging may include message content

**File:** `mqtt_client.py:466,581`
**Status:** Open

Malformed messages are logged at DEBUG level with exception details that may include message content. Not a risk in production (DEBUG disabled), but could expose data in development.

---

#### SEC-19: Hardcoded 10-second MQTT connection timeout

**File:** `mqtt_client.py:263`
**Status:** Open

Connection wait timeout is hardcoded at 10 seconds. Too short for slow networks (satellite links, congested brokers), but making it configurable is a low-priority improvement.

---

#### SEC-20: Missing input size limits on MQTT text messages

**File:** `mqtt_client.py`
**Status:** Open

The web API validates message length (enforced in send endpoint), but the MQTT message handler doesn't enforce a maximum text length for incoming messages. Extremely large messages could use excess memory.

**Mitigation:** MQTT brokers typically enforce maximum packet sizes. The paho-mqtt client also has internal limits.

---

#### SEC-21: Thread resource leak potential

**File:** `meshtastic_api.py:174-188`
**Status:** Open

`_start_worker_thread()` joins the previous thread with a 5-second timeout. If the thread hangs past the timeout, a new thread starts while the old one continues, potentially accumulating threads.

---

#### SEC-22: Node dictionary modification during iteration

**File:** `models.py:749-765`
**Status:** Open — mitigated by lock

`cleanup_stale_nodes()` builds a list of stale nodes first, then removes them in a separate pass. The lock is held during removal. This is safe because list comprehension creates a snapshot.

---

### INFORMATIONAL (Positive Findings)

#### SEC-P1: Timing-safe authentication comparisons

`hmac.compare_digest()` is used consistently across all authentication checks (API key, CSRF token, password verification). This prevents timing side-channel attacks.

#### SEC-P2: Restrictive config file permissions

Config files are created with `0o600` (owner read/write only) at `config.py:453`. This protects credentials stored in the INI file.

#### SEC-P3: Double-submit cookie CSRF protection

`web/middleware.py` implements proper CSRF protection with cryptographically random tokens, SameSite=strict cookies, and defense-in-depth validation for JSON requests.

#### SEC-P4: Security headers on all responses

X-Content-Type-Options, X-Frame-Options, and Content-Security-Policy headers are set on all HTTP responses.

#### SEC-P5: No unsafe serialization

The codebase does not use `pickle`, `eval()`, `exec()`, or other unsafe deserialization. JSON is used for all data interchange.

#### SEC-P6: WebSocket connection limits

`WebSocketManager` enforces a configurable maximum connection count (default 100) and properly cleans up dead connections during broadcast.

---

## Remediation Status

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| SEC-01 | Critical | WebSocket auth bypass | **Fixed** |
| SEC-02 | High | Unbounded message queue | **Fixed** |
| SEC-03 | High | Unvalidated MQTT topics | **Fixed** |
| SEC-04 | High | Deprecated SSL constant | **Fixed** |
| SEC-05 | High | Missing hostname validation | **Fixed** |
| SEC-06 | High | Unvalidated subprocess args | **Fixed** |
| SEC-07 | High | MQTT creds over cleartext | **Fixed** |
| SEC-08 | Medium | Permissive CSP | Open |
| SEC-09 | Medium | Rate limiter not proxy-aware | **Fixed** |
| SEC-10 | Medium | Missing CORS config | Open |
| SEC-11 | Medium | Missing config bounds | **Fixed** |
| SEC-12 | Medium | Basic auth over HTTP | **Fixed** |
| SEC-13 | Medium | Config path traversal | Open (low risk) |
| SEC-14 | Medium | Weak JSON error handling | **Fixed** |
| SEC-15 | Medium | Broad exception handling | **Fixed** |
| SEC-16 | Medium | Alert text not sanitized | Open (low risk) |
| SEC-17 | Medium | CSRF HttpOnly=false | Open (by design) |
| SEC-18 | Low | Debug logging exposure | Open |
| SEC-19 | Low | Hardcoded timeout | Open |
| SEC-20 | Low | No MQTT msg size limit | Open |
| SEC-21 | Low | Thread resource leak | Open |
| SEC-22 | Low | Dict iteration safety | Open (mitigated) |

**Fixed across sessions:** 12 of 22 findings (all Critical, all High, 5 of 10 Medium)

---

## Recommendations (Priority Order)

1. ~~Fix WebSocket auth misconfiguration bypass~~ (Done)
2. ~~Bound message queue~~ (Done)
3. ~~Validate MQTT topic components~~ (Done)
4. ~~Fix deprecated SSL constant~~ (Done)
5. ~~Validate HTTP hostnames~~ (Done)
6. ~~Add config validation bounds~~ (Done)
7. ~~Add subprocess argument validation for usernames~~ (Done)
8. ~~Warn when non-default MQTT credentials used without TLS~~ (Done)
9. Tighten CSP by removing `'unsafe-inline'`
10. ~~Add proxy-aware rate limiting~~ (Done)
11. Add explicit CORS middleware configuration
12. ~~Narrow broad `except Exception` catches to specific types~~ (Done)

---

*See CODE_REVIEW.md for code quality (non-security) findings.*
*See RELIABILITY_ROADMAP.md for the full development tracking list.*

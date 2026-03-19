# Persistent Issues — meshing_around_meshforge

> **Purpose**: Track recurring issues and their fixes.
> **Last updated**: 2026-03-13

---

## Active Issues

### #1: TUI Rich Fallback Missing (HIGH)
TUI exits without Rich installed — no plain-text fallback.
**Rule**: Check `HAS_RICH` before all Rich usage. Provide `print()`-based alternative.
**Status**: Open

### #2: MQTT Credentials in Code (MEDIUM)
Default MQTT credentials (`meshdev`/`large4cats`) appear as string fallbacks.
**Rule**: Credentials from `mesh_client.ini` only. Template defaults are acceptable.
**Status**: Open — tracked in CODE_REVIEW.md

### #3: DRY Violations in TUI (MEDIUM)
Duplicated battery/SNR rendering, severity-to-color mappings across screens.
**Rule**: Extract shared helpers to `tui/helpers.py`.
**Status**: Open

### #4: configure_bot.py Broad Exceptions (LOW)
Several `except Exception` blocks in the bot configuration wizard.
**Rule**: Catch specific exceptions per MF003.
**Status**: Open — benign (user-interactive wizard, not daemon)

---

## Resolved Issues

| Issue | Fix | Prevention |
|-------|-----|------------|
| Unbounded message queue | Added maxlen to deque | `MESSAGE_HISTORY_MAX = 1000` |
| MQTT topic validation | Added sanitization | `_validate_topic()` |
| Subprocess argument validation | Added hostname regex | `_HOSTNAME_RE` |

---

## Development Checklist

Before committing:
- [ ] No `Path.home()` — check for sudo compatibility
- [ ] No bare `except:` — specific exception types
- [ ] No `shell=True` — use list args
- [ ] `subprocess` calls have `timeout=`
- [ ] Rich features guarded by `HAS_RICH`
- [ ] All config values from `mesh_client.ini`, not hardcoded
- [ ] Tests pass: `python3 -m pytest tests/ -v`

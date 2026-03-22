# Persistent Issues — meshing_around_meshforge

> **Purpose**: Track recurring issues and their fixes.
> **Last updated**: 2026-03-22

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

### #5: Rich Markup `[s]` = Strikethrough (RESOLVED)
`[s]` in Rich markup means strikethrough. Keyboard shortcut labels like `[s] send` in
Panel subtitles caused all text after them to be struck through.
**Rule**: Always escape bracket shortcuts in Rich markup: `\\[s]`, `\\[r]`, `\\[q]`, etc.
Use `Text("literal [s] text")` (no markup) or `\\[s]` in markup strings.
**Status**: Fixed 2026-03-22

### #6: Dashboard Shows MQTT Labels in TCP Mode (RESOLVED)
When connected via TCP/serial, dashboard showed "Topic: -", "Channels: -", "MQTT Rx: -"
which were meaningless. Now adapts labels per connection type.
**Status**: Fixed 2026-03-22

---

## Resolved Issues

| Issue | Fix | Prevention |
|-------|-----|------------|
| Rich `[s]` strikethrough | Escape as `\\[s]` in markup | Never use bare `[letter]` in Rich markup strings |
| Dashboard MQTT labels in TCP | Adapt labels per `conn.interface_type` | Check connection type before showing mode-specific labels |
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
- [ ] No bare `[s]`, `[b]`, `[i]`, `[u]` in Rich markup — escape as `\\[s]` etc.
- [ ] All config values from `mesh_client.ini`, not hardcoded
- [ ] Tests pass: `python3 -m pytest tests/ -v`

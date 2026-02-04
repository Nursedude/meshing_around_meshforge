# Session Notes: MeshForge TUI Interoperability Analysis

**Date:** 2026-02-01
**Session ID:** session_015u4F88ez3TNSNavFQZUFeT
**Branch:** `claude/meshfroge-tui-integration-xWPOZ`

## Summary

Compared MeshForge (this repo) with upstream `SpudGunMan/meshing-around` to identify TUI features and interoperability enhancements.

## Repository Comparison

| Aspect | MeshForge (This Repo) | meshing-around (Upstream) |
|--------|----------------------|---------------------------|
| **Purpose** | TUI/Web monitoring clients | Bot/autoresponder server |
| **Architecture** | Client-focused (view mesh data) | Server-focused (respond to commands) |
| **Connection** | Single interface manager | Multi-interface (up to 9 radios) |
| **Config Format** | INI (client-focused sections) | INI (bot-focused sections) |

---

## Key Differences Found

### 1. Multi-Interface Support (HIGH PRIORITY)

**Upstream:** Supports 9 concurrent interfaces (`interface1` through `interface9`)
```python
# From upstream modules/system.py
interface1 = interface2 = interface3 = ... = interface9 = None
for i in range(1, 10):
    interface_type = globals().get(f'interface{i}_type')
    # Initialize each interface
```

**MeshForge:** Single `ConnectionManager` handles one connection at a time.

**Recommendation:** Add multi-interface support to `connection_manager.py` to monitor multiple radios simultaneously in the TUI.

---

### 2. Bot Command Recognition (MEDIUM PRIORITY)

**Upstream:** Has extensive command recognition (`trap_list`):
```python
# ~70+ commands including:
- ping, ack, test, cq, cqcq
- whoami, whois, whereami
- wx, wxc, wxalert, solar, hfcond
- wiki, askai, joke
- bbslist, bbspost, bbsread
- games (blackjack, dopewar, battleship, etc.)
- sitrep, lheard, history
- emergency keywords (911, 112, etc.)
```

**MeshForge:** Only recognizes emergency keywords in `AlertConfig`:
```python
emergency_keywords: List[str] = ["emergency", "911", "112", ...]
```

**Recommendation:** Add command highlighting in TUI to show when bot commands are used. Consider adding a "Bot Commands" panel showing recent command activity.

---

### 3. Message Store & Forward (MEDIUM PRIORITY)

**Upstream:** Has `msg_history` and `messages` command:
```python
msg_history = []  # message history for store and forward
MAX_MSG_HISTORY = 250
```

**MeshForge:** Has `MeshNetwork.messages` with similar functionality but different limits.

**Recommendation:** Align message history limits and add config option to sync with meshing-around bot.

---

### 4. Emergency Handler Integration (HIGH PRIORITY)

**Upstream `emergencyHandler` section:**
```ini
[emergencyHandler]
enabled = False
alert_channel = 2
alert_interface = 1
```

**MeshForge:** Has similar structure but could benefit from:
- Adding `alert_interface` config for multi-radio setups
- Cross-channel emergency broadcasting like upstream

---

### 5. Sentry/Proximity Detection (MEDIUM PRIORITY)

**Upstream:**
```ini
[sentry]
SentryEnabled = True
SentryInterface = 1
SentryChannel = 2
SentryRadius = 100  # meters
```

**MeshForge:** Has `AlertType.PROXIMITY` but no radius-based detection.

**Recommendation:** Add sentry configuration section to config.py.

---

### 6. Config Compatibility (HIGH PRIORITY)

**Differences in section names:**
| Feature | Upstream Section | MeshForge Section |
|---------|-----------------|-------------------|
| Alerts | `[emergencyHandler]` | `[emergencyHandler]` (compatible) |
| Games | `[games]` | Not present |
| BBS | `[bbs]` | Not present |
| Sentry | `[sentry]` | Not present |
| SMTP | `[smtp]` | Not present |
| Scheduler | `[scheduler]` | Not present |

**Recommendation:** MeshForge config should be able to read upstream config files for seamless integration.

---

## TUI Enhancement Opportunities

### Immediate (Low Effort)

1. **Display bot command activity** - Highlight messages that trigger bot commands
2. **Show multi-node summary** - Display stats from multiple radios if connected
3. **Emergency keyword highlighting** - Already present, align keyword list with upstream

### Medium Term

4. **Bot status panel** - Show if bot commands are enabled/disabled
5. **Command history view** - Similar to upstream's `history` command
6. **Sentry alerts display** - Show proximity alerts in alerts panel

### Long Term

7. **Multi-interface TUI** - Support monitoring multiple radios in split view
8. **BBS integration** - Display BBS posts/messages in dedicated screen
9. **Game tracking display** - Show active games from connected bots

---

## Files Modified/Analyzed

### MeshForge (This Repo)
- `meshing_around_clients/tui/app.py` - Main TUI (863 lines)
- `meshing_around_clients/core/models.py` - Data models (340 lines)
- `meshing_around_clients/core/connection_manager.py` - Connection handling (398 lines)
- `meshing_around_clients/core/config.py` - Configuration (246 lines)

### Upstream (SpudGunMan/meshing-around)
- `mesh_bot.py` - Main bot (~300+ lines reviewed)
- `modules/system.py` - System initialization (~400 lines reviewed)
- `modules/settings.py` - Settings management (~200 lines reviewed)
- `modules/log.py` - Logging with CustomFormatter
- `modules/smtp.py` - Email notifications
- `config.template` - Full configuration template

---

## Action Items for Next Session

1. [ ] Add `interface2`...`interface9` support to `connection_manager.py`
2. [ ] Add sentry config section to `config.py`
3. [ ] Create bot command recognition utility
4. [ ] Add command highlighting to TUI message display
5. [ ] Align emergency keywords with upstream
6. [ ] Test reading upstream `config.ini` in MeshForge

---

## Git State

```
Current branch: claude/meshfroge-tui-integration-xWPOZ
Upstream remote: https://github.com/SpudGunMan/meshing-around.git
Upstream branch: upstream/main (fetched)
Recent upstream version: v1.9.9.5
```

---

## Session Entropy Check

**Status: LOW** - Analysis complete, context is clean.

Key context preserved:
- Upstream fetched to `upstream/main`
- Comparison matrix documented above
- Action items clearly defined
- No uncommitted changes

**Ready for new session:** Yes, all findings documented.

# Reliability Improvement Roadmap

**Version:** 0.5.0-beta
**Date:** 2026-02-21

This document tracks reliability improvements needed for MeshForge to reach stable release.

## Priority Levels

- **P0 - Critical**: Blocking issues, data loss potential
- **P1 - High**: Core functionality broken
- **P2 - Medium**: Feature incomplete or unreliable
- **P3 - Low**: Nice to have, polish

---

## Connection Layer (P1)

### Serial Mode
- [ ] Test with actual Meshtastic device on USB
- [ ] Handle device disconnect/reconnect gracefully
- [ ] Test on different hardware (T-Beam, T-Echo, Heltec)
- [ ] Verify baudrate detection works

### TCP Mode
- [ ] Test with meshtastic device in TCP mode
- [ ] Implement connection timeout handling
- [ ] Add reconnection with exponential backoff
- [ ] Test with `meshtasticd` remote connections

### MQTT Mode
- [ ] Test full message flow with mqtt.meshtastic.org
- [ ] Verify topic subscription/parsing
- [ ] Test reconnection after broker disconnect
- [ ] Handle broker authentication properly
- [ ] Test with custom MQTT brokers

### BLE Mode
- [ ] Test Bluetooth discovery on Linux
- [ ] Test on Raspberry Pi with BT adapter
- [ ] Handle pairing/connection lifecycle
- [ ] Test with multiple BLE devices

---

## Data Models (P2)

### Message Handling
- [ ] Verify message ID generation is unique
- [ ] Test message history limits work correctly
- [ ] Ensure thread safety under high message volume
- [ ] Test encrypted message handling

### Node Tracking
- [ ] Verify node online/offline detection accuracy
- [ ] Test node timeout thresholds
- [ ] Validate telemetry parsing from real devices
- [ ] Test with 50+ nodes in mesh

### Alert System
- [ ] Verify emergency keyword detection accuracy
- [ ] Test proximity zone calculations (haversine)
- [ ] Validate alert deduplication logic
- [ ] Test alert severity escalation

---

## TUI Client (P2)

### Display
- [ ] Test on various terminal sizes (80x24, 120x40, etc.)
- [ ] Verify color rendering on different terminals
- [ ] Test Rich fallback when library missing
- [ ] Handle Unicode/emoji in messages correctly

### Input
- [ ] Test keyboard handling on different systems
- [ ] Verify all keyboard shortcuts work
- [ ] Test message send flow end-to-end
- [ ] Handle paste of long text properly

### Performance
- [ ] Profile CPU usage during live updates
- [ ] Test memory usage over 24+ hour runs
- [ ] Verify no memory leaks in message history

---

## Web Client (P2)

### Templates
- [ ] Test all HTML templates render correctly
- [ ] Verify responsive design on mobile
- [ ] Test WebSocket reconnection in browser
- [ ] Validate CSRF protection

### API
- [ ] Test all REST endpoints
- [ ] Verify rate limiting works
- [ ] Test authentication flow
- [ ] Validate input sanitization

### WebSocket
- [ ] Test with multiple concurrent clients
- [ ] Verify message broadcast to all clients
- [ ] Test reconnection after server restart
- [ ] Handle malformed WebSocket messages

---

## Notifications (P3)

### Email/SMTP
- [ ] Test with Gmail SMTP
- [ ] Test with custom SMTP server
- [ ] Verify rate limiting prevents spam
- [ ] Test quiet hours functionality

### SMS
- [ ] Test email-to-SMS gateways (AT&T, Verizon)
- [ ] Test Twilio integration
- [ ] Test HTTP gateway option
- [ ] Verify phone number validation

---

## Configuration (P2)

### INI Parsing
- [ ] Test with malformed config files
- [x] Verify default values applied correctly (unified schema)
- [ ] Test config migration from older versions
- [x] Validate sensitive data handling (passwords) - config_schema.py

### Upstream Compatibility
- [x] Read meshing-around config.ini successfully - ConfigLoader._load_upstream()
- [x] Handle missing sections gracefully - defaults via dataclasses
- [x] Map equivalent config options - config_schema.py maps both formats

### Auto-Update System (NEW)
- [x] Design auto-update architecture (opt-in)
- [x] Support both MeshForge and upstream updates
- [x] Weekly/monthly schedule options
- [ ] Test update workflow on Pi Zero 2W

---

## Testing Infrastructure (P1)

### Unit Tests
- [x] Add tests for models.py (Node, Message, Alert) - 45+ tests
- [x] Add tests for config.py - 18+ tests
- [ ] Target 80% code coverage

### Integration Tests
- [ ] Test TUI screen rendering
- [ ] Test Web API endpoints
- [ ] Mock Meshtastic device for testing

### CI/CD
- [ ] Set up GitHub Actions workflow
- [ ] Run tests on PR
- [ ] Lint with flake8/black
- [ ] Type check with mypy

---

## Documentation (P3)

### User Docs
- [ ] Complete setup guide for each OS
- [ ] Troubleshooting guide
- [ ] FAQ document
- [ ] Video walkthrough

### Developer Docs
- [ ] API documentation
- [ ] Architecture decision records
- [ ] Contributing guide improvements
- [ ] Code style guide

---

## Upstream Integration (P2)

### Multi-Interface Support
- [ ] Add support for interface2...interface9
- [ ] Allow monitoring multiple radios in TUI
- [ ] Show combined view in dashboard

### Command Recognition
- [ ] Highlight bot commands in message view
- [ ] Show command response previews
- [ ] Parse upstream trap_list format

### Sentry Mode
- [ ] Add [sentry] config section
- [ ] Implement radius-based proximity detection
- [ ] Match upstream behavior

---

## Completion Criteria for v1.0.0

Before releasing v1.0.0-stable, the following must be complete:

1. **All P0 and P1 items resolved**
2. **At least 80% of P2 items resolved**
3. **Unit test coverage > 70%**
4. **Tested on real Meshtastic hardware**
5. **Documentation complete for all working features**
6. **No known data loss bugs**
7. **Graceful handling of all connection failures**

---

## Progress Tracking

| Category | P0 | P1 | P2 | P3 | Done |
|----------|----|----|----|----|------|
| Connection | 0 | 4 | 0 | 0 | 0% |
| Models | 0 | 0 | 4 | 0 | 0% |
| TUI | 0 | 0 | 3 | 0 | 0% |
| Web | 0 | 0 | 3 | 0 | 0% |
| Notifications | 0 | 0 | 0 | 2 | 0% |
| Config | 0 | 0 | 2 | 0 | **75%** |
| Testing | 0 | 2 | 0 | 0 | **40%** |
| Docs | 0 | 0 | 0 | 2 | 0% |
| Upstream | 0 | 0 | 3 | 0 | 0% |

**Total Items:** 24 (P0: 0, P1: 6, P2: 14, P3: 4)
**Unit Tests:** 147 passing, 44 skipped (MQTT integration, web/fastapi)

---

## Recent Changes (2026-02-04)

### New Modules Added
- `config_schema.py` - Unified configuration with dataclass validation
- `pi_utils.py` - Raspberry Pi detection, serial ports, PEP 668 handling
- `system_maintenance.py` - Auto-update system, git-based updates
- `cli_utils.py` - Terminal colors, formatted printing, menus

### Exception Handling Improvements
- Fixed 7 broad exceptions in `mqtt_client.py`
- Fixed 8 broad exceptions in `meshtastic_api.py`
- Fixed 6 broad exceptions in `configure_bot.py` (shutil, os.chdir, subprocess)
- All exceptions now use specific types (OSError, ValueError, etc.)

### configure_bot.py Decomposition
- Reduced from 2307 to ~2000 lines
- Extracted code to new modules with fallback support
- Removed duplicate functions that shadowed imports

### Upstream Integration
- Added git remote for SpudGunMan/meshing-around
- Config loader supports both upstream and MeshForge formats
- Multi-interface support (interface2...interface9)

---

*Last updated: 2026-02-21*

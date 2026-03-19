# Hardware Testing Guide

> **EXTENSION MODULE** - This is a MeshForge extension module. APIs and features may change without notice.

This document outlines requirements and procedures for testing MeshForge with Meshtastic hardware.

## Test Status

| Mode | Status | Blocker |
|------|--------|---------|
| Serial | **Untested** | Requires USB-connected device |
| TCP | **Working** | Tested with remote nodes via port 4403 |
| BLE | **Untested** | Requires Bluetooth-enabled device |
| MQTT | **Partial** | Works; integration tests skipped without network |
| Demo | **Working** | No hardware needed |

## Requirements

### Hardware
- Meshtastic-compatible device (T-Beam, T-Echo, RAK WisBlock, Heltec, etc.)
- USB cable (for Serial mode)
- Network connectivity (for TCP/MQTT modes)
- Bluetooth adapter (for BLE mode)

### Software
```bash
# Core dependencies
pip install meshtastic paho-mqtt rich

# For development
pip install pytest
```

### System Setup (Linux)
```bash
# Add user to dialout group for serial access
sudo usermod -a -G dialout $USER

# Logout and login for group change to take effect
# Or use: newgrp dialout
```

## Testing Procedures

Connection mode is set via `mesh_client.ini` (not CLI flags). Use `--setup`
to run the interactive wizard, or edit the config directly:

```ini
[interface]
type = serial    # serial, tcp, http, mqtt, ble, auto
port =           # e.g., /dev/ttyUSB0 (auto-detect if empty)
hostname =       # e.g., 192.168.1.100 (for tcp/http)
mac =            # e.g., AA:BB:CC:DD:EE:FF (for ble)
```

### Serial Mode Testing

**Prerequisites:**
- Meshtastic device connected via USB
- User in `dialout` group (Linux) or appropriate permissions

**Setup:**
```ini
[interface]
type = serial
port =           # leave empty for auto-detect, or set /dev/ttyUSB0
```

**Test Steps:**
```bash
# 1. Verify device detection
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null

# 2. Run client
python3 mesh_client.py --tui

# 3. Verify in TUI:
#    - Dashboard shows "connected (serial)"
#    - My Node shows device info
#    - Nodes screen populates with mesh nodes
#    - Messages can be sent/received
```

**Expected Results:**
- [ ] Device auto-detected or port selectable
- [ ] Connection status shows "connected (serial)"
- [ ] Node info (short name, long name, hardware) displayed
- [ ] Position/telemetry data received
- [ ] Messages send successfully (check for ACK)
- [ ] Alerts trigger on emergency keywords

### TCP Mode Testing

**Prerequisites:**
- Meshtastic device with WiFi enabled
- Device hostname/IP known
- Device configured to allow TCP connections (port 4403)

**Setup:**
```ini
[interface]
type = tcp
hostname = 192.168.1.100    # your device IP
```

**Test Steps:**
```bash
# 1. Verify TCP connectivity
nc -zv <device-ip> 4403

# 2. Run client
python3 mesh_client.py --tui

# 3. Same verification as Serial mode
```

**Expected Results:**
- [ ] TCP connection established
- [ ] All Serial mode functionality works over TCP
- [ ] Reconnection works after network interruption

### BLE Mode Testing

**Prerequisites:**
- Bluetooth adapter on host system
- Meshtastic device with BLE enabled
- Device MAC address known

**Setup:**
```ini
[interface]
type = ble
mac = AA:BB:CC:DD:EE:FF    # your device MAC
```

**Test Steps:**
```bash
# 1. Scan for BLE devices
python3 -c "from meshtastic.ble_interface import BLEInterface; BLEInterface.scan()"

# 2. Run client
python3 mesh_client.py --tui
```

**Expected Results:**
- [ ] BLE device discovered
- [ ] Connection established
- [ ] Basic functionality works (may be slower than Serial/TCP)

### MQTT Mode Testing

**Prerequisites:**
- Network connectivity to mqtt.meshtastic.org (or custom broker)
- paho-mqtt installed

**Setup:**
```ini
[interface]
type = mqtt

[mqtt]
enabled = true
broker = mqtt.meshtastic.org
topic_root = msh/US
channels = LongFast
```

Or use a regional profile:
```bash
python3 mesh_client.py --profile hawaii
```

**Test Steps:**
```bash
# 1. Test broker connectivity
python3 -c "import socket; socket.create_connection(('mqtt.meshtastic.org', 1883), 5); print('OK')"

# 2. Run client
python3 mesh_client.py --tui

# 3. Verify:
#    - Connection status shows "connected (MQTT)"
#    - Nodes appear from mesh traffic
#    - Messages visible on subscribed channels
```

**Expected Results:**
- [ ] MQTT broker connection successful
- [ ] Subscribed to appropriate topics
- [ ] Receiving mesh traffic
- [ ] Node info populated from MQTT messages
- [ ] Alerts work for emergency keywords
- [ ] Commands recognized (cmd, help, ping) without triggering alerts

## Test Matrix

### Connection Modes x Features

| Feature | Serial | TCP | BLE | MQTT |
|---------|--------|-----|-----|------|
| Node List | ? | ? | ? | ? |
| Position Data | ? | ? | ? | ? |
| Telemetry | ? | ? | ? | ? |
| Send Message | ? | ? | ? | ? |
| Receive Message | ? | ? | ? | ? |
| Emergency Alerts | ? | ? | ? | ? |
| Battery Alerts | ? | ? | ? | ? |
| Command Handler | ? | ? | ? | ? |

Legend: pass = Tested OK, fail = Failed, ? = Untested

### TUI Screens

| Screen | Serial | TCP | BLE | MQTT | Demo |
|--------|--------|-----|-----|------|------|
| Dashboard | ? | ? | ? | ? | pass |
| Nodes | ? | ? | ? | ? | pass |
| Messages | ? | ? | ? | ? | pass |
| Alerts | ? | ? | ? | ? | pass |
| Topology | ? | ? | ? | ? | pass |
| Devices | ? | ? | ? | ? | pass |
| Help | ? | ? | ? | ? | pass |

## Automated Tests

```bash
# All unit tests (no hardware needed)
python3 -m pytest tests/ -v

# Specific module
python3 -m pytest tests/test_models.py -v
python3 -m pytest tests/test_config.py -v

# MQTT integration tests (requires network)
python3 -m pytest tests/test_mqtt_client.py -v -k integration
```

> For troubleshooting connection issues (serial, TCP, BLE, MQTT), see the main [README.md](README.md).

## Reporting Test Results

When reporting hardware test results, include:

1. **Device Info**
   - Hardware model (T-Beam, RAK, etc.)
   - Firmware version
   - Region setting

2. **Host System**
   - OS and version
   - Python version
   - MeshForge version

3. **Test Results**
   - Which modes tested
   - Pass/fail for each feature
   - Screenshots if relevant
   - Error messages/logs

Submit results via GitHub issue: https://github.com/Nursedude/meshing_around_meshforge/issues

## Contributing Hardware Tests

To add automated hardware tests:

1. Create test file in `tests/` directory
2. Use `@unittest.skipUnless()` for hardware-dependent tests
3. Document hardware requirements in docstring
4. Submit PR with test results

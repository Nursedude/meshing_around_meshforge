# Hardware Testing Guide

> **EXTENSION MODULE** - This is a MeshForge extension module. APIs and features may change without notice.

This document outlines requirements and procedures for testing MeshForge with Meshtastic hardware.

## Test Status

| Mode | Status | Blocker |
|------|--------|---------|
| Serial | **Untested** | Requires USB-connected device |
| TCP | **Untested** | Requires network-accessible device |
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

### Serial Mode Testing

**Prerequisites:**
- Meshtastic device connected via USB
- User in `dialout` group (Linux) or appropriate permissions

**Test Steps:**
```bash
# 1. Verify device detection
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null

# 2. Run client in serial mode
python3 mesh_client.py --serial

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

**Test Steps:**
```bash
# 1. Verify TCP connectivity
nc -zv <device-ip> 4403

# 2. Run client in TCP mode
python3 mesh_client.py --tcp --host <device-ip>

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

**Test Steps:**
```bash
# 1. Scan for BLE devices
python3 -c "from meshtastic.ble_interface import BLEInterface; BLEInterface.scan()"

# 2. Run client in BLE mode
python3 mesh_client.py --ble --mac <device-mac>
```

**Expected Results:**
- [ ] BLE device discovered
- [ ] Connection established
- [ ] Basic functionality works (may be slower than Serial/TCP)

### MQTT Mode Testing

**Prerequisites:**
- Network connectivity to mqtt.meshtastic.org (or custom broker)
- paho-mqtt installed

**Test Steps:**
```bash
# 1. Test broker connectivity
python3 -c "import socket; socket.create_connection(('mqtt.meshtastic.org', 1883), 5); print('OK')"

# 2. Run client in MQTT mode
python3 mesh_client.py --mqtt

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

## Test Matrix

### Connection Modes × Features

| Feature | Serial | TCP | BLE | MQTT |
|---------|--------|-----|-----|------|
| Node List | ? | ? | ? | ? |
| Position Data | ? | ? | ? | ? |
| Telemetry | ? | ? | ? | ? |
| Send Message | ? | ? | ? | ? |
| Receive Message | ? | ? | ? | ? |
| Emergency Alerts | ? | ? | ? | ? |
| Battery Alerts | ? | ? | ? | ? |

Legend: ✓ = Tested OK, ✗ = Failed, ? = Untested

### TUI Screens

| Screen | Serial | TCP | BLE | MQTT | Demo |
|--------|--------|-----|-----|------|------|
| Dashboard | ? | ? | ? | ? | ✓ |
| Nodes | ? | ? | ? | ? | ✓ |
| Messages | ? | ? | ? | ? | ✓ |
| Alerts | ? | ? | ? | ? | ✓ |
| Map | ? | ? | ? | ? | ✓ |
| Settings | ? | ? | ? | ? | ✓ |

## Automated Tests

### Running Unit Tests
```bash
# All unit tests (no hardware needed)
python3 -m unittest discover tests/ -v

# Specific module
python3 -m unittest tests.test_models -v
python3 -m unittest tests.test_config -v
```

### Running Integration Tests
```bash
# MQTT integration (requires network)
python3 -m unittest tests.test_mqtt_client.TestMQTTIntegration -v

# With pytest (if installed)
pytest tests/ -v -k integration
```

## Troubleshooting

### Serial Issues
```bash
# Permission denied
sudo chmod 666 /dev/ttyUSB0  # Temporary fix
# Or add user to dialout group (permanent)

# Device not found
dmesg | tail -20  # Check kernel messages
lsusb  # List USB devices
```

### TCP Issues
```bash
# Connection refused
# Check device WiFi is enabled and connected
# Check port 4403 is open on device

# Timeout
ping <device-ip>  # Check basic connectivity
```

### BLE Issues
```bash
# No devices found
sudo hcitool lescan  # Check Bluetooth adapter works
# Ensure device BLE is enabled and not connected elsewhere
```

### MQTT Issues
```bash
# Connection failed
# Check network/firewall allows outbound 1883
# Try alternative broker port (8883 for TLS)
```

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

# Enhanced Alert Configuration for MeshForge

> Detailed reference for `configure_bot.py`. For a quick overview of all 12 alert types and the project as a whole, see [README.md](README.md).

This configuration system provides granular control over all alert types, along with an interactive configuration tool (`configure_bot.py`) to make setup easier.

## Features

### Enhanced Alert Types

1. **Emergency Alerts** - Configurable keywords, notifications, and response settings
2. **Proximity Alerts** - Location-based notifications when nodes enter specified areas
3. **Altitude Alerts** - Detect high-flying nodes
4. **Weather Alerts** - NOAA/weather service integration with severity filtering
5. **iPAWS/EAS Alerts** - FEMA emergency alert system integration
6. **Volcano Alerts** - USGS volcano monitoring
7. **Battery Alerts** - Low battery detection and notifications
8. **Noisy Node Detection** - Automatically detect and optionally mute spam nodes
9. **New Node Welcomes** - Greet new nodes joining the mesh
10. **SNR Alerts** - Signal-to-noise ratio monitoring
11. **Disconnect Alerts** - Notify when nodes go offline
12. **Custom Alerts** - Create your own keyword-based alerts

### Key Improvements

- **Cooldown Periods** - Prevent alert spam with configurable cooldown timers
- **Alert Prioritization** - Priority levels for different alert types
- **Quiet Hours** - Suppress alerts during specified time periods
- **Rate Limiting** - Global and per-alert-type rate limiting
- **Multi-Channel Support** - Route different alerts to different channels
- **Email/SMS Integration** - Send critical alerts via email or SMS
- **Script Execution** - Trigger custom scripts on alert events
- **Comprehensive Logging** - Separate log files for each alert type
- **Sound Notifications** - Play sounds for critical alerts

## Installation

### Method 1: Interactive Configuration Tool (Recommended)

1. Make the configuration script executable:
```bash
chmod +x configure_bot.py
```

2. Run the interactive configuration tool:
```bash
python3 configure_bot.py
```

3. Follow the prompts to configure your bot. The tool will:
   - Guide you through each configuration section
   - Provide sensible defaults
   - Validate your inputs
   - Save your configuration to `mesh_client.ini` (or the path you specify)

### Method 2: Manual Configuration

1. Copy the enhanced config template:
```bash
cp config.enhanced.ini config.ini
```

2. Edit `config.ini` with your preferred text editor:
```bash
nano config.ini
```

3. Configure each section according to your needs (see Configuration Reference below)

## Interactive Configuration Tool

The `configure_bot.py` script provides a user-friendly interface for configuring your bot.

### Features:
- **Menu-driven interface** - Easy navigation through configuration options
- **Input validation** - Ensures valid configuration values
- **Colored output** - Clear visual feedback
- **Default values** - Sensible defaults for quick setup
- **Load existing config** - Modify existing configurations
- **Section-by-section** - Configure only what you need

### Usage Example:

```bash
$ python3 configure_bot.py

==================================================================
     Interactive Configuration Tool for Meshing-Around Bot      
==================================================================

Config file path [config.ini]: 

Configuration Menu
------------------
1. Interface Settings (Serial/TCP/BLE)
2. General Settings (Bot name, admins)
3. Emergency Alerts
4. Proximity Alerts
...
```

## Configuration Reference

### Emergency Handler

```ini
[emergencyHandler]
enabled = True
emergency_keywords = emergency,911,112,999,police,fire,ambulance,rescue,help,sos,mayday
alert_channel = 2
alert_interface = 1
play_sound = False
send_email = False
send_sms = False
cooldown_period = 300  # 5 minutes between alerts
log_to_file = True
log_file = logs/emergency_alerts.log
```

**Parameters:**
- `enabled` - Enable/disable emergency detection
- `emergency_keywords` - Comma-separated list of trigger words
- `alert_channel` - Channel number to send alerts to
- `cooldown_period` - Minimum seconds between repeated alerts
- `play_sound` - Play audio alert
- `send_email` - Email notifications
- `send_sms` - SMS notifications
- `log_to_file` - Log all emergency events

### Proximity Alerts

```ini
[proximityAlert]
enabled = False
target_latitude = 0.0
target_longitude = 0.0
radius_meters = 100
check_interval = 60
alert_channel = 0
run_script = False
script_path = 
node_cooldown = 600  # 10 minutes per node
```

**Use Cases:**
- Campsite monitoring - alert when members return
- Geofencing - track nodes entering/leaving areas
- Asset tracking - monitor equipment locations
- Event coordination - notify when attendees arrive

**Parameters:**
- `target_latitude/longitude` - Center point for proximity detection
- `radius_meters` - Alert radius in meters
- `check_interval` - How often to check positions (seconds)
- `run_script` - Execute custom script on trigger
- `node_cooldown` - Prevent repeated alerts for same node

### Battery Alerts

```ini
[batteryAlert]
enabled = False
threshold_percent = 20
check_interval_minutes = 30
alert_channel = 0
monitor_nodes =   # Empty = all nodes
node_cooldown_minutes = 180  # 3 hours
```

**Parameters:**
- `threshold_percent` - Alert when battery drops below this level
- `monitor_nodes` - Specific node numbers to monitor (empty = all)
- `node_cooldown_minutes` - Time between alerts for same node

### Noisy Node Detection

```ini
[noisyNodeAlert]
enabled = False
message_threshold = 50
time_period_minutes = 10
auto_mute = False
mute_duration_minutes = 60
whitelist =   # Exempt nodes from detection
```

**Parameters:**
- `message_threshold` - Messages per time period to trigger alert
- `time_period_minutes` - Measurement window
- `auto_mute` - Automatically mute noisy nodes
- `mute_duration_minutes` - How long to mute
- `whitelist` - Node numbers to exclude from detection

### Weather Alerts

```ini
[weatherAlert]
enabled = False
location =   # latitude,longitude
severity_levels = Extreme,Severe
check_interval_minutes = 30
alert_channel = 2
include_details = True
```

**Parameters:**
- `location` - Geographic coordinates for alerts
- `severity_levels` - Which alert levels to forward (Extreme, Severe, Moderate, Minor)
- `check_interval_minutes` - How often to poll weather services

### Global Alert Settings

```ini
[alertGlobal]
global_enabled = True
quiet_hours =   # Format: HH:MM-HH:MM (e.g., 22:00-07:00)
max_alerts_per_hour = 20
emergency_priority = 4
weather_priority = 3
proximity_priority = 2
general_priority = 1
```

**Parameters:**
- `global_enabled` - Master on/off switch for all alerts
- `quiet_hours` - Time range when alerts are suppressed
- `max_alerts_per_hour` - Rate limit across all alert types
- Priority levels - Control alert routing and importance (1-4)

### Email/SMS Configuration

```ini
[smtp]
enableSMTP = False
SMTP_SERVER = smtp.gmail.com
SMTP_PORT = 587
SMTP_AUTH = True
SMTP_USERNAME = your_email@gmail.com
SMTP_PASSWORD = your_app_password
SMTP_FROM = your_email@gmail.com
sysopEmails = admin@example.com

[sms]
enabled = False
gateway = @txt.att.net  # or @vtext.com, @tmomail.net, etc.
phone_numbers = 5551234567,5559876543
```

**SMS Gateways:**
- AT&T: `@txt.att.net`
- T-Mobile: `@tmomail.net`
- Verizon: `@vtext.com`
- Sprint: `@messaging.sprintpcs.com`

## Advanced Features

### Alert Message Templates

Many alerts support message templates with placeholders:

```ini
alert_message = Node {node_name} is within {distance}m of target location
```

**Available placeholders:**
- `{node_name}` - Node's display name
- `{node_id}` - Node number
- `{distance}` - Distance in meters (proximity alerts)
- `{altitude}` - Altitude in meters
- `{battery}` - Battery percentage
- `{count}` - Message count (noisy node)
- `{duration}` - Time duration
- `{keyword}` - Triggered keyword

### Script Execution

Alerts can trigger custom scripts for automation:

```ini
run_script = True
script_path = /home/user/scripts/proximity_alert.sh
```

Your script will receive alert details as environment variables:
- `ALERT_TYPE` - Type of alert triggered
- `NODE_NAME` - Node that triggered the alert
- `NODE_ID` - Node number
- `ALERT_MESSAGE` - Full alert message

Example script:
```bash
#!/bin/bash
echo "[$(date)] Alert: $ALERT_TYPE from $NODE_NAME" >> /var/log/mesh_alerts.log

# Example: Turn on lights when someone arrives
if [ "$ALERT_TYPE" = "proximity" ]; then
    mosquitto_pub -t "home/lights/on" -m "1"
fi
```

### Log File Organization

Each alert type can have its own log file:

```
logs/
├── emergency_alerts.log
├── proximity_alerts.log
├── battery_alerts.log
├── weather_alerts.log
├── noisy_node_alerts.log
└── ...
```

Log format:
```
2026-02-21 14:30:45 - EMERGENCY - Node:Hiker-01 (1234567890) - Keyword:help - Message:"Need help at coordinates"
2026-02-21 15:15:22 - PROXIMITY - Node:Camper-02 (9876543210) - Distance:45m - Target:Base Camp
```

## Best Practices

### 1. Start Simple
Begin with just a few alert types enabled:
- Emergency alerts
- New node welcomes
- Battery monitoring

### 2. Tune Your Thresholds
- Monitor logs to see typical activity
- Adjust thresholds to reduce false positives
- Use cooldown periods to prevent spam

### 3. Use Priority Levels
Configure high-priority channels for critical alerts:
- Emergency alerts → Channel 2 (monitored)
- General alerts → Channel 0 (main)

### 4. Test Your Configuration
```bash
# Test emergency keywords
# Test proximity detection
# Verify email/SMS delivery
# Check log files are being created
```

### 5. Backup Your Configuration
```bash
cp config.ini config.ini.backup
```

## Troubleshooting

### Alerts Not Triggering

1. Check if alert type is enabled:
```ini
enabled = True
```

2. Verify global alerts are enabled:
```ini
[alertGlobal]
global_enabled = True
```

3. Check you're not in quiet hours:
```ini
quiet_hours =   # Leave empty or remove quiet period
```

4. Review cooldown periods - may need to wait between alerts

### Email Not Sending

1. For Gmail, use an App Password (not your regular password)
2. Enable "Less secure app access" or use OAuth
3. Check SMTP settings match your provider
4. Verify firewall allows SMTP traffic (port 587/465)

### High Alert Volume

1. Increase cooldown periods
2. Adjust detection thresholds
3. Enable rate limiting
4. Use quiet hours
5. Whitelist known-good nodes

## Examples

### Example 1: Emergency Response Setup

Perfect for SAR (Search and Rescue) or emergency comms:

```ini
[emergencyHandler]
enabled = True
emergency_keywords = emergency,sos,help,911,rescue,urgent,mayday,injured
alert_channel = 2  # Dedicated emergency channel
send_email = True
send_sms = True
play_sound = True
cooldown_period = 60  # Quick response
```

### Example 2: Campsite Monitoring

Alert when campers return to base:

```ini
[proximityAlert]
enabled = True
target_latitude = 45.1234
target_longitude = -123.5678
radius_meters = 50
alert_message = {node_name} has arrived at base camp
alert_channel = 0
check_interval = 30
run_script = True
script_path = /home/user/scripts/camper_return.sh
```

### Example 3: Fleet Battery Monitoring

Monitor a fleet of radio devices:

```ini
[batteryAlert]
enabled = True
threshold_percent = 25
check_interval_minutes = 15
alert_channel = 1
monitor_nodes = 1234567890,9876543210,1111222233
send_email = True
```

### Example 4: High Altitude Detection

For balloon or drone tracking:

```ini
[altitudeAlert]
enabled = True
min_altitude = 500
alert_message = High altitude node: {node_name} at {altitude}m
alert_channel = 3
check_interval = 60
```

## Migration from Original Config

If you have an existing `config.ini`, the interactive tool can load it:

```bash
python3 configure_bot.py
# Enter your existing config file path when prompted
```

The tool will preserve your existing settings and only prompt for new options.

## Support

For issues or questions:
- GitHub: https://github.com/Nursedude/meshing_around_meshforge/issues
- Check the main repository README
- Review logs in the `logs/` directory

## License

Same license as the main meshing-around project (GPL-3.0)

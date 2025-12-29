# Meshing-Around Enhanced Configuration Tool

Enhanced configuration system and interactive setup tool for the [meshing-around](https://github.com/SpudGunMan/meshing-around) Meshtastic bot project.

## Supported Platforms

- **Raspberry Pi OS Bookworm** (Debian 12)
- **Raspberry Pi OS Trixie** (Debian 13)
- **Ubuntu 22.04/24.04** (Jammy/Noble)
- **Standard Debian systems**

## 🚀 Quick Start

```bash
# Clone this repository
git clone https://github.com/nursedude/meshing_around_config.git
cd meshing_around_config

# Run the interactive configuration tool
python3 configure_bot.py
```

## 📋 What's Included

This repository provides enhanced alert configuration capabilities for the meshing-around bot:

- **Interactive Configuration Tool** (`configure_bot.py`) - User-friendly setup wizard
- **Enhanced Config Template** (`config.enhanced.ini`) - Comprehensive alert settings
- **Detailed Documentation** (`ALERT_CONFIG_README.md`) - Complete configuration guide

## ✨ Features

### Complete Installation & Management

- **Fresh Install** - Clone and set up meshing-around from GitHub
- **Automated venv Setup** - PEP 668 compliant virtual environment creation
- **Dependency Installation** - Handles package name fixes (pubsub→PyPubSub, etc.)
- **install.sh Integration** - Use meshing-around's native installer
- **launch.sh Support** - Start bot using venv-aware launch script
- **Systemd Service** - Create auto-start service for the bot
- **System Updates** - Integrated apt update/upgrade

### Raspberry Pi Specific Features

- **Auto-Detection** - Detects Pi model and OS version
- **Serial Port Setup** - Configure UART via raspi-config
- **I2C/SPI Configuration** - Enable interfaces for sensors
- **dialout Group** - Automatic permission setup
- **Bookworm/Trixie Support** - Handles PEP 668 environment

### 12 Configurable Alert Types

1. **Emergency Alerts** - Custom keywords, multi-channel notifications
2. **Proximity Alerts** - Geofencing and location-based triggers
3. **Altitude Alerts** - High-altitude node detection
4. **Weather Alerts** - NOAA/weather service integration
5. **iPAWS/EAS Alerts** - FEMA emergency alert system
6. **Volcano Alerts** - USGS volcano monitoring
7. **Battery Alerts** - Low battery detection
8. **Noisy Node Detection** - Spam prevention and auto-muting
9. **New Node Welcomes** - Automated greetings
10. **SNR Alerts** - Signal quality monitoring
11. **Disconnect Alerts** - Offline node detection
12. **Custom Alerts** - User-defined keyword triggers

### Advanced Capabilities

- ⏱️ **Cooldown Periods** - Prevent alert spam
- 📧 **Email/SMS Integration** - Multi-channel notifications
- 🔔 **Sound Alerts** - Audio notifications for critical events
- 📝 **Comprehensive Logging** - Separate logs per alert type
- 🎯 **Priority Levels** - Route alerts by importance
- 🌙 **Quiet Hours** - Suppress alerts during sleep hours
- 📊 **Rate Limiting** - Global and per-type limits
- 🔧 **Script Execution** - Trigger automation on alerts

## 💻 Installation

### Prerequisites

- Python 3.6+
- [meshing-around](https://github.com/SpudGunMan/meshing-around) bot installed

### Setup

1. **Download the configuration tool:**
   ```bash
   git clone https://github.com/nursedude/meshing_around_config.git
   cd meshing_around_config
   ```

2. **Make the script executable:**
   ```bash
   chmod +x configure_bot.py
   ```

3. **Run the interactive configurator:**
   ```bash
   python3 configure_bot.py
   ```

4. **Copy the generated config to your meshing-around directory:**
   ```bash
   cp config.ini /path/to/meshing-around/
   ```

## 📖 Usage

### Interactive Mode (Recommended)

```bash
python3 configure_bot.py
```

The tool will guide you through:
- Interface settings (Serial/TCP/BLE)
- Bot general settings
- Each alert type configuration
- Email/SMS notification setup
- Global alert preferences

### Manual Configuration

1. Copy the template:
   ```bash
   cp config.enhanced.ini config.ini
   ```

2. Edit with your preferred editor:
   ```bash
   nano config.ini
   ```

3. Configure each section according to your needs

## 📚 Documentation

See [ALERT_CONFIG_README.md](ALERT_CONFIG_README.md) for:
- Detailed configuration reference
- Parameter descriptions
- Use case examples
- Troubleshooting guide
- Best practices

## 🎯 Use Cases

### Emergency Response / SAR

```ini
[emergencyHandler]
enabled = True
emergency_keywords = emergency,sos,help,mayday,rescue
alert_channel = 2
send_email = True
send_sms = True
play_sound = True
```

### Campsite Monitoring

```ini
[proximityAlert]
enabled = True
target_latitude = 45.1234
target_longitude = -123.5678
radius_meters = 50
alert_message = {node_name} has arrived at base camp
```

### Fleet Battery Monitoring

```ini
[batteryAlert]
enabled = True
threshold_percent = 25
check_interval_minutes = 15
send_email = True
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the GPL-3.0 License - same as the main [meshing-around](https://github.com/SpudGunMan/meshing-around) project.

## 🙏 Acknowledgments

- [SpudGunMan](https://github.com/SpudGunMan) - Original meshing-around project
- The Meshtastic community
- All contributors to the meshing-around project

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/nursedude/meshing_around_config/issues)
- **Main Project**: [meshing-around](https://github.com/SpudGunMan/meshing-around)
- **Meshtastic**: [meshtastic.org](https://meshtastic.org)

## 🔗 Related Projects

- [meshing-around](https://github.com/SpudGunMan/meshing-around) - Main bot project
- [Meshtastic](https://github.com/meshtastic) - Mesh networking platform

---

**Note**: This is an enhancement tool for the meshing-around project. Make sure you have the main meshing-around bot installed first.

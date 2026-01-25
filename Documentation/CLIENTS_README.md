# Meshing-Around Clients

TUI (Terminal User Interface) and Web clients for the [meshing-around](https://github.com/SpudGunMan/meshing-around) Meshtastic bot system.

Built using the **MeshForge Foundation** principles:
- Modularity: Each component is independently configurable
- User-friendly: Interactive interfaces with sensible defaults
- Multi-platform: Works across different systems
- Robustness: Fallback mechanisms and error handling

## Features

### TUI Client
- Real-time mesh network monitoring
- Node status with battery, SNR, and position data
- Message history with channel filtering
- Alert system with severity levels
- Send messages directly from terminal
- Works over SSH for headless systems

### Web Client
- Modern responsive dashboard
- Real-time updates via WebSocket
- REST API for integration
- Node details and management
- Message composition and history
- Alert acknowledgment system

## Quick Start

### Installation

```bash
# Install dependencies
pip install -r meshing_around_clients/requirements.txt

# Or install individually
pip install rich fastapi uvicorn jinja2 meshtastic
```

### Running the TUI Client

```bash
# Demo mode (no hardware required)
python run_tui.py --demo

# Connect to serial device
python run_tui.py --serial /dev/ttyUSB0

# Connect to TCP device
python run_tui.py --tcp 192.168.1.100
```

#### TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Dashboard view |
| `2` | Nodes view |
| `3` | Messages view |
| `4` | Alerts view |
| `s` | Send message |
| `r` | Refresh data |
| `c` | Connect/Disconnect |
| `?` | Help |
| `q` | Quit / Back |

### Running the Web Client

```bash
# Demo mode
python run_web.py --demo

# Production mode
python run_web.py --host 0.0.0.0 --port 8080

# With auto-reload for development
python run_web.py --reload --demo
```

Then open `http://localhost:8080` in your browser.

## Architecture

```
meshing_around_clients/
├── __init__.py
├── requirements.txt
├── core/                      # Shared core functionality
│   ├── __init__.py
│   ├── config.py              # Configuration management
│   ├── models.py              # Data models (Node, Message, Alert, etc.)
│   ├── meshtastic_api.py      # Meshtastic device communication
│   └── message_handler.py     # Message processing and commands
├── tui/                       # Terminal UI client
│   ├── __init__.py
│   ├── app.py                 # Main TUI application
│   ├── screens/               # Screen components
│   └── widgets/               # Custom widgets
└── web/                       # Web client
    ├── __init__.py
    ├── app.py                 # FastAPI application
    ├── routes/                # API endpoints
    ├── static/
    │   ├── css/style.css      # Styles
    │   └── js/app.js          # Frontend JavaScript
    └── templates/             # Jinja2 HTML templates
        ├── base.html
        ├── index.html
        ├── nodes.html
        ├── messages.html
        └── alerts.html
```

## REST API

The web client provides a REST API for integration:

### Status
- `GET /api/status` - Connection and network status
- `GET /api/network` - Full network state

### Nodes
- `GET /api/nodes` - List all nodes
- `GET /api/nodes/{node_id}` - Get specific node

### Messages
- `GET /api/messages` - Get message history
- `GET /api/messages?channel=0` - Filter by channel
- `POST /api/messages/send` - Send a message

### Alerts
- `GET /api/alerts` - Get all alerts
- `GET /api/alerts?unread_only=true` - Get unread alerts
- `POST /api/alerts/acknowledge` - Acknowledge an alert

### Connection
- `POST /api/connect` - Connect to device
- `POST /api/disconnect` - Disconnect from device

### Configuration
- `GET /api/config` - Get current configuration

## WebSocket

Connect to `ws://host:port/ws` for real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:8080/ws');

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    // msg.type: 'init', 'message', 'alert', 'node_update', 'node_new'
    // msg.data: payload
};

// Send a message
ws.send(JSON.stringify({
    type: 'send_message',
    text: 'Hello mesh!',
    destination: '^all',
    channel: 0
}));
```

## Configuration

Configuration is stored in `~/.config/meshing-around-clients/config.ini`:

```ini
[interface]
type = serial
port = /dev/ttyUSB0
# hostname = 192.168.1.100  # For TCP
# mac = AA:BB:CC:DD:EE:FF    # For BLE

[general]
bot_name = MeshBot
bbs_admin_list = 12345,67890
favoriteNodeList = 11111,22222

[emergencyHandler]
enabled = True
emergency_keywords = emergency,911,sos,help
alert_channel = 2

[web]
host = 0.0.0.0
port = 8080

[tui]
refresh_rate = 1.0
show_timestamps = True
message_history = 500
```

## Data Models

### Node
- `node_id`: Unique node identifier
- `node_num`: Node number
- `short_name`, `long_name`: Display names
- `hardware_model`: Device hardware
- `role`: CLIENT, ROUTER, REPEATER, etc.
- `position`: Latitude, longitude, altitude
- `telemetry`: Battery, voltage, SNR, RSSI
- `last_heard`: Last activity timestamp

### Message
- `sender_id`, `sender_name`: Sender info
- `recipient_id`: Destination (empty for broadcast)
- `channel`: Channel number (0-7)
- `text`: Message content
- `timestamp`: When sent/received
- `snr`, `rssi`: Signal quality

### Alert
- `alert_type`: EMERGENCY, BATTERY, NEW_NODE, etc.
- `severity`: 1 (low) to 4 (critical)
- `title`, `message`: Alert content
- `acknowledged`: Acknowledgment status

## Demo Mode

Both clients support demo mode for testing without hardware:

```bash
python run_tui.py --demo
python run_web.py --demo
```

Demo mode generates:
- 5 simulated nodes with realistic data
- Random messages and alerts
- Proper battery and SNR values

## Integration with meshing-around

These clients are designed to work alongside the main meshing-around bot:

1. **Monitoring**: View real-time mesh activity
2. **Management**: Send messages and commands
3. **Alerts**: Monitor emergency and status alerts
4. **Configuration**: Use shared configuration files

## Contributing

Contributions are welcome! Please:
1. Follow the MeshForge Foundation principles
2. Maintain compatibility with existing APIs
3. Add tests for new features
4. Update documentation

## License

GPL-3.0 License - See LICENSE file for details.

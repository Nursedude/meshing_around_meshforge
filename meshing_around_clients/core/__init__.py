"""
Core module for Meshing-Around Clients.
Provides shared runtime functionality for TUI and Web clients.

Supports multiple connection types:
- Serial (direct USB connection to radio)
- TCP (remote Meshtastic device)
- HTTP (meshtasticd HTTP API)
- MQTT (no radio required)
- BLE (Bluetooth)
- Demo (simulated data)

Setup-only modules (cli_utils, pi_utils, system_maintenance,
alert_configurators, config_schema) have been moved to
meshing_around_clients.setup.
"""

from .config import Config
from .meshtastic_api import MeshtasticAPI, MockMeshtasticAPI
from .models import Alert, MeshNetwork, Message, Node, NodeTelemetry, Position

# MQTT is optional
try:
    from .mqtt_client import MQTTConfig, MQTTMeshtasticClient

    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    MQTTMeshtasticClient = None
    MQTTConfig = None

__all__ = [
    # Models
    "Node",
    "Message",
    "Alert",
    "MeshNetwork",
    "NodeTelemetry",
    "Position",
    # API
    "MeshtasticAPI",
    "MockMeshtasticAPI",
    "Config",
    # MQTT
    "MQTTMeshtasticClient",
    "MQTTConfig",
    "MQTT_AVAILABLE",
]

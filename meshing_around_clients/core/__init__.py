"""
Core module for Meshing-Around Clients.
Provides shared functionality for TUI and Web clients.

Supports multiple connection types:
- Serial (direct USB connection to radio)
- TCP (remote Meshtastic device)
- MQTT (no radio required)
- BLE (Bluetooth)
"""

from .models import Node, Message, Alert, MeshNetwork, NodeTelemetry
from .meshtastic_api import MeshtasticAPI, MockMeshtasticAPI
from .message_handler import MessageHandler
from .config import Config
from .connection_manager import ConnectionManager, ConnectionType

# MQTT is optional
try:
    from .mqtt_client import MQTTMeshtasticClient, MQTTConfig
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    MQTTMeshtasticClient = None
    MQTTConfig = None

__all__ = [
    'Node', 'Message', 'Alert', 'MeshNetwork', 'NodeTelemetry',
    'MeshtasticAPI', 'MockMeshtasticAPI', 'MessageHandler', 'Config',
    'ConnectionManager', 'ConnectionType',
    'MQTTMeshtasticClient', 'MQTTConfig', 'MQTT_AVAILABLE'
]

"""
Core module for Meshing-Around Clients.
Provides shared functionality for TUI and Web clients.

Supports multiple connection types:
- Serial (direct USB connection to radio)
- TCP (remote Meshtastic device)
- MQTT (no radio required)
- BLE (Bluetooth)

New in 0.6.0:
- Unified config schema (config_schema.py)
- Pi utilities (pi_utils.py)
- System maintenance/auto-update (system_maintenance.py)
- CLI utilities (cli_utils.py)
"""

from .models import Node, Message, Alert, MeshNetwork, NodeTelemetry, Position
from .meshtastic_api import MeshtasticAPI, MockMeshtasticAPI
from .message_handler import MessageHandler
from .config import Config
from .connection_manager import ConnectionManager, ConnectionType
from .alert_detector import AlertDetector, AlertDetectorConfig, ProximityZone
from .notifications import NotificationManager, NotificationConfig, EmailConfig, SMSConfig

# New unified configuration
from .config_schema import (
    UnifiedConfig, ConfigLoader, ConnectionType as SchemaConnectionType,
    InterfaceConfig, MQTTConfig as SchemaMQTTConfig, GeneralConfig,
    EmergencyAlertConfig, SentryConfig, AltitudeAlertConfig,
    AutoUpdateConfig, AlertPriority
)

# Pi and system utilities
from .pi_utils import (
    is_raspberry_pi, get_pi_model, get_os_info, is_bookworm_or_newer,
    check_pep668_environment, get_pi_info, get_serial_ports,
    check_user_groups, get_pip_command, get_pip_install_flags,
    PiInfo, SerialPortInfo
)

from .system_maintenance import (
    system_update, update_upstream, update_meshforge,
    check_for_updates, find_meshing_around, install_python_dependencies,
    create_systemd_service, manage_service, UpdateResult
)

from .cli_utils import (
    Colors, print_header, print_section, print_success, print_warning,
    print_error, print_info, print_step, get_input, get_yes_no, get_choice,
    validate_mac_address, validate_ip_address, validate_email, ProgressBar, Menu
)

# MQTT is optional
try:
    from .mqtt_client import MQTTMeshtasticClient, MQTTConfig
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    MQTTMeshtasticClient = None
    MQTTConfig = None

__all__ = [
    # Models
    'Node', 'Message', 'Alert', 'MeshNetwork', 'NodeTelemetry', 'Position',
    # API
    'MeshtasticAPI', 'MockMeshtasticAPI', 'MessageHandler', 'Config',
    # Connections
    'ConnectionManager', 'ConnectionType',
    # Alerts
    'AlertDetector', 'AlertDetectorConfig', 'ProximityZone',
    # Notifications
    'NotificationManager', 'NotificationConfig', 'EmailConfig', 'SMSConfig',
    # MQTT
    'MQTTMeshtasticClient', 'MQTTConfig', 'MQTT_AVAILABLE',
    # New: Unified Config
    'UnifiedConfig', 'ConfigLoader', 'SchemaConnectionType', 'InterfaceConfig',
    'SchemaMQTTConfig', 'GeneralConfig', 'EmergencyAlertConfig', 'SentryConfig',
    'AltitudeAlertConfig', 'AutoUpdateConfig', 'AlertPriority',
    # New: Pi Utils
    'is_raspberry_pi', 'get_pi_model', 'get_os_info', 'is_bookworm_or_newer',
    'check_pep668_environment', 'get_pi_info', 'get_serial_ports',
    'check_user_groups', 'get_pip_command', 'get_pip_install_flags',
    'PiInfo', 'SerialPortInfo',
    # New: System Maintenance
    'system_update', 'update_upstream', 'update_meshforge',
    'check_for_updates', 'find_meshing_around', 'install_python_dependencies',
    'create_systemd_service', 'manage_service', 'UpdateResult',
    # New: CLI Utils
    'Colors', 'print_header', 'print_section', 'print_success', 'print_warning',
    'print_error', 'print_info', 'print_step', 'get_input', 'get_yes_no', 'get_choice',
    'validate_mac_address', 'validate_ip_address', 'validate_email', 'ProgressBar', 'Menu'
]

"""
Setup-only modules for Meshing-Around Clients.
These are used by configure_bot.py and mesh_client.py --import-config,
NOT by the runtime TUI/Web applications.

Modules:
- cli_utils: Terminal colors, printing, user input helpers
- pi_utils: Raspberry Pi detection, serial ports, venv management
- system_maintenance: Updates, git operations, systemd services
- alert_configurators: Alert configuration wizards
- config_schema: Unified config schema for upstream format conversion
"""

from .alert_configurators import (
    ALERT_CONFIGURATORS,
    configure_altitude_alerts,
    configure_battery_alerts,
    configure_disconnect_alerts,
    configure_email_sms,
    configure_emergency_alerts,
    configure_general,
    configure_global_settings,
    configure_interface,
    configure_new_node_alerts,
    configure_noisy_node_alerts,
    configure_proximity_alerts,
    configure_weather_alerts,
    create_basic_config,
)
from .cli_utils import (
    Colors,
    Menu,
    ProgressBar,
    get_choice,
    get_input,
    get_yes_no,
    print_error,
    print_header,
    print_info,
    print_section,
    print_step,
    print_success,
    print_warning,
    validate_email,
    validate_ip_address,
    validate_mac_address,
)
from .config_schema import (
    AlertPriority,
    AltitudeAlertConfig,
    AutoUpdateConfig,
    ConfigLoader,
)
from .config_schema import ConnectionType as SchemaConnectionType
from .config_schema import (
    EmergencyAlertConfig,
    GeneralConfig,
    InterfaceConfig,
)
from .config_schema import MQTTConfig as SchemaMQTTConfig
from .config_schema import (
    SentryConfig,
    UnifiedConfig,
)
from .pi_utils import (
    PiInfo,
    SerialPortInfo,
    check_pep668_environment,
    check_user_groups,
    get_os_info,
    get_pi_info,
    get_pi_model,
    get_pip_command,
    get_pip_install_flags,
    get_serial_ports,
    is_bookworm_or_newer,
    is_raspberry_pi,
)
from .system_maintenance import (
    UpdateResult,
    check_for_updates,
    create_systemd_service,
    find_meshing_around,
    install_python_dependencies,
    manage_service,
    system_update,
    update_meshforge,
    update_upstream,
)

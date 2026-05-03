"""
Alert Configuration Wizards for MeshForge.

Provides interactive configurators for all alert types:
- Emergency alerts
- Proximity alerts
- Altitude alerts
- Weather alerts
- Battery alerts
- Noisy node detection
- New node welcomes
- Disconnect alerts
- Email/SMS notifications
- Global alert settings

Extracted from configure_bot.py for modularity.
"""

import configparser
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .cli_utils import (
    get_input,
    get_yes_no,
    print_section,
    print_success,
    print_warning,
    validate_coordinates,
    validate_email,
)


class Prompter:
    """Protocol for a prompt backend (CLI stdin or TUI Rich).

    Duck-typed — any object with these methods works. configure_bot.py uses
    the module-level cli_utils functions directly; the TUI can pass its own
    Rich-backed prompter into `use_prompter()` to drive the same
    configurator functions without stdin.
    """

    def get_input(
        self,
        prompt: str,
        default: str = "",
        input_type: type = str,
        password: bool = False,
        validator: "Callable[[Any], bool] | None" = None,
        error_message: str = "Invalid input",
    ) -> Any:
        raise NotImplementedError

    def get_yes_no(self, prompt: str, default: bool = False) -> bool:
        raise NotImplementedError

    def print_section(self, text: str) -> None:
        raise NotImplementedError

    def print_success(self, text: str) -> None:
        raise NotImplementedError

    def print_warning(self, text: str) -> None:
        raise NotImplementedError


@contextmanager
def use_prompter(prompter: Prompter) -> "Iterator[None]":
    """Temporarily swap the I/O helpers so a configurator runs against a custom Prompter.

    Used by the TUI to drive these wizards via Rich prompts instead of stdin.
    Single-threaded — do not nest or call from a worker thread. The
    configurator functions themselves are unchanged; this rebinds the
    module-level names they resolve at call time.
    """
    global get_input, get_yes_no, print_section, print_success, print_warning
    orig = (get_input, get_yes_no, print_section, print_success, print_warning)
    get_input = prompter.get_input
    get_yes_no = prompter.get_yes_no
    print_section = prompter.print_section
    print_success = prompter.print_success
    print_warning = prompter.print_warning
    try:
        yield
    finally:
        get_input, get_yes_no, print_section, print_success, print_warning = orig


def _in_range(lo: int, hi: int) -> Callable[[int], bool]:
    """Return a validator that checks lo <= value <= hi."""
    return lambda v: lo <= v <= hi


def _positive(v: int) -> bool:
    """Validate that value is positive."""
    return v > 0


# Meshtastic supports channel indices 0-7
_valid_channel = _in_range(0, 7)
_valid_percent = _in_range(1, 100)


def configure_interface(config: configparser.ConfigParser) -> None:
    """Configure interface settings (Serial/TCP/BLE)."""
    print_section("Interface Configuration")

    print("\nConnection types:")
    print("  1. Serial (recommended)")
    print("  2. TCP")
    print("  3. BLE")

    conn_type = get_input("Select connection type (1-3)", "1")
    type_map = {"1": "serial", "2": "tcp", "3": "ble"}
    conn_type_str = type_map.get(conn_type, "serial")

    if "interface" not in config:
        config.add_section("interface")

    config["interface"]["type"] = conn_type_str

    if conn_type_str == "serial":
        use_auto = get_yes_no("Use auto-detect for serial port?", True)
        if not use_auto:
            port = get_input("Enter serial port", "/dev/ttyUSB0")
            config["interface"]["port"] = port
    elif conn_type_str == "tcp":
        hostname = get_input("Enter TCP hostname/IP", "192.168.1.100")
        config["interface"]["hostname"] = hostname
    elif conn_type_str == "ble":
        mac = get_input("Enter BLE MAC address", "AA:BB:CC:DD:EE:FF")
        config["interface"]["mac"] = mac

    print_success(f"Interface configured: {conn_type_str}")


def configure_general(config: configparser.ConfigParser) -> None:
    """Configure general bot settings."""
    print_section("General Settings")

    if "general" not in config:
        config.add_section("general")

    bot_name = get_input("Bot name", "MeshBot")
    config["general"]["bot_name"] = bot_name

    if get_yes_no("Configure admin nodes?", False):
        admin_list = get_input("Admin node numbers (comma-separated)")
        config["general"]["bbs_admin_list"] = admin_list

    if get_yes_no("Configure favorite nodes?", False):
        fav_list = get_input("Favorite node numbers (comma-separated)")
        config["general"]["favoriteNodeList"] = fav_list

    print_success("General settings configured")


def configure_emergency_alerts(config: configparser.ConfigParser) -> None:
    """Configure emergency alert settings."""
    print_section("Emergency Alert Configuration")

    if "emergencyHandler" not in config:
        config.add_section("emergencyHandler")

    if not get_yes_no("Enable emergency keyword detection?", True):
        config["emergencyHandler"]["enabled"] = "False"
        return

    config["emergencyHandler"]["enabled"] = "True"

    print("\nDefault keywords: emergency, 911, 112, 999, police, fire, ambulance, rescue, help, sos, mayday")
    if get_yes_no("Use default emergency keywords?", True):
        config["emergencyHandler"][
            "emergency_keywords"
        ] = "emergency,911,112,999,police,fire,ambulance,rescue,help,sos,mayday"
    else:
        keywords = get_input("Enter emergency keywords (comma-separated)")
        config["emergencyHandler"]["emergency_keywords"] = keywords

    channel = get_input(
        "Alert channel number (0-7)", "2", int, validator=_valid_channel, error_message="Channel must be 0-7"
    )
    config["emergencyHandler"]["alert_channel"] = str(channel)

    cooldown = get_input(
        "Cooldown period between alerts (seconds)", "300", int, validator=_positive, error_message="Must be positive"
    )
    config["emergencyHandler"]["cooldown_period"] = str(cooldown)

    if get_yes_no("Enable email notifications for emergencies?", False):
        config["emergencyHandler"]["send_email"] = "True"

    if get_yes_no("Enable SMS notifications for emergencies?", False):
        config["emergencyHandler"]["send_sms"] = "True"

    if get_yes_no("Play sound for emergency alerts?", False):
        config["emergencyHandler"]["play_sound"] = "True"
        sound_file = get_input("Sound file path", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga")
        config["emergencyHandler"]["sound_file"] = sound_file

    print_success("Emergency alerts configured")


def configure_proximity_alerts(config: configparser.ConfigParser) -> None:
    """Configure proximity-based alerts."""
    print_section("Proximity Alert Configuration")

    print("\nProximity alerts notify when nodes enter a specified area")
    print("Useful for campsite monitoring, geofencing, etc.")

    if "proximityAlert" not in config:
        config.add_section("proximityAlert")

    if not get_yes_no("Enable proximity alerts?", False):
        config["proximityAlert"]["enabled"] = "False"
        return

    config["proximityAlert"]["enabled"] = "True"

    lat = get_input("Target latitude", "0.0", float)
    config["proximityAlert"]["target_latitude"] = str(lat)

    lon = get_input("Target longitude", "0.0", float)
    config["proximityAlert"]["target_longitude"] = str(lon)

    if not validate_coordinates(lat, lon):
        print_warning("Coordinates may be invalid - verify values")

    radius = get_input(
        "Proximity radius in meters", "100", int, validator=_positive, error_message="Radius must be positive"
    )
    config["proximityAlert"]["radius_meters"] = str(radius)

    channel = get_input("Alert channel (0-7)", "0", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["proximityAlert"]["alert_channel"] = str(channel)

    interval = get_input("Check interval in seconds", "60", int, validator=_positive, error_message="Must be positive")
    config["proximityAlert"]["check_interval"] = str(interval)

    if get_yes_no("Execute script on proximity trigger?", False):
        config["proximityAlert"]["run_script"] = "True"
        script_path = get_input("Script path")
        config["proximityAlert"]["script_path"] = script_path

    print_success("Proximity alerts configured")


def configure_altitude_alerts(config: configparser.ConfigParser) -> None:
    """Configure high altitude alerts."""
    print_section("Altitude Alert Configuration")

    if "altitudeAlert" not in config:
        config.add_section("altitudeAlert")

    if not get_yes_no("Enable high altitude detection?", False):
        config["altitudeAlert"]["enabled"] = "False"
        return

    config["altitudeAlert"]["enabled"] = "True"

    altitude = get_input(
        "Minimum altitude threshold (meters)", "1000", int, validator=_positive, error_message="Must be positive"
    )
    config["altitudeAlert"]["min_altitude"] = str(altitude)

    channel = get_input("Alert channel (0-7)", "0", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["altitudeAlert"]["alert_channel"] = str(channel)

    interval = get_input("Check interval (seconds)", "120", int, validator=_positive, error_message="Must be positive")
    config["altitudeAlert"]["check_interval"] = str(interval)

    print_success("Altitude alerts configured")


def configure_weather_alerts(config: configparser.ConfigParser) -> None:
    """Configure weather/NOAA alerts."""
    print_section("Weather Alert Configuration")

    if "weatherAlert" not in config:
        config.add_section("weatherAlert")

    if not get_yes_no("Enable weather/NOAA alerts?", False):
        config["weatherAlert"]["enabled"] = "False"
        return

    config["weatherAlert"]["enabled"] = "True"

    location = get_input("Location (latitude,longitude)")
    config["weatherAlert"]["location"] = location

    print("\nSeverity levels: Extreme, Severe, Moderate, Minor")
    severity = get_input("Alert severity levels (comma-separated)", "Extreme,Severe")
    config["weatherAlert"]["severity_levels"] = severity

    interval = get_input("Check interval (minutes)", "30", int, validator=_positive, error_message="Must be positive")
    config["weatherAlert"]["check_interval_minutes"] = str(interval)

    channel = get_input("Alert channel (0-7)", "2", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["weatherAlert"]["alert_channel"] = str(channel)

    print_success("Weather alerts configured")


def configure_battery_alerts(config: configparser.ConfigParser) -> None:
    """Configure low battery alerts."""
    print_section("Battery Alert Configuration")

    if "batteryAlert" not in config:
        config.add_section("batteryAlert")

    if not get_yes_no("Enable low battery monitoring?", False):
        config["batteryAlert"]["enabled"] = "False"
        return

    config["batteryAlert"]["enabled"] = "True"

    threshold = get_input(
        "Battery threshold percentage (1-100)", "20", int, validator=_valid_percent, error_message="Must be 1-100"
    )
    config["batteryAlert"]["threshold_percent"] = str(threshold)

    interval = get_input("Check interval (minutes)", "30", int, validator=_positive, error_message="Must be positive")
    config["batteryAlert"]["check_interval_minutes"] = str(interval)

    channel = get_input("Alert channel (0-7)", "0", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["batteryAlert"]["alert_channel"] = str(channel)

    if get_yes_no("Monitor specific nodes only?", False):
        nodes = get_input("Node numbers to monitor (comma-separated)")
        config["batteryAlert"]["monitor_nodes"] = nodes

    print_success("Battery alerts configured")


def configure_noisy_node_alerts(config: configparser.ConfigParser) -> None:
    """Configure noisy node detection."""
    print_section("Noisy Node Alert Configuration")

    if "noisyNodeAlert" not in config:
        config.add_section("noisyNodeAlert")

    if not get_yes_no("Enable noisy node detection?", False):
        config["noisyNodeAlert"]["enabled"] = "False"
        return

    config["noisyNodeAlert"]["enabled"] = "True"

    threshold = get_input(
        "Message threshold (messages per period)", "50", int, validator=_positive, error_message="Must be positive"
    )
    config["noisyNodeAlert"]["message_threshold"] = str(threshold)

    period = get_input("Time period (minutes)", "10", int, validator=_positive, error_message="Must be positive")
    config["noisyNodeAlert"]["time_period_minutes"] = str(period)

    if get_yes_no("Auto-mute noisy nodes?", False):
        config["noisyNodeAlert"]["auto_mute"] = "True"
        duration = get_input(
            "Mute duration (minutes)", "60", int, validator=_positive, error_message="Must be positive"
        )
        config["noisyNodeAlert"]["mute_duration_minutes"] = str(duration)

    print_success("Noisy node alerts configured")


def configure_new_node_alerts(config: configparser.ConfigParser) -> None:
    """Configure new node welcome messages."""
    print_section("New Node Alert Configuration")

    if "newNodeAlert" not in config:
        config.add_section("newNodeAlert")

    if not get_yes_no("Enable new node welcomes?", True):
        config["newNodeAlert"]["enabled"] = "False"
        return

    config["newNodeAlert"]["enabled"] = "True"

    message = get_input("Welcome message (use {node_name} placeholder)", "Welcome to the mesh, {node_name}!")
    config["newNodeAlert"]["welcome_message"] = message

    send_dm = get_yes_no("Send welcome as DM?", True)
    config["newNodeAlert"]["send_as_dm"] = str(send_dm)

    if get_yes_no("Also announce to channel?", False):
        config["newNodeAlert"]["announce_to_channel"] = "True"
        channel = get_input(
            "Announcement channel (0-7)", "0", int, validator=_valid_channel, error_message="Channel must be 0-7"
        )
        config["newNodeAlert"]["announcement_channel"] = str(channel)

    print_success("New node alerts configured")


def configure_disconnect_alerts(config: configparser.ConfigParser) -> None:
    """Configure node disconnect alerts."""
    print_section("Disconnect Alert Configuration")

    if "disconnectAlert" not in config:
        config.add_section("disconnectAlert")

    if not get_yes_no("Enable disconnect monitoring?", False):
        config["disconnectAlert"]["enabled"] = "False"
        return

    config["disconnectAlert"]["enabled"] = "True"

    timeout = get_input(
        "Consider disconnected after (minutes)", "30", int, validator=_positive, error_message="Must be positive"
    )
    config["disconnectAlert"]["timeout_minutes"] = str(timeout)

    if get_yes_no("Monitor specific nodes only?", False):
        nodes = get_input("Node numbers to monitor (comma-separated)")
        config["disconnectAlert"]["monitor_nodes"] = nodes
    else:
        config["disconnectAlert"]["monitor_all"] = "True"

    channel = get_input("Alert channel (0-7)", "0", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["disconnectAlert"]["alert_channel"] = str(channel)

    print_success("Disconnect alerts configured")


def configure_email_sms(config: configparser.ConfigParser) -> None:
    """Configure email and SMS settings."""
    print_section("Email/SMS Configuration")

    if "smtp" not in config:
        config.add_section("smtp")
    if "sms" not in config:
        config.add_section("sms")

    if not get_yes_no("Configure email settings?", False):
        return

    config["smtp"]["enableSMTP"] = "True"

    server = get_input("SMTP server", "smtp.gmail.com")
    config["smtp"]["SMTP_SERVER"] = server

    port = get_input("SMTP port", "587", int)
    config["smtp"]["SMTP_PORT"] = str(port)

    username = get_input("SMTP username/email")
    config["smtp"]["SMTP_USERNAME"] = username

    password = get_input("SMTP password", password=True)
    config["smtp"]["SMTP_PASSWORD"] = password

    from_addr = get_input("From email address", username)
    config["smtp"]["SMTP_FROM"] = from_addr

    if not validate_email(from_addr):
        print_warning("Email address format may be invalid")

    sysop_emails = get_input("Sysop email addresses (comma-separated)")
    config["smtp"]["sysopEmails"] = sysop_emails

    if get_yes_no("Configure SMS settings?", False):
        config["sms"]["enabled"] = "True"
        gateway = get_input("SMS gateway (e.g., @txt.att.net)")
        config["sms"]["gateway"] = gateway
        phones = get_input("Phone numbers (comma-separated)")
        config["sms"]["phone_numbers"] = phones

    print_success("Email/SMS settings configured")


def configure_global_settings(config: configparser.ConfigParser) -> None:
    """Configure global alert settings."""
    print_section("Global Alert Settings")

    if "alertGlobal" not in config:
        config.add_section("alertGlobal")

    if get_yes_no("Enable all alerts globally?", True):
        config["alertGlobal"]["global_enabled"] = "True"
    else:
        config["alertGlobal"]["global_enabled"] = "False"
        return

    if get_yes_no("Configure quiet hours?", False):
        quiet = get_input("Quiet hours (24hr format HH:MM-HH:MM, e.g., 22:00-07:00)")
        config["alertGlobal"]["quiet_hours"] = quiet

    max_rate = get_input("Maximum alerts per hour (all types)", "20", int)
    config["alertGlobal"]["max_alerts_per_hour"] = str(max_rate)

    print_success("Global settings configured")


def configure_ipaws_alerts(config: configparser.ConfigParser) -> None:
    """Configure IPAWS (Integrated Public Alert & Warning System) alerts."""
    print_section("IPAWS Alert Configuration")

    if "ipawsAlert" not in config:
        config.add_section("ipawsAlert")

    if not get_yes_no("Enable IPAWS alerts?", False):
        config["ipawsAlert"]["enabled"] = "False"
        return

    config["ipawsAlert"]["enabled"] = "True"

    state = get_input("2-letter state code (e.g., HI, CA, TX)", "US")
    config["ipawsAlert"]["state"] = state.upper()

    if get_yes_no("Filter to specific county FIPS codes?", False):
        fips = get_input("FIPS codes (comma-separated)")
        config["ipawsAlert"]["fips_codes"] = fips

    channel = get_input("Alert channel (0-7)", "2", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["ipawsAlert"]["alert_channel"] = str(channel)

    cooldown = get_input("Repeat cooldown (seconds)", "300", int, validator=_positive, error_message="Must be positive")
    config["ipawsAlert"]["cooldown_seconds"] = str(cooldown)

    print_success("IPAWS alerts configured")


def configure_volcano_alerts(config: configparser.ConfigParser) -> None:
    """Configure USGS volcano alerts."""
    print_section("Volcano Alert Configuration")

    if "volcanoAlert" not in config:
        config.add_section("volcanoAlert")

    if not get_yes_no("Enable volcano alerts?", False):
        config["volcanoAlert"]["enabled"] = "False"
        return

    config["volcanoAlert"]["enabled"] = "True"

    lat = get_input("Latitude for proximity filtering", "0.0", float)
    lon = get_input("Longitude for proximity filtering", "0.0", float)
    if not validate_coordinates(lat, lon):
        print_warning("Coordinates look unusual — double-check lat/lon values")
    config["volcanoAlert"]["latitude"] = str(lat)
    config["volcanoAlert"]["longitude"] = str(lon)

    radius = get_input("Alert radius (km)", "500", int, validator=_positive, error_message="Must be positive")
    config["volcanoAlert"]["radius_km"] = str(radius)

    channel = get_input("Alert channel (0-7)", "2", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["volcanoAlert"]["alert_channel"] = str(channel)

    print_success("Volcano alerts configured")


def configure_snr_alerts(config: configparser.ConfigParser) -> None:
    """Configure SNR (signal-to-noise) threshold alerts."""
    print_section("SNR Alert Configuration")

    if "snrAlert" not in config:
        config.add_section("snrAlert")

    if not get_yes_no("Enable SNR alerts?", False):
        config["snrAlert"]["enabled"] = "False"
        return

    config["snrAlert"]["enabled"] = "True"

    threshold = get_input("SNR threshold (dB) — alert when node falls below", "-5", int)
    config["snrAlert"]["threshold_db"] = str(threshold)

    if get_yes_no("Monitor all nodes? (No = specific nodes)", True):
        config["snrAlert"]["monitor_all"] = "True"
    else:
        nodes = get_input("Node numbers to monitor (comma-separated)")
        config["snrAlert"]["monitor_nodes"] = nodes

    channel = get_input("Alert channel (0-7)", "0", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["snrAlert"]["alert_channel"] = str(channel)

    cooldown = get_input("Repeat cooldown (seconds)", "600", int, validator=_positive, error_message="Must be positive")
    config["snrAlert"]["cooldown_seconds"] = str(cooldown)

    print_success("SNR alerts configured")


def configure_custom_alerts(config: configparser.ConfigParser) -> None:
    """Configure custom pattern-matching alerts."""
    print_section("Custom Alert Configuration")

    if "customAlert" not in config:
        config.add_section("customAlert")

    if not get_yes_no("Enable custom alerts?", False):
        config["customAlert"]["enabled"] = "False"
        return

    config["customAlert"]["enabled"] = "True"

    name = get_input("Rule name (e.g., 'low_battery_fleet')", "custom_rule")
    config["customAlert"]["rule_name"] = name

    pattern = get_input("Match pattern (regex or plain text)")
    config["customAlert"]["pattern"] = pattern

    if get_yes_no("Treat pattern as regex?", False):
        config["customAlert"]["pattern_is_regex"] = "True"

    channel = get_input("Alert channel (0-7)", "0", int, validator=_valid_channel, error_message="Channel must be 0-7")
    config["customAlert"]["alert_channel"] = str(channel)

    severity = get_input("Severity (1-5, 5=critical)", "3", int, validator=_in_range(1, 5), error_message="Must be 1-5")
    config["customAlert"]["severity"] = str(severity)

    print_success("Custom alerts configured")


def create_basic_config() -> configparser.ConfigParser:
    """Create a basic configuration interactively."""
    print_section("Basic Configuration")

    config = configparser.ConfigParser()

    # Initialize all sections
    sections = [
        "interface",
        "general",
        "emergencyHandler",
        "proximityAlert",
        "altitudeAlert",
        "weatherAlert",
        "ipawsAlert",
        "volcanoAlert",
        "noisyNodeAlert",
        "batteryAlert",
        "newNodeAlert",
        "snrAlert",
        "disconnectAlert",
        "customAlert",
        "alertGlobal",
        "smtp",
        "sms",
    ]
    for section in sections:
        config.add_section(section)

    # Basic interface config
    configure_interface(config)

    # Basic general config
    configure_general(config)

    # Enable emergency alerts by default
    config["emergencyHandler"]["enabled"] = "True"
    config["emergencyHandler"]["emergency_keywords"] = "emergency,911,112,999,sos,help,mayday"
    config["emergencyHandler"]["alert_channel"] = "2"
    print_success("Emergency alerts enabled with default keywords")

    # Enable new node welcomes
    config["newNodeAlert"]["enabled"] = "True"
    config["newNodeAlert"]["welcome_message"] = "Welcome to the mesh!"
    print_success("New node welcomes enabled")

    # Global settings
    config["alertGlobal"]["global_enabled"] = "True"

    return config


# Mapping of alert types to configurator functions
ALERT_CONFIGURATORS = {
    "interface": configure_interface,
    "general": configure_general,
    "emergency": configure_emergency_alerts,
    "proximity": configure_proximity_alerts,
    "altitude": configure_altitude_alerts,
    "weather": configure_weather_alerts,
    "ipaws": configure_ipaws_alerts,
    "volcano": configure_volcano_alerts,
    "battery": configure_battery_alerts,
    "noisy_node": configure_noisy_node_alerts,
    "new_node": configure_new_node_alerts,
    "snr": configure_snr_alerts,
    "disconnect": configure_disconnect_alerts,
    "custom": configure_custom_alerts,
    "email_sms": configure_email_sms,
    "global": configure_global_settings,
}


def run_all_configurators(config: configparser.ConfigParser) -> None:
    """Run all configurators in sequence."""
    configure_interface(config)
    configure_general(config)
    configure_emergency_alerts(config)
    configure_proximity_alerts(config)
    configure_altitude_alerts(config)
    configure_weather_alerts(config)
    configure_ipaws_alerts(config)
    configure_volcano_alerts(config)
    configure_battery_alerts(config)
    configure_noisy_node_alerts(config)
    configure_new_node_alerts(config)
    configure_snr_alerts(config)
    configure_disconnect_alerts(config)
    configure_custom_alerts(config)
    configure_email_sms(config)
    configure_global_settings(config)

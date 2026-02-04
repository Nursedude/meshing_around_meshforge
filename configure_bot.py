#!/usr/bin/env python3
"""
Meshing-Around Enhanced Configuration Tool
Interactive setup for the meshing-around Meshtastic bot

Supports:
- Raspberry Pi OS Bookworm (Debian 12)
- Raspberry Pi OS Trixie (Debian 13)
- Standard Debian/Ubuntu systems

Features:
- Automatic system updates at startup
- Virtual environment setup for PEP 668 compliance
- Serial port detection and configuration
- raspi-config integration for Raspberry Pi

Now uses modular components from meshing_around_clients.core:
- cli_utils: Terminal colors, printing, user input
- pi_utils: Pi detection, serial ports, venv management
- system_maintenance: Updates, git operations, systemd services
- alert_configurators: Alert configuration wizards
"""

import os
import sys
import subprocess
import shutil
import time
import configparser
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

# Version info
VERSION = "0.5.0-beta"
SUPPORTED_OS = ["bookworm", "trixie", "forky", "sid", "noble", "jammy"]

# Try to import modular components - fallback to inline if not available
try:
    from meshing_around_clients.core.cli_utils import (
        Colors, print_header, print_section, print_success, print_warning,
        print_error, print_info, print_step, get_input, get_yes_no,
        validate_mac_address, validate_coordinates
    )
    from meshing_around_clients.core.pi_utils import (
        is_raspberry_pi, get_pi_model, get_os_info, is_bookworm_or_newer,
        check_pep668_environment, get_serial_ports, get_serial_port_list,
        check_user_groups, add_user_to_dialout, get_default_venv_path,
        check_venv_exists, create_venv, get_pip_command, get_pip_install_flags,
        get_python_command, get_pi_config_path, check_serial_enabled,
        configure_serial_via_raspi_config, get_pi_info, is_pi_zero_2w,
        get_recommended_connection_mode
    )
    from meshing_around_clients.core.system_maintenance import (
        run_command, system_update as do_system_update, find_meshing_around,
        git_pull, update_upstream, update_meshforge, check_for_updates,
        install_python_dependencies, create_systemd_service as create_service,
        manage_service, check_service_status, clone_meshing_around,
        install_package, check_required_packages
    )
    from meshing_around_clients.core.alert_configurators import (
        configure_interface, configure_general, configure_emergency_alerts,
        configure_proximity_alerts, configure_altitude_alerts,
        configure_weather_alerts, configure_battery_alerts,
        configure_noisy_node_alerts, configure_new_node_alerts,
        configure_disconnect_alerts, configure_email_sms,
        configure_global_settings, create_basic_config, ALERT_CONFIGURATORS
    )
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False
    # Fallback: define inline versions (legacy support)
    from getpass import getpass

    class Colors:
        """ANSI color codes for terminal output"""
        HEADER = '\033[95m'
        OKBLUE = '\033[94m'
        OKCYAN = '\033[96m'
        OKGREEN = '\033[92m'
        WARNING = '\033[93m'
        FAIL = '\033[91m'
        ENDC = '\033[0m'
        BOLD = '\033[1m'
        UNDERLINE = '\033[4m'

    def print_header(text: str):
        """Print a formatted header"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{text:^70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}\n")

    def print_section(text: str):
        """Print a section header"""
        print(f"\n{Colors.OKCYAN}{Colors.BOLD}{text}{Colors.ENDC}")
        print(f"{Colors.OKCYAN}{'-'*len(text)}{Colors.ENDC}")

    def print_success(text: str):
        """Print success message"""
        print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")

    def print_warning(text: str):
        """Print warning message"""
        print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")

    def print_error(text: str):
        """Print error message"""
        print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")

    def print_info(text: str):
        """Print info message"""
        print(f"{Colors.OKBLUE}ℹ {text}{Colors.ENDC}")

    def print_step(current: int, total: int, text: str):
        """Print step progress"""
        print(f"{Colors.OKCYAN}[{current}/{total}] {text}{Colors.ENDC}")

def run_command(cmd: List[str], desc: str = "", capture: bool = False, sudo: bool = False) -> Tuple[int, str, str]:
    """Run a shell command with optional sudo and output"""
    if sudo:
        cmd = ['sudo'] + cmd

    if desc:
        print_info(f"{desc}...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=600  # 10 minute timeout
        )
        stdout = result.stdout if capture else ""
        stderr = result.stderr if capture else ""
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        print_error(f"Command timed out: {' '.join(cmd)}")
        return -1, "", "Timeout"
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        return -1, "", "Command not found"
    except OSError as e:
        print_error(f"Command failed: {e}")
        return -1, "", str(e)

def find_meshing_around() -> Optional[Path]:
    """Find the meshing-around installation directory"""
    common_paths = [
        Path.home() / "meshing-around",
        Path.home() / "mesh-bot",
        Path("/opt/meshing-around"),
        Path("/opt/mesh-bot"),
        Path.cwd().parent / "meshing-around",
        Path.cwd() / "meshing-around",
    ]

    for path in common_paths:
        if path.exists() and (path / "mesh_bot.py").exists():
            return path

    # Try to find it with locate or find
    try:
        result = subprocess.run(
            ['find', str(Path.home()), '-name', 'mesh_bot.py', '-type', 'f'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            bot_path = Path(result.stdout.strip().split('\n')[0]).parent
            return bot_path
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    return None

def validate_mac_address(mac: str) -> bool:
    """Validate BLE MAC address format"""
    pattern = r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$'
    return bool(re.match(pattern, mac))

def validate_coordinates(lat: float, lon: float) -> bool:
    """Validate latitude and longitude values"""
    return -90 <= lat <= 90 and -180 <= lon <= 180

def validate_port(port: str) -> bool:
    """Validate serial port exists"""
    return os.path.exists(port) or port.startswith('/dev/')


# ============================================================================
# RASPBERRY PI COMPATIBILITY FUNCTIONS
# ============================================================================

def is_raspberry_pi() -> bool:
    """Detect if running on a Raspberry Pi"""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo:
                return True
    except (FileNotFoundError, PermissionError, IOError):
        pass

    # Check for Pi-specific files
    if os.path.exists('/sys/firmware/devicetree/base/model'):
        try:
            with open('/sys/firmware/devicetree/base/model', 'r') as f:
                if 'Raspberry Pi' in f.read():
                    return True
        except (FileNotFoundError, PermissionError, IOError):
            pass

    return False


def get_pi_model() -> str:
    """Get Raspberry Pi model information"""
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as f:
            return f.read().strip().rstrip('\x00')
    except (FileNotFoundError, PermissionError, IOError):
        return "Unknown"


def get_os_info() -> Tuple[str, str]:
    """Get OS name and version (codename)"""
    os_name = "Unknown"
    os_version = "Unknown"

    try:
        with open('/etc/os-release', 'r') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    os_name = line.split('=')[1].strip().strip('"')
                elif line.startswith('VERSION_CODENAME='):
                    os_version = line.split('=')[1].strip().strip('"')
    except (FileNotFoundError, PermissionError, IOError):
        pass

    return os_name, os_version


def is_bookworm_or_newer() -> bool:
    """Check if running Debian Bookworm (12) or newer"""
    _, codename = get_os_info()
    # Bookworm and newer codenames
    new_codenames = ['bookworm', 'trixie', 'forky', 'sid']
    return codename.lower() in new_codenames


def check_pep668_environment() -> bool:
    """Check if PEP 668 externally managed environment is in effect"""
    # Check for EXTERNALLY-MANAGED file
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    managed_file = Path(f"/usr/lib/python{python_version}/EXTERNALLY-MANAGED")
    return managed_file.exists()


def get_serial_ports() -> List[str]:
    """Get available serial ports, including Raspberry Pi specific ones"""
    ports = []

    # Common USB serial ports
    usb_patterns = ['/dev/ttyUSB*', '/dev/ttyACM*']

    # Raspberry Pi specific serial ports
    pi_ports = ['/dev/ttyAMA0', '/dev/serial0', '/dev/serial1', '/dev/ttyS0']

    # Check USB ports
    for pattern in usb_patterns:
        ret, stdout, _ = run_command(['ls', pattern], capture=True)
        if ret == 0 and stdout.strip():
            ports.extend(stdout.strip().split('\n'))

    # Check Pi-specific ports
    for port in pi_ports:
        if os.path.exists(port):
            ports.append(port)

    return list(set(ports))  # Remove duplicates


def check_user_groups() -> Tuple[bool, bool]:
    """Check if user is in dialout and gpio groups"""
    try:
        groups = subprocess.run(['groups'], capture_output=True, text=True).stdout
        in_dialout = 'dialout' in groups
        in_gpio = 'gpio' in groups
        return in_dialout, in_gpio
    except (subprocess.SubprocessError, FileNotFoundError, Exception):
        return False, False


def fix_serial_permissions() -> bool:
    """Add current user to dialout group for serial port access"""
    print_section("Serial Port Permissions")

    in_dialout, in_gpio = check_user_groups()

    if in_dialout:
        print_success("User already in 'dialout' group")
        return True

    print_warning("User not in 'dialout' group - serial ports may not be accessible")

    if not get_yes_no("Add current user to 'dialout' group?", True):
        print_warning("Skipping - you may need to run as root or add yourself to dialout group")
        return False

    username = os.environ.get('USER', os.environ.get('LOGNAME', ''))
    if not username:
        print_error("Could not determine username")
        return False

    ret, _, stderr = run_command(['usermod', '-a', '-G', 'dialout', username], sudo=True)

    if ret == 0:
        print_success(f"Added {username} to 'dialout' group")
        print_warning("You must log out and back in for this to take effect!")
        print_info("Or run: newgrp dialout")
        return True
    else:
        print_error(f"Failed to add user to dialout group: {stderr}")
        return False


def setup_virtual_environment(venv_path: Path = None) -> Tuple[bool, Optional[Path]]:
    """Set up a Python virtual environment for Bookworm compatibility"""
    print_section("Python Environment Setup")

    if not check_pep668_environment():
        print_info("PEP 668 not in effect - can use system pip directly")
        return True, None

    print_warning("Raspberry Pi OS Bookworm uses PEP 668 (externally managed environment)")
    print_info("A virtual environment is recommended for Python packages")

    if venv_path is None:
        default_venv = Path.home() / "meshing-around-venv"
        venv_input = get_input("Virtual environment path", str(default_venv))
        venv_path = Path(venv_input)

    if venv_path.exists():
        print_success(f"Virtual environment already exists: {venv_path}")
        return True, venv_path

    if not get_yes_no(f"Create virtual environment at {venv_path}?", True):
        print_warning("Skipping venv - pip installs may fail on Bookworm")
        return False, None

    # Check if python3-venv is installed
    ret, _, _ = run_command(['dpkg', '-l', 'python3-venv'], capture=True)
    if ret != 0:
        print_info("Installing python3-venv...")
        ret, _, stderr = run_command(['apt', 'install', '-y', 'python3-venv'], sudo=True)
        if ret != 0:
            print_error(f"Failed to install python3-venv: {stderr}")
            return False, None

    # Create virtual environment
    print_info(f"Creating virtual environment at {venv_path}...")
    ret, _, stderr = run_command(['python3', '-m', 'venv', str(venv_path)])

    if ret == 0:
        print_success(f"Virtual environment created: {venv_path}")
        print_info(f"Activate with: source {venv_path}/bin/activate")
        return True, venv_path
    else:
        print_error(f"Failed to create venv: {stderr}")
        return False, None


def get_pip_command(venv_path: Optional[Path] = None) -> List[str]:
    """Get the appropriate pip command based on environment.

    Returns a base command list. The --break-system-packages flag is placed
    after 'install' since pip requires subcommand before global flags.
    Usage: get_pip_command() + ['install', ...] or
           get_pip_command() + ['install'] + get_pip_extra_flags() + [...]
    """
    if venv_path and venv_path.exists():
        return [str(venv_path / "bin" / "pip3")]
    else:
        return ['pip3']


def get_pip_install_flags() -> List[str]:
    """Get extra flags needed for pip install (e.g. --break-system-packages)."""
    if check_pep668_environment():
        return ['--break-system-packages']
    return []


def raspberry_pi_setup() -> Tuple[bool, Optional[Path]]:
    """Complete Raspberry Pi setup wizard"""
    print_header("Raspberry Pi Setup")

    if not is_raspberry_pi():
        print_info("Not running on Raspberry Pi - skipping Pi-specific setup")
        return True, None

    pi_model = get_pi_model()
    os_name, os_codename = get_os_info()

    print_success(f"Detected: {pi_model}")
    print_info(f"OS: {os_name} ({os_codename})")

    errors = []
    venv_path = None

    # Step 1: Check serial permissions
    print_step(1, 4, "Checking serial port permissions...")
    if not fix_serial_permissions():
        errors.append("Serial permissions not configured")

    # Step 2: Check available serial ports
    print_step(2, 4, "Detecting serial ports...")
    ports = get_serial_ports()
    if ports:
        print_success(f"Found serial ports: {', '.join(ports)}")
    else:
        print_warning("No serial ports found - connect your Meshtastic device")

    # Step 3: Handle PEP 668 / virtual environment
    print_step(3, 4, "Setting up Python environment...")
    if is_bookworm_or_newer():
        success, venv_path = setup_virtual_environment()
        if not success:
            errors.append("Virtual environment not configured")

    # Step 4: Check for required system packages
    print_step(4, 4, "Checking system packages...")
    required_packages = ['python3-pip', 'git']
    missing = []

    for pkg in required_packages:
        ret, _, _ = run_command(['dpkg', '-l', pkg], capture=True)
        if ret != 0:
            missing.append(pkg)

    if missing:
        print_warning(f"Missing packages: {', '.join(missing)}")
        if get_yes_no("Install missing packages?", True):
            ret, _, stderr = run_command(['apt', 'install', '-y'] + missing, sudo=True)
            if ret == 0:
                print_success("Packages installed")
            else:
                print_error(f"Failed to install packages: {stderr}")
                errors.append("Some packages not installed")
    else:
        print_success("All required packages installed")

    # Summary
    print_section("Raspberry Pi Setup Summary")
    if errors:
        print_warning("Setup completed with issues:")
        for err in errors:
            print_error(f"  • {err}")
    else:
        print_success("Raspberry Pi setup complete!")

    if venv_path:
        print_info(f"Virtual environment: {venv_path}")
        print_info(f"Activate before running bot: source {venv_path}/bin/activate")

    return len(errors) == 0, venv_path


def get_pi_config_path() -> Path:
    """Get the correct config.txt path for Bookworm/Trixie"""
    # Bookworm and newer use /boot/firmware/config.txt
    bookworm_path = Path("/boot/firmware/config.txt")
    legacy_path = Path("/boot/config.txt")

    if bookworm_path.exists():
        return bookworm_path
    elif legacy_path.exists():
        return legacy_path
    else:
        # Default to Bookworm path for new installations
        return bookworm_path


def check_serial_enabled() -> Tuple[bool, bool]:
    """Check if serial port is enabled in config.txt
    Returns: (uart_enabled, console_enabled)
    """
    config_path = get_pi_config_path()

    if not config_path.exists():
        return False, False

    try:
        with open(config_path, 'r') as f:
            content = f.read()

        uart_enabled = 'enable_uart=1' in content
        # Check if console is on serial (in cmdline.txt)
        cmdline_path = config_path.parent / "cmdline.txt"
        console_enabled = False
        if cmdline_path.exists():
            with open(cmdline_path, 'r') as f:
                cmdline = f.read()
                console_enabled = 'console=serial' in cmdline or 'console=ttyAMA' in cmdline

        return uart_enabled, console_enabled
    except (FileNotFoundError, PermissionError, IOError):
        return False, False


def configure_serial_raspi_config() -> bool:
    """Configure serial port using raspi-config (non-interactive)"""
    print_section("Serial Port Configuration")

    if not is_raspberry_pi():
        print_info("Not a Raspberry Pi - skipping raspi-config")
        return True

    # Check if raspi-config exists
    ret, _, _ = run_command(['which', 'raspi-config'], capture=True)
    if ret != 0:
        print_warning("raspi-config not found - manual configuration may be needed")
        return False

    uart_enabled, console_enabled = check_serial_enabled()

    if uart_enabled:
        print_success("UART is already enabled")
        if console_enabled:
            print_warning("Serial console is enabled - this may interfere with Meshtastic")
            if get_yes_no("Disable serial console (recommended for Meshtastic)?", True):
                # Disable console but keep hardware serial
                ret, _, stderr = run_command(
                    ['raspi-config', 'nonint', 'do_serial_cons', '1'],
                    sudo=True
                )
                if ret == 0:
                    print_success("Serial console disabled")
                else:
                    print_error(f"Failed to disable console: {stderr}")
        return True

    print_warning("UART is not enabled")
    if not get_yes_no("Enable UART for Meshtastic serial connection?", True):
        return False

    # Enable serial hardware, disable console
    print_info("Enabling serial port via raspi-config...")

    # do_serial_hw 0 = enable, 1 = disable (yes, it's backwards)
    ret, _, stderr = run_command(
        ['raspi-config', 'nonint', 'do_serial_hw', '0'],
        sudo=True
    )
    if ret != 0:
        print_error(f"Failed to enable serial hardware: {stderr}")
        return False

    # Disable console on serial
    ret, _, stderr = run_command(
        ['raspi-config', 'nonint', 'do_serial_cons', '1'],
        sudo=True
    )
    if ret == 0:
        print_success("Serial port enabled, console disabled")
        print_warning("A reboot is required for changes to take effect!")
        return True
    else:
        print_error(f"Failed to configure serial console: {stderr}")
        return False


def enable_i2c_spi() -> bool:
    """Enable I2C and SPI interfaces if needed"""
    if not is_raspberry_pi():
        return True

    print_section("I2C/SPI Configuration")

    # Check if raspi-config exists
    ret, _, _ = run_command(['which', 'raspi-config'], capture=True)
    if ret != 0:
        print_warning("raspi-config not found")
        return False

    # Check current I2C status
    ret, stdout, _ = run_command(['raspi-config', 'nonint', 'get_i2c'], capture=True)
    i2c_enabled = ret == 0 and stdout.strip() == '0'

    if i2c_enabled:
        print_success("I2C is already enabled")
    else:
        if get_yes_no("Enable I2C interface?", False):
            ret, _, _ = run_command(['raspi-config', 'nonint', 'do_i2c', '0'], sudo=True)
            if ret == 0:
                print_success("I2C enabled")
            else:
                print_warning("Failed to enable I2C")

    # Check SPI status
    ret, stdout, _ = run_command(['raspi-config', 'nonint', 'get_spi'], capture=True)
    spi_enabled = ret == 0 and stdout.strip() == '0'

    if spi_enabled:
        print_success("SPI is already enabled")
    else:
        if get_yes_no("Enable SPI interface?", False):
            ret, _, _ = run_command(['raspi-config', 'nonint', 'do_spi', '0'], sudo=True)
            if ret == 0:
                print_success("SPI enabled")
            else:
                print_warning("Failed to enable SPI")

    return True


def startup_system_check() -> bool:
    """Run system checks and updates at startup"""
    print_header("Meshing-Around Enhanced Configuration Tool")
    print(f"Version {VERSION}\n")

    # Detect platform
    os_name, os_codename = get_os_info()

    if is_raspberry_pi():
        pi_model = get_pi_model()
        print_success(f"Platform: {pi_model}")
    else:
        print_info("Platform: Standard Linux system")

    print(f"OS: {os_name} ({os_codename})")

    # Check if this is a supported OS
    if os_codename.lower() in SUPPORTED_OS:
        print_success(f"OS version supported")
    else:
        print_warning(f"OS version '{os_codename}' may not be fully tested")

    # Check Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 9):
        print_success(f"Python {py_version}")
    else:
        print_warning(f"Python {py_version} - version 3.9+ recommended")

    # Offer to run system update
    print_section("System Update")
    print_info("It's recommended to update your system before proceeding")

    if get_yes_no("Run system update now (apt update && apt upgrade)?", True):
        errors = []

        # apt update
        print_step(1, 3, "Updating package lists...")
        ret, _, stderr = run_command(['apt', 'update'], sudo=True)
        if ret != 0:
            errors.append(f"apt update: {stderr}")
            print_warning("Failed to update package lists")
        else:
            print_success("Package lists updated")

        # apt upgrade
        print_step(2, 3, "Upgrading packages...")
        ret, _, stderr = run_command(['apt', 'upgrade', '-y'], sudo=True)
        if ret != 0:
            errors.append(f"apt upgrade: {stderr}")
            print_warning("Failed to upgrade packages")
        else:
            print_success("Packages upgraded")

        # Cleanup
        print_step(3, 3, "Cleaning up...")
        run_command(['apt', 'autoremove', '-y'], sudo=True)
        print_success("Cleanup complete")

        if errors:
            print_warning("Some updates failed (may be normal without network):")
            for err in errors:
                print_info(f"  {err[:60]}...")
    else:
        print_info("Skipping system update")

    # Pi-specific checks
    if is_raspberry_pi():
        # Check for required packages on Pi
        print_section("Raspberry Pi Prerequisites")

        required_pkgs = ['python3-pip', 'python3-venv', 'git', 'i2c-tools']
        missing = []

        for pkg in required_pkgs:
            ret, _, _ = run_command(['dpkg', '-s', pkg], capture=True)
            if ret != 0:
                missing.append(pkg)

        if missing:
            print_warning(f"Missing packages: {', '.join(missing)}")
            if get_yes_no("Install missing packages?", True):
                ret, _, _ = run_command(['apt', 'install', '-y'] + missing, sudo=True)
                if ret == 0:
                    print_success("Packages installed")
                else:
                    print_warning("Some packages failed to install")
        else:
            print_success("All required packages installed")

        # Configure serial if needed
        configure_serial_raspi_config()

    return True


def get_input(prompt: str, default: str = "", input_type: type = str, password: bool = False) -> Any:
    """Get user input with optional default value and password masking"""
    if default:
        if password:
            full_prompt = f"{prompt} [****]: "
        else:
            full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "

    while True:
        try:
            if password:
                value = getpass(full_prompt)
            else:
                value = input(full_prompt).strip()

            if not value and default:
                value = str(default)

            if input_type == bool:
                value_lower = str(value).lower()
                if value_lower in ['true', 'yes', 'y', '1', 'on']:
                    return True
                elif value_lower in ['false', 'no', 'n', '0', 'off']:
                    return False
                else:
                    print_error("Please enter yes/no (y/n) or true/false")
                    continue
            elif input_type == int:
                return int(value) if value else int(default) if default else 0
            elif input_type == float:
                return float(value) if value else float(default) if default else 0.0
            else:
                return value
        except ValueError:
            print_error(f"Invalid input. Expected {input_type.__name__}")

def get_yes_no(prompt: str, default: bool = False) -> bool:
    """Get yes/no input from user"""
    default_str = "Y/n" if default else "y/N"
    response = get_input(f"{prompt} ({default_str})", "y" if default else "n")
    return response.lower() in ['y', 'yes', 'true', '1']

def configure_interface(config: configparser.ConfigParser):
    """Configure interface settings"""
    print_section("Interface Configuration")
    
    print("\nConnection types:")
    print("  1. Serial (recommended)")
    print("  2. TCP")
    print("  3. BLE")
    
    conn_type = get_input("Select connection type (1-3)", "1")
    type_map = {"1": "serial", "2": "tcp", "3": "ble"}
    conn_type_str = type_map.get(conn_type, "serial")
    
    config['interface']['type'] = conn_type_str
    
    if conn_type_str == "serial":
        use_auto = get_yes_no("Use auto-detect for serial port?", True)
        if not use_auto:
            port = get_input("Enter serial port", "/dev/ttyUSB0")
            config['interface']['port'] = port
    elif conn_type_str == "tcp":
        hostname = get_input("Enter TCP hostname/IP", "192.168.1.100")
        config['interface']['hostname'] = hostname
    elif conn_type_str == "ble":
        mac = get_input("Enter BLE MAC address", "AA:BB:CC:DD:EE:FF")
        config['interface']['mac'] = mac
    
    print_success(f"Interface configured: {conn_type_str}")

def configure_general(config: configparser.ConfigParser):
    """Configure general settings"""
    print_section("General Settings")
    
    bot_name = get_input("Bot name", "MeshBot")
    config['general']['bot_name'] = bot_name
    
    if get_yes_no("Configure admin nodes?", False):
        admin_list = get_input("Admin node numbers (comma-separated)")
        config['general']['bbs_admin_list'] = admin_list
    
    if get_yes_no("Configure favorite nodes?", False):
        fav_list = get_input("Favorite node numbers (comma-separated)")
        config['general']['favoriteNodeList'] = fav_list
    
    print_success("General settings configured")

def configure_emergency_alerts(config: configparser.ConfigParser):
    """Configure emergency alert settings"""
    print_section("Emergency Alert Configuration")
    
    if not get_yes_no("Enable emergency keyword detection?", True):
        config['emergencyHandler']['enabled'] = 'False'
        return
    
    config['emergencyHandler']['enabled'] = 'True'
    
    print("\nDefault keywords: emergency, 911, 112, 999, police, fire, ambulance, rescue, help, sos, mayday")
    if get_yes_no("Use default emergency keywords?", True):
        config['emergencyHandler']['emergency_keywords'] = 'emergency,911,112,999,police,fire,ambulance,rescue,help,sos,mayday'
    else:
        keywords = get_input("Enter emergency keywords (comma-separated)")
        config['emergencyHandler']['emergency_keywords'] = keywords
    
    channel = get_input("Alert channel number", "2", int)
    config['emergencyHandler']['alert_channel'] = str(channel)
    
    cooldown = get_input("Cooldown period between alerts (seconds)", "300", int)
    config['emergencyHandler']['cooldown_period'] = str(cooldown)
    
    if get_yes_no("Enable email notifications for emergencies?", False):
        config['emergencyHandler']['send_email'] = 'True'
    
    if get_yes_no("Enable SMS notifications for emergencies?", False):
        config['emergencyHandler']['send_sms'] = 'True'
    
    if get_yes_no("Play sound for emergency alerts?", False):
        config['emergencyHandler']['play_sound'] = 'True'
        sound_file = get_input("Sound file path", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga")
        config['emergencyHandler']['sound_file'] = sound_file
    
    print_success("Emergency alerts configured")

def configure_proximity_alerts(config: configparser.ConfigParser):
    """Configure proximity-based alerts"""
    print_section("Proximity Alert Configuration")
    
    print("\nProximity alerts notify when nodes enter a specified area")
    print("Useful for campsite monitoring, geofencing, etc.")
    
    if not get_yes_no("Enable proximity alerts?", False):
        config['proximityAlert']['enabled'] = 'False'
        return
    
    config['proximityAlert']['enabled'] = 'True'
    
    lat = get_input("Target latitude", "0.0", float)
    config['proximityAlert']['target_latitude'] = str(lat)
    
    lon = get_input("Target longitude", "0.0", float)
    config['proximityAlert']['target_longitude'] = str(lon)
    
    radius = get_input("Proximity radius in meters", "100", int)
    config['proximityAlert']['radius_meters'] = str(radius)
    
    channel = get_input("Alert channel", "0", int)
    config['proximityAlert']['alert_channel'] = str(channel)
    
    interval = get_input("Check interval in seconds", "60", int)
    config['proximityAlert']['check_interval'] = str(interval)
    
    if get_yes_no("Execute script on proximity trigger?", False):
        config['proximityAlert']['run_script'] = 'True'
        script_path = get_input("Script path")
        config['proximityAlert']['script_path'] = script_path
    
    print_success("Proximity alerts configured")

def configure_altitude_alerts(config: configparser.ConfigParser):
    """Configure high altitude alerts"""
    print_section("Altitude Alert Configuration")
    
    if not get_yes_no("Enable high altitude detection?", False):
        config['altitudeAlert']['enabled'] = 'False'
        return
    
    config['altitudeAlert']['enabled'] = 'True'
    
    altitude = get_input("Minimum altitude threshold (meters)", "1000", int)
    config['altitudeAlert']['min_altitude'] = str(altitude)
    
    channel = get_input("Alert channel", "0", int)
    config['altitudeAlert']['alert_channel'] = str(channel)
    
    interval = get_input("Check interval (seconds)", "120", int)
    config['altitudeAlert']['check_interval'] = str(interval)
    
    print_success("Altitude alerts configured")

def configure_weather_alerts(config: configparser.ConfigParser):
    """Configure weather/NOAA alerts"""
    print_section("Weather Alert Configuration")
    
    if not get_yes_no("Enable weather/NOAA alerts?", False):
        config['weatherAlert']['enabled'] = 'False'
        return
    
    config['weatherAlert']['enabled'] = 'True'
    
    location = get_input("Location (latitude,longitude)")
    config['weatherAlert']['location'] = location
    
    print("\nSeverity levels: Extreme, Severe, Moderate, Minor")
    severity = get_input("Alert severity levels (comma-separated)", "Extreme,Severe")
    config['weatherAlert']['severity_levels'] = severity
    
    interval = get_input("Check interval (minutes)", "30", int)
    config['weatherAlert']['check_interval_minutes'] = str(interval)
    
    channel = get_input("Alert channel", "2", int)
    config['weatherAlert']['alert_channel'] = str(channel)
    
    print_success("Weather alerts configured")

def configure_battery_alerts(config: configparser.ConfigParser):
    """Configure low battery alerts"""
    print_section("Battery Alert Configuration")
    
    if not get_yes_no("Enable low battery monitoring?", False):
        config['batteryAlert']['enabled'] = 'False'
        return
    
    config['batteryAlert']['enabled'] = 'True'
    
    threshold = get_input("Battery threshold percentage", "20", int)
    config['batteryAlert']['threshold_percent'] = str(threshold)
    
    interval = get_input("Check interval (minutes)", "30", int)
    config['batteryAlert']['check_interval_minutes'] = str(interval)
    
    channel = get_input("Alert channel", "0", int)
    config['batteryAlert']['alert_channel'] = str(channel)
    
    if get_yes_no("Monitor specific nodes only?", False):
        nodes = get_input("Node numbers to monitor (comma-separated)")
        config['batteryAlert']['monitor_nodes'] = nodes
    
    print_success("Battery alerts configured")

def configure_noisy_node_alerts(config: configparser.ConfigParser):
    """Configure noisy node detection"""
    print_section("Noisy Node Alert Configuration")
    
    if not get_yes_no("Enable noisy node detection?", False):
        config['noisyNodeAlert']['enabled'] = 'False'
        return
    
    config['noisyNodeAlert']['enabled'] = 'True'
    
    threshold = get_input("Message threshold (messages per period)", "50", int)
    config['noisyNodeAlert']['message_threshold'] = str(threshold)
    
    period = get_input("Time period (minutes)", "10", int)
    config['noisyNodeAlert']['time_period_minutes'] = str(period)
    
    if get_yes_no("Auto-mute noisy nodes?", False):
        config['noisyNodeAlert']['auto_mute'] = 'True'
        duration = get_input("Mute duration (minutes)", "60", int)
        config['noisyNodeAlert']['mute_duration_minutes'] = str(duration)
    
    print_success("Noisy node alerts configured")

def configure_new_node_alerts(config: configparser.ConfigParser):
    """Configure new node welcome messages"""
    print_section("New Node Alert Configuration")
    
    if not get_yes_no("Enable new node welcomes?", True):
        config['newNodeAlert']['enabled'] = 'False'
        return
    
    config['newNodeAlert']['enabled'] = 'True'
    
    message = get_input("Welcome message (use {node_name} placeholder)", "Welcome to the mesh, {node_name}!")
    config['newNodeAlert']['welcome_message'] = message
    
    send_dm = get_yes_no("Send welcome as DM?", True)
    config['newNodeAlert']['send_as_dm'] = str(send_dm)
    
    if get_yes_no("Also announce to channel?", False):
        config['newNodeAlert']['announce_to_channel'] = 'True'
        channel = get_input("Announcement channel", "0", int)
        config['newNodeAlert']['announcement_channel'] = str(channel)
    
    print_success("New node alerts configured")

def configure_email_sms(config: configparser.ConfigParser):
    """Configure email and SMS settings"""
    print_section("Email/SMS Configuration")
    
    if not get_yes_no("Configure email settings?", False):
        return
    
    config['smtp']['enableSMTP'] = 'True'
    
    server = get_input("SMTP server", "smtp.gmail.com")
    config['smtp']['SMTP_SERVER'] = server
    
    port = get_input("SMTP port", "587", int)
    config['smtp']['SMTP_PORT'] = str(port)
    
    username = get_input("SMTP username/email")
    config['smtp']['SMTP_USERNAME'] = username
    
    password = get_input("SMTP password", password=True)
    config['smtp']['SMTP_PASSWORD'] = password
    
    from_addr = get_input("From email address", username)
    config['smtp']['SMTP_FROM'] = from_addr
    
    sysop_emails = get_input("Sysop email addresses (comma-separated)")
    config['smtp']['sysopEmails'] = sysop_emails
    
    if get_yes_no("Configure SMS settings?", False):
        config['sms']['enabled'] = 'True'
        gateway = get_input("SMS gateway (e.g., @txt.att.net)")
        config['sms']['gateway'] = gateway
        phones = get_input("Phone numbers (comma-separated)")
        config['sms']['phone_numbers'] = phones
    
    print_success("Email/SMS settings configured")

def configure_global_settings(config: configparser.ConfigParser):
    """Configure global alert settings"""
    print_section("Global Alert Settings")

    if get_yes_no("Enable all alerts globally?", True):
        config['alertGlobal']['global_enabled'] = 'True'
    else:
        config['alertGlobal']['global_enabled'] = 'False'
        return

    if get_yes_no("Configure quiet hours?", False):
        quiet = get_input("Quiet hours (24hr format HH:MM-HH:MM, e.g., 22:00-07:00)")
        config['alertGlobal']['quiet_hours'] = quiet

    max_rate = get_input("Maximum alerts per hour (all types)", "20", int)
    config['alertGlobal']['max_alerts_per_hour'] = str(max_rate)

    print_success("Global settings configured")


# ============================================================================
# SYSTEM MAINTENANCE FUNCTIONS
# ============================================================================

def system_update() -> bool:
    """Run apt update and upgrade"""
    print_section("System Update")
    print_info("This will update your system packages (requires sudo)")

    if not get_yes_no("Proceed with system update?", True):
        print_warning("Skipping system update")
        return True

    errors = []

    # Step 1: apt update
    print_step(1, 3, "Updating package lists...")
    ret, stdout, stderr = run_command(['apt', 'update'], sudo=True)
    if ret != 0:
        errors.append(f"apt update failed: {stderr}")
        print_error("Failed to update package lists")
    else:
        print_success("Package lists updated")

    # Step 2: apt upgrade
    print_step(2, 3, "Upgrading packages...")
    ret, stdout, stderr = run_command(['apt', 'upgrade', '-y'], sudo=True)
    if ret != 0:
        errors.append(f"apt upgrade failed: {stderr}")
        print_error("Failed to upgrade packages")
    else:
        print_success("Packages upgraded")

    # Step 3: Clean up
    print_step(3, 3, "Cleaning up...")
    run_command(['apt', 'autoremove', '-y'], sudo=True)
    print_success("Cleanup complete")

    if errors:
        print_warning("Some errors occurred during update:")
        for err in errors:
            print_error(f"  {err}")
        return False

    print_success("System update completed successfully!")
    return True


def update_meshing_around(meshing_path: Optional[Path] = None) -> Tuple[bool, Optional[Path]]:
    """Git pull the latest meshing-around code"""
    print_section("Update Meshing-Around")

    # Find meshing-around directory
    if meshing_path is None:
        meshing_path = find_meshing_around()

    if meshing_path is None:
        print_warning("Meshing-around not found in common locations")
        custom_path = get_input("Enter path to meshing-around directory (or 'skip')")
        if custom_path.lower() == 'skip':
            return True, None
        meshing_path = Path(custom_path)

    if not meshing_path.exists():
        print_error(f"Directory not found: {meshing_path}")
        if get_yes_no("Clone meshing-around from GitHub?", True):
            clone_path = get_input("Clone to directory", str(Path.home() / "meshing-around"))
            ret, _, stderr = run_command(
                ['git', 'clone', 'https://github.com/SpudGunMan/meshing-around.git', clone_path],
                desc="Cloning meshing-around"
            )
            if ret == 0:
                print_success(f"Cloned to {clone_path}")
                meshing_path = Path(clone_path)
            else:
                print_error(f"Clone failed: {stderr}")
                return False, None
        else:
            return True, None

    print_info(f"Found meshing-around at: {meshing_path}")

    # Git pull
    print_info("Pulling latest changes...")
    original_dir = os.getcwd()
    try:
        os.chdir(meshing_path)

        # Check for uncommitted changes
        ret, stdout, _ = run_command(['git', 'status', '--porcelain'], capture=True)
        if stdout.strip():
            print_warning("Uncommitted changes detected:")
            print(stdout)
            if not get_yes_no("Continue with git pull anyway?", False):
                os.chdir(original_dir)
                return True, meshing_path

        # Git pull
        ret, stdout, stderr = run_command(['git', 'pull', 'origin', 'main'], capture=True)
        if ret != 0:
            # Try master branch
            ret, stdout, stderr = run_command(['git', 'pull', 'origin', 'master'], capture=True)

        if ret == 0:
            if 'Already up to date' in stdout:
                print_success("Already up to date")
            else:
                print_success("Updated to latest version")
                print(stdout)
        else:
            print_error(f"Git pull failed: {stderr}")
            os.chdir(original_dir)
            return False, meshing_path

    finally:
        os.chdir(original_dir)

    return True, meshing_path


def install_dependencies(meshing_path: Path, venv_path: Optional[Path] = None) -> bool:
    """Install Python dependencies for meshing-around with Raspberry Pi compatibility"""
    print_section("Install Dependencies")

    requirements_file = meshing_path / "requirements.txt"
    if not requirements_file.exists():
        print_warning("No requirements.txt found")
        return True

    if not get_yes_no("Install Python dependencies?", True):
        return True

    # Determine the pip command to use
    pip_cmd = get_pip_command(venv_path)

    # Check for Bookworm/PEP 668
    if check_pep668_environment() and not venv_path:
        print_warning("Raspberry Pi OS Bookworm detected with PEP 668")
        print_info("Using --break-system-packages flag (or use a virtual environment)")

    extra_flags = get_pip_install_flags()
    pip_display = ' '.join(pip_cmd)

    print_info(f"Using pip command: {pip_display}")

    # Try installing from requirements.txt first
    print_info("Installing from requirements.txt...")
    install_cmd = pip_cmd + ['install'] + extra_flags + ['-r', str(requirements_file)]
    ret, stdout, stderr = run_command(install_cmd, capture=True)

    if ret != 0:
        print_warning("Some packages failed to install from requirements.txt")
        print_info("Trying alternative package names...")

        # Known package name fixes for compatibility
        package_fixes = {
            'pubsub': 'PyPubSub',
            'pyephem': 'ephem',
        }

        # Install core packages individually with fixes
        core_packages = [
            'meshtastic',
            'PyPubSub',  # Instead of pubsub
            'ephem',     # Instead of pyephem
            'requests',
            'maidenhead',
            'beautifulsoup4',
            'dadjokes',
            'geopy',
            'schedule',
        ]

        failed_packages = []
        for pkg in core_packages:
            print_info(f"Installing {pkg}...")
            install_cmd = pip_cmd + ['install'] + extra_flags + [pkg]
            ret, _, stderr = run_command(install_cmd, capture=True)
            if ret != 0:
                failed_packages.append(pkg)
                print_warning(f"  Failed to install {pkg}")
            else:
                print_success(f"  Installed {pkg}")

        if failed_packages:
            print_warning(f"Failed packages: {', '.join(failed_packages)}")
            print_info("You may need to install these manually")
            return False
    else:
        print_success("All dependencies installed from requirements.txt")

    # Verify critical packages
    print_info("Verifying critical packages...")
    python_cmd = str(venv_path / "bin" / "python3") if venv_path else "python3"

    critical = ['meshtastic']
    for pkg in critical:
        ret, _, _ = run_command([python_cmd, '-c', f'import {pkg}'], capture=True)
        if ret == 0:
            print_success(f"  {pkg} OK")
        else:
            print_error(f"  {pkg} MISSING")
            return False

    print_success("Dependencies installed successfully!")
    return True


def install_meshing_around() -> Tuple[bool, Optional[Path], Optional[Path]]:
    """Download and fully install meshing-around from GitHub

    Returns: (success, meshing_path, venv_path)
    """
    print_header("Install Meshing-Around")

    print("""
This wizard will:
  1. Clone meshing-around from GitHub
  2. Set up a Python virtual environment (if needed)
  3. Install all Python dependencies
  4. Optionally set up a systemd service for auto-start
    """)

    if not get_yes_no("Continue with installation?", True):
        return False, None, None

    errors = []
    venv_path = None

    # Step 1: Determine installation location
    print_step(1, 5, "Choosing installation location...")

    default_install_path = Path.home() / "meshing-around"
    install_path = Path(get_input("Installation directory", str(default_install_path)))

    # Check if already exists
    if install_path.exists():
        if (install_path / "mesh_bot.py").exists():
            print_warning(f"Meshing-around already installed at {install_path}")
            if get_yes_no("Update existing installation instead?", True):
                success, path = update_meshing_around(install_path)
                return success, path, None
            elif get_yes_no("Remove and reinstall?", False):
                try:
                    shutil.rmtree(install_path)
                    print_success("Removed existing installation")
                except Exception as e:
                    print_error(f"Failed to remove: {e}")
                    return False, None, None
            else:
                return False, None, None
        else:
            print_warning(f"Directory exists but doesn't contain meshing-around")
            if not get_yes_no("Remove and use this directory?", False):
                return False, None, None
            try:
                shutil.rmtree(install_path)
            except Exception as e:
                print_error(f"Failed to remove: {e}")
                return False, None, None

    # Step 2: Clone the repository
    print_step(2, 5, "Cloning meshing-around from GitHub...")

    # Make sure git is installed
    ret, _, _ = run_command(['which', 'git'], capture=True)
    if ret != 0:
        print_info("Installing git...")
        ret, _, stderr = run_command(['apt', 'install', '-y', 'git'], sudo=True)
        if ret != 0:
            print_error(f"Failed to install git: {stderr}")
            return False, None, None

    # Clone the repository
    ret, stdout, stderr = run_command(
        ['git', 'clone', 'https://github.com/SpudGunMan/meshing-around.git', str(install_path)],
        desc="Cloning repository"
    )

    if ret != 0:
        print_error(f"Failed to clone repository: {stderr}")
        return False, None, None

    print_success(f"Cloned meshing-around to {install_path}")

    # Step 3: Set up virtual environment (if needed)
    print_step(3, 5, "Setting up Python environment...")

    if is_bookworm_or_newer() or check_pep668_environment():
        print_info("PEP 668 environment detected - setting up virtual environment")

        default_venv = install_path / "venv"
        venv_input = get_input("Virtual environment path", str(default_venv))
        venv_path = Path(venv_input)

        # Check if python3-venv is installed
        ret, _, _ = run_command(['dpkg', '-l', 'python3-venv'], capture=True)
        if ret != 0:
            print_info("Installing python3-venv...")
            ret, _, stderr = run_command(['apt', 'install', '-y', 'python3-venv'], sudo=True)
            if ret != 0:
                print_error(f"Failed to install python3-venv: {stderr}")
                errors.append("Failed to install python3-venv")

        if not venv_path.exists():
            print_info(f"Creating virtual environment at {venv_path}...")
            ret, _, stderr = run_command(['python3', '-m', 'venv', str(venv_path)])

            if ret == 0:
                print_success(f"Virtual environment created")
            else:
                print_error(f"Failed to create venv: {stderr}")
                errors.append("Virtual environment creation failed")
                venv_path = None
        else:
            print_success("Virtual environment already exists")
    else:
        print_info("System pip can be used directly (no PEP 668)")

    # Step 4: Install dependencies
    print_step(4, 5, "Installing Python dependencies...")

    if not install_dependencies(install_path, venv_path):
        errors.append("Some dependencies failed to install")

    # Step 5: Optional systemd service setup
    print_step(5, 5, "Optional service setup...")

    if get_yes_no("Create systemd service for auto-start on boot?", False):
        if create_systemd_service(install_path, venv_path):
            print_success("Systemd service created")
        else:
            errors.append("Systemd service creation failed")

    # Summary
    print_section("Installation Summary")

    if errors:
        print_warning("Installation completed with some issues:")
        for err in errors:
            print_error(f"  • {err}")
    else:
        print_success("Meshing-around installed successfully!")

    print_info(f"\nInstallation path: {install_path}")

    if venv_path:
        print_info(f"Virtual environment: {venv_path}")
        print(f"""
{Colors.OKCYAN}To run the bot:{Colors.ENDC}
  1. source {venv_path}/bin/activate
  2. cd {install_path}
  3. python3 mesh_bot.py

{Colors.OKCYAN}Or use the systemd service (if created):{Colors.ENDC}
  sudo systemctl start meshing-around
  sudo systemctl enable meshing-around  # auto-start on boot
""")
    else:
        print(f"""
{Colors.OKCYAN}To run the bot:{Colors.ENDC}
  1. cd {install_path}
  2. python3 mesh_bot.py
""")

    return len(errors) == 0, install_path, venv_path


def create_systemd_service(install_path: Path, venv_path: Optional[Path] = None) -> bool:
    """Create a systemd service file for meshing-around auto-start"""
    print_section("Create Systemd Service")

    # Get current user
    username = os.environ.get('USER', os.environ.get('LOGNAME', 'pi'))

    # Determine python path
    if venv_path and venv_path.exists():
        python_path = str(venv_path / "bin" / "python3")
    else:
        python_path = "/usr/bin/python3"

    # Create service file content
    service_name = "meshing-around"
    service_content = f"""[Unit]
Description=Meshing-Around Meshtastic Bot
After=network.target

[Service]
Type=simple
User={username}
WorkingDirectory={install_path}
ExecStart={python_path} {install_path}/mesh_bot.py
Restart=on-failure
RestartSec=10

# Environment
Environment=PYTHONUNBUFFERED=1
{f'Environment=VIRTUAL_ENV={venv_path}' if venv_path else ''}

# Logging
StandardOutput=append:/var/log/meshing-around.log
StandardError=append:/var/log/meshing-around.log

[Install]
WantedBy=multi-user.target
"""

    # Preview the service
    print_info("Service file preview:")
    print(f"{Colors.OKCYAN}{service_content}{Colors.ENDC}")

    if not get_yes_no("Create this service file?", True):
        return False

    # Write service file
    import tempfile
    service_path = Path(f"/etc/systemd/system/{service_name}.service")

    temp_path = None
    try:
        # Write to secure temp file (unpredictable path, restricted permissions)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.service', delete=False) as tf:
            tf.write(service_content)
            temp_path = Path(tf.name)

        # Copy to systemd directory with sudo
        ret, _, stderr = run_command(['cp', str(temp_path), str(service_path)], sudo=True)
        if ret != 0:
            print_error(f"Failed to copy service file: {stderr}")
            return False

        # Set permissions
        run_command(['chmod', '644', str(service_path)], sudo=True)

        # Create log file
        log_path = Path("/var/log/meshing-around.log")
        run_command(['touch', str(log_path)], sudo=True)
        run_command(['chown', f'{username}:{username}', str(log_path)], sudo=True)

        # Reload systemd
        ret, _, stderr = run_command(['systemctl', 'daemon-reload'], sudo=True)
        if ret != 0:
            print_error(f"Failed to reload systemd: {stderr}")
            return False

        print_success(f"Service created: {service_path}")

        # Offer to enable and start
        if get_yes_no("Enable service to start on boot?", True):
            ret, _, stderr = run_command(['systemctl', 'enable', service_name], sudo=True)
            if ret == 0:
                print_success("Service enabled for auto-start")
            else:
                print_error(f"Failed to enable service: {stderr}")

        if get_yes_no("Start the service now?", False):
            ret, _, stderr = run_command(['systemctl', 'start', service_name], sudo=True)
            if ret == 0:
                print_success("Service started")
                # Show status
                time.sleep(2)
                ret, stdout, _ = run_command(['systemctl', 'status', service_name], capture=True)
                if ret == 0:
                    print(stdout)
            else:
                print_error(f"Failed to start service: {stderr}")

        print_info(f"""
Service management commands:
  sudo systemctl start {service_name}     # Start the bot
  sudo systemctl stop {service_name}      # Stop the bot
  sudo systemctl restart {service_name}   # Restart the bot
  sudo systemctl status {service_name}    # Check status
  sudo journalctl -u {service_name} -f    # View logs
""")

        return True

    except (OSError, subprocess.SubprocessError) as e:
        print_error(f"Failed to create service: {e}")
        return False
    finally:
        # Clean up temp file
        if temp_path and temp_path.exists():
            temp_path.unlink()


def run_install_script(meshing_path: Path) -> bool:
    """Run the meshing-around install.sh script for automated setup"""
    print_section("Run install.sh")

    install_script = meshing_path / "install.sh"

    if not install_script.exists():
        print_error(f"install.sh not found at {meshing_path}")
        print_info("This script is part of the meshing-around repository")
        print_info("It automates venv creation and requirements installation")
        return False

    print_info("The install.sh script will:")
    print("  • Optionally create a Python virtual environment")
    print("  • Install requirements from requirements.txt")
    print("  • Set up the meshing-around bot environment")

    if not get_yes_no("\nRun install.sh now?", True):
        return False

    # Make sure the script is executable
    run_command(['chmod', '+x', str(install_script)])

    # Run the install script
    print_info("Running install.sh...")
    original_dir = os.getcwd()

    try:
        os.chdir(meshing_path)
        ret, stdout, stderr = run_command(['bash', str(install_script)])

        if ret == 0:
            print_success("install.sh completed successfully!")
            return True
        else:
            print_error(f"install.sh failed with exit code {ret}")
            if stderr:
                print_error(f"Error: {stderr}")
            return False
    except Exception as e:
        print_error(f"Failed to run install.sh: {e}")
        return False
    finally:
        os.chdir(original_dir)


def run_launch_script(meshing_path: Path, venv_path: Optional[Path] = None) -> bool:
    """Run the meshing-around launch.sh script to start the bot"""
    print_section("Launch Bot")

    launch_script = meshing_path / "launch.sh"

    # Check for launch.sh first
    if launch_script.exists():
        print_info("Found launch.sh - this is used for venv installations")
        print_info("It will activate the venv and start the bot")

        if get_yes_no("Run launch.sh to start the bot?", True):
            # Make sure the script is executable
            run_command(['chmod', '+x', str(launch_script)])

            print_info("Starting bot via launch.sh...")
            original_dir = os.getcwd()

            try:
                os.chdir(meshing_path)

                # Run in background using nohup
                process = subprocess.Popen(
                    ['bash', str(launch_script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True
                )

                # Wait a few seconds to see if it starts
                time.sleep(3)

                if process.poll() is None:
                    print_success(f"Bot started successfully! PID: {process.pid}")
                    print_info("Bot is running in the background")
                    return True
                else:
                    stdout, stderr = process.communicate()
                    print_error("Bot failed to start:")
                    if stderr:
                        print(stderr.decode())
                    return False

            except Exception as e:
                print_error(f"Failed to run launch.sh: {e}")
                return False
            finally:
                os.chdir(original_dir)

    else:
        print_warning("launch.sh not found - using direct Python execution")

        # Fall back to running mesh_bot.py directly
        bot_script = meshing_path / "mesh_bot.py"
        if not bot_script.exists():
            print_error(f"mesh_bot.py not found at {meshing_path}")
            return False

        # Determine python command
        if venv_path and venv_path.exists():
            python_cmd = str(venv_path / "bin" / "python3")
            print_info(f"Using venv Python: {python_cmd}")
        else:
            python_cmd = "python3"
            print_info("Using system Python")

        if get_yes_no("Start the bot now?", True):
            original_dir = os.getcwd()
            try:
                os.chdir(meshing_path)

                process = subprocess.Popen(
                    [python_cmd, str(bot_script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True
                )

                time.sleep(3)

                if process.poll() is None:
                    print_success(f"Bot started successfully! PID: {process.pid}")
                    return True
                else:
                    stdout, stderr = process.communicate()
                    print_error("Bot failed to start:")
                    if stderr:
                        print(stderr.decode())
                    return False

            except Exception as e:
                print_error(f"Failed to start bot: {e}")
                return False
            finally:
                os.chdir(original_dir)

    return False


def verify_bot_running(meshing_path: Path) -> bool:
    """Verify that the meshing-around bot can run"""
    print_section("Verify Bot")

    bot_script = meshing_path / "mesh_bot.py"
    if not bot_script.exists():
        print_error(f"mesh_bot.py not found at {meshing_path}")
        return False

    # Check if bot is already running
    ret, stdout, _ = run_command(['pgrep', '-f', 'mesh_bot.py'], capture=True)
    if ret == 0 and stdout.strip():
        print_success("Bot is already running!")
        print_info(f"PID(s): {stdout.strip()}")
        return True

    # Test if bot can start (syntax check)
    print_info("Checking bot syntax...")
    ret, stdout, stderr = run_command(
        ['python3', '-m', 'py_compile', str(bot_script)],
        capture=True
    )
    if ret != 0:
        print_error(f"Syntax error in bot: {stderr}")
        return False
    print_success("Bot syntax OK")

    # Check for config file
    config_locations = [
        meshing_path / "config.ini",
        meshing_path / "config.yaml",
        meshing_path / "config.yml"
    ]
    config_found = any(c.exists() for c in config_locations)
    if not config_found:
        print_warning("No config file found in meshing-around directory")
        print_info("Run this configurator and copy config.ini to meshing-around directory")

    # Try to start the bot
    if get_yes_no("Start the bot now?", True):
        print_info("Starting mesh_bot.py...")
        original_dir = os.getcwd()
        try:
            os.chdir(meshing_path)

            # Start in background
            process = subprocess.Popen(
                ['python3', 'mesh_bot.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )

            # Wait a few seconds to see if it crashes
            time.sleep(3)

            if process.poll() is None:
                print_success(f"Bot started successfully! PID: {process.pid}")
                print_info("Bot is running in the background")
                return True
            else:
                stdout, stderr = process.communicate()
                print_error("Bot failed to start:")
                if stderr:
                    print(stderr.decode())
                if stdout:
                    print(stdout.decode())
                return False

        except Exception as e:
            print_error(f"Failed to start bot: {e}")
            return False
        finally:
            os.chdir(original_dir)

    return True


def quick_setup():
    """Quick setup wizard for first-time users with Raspberry Pi support"""
    print_header("Quick Setup Wizard")

    # Detect platform
    pi_detected = is_raspberry_pi()
    bookworm_detected = is_bookworm_or_newer()

    if pi_detected:
        pi_model = get_pi_model()
        print_success(f"Detected: {pi_model}")

    if bookworm_detected:
        print_warning("Raspberry Pi OS Bookworm detected - will configure virtual environment")

    steps = 6 if pi_detected else 5
    print(f"""
This wizard will:
  1. {"Raspberry Pi setup (permissions, venv)" if pi_detected else "Check system requirements"}
  2. Update your system (apt update/upgrade)
  3. Find or clone meshing-around
  4. Install dependencies
  5. Create a basic configuration
  6. Verify the bot can run
""")

    if not get_yes_no("Continue with quick setup?", True):
        return None

    errors = []
    venv_path = None

    # Step 1: Raspberry Pi setup (or system check)
    if pi_detected:
        print_step(1, steps, "Raspberry Pi Setup")
        success, venv_path = raspberry_pi_setup()
        if not success:
            errors.append("Raspberry Pi setup had issues")
    else:
        print_step(1, steps, "System Check")
        show_system_info()

    # Step 2: System update
    print_step(2, steps, "System Update")
    if not system_update():
        errors.append("System update had issues")

    # Step 3: Find/update meshing-around
    print_step(3, steps, "Meshing-Around Setup")
    success, meshing_path = update_meshing_around()
    if not success:
        errors.append("Failed to update meshing-around")

    # Step 4: Install dependencies (with venv support)
    if meshing_path:
        print_step(4, steps, "Install Dependencies")
        if not install_dependencies(meshing_path, venv_path):
            errors.append("Dependency installation had issues")

    # Step 5: Create basic config
    print_step(5, steps, "Create Configuration")
    config = create_basic_config()

    # Step 6: Verify bot
    if meshing_path:
        print_step(6, steps, "Verify Bot")
        if not verify_bot_running(meshing_path):
            errors.append("Bot verification failed")

    # Summary
    print_section("Setup Summary")
    if errors:
        print_warning("Setup completed with some issues:")
        for err in errors:
            print_error(f"  • {err}")
    else:
        print_success("Setup completed successfully!")

    if meshing_path:
        print_info(f"Meshing-around location: {meshing_path}")

        if venv_path:
            print_info(f"Virtual environment: {venv_path}")
            print_info("\nNext steps:")
            print(f"  1. Copy config.ini to {meshing_path}/")
            print(f"  2. source {venv_path}/bin/activate")
            print(f"  3. cd {meshing_path}")
            print("  4. python3 mesh_bot.py")
        else:
            print_info("Next steps:")
            print(f"  1. Copy config.ini to {meshing_path}/")
            print(f"  2. cd {meshing_path}")
            print("  3. python3 mesh_bot.py")

    return config


def create_basic_config() -> configparser.ConfigParser:
    """Create a basic configuration interactively"""
    print_section("Basic Configuration")

    config = configparser.ConfigParser()

    # Initialize all sections
    sections = [
        'interface', 'general', 'emergencyHandler', 'proximityAlert',
        'altitudeAlert', 'weatherAlert', 'ipawsAlert', 'volcanoAlert',
        'noisyNodeAlert', 'batteryAlert', 'newNodeAlert', 'snrAlert',
        'disconnectAlert', 'customAlert', 'alertGlobal', 'smtp', 'sms'
    ]
    for section in sections:
        config.add_section(section)

    # Basic interface config
    configure_interface(config)

    # Basic general config
    configure_general(config)

    # Enable emergency alerts by default
    config['emergencyHandler']['enabled'] = 'True'
    config['emergencyHandler']['emergency_keywords'] = 'emergency,911,112,999,sos,help,mayday'
    config['emergencyHandler']['alert_channel'] = '2'
    print_success("Emergency alerts enabled with default keywords")

    # Enable new node welcomes
    config['newNodeAlert']['enabled'] = 'True'
    config['newNodeAlert']['welcome_message'] = 'Welcome to the mesh!'
    print_success("New node welcomes enabled")

    # Global settings
    config['alertGlobal']['global_enabled'] = 'True'

    return config


def show_system_info():
    """Display system information including Raspberry Pi details"""
    print_section("System Information")

    # Raspberry Pi detection
    if is_raspberry_pi():
        pi_model = get_pi_model()
        print_success(f"Raspberry Pi: {pi_model}")
    else:
        print_info("Platform: Standard Linux/x86")

    # OS Info
    os_name, os_codename = get_os_info()
    print(f"OS: {os_name}")

    if is_bookworm_or_newer():
        print_warning(f"  Codename: {os_codename} (PEP 668 applies)")
    else:
        print(f"  Codename: {os_codename}")

    # Kernel
    ret, stdout, _ = run_command(['uname', '-r'], capture=True)
    if ret == 0:
        print(f"Kernel: {stdout.strip()}")

    # Python version
    print(f"Python: {sys.version.split()[0]}")

    # PEP 668 status
    if check_pep668_environment():
        print_warning("PEP 668: Externally managed environment (use venv or --break-system-packages)")
    else:
        print_success("PEP 668: Not in effect (system pip works normally)")

    # Check for meshtastic library
    try:
        import meshtastic
        print(f"Meshtastic library: {meshtastic.__version__ if hasattr(meshtastic, '__version__') else 'installed'}")
    except ImportError:
        print_warning("Meshtastic library: NOT INSTALLED")
        print_info("  Install with: pip3 install meshtastic")

    # User groups
    in_dialout, in_gpio = check_user_groups()
    print(f"\nUser groups:")
    if in_dialout:
        print_success("  dialout: YES (serial port access)")
    else:
        print_warning("  dialout: NO (run 'sudo usermod -a -G dialout $USER')")

    if is_raspberry_pi() and in_gpio:
        print_success("  gpio: YES")

    # Check for serial ports (including Pi-specific)
    print("\nSerial ports:")
    ports = get_serial_ports()
    if ports:
        for port in ports:
            print_success(f"  {port}")
    else:
        print_warning("  No serial ports found - connect your Meshtastic device")

    # Check for meshing-around
    meshing_path = find_meshing_around()
    if meshing_path:
        print(f"\nMeshing-around: {meshing_path}")
        # Check for config
        if (meshing_path / "config.ini").exists():
            print_success("  config.ini: Found")
        else:
            print_warning("  config.ini: Not found")
    else:
        print_warning("\nMeshing-around: NOT FOUND")

    # Check for virtual environment
    venv_path = Path.home() / "meshing-around-venv"
    if venv_path.exists():
        print_success(f"\nVirtual environment: {venv_path}")
    elif is_bookworm_or_newer():
        print_warning(f"\nVirtual environment: Not found (recommended for Bookworm)")

    # Disk space
    ret, stdout, _ = run_command(['df', '-h', '/'], capture=True)
    if ret == 0:
        print(f"\nDisk space:\n{stdout}")

    # Memory (useful for Pi)
    if is_raspberry_pi():
        ret, stdout, _ = run_command(['free', '-h'], capture=True)
        if ret == 0:
            print(f"Memory:\n{stdout}")

def load_config(config_file: str) -> configparser.ConfigParser:
    """Load existing config or create new one"""
    config = configparser.ConfigParser()
    
    if os.path.exists(config_file):
        print_success(f"Loading existing config from {config_file}")
        config.read(config_file)
    else:
        print_warning(f"No existing config found, creating new configuration")
        # Initialize sections
        sections = [
            'interface', 'general', 'emergencyHandler', 'proximityAlert',
            'altitudeAlert', 'weatherAlert', 'ipawsAlert', 'volcanoAlert',
            'noisyNodeAlert', 'batteryAlert', 'newNodeAlert', 'snrAlert',
            'disconnectAlert', 'customAlert', 'alertGlobal', 'smtp', 'sms'
        ]
        for section in sections:
            if not config.has_section(section):
                config.add_section(section)
    
    return config

def save_config(config: configparser.ConfigParser, config_file: str):
    """Save configuration to file"""
    try:
        with open(config_file, 'w') as f:
            config.write(f)
        print_success(f"\nConfiguration saved to {config_file}")
    except OSError as e:
        print_error(f"Failed to save config: {e}")
        sys.exit(1)

def main_menu():
    """Display main menu and handle user selection"""
    # Run startup checks (includes system update)
    startup_system_check()

    print("\nThis tool will help you configure your Meshtastic bot")
    print("You can configure alert settings, connection parameters, and more\n")

    # Show startup menu
    print_section("Start Menu")
    print("1. Quick Setup (recommended for first-time users)")
    print("2. Install Meshing-Around (fresh install)")
    print("3. Advanced Configuration")
    print("4. System Maintenance Only")
    if is_raspberry_pi():
        print("5. Raspberry Pi Setup")
        print("6. Show System Info")
        print("7. Exit")
        max_choice = "7"
    else:
        print("5. Show System Info")
        print("6. Exit")
        max_choice = "6"

    start_choice = get_input(f"\nSelect option (1-{max_choice})", "1")

    if start_choice == "1":
        config = quick_setup()
        if config:
            config_file = get_input("Save config to", "config.ini")
            save_config(config, config_file)
        return
    elif start_choice == "2":
        success, meshing_path, venv_path = install_meshing_around()
        if success and meshing_path:
            if get_yes_no("\nConfigure the bot now?", True):
                config = create_basic_config()
                config_file = str(meshing_path / "config.ini")
                save_config(config, config_file)
                print_success(f"Config saved to {config_file}")
        return
    elif start_choice == "4":
        system_maintenance_menu()
        return
    elif start_choice == "5" and is_raspberry_pi():
        raspberry_pi_setup()
        if get_yes_no("\nContinue to configuration?", True):
            pass
        else:
            return
    elif (start_choice == "5" and not is_raspberry_pi()) or (start_choice == "6" and is_raspberry_pi()):
        show_system_info()
        if get_yes_no("\nContinue to configuration?", True):
            pass
        else:
            return
    elif (start_choice == "6" and not is_raspberry_pi()) or (start_choice == "7" and is_raspberry_pi()):
        print_success("Goodbye!")
        return

    # Determine config file location
    default_config = "config.ini"
    config_file = get_input(f"Config file path", default_config)

    # Load or create config
    config = load_config(config_file)

    # Track meshing-around path
    meshing_path = find_meshing_around()

    # Track virtual environment path
    venv_path = Path.home() / "meshing-around-venv"
    if not venv_path.exists():
        venv_path = None

    # Configuration wizard
    while True:
        print_section("Configuration Menu")
        print(f"{Colors.BOLD}--- Alert Configuration ---{Colors.ENDC}")
        print("1.  Interface Settings (Serial/TCP/BLE)")
        print("2.  General Settings (Bot name, admins)")
        print("3.  Emergency Alerts")
        print("4.  Proximity Alerts")
        print("5.  Altitude Alerts")
        print("6.  Weather Alerts")
        print("7.  Battery Alerts")
        print("8.  Noisy Node Detection")
        print("9.  New Node Welcomes")
        print("10. Email/SMS Settings")
        print("11. Global Alert Settings")
        print(f"\n{Colors.BOLD}--- System Maintenance ---{Colors.ENDC}")
        print("12. System Update (apt update/upgrade)")
        print("13. Install Meshing-Around (fresh install)")
        print("14. Update Meshing-Around (git pull)")
        print("15. Install Dependencies")
        print("16. Run install.sh (use meshing-around's installer)")
        print("17. Verify Bot Running")
        print("18. Launch Bot (using launch.sh if available)")
        print("19. Show System Info")
        if is_raspberry_pi():
            print("20. Raspberry Pi Setup")
        print(f"\n{Colors.BOLD}--- Save & Exit ---{Colors.ENDC}")
        print("21. Save and Exit")
        print("22. Save, Deploy & Start Bot")
        print("23. Exit without Saving")

        choice = get_input("\nSelect option (1-23)", "21")

        if choice == "1":
            configure_interface(config)
        elif choice == "2":
            configure_general(config)
        elif choice == "3":
            configure_emergency_alerts(config)
        elif choice == "4":
            configure_proximity_alerts(config)
        elif choice == "5":
            configure_altitude_alerts(config)
        elif choice == "6":
            configure_weather_alerts(config)
        elif choice == "7":
            configure_battery_alerts(config)
        elif choice == "8":
            configure_noisy_node_alerts(config)
        elif choice == "9":
            configure_new_node_alerts(config)
        elif choice == "10":
            configure_email_sms(config)
        elif choice == "11":
            configure_global_settings(config)
        elif choice == "12":
            system_update()
        elif choice == "13":
            success, meshing_path, venv_path = install_meshing_around()
        elif choice == "14":
            success, meshing_path = update_meshing_around(meshing_path)
        elif choice == "15":
            if meshing_path:
                install_dependencies(meshing_path, venv_path)
            else:
                print_error("Meshing-around not found. Run option 13 or 14 first.")
        elif choice == "16":
            if meshing_path:
                run_install_script(meshing_path)
            else:
                print_error("Meshing-around not found. Run option 13 or 14 first.")
        elif choice == "17":
            if meshing_path:
                verify_bot_running(meshing_path)
            else:
                print_error("Meshing-around not found. Run option 13 or 14 first.")
        elif choice == "18":
            if meshing_path:
                run_launch_script(meshing_path, venv_path)
            else:
                print_error("Meshing-around not found. Run option 13 or 14 first.")
        elif choice == "19":
            show_system_info()
        elif choice == "20" and is_raspberry_pi():
            _, venv_path = raspberry_pi_setup()
        elif choice == "21":
            save_config(config, config_file)
            print_success("\nConfiguration complete!")
            if meshing_path:
                print_info(f"Copy config to: {meshing_path}/config.ini")
            if venv_path:
                print_info(f"Activate venv: source {venv_path}/bin/activate")
            print(f"\nRun the bot with: python3 mesh_bot.py")
            break
        elif choice == "22":
            save_config(config, config_file)
            if meshing_path:
                deploy_and_start(config_file, meshing_path)
            else:
                print_error("Meshing-around not found. Configure path first.")
            break
        elif choice == "23":
            if get_yes_no("Exit without saving changes?", False):
                print_warning("Exiting without saving")
                break
        else:
            print_error("Invalid choice, please try again")


def system_maintenance_menu():
    """Menu for system maintenance only with Raspberry Pi support"""
    print_header("System Maintenance")

    meshing_path = find_meshing_around()
    venv_path = Path.home() / "meshing-around-venv"
    if not venv_path.exists():
        venv_path = None

    while True:
        print_section("Maintenance Menu")
        print("1. System Update (apt update/upgrade)")
        print("2. Install Meshing-Around (fresh install)")
        print("3. Update Meshing-Around (git pull)")
        print("4. Install Dependencies")
        print("5. Run install.sh (meshing-around's installer)")
        print("6. Launch Bot (using launch.sh)")
        print("7. Verify Bot Running")
        print("8. Show System Info")
        if is_raspberry_pi():
            print("9. Raspberry Pi Setup")
            print("10. Run All Maintenance")
            print("11. Back to Main Menu")
            max_opt = "11"
        else:
            print("9. Run All Maintenance")
            print("10. Back to Main Menu")
            max_opt = "10"

        choice = get_input(f"\nSelect option (1-{max_opt})", max_opt)

        if choice == "1":
            system_update()
        elif choice == "2":
            success, meshing_path, venv_path = install_meshing_around()
        elif choice == "3":
            success, meshing_path = update_meshing_around(meshing_path)
        elif choice == "4":
            if meshing_path:
                install_dependencies(meshing_path, venv_path)
            else:
                print_error("Meshing-around not found. Run option 2 or 3 first.")
        elif choice == "5":
            if meshing_path:
                run_install_script(meshing_path)
            else:
                print_error("Meshing-around not found. Run option 2 or 3 first.")
        elif choice == "6":
            if meshing_path:
                run_launch_script(meshing_path, venv_path)
            else:
                print_error("Meshing-around not found. Run option 2 or 3 first.")
        elif choice == "7":
            if meshing_path:
                verify_bot_running(meshing_path)
            else:
                print_error("Meshing-around not found. Run option 2 or 3 first.")
        elif choice == "8":
            show_system_info()
        elif choice == "9" and is_raspberry_pi():
            _, venv_path = raspberry_pi_setup()
        elif (choice == "9" and not is_raspberry_pi()) or (choice == "10" and is_raspberry_pi()):
            # Run all maintenance
            print_section("Running All Maintenance")
            if is_raspberry_pi():
                print_step(1, 5, "Raspberry Pi Setup")
                _, venv_path = raspberry_pi_setup()
            print_step(2 if is_raspberry_pi() else 1, 5 if is_raspberry_pi() else 4, "System Update")
            system_update()
            print_step(3 if is_raspberry_pi() else 2, 5 if is_raspberry_pi() else 4, "Update Meshing-Around")
            success, meshing_path = update_meshing_around(meshing_path)
            if meshing_path:
                print_step(4 if is_raspberry_pi() else 3, 5 if is_raspberry_pi() else 4, "Install Dependencies")
                install_dependencies(meshing_path, venv_path)
                print_step(5 if is_raspberry_pi() else 4, 5 if is_raspberry_pi() else 4, "Verify Bot")
                verify_bot_running(meshing_path)
            print_success("Maintenance complete!")
        elif (choice == "10" and not is_raspberry_pi()) or (choice == "11" and is_raspberry_pi()):
            break
        else:
            print_error("Invalid choice")


def deploy_and_start(config_file: str, meshing_path: Path):
    """Deploy config and start the bot"""
    print_section("Deploy and Start")

    # Copy config to meshing-around directory
    dest_config = meshing_path / "config.ini"
    try:
        shutil.copy(config_file, dest_config)
        print_success(f"Config deployed to {dest_config}")
    except OSError as e:
        print_error(f"Failed to copy config: {e}")
        return

    # Start the bot
    verify_bot_running(meshing_path)

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print_warning("\n\nConfiguration cancelled by user")
        sys.exit(0)
    except Exception as e:
        print_error(f"\nAn error occurred: {e}")
        sys.exit(1)

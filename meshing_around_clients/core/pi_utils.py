"""
Raspberry Pi utilities for MeshForge.

Provides:
- Pi detection and model identification
- Serial port detection and configuration
- PEP 668 virtual environment management
- User group management (dialout, gpio)
- raspi-config integration

Extracted from configure_bot.py for reusability across MeshForge.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PiInfo:
    """Raspberry Pi system information."""

    is_pi: bool = False
    model: str = "Unknown"
    os_name: str = "Unknown"
    os_codename: str = "Unknown"
    is_bookworm_or_newer: bool = False
    pep668_active: bool = False
    python_version: str = ""
    in_dialout: bool = False
    in_gpio: bool = False


@dataclass
class SerialPortInfo:
    """Serial port information."""

    port: str
    is_usb: bool = False
    is_pi_native: bool = False
    description: str = ""


# =============================================================================
# Pi Detection
# =============================================================================


def is_raspberry_pi() -> bool:
    """Detect if running on a Raspberry Pi."""
    # Check cpuinfo
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()
            if "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo:
                return True
    except (FileNotFoundError, PermissionError, IOError):
        pass

    # Check device tree model
    if os.path.exists("/sys/firmware/devicetree/base/model"):
        try:
            with open("/sys/firmware/devicetree/base/model", "r") as f:
                if "Raspberry Pi" in f.read():
                    return True
        except (FileNotFoundError, PermissionError, IOError):
            pass

    return False


def get_pi_model() -> str:
    """Get Raspberry Pi model information."""
    try:
        with open("/sys/firmware/devicetree/base/model", "r") as f:
            return f.read().strip().rstrip("\x00")
    except (FileNotFoundError, PermissionError, IOError):
        return "Unknown"


def get_os_info() -> Tuple[str, str]:
    """Get OS name and version codename.

    Returns:
        Tuple of (pretty_name, codename)
    """
    os_name = "Unknown"
    os_codename = "Unknown"

    try:
        with open("/etc/os-release", "r") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=")[1].strip().strip('"')
                elif line.startswith("VERSION_CODENAME="):
                    os_codename = line.split("=")[1].strip().strip('"')
    except (FileNotFoundError, PermissionError, IOError):
        pass

    return os_name, os_codename


def is_bookworm_or_newer() -> bool:
    """Check if running Debian Bookworm (12) or newer.

    Bookworm introduced PEP 668 which requires virtual environments
    or --break-system-packages for pip installs.
    """
    _, codename = get_os_info()
    # Bookworm and newer codenames
    new_codenames = ["bookworm", "trixie", "forky", "sid", "noble"]
    return codename.lower() in new_codenames


def check_pep668_environment() -> bool:
    """Check if PEP 668 externally managed environment is in effect.

    PEP 668 prevents pip from installing packages system-wide
    on certain Linux distributions (Debian Bookworm+, Ubuntu 23.04+).
    """
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    managed_file = Path(f"/usr/lib/python{python_version}/EXTERNALLY-MANAGED")
    return managed_file.exists()


def get_pi_info() -> PiInfo:
    """Get comprehensive Raspberry Pi system information."""
    is_pi = is_raspberry_pi()
    os_name, os_codename = get_os_info()
    in_dialout, in_gpio = check_user_groups()

    return PiInfo(
        is_pi=is_pi,
        model=get_pi_model() if is_pi else "Not a Pi",
        os_name=os_name,
        os_codename=os_codename,
        is_bookworm_or_newer=is_bookworm_or_newer(),
        pep668_active=check_pep668_environment(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        in_dialout=in_dialout,
        in_gpio=in_gpio,
    )


# =============================================================================
# Serial Port Detection
# =============================================================================


def get_serial_ports() -> List[SerialPortInfo]:
    """Get available serial ports including Pi-specific ones.

    Returns:
        List of SerialPortInfo objects for each detected port
    """
    ports = []
    seen = set()

    # Common USB serial ports
    usb_patterns = ["/dev/ttyUSB*", "/dev/ttyACM*"]
    for pattern in usb_patterns:
        try:
            result = subprocess.run(["ls", pattern], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                for port in result.stdout.strip().split("\n"):
                    if port and port not in seen:
                        seen.add(port)
                        ports.append(
                            SerialPortInfo(port=port, is_usb=True, is_pi_native=False, description="USB Serial")
                        )
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass

    # Pi-specific serial ports
    pi_ports = [
        ("/dev/ttyAMA0", "Pi Primary UART"),
        ("/dev/serial0", "Pi Serial0 (Primary)"),
        ("/dev/serial1", "Pi Serial1 (Secondary)"),
        ("/dev/ttyS0", "Pi Mini UART"),
    ]
    for port, desc in pi_ports:
        if os.path.exists(port) and port not in seen:
            seen.add(port)
            ports.append(SerialPortInfo(port=port, is_usb=False, is_pi_native=True, description=desc))

    return ports


def get_serial_port_list() -> List[str]:
    """Get simple list of serial port paths.

    Convenience function for backward compatibility.
    """
    return [p.port for p in get_serial_ports()]


# =============================================================================
# User Group Management
# =============================================================================


def check_user_groups() -> Tuple[bool, bool]:
    """Check if current user is in dialout and gpio groups.

    Returns:
        Tuple of (in_dialout, in_gpio)
    """
    try:
        result = subprocess.run(["groups"], capture_output=True, text=True, timeout=5)
        groups = result.stdout.lower()
        in_dialout = "dialout" in groups
        in_gpio = "gpio" in groups
        return in_dialout, in_gpio
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False, False


def add_user_to_dialout(username: Optional[str] = None) -> Tuple[bool, str]:
    """Add user to dialout group for serial port access.

    Args:
        username: Username to add. Uses current user if None.

    Returns:
        Tuple of (success, message)
    """
    if username is None:
        username = os.environ.get("USER", os.environ.get("LOGNAME", ""))

    if not username:
        return False, "Could not determine username"

    in_dialout, _ = check_user_groups()
    if in_dialout:
        return True, f"User {username} already in dialout group"

    try:
        result = subprocess.run(
            ["sudo", "usermod", "-a", "-G", "dialout", username], capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True, f"Added {username} to dialout group. Log out and back in for effect."
        else:
            return False, f"Failed to add to dialout: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except subprocess.SubprocessError as e:
        return False, f"Command failed: {e}"


# =============================================================================
# Virtual Environment Management
# =============================================================================


def get_default_venv_path() -> Path:
    """Get default virtual environment path for MeshForge."""
    return Path.home() / "meshing-around-venv"


def check_venv_exists(venv_path: Optional[Path] = None) -> bool:
    """Check if a virtual environment exists at the given path."""
    if venv_path is None:
        venv_path = get_default_venv_path()
    return venv_path.exists() and (venv_path / "bin" / "python3").exists()


def create_venv(venv_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Create a Python virtual environment.

    Args:
        venv_path: Path for the venv. Uses default if None.

    Returns:
        Tuple of (success, message)
    """
    if venv_path is None:
        venv_path = get_default_venv_path()

    if check_venv_exists(venv_path):
        return True, f"Virtual environment already exists at {venv_path}"

    # Check if python3-venv is installed
    try:
        result = subprocess.run(["dpkg", "-l", "python3-venv"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            # Try to install python3-venv
            install_result = subprocess.run(
                ["sudo", "apt", "install", "-y", "python3-venv"], capture_output=True, text=True, timeout=120
            )
            if install_result.returncode != 0:
                return False, f"Failed to install python3-venv: {install_result.stderr}"
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        return False, f"Failed to check/install python3-venv: {e}"

    # Create the virtual environment
    try:
        result = subprocess.run(["python3", "-m", "venv", str(venv_path)], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return True, f"Virtual environment created at {venv_path}"
        else:
            return False, f"Failed to create venv: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "Venv creation timed out"
    except subprocess.SubprocessError as e:
        return False, f"Venv creation failed: {e}"


def get_pip_command(venv_path: Optional[Path] = None) -> List[str]:
    """Get the appropriate pip command based on environment.

    Args:
        venv_path: Path to virtual environment. Uses system pip if None.

    Returns:
        List of command components for pip
    """
    if venv_path and venv_path.exists():
        pip_path = venv_path / "bin" / "pip3"
        if pip_path.exists():
            return [str(pip_path)]

    return ["pip3"]


def get_pip_install_flags() -> List[str]:
    """Get extra flags needed for pip install.

    Returns --break-system-packages if PEP 668 is in effect.
    """
    if check_pep668_environment():
        return ["--break-system-packages"]
    return []


def get_python_command(venv_path: Optional[Path] = None) -> str:
    """Get the Python interpreter command.

    Args:
        venv_path: Path to virtual environment. Uses system python if None.

    Returns:
        Path to Python interpreter
    """
    if venv_path and venv_path.exists():
        python_path = venv_path / "bin" / "python3"
        if python_path.exists():
            return str(python_path)

    return "python3"


# =============================================================================
# Pi Config.txt Management
# =============================================================================


def get_pi_config_path() -> Path:
    """Get the correct config.txt path for the current Pi OS.

    Bookworm and newer use /boot/firmware/config.txt.
    Legacy uses /boot/config.txt.
    """
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
    """Check if serial port is enabled in config.txt.

    Returns:
        Tuple of (uart_enabled, console_on_serial)
    """
    config_path = get_pi_config_path()

    if not config_path.exists():
        return False, False

    try:
        with open(config_path, "r") as f:
            content = f.read()

        uart_enabled = "enable_uart=1" in content

        # Check if console is on serial (in cmdline.txt)
        cmdline_path = config_path.parent / "cmdline.txt"
        console_enabled = False
        if cmdline_path.exists():
            with open(cmdline_path, "r") as f:
                cmdline = f.read()
                console_enabled = "console=serial" in cmdline or "console=ttyAMA" in cmdline

        return uart_enabled, console_enabled
    except (FileNotFoundError, PermissionError, IOError):
        return False, False


def configure_serial_via_raspi_config(enable_uart: bool = True, disable_console: bool = True) -> Tuple[bool, str]:
    """Configure serial port using raspi-config (non-interactive).

    Args:
        enable_uart: Whether to enable UART
        disable_console: Whether to disable serial console

    Returns:
        Tuple of (success, message)
    """
    if not is_raspberry_pi():
        return True, "Not a Raspberry Pi, skipping"

    # Check if raspi-config exists
    try:
        result = subprocess.run(["which", "raspi-config"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False, "raspi-config not found"
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False, "Could not check for raspi-config"

    messages = []

    if enable_uart:
        # do_serial_hw 0 = enable, 1 = disable (yes, it's backwards)
        try:
            result = subprocess.run(
                ["sudo", "raspi-config", "nonint", "do_serial_hw", "0"], capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                messages.append("UART enabled")
            else:
                return False, f"Failed to enable UART: {result.stderr}"
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            return False, f"Failed to enable UART: {e}"

    if disable_console:
        try:
            result = subprocess.run(
                ["sudo", "raspi-config", "nonint", "do_serial_cons", "1"], capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                messages.append("Serial console disabled")
            else:
                return False, f"Failed to disable serial console: {result.stderr}"
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            return False, f"Failed to disable serial console: {e}"

    return True, "; ".join(messages) + ". Reboot required."


def check_i2c_spi_enabled() -> Tuple[bool, bool]:
    """Check if I2C and SPI are enabled.

    Returns:
        Tuple of (i2c_enabled, spi_enabled)
    """
    if not is_raspberry_pi():
        return False, False

    try:
        # Check I2C
        i2c_result = subprocess.run(
            ["sudo", "raspi-config", "nonint", "get_i2c"], capture_output=True, text=True, timeout=10
        )
        i2c_enabled = i2c_result.returncode == 0 and i2c_result.stdout.strip() == "0"

        # Check SPI
        spi_result = subprocess.run(
            ["sudo", "raspi-config", "nonint", "get_spi"], capture_output=True, text=True, timeout=10
        )
        spi_enabled = spi_result.returncode == 0 and spi_result.stdout.strip() == "0"

        return i2c_enabled, spi_enabled
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False, False


# =============================================================================
# Pi Zero 2W Specific
# =============================================================================


def is_pi_zero() -> bool:
    """Check if running on a Pi Zero (any variant)."""
    model = get_pi_model().lower()
    return "zero" in model


def is_pi_zero_2w() -> bool:
    """Check if running on a Pi Zero 2W specifically."""
    model = get_pi_model().lower()
    return "zero 2" in model


def get_recommended_connection_mode() -> str:
    """Get recommended connection mode for the current Pi.

    Pi Zero 2W is recommended for MQTT mode (no direct serial).
    Other Pis can use serial.
    """
    if is_pi_zero():
        return "mqtt"  # MQTT recommended for Pi Zero due to limited resources
    elif is_raspberry_pi():
        return "serial"
    else:
        return "serial"

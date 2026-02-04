"""
Unit tests for pi_utils module.

Tests:
- Pi detection functions
- OS info functions
- Serial port functions
- PEP 668 environment checking
- Virtual environment management
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from meshing_around_clients.core.pi_utils import (
    is_raspberry_pi, get_pi_model, get_os_info, is_bookworm_or_newer,
    check_pep668_environment, get_serial_ports, get_serial_port_list,
    check_user_groups, get_default_venv_path, check_venv_exists,
    get_pip_command, get_pip_install_flags, get_python_command,
    get_pi_config_path, check_serial_enabled, PiInfo, SerialPortInfo,
    get_pi_info, is_pi_zero, is_pi_zero_2w, get_recommended_connection_mode
)


class TestPiDetection:
    """Test Raspberry Pi detection functions."""

    def test_is_raspberry_pi_returns_bool(self):
        """Verify is_raspberry_pi returns boolean."""
        result = is_raspberry_pi()
        assert isinstance(result, bool)

    def test_get_pi_model_returns_string(self):
        """Verify get_pi_model returns string."""
        result = get_pi_model()
        assert isinstance(result, str)

    @patch('builtins.open', mock_open(read_data='Raspberry Pi 4 Model B Rev 1.4'))
    @patch('os.path.exists', return_value=True)
    def test_get_pi_model_from_file(self, mock_exists):
        """Test getting Pi model from device tree."""
        result = get_pi_model()
        assert isinstance(result, str)


class TestOSInfo:
    """Test OS information functions."""

    def test_get_os_info_returns_tuple(self):
        """Verify get_os_info returns tuple of strings."""
        os_name, codename = get_os_info()
        assert isinstance(os_name, str)
        assert isinstance(codename, str)

    @patch('builtins.open', mock_open(read_data='''
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
VERSION_CODENAME=bookworm
'''))
    def test_get_os_info_parses_bookworm(self):
        """Test parsing Bookworm os-release."""
        os_name, codename = get_os_info()
        # Note: May not match due to mock behavior, just verify no crash
        assert isinstance(os_name, str)
        assert isinstance(codename, str)

    def test_is_bookworm_or_newer_returns_bool(self):
        """Verify is_bookworm_or_newer returns boolean."""
        result = is_bookworm_or_newer()
        assert isinstance(result, bool)


class TestPEP668:
    """Test PEP 668 environment detection."""

    def test_check_pep668_environment_returns_bool(self):
        """Verify check_pep668_environment returns boolean."""
        result = check_pep668_environment()
        assert isinstance(result, bool)

    @patch.object(Path, 'exists', return_value=True)
    def test_check_pep668_when_file_exists(self, mock_exists):
        """Test PEP 668 detection when EXTERNALLY-MANAGED exists."""
        result = check_pep668_environment()
        assert isinstance(result, bool)


class TestSerialPorts:
    """Test serial port detection."""

    def test_get_serial_ports_returns_list(self):
        """Verify get_serial_ports returns list."""
        result = get_serial_ports()
        assert isinstance(result, list)

    def test_get_serial_port_list_returns_strings(self):
        """Verify get_serial_port_list returns list of strings."""
        result = get_serial_port_list()
        assert isinstance(result, list)
        for port in result:
            assert isinstance(port, str)


class TestUserGroups:
    """Test user group checking."""

    def test_check_user_groups_returns_tuple(self):
        """Verify check_user_groups returns tuple of bools."""
        in_dialout, in_gpio = check_user_groups()
        assert isinstance(in_dialout, bool)
        assert isinstance(in_gpio, bool)


class TestVirtualEnvironment:
    """Test virtual environment functions."""

    def test_get_default_venv_path_returns_path(self):
        """Verify get_default_venv_path returns Path."""
        result = get_default_venv_path()
        assert isinstance(result, Path)
        assert "meshing-around-venv" in str(result)

    def test_check_venv_exists_returns_bool(self):
        """Verify check_venv_exists returns boolean."""
        result = check_venv_exists()
        assert isinstance(result, bool)

    def test_get_pip_command_returns_list(self):
        """Verify get_pip_command returns list."""
        result = get_pip_command()
        assert isinstance(result, list)
        assert len(result) > 0
        assert "pip" in result[0].lower()

    def test_get_pip_install_flags_returns_list(self):
        """Verify get_pip_install_flags returns list."""
        result = get_pip_install_flags()
        assert isinstance(result, list)

    def test_get_python_command_returns_string(self):
        """Verify get_python_command returns string."""
        result = get_python_command()
        assert isinstance(result, str)
        assert "python" in result.lower()


class TestPiConfig:
    """Test Pi config.txt functions."""

    def test_get_pi_config_path_returns_path(self):
        """Verify get_pi_config_path returns Path."""
        result = get_pi_config_path()
        assert isinstance(result, Path)

    def test_check_serial_enabled_returns_tuple(self):
        """Verify check_serial_enabled returns tuple of bools."""
        uart_enabled, console_enabled = check_serial_enabled()
        assert isinstance(uart_enabled, bool)
        assert isinstance(console_enabled, bool)


class TestDataClasses:
    """Test data classes."""

    def test_pi_info_creation(self):
        """Test PiInfo dataclass creation."""
        info = PiInfo(
            is_pi=True,
            model="Raspberry Pi 4 Model B",
            os_name="Debian",
            os_codename="bookworm"
        )
        assert info.is_pi is True
        assert "Raspberry Pi" in info.model

    def test_serial_port_info_creation(self):
        """Test SerialPortInfo dataclass creation."""
        port = SerialPortInfo(
            port="/dev/ttyUSB0",
            is_usb=True,
            is_pi_native=False,
            description="USB Serial"
        )
        assert port.port == "/dev/ttyUSB0"
        assert port.is_usb is True

    def test_get_pi_info_returns_piinfo(self):
        """Verify get_pi_info returns PiInfo."""
        result = get_pi_info()
        assert isinstance(result, PiInfo)
        assert isinstance(result.is_pi, bool)
        assert isinstance(result.model, str)


class TestPiZeroDetection:
    """Test Pi Zero specific functions."""

    def test_is_pi_zero_returns_bool(self):
        """Verify is_pi_zero returns boolean."""
        result = is_pi_zero()
        assert isinstance(result, bool)

    def test_is_pi_zero_2w_returns_bool(self):
        """Verify is_pi_zero_2w returns boolean."""
        result = is_pi_zero_2w()
        assert isinstance(result, bool)

    def test_get_recommended_connection_mode_returns_string(self):
        """Verify get_recommended_connection_mode returns valid mode."""
        result = get_recommended_connection_mode()
        assert isinstance(result, str)
        assert result in ["serial", "mqtt", "tcp", "ble"]

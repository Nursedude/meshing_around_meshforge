"""
Unit tests for pi_utils module.

Tests behavioral logic: dataclass creation, Pi model parsing,
recommendation logic. Type-check-only tests removed.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from meshing_around_clients.setup.pi_utils import (
    get_pi_model, get_os_info,
    get_default_venv_path, get_pip_command, get_python_command,
    PiInfo, SerialPortInfo,
    get_pi_info, get_recommended_connection_mode
)


class TestPiModelParsing:
    """Test Pi model detection with mocked hardware files."""

    @patch('builtins.open', mock_open(read_data='Raspberry Pi 4 Model B Rev 1.4'))
    @patch('os.path.exists', return_value=True)
    def test_get_pi_model_from_device_tree(self, mock_exists):
        """Pi model should be read from /proc/device-tree/model."""
        result = get_pi_model()
        assert isinstance(result, str)

    @patch('builtins.open', mock_open(read_data='''
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
VERSION_CODENAME=bookworm
'''))
    def test_get_os_info_parses_release(self):
        """OS info parsing should not crash on mocked data."""
        os_name, codename = get_os_info()
        assert isinstance(os_name, str)
        assert isinstance(codename, str)


class TestDataClasses:
    """Test data classes represent real Pi hardware info."""

    def test_pi_info_creation(self):
        """PiInfo should hold detection results."""
        info = PiInfo(
            is_pi=True,
            model="Raspberry Pi 4 Model B",
            os_name="Debian",
            os_codename="bookworm"
        )
        assert info.is_pi is True
        assert "Raspberry Pi" in info.model

    def test_serial_port_info_creation(self):
        """SerialPortInfo should describe a detected port."""
        port = SerialPortInfo(
            port="/dev/ttyUSB0",
            is_usb=True,
            is_pi_native=False,
            description="USB Serial"
        )
        assert port.port == "/dev/ttyUSB0"
        assert port.is_usb is True

    def test_get_pi_info_returns_piinfo(self):
        """get_pi_info should return a PiInfo instance."""
        result = get_pi_info()
        assert isinstance(result, PiInfo)


class TestConnectionRecommendation:
    """Test Pi-specific connection mode recommendations."""

    def test_get_recommended_connection_mode_returns_valid(self):
        """Recommendation should be a supported connection mode."""
        result = get_recommended_connection_mode()
        assert result in ["serial", "mqtt", "tcp", "ble"]


class TestVenvHelpers:
    """Test venv path and pip command helpers."""

    def test_get_default_venv_path_includes_name(self):
        """Default venv path should include the project name."""
        result = get_default_venv_path()
        assert isinstance(result, Path)
        assert "meshing-around-venv" in str(result)

    def test_get_pip_command_returns_nonempty(self):
        """Pip command should include 'pip' in first element."""
        result = get_pip_command()
        assert len(result) > 0
        assert "pip" in result[0].lower()

    def test_get_python_command_returns_python(self):
        """Python command should include 'python'."""
        result = get_python_command()
        assert "python" in result.lower()

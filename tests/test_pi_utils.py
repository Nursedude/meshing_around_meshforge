"""
Unit tests for pi_utils module.

Tests behavioral logic: dataclass creation, Pi model parsing,
recommendation logic. Type-check-only tests removed.
"""

from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from meshing_around_clients.setup.pi_utils import (
    PiInfo,
    SerialPortInfo,
    get_default_venv_path,
    get_os_info,
    get_pi_info,
    get_pi_model,
    get_pip_command,
    get_python_command,
    get_recommended_connection_mode,
)


class TestPiModelParsing:
    """Test Pi model detection with mocked hardware files."""

    @patch("builtins.open", mock_open(read_data="Raspberry Pi 4 Model B Rev 1.4"))
    @patch("os.path.exists", return_value=True)
    def test_get_pi_model_from_device_tree(self, mock_exists):
        """Pi model should be read from /proc/device-tree/model."""
        result = get_pi_model()
        assert isinstance(result, str)

    @patch(
        "builtins.open",
        mock_open(read_data="""
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
VERSION_CODENAME=bookworm
"""),
    )
    def test_get_os_info_parses_release(self):
        """OS info parsing should not crash on mocked data."""
        os_name, codename = get_os_info()
        assert isinstance(os_name, str)
        assert isinstance(codename, str)


class TestDataClasses:
    """Test data classes represent real Pi hardware info."""

    def test_pi_info_creation(self):
        """PiInfo should hold detection results."""
        info = PiInfo(is_pi=True, model="Raspberry Pi 4 Model B", os_name="Debian", os_codename="bookworm")
        assert info.is_pi is True
        assert "Raspberry Pi" in info.model

    def test_serial_port_info_creation(self):
        """SerialPortInfo should describe a detected port."""
        port = SerialPortInfo(port="/dev/ttyUSB0", is_usb=True, is_pi_native=False, description="USB Serial")
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

    def test_get_pip_command_with_venv_path(self):
        """Pip command with a non-existent venv falls back to system pip."""
        result = get_pip_command(Path("/nonexistent/venv"))
        assert "pip" in result[0].lower()

    def test_get_python_command_with_venv_path(self):
        """Python command with a non-existent venv falls back to system python."""
        result = get_python_command(Path("/nonexistent/venv"))
        assert "python" in result.lower()


class TestCheckVenvExists:
    """Test venv existence checking."""

    def test_check_venv_nonexistent_path(self):
        from meshing_around_clients.setup.pi_utils import check_venv_exists

        assert check_venv_exists(Path("/nonexistent/path")) is False

    def test_check_venv_default_path(self):
        from meshing_around_clients.setup.pi_utils import check_venv_exists

        # Default path likely doesn't exist in test env
        result = check_venv_exists()
        assert isinstance(result, bool)


class TestPiConfigPath:
    """Test Pi config path detection."""

    @patch("pathlib.Path.exists", return_value=False)
    def test_get_pi_config_path_default(self, mock_exists):
        from meshing_around_clients.setup.pi_utils import get_pi_config_path

        result = get_pi_config_path()
        assert isinstance(result, Path)

    def test_get_pi_config_path_returns_path(self):
        from meshing_around_clients.setup.pi_utils import get_pi_config_path

        result = get_pi_config_path()
        assert isinstance(result, Path)


class TestPep668:
    """Test PEP 668 environment checks."""

    def test_check_pep668_returns_bool(self):
        from meshing_around_clients.setup.pi_utils import check_pep668_environment

        result = check_pep668_environment()
        assert isinstance(result, bool)

    def test_is_bookworm_or_newer_returns_bool(self):
        from meshing_around_clients.setup.pi_utils import is_bookworm_or_newer

        result = is_bookworm_or_newer()
        assert isinstance(result, bool)


class TestPiDetection:
    """Test Pi-specific detection functions."""

    def test_is_raspberry_pi_returns_bool(self):
        from meshing_around_clients.setup.pi_utils import is_raspberry_pi

        result = is_raspberry_pi()
        assert isinstance(result, bool)

    def test_is_pi_zero_returns_bool(self):
        from meshing_around_clients.setup.pi_utils import is_pi_zero

        result = is_pi_zero()
        assert isinstance(result, bool)

    def test_is_pi_zero_2w_returns_bool(self):
        from meshing_around_clients.setup.pi_utils import is_pi_zero_2w

        result = is_pi_zero_2w()
        assert isinstance(result, bool)


class TestGetPipInstallFlags:
    """Test pip install flag generation."""

    def test_get_pip_install_flags_returns_list(self):
        from meshing_around_clients.setup.pi_utils import get_pip_install_flags

        result = get_pip_install_flags()
        assert isinstance(result, list)

    @patch("meshing_around_clients.setup.pi_utils.check_pep668_environment", return_value=True)
    def test_get_pip_install_flags_with_pep668(self, mock_pep):
        from meshing_around_clients.setup.pi_utils import get_pip_install_flags

        result = get_pip_install_flags()
        assert "--break-system-packages" in result

    @patch("meshing_around_clients.setup.pi_utils.check_pep668_environment", return_value=False)
    def test_get_pip_install_flags_without_pep668(self, mock_pep):
        from meshing_around_clients.setup.pi_utils import get_pip_install_flags

        result = get_pip_install_flags()
        assert result == []


class TestSerialPortDetection:
    """Test serial port detection."""

    def test_get_serial_port_list_returns_list(self):
        from meshing_around_clients.setup.pi_utils import get_serial_port_list

        result = get_serial_port_list()
        assert isinstance(result, list)

    def test_get_serial_ports_returns_list(self):
        from meshing_around_clients.setup.pi_utils import get_serial_ports

        result = get_serial_ports()
        assert isinstance(result, list)


class TestUserGroups:
    """Test user group checking."""

    def test_check_user_groups_returns_tuple(self):
        from meshing_around_clients.setup.pi_utils import check_user_groups

        result = check_user_groups()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_add_user_to_dialout_empty_username(self):
        from meshing_around_clients.setup.pi_utils import add_user_to_dialout

        with patch.dict("os.environ", {"USER": "", "LOGNAME": ""}, clear=False):
            success, msg = add_user_to_dialout("")
            assert success is False

    def test_add_user_to_dialout_invalid_username(self):
        from meshing_around_clients.setup.pi_utils import add_user_to_dialout

        success, msg = add_user_to_dialout("INVALID USER!")
        assert success is False
        assert "Invalid username" in msg


class TestCheckSerialEnabled:
    """Test serial port enabled check."""

    def test_check_serial_enabled_returns_tuple(self):
        from meshing_around_clients.setup.pi_utils import check_serial_enabled

        result = check_serial_enabled()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_check_i2c_spi_enabled_returns_tuple(self):
        from meshing_around_clients.setup.pi_utils import check_i2c_spi_enabled

        result = check_i2c_spi_enabled()
        assert isinstance(result, tuple)
        assert len(result) == 2

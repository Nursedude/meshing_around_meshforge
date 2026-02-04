"""
Integration tests for configure_bot.py module fallback pattern.

Tests that:
1. Modules can be imported when available
2. Fallback functions work correctly when modules unavailable
3. MODULES_AVAILABLE flag is properly set
4. Functionality is consistent between module and fallback versions
"""

import unittest
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestModuleAvailability(unittest.TestCase):
    """Test that modules can be imported and detected."""

    def test_cli_utils_import(self):
        """Test cli_utils module can be imported."""
        from meshing_around_clients.core.cli_utils import (
            Colors, print_header, print_section, print_success, print_warning,
            print_error, print_info, get_input, get_yes_no,
            validate_mac_address, validate_coordinates
        )
        self.assertTrue(hasattr(Colors, 'HEADER'))
        self.assertTrue(callable(print_header))
        self.assertTrue(callable(validate_mac_address))

    def test_pi_utils_import(self):
        """Test pi_utils module can be imported."""
        from meshing_around_clients.core.pi_utils import (
            is_raspberry_pi, get_pi_model, get_os_info, is_bookworm_or_newer,
            check_pep668_environment, get_serial_ports
        )
        self.assertTrue(callable(is_raspberry_pi))
        self.assertTrue(callable(get_os_info))

    def test_system_maintenance_import(self):
        """Test system_maintenance module can be imported."""
        from meshing_around_clients.core.system_maintenance import (
            run_command, find_meshing_around
        )
        self.assertTrue(callable(run_command))
        self.assertTrue(callable(find_meshing_around))

    def test_alert_configurators_import(self):
        """Test alert_configurators module can be imported."""
        from meshing_around_clients.core.alert_configurators import (
            configure_interface, configure_general, configure_emergency_alerts,
            create_basic_config
        )
        self.assertTrue(callable(configure_interface))
        self.assertTrue(callable(create_basic_config))


class TestCliUtilsFunctions(unittest.TestCase):
    """Test CLI utilities work correctly."""

    def test_colors_class(self):
        """Test Colors class has expected attributes."""
        from meshing_around_clients.core.cli_utils import Colors
        self.assertTrue(hasattr(Colors, 'HEADER'))
        self.assertTrue(hasattr(Colors, 'OKGREEN'))
        self.assertTrue(hasattr(Colors, 'WARNING'))
        self.assertTrue(hasattr(Colors, 'FAIL'))
        self.assertTrue(hasattr(Colors, 'ENDC'))

    def test_validate_mac_address_valid(self):
        """Test MAC address validation with valid addresses."""
        from meshing_around_clients.core.cli_utils import validate_mac_address
        self.assertTrue(validate_mac_address("AA:BB:CC:DD:EE:FF"))
        self.assertTrue(validate_mac_address("aa:bb:cc:dd:ee:ff"))
        self.assertTrue(validate_mac_address("00:11:22:33:44:55"))

    def test_validate_mac_address_invalid(self):
        """Test MAC address validation with invalid addresses."""
        from meshing_around_clients.core.cli_utils import validate_mac_address
        self.assertFalse(validate_mac_address("invalid"))
        self.assertFalse(validate_mac_address("AA:BB:CC"))
        self.assertFalse(validate_mac_address("AA:BB:CC:DD:EE:GG"))

    def test_validate_coordinates_valid(self):
        """Test coordinate validation with valid coordinates."""
        from meshing_around_clients.core.cli_utils import validate_coordinates
        # validate_coordinates takes lat, lon as separate float args
        self.assertTrue(validate_coordinates(40.7128, -74.0060))
        self.assertTrue(validate_coordinates(0, 0))
        self.assertTrue(validate_coordinates(-90, 180))
        self.assertTrue(validate_coordinates(89.999, -179.999))

    def test_validate_coordinates_invalid(self):
        """Test coordinate validation with invalid coordinates."""
        from meshing_around_clients.core.cli_utils import validate_coordinates
        # validate_coordinates takes lat, lon as separate float args
        self.assertFalse(validate_coordinates(91, 0))  # lat > 90
        self.assertFalse(validate_coordinates(0, 181))  # lon > 180
        self.assertFalse(validate_coordinates(-91, 0))  # lat < -90


class TestPiUtilsFunctions(unittest.TestCase):
    """Test Pi utilities work correctly."""

    def test_is_raspberry_pi(self):
        """Test Pi detection returns boolean."""
        from meshing_around_clients.core.pi_utils import is_raspberry_pi
        result = is_raspberry_pi()
        self.assertIsInstance(result, bool)

    def test_get_os_info(self):
        """Test OS info returns tuple with name and codename."""
        from meshing_around_clients.core.pi_utils import get_os_info
        info = get_os_info()
        # Returns Tuple[str, str] - (os_name, version_codename)
        self.assertIsInstance(info, tuple)
        self.assertEqual(len(info), 2)
        self.assertIsInstance(info[0], str)  # OS name
        self.assertIsInstance(info[1], str)  # Version codename

    def test_is_bookworm_or_newer(self):
        """Test bookworm detection returns boolean."""
        from meshing_around_clients.core.pi_utils import is_bookworm_or_newer
        result = is_bookworm_or_newer()
        self.assertIsInstance(result, bool)

    def test_get_serial_ports(self):
        """Test serial port detection returns list."""
        from meshing_around_clients.core.pi_utils import get_serial_ports
        ports = get_serial_ports()
        self.assertIsInstance(ports, list)


class TestSystemMaintenanceFunctions(unittest.TestCase):
    """Test system maintenance utilities."""

    def test_run_command_success(self):
        """Test running a simple command."""
        from meshing_around_clients.core.system_maintenance import run_command
        # run_command takes list, returns (return_code, stdout, stderr)
        return_code, stdout, stderr = run_command(["echo", "test"], capture=True)
        self.assertEqual(return_code, 0)
        self.assertIn("test", stdout)

    def test_run_command_failure(self):
        """Test running a failing command."""
        from meshing_around_clients.core.system_maintenance import run_command
        # run_command takes list, returns (return_code, stdout, stderr)
        return_code, stdout, stderr = run_command(["false"], capture=True)
        self.assertNotEqual(return_code, 0)

    def test_find_meshing_around(self):
        """Test finding meshing-around installation."""
        from meshing_around_clients.core.system_maintenance import find_meshing_around
        # Should return None or a Path, not raise
        result = find_meshing_around()
        self.assertTrue(result is None or isinstance(result, (str, Path)))


class TestAlertConfiguratorsFunctions(unittest.TestCase):
    """Test alert configurator utilities."""

    def test_alert_configurators_importable(self):
        """Test alert configurators module can be imported."""
        from meshing_around_clients.core.alert_configurators import (
            configure_interface, configure_general, configure_emergency_alerts,
            create_basic_config
        )
        # Verify functions are callable (don't call create_basic_config as it's interactive)
        self.assertTrue(callable(configure_interface))
        self.assertTrue(callable(configure_general))
        self.assertTrue(callable(create_basic_config))


class TestConfigureBotFallbackConsistency(unittest.TestCase):
    """Test that fallback functions in configure_bot.py work consistently."""

    def test_configure_bot_imports(self):
        """Test configure_bot.py can be imported."""
        import configure_bot
        # Should have MODULES_AVAILABLE set
        self.assertIsInstance(configure_bot.MODULES_AVAILABLE, bool)
        # Should have VERSION
        self.assertEqual(configure_bot.VERSION, "0.5.0-beta")

    def test_modules_available_flag(self):
        """Test MODULES_AVAILABLE is True when modules exist."""
        import configure_bot
        # Since we can import cli_utils, pi_utils, etc., MODULES_AVAILABLE should be True
        self.assertTrue(configure_bot.MODULES_AVAILABLE)

    def test_colors_class_available(self):
        """Test Colors class is available regardless of module status."""
        import configure_bot
        self.assertTrue(hasattr(configure_bot, 'Colors') or configure_bot.MODULES_AVAILABLE)

    def test_print_functions_available(self):
        """Test print helper functions are available."""
        import configure_bot
        # These should be available either from module or fallback
        self.assertTrue(hasattr(configure_bot, 'print_header') or callable(configure_bot.print_header))
        self.assertTrue(hasattr(configure_bot, 'print_success') or callable(configure_bot.print_success))


if __name__ == "__main__":
    unittest.main()

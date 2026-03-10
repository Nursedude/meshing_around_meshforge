"""
Unit tests for alert_configurators module.

Tests ALERT_CONFIGURATORS mapping and actual configurator behavior
with mocked user input. Removed: TestConfiguratorFunctions (signature
inspection via inspect.signature — not useful).
"""

import configparser
from unittest.mock import patch

import pytest

from meshing_around_clients.setup.alert_configurators import (
    ALERT_CONFIGURATORS,
    configure_emergency_alerts,
    configure_general,
    configure_interface,
    create_basic_config,
)


class TestAlertConfiguratorsMapping:
    """Test the ALERT_CONFIGURATORS mapping."""

    def test_mapping_has_expected_keys(self):
        """Verify all expected alert types are mapped."""
        expected_keys = [
            "interface",
            "general",
            "emergency",
            "proximity",
            "altitude",
            "weather",
            "battery",
            "noisy_node",
            "new_node",
            "disconnect",
            "email_sms",
            "global",
        ]
        for key in expected_keys:
            assert key in ALERT_CONFIGURATORS, f"Missing key: {key}"

    def test_mapping_values_are_callable(self):
        """Verify all mapping values are callable functions."""
        for key, func in ALERT_CONFIGURATORS.items():
            assert callable(func), f"Value for {key} is not callable"


class TestCreateBasicConfig:
    """Test create_basic_config with mocked input."""

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_create_basic_config_returns_configparser(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test create_basic_config returns ConfigParser."""
        mock_input.side_effect = ["1", "MeshBot"]
        mock_yes_no.side_effect = [True, False, False]

        result = create_basic_config()
        assert isinstance(result, configparser.ConfigParser)

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_create_basic_config_has_required_sections(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test create_basic_config creates required sections."""
        mock_input.side_effect = ["1", "TestBot"]
        mock_yes_no.side_effect = [True, False, False]

        config = create_basic_config()

        assert config.has_section("interface")
        assert config.has_section("general")
        assert config.has_section("emergencyHandler")
        assert config.has_section("newNodeAlert")
        assert config.has_section("alertGlobal")

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_create_basic_config_enables_emergency_alerts(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test create_basic_config enables emergency alerts by default."""
        mock_input.side_effect = ["1", "TestBot"]
        mock_yes_no.side_effect = [True, False, False]

        config = create_basic_config()

        assert config.get("emergencyHandler", "enabled") == "True"
        assert "emergency" in config.get("emergencyHandler", "emergency_keywords")


class TestIndividualConfigurators:
    """Test individual configurators with mocked input."""

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_interface_serial(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test configure_interface for serial connection."""
        config = configparser.ConfigParser()
        mock_input.return_value = "1"
        mock_yes_no.return_value = True

        configure_interface(config)

        assert config.has_section("interface")
        assert config.get("interface", "type") == "serial"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_interface_tcp(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test configure_interface for TCP connection."""
        config = configparser.ConfigParser()
        mock_input.side_effect = ["2", "192.168.1.100"]

        configure_interface(config)

        assert config.get("interface", "type") == "tcp"
        assert config.get("interface", "hostname") == "192.168.1.100"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_general_settings(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test configure_general settings."""
        config = configparser.ConfigParser()
        mock_input.return_value = "MyMeshBot"
        mock_yes_no.return_value = False

        configure_general(config)

        assert config.has_section("general")
        assert config.get("general", "bot_name") == "MyMeshBot"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_interface_ble(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test configure_interface for BLE connection."""
        config = configparser.ConfigParser()
        mock_input.side_effect = ["3", "AA:BB:CC:DD:EE:FF"]

        configure_interface(config)

        assert config.get("interface", "type") == "ble"
        assert config.get("interface", "mac") == "AA:BB:CC:DD:EE:FF"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_general_with_admin_and_favorites(self, mock_success, mock_section, mock_yes_no, mock_input):
        """Test configure_general with admin and favorite nodes."""
        config = configparser.ConfigParser()
        mock_input.side_effect = ["MeshBot", "123,456", "789"]
        mock_yes_no.side_effect = [True, True]  # yes to admin, yes to favorites

        configure_general(config)

        assert config.get("general", "bbs_admin_list") == "123,456"
        assert config.get("general", "favoriteNodeList") == "789"


class TestAlertConfiguratorFunctions:
    """Test all alert configurator functions with mocked input."""

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_emergency_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_emergency_alerts(config)
        assert config.get("emergencyHandler", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_emergency_enabled_defaults(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_emergency_alerts

        config = configparser.ConfigParser()
        # enabled=True, use default keywords=True, email=False, sms=False, sound=False
        mock_yes_no.side_effect = [True, True, False, False, False]
        mock_input.side_effect = ["2", "300"]
        configure_emergency_alerts(config)
        assert config.get("emergencyHandler", "enabled") == "True"
        assert "emergency" in config.get("emergencyHandler", "emergency_keywords")

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    @patch("meshing_around_clients.setup.alert_configurators.print_warning")
    @patch("meshing_around_clients.setup.alert_configurators.validate_coordinates", return_value=True)
    def test_configure_proximity_enabled(self, mock_vc, mock_warn, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_proximity_alerts

        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, False]  # enable=True, run_script=False
        mock_input.side_effect = ["45.0", "-122.0", "200", "0", "60"]
        configure_proximity_alerts(config)
        assert config.get("proximityAlert", "enabled") == "True"
        assert config.get("proximityAlert", "radius_meters") == "200"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_proximity_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_proximity_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_proximity_alerts(config)
        assert config.get("proximityAlert", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_altitude_enabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_altitude_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = True
        mock_input.side_effect = ["1000", "0", "120"]
        configure_altitude_alerts(config)
        assert config.get("altitudeAlert", "enabled") == "True"
        assert config.get("altitudeAlert", "min_altitude") == "1000"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_altitude_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_altitude_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_altitude_alerts(config)
        assert config.get("altitudeAlert", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_weather_enabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_weather_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = True
        mock_input.side_effect = ["45.0,-122.0", "Extreme,Severe", "30", "2"]
        configure_weather_alerts(config)
        assert config.get("weatherAlert", "enabled") == "True"
        assert config.get("weatherAlert", "location") == "45.0,-122.0"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_weather_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_weather_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_weather_alerts(config)
        assert config.get("weatherAlert", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_battery_enabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_battery_alerts

        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, False]  # enable=True, monitor_specific=False
        mock_input.side_effect = ["20", "30", "0"]
        configure_battery_alerts(config)
        assert config.get("batteryAlert", "enabled") == "True"
        assert config.get("batteryAlert", "threshold_percent") == "20"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_battery_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_battery_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_battery_alerts(config)
        assert config.get("batteryAlert", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_noisy_node_enabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_noisy_node_alerts

        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, False]  # enable=True, auto_mute=False
        mock_input.side_effect = ["50", "10"]
        configure_noisy_node_alerts(config)
        assert config.get("noisyNodeAlert", "enabled") == "True"
        assert config.get("noisyNodeAlert", "message_threshold") == "50"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_noisy_node_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_noisy_node_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_noisy_node_alerts(config)
        assert config.get("noisyNodeAlert", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_new_node_enabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_new_node_alerts

        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, True, False]  # enable, send_dm, announce=False
        mock_input.side_effect = ["Welcome {node_name}!"]
        configure_new_node_alerts(config)
        assert config.get("newNodeAlert", "enabled") == "True"
        assert config.get("newNodeAlert", "welcome_message") == "Welcome {node_name}!"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_new_node_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_new_node_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_new_node_alerts(config)
        assert config.get("newNodeAlert", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_disconnect_enabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_disconnect_alerts

        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, False]  # enable, monitor_specific=False
        mock_input.side_effect = ["30", "0"]
        configure_disconnect_alerts(config)
        assert config.get("disconnectAlert", "enabled") == "True"
        assert config.get("disconnectAlert", "monitor_all") == "True"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_disconnect_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_disconnect_alerts

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_disconnect_alerts(config)
        assert config.get("disconnectAlert", "enabled") == "False"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    @patch("meshing_around_clients.setup.alert_configurators.print_warning")
    @patch("meshing_around_clients.setup.alert_configurators.validate_email", return_value=True)
    def test_configure_email_sms_enabled(self, mock_ve, mock_warn, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_email_sms

        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, False]  # configure email=True, sms=False
        mock_input.side_effect = [
            "smtp.gmail.com",
            "587",
            "user@test.com",
            "pass123",
            "user@test.com",
            "admin@test.com",
        ]
        configure_email_sms(config)
        assert config.get("smtp", "enableSMTP") == "True"
        assert config.get("smtp", "SMTP_SERVER") == "smtp.gmail.com"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_email_sms_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_email_sms

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_email_sms(config)
        # Should not have enableSMTP
        assert not config.has_option("smtp", "enableSMTP")

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_global_enabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_global_settings

        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, False]  # enable=True, quiet_hours=False
        mock_input.return_value = "20"
        configure_global_settings(config)
        assert config.get("alertGlobal", "global_enabled") == "True"
        assert config.get("alertGlobal", "max_alerts_per_hour") == "20"

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    def test_configure_global_disabled(self, mock_success, mock_section, mock_yes_no, mock_input):
        from meshing_around_clients.setup.alert_configurators import configure_global_settings

        config = configparser.ConfigParser()
        mock_yes_no.return_value = False
        configure_global_settings(config)
        assert config.get("alertGlobal", "global_enabled") == "False"


class TestValidatorHelpers:
    """Test _in_range and _positive validator helpers."""

    def test_in_range_valid(self):
        from meshing_around_clients.setup.alert_configurators import _in_range

        validator = _in_range(0, 7)
        assert validator(0) is True
        assert validator(7) is True
        assert validator(3) is True

    def test_in_range_invalid(self):
        from meshing_around_clients.setup.alert_configurators import _in_range

        validator = _in_range(0, 7)
        assert validator(-1) is False
        assert validator(8) is False

    def test_positive_valid(self):
        from meshing_around_clients.setup.alert_configurators import _positive

        assert _positive(1) is True
        assert _positive(100) is True

    def test_positive_invalid(self):
        from meshing_around_clients.setup.alert_configurators import _positive

        assert _positive(0) is False
        assert _positive(-1) is False


class TestRunAllConfigurators:
    """Test run_all_configurators."""

    @patch("meshing_around_clients.setup.alert_configurators.get_input")
    @patch("meshing_around_clients.setup.alert_configurators.get_yes_no")
    @patch("meshing_around_clients.setup.alert_configurators.print_section")
    @patch("meshing_around_clients.setup.alert_configurators.print_success")
    @patch("meshing_around_clients.setup.alert_configurators.print_warning")
    @patch("meshing_around_clients.setup.alert_configurators.validate_coordinates", return_value=True)
    @patch("meshing_around_clients.setup.alert_configurators.validate_email", return_value=True)
    def test_run_all_does_not_crash(
        self, mock_ve, mock_vc, mock_warn, mock_success, mock_section, mock_yes_no, mock_input
    ):
        from meshing_around_clients.setup.alert_configurators import run_all_configurators

        config = configparser.ConfigParser()
        # All disabled to keep it simple
        mock_yes_no.return_value = False
        mock_input.side_effect = ["1", "MeshBot"] + [""] * 50  # Extra for any remaining calls

        run_all_configurators(config)
        assert config.has_section("interface")

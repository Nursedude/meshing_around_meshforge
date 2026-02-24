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

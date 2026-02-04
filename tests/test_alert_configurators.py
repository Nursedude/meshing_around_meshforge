"""
Unit tests for alert_configurators module.

Tests:
- ALERT_CONFIGURATORS mapping
- create_basic_config function structure
- Configurator function existence
"""

import pytest
import configparser
from unittest.mock import patch, MagicMock

from meshing_around_clients.core.alert_configurators import (
    ALERT_CONFIGURATORS,
    configure_interface, configure_general, configure_emergency_alerts,
    configure_proximity_alerts, configure_altitude_alerts,
    configure_weather_alerts, configure_battery_alerts,
    configure_noisy_node_alerts, configure_new_node_alerts,
    configure_disconnect_alerts, configure_email_sms,
    configure_global_settings, create_basic_config
)


class TestAlertConfiguratorsMapping:
    """Test the ALERT_CONFIGURATORS mapping."""

    def test_mapping_exists(self):
        """Verify ALERT_CONFIGURATORS is a dict."""
        assert isinstance(ALERT_CONFIGURATORS, dict)

    def test_mapping_has_expected_keys(self):
        """Verify all expected alert types are mapped."""
        expected_keys = [
            'interface', 'general', 'emergency', 'proximity', 'altitude',
            'weather', 'battery', 'noisy_node', 'new_node', 'disconnect',
            'email_sms', 'global'
        ]
        for key in expected_keys:
            assert key in ALERT_CONFIGURATORS, f"Missing key: {key}"

    def test_mapping_values_are_callable(self):
        """Verify all mapping values are callable functions."""
        for key, func in ALERT_CONFIGURATORS.items():
            assert callable(func), f"Value for {key} is not callable"

    def test_correct_functions_mapped(self):
        """Verify correct functions are mapped to keys."""
        assert ALERT_CONFIGURATORS['interface'] == configure_interface
        assert ALERT_CONFIGURATORS['general'] == configure_general
        assert ALERT_CONFIGURATORS['emergency'] == configure_emergency_alerts
        assert ALERT_CONFIGURATORS['proximity'] == configure_proximity_alerts
        assert ALERT_CONFIGURATORS['altitude'] == configure_altitude_alerts
        assert ALERT_CONFIGURATORS['weather'] == configure_weather_alerts
        assert ALERT_CONFIGURATORS['battery'] == configure_battery_alerts
        assert ALERT_CONFIGURATORS['noisy_node'] == configure_noisy_node_alerts
        assert ALERT_CONFIGURATORS['new_node'] == configure_new_node_alerts
        assert ALERT_CONFIGURATORS['disconnect'] == configure_disconnect_alerts
        assert ALERT_CONFIGURATORS['email_sms'] == configure_email_sms
        assert ALERT_CONFIGURATORS['global'] == configure_global_settings


class TestConfiguratorFunctions:
    """Test configurator functions accept config objects."""

    def test_configure_interface_accepts_config(self):
        """Verify configure_interface signature."""
        config = configparser.ConfigParser()
        # Function should accept config as argument
        import inspect
        sig = inspect.signature(configure_interface)
        assert 'config' in sig.parameters

    def test_configure_general_accepts_config(self):
        """Verify configure_general signature."""
        import inspect
        sig = inspect.signature(configure_general)
        assert 'config' in sig.parameters

    def test_configure_emergency_alerts_accepts_config(self):
        """Verify configure_emergency_alerts signature."""
        import inspect
        sig = inspect.signature(configure_emergency_alerts)
        assert 'config' in sig.parameters


class TestCreateBasicConfig:
    """Test create_basic_config with mocked input."""

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_create_basic_config_returns_configparser(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test create_basic_config returns ConfigParser."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # Connection type: serial
            "MeshBot",  # Bot name
        ]
        mock_yes_no.side_effect = [
            True,   # Use auto-detect for serial
            False,  # Don't configure admin nodes
            False,  # Don't configure favorite nodes
        ]

        result = create_basic_config()

        assert isinstance(result, configparser.ConfigParser)

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_create_basic_config_has_required_sections(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test create_basic_config creates required sections."""
        mock_input.side_effect = ["1", "TestBot"]
        mock_yes_no.side_effect = [True, False, False]

        config = create_basic_config()

        assert config.has_section('interface')
        assert config.has_section('general')
        assert config.has_section('emergencyHandler')
        assert config.has_section('newNodeAlert')
        assert config.has_section('alertGlobal')

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_create_basic_config_enables_emergency_alerts(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test create_basic_config enables emergency alerts by default."""
        mock_input.side_effect = ["1", "TestBot"]
        mock_yes_no.side_effect = [True, False, False]

        config = create_basic_config()

        assert config.get('emergencyHandler', 'enabled') == 'True'
        assert 'emergency' in config.get('emergencyHandler', 'emergency_keywords')


class TestIndividualConfiguratorsWithMockedInput:
    """Test individual configurators with mocked input."""

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_configure_interface_serial(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test configure_interface for serial connection."""
        config = configparser.ConfigParser()
        mock_input.return_value = "1"  # Serial
        mock_yes_no.return_value = True  # Auto-detect

        configure_interface(config)

        assert config.has_section('interface')
        assert config.get('interface', 'type') == 'serial'

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_configure_interface_tcp(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test configure_interface for TCP connection."""
        config = configparser.ConfigParser()
        mock_input.side_effect = ["2", "192.168.1.100"]  # TCP, hostname

        configure_interface(config)

        assert config.get('interface', 'type') == 'tcp'
        assert config.get('interface', 'hostname') == '192.168.1.100'

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_configure_emergency_alerts_enabled(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test configure_emergency_alerts when enabled."""
        config = configparser.ConfigParser()
        mock_yes_no.side_effect = [True, True, False, False, False]  # Enable, use defaults, no email, no SMS, no sound
        mock_input.side_effect = ["2", "300"]  # channel, cooldown

        configure_emergency_alerts(config)

        assert config.has_section('emergencyHandler')
        assert config.get('emergencyHandler', 'enabled') == 'True'
        assert config.get('emergencyHandler', 'alert_channel') == '2'

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_configure_emergency_alerts_disabled(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test configure_emergency_alerts when disabled."""
        config = configparser.ConfigParser()
        mock_yes_no.return_value = False  # Don't enable

        configure_emergency_alerts(config)

        assert config.get('emergencyHandler', 'enabled') == 'False'

    @patch('meshing_around_clients.core.alert_configurators.get_input')
    @patch('meshing_around_clients.core.alert_configurators.get_yes_no')
    @patch('meshing_around_clients.core.alert_configurators.print_section')
    @patch('meshing_around_clients.core.alert_configurators.print_success')
    def test_configure_general_settings(
        self, mock_success, mock_section, mock_yes_no, mock_input
    ):
        """Test configure_general settings."""
        config = configparser.ConfigParser()
        mock_input.return_value = "MyMeshBot"
        mock_yes_no.return_value = False  # No admin/favorite nodes

        configure_general(config)

        assert config.has_section('general')
        assert config.get('general', 'bot_name') == 'MyMeshBot'

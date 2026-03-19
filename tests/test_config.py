"""
Unit tests for meshing_around_clients.core.config
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.config import (
    AlertConfig,
    Config,
    InterfaceConfig,
    LoggingConfig,
    TuiConfig,
    _str_to_bool,
)


class TestStrToBool(unittest.TestCase):
    """Test _str_to_bool() utility function."""

    def test_true_string_values(self):
        for val in ("true", "True", "TRUE", "yes", "Yes", "1", "on", "ON"):
            self.assertTrue(_str_to_bool(val), f"Expected True for {val!r}")

    def test_false_string_values(self):
        for val in ("false", "False", "no", "0", "off", "", "random", "nope"):
            self.assertFalse(_str_to_bool(val), f"Expected False for {val!r}")

    def test_bool_passthrough(self):
        self.assertTrue(_str_to_bool(True))
        self.assertFalse(_str_to_bool(False))

    def test_int_values(self):
        self.assertTrue(_str_to_bool(1))
        self.assertFalse(_str_to_bool(0))

    def test_none_is_false(self):
        self.assertFalse(_str_to_bool(None))


class TestInterfaceConfig(unittest.TestCase):
    """Test InterfaceConfig dataclass."""

    def test_default_values(self):
        cfg = InterfaceConfig()
        self.assertEqual(cfg.type, "serial")
        self.assertEqual(cfg.port, "")
        self.assertEqual(cfg.hostname, "")
        self.assertEqual(cfg.baudrate, 115200)

    def test_custom_values(self):
        cfg = InterfaceConfig(type="tcp", hostname="192.168.1.1", port="4403")
        self.assertEqual(cfg.type, "tcp")
        self.assertEqual(cfg.hostname, "192.168.1.1")

    def test_http_url_field(self):
        """Test http_url field for meshtasticd HTTP API."""
        cfg = InterfaceConfig(type="http", http_url="http://meshtastic.local")
        self.assertEqual(cfg.type, "http")
        self.assertEqual(cfg.http_url, "http://meshtastic.local")

    def test_http_url_default_empty(self):
        """Test http_url defaults to empty string."""
        cfg = InterfaceConfig()
        self.assertEqual(cfg.http_url, "")

    def test_from_dict_with_http_url(self):
        """Test InterfaceConfig.from_dict handles http_url."""
        data = {"type": "http", "http_url": "http://192.168.1.50"}
        cfg = InterfaceConfig.from_dict(data)
        self.assertEqual(cfg.type, "http")
        self.assertEqual(cfg.http_url, "http://192.168.1.50")


class TestAlertConfig(unittest.TestCase):
    """Test AlertConfig dataclass."""

    def test_default_values(self):
        cfg = AlertConfig()
        self.assertTrue(cfg.enabled)
        self.assertIn("emergency", cfg.emergency_keywords)
        self.assertIn("sos", cfg.emergency_keywords)
        self.assertEqual(cfg.alert_channel, 2)
        self.assertEqual(cfg.cooldown_period, 300)

    def test_custom_values(self):
        cfg = AlertConfig(enabled=False, alert_channel=5, cooldown_period=600)
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.alert_channel, 5)
        self.assertEqual(cfg.cooldown_period, 600)


class TestTuiConfig(unittest.TestCase):
    """Test TuiConfig dataclass."""

    def test_default_values(self):
        cfg = TuiConfig()
        self.assertEqual(cfg.refresh_rate, 1.0)
        self.assertEqual(cfg.color_scheme, "default")
        self.assertTrue(cfg.show_timestamps)
        self.assertEqual(cfg.message_history, 500)

    def test_custom_values(self):
        cfg = TuiConfig(refresh_rate=0.5, color_scheme="dark", message_history=1000)
        self.assertEqual(cfg.refresh_rate, 0.5)
        self.assertEqual(cfg.color_scheme, "dark")
        self.assertEqual(cfg.message_history, 1000)


class TestConfig(unittest.TestCase):
    """Test Config class."""

    def test_default_initialization(self):
        cfg = Config(config_path="/nonexistent/path/config.ini")
        self.assertIsNotNone(cfg.interface)
        self.assertIsNotNone(cfg.alerts)
        self.assertIsNotNone(cfg.tui)
        self.assertEqual(cfg.bot_name, "MeshBot")

    def test_to_dict(self):
        cfg = Config(config_path="/nonexistent/path/config.ini")
        d = cfg.to_dict()
        self.assertIn("interface", d)
        self.assertIn("general", d)
        self.assertIn("alerts", d)
        self.assertIn("tui", d)
        self.assertEqual(d["general"]["bot_name"], "MeshBot")

    def test_save_and_load(self):
        """Test saving and loading configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.ini"

            # Create and save config
            cfg1 = Config(config_path=str(config_path))
            cfg1.bot_name = "TestBot"
            cfg1.interface.type = "tcp"
            cfg1.interface.hostname = "192.168.1.100"
            cfg1.alerts.enabled = False
            cfg1.alerts.alert_channel = 5
            cfg1.tui.refresh_rate = 0.5
            cfg1.admin_nodes = ["!node1", "!node2"]
            cfg1.favorite_nodes = ["!fav1"]

            result = cfg1.save()
            self.assertTrue(result)
            self.assertTrue(config_path.exists())

            # Verify file permissions (600 = owner read/write only)
            mode = os.stat(config_path).st_mode & 0o777
            self.assertEqual(mode, 0o600)

            # Load config in new instance
            cfg2 = Config(config_path=str(config_path))

            self.assertEqual(cfg2.bot_name, "TestBot")
            self.assertEqual(cfg2.interface.type, "tcp")
            self.assertEqual(cfg2.interface.hostname, "192.168.1.100")
            self.assertFalse(cfg2.alerts.enabled)
            self.assertEqual(cfg2.alerts.alert_channel, 5)
            self.assertEqual(cfg2.tui.refresh_rate, 0.5)
            self.assertEqual(cfg2.admin_nodes, ["!node1", "!node2"])
            self.assertEqual(cfg2.favorite_nodes, ["!fav1"])

    def test_load_nonexistent_file(self):
        """Test loading from nonexistent file returns False."""
        cfg = Config(config_path="/nonexistent/path/config.ini")
        result = cfg.load()
        self.assertFalse(result)

    def test_load_with_missing_sections(self):
        """Test loading config with missing sections uses defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "minimal.ini"
            # Write minimal config with only one section
            config_path.write_text("[general]\nbot_name = MinimalBot\n")

            cfg = Config(config_path=str(config_path))

            # Check general was loaded
            self.assertEqual(cfg.bot_name, "MinimalBot")
            # Check defaults for missing sections
            self.assertEqual(cfg.interface.type, "serial")
            self.assertTrue(cfg.alerts.enabled)

    def test_emergency_keywords_parsing(self):
        """Test parsing of emergency keywords from config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "keywords.ini"
            config_path.write_text(
                "[emergencyHandler]\n"
                "enabled = true\n"
                "emergency_keywords = help, rescue, mayday, custom_word\n"
                "alert_channel = 3\n"
            )

            cfg = Config(config_path=str(config_path))

            self.assertTrue(cfg.alerts.enabled)
            self.assertIn("help", cfg.alerts.emergency_keywords)
            self.assertIn("rescue", cfg.alerts.emergency_keywords)
            self.assertIn("custom_word", cfg.alerts.emergency_keywords)
            self.assertEqual(cfg.alerts.alert_channel, 3)

    def test_admin_nodes_parsing(self):
        """Test parsing of admin nodes list from config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "admins.ini"
            config_path.write_text(
                "[general]\n"
                "bot_name = AdminBot\n"
                "bbs_admin_list = !admin1, !admin2, !admin3\n"
                "favoriteNodeList = !fav1, !fav2\n"
            )

            cfg = Config(config_path=str(config_path))

            self.assertEqual(cfg.admin_nodes, ["!admin1", "!admin2", "!admin3"])
            self.assertEqual(cfg.favorite_nodes, ["!fav1", "!fav2"])

    def test_config_path_creation(self):
        """Test that save creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nested" / "deep" / "config.ini"

            cfg = Config(config_path=str(config_path))
            cfg.bot_name = "NestedBot"
            result = cfg.save()

            self.assertTrue(result)
            self.assertTrue(config_path.exists())

    def test_save_and_load_http_url(self):
        """Test saving and loading HTTP URL configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "http_config.ini"

            cfg1 = Config(config_path=str(config_path))
            cfg1.interface.type = "http"
            cfg1.interface.http_url = "http://meshtastic.local"
            cfg1.save()

            cfg2 = Config(config_path=str(config_path))
            self.assertEqual(cfg2.interface.type, "http")
            self.assertEqual(cfg2.interface.http_url, "http://meshtastic.local")

    def test_to_dict_includes_http_url(self):
        """Test to_dict includes http_url field."""
        cfg = Config(config_path="/nonexistent/path/config.ini")
        cfg.interface.http_url = "http://192.168.1.50"
        d = cfg.to_dict()
        self.assertEqual(d["interface"]["http_url"], "http://192.168.1.50")
        self.assertIn("http_url", d["interfaces"][0])

    def test_interface_baudrate(self):
        """Test baudrate is correctly saved and loaded as integer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "baudrate.ini"

            cfg1 = Config(config_path=str(config_path))
            cfg1.interface.baudrate = 9600
            cfg1.save()

            cfg2 = Config(config_path=str(config_path))
            self.assertEqual(cfg2.interface.baudrate, 9600)
            self.assertIsInstance(cfg2.interface.baudrate, int)


class TestConfigDefaults(unittest.TestCase):
    """Test that all config defaults are sensible."""

    def test_default_alert_keywords_comprehensive(self):
        """Verify default emergency keywords include critical terms."""
        cfg = AlertConfig()
        expected_terms = ["emergency", "911", "sos", "mayday"]
        for term in expected_terms:
            self.assertIn(term, cfg.emergency_keywords, f"Missing critical keyword: {term}")
        # 'help' should NOT be an emergency keyword (it's a command)
        self.assertNotIn("help", cfg.emergency_keywords)

    def test_default_tui_reasonable_refresh(self):
        """TUI refresh rate should be reasonable (not too fast or slow)."""
        cfg = TuiConfig()
        self.assertGreaterEqual(cfg.refresh_rate, 0.1)
        self.assertLessEqual(cfg.refresh_rate, 10.0)


class TestLoggingConfig(unittest.TestCase):
    """Test LoggingConfig dataclass."""

    def test_default_values(self):
        cfg = LoggingConfig()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.level, "INFO")
        self.assertEqual(cfg.file, "logs/mesh_client.log")
        self.assertEqual(cfg.max_size_mb, 10)
        self.assertEqual(cfg.backup_count, 3)

    def test_custom_values(self):
        cfg = LoggingConfig(level="DEBUG", max_size_mb=50, backup_count=5)
        self.assertEqual(cfg.level, "DEBUG")
        self.assertEqual(cfg.max_size_mb, 50)
        self.assertEqual(cfg.backup_count, 5)


class TestLoggingConfigLoadSave(unittest.TestCase):
    """Test loading and saving [logging] config section."""

    def test_logging_section_loaded(self):
        """Config should load [logging] section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "logging.ini"
            config_path.write_text(
                "[logging]\n"
                "enabled = true\n"
                "level = DEBUG\n"
                "file = custom.log\n"
                "max_size_mb = 25\n"
                "backup_count = 5\n"
            )
            cfg = Config(config_path=str(config_path))
            self.assertTrue(cfg.logging.enabled)
            self.assertEqual(cfg.logging.level, "DEBUG")
            self.assertEqual(cfg.logging.file, "custom.log")
            self.assertEqual(cfg.logging.max_size_mb, 25)
            self.assertEqual(cfg.logging.backup_count, 5)

    def test_logging_defaults_when_missing(self):
        """Config should use defaults when [logging] section is absent."""
        cfg = Config(config_path="/nonexistent/path.ini")
        self.assertTrue(cfg.logging.enabled)
        self.assertEqual(cfg.logging.level, "INFO")

    def test_logging_save_and_reload(self):
        """Config should round-trip [logging] section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "log_save.ini"
            cfg1 = Config(config_path=str(config_path))
            cfg1.logging.level = "WARNING"
            cfg1.logging.max_size_mb = 50
            cfg1.save()

            cfg2 = Config(config_path=str(config_path))
            self.assertEqual(cfg2.logging.level, "WARNING")
            self.assertEqual(cfg2.logging.max_size_mb, 50)

    def test_to_dict_includes_logging(self):
        """to_dict should include logging section."""
        cfg = Config(config_path="/nonexistent/path.ini")
        d = cfg.to_dict()
        self.assertIn("logging", d)
        self.assertEqual(d["logging"]["level"], "INFO")


class TestEnvVarOverrides(unittest.TestCase):
    """Test environment variable config overrides."""

    def setUp(self):
        # Clean up any MESHFORGE_ env vars before each test
        self._original_env = {}
        for key in list(os.environ):
            if key.startswith("MESHFORGE_"):
                self._original_env[key] = os.environ.pop(key)

    def tearDown(self):
        # Restore original env vars and clean up test vars
        for key in list(os.environ):
            if key.startswith("MESHFORGE_"):
                del os.environ[key]
        os.environ.update(self._original_env)

    def test_mqtt_broker_override(self):
        """MESHFORGE_MQTT_BROKER should override INI value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "env_test.ini"
            config_path.write_text("[mqtt]\nbroker = original.broker.com\n")

            os.environ["MESHFORGE_MQTT_BROKER"] = "override.broker.com"
            cfg = Config(config_path=str(config_path))
            self.assertEqual(cfg.mqtt.broker, "override.broker.com")

    def test_interface_type_override(self):
        """MESHFORGE_INTERFACE_TYPE should override interface type."""
        os.environ["MESHFORGE_INTERFACE_TYPE"] = "tcp"
        cfg = Config(config_path="/nonexistent/path.ini")
        cfg._apply_env_overrides()
        self.assertEqual(cfg.interface.type, "tcp")

    def test_mqtt_enabled_as_bool(self):
        """MESHFORGE_MQTT_ENABLED should be converted to bool."""
        os.environ["MESHFORGE_MQTT_ENABLED"] = "true"
        cfg = Config(config_path="/nonexistent/path.ini")
        cfg._apply_env_overrides()
        self.assertTrue(cfg.mqtt.enabled)

    def test_unset_env_vars_dont_affect_config(self):
        """Config should use defaults when no env vars are set."""
        cfg = Config(config_path="/nonexistent/path.ini")
        self.assertEqual(cfg.mqtt.broker, "mqtt.meshtastic.org")

    def test_logging_level_override(self):
        """MESHFORGE_LOGGING_LEVEL should override logging level."""
        os.environ["MESHFORGE_LOGGING_LEVEL"] = "DEBUG"
        cfg = Config(config_path="/nonexistent/path.ini")
        cfg._apply_env_overrides()
        self.assertEqual(cfg.logging.level, "DEBUG")

    def test_tui_refresh_rate_as_float(self):
        """MESHFORGE_TUI_REFRESH_RATE should be converted to float."""
        os.environ["MESHFORGE_TUI_REFRESH_RATE"] = "0.5"
        cfg = Config(config_path="/nonexistent/path.ini")
        cfg._apply_env_overrides()
        self.assertEqual(cfg.tui.refresh_rate, 0.5)


if __name__ == "__main__":
    unittest.main()

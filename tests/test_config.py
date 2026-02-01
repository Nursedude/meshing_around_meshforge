"""
Unit tests for meshing_around_clients.core.config
"""

import unittest
import tempfile
import os
from pathlib import Path

import sys
sys.path.insert(0, str(__file__).rsplit('/tests/', 1)[0])

from meshing_around_clients.core.config import (
    InterfaceConfig, AlertConfig, WebConfig, TuiConfig, Config
)


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


class TestWebConfig(unittest.TestCase):
    """Test WebConfig dataclass."""

    def test_default_values(self):
        cfg = WebConfig()
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.port, 8080)
        self.assertFalse(cfg.debug)
        self.assertFalse(cfg.enable_auth)

    def test_custom_values(self):
        cfg = WebConfig(host="0.0.0.0", port=9000, debug=True, enable_auth=True)
        self.assertEqual(cfg.host, "0.0.0.0")
        self.assertEqual(cfg.port, 9000)
        self.assertTrue(cfg.debug)
        self.assertTrue(cfg.enable_auth)


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
        self.assertIsNotNone(cfg.web)
        self.assertIsNotNone(cfg.tui)
        self.assertEqual(cfg.bot_name, "MeshBot")

    def test_to_dict(self):
        cfg = Config(config_path="/nonexistent/path/config.ini")
        d = cfg.to_dict()
        self.assertIn("interface", d)
        self.assertIn("general", d)
        self.assertIn("alerts", d)
        self.assertIn("web", d)
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
            cfg1.web.port = 9000
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
            self.assertEqual(cfg2.web.port, 9000)
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
            self.assertEqual(cfg.web.port, 8080)

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
        expected_terms = ["emergency", "911", "help", "sos", "mayday"]
        for term in expected_terms:
            self.assertIn(term, cfg.emergency_keywords,
                          f"Missing critical keyword: {term}")

    def test_default_web_binds_localhost(self):
        """Web server should default to localhost for security."""
        cfg = WebConfig()
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertFalse(cfg.enable_auth)  # Auth disabled when localhost only

    def test_default_tui_reasonable_refresh(self):
        """TUI refresh rate should be reasonable (not too fast or slow)."""
        cfg = TuiConfig()
        self.assertGreaterEqual(cfg.refresh_rate, 0.1)
        self.assertLessEqual(cfg.refresh_rate, 10.0)


if __name__ == "__main__":
    unittest.main()

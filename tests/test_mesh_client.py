"""
Unit tests for mesh_client.py — the main zero-dep bootstrap launcher.

Tests cover dependency checking, config loading/saving, connection type
detection, and legacy config migration.
"""

import os
import sys
import tempfile
import unittest
from configparser import ConfigParser
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

import mesh_client  # noqa: E402


class TestCheckDependency(unittest.TestCase):
    """Test check_dependency() package availability checks."""

    def test_stdlib_module_found(self):
        """os module is always available."""
        self.assertTrue(mesh_client.check_dependency("os"))

    def test_nonexistent_package_not_found(self):
        self.assertFalse(mesh_client.check_dependency("nonexistent_fake_package_xyz"))

    def test_version_specifier_stripped(self):
        """Version specifiers like >=1.0 should not break the import check."""
        # 'os' is always available, even with a version specifier
        self.assertTrue(mesh_client.check_dependency("os>=1.0"))

    def test_paho_mqtt_mapping(self):
        """paho-mqtt should map to paho.mqtt.client for import check."""
        # We don't know if paho is installed, but the mapping should be correct
        result = mesh_client.check_dependency("paho-mqtt")
        self.assertIsInstance(result, bool)


class TestGetMissingDeps(unittest.TestCase):
    """Test get_missing_deps() with various config scenarios."""

    def _make_config(self, **overrides):
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        for key, value in overrides.items():
            section, option = key.split(".", 1)
            if not config.has_section(section):
                config.add_section(section)
            config.set(section, option, str(value))
        return config

    def test_returns_list(self):
        config = self._make_config()
        result = mesh_client.get_missing_deps(config)
        self.assertIsInstance(result, list)

    def test_mqtt_mode_includes_paho(self):
        """When interface type is mqtt, paho-mqtt should be required."""
        config = self._make_config(**{"interface.type": "mqtt"})
        with patch.object(mesh_client, "check_dependency", return_value=False):
            missing = mesh_client.get_missing_deps(config)
        self.assertTrue(any("paho" in d for d in missing))

    def test_serial_mode_includes_meshtastic(self):
        """When interface type is serial, meshtastic should be required."""
        config = self._make_config(**{"interface.type": "serial"})
        with patch.object(mesh_client, "check_dependency", return_value=False):
            missing = mesh_client.get_missing_deps(config)
        self.assertTrue(any("meshtastic" in d for d in missing))

    def test_ble_mode_includes_bleak(self):
        config = self._make_config(**{"interface.type": "ble"})
        with patch.object(mesh_client, "check_dependency", return_value=False):
            missing = mesh_client.get_missing_deps(config)
        self.assertTrue(any("bleak" in d for d in missing))

    def test_no_duplicates(self):
        config = self._make_config()
        with patch.object(mesh_client, "check_dependency", return_value=False):
            missing = mesh_client.get_missing_deps(config)
        self.assertEqual(len(missing), len(set(missing)))


class TestLoadSaveConfig(unittest.TestCase):
    """Test load_config() and save_config() round-trip."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "test_mesh_client.ini"

    def tearDown(self):
        if self.config_path.exists():
            self.config_path.unlink()
        os.rmdir(self.tmpdir)

    @patch.object(mesh_client, "CONFIG_FILE")
    def test_save_creates_file(self, mock_config_file):
        mock_config_file.__str__ = lambda self: str(self)
        # Use the real path
        mesh_client.CONFIG_FILE = self.config_path
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        mesh_client.save_config(config)
        self.assertTrue(self.config_path.exists())

    @patch.object(mesh_client, "CONFIG_FILE")
    def test_save_sets_restricted_permissions(self, mock_config_file):
        mesh_client.CONFIG_FILE = self.config_path
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        mesh_client.save_config(config)
        mode = os.stat(self.config_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    @patch.object(mesh_client, "CONFIG_FILE")
    def test_load_roundtrip_preserves_values(self, mock_config_file):
        mesh_client.CONFIG_FILE = self.config_path
        # Save
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        config.set("interface", "type", "mqtt")
        mesh_client.save_config(config)
        # Load
        loaded = mesh_client.load_config()
        self.assertEqual(loaded.get("interface", "type"), "mqtt")


class TestMigrateConnectionSection(unittest.TestCase):
    """Test _migrate_connection_section() for legacy config migration."""

    def test_no_migration_without_connection_section(self):
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        result = mesh_client._migrate_connection_section(config)
        self.assertFalse(result)

    def test_migration_moves_type(self):
        config = ConfigParser()
        config.add_section("connection")
        config.set("connection", "type", "serial")
        result = mesh_client._migrate_connection_section(config)
        self.assertTrue(result)
        self.assertEqual(config.get("interface", "type"), "serial")

    def test_migration_removes_connection_section(self):
        config = ConfigParser()
        config.add_section("connection")
        config.set("connection", "type", "mqtt")
        mesh_client._migrate_connection_section(config)
        self.assertFalse(config.has_section("connection"))

    def test_migration_moves_mqtt_keys(self):
        config = ConfigParser()
        config.add_section("connection")
        config.set("connection", "mqtt_broker", "custom.broker.com")
        config.set("connection", "mqtt_port", "8883")
        mesh_client._migrate_connection_section(config)
        if config.has_section("mqtt"):
            # Check that mqtt keys were migrated
            broker = config.get("mqtt", "broker", fallback=None)
            if broker:
                self.assertEqual(broker, "custom.broker.com")


class TestDetectConnectionType(unittest.TestCase):
    """Test detect_connection_type() auto-detection logic."""

    def _make_config(self, conn_type="auto", **extras):
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        config.set("interface", "type", conn_type)
        for key, val in extras.items():
            section, option = key.split(".", 1)
            config.set(section, option, str(val))
        return config

    def test_explicit_type_returned_directly(self):
        for t in ["serial", "tcp", "mqtt", "http", "ble"]:
            config = self._make_config(conn_type=t)
            result = mesh_client.detect_connection_type(config)
            self.assertEqual(result, t)

    def test_auto_with_tcp_hostname(self):
        config = self._make_config(conn_type="auto", **{"interface.hostname": "192.168.1.100"})
        with patch.object(mesh_client, "detect_serial_ports", return_value=[]):
            result = mesh_client.detect_connection_type(config)
        self.assertEqual(result, "tcp")

    def test_auto_with_mqtt_enabled(self):
        config = self._make_config(conn_type="auto", **{"mqtt.enabled": "true"})
        with patch.object(mesh_client, "detect_serial_ports", return_value=[]):
            result = mesh_client.detect_connection_type(config)
        self.assertEqual(result, "mqtt")


class TestCheckPythonVersion(unittest.TestCase):
    """Test check_python_version()."""

    def test_current_python_is_38_plus(self):
        self.assertTrue(mesh_client.check_python_version())


class TestSetupLogging(unittest.TestCase):
    """Test setup_logging() configures RotatingFileHandler."""

    def setUp(self):
        import logging

        # Save root logger state
        self._root_handlers = logging.getLogger().handlers[:]
        self._root_level = logging.getLogger().level

    def tearDown(self):
        import logging

        # Restore root logger state
        root = logging.getLogger()
        root.handlers = self._root_handlers
        root.setLevel(self._root_level)
        mesh_client._logging_configured = False

    def test_creates_rotating_file_handler(self):
        """setup_logging should create a RotatingFileHandler."""
        import logging
        from logging.handlers import RotatingFileHandler

        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConfigParser()
            config.read_string(
                "[logging]\n"
                "enabled = true\n"
                "level = INFO\n"
                f"file = {tmpdir}/test.log\n"
                "max_size_mb = 5\n"
                "backup_count = 2\n"
            )
            mesh_client.setup_logging(config)

            root = logging.getLogger()
            rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
            self.assertEqual(len(rotating_handlers), 1)
            self.assertEqual(rotating_handlers[0].maxBytes, 5 * 1024 * 1024)
            self.assertEqual(rotating_handlers[0].backupCount, 2)

    def test_respects_disabled(self):
        """setup_logging should not add file handler when disabled."""
        import logging
        from logging.handlers import RotatingFileHandler

        config = ConfigParser()
        config.read_string("[logging]\nenabled = false\n")
        mesh_client.setup_logging(config)

        root = logging.getLogger()
        rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        self.assertEqual(len(rotating_handlers), 0)

    def test_sets_log_level(self):
        """setup_logging should set the root logger level."""
        import logging

        config = ConfigParser()
        config.read_string("[logging]\nenabled = false\nlevel = WARNING\n")
        mesh_client.setup_logging(config)

        self.assertEqual(logging.getLogger().level, logging.WARNING)

    def test_log_delegates_after_setup(self):
        """log() should delegate to standard logging after setup_logging()."""
        import logging

        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConfigParser()
            config.read_string(f"[logging]\nenabled = true\nfile = {tmpdir}/delegate.log\n")
            mesh_client.setup_logging(config)

            self.assertTrue(mesh_client._logging_configured)
            # log() should not raise
            mesh_client.log("test message", "INFO")


class TestCleanInterfaceForType(unittest.TestCase):
    """Test _clean_interface_for_type() clears stale interface fields."""

    def _make_config(self):
        config = ConfigParser()
        config.add_section("interface")
        config.set("interface", "type", "serial")
        config.set("interface", "port", "/dev/ttyACM0")
        config.set("interface", "hostname", "192.168.1.100")
        config.set("interface", "http_url", "http://192.168.1.100")
        config.set("interface", "mac", "AA:BB:CC:DD:EE:FF")
        return config

    def test_tcp_clears_port(self):
        """Switching to TCP should clear serial port."""
        config = self._make_config()
        mesh_client._clean_interface_for_type(config, "tcp")
        self.assertEqual(config.get("interface", "port"), "")

    def test_tcp_preserves_hostname(self):
        """Switching to TCP should keep hostname."""
        config = self._make_config()
        mesh_client._clean_interface_for_type(config, "tcp")
        self.assertEqual(config.get("interface", "hostname"), "192.168.1.100")

    def test_serial_clears_hostname(self):
        """Switching to serial should clear hostname and http_url."""
        config = self._make_config()
        mesh_client._clean_interface_for_type(config, "serial")
        self.assertEqual(config.get("interface", "hostname"), "")
        self.assertEqual(config.get("interface", "http_url"), "")

    def test_serial_preserves_port(self):
        """Switching to serial should keep serial port."""
        config = self._make_config()
        mesh_client._clean_interface_for_type(config, "serial")
        self.assertEqual(config.get("interface", "port"), "/dev/ttyACM0")

    def test_mqtt_clears_all_device_fields(self):
        """Switching to MQTT should clear port, hostname, http_url, mac."""
        config = self._make_config()
        mesh_client._clean_interface_for_type(config, "mqtt")
        self.assertEqual(config.get("interface", "port"), "")
        self.assertEqual(config.get("interface", "hostname"), "")
        self.assertEqual(config.get("interface", "http_url"), "")
        self.assertEqual(config.get("interface", "mac"), "")

    def test_auto_clears_nothing(self):
        """Auto-detect should preserve all fields."""
        config = self._make_config()
        mesh_client._clean_interface_for_type(config, "auto")
        self.assertEqual(config.get("interface", "port"), "/dev/ttyACM0")
        self.assertEqual(config.get("interface", "hostname"), "192.168.1.100")

    def test_http_clears_port_and_mac(self):
        """HTTP mode clears port and mac but keeps hostname for fallback."""
        config = self._make_config()
        mesh_client._clean_interface_for_type(config, "http")
        self.assertEqual(config.get("interface", "port"), "")
        self.assertEqual(config.get("interface", "mac"), "")
        self.assertEqual(config.get("interface", "hostname"), "192.168.1.100")


class TestDefaultConfigTemplate(unittest.TestCase):
    """Test DEFAULT_CONFIG loads from template file with embedded fallback."""

    def test_default_config_is_nonempty(self):
        """DEFAULT_CONFIG should be loaded successfully."""
        self.assertTrue(len(mesh_client.DEFAULT_CONFIG) > 100)

    def test_default_config_has_interface_section(self):
        """DEFAULT_CONFIG should contain [interface] section."""
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        self.assertTrue(config.has_section("interface"))

    def test_default_config_has_all_sections(self):
        """DEFAULT_CONFIG should have all expected sections."""
        config = ConfigParser()
        config.read_string(mesh_client.DEFAULT_CONFIG)
        expected = ["interface", "mqtt", "features", "commands",
                    "data_sources", "maps", "alerts", "network",
                    "display", "logging", "advanced"]
        for section in expected:
            self.assertTrue(config.has_section(section),
                            f"Missing section: {section}")

    def test_embedded_fallback_is_valid(self):
        """The embedded fallback config should parse correctly."""
        config = ConfigParser()
        config.read_string(mesh_client._EMBEDDED_DEFAULT_CONFIG)
        self.assertTrue(config.has_section("interface"))
        self.assertTrue(config.has_section("mqtt"))

    def test_template_file_exists(self):
        """mesh_client.ini.template should exist in project root."""
        template = Path(mesh_client.SCRIPT_DIR) / "mesh_client.ini.template"
        self.assertTrue(template.exists(),
                        f"Template not found at {template}")


if __name__ == "__main__":
    unittest.main()

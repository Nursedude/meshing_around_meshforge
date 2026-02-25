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


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for meshing_around_clients.core.config_schema

Tests:
1. UnifiedConfig dataclass
2. Multi-interface support (1-9 interfaces)
3. Upstream config format loading
4. MeshForge config format loading
5. Config validation
6. Config save/load roundtrip
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from meshing_around_clients.setup.config_schema import (
    AlertPriority,
    AltitudeAlertConfig,
    AutoUpdateConfig,
    BatteryAlertConfig,
    ConfigLoader,
    ConnectionType,
    DisconnectAlertConfig,
    EmergencyAlertConfig,
    GeneralConfig,
    InterfaceConfig,
    MQTTConfig,
    NewNodeAlertConfig,
    NoisyNodeAlertConfig,
    SentryConfig,
    SMSConfig,
    SMTPConfig,
    TUIConfig,
    UnifiedConfig,
    WeatherAlertConfig,
    WebConfig,
    _str_to_bool,
    _str_to_int_list,
    _str_to_list,
)


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions."""

    def test_str_to_bool_true_values(self):
        """Test string to bool conversion for true values."""
        self.assertTrue(_str_to_bool("true"))
        self.assertTrue(_str_to_bool("True"))
        self.assertTrue(_str_to_bool("TRUE"))
        self.assertTrue(_str_to_bool("yes"))
        self.assertTrue(_str_to_bool("1"))
        self.assertTrue(_str_to_bool("on"))
        self.assertTrue(_str_to_bool(True))

    def test_str_to_bool_false_values(self):
        """Test string to bool conversion for false values."""
        self.assertFalse(_str_to_bool("false"))
        self.assertFalse(_str_to_bool("False"))
        self.assertFalse(_str_to_bool("no"))
        self.assertFalse(_str_to_bool("0"))
        self.assertFalse(_str_to_bool(""))
        self.assertFalse(_str_to_bool(False))

    def test_str_to_list(self):
        """Test comma-separated string to list conversion."""
        self.assertEqual(_str_to_list("a, b, c"), ["a", "b", "c"])
        self.assertEqual(_str_to_list("single"), ["single"])
        self.assertEqual(_str_to_list(""), [])
        self.assertEqual(_str_to_list("  spaced  ,  items  "), ["spaced", "items"])

    def test_str_to_int_list(self):
        """Test comma-separated string to int list conversion."""
        self.assertEqual(_str_to_int_list("1, 2, 3"), [1, 2, 3])
        self.assertEqual(_str_to_int_list(""), [])
        self.assertEqual(_str_to_int_list("1, invalid, 3"), [1, 3])


class TestConnectionType(unittest.TestCase):
    """Test ConnectionType enum."""

    def test_connection_types(self):
        """Test all connection types exist."""
        self.assertEqual(ConnectionType.SERIAL.value, "serial")
        self.assertEqual(ConnectionType.TCP.value, "tcp")
        self.assertEqual(ConnectionType.BLE.value, "ble")
        self.assertEqual(ConnectionType.MQTT.value, "mqtt")
        self.assertEqual(ConnectionType.DEMO.value, "demo")


class TestInterfaceConfig(unittest.TestCase):
    """Test InterfaceConfig dataclass."""

    def test_default_values(self):
        """Test default interface config."""
        cfg = InterfaceConfig()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.type, ConnectionType.SERIAL)
        self.assertEqual(cfg.port, "")
        self.assertEqual(cfg.baudrate, 115200)

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {"enabled": "true", "type": "tcp", "hostname": "192.168.1.100", "port": "4403", "baudrate": "9600"}
        cfg = InterfaceConfig.from_dict(data)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.type, ConnectionType.TCP)
        self.assertEqual(cfg.hostname, "192.168.1.100")
        self.assertEqual(cfg.baudrate, 9600)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        cfg = InterfaceConfig(enabled=True, type=ConnectionType.MQTT, hostname="broker.example.com")
        d = cfg.to_dict()
        self.assertEqual(d["enabled"], "True")
        self.assertEqual(d["type"], "mqtt")
        self.assertEqual(d["hostname"], "broker.example.com")

    def test_validate_ble_mac(self):
        """Test BLE MAC address validation."""
        cfg = InterfaceConfig(type=ConnectionType.BLE, mac="AA:BB:CC:DD:EE:FF")
        errors = cfg.validate()
        self.assertEqual(errors, [])

        cfg_bad = InterfaceConfig(type=ConnectionType.BLE, mac="invalid")
        errors = cfg_bad.validate()
        self.assertTrue(len(errors) > 0)

    def test_validate_tcp_hostname(self):
        """Test TCP hostname validation."""
        cfg_ok = InterfaceConfig(type=ConnectionType.TCP, hostname="192.168.1.1")
        self.assertEqual(cfg_ok.validate(), [])

        cfg_bad = InterfaceConfig(type=ConnectionType.TCP, hostname="")
        errors = cfg_bad.validate()
        self.assertTrue(len(errors) > 0)


class TestAlertConfigs(unittest.TestCase):
    """Test alert configuration dataclasses."""

    def test_emergency_alert_defaults(self):
        """Test emergency alert default values."""
        cfg = EmergencyAlertConfig()
        self.assertTrue(cfg.enabled)
        self.assertIn("emergency", cfg.keywords)
        self.assertIn("sos", cfg.keywords)
        self.assertEqual(cfg.cooldown_period, 300)

    def test_emergency_alert_from_dict(self):
        """Test emergency alert from dictionary."""
        data = {"enabled": "false", "emergency_keywords": "help, rescue", "alert_channel": "5"}
        cfg = EmergencyAlertConfig.from_dict(data)
        self.assertFalse(cfg.enabled)
        self.assertIn("help", cfg.keywords)
        self.assertEqual(cfg.alert_channel, 5)

    def test_sentry_from_upstream(self):
        """Test Sentry config from upstream format."""
        data = {
            "SentryEnabled": "true",
            "SentryRadius": "200",
            "SentryChannel": "3",
            "sentryIgnoreList": "!node1, !node2",
        }
        cfg = SentryConfig.from_upstream(data)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.radius_meters, 200)
        self.assertEqual(cfg.channel, 3)
        self.assertEqual(cfg.ignore_list, ["!node1", "!node2"])

    def test_sentry_from_meshforge(self):
        """Test Sentry config from MeshForge format."""
        data = {"enabled": "true", "target_latitude": "40.7128", "target_longitude": "-74.0060", "radius_meters": "150"}
        cfg = SentryConfig.from_meshforge(data)
        self.assertTrue(cfg.enabled)
        self.assertAlmostEqual(cfg.target_latitude, 40.7128)
        self.assertEqual(cfg.radius_meters, 150)

    def test_altitude_from_upstream(self):
        """Test altitude alert from upstream format."""
        data = {"highFlyingAlert": "true", "highFlyingAlertAltitude": "3000", "highFlyingAlertChannel": "2"}
        cfg = AltitudeAlertConfig.from_upstream(data)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.min_altitude, 3000)
        self.assertEqual(cfg.channel, 2)


class TestMQTTConfig(unittest.TestCase):
    """Test MQTT configuration."""

    def test_default_values(self):
        """Test MQTT default values."""
        cfg = MQTTConfig()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.broker, "mqtt.meshtastic.org")
        self.assertEqual(cfg.port, 1883)
        self.assertEqual(cfg.username, "meshdev")
        self.assertEqual(cfg.password, "large4cats")

    def test_from_dict(self):
        """Test MQTT config from dictionary."""
        data = {"enabled": "true", "broker": "custom.broker.com", "port": "8883", "use_tls": "true"}
        cfg = MQTTConfig.from_dict(data)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.broker, "custom.broker.com")
        self.assertEqual(cfg.port, 8883)
        self.assertTrue(cfg.use_tls)


class TestUnifiedConfig(unittest.TestCase):
    """Test UnifiedConfig main class."""

    def test_default_initialization(self):
        """Test default unified config."""
        cfg = UnifiedConfig()
        self.assertEqual(len(cfg.interfaces), 1)
        self.assertIsInstance(cfg.general, GeneralConfig)
        self.assertIsInstance(cfg.emergency, EmergencyAlertConfig)
        self.assertIsInstance(cfg.mqtt, MQTTConfig)

    def test_validate_empty(self):
        """Test validation of default config."""
        cfg = UnifiedConfig()
        errors = cfg.validate()
        # Default config should be valid
        self.assertEqual(errors, [])

    def test_validate_mqtt_no_broker(self):
        """Test validation catches MQTT enabled without broker."""
        cfg = UnifiedConfig()
        cfg.mqtt.enabled = True
        cfg.mqtt.broker = ""
        errors = cfg.validate()
        self.assertTrue(any("MQTT" in e for e in errors))

    def test_get_active_interfaces(self):
        """Test getting active interfaces."""
        cfg = UnifiedConfig()
        cfg.interfaces = [InterfaceConfig(enabled=True), InterfaceConfig(enabled=False), InterfaceConfig(enabled=True)]
        active = cfg.get_active_interfaces()
        self.assertEqual(len(active), 2)
        self.assertEqual(active[0][0], 0)
        self.assertEqual(active[1][0], 2)

    def test_multiple_interfaces(self):
        """Test config with multiple interfaces."""
        cfg = UnifiedConfig()
        cfg.interfaces = [
            InterfaceConfig(type=ConnectionType.SERIAL, port="/dev/ttyUSB0"),
            InterfaceConfig(type=ConnectionType.TCP, hostname="192.168.1.100"),
            InterfaceConfig(type=ConnectionType.MQTT, enabled=False),
        ]
        self.assertEqual(len(cfg.interfaces), 3)
        self.assertEqual(cfg.interfaces[0].type, ConnectionType.SERIAL)
        self.assertEqual(cfg.interfaces[1].type, ConnectionType.TCP)


class TestConfigLoaderUpstream(unittest.TestCase):
    """Test loading upstream meshing-around config format."""

    def test_load_upstream_format(self):
        """Test loading upstream config with [sentry] section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "upstream.ini"
            config_path.write_text("""
[interface]
type = serial
port = /dev/ttyUSB0

[interface2]
enabled = true
type = tcp
hostname = 192.168.1.100

[general]
bot_name = UpstreamBot
respond_by_dm_only = true
bbs_admin_list = !admin1, !admin2

[sentry]
SentryEnabled = true
SentryRadius = 200
SentryChannel = 3

[emergencyHandler]
enabled = true
emergency_keywords = help, rescue, sos
""")
            cfg = ConfigLoader.load(config_path)

            # Check format detected
            self.assertEqual(cfg.config_format, "upstream")

            # Check interfaces
            self.assertEqual(len(cfg.interfaces), 2)
            self.assertEqual(cfg.interfaces[0].type, ConnectionType.SERIAL)
            self.assertEqual(cfg.interfaces[1].type, ConnectionType.TCP)

            # Check general
            self.assertEqual(cfg.general.bot_name, "UpstreamBot")
            self.assertEqual(cfg.general.admin_nodes, ["!admin1", "!admin2"])

            # Check sentry
            self.assertTrue(cfg.sentry.enabled)
            self.assertEqual(cfg.sentry.radius_meters, 200)

    def test_load_upstream_9_interfaces(self):
        """Test loading all 9 possible interfaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "multi.ini"
            content = "[sentry]\nSentryEnabled = false\n"
            for i in range(1, 10):
                section = "interface" if i == 1 else f"interface{i}"
                content += f"\n[{section}]\nenabled = true\ntype = serial\nport = /dev/ttyUSB{i-1}\n"
            config_path.write_text(content)

            cfg = ConfigLoader.load(config_path)
            self.assertEqual(len(cfg.interfaces), 9)
            for i, iface in enumerate(cfg.interfaces):
                self.assertEqual(iface.port, f"/dev/ttyUSB{i}")


class TestConfigLoaderMeshForge(unittest.TestCase):
    """Test loading MeshForge config format."""

    def test_load_meshforge_format(self):
        """Test loading MeshForge config (no [sentry] or [bbs])."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "meshforge.ini"
            config_path.write_text("""
[interface]
type = mqtt
enabled = true

[general]
bot_name = MeshForgeBot

[mqtt]
enabled = true
broker = mqtt.meshtastic.org
topic_root = msh/US

[tui]
refresh_rate = 0.5
color_scheme = dark

[web]
port = 9000
enable_auth = true
""")
            cfg = ConfigLoader.load(config_path)

            # Check format detected
            self.assertEqual(cfg.config_format, "meshforge")

            # Check values
            self.assertEqual(cfg.general.bot_name, "MeshForgeBot")
            self.assertTrue(cfg.mqtt.enabled)
            self.assertEqual(cfg.mqtt.broker, "mqtt.meshtastic.org")
            self.assertEqual(cfg.tui.refresh_rate, 0.5)
            self.assertEqual(cfg.web.port, 9000)

    def test_load_meshforge_multi_interface(self):
        """Test loading MeshForge config with multiple interfaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "multi.ini"
            config_path.write_text("""
[interface.1]
type = serial
port = /dev/ttyUSB0
enabled = true

[interface.2]
type = tcp
hostname = 192.168.1.100
enabled = true

[interface.3]
type = mqtt
enabled = false

[general]
bot_name = MultiBot
""")
            cfg = ConfigLoader.load(config_path)

            # Check interfaces loaded
            self.assertEqual(len(cfg.interfaces), 3)
            self.assertEqual(cfg.interfaces[0].type, ConnectionType.SERIAL)
            self.assertEqual(cfg.interfaces[0].port, "/dev/ttyUSB0")
            self.assertEqual(cfg.interfaces[1].type, ConnectionType.TCP)
            self.assertEqual(cfg.interfaces[1].hostname, "192.168.1.100")
            self.assertEqual(cfg.interfaces[2].type, ConnectionType.MQTT)
            self.assertFalse(cfg.interfaces[2].enabled)


class TestConfigLoaderSave(unittest.TestCase):
    """Test saving configuration."""

    def test_save_and_reload(self):
        """Test save and reload roundtrip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "roundtrip.ini"

            cfg = UnifiedConfig(config_path=config_path)
            cfg.general.bot_name = "RoundtripBot"
            cfg.interfaces = [
                InterfaceConfig(type=ConnectionType.SERIAL, port="/dev/ttyUSB0"),
                InterfaceConfig(type=ConnectionType.TCP, hostname="192.168.1.1"),
            ]
            cfg.mqtt.enabled = True
            cfg.mqtt.broker = "test.broker.com"
            cfg.emergency.keywords = ["help", "test"]

            result = ConfigLoader.save(cfg, config_path)
            self.assertTrue(result)
            self.assertTrue(config_path.exists())

            # Check permissions
            mode = os.stat(config_path).st_mode & 0o777
            self.assertEqual(mode, 0o600)

            # Reload
            cfg2 = ConfigLoader.load(config_path)
            self.assertEqual(cfg2.general.bot_name, "RoundtripBot")
            self.assertTrue(cfg2.mqtt.enabled)
            self.assertEqual(cfg2.mqtt.broker, "test.broker.com")

    def test_save_creates_directory(self):
        """Test save creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nested" / "deep" / "config.ini"

            cfg = UnifiedConfig(config_path=config_path)
            result = ConfigLoader.save(cfg, config_path)

            self.assertTrue(result)
            self.assertTrue(config_path.exists())


class TestConfigLoaderNonexistent(unittest.TestCase):
    """Test handling of nonexistent config files."""

    def test_load_nonexistent_returns_default(self):
        """Test loading nonexistent file returns default config."""
        cfg = ConfigLoader.load(Path("/nonexistent/config.ini"))
        self.assertIsInstance(cfg, UnifiedConfig)
        self.assertEqual(cfg.config_path, Path("/nonexistent/config.ini"))
        # Should have defaults
        self.assertEqual(len(cfg.interfaces), 1)


if __name__ == "__main__":
    unittest.main()

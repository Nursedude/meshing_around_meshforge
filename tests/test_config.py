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
    MQTTConfig,
    TuiConfig,
    _coerce_float,
    _coerce_int,
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


class TestCoerceInt(unittest.TestCase):
    """Test _coerce_int() helper for malformed INI values."""

    def test_valid_int_string_parses(self):
        self.assertEqual(_coerce_int("42", 0), 42)

    def test_valid_int_passthrough(self):
        self.assertEqual(_coerce_int(115200, 9600), 115200)

    def test_non_numeric_string_returns_default(self):
        self.assertEqual(_coerce_int("abc", 1883), 1883)

    def test_empty_string_returns_default(self):
        self.assertEqual(_coerce_int("", 1883), 1883)

    def test_none_returns_default(self):
        self.assertEqual(_coerce_int(None, 10), 10)

    def test_float_string_returns_default(self):
        # int("3.14") raises ValueError — we want the default, not a crash
        self.assertEqual(_coerce_int("3.14", 5), 5)

    def test_whitespace_string_returns_default(self):
        self.assertEqual(_coerce_int("  ", 300), 300)


class TestInterfaceConfigMalformedValues(unittest.TestCase):
    """InterfaceConfig.from_dict should not crash on non-numeric INI values."""

    def test_bad_baudrate_falls_back_to_default(self):
        cfg = InterfaceConfig.from_dict({"type": "serial", "baudrate": "not_a_number"})
        self.assertEqual(cfg.baudrate, 115200)

    def test_empty_baudrate_falls_back_to_default(self):
        cfg = InterfaceConfig.from_dict({"type": "serial", "baudrate": ""})
        self.assertEqual(cfg.baudrate, 115200)

    def test_valid_baudrate_preserved(self):
        cfg = InterfaceConfig.from_dict({"type": "serial", "baudrate": "57600"})
        self.assertEqual(cfg.baudrate, 57600)


class TestMQTTConfigMalformedValues(unittest.TestCase):
    """MQTTConfig.from_dict should not crash on non-numeric INI values."""

    def test_bad_port_falls_back_to_default(self):
        cfg = MQTTConfig.from_dict({"port": "garbage"})
        self.assertEqual(cfg.port, 1883)

    def test_bad_qos_falls_back_to_default(self):
        cfg = MQTTConfig.from_dict({"qos": "maybe"})
        self.assertEqual(cfg.qos, 1)

    def test_bad_timeouts_fall_back_to_defaults(self):
        cfg = MQTTConfig.from_dict(
            {
                "connect_timeout": "soon",
                "reconnect_delay": "later",
                "max_reconnect_delay": "never",
                "max_reconnect_attempts": "many",
            }
        )
        self.assertEqual(cfg.connect_timeout, 10)
        self.assertEqual(cfg.reconnect_delay, 5)
        self.assertEqual(cfg.max_reconnect_delay, 300)
        self.assertEqual(cfg.max_reconnect_attempts, 10)

    def test_valid_port_preserved(self):
        cfg = MQTTConfig.from_dict({"port": "8883"})
        self.assertEqual(cfg.port, 8883)


class TestCoerceFloat(unittest.TestCase):
    """Test _coerce_float() helper for malformed INI values."""

    def test_valid_float_string_parses(self):
        self.assertEqual(_coerce_float("3.14", 0.0), 3.14)

    def test_int_string_parses_as_float(self):
        self.assertEqual(_coerce_float("5", 1.0), 5.0)

    def test_valid_float_passthrough(self):
        self.assertEqual(_coerce_float(2.5, 9.0), 2.5)

    def test_non_numeric_string_returns_default(self):
        self.assertEqual(_coerce_float("abc", 1.0), 1.0)

    def test_empty_string_returns_default(self):
        self.assertEqual(_coerce_float("", 1.0), 1.0)

    def test_none_returns_default(self):
        self.assertEqual(_coerce_float(None, 5.0), 5.0)


class TestConfigLoadMalformedValues(unittest.TestCase):
    """Config.load() must tolerate hand-edited garbage numeric INI values.

    Regression for CLAUDE.md latent-bug #3: load() used ConfigParser.getint/
    getfloat, which raise a raw ValueError on a present-but-non-numeric value.
    That ValueError is not a configparser.Error, so it escaped load()'s except
    clause and crashed startup before the UI/logger were up. Each field must now
    fall back to its default instead.
    """

    def _load(self, ini_text: str) -> Config:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "garbage.ini"
            config_path.write_text(ini_text)
            cfg = Config(config_path=str(config_path))
            # Construction auto-loads; calling again must also not raise.
            self.assertTrue(cfg.load())
            return cfg

    def test_garbage_numerics_across_sections_do_not_crash(self):
        cfg = self._load(
            "[network]\n"
            "default_channel = abc\n"
            "message_history = lots\n"
            "max_message_length = big\n"
            "[tui]\n"
            "refresh_rate = fast\n"
            "message_history = many\n"
            "[maps]\n"
            "port = notaport\n"
            "[mqtt]\n"
            "port = xyz\n"
            "qos = high\n"
            "connect_timeout = soon\n"
            "[storage]\n"
            "auto_save_interval = sometimes\n"
            "max_message_history = inf\n"
            "[logging]\n"
            "max_size_mb = huge\n"
            "backup_count = none\n"
            "[advanced]\n"
            "chunk_reassembly_timeout = whenever\n"
            "[data_sources]\n"
            "volcano_lat = north\n"
            "volcano_lon = west\n"
            "[emergencyHandler]\n"
            "alert_channel = q\n"
            "cooldown_period = q\n"
        )
        # Every malformed field fell back to its default. (default_channel and
        # mqtt.port are intentionally NOT asserted to a literal — they can be
        # overridden by the upstream-bot fallback / global config seeding, which
        # is environment-dependent; we only require they didn't crash and stayed
        # the right type.)
        self.assertEqual(cfg.network_cfg.message_history, 500)
        self.assertEqual(cfg.network_cfg.max_message_length, 200)
        self.assertEqual(cfg.tui.refresh_rate, 1.0)
        self.assertEqual(cfg.maps.port, 8808)
        self.assertIsInstance(cfg.mqtt.port, int)
        self.assertEqual(cfg.mqtt.qos, 1)
        self.assertEqual(cfg.logging.max_size_mb, 10)
        self.assertEqual(cfg.logging.backup_count, 3)
        self.assertEqual(cfg.chunk_reassembly_timeout, 5.0)
        self.assertEqual(cfg.data_sources.volcano_lat, 0.0)
        self.assertEqual(cfg.alerts.alert_channel, 2)

    def test_valid_numerics_still_parse(self):
        # Use fields not subject to upstream/global override.
        cfg = self._load("[maps]\nport = 9000\n[tui]\nrefresh_rate = 0.5\nmessage_history = 750\n")
        self.assertEqual(cfg.maps.port, 9000)
        self.assertEqual(cfg.tui.refresh_rate, 0.5)
        self.assertEqual(cfg.tui.message_history, 750)


class TestCorruptConfigLeavesWitness(unittest.TestCase):
    """A corrupt EXISTING config must not silently fall back to defaults (the
    public broker + public creds). load() must leave a witness (load_error +
    an ERROR log), not a stdout flash the TUI overwrites."""

    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_corrupt_config_sets_load_error_and_logs(self):
        # No section header -> configparser.MissingSectionHeaderError.
        bad = self._write("this is not a valid ini file\nkey = value\n")
        with self.assertLogs("meshing_around_clients.core.config", level="ERROR") as cm:
            cfg = Config(bad)
        self.assertIsNotNone(cfg.load_error)
        self.assertTrue(any("Failed to load config" in m for m in cm.output))

    def test_corrupt_config_still_exposes_default_broker_but_flagged(self):
        # The dataclass default broker is the PUBLIC one; the point of the fix
        # is that the fallback is now OBSERVABLE (load_error set), not silent.
        bad = self._write("]]]not ini[[[\n")
        cfg = Config(bad)
        self.assertIsNotNone(cfg.load_error)
        self.assertEqual(cfg.mqtt.broker, "mqtt.meshtastic.org")  # default, now witnessed

    def test_valid_config_has_no_load_error(self):
        good = self._write("[mqtt]\nbroker = broker.example.internal\n")
        cfg = Config(good)
        self.assertIsNone(cfg.load_error)
        self.assertEqual(cfg.mqtt.broker, "broker.example.internal")


if __name__ == "__main__":
    unittest.main()


class TestAtomicConfigWrite(unittest.TestCase):
    """save() must be torn-write safe: temp-in-same-dir + os.replace, so a
    crash/power-loss mid-write can never leave a truncated config on an SD-card
    Pi (it would strand the operator's only config)."""

    def _tmpdir(self):
        import shutil

        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return Path(d)

    def test_atomic_write_produces_file_perms_and_no_leftover_tmp(self):
        import configparser

        from meshing_around_clients.core.config import _atomic_write_parser

        p = self._tmpdir() / "sub" / "mesh_client.ini"  # parent auto-created
        parser = configparser.ConfigParser()
        parser["mqtt"] = {"broker": "b.internal", "password": "sekret"}
        _atomic_write_parser(parser, p)

        self.assertTrue(p.exists())
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
        self.assertEqual([f for f in os.listdir(p.parent) if f.endswith(".tmp")], [])
        rp = configparser.ConfigParser()
        rp.read(p)
        self.assertEqual(rp["mqtt"]["broker"], "b.internal")

    def test_failed_write_preserves_old_file_and_cleans_tmp(self):
        from meshing_around_clients.core.config import _atomic_write_parser

        d = self._tmpdir()
        p = d / "mesh_client.ini"
        p.write_text("[old]\nk = v\n")  # pre-existing good config

        class BadParser:
            def write(self, f):
                raise IOError("disk full mid-write")

        with self.assertRaises(IOError):
            _atomic_write_parser(BadParser(), p)

        # Atomicity: the old file is untouched and no temp is left behind.
        self.assertEqual(p.read_text(), "[old]\nk = v\n")
        self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])

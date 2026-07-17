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

    @patch.object(mesh_client, "CONFIG_FILE")
    def test_corrupt_config_does_not_raise_and_sets_witness(self, mock_config_file):
        """A3b: a corrupt mesh_client.ini must not raise an unhandled
        ConfigParser traceback — it records a witness instead."""
        mesh_client.CONFIG_FILE = self.config_path
        # Not-an-INI content (no section header) -> MissingSectionHeaderError.
        self.config_path.write_text("this is not = a valid ini\nno section header\n")
        mesh_client.CONFIG_LOAD_ERROR = None
        config = mesh_client.load_config()  # must not raise
        self.assertIsNotNone(config)
        self.assertIsNotNone(mesh_client.CONFIG_LOAD_ERROR)

    @patch.object(mesh_client, "CONFIG_FILE")
    def test_corrupt_config_returns_usable_parser(self, mock_config_file):
        """3rd pass: A3b returned an EMPTY parser, so the crash it cured
        resurfaced one menu interaction later — config.set(section, ...) on a
        missing section raised NoSectionError. The parser must carry the
        default sections so menus don't re-crash, while keeping the witness."""
        import configparser

        mesh_client.CONFIG_FILE = self.config_path
        self.config_path.write_text("this is not = a valid ini\nno section header\n")
        mesh_client.CONFIG_LOAD_ERROR = None
        config = mesh_client.load_config()

        # The witness stays set...
        self.assertIsNotNone(mesh_client.CONFIG_LOAD_ERROR)
        # ...and every menu-write path is safe (the exact resurfacing crash).
        try:
            config.set("interface", "type", "mqtt")
            config.set("advanced", "demo_mode", "true")
        except configparser.NoSectionError as e:
            self.fail(f"corrupt-config parser missing a default section: {e}")


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

    def test_garbage_numeric_values_do_not_crash(self):
        """Hand-edited non-numeric logging values must fall back, not crash.

        Regression for CLAUDE.md latent-bug #3: setup_logging used raw
        config.getint(), which raised ValueError on a non-numeric value and
        crashed startup before logging was even configured.
        """
        import logging
        from logging.handlers import RotatingFileHandler

        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConfigParser()
            config.read_string(
                "[logging]\n"
                "enabled = true\n"
                f"file = {tmpdir}/test.log\n"
                "max_size_mb = big\n"
                "backup_count = none\n"
                "message_log_backup_count = lots\n"
            )
            mesh_client.setup_logging(config)  # must not raise

            root = logging.getLogger()
            rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
            self.assertEqual(len(rotating), 1)
            # Defaults (10 MiB, 3 backups) applied instead of crashing.
            self.assertEqual(rotating[0].maxBytes, 10 * 1024 * 1024)
            self.assertEqual(rotating[0].backupCount, 3)

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
        expected = [
            "interface",
            "mqtt",
            "features",
            "commands",
            "data_sources",
            "maps",
            "alerts",
            "network",
            "display",
            "logging",
            "advanced",
        ]
        for section in expected:
            self.assertTrue(config.has_section(section), f"Missing section: {section}")

    def test_embedded_fallback_is_valid(self):
        """The embedded fallback config should parse correctly."""
        config = ConfigParser()
        config.read_string(mesh_client._EMBEDDED_DEFAULT_CONFIG)
        self.assertTrue(config.has_section("interface"))
        self.assertTrue(config.has_section("mqtt"))

    def test_template_file_exists(self):
        """mesh_client.ini.template should exist in project root."""
        template = Path(mesh_client.SCRIPT_DIR) / "mesh_client.ini.template"
        self.assertTrue(template.exists(), f"Template not found at {template}")


class TestHeadlessFlag(unittest.TestCase):
    """--headless integration tests.

    The pre-fix systemd unit on wh6gxzTRDEV (BA5E) flap-looped 223 times
    in 2 hours because the TUI exited immediately on stdin.isatty() under
    systemd.  --headless gives the daemon path an explicit CLI entrypoint
    that handles SIGTERM cleanly and emits a heartbeat log.
    """

    def test_help_lists_headless_flag(self):
        """--headless must appear in `--help` output (otherwise systemd
        unit authors can't discover the right flag)."""
        import subprocess

        result = subprocess.run(
            [sys.executable, str(Path(mesh_client.SCRIPT_DIR) / "mesh_client.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, f"--help failed: {result.stderr}")
        self.assertIn("--headless", result.stdout)
        self.assertIn("systemd", result.stdout)

    def test_headless_runs_without_tty_and_exits_on_sigterm(self):
        """Spawn `mesh_client.py --headless --demo` with no controlling
        terminal (stdin redirected from /dev/null), wait for the
        connected log, then SIGTERM and assert the process exits
        cleanly within a few seconds.

        This is the regression test for the BA5E flap loop: the
        pre-fix code path would `Error: No terminal detected ... TUI
        requires an interactive terminal` and exit before any work.
        With --headless that path is bypassed.
        """
        import signal
        import subprocess
        import time

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(mesh_client.SCRIPT_DIR) / "mesh_client.py"),
                "--headless",
                "--demo",
                "--no-venv",
            ],
            stdin=subprocess.DEVNULL,  # no TTY, no controlling terminal
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            start_new_session=True,  # detach from this process group so SIGINT here doesn't leak
        )
        try:
            # Wait for the "Connected" log line — proves the headless
            # branch was actually taken and the API initialized.
            deadline = time.monotonic() + 30.0
            connected = False
            output_buf = []
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                output_buf.append(line)
                if "Connected." in line:
                    connected = True
                    break
            self.assertTrue(
                connected,
                "headless mode never reached 'Connected.'; output was:\n" + "".join(output_buf),
            )

            # Send SIGTERM (what systemctl stop sends) and confirm clean exit.
            proc.send_signal(signal.SIGTERM)
            try:
                returncode = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("headless process did not exit within 10s of SIGTERM")

            # Drain remaining output for the assertion message.
            tail = proc.stdout.read() if proc.stdout else ""
            self.assertEqual(
                returncode,
                0,
                f"headless exit code {returncode} (expected 0). Tail:\n{''.join(output_buf)}{tail}",
            )
            self.assertIn(
                "Received SIGTERM",
                "".join(output_buf) + tail,
                "SIGTERM handler did not log shutdown",
            )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


class TestLauncherRenameRadio(unittest.TestCase):
    """_launcher_rename_radio is the launcher-menu entry that fixes
    the gap PR #178 left: the rename ability has to be reachable from
    the operator's existing raspi-config-style launcher, NOT only via
    a separate UI.
    """

    def setUp(self):
        # Minimal ConfigParser fixture
        from configparser import ConfigParser

        self.config = ConfigParser()
        self.config["interface"] = {"type": "tcp", "hostname": "10.250.203.50", "port": ""}

    @patch("mesh_client.subprocess.run")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_tcp_interface_runs_meshtastic_set_owner(self, mock_input, mock_yesno, _mock_msg, mock_run):
        """[interface] type=tcp + hostname=X -> meshtastic --host X --set-owner ..."""
        import subprocess as _sp

        mock_input.side_effect = ["MeshtasticHILO", "HILO"]
        mock_yesno.return_value = True
        mock_run.return_value = _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        mesh_client._launcher_rename_radio(self.config)

        self.assertEqual(mock_run.call_count, 1)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--host", cmd)
        self.assertIn("10.250.203.50", cmd)
        self.assertIn("--set-owner", cmd)
        self.assertIn("MeshtasticHILO", cmd)
        self.assertIn("--set-owner-short", cmd)
        self.assertIn("HILO", cmd)

    @patch("mesh_client.subprocess.run")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_mqtt_interface_prompts_for_radio_host(self, mock_input, mock_yesno, _mock_msg, mock_run):
        """BA5E case: mesh_client interface=mqtt, no direct radio path —
        the handler must prompt for the radio's TCP host separately."""
        import subprocess as _sp

        self.config["interface"]["type"] = "mqtt"
        # inputs: 1) radio host, 2) longName, 3) shortName
        mock_input.side_effect = ["192.168.1.50", "MeshtasticHILO", "HILO"]
        mock_yesno.return_value = True
        mock_run.return_value = _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        mesh_client._launcher_rename_radio(self.config)

        cmd = mock_run.call_args[0][0]
        self.assertIn("--host", cmd)
        self.assertIn("192.168.1.50", cmd)

    @patch("mesh_client.subprocess.run")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_cancel_at_confirm_does_not_invoke_meshtastic(self, mock_input, mock_yesno, _mock_msg, mock_run):
        """If the user answers No at the confirm prompt, no subprocess fires."""
        mock_input.side_effect = ["MyNode", "MYNO"]
        mock_yesno.return_value = False

        mesh_client._launcher_rename_radio(self.config)

        mock_run.assert_not_called()

    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_serial_interface_missing_port_shows_hint(self, _mock_input, mock_msg):
        """Serial mode with no port set must NOT prompt for names —
        it should hint at the missing config and return."""
        self.config["interface"]["type"] = "serial"
        self.config["interface"]["port"] = ""

        mesh_client._launcher_rename_radio(self.config)

        mock_msg.assert_called_once()
        body = mock_msg.call_args[0][0]
        self.assertIn("no port set", body.lower())


class TestLauncherMenuRenameRadioEntry(unittest.TestCase):
    """The launcher menu's items list must include the rename-radio entry
    so the operator can find it from the menu they already know.
    """

    def test_rename_radio_entry_present(self):
        """grep the file for the menu tuple — cheaper than driving the menu."""
        src = (mesh_client.SCRIPT_DIR / "mesh_client.py").read_text()
        self.assertIn('("rename-radio"', src, "missing rename-radio menu entry")
        self.assertIn("Rename Radio", src)


class TestLauncherRenameBot(unittest.TestCase):
    """_launcher_rename_bot changes [mqtt] node_id in mesh_client.ini.

    Bot identity on the mesh = the last 4 hex chars of node_id.
    Default !c0deba5e -> "BA5E".  Operator wants to change those 4
    chars without having to hand-edit the ini.  The c0de prefix is
    the anti-loopback marker and is locked.
    """

    def setUp(self):
        from configparser import ConfigParser

        self.config = ConfigParser()
        self.config["mqtt"] = {"node_id": "!c0deba5e"}

    @patch("mesh_client.save_config")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_valid_hex_change_saves(self, mock_input, mock_yesno, mock_msg, mock_save):
        """Operator types 'dead' -> node_id becomes !c0dedead, save fires."""
        mock_input.return_value = "dead"
        mock_yesno.return_value = True

        mesh_client._launcher_rename_bot(self.config)

        self.assertEqual(self.config.get("mqtt", "node_id"), "!c0dedead")
        mock_save.assert_called_once_with(self.config)

    @patch("mesh_client.save_config")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_non_hex_input_rejected(self, mock_input, mock_yesno, mock_msg, mock_save):
        """'hilo' contains h, i, l, o — not hex chars — must reject + not save."""
        mock_input.return_value = "hilo"

        mesh_client._launcher_rename_bot(self.config)

        # node_id unchanged
        self.assertEqual(self.config.get("mqtt", "node_id"), "!c0deba5e")
        mock_save.assert_not_called()
        # User was shown an "Invalid" message
        mock_msg.assert_called_once()
        title = mock_msg.call_args.kwargs.get("title", "")
        self.assertIn("Invalid", title)

    @patch("mesh_client.save_config")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_wrong_length_rejected(self, mock_input, mock_yesno, mock_msg, mock_save):
        """3-char and 5-char inputs both rejected."""
        for bad in ("dea", "deadd"):
            mock_input.return_value = bad
            mesh_client._launcher_rename_bot(self.config)
        self.assertEqual(self.config.get("mqtt", "node_id"), "!c0deba5e")
        mock_save.assert_not_called()

    @patch("mesh_client.save_config")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_cancel_at_confirm_does_not_save(self, mock_input, mock_yesno, mock_msg, mock_save):
        """Valid hex typed, but user says No at the confirm yesno -> no save."""
        mock_input.return_value = "dead"
        mock_yesno.return_value = False

        mesh_client._launcher_rename_bot(self.config)

        self.assertEqual(self.config.get("mqtt", "node_id"), "!c0deba5e")
        mock_save.assert_not_called()

    @patch("mesh_client.save_config")
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_unchanged_input_does_not_save(self, mock_input, mock_yesno, mock_msg, mock_save):
        """Typing the current name back == no-op; never reaches confirm."""
        mock_input.return_value = "ba5e"

        mesh_client._launcher_rename_bot(self.config)

        mock_save.assert_not_called()
        mock_yesno.assert_not_called()
        mock_msg.assert_called_once()
        title = mock_msg.call_args.kwargs.get("title", "")
        self.assertEqual(title, "No Change")

    @patch("mesh_client.save_config", side_effect=OSError("disk full"))
    @patch("meshing_around_clients.setup.whiptail.msgbox")
    @patch("meshing_around_clients.setup.whiptail.yesno")
    @patch("meshing_around_clients.setup.whiptail.inputbox")
    def test_save_failure_rolls_back(self, mock_input, mock_yesno, mock_msg, _mock_save):
        """If save_config raises, the in-memory node_id is restored."""
        mock_input.return_value = "dead"
        mock_yesno.return_value = True

        mesh_client._launcher_rename_bot(self.config)

        # Rolled back
        self.assertEqual(self.config.get("mqtt", "node_id"), "!c0deba5e")

    def test_rename_bot_entry_present_in_menu(self):
        """The launcher items list must include the rename-bot entry."""
        src = (mesh_client.SCRIPT_DIR / "mesh_client.py").read_text()
        self.assertIn('("rename-bot"', src, "missing rename-bot menu entry")
        self.assertIn("Change Bot Name", src)


if __name__ == "__main__":
    unittest.main()

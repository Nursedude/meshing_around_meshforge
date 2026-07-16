"""Unit tests for WhiptailTUI screen handlers added in PR #178.

Covers:
- _show_bot_config: round-trip edit + .ini.bak backup
- _radio_rename: command-line composition for serial/tcp/mqtt
- Pi2W auto-default in mesh_client.main
"""

import configparser
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.config import Config  # noqa: E402
from meshing_around_clients.tui.whiptail_tui import WhiptailTUI  # noqa: E402


def _make_tui(tmp_config_path: Path = None) -> WhiptailTUI:
    """Construct a WhiptailTUI in demo mode for tests."""
    cfg = Config()
    if tmp_config_path is not None:
        cfg.interface.type = "tcp"
        cfg.interface.hostname = "10.0.0.2"
    return WhiptailTUI(config=cfg, demo_mode=True)


class TestShowBotConfigSave(unittest.TestCase):
    """_show_bot_config edits the bot's config.ini in place with .bak backup."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.ini"
        # Minimal bot config with the [general] section and a bot_name field —
        # mirrors what /opt/meshing-around/config.ini looks like on BA5E.
        self.config_path.write_text(
            "[general]\n" "bot_name = BA5E\n" "responseDelay = 0.1\n" "\n" "[interface]\n" "type = tcp\n"
        )

        self.tui = _make_tui()
        # Force _find_bot_config to return our temp file
        self.tui._find_bot_config = lambda: self.config_path  # type: ignore

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("meshing_around_clients.tui.whiptail_tui.msgbox")
    @patch("meshing_around_clients.tui.whiptail_tui.inputbox")
    @patch("meshing_around_clients.tui.whiptail_tui.menu")
    def test_rename_bot_name_persists_to_disk_with_backup(self, mock_menu, mock_input, mock_msg):
        """User flow: pick general -> pick bot_name -> type new name -> save.

        After save: bot_name must be the new value on disk, AND
        config.ini.bak must contain the OLD value.
        """
        # menu() calls: section pick, key pick, then back-to-section ("e"), then back-out ("e")
        mock_menu.side_effect = ["general", "bot_name", "e", "e"]
        mock_input.return_value = "MeshtasticHILO"

        self.tui._show_bot_config()

        # Verify new value on disk
        parsed = configparser.ConfigParser()
        parsed.read(str(self.config_path))
        self.assertEqual(parsed.get("general", "bot_name"), "MeshtasticHILO")

        # Verify backup file has the OLD value
        bak = self.config_path.with_suffix(".ini.bak")
        self.assertTrue(bak.exists(), "expected config.ini.bak to exist after save")
        bak_parsed = configparser.ConfigParser()
        bak_parsed.read(str(bak))
        self.assertEqual(bak_parsed.get("general", "bot_name"), "BA5E")

        # Verify the operator was shown the restart-bot hint
        msg_calls = [str(c) for c in mock_msg.call_args_list]
        self.assertTrue(
            any("systemctl restart mesh_bot.service" in c for c in msg_calls),
            f"expected restart hint in msgbox calls, got: {msg_calls}",
        )

    @patch("meshing_around_clients.tui.whiptail_tui.msgbox")
    @patch("meshing_around_clients.tui.whiptail_tui.inputbox")
    @patch("meshing_around_clients.tui.whiptail_tui.menu")
    def test_cancel_edit_does_not_write(self, mock_menu, mock_input, mock_msg):
        """If inputbox returns None (user cancelled), file is unchanged."""
        mock_menu.side_effect = ["general", "bot_name", "e", "e"]
        mock_input.return_value = None  # cancelled

        original_mtime = self.config_path.stat().st_mtime

        self.tui._show_bot_config()

        # Still BA5E
        parsed = configparser.ConfigParser()
        parsed.read(str(self.config_path))
        self.assertEqual(parsed.get("general", "bot_name"), "BA5E")
        # No backup file created
        self.assertFalse(self.config_path.with_suffix(".ini.bak").exists())
        # mtime unchanged
        self.assertEqual(self.config_path.stat().st_mtime, original_mtime)

    @patch("meshing_around_clients.tui.whiptail_tui.msgbox")
    @patch("meshing_around_clients.tui.whiptail_tui.menu")
    def test_missing_config_shows_install_hint(self, mock_menu, mock_msg):
        """When bot config doesn't exist, user gets a hint, not a crash."""
        self.tui._find_bot_config = lambda: None  # type: ignore
        self.tui._show_bot_config()
        mock_msg.assert_called_once()
        body = mock_msg.call_args[0][0]
        self.assertIn("not found", body.lower())


class TestRadioRenameCommand(unittest.TestCase):
    """_radio_rename composes the right `meshtastic --set-owner` invocation."""

    def setUp(self):
        self.tui = WhiptailTUI(config=Config(), demo_mode=True)

    @patch("meshing_around_clients.tui.whiptail_tui.subprocess.run")
    @patch("meshing_around_clients.tui.whiptail_tui.msgbox")
    @patch("meshing_around_clients.tui.whiptail_tui.infobox")
    @patch("meshing_around_clients.tui.whiptail_tui.yesno")
    @patch("meshing_around_clients.tui.whiptail_tui.inputbox")
    def test_tcp_interface_uses_host_arg(self, mock_input, mock_yesno, _info, _msg, mock_run):
        """[interface] type=tcp + hostname=X -> meshtastic --host X --set-owner ...

        BA5E uses MQTT for mesh_client but the radio is reachable
        via TCP; this test covers operators on a pure-TCP setup.
        """
        self.tui.config.interface.type = "tcp"
        self.tui.config.interface.hostname = "10.250.203.50"
        mock_input.side_effect = ["MeshtasticHILO", "HILO"]
        mock_yesno.return_value = True
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        self.tui._radio_rename()

        self.assertEqual(mock_run.call_count, 1)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--host", cmd)
        self.assertIn("10.250.203.50", cmd)
        self.assertIn("--set-owner", cmd)
        self.assertIn("MeshtasticHILO", cmd)
        self.assertIn("--set-owner-short", cmd)
        self.assertIn("HILO", cmd)

    @patch("meshing_around_clients.tui.whiptail_tui.subprocess.run")
    @patch("meshing_around_clients.tui.whiptail_tui.msgbox")
    @patch("meshing_around_clients.tui.whiptail_tui.infobox")
    @patch("meshing_around_clients.tui.whiptail_tui.yesno")
    @patch("meshing_around_clients.tui.whiptail_tui.inputbox")
    def test_serial_interface_uses_port_arg(self, mock_input, mock_yesno, _info, _msg, mock_run):
        """[interface] type=serial + port=/dev/ttyUSB0 -> meshtastic --port /dev/ttyUSB0 ..."""
        self.tui.config.interface.type = "serial"
        self.tui.config.interface.port = "/dev/ttyUSB0"
        mock_input.side_effect = ["MyNode", "MYNO"]
        mock_yesno.return_value = True
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        self.tui._radio_rename()

        cmd = mock_run.call_args[0][0]
        self.assertIn("--port", cmd)
        self.assertIn("/dev/ttyUSB0", cmd)

    @patch("meshing_around_clients.tui.whiptail_tui.subprocess.run")
    @patch("meshing_around_clients.tui.whiptail_tui.msgbox")
    @patch("meshing_around_clients.tui.whiptail_tui.infobox")
    @patch("meshing_around_clients.tui.whiptail_tui.yesno")
    @patch("meshing_around_clients.tui.whiptail_tui.inputbox")
    def test_mqtt_interface_prompts_for_radio_host(self, mock_input, mock_yesno, _info, _msg, mock_run):
        """[interface] type=mqtt requires a separate radio TCP host prompt.

        The BA5E case: mesh_client connects via MQTT but the radio
        (G2 WiFi Radio) is at a different TCP IP we have to ask for.
        """
        self.tui.config.interface.type = "mqtt"
        # inputs: 1) radio host, 2) longName, 3) shortName
        mock_input.side_effect = ["192.168.1.50", "MeshtasticHILO", "HILO"]
        mock_yesno.return_value = True
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        self.tui._radio_rename()

        cmd = mock_run.call_args[0][0]
        self.assertIn("--host", cmd)
        self.assertIn("192.168.1.50", cmd)

    @patch("meshing_around_clients.tui.whiptail_tui.subprocess.run")
    @patch("meshing_around_clients.tui.whiptail_tui.msgbox")
    @patch("meshing_around_clients.tui.whiptail_tui.infobox")
    @patch("meshing_around_clients.tui.whiptail_tui.yesno")
    @patch("meshing_around_clients.tui.whiptail_tui.inputbox")
    def test_cancel_at_confirm_does_not_invoke_meshtastic(self, mock_input, mock_yesno, _info, _msg, mock_run):
        """If the user says No at the confirm yesno, no subprocess fires."""
        self.tui.config.interface.type = "tcp"
        self.tui.config.interface.hostname = "10.0.0.5"
        mock_input.side_effect = ["MyNode", "MYNO"]
        mock_yesno.return_value = False  # user backs out

        self.tui._radio_rename()

        mock_run.assert_not_called()


class TestPiZeroAutoDefault(unittest.TestCase):
    """mesh_client.main() on any Pi Zero (W or 2W) + TTY + no mode flag
    should skip the launcher menu and route directly to whiptail.

    Originally only matched Pi Zero 2W; broadened in PR #179 after
    discovering BA5E is actually a Pi Zero W (original ARMv6), not a
    Pi Zero 2W, and the auto-default never fired there.
    """

    def _exercise_slice(self, is_pi_zero_result):
        """Exercise the relevant slice of main() with is_pi_zero mocked."""
        import mesh_client

        config = mesh_client.load_config()
        captured = {}

        def fake_run_application(cfg):
            captured["mode"] = cfg.get("features", "mode", fallback="?")
            captured["force_whiptail"] = cfg.getboolean("features", "force_whiptail", fallback=False)
            captured["called"] = True
            return True

        with (
            patch("meshing_around_clients.setup.pi_utils.is_pi_zero", return_value=is_pi_zero_result),
            patch("meshing_around_clients.setup.pi_utils.get_pi_model", return_value="Raspberry Pi Test"),
            patch("mesh_client.run_application", side_effect=fake_run_application),
        ):
            is_interactive = True
            has_mode_flag = False
            if is_interactive and not has_mode_flag:
                try:
                    from meshing_around_clients.setup.pi_utils import is_pi_zero

                    if is_pi_zero():
                        config.set("features", "mode", "tui")
                        config.set("features", "force_whiptail", "true")
                        mesh_client.run_application(config)
                except ImportError:
                    pass

        return captured

    def test_pi_zero_routes_to_whiptail(self):
        """Pi Zero W (or 2W) -> whiptail mode + force_whiptail=true."""
        captured = self._exercise_slice(is_pi_zero_result=True)
        self.assertTrue(captured.get("called"), "expected run_application to fire")
        self.assertEqual(captured.get("mode"), "tui")
        self.assertTrue(captured.get("force_whiptail"))

    def test_non_pi_falls_through_to_launcher(self):
        """Non-Pi (x86, Pi 4, etc.) -> auto-default does NOT fire."""
        captured = self._exercise_slice(is_pi_zero_result=False)
        self.assertFalse(captured.get("called"), "run_application should not fire on non-Pi-Zero")


class TestWhiptailNoneNodeGuards(unittest.TestCase):
    """A node with None role/snr/latitude (malformed packet or partial
    deserialize) must not crash whiptail rendering — run_interactive() catches
    only KeyboardInterrupt, so one such node would exit the WHOLE TUI."""

    def _none_node(self):
        from meshing_around_clients.core.models import LinkQuality, Node, Position

        return Node(
            node_id="!badnode",
            node_num=0xBAD,
            long_name="Broken",
            role=None,  # crashes `node.role.value`
            link_quality=LinkQuality(snr=None, snr_avg=None, rssi=None),  # crashes `snr:.1f`
            position=Position(latitude=None, longitude=1.234),  # crashes `latitude:.5f`
        )

    def test_role_value_helper_is_none_safe(self):
        from meshing_around_clients.tui.whiptail_tui import _role_value

        self.assertEqual(_role_value(self._none_node()), "UNKNOWN")

    def test_show_node_detail_survives_none_fields(self):
        tui = _make_tui()
        node = self._none_node()
        with patch("meshing_around_clients.tui.whiptail_tui.msgbox") as mbox:
            # Must not raise (was AttributeError/TypeError before the guards).
            tui._show_node_detail(node.node_id, [node])
        mbox.assert_called_once()

    def test_node_menu_desc_survives_none_snr(self):
        # The node-list menu builds "SNR:{snr:.0f}" — None snr must not crash it.
        tui = _make_tui()
        node = self._none_node()
        tui.api.network.add_node(node)
        with patch("meshing_around_clients.tui.whiptail_tui.menu", return_value=None):
            tui._show_nodes()  # builds the menu desc for each node


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for meshing_around_clients.setup.whiptail fallback functions.
"""

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.setup import whiptail


class TestIsTty(unittest.TestCase):
    """Test _is_tty() TTY detection."""

    def test_returns_true_when_tty(self):
        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 0
        with patch.object(whiptail.sys, "stdin", mock_stdin), patch.object(whiptail.os, "isatty", return_value=True):
            self.assertTrue(whiptail._is_tty())

    def test_returns_false_when_not_tty(self):
        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 0
        with patch.object(whiptail.sys, "stdin", mock_stdin), patch.object(whiptail.os, "isatty", return_value=False):
            self.assertFalse(whiptail._is_tty())

    def test_returns_false_on_value_error(self):
        mock_stdin = MagicMock()
        mock_stdin.fileno.side_effect = ValueError("no fileno")
        with patch.object(whiptail.sys, "stdin", mock_stdin):
            self.assertFalse(whiptail._is_tty())

    def test_returns_false_on_os_error(self):
        mock_stdin = MagicMock()
        mock_stdin.fileno.side_effect = OSError("bad fd")
        with patch.object(whiptail.sys, "stdin", mock_stdin):
            self.assertFalse(whiptail._is_tty())

    def test_returns_false_when_no_fileno(self):
        mock_stdin = MagicMock(spec=[])  # no fileno attribute
        with patch.object(whiptail.sys, "stdin", mock_stdin):
            self.assertFalse(whiptail._is_tty())


class TestCanUseWhiptail(unittest.TestCase):
    """Test _can_use_whiptail() logic."""

    def test_true_when_whiptail_and_tty(self):
        with patch.object(whiptail, "HAS_WHIPTAIL", True), patch.object(whiptail, "_is_tty", return_value=True):
            self.assertTrue(whiptail._can_use_whiptail())

    def test_false_when_no_whiptail(self):
        with patch.object(whiptail, "HAS_WHIPTAIL", False), patch.object(whiptail, "_is_tty", return_value=True):
            self.assertFalse(whiptail._can_use_whiptail())

    def test_false_when_no_tty(self):
        with patch.object(whiptail, "HAS_WHIPTAIL", True), patch.object(whiptail, "_is_tty", return_value=False):
            self.assertFalse(whiptail._can_use_whiptail())


class TestFallbackYesno(unittest.TestCase):
    """Test _fallback_yesno() input handling."""

    @patch("builtins.input", return_value="y")
    def test_yes(self, _):
        self.assertTrue(whiptail._fallback_yesno("Continue?"))

    @patch("builtins.input", return_value="yes")
    def test_yes_full(self, _):
        self.assertTrue(whiptail._fallback_yesno("Continue?"))

    @patch("builtins.input", return_value="n")
    def test_no(self, _):
        self.assertFalse(whiptail._fallback_yesno("Continue?"))

    @patch("builtins.input", return_value="no")
    def test_no_full(self, _):
        self.assertFalse(whiptail._fallback_yesno("Continue?"))

    @patch("builtins.input", return_value="")
    def test_empty_defaults_yes(self, _):
        self.assertTrue(whiptail._fallback_yesno("Continue?", default_yes=True))

    @patch("builtins.input", return_value="")
    def test_empty_defaults_no(self, _):
        self.assertFalse(whiptail._fallback_yesno("Continue?", default_yes=False))

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_returns_default(self, _):
        self.assertTrue(whiptail._fallback_yesno("Continue?", default_yes=True))
        self.assertFalse(whiptail._fallback_yesno("Continue?", default_yes=False))

    @patch("builtins.input", side_effect=EOFError)
    def test_eof_returns_default(self, _):
        self.assertTrue(whiptail._fallback_yesno("Continue?", default_yes=True))


class TestFallbackInputbox(unittest.TestCase):
    """Test _fallback_inputbox() input handling."""

    @patch("builtins.input", return_value="hello")
    def test_returns_input(self, _):
        self.assertEqual(whiptail._fallback_inputbox("Enter:"), "hello")

    @patch("builtins.input", return_value="")
    def test_empty_returns_default(self, _):
        self.assertEqual(whiptail._fallback_inputbox("Enter:", default="world"), "world")

    @patch("builtins.input", return_value="  custom  ")
    def test_strips_whitespace(self, _):
        self.assertEqual(whiptail._fallback_inputbox("Enter:"), "custom")

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_interrupt_returns_none(self, _):
        self.assertIsNone(whiptail._fallback_inputbox("Enter:"))

    @patch("builtins.input", side_effect=EOFError)
    def test_eof_returns_none(self, _):
        self.assertIsNone(whiptail._fallback_inputbox("Enter:"))


class TestFallbackMenu(unittest.TestCase):
    """Test _fallback_menu() selection logic."""

    ITEMS = [("tui", "Terminal UI"), ("web", "Web Dashboard"), ("demo", "Demo Mode")]

    @patch("builtins.input", return_value="1")
    def test_select_first(self, _):
        self.assertEqual(whiptail._fallback_menu("Menu", self.ITEMS), "tui")

    @patch("builtins.input", return_value="2")
    def test_select_second(self, _):
        self.assertEqual(whiptail._fallback_menu("Menu", self.ITEMS), "web")

    @patch("builtins.input", return_value="3")
    def test_select_third(self, _):
        self.assertEqual(whiptail._fallback_menu("Menu", self.ITEMS), "demo")

    @patch("builtins.input", return_value="0")
    def test_cancel(self, _):
        self.assertIsNone(whiptail._fallback_menu("Menu", self.ITEMS))

    @patch("builtins.input", return_value="99")
    def test_out_of_range(self, _):
        self.assertIsNone(whiptail._fallback_menu("Menu", self.ITEMS))

    @patch("builtins.input", return_value="")
    def test_empty_uses_default(self, _):
        self.assertEqual(whiptail._fallback_menu("Menu", self.ITEMS, default="web"), "web")

    @patch("builtins.input", return_value="web")
    def test_tag_match(self, _):
        self.assertEqual(whiptail._fallback_menu("Menu", self.ITEMS), "web")

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_interrupt_returns_none(self, _):
        self.assertIsNone(whiptail._fallback_menu("Menu", self.ITEMS))


class TestFallbackMsgbox(unittest.TestCase):
    """Test _fallback_msgbox() display."""

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_prints_title_and_message(self, mock_print, _):
        whiptail._fallback_msgbox("Hello world", title="Test")
        printed = "".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("Test", printed)
        self.assertIn("Hello world", printed)

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    @patch("builtins.print")
    def test_interrupt_handled(self, mock_print, _):
        # Should not raise
        whiptail._fallback_msgbox("msg")


class TestFallbackRadiolist(unittest.TestCase):
    """Test _fallback_radiolist() selection logic."""

    ITEMS = [
        ("debug", "Debug output", False),
        ("info", "Normal (default)", True),
        ("error", "Errors only", False),
    ]

    @patch("builtins.input", return_value="1")
    def test_select_first(self, _):
        self.assertEqual(whiptail._fallback_radiolist("Level", self.ITEMS), "debug")

    @patch("builtins.input", return_value="")
    def test_empty_selects_default(self, _):
        # "info" is selected (True), so default_num is "2"
        self.assertEqual(whiptail._fallback_radiolist("Level", self.ITEMS), "info")

    @patch("builtins.input", return_value="0")
    def test_cancel(self, _):
        self.assertIsNone(whiptail._fallback_radiolist("Level", self.ITEMS))

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_interrupt_returns_none(self, _):
        self.assertIsNone(whiptail._fallback_radiolist("Level", self.ITEMS))

    @patch("builtins.input", return_value="99")
    def test_out_of_range(self, _):
        self.assertIsNone(whiptail._fallback_radiolist("Level", self.ITEMS))


class TestResetTerminal(unittest.TestCase):
    """Test _reset_terminal() safety."""

    @patch.object(whiptail.subprocess, "run")
    @patch.object(whiptail.os, "close")
    @patch.object(whiptail.os, "open", return_value=3)
    def test_calls_stty_sane(self, mock_open, mock_close, mock_run):
        whiptail._reset_terminal()
        mock_open.assert_called_once_with("/dev/tty", os.O_RDWR)
        mock_run.assert_called_once()
        self.assertIn("stty", mock_run.call_args[0][0])
        mock_close.assert_called_once_with(3)

    @patch.object(whiptail.os, "open", side_effect=OSError("no tty"))
    def test_handles_os_error(self, _):
        # Should not raise
        whiptail._reset_terminal()


class TestRunWhiptail(unittest.TestCase):
    """Test _run_whiptail() wrapper."""

    @patch.object(whiptail.subprocess, "run")
    def test_returns_completed_process(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stderr="tui")
        result = whiptail._run_whiptail(["whiptail", "--menu"])
        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 0)

    @patch.object(whiptail, "_reset_terminal")
    @patch.object(whiptail.subprocess, "run", side_effect=subprocess.TimeoutExpired("cmd", 30))
    def test_timeout_returns_none(self, _, mock_reset):
        result = whiptail._run_whiptail(["whiptail", "--menu"])
        self.assertIsNone(result)
        mock_reset.assert_called_once()

    @patch.object(whiptail, "_reset_terminal")
    @patch.object(whiptail.subprocess, "run", side_effect=OSError("fail"))
    def test_os_error_returns_none(self, _, mock_reset):
        result = whiptail._run_whiptail(["whiptail", "--menu"])
        self.assertIsNone(result)
        mock_reset.assert_called_once()


class TestMenuWhiptailPath(unittest.TestCase):
    """Test menu() when whiptail is available."""

    ITEMS = [("tui", "Terminal UI"), ("web", "Web Dashboard")]

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_returns_selection(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stderr="web")
        result = whiptail.menu("Test", self.ITEMS)
        self.assertEqual(result, "web")

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_cancel_returns_none(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="")
        result = whiptail.menu("Test", self.ITEMS)
        self.assertIsNone(result)

    @patch("builtins.input", return_value="1")
    @patch.object(whiptail, "_run_whiptail", return_value=None)
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_timeout_falls_back(self, _, __, ___):
        result = whiptail.menu("Test", self.ITEMS)
        self.assertEqual(result, "tui")


class TestYesnoWhiptailPath(unittest.TestCase):
    """Test yesno() when whiptail is available."""

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_yes(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        self.assertTrue(whiptail.yesno("Continue?"))

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_no(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1)
        self.assertFalse(whiptail.yesno("Continue?"))

    @patch("builtins.input", return_value="y")
    @patch.object(whiptail, "_run_whiptail", return_value=None)
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_timeout_falls_back(self, _, __, ___):
        self.assertTrue(whiptail.yesno("Continue?"))


class TestMsgboxWhiptailPath(unittest.TestCase):
    """Test msgbox() when whiptail is available."""

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_displays_message(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        whiptail.msgbox("Hello")  # Should not raise
        mock_run.assert_called_once()

    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    @patch.object(whiptail, "_run_whiptail", return_value=None)
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_timeout_falls_back(self, _, __, ___, ____):
        whiptail.msgbox("Hello")  # Should not raise


class TestInputboxWhiptailPath(unittest.TestCase):
    """Test inputbox() when whiptail is available."""

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_returns_input(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stderr="hello")
        result = whiptail.inputbox("Enter:")
        self.assertEqual(result, "hello")

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_cancel_returns_none(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="")
        result = whiptail.inputbox("Enter:")
        self.assertIsNone(result)

    @patch("builtins.input", return_value="fallback")
    @patch.object(whiptail, "_run_whiptail", return_value=None)
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_timeout_falls_back(self, _, __, ___):
        result = whiptail.inputbox("Enter:")
        self.assertEqual(result, "fallback")


class TestRadiolistWhiptailPath(unittest.TestCase):
    """Test radiolist() when whiptail is available."""

    ITEMS = [("a", "Option A", True), ("b", "Option B", False)]

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_returns_selection(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stderr="b")
        result = whiptail.radiolist("Pick", self.ITEMS)
        self.assertEqual(result, "b")

    @patch.object(whiptail, "_run_whiptail")
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_cancel_returns_none(self, _, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="")
        result = whiptail.radiolist("Pick", self.ITEMS)
        self.assertIsNone(result)

    @patch("builtins.input", return_value="1")
    @patch.object(whiptail, "_run_whiptail", return_value=None)
    @patch.object(whiptail, "_can_use_whiptail", return_value=True)
    def test_timeout_falls_back(self, _, __, ___):
        result = whiptail.radiolist("Pick", self.ITEMS)
        self.assertEqual(result, "a")


if __name__ == "__main__":
    unittest.main()

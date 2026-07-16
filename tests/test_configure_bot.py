"""Tests for configure_bot.py standalone paths.

Only exercises logic that doesn't require the full modular setup stack —
specifically the fallback-branch helpers that kick in when the core
modules fail to import (e.g. during setup_headless.sh bootstrap).
"""

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestGetUserHomeFallback(unittest.TestCase):
    """The fallback `get_user_home` path is taken when the core modules
    can't be imported.  Prior to the post-merge review, the non-sudo
    branch of that fallback recursed on itself — this test pins the fix.
    """

    def setUp(self):
        self._saved_sudo_user = os.environ.pop("SUDO_USER", None)
        # Force the `except ImportError:` branch in configure_bot.py by
        # injecting a sentinel module that raises on attribute access
        # for any submodule import.  The simplest way: remove the real
        # core modules from sys.modules and stub `meshing_around_clients`
        # to a bare ModuleType so the `from ... import` line fails.
        self._saved_modules = {
            k: v for k, v in sys.modules.items() if k.startswith("meshing_around_clients") or k == "configure_bot"
        }
        for k in list(self._saved_modules):
            del sys.modules[k]

    def tearDown(self):
        if self._saved_sudo_user is not None:
            os.environ["SUDO_USER"] = self._saved_sudo_user
        else:
            os.environ.pop("SUDO_USER", None)
        for k in list(sys.modules):
            if k.startswith("meshing_around_clients") or k == "configure_bot":
                del sys.modules[k]
        sys.modules.update(self._saved_modules)

    def test_fallback_without_sudo_user_does_not_recurse(self):
        """Drop SUDO_USER, force fallback, call — assert no RecursionError."""

        # Poison the core config module so `from ...core.config import
        # get_user_home` raises ImportError, which triggers the fallback
        # definition in configure_bot.py.
        class _Raiser:
            def __getattr__(self, name):
                raise ImportError(f"stubbed out {name!r}")

        # A module whose import machinery always raises when any attr
        # is pulled from it is sufficient to make `from ... import X`
        # raise ImportError.
        sys.modules["meshing_around_clients.core.config"] = _Raiser()

        configure_bot = importlib.import_module("configure_bot")

        # With SUDO_USER unset, the fallback must return Path.home() —
        # not recurse into itself.  Recursion would raise RecursionError
        # before the assertion is reached.
        result = configure_bot.get_user_home()
        self.assertIsInstance(result, Path)
        self.assertEqual(result, Path.home())

    def test_fallback_with_sudo_user_uses_sudo_user_home(self):
        """When SUDO_USER is set, fallback returns /home/<SUDO_USER>."""

        class _Raiser:
            def __getattr__(self, name):
                raise ImportError(f"stubbed out {name!r}")

        sys.modules["meshing_around_clients.core.config"] = _Raiser()
        os.environ["SUDO_USER"] = "alice"

        configure_bot = importlib.import_module("configure_bot")

        result = configure_bot.get_user_home()
        self.assertEqual(result, Path("/home/alice"))


class TestRmtreeTargetGuard(unittest.TestCase):
    """`_is_safe_rmtree_target` must refuse dangerous root-owned deletions."""

    def setUp(self):
        import importlib

        self.configure_bot = importlib.import_module("configure_bot")

    def test_refuses_root_and_system_dirs(self):
        for p in ["/", "/home", "/opt", "/etc", "/usr", "/root", "/var", "/boot"]:
            self.assertFalse(
                self.configure_bot._is_safe_rmtree_target(Path(p)),
                f"should refuse {p}",
            )

    def test_refuses_home_directory_root(self):
        # A user's home itself must be refused (typo'd install dir).
        self.assertFalse(self.configure_bot._is_safe_rmtree_target(Path("/home/pi")))
        self.assertFalse(self.configure_bot._is_safe_rmtree_target(Path("/home/alice")))

    def test_allows_install_subdirectory(self):
        # The intended target — a named subdirectory — is allowed.
        self.assertTrue(self.configure_bot._is_safe_rmtree_target(Path("/home/pi/meshing-around")))
        self.assertTrue(self.configure_bot._is_safe_rmtree_target(Path("/opt/meshing-around")))


class TestSystemdUnitBuilder(unittest.TestCase):
    """S4: the meshing-around unit builder must quote ExecStart paths (so an
    install dir with a space stays one argv token) and refuse control-char /
    quote injection into a root-owned unit."""

    def setUp(self):
        import importlib

        self.cb = importlib.import_module("configure_bot")

    def test_execstart_paths_quoted_for_spaces(self):
        unit = self.cb._build_meshing_around_unit(
            Path("/home/pi/mesh bot"), "/home/pi/mesh bot/.venv/bin/python3", "pi", None
        )
        self.assertIn('ExecStart="/home/pi/mesh bot/.venv/bin/python3" "/home/pi/mesh bot/mesh_bot.py"', unit)

    def test_user_and_workdir_present(self):
        unit = self.cb._build_meshing_around_unit(Path("/opt/app"), "/usr/bin/python3", "meshuser", None)
        self.assertIn("User=meshuser", unit)
        self.assertIn("WorkingDirectory=/opt/app", unit)

    def test_rejects_newline_injection(self):
        with self.assertRaises(ValueError):
            self.cb._build_meshing_around_unit(Path("/opt/x\nExecStartPre=/bin/evil"), "/usr/bin/python3", "pi", None)

    def test_rejects_quote_in_path(self):
        with self.assertRaises(ValueError):
            self.cb._build_meshing_around_unit(Path('/opt/x"y'), "/usr/bin/python3", "pi", None)

    def test_rejects_newline_in_username(self):
        with self.assertRaises(ValueError):
            self.cb._build_meshing_around_unit(Path("/opt/app"), "/usr/bin/python3", "pi\nExecStartPre=/bin/evil", None)


if __name__ == "__main__":
    unittest.main()

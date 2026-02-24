"""
Unit tests for meshing_around_clients.setup.system_maintenance

Tests cover data classes, command execution, update scheduling, and git helpers.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.setup.system_maintenance import (
    UpdateResult,
    VersionInfo,
    run_command,
    should_check_updates,
)


class TestUpdateResultDataclass(unittest.TestCase):
    """Test UpdateResult dataclass."""

    def test_default_values(self):
        result = UpdateResult(success=True, message="OK")
        self.assertTrue(result.success)
        self.assertEqual(result.message, "OK")
        self.assertEqual(result.changes, [])
        self.assertEqual(result.errors, [])
        self.assertFalse(result.requires_restart)

    def test_with_changes_and_errors(self):
        result = UpdateResult(
            success=False,
            message="Partial failure",
            changes=["updated X"],
            errors=["failed Y"],
            requires_restart=True,
        )
        self.assertFalse(result.success)
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(result.requires_restart)


class TestVersionInfoDataclass(unittest.TestCase):
    """Test VersionInfo dataclass."""

    def test_creation(self):
        info = VersionInfo(current="0.5.0", latest="0.6.0", has_update=True, source="meshforge")
        self.assertEqual(info.current, "0.5.0")
        self.assertEqual(info.latest, "0.6.0")
        self.assertTrue(info.has_update)
        self.assertEqual(info.source, "meshforge")


class TestRunCommand(unittest.TestCase):
    """Test run_command function."""

    def test_successful_command(self):
        ret, stdout, stderr = run_command(["echo", "hello"])
        self.assertEqual(ret, 0)
        self.assertIn("hello", stdout)

    def test_failing_command(self):
        ret, stdout, stderr = run_command(["false"])
        self.assertNotEqual(ret, 0)

    def test_command_not_found(self):
        ret, stdout, stderr = run_command(["nonexistent_command_xyz"])
        self.assertEqual(ret, -1)
        self.assertIn("not found", stderr.lower())

    def test_timeout(self):
        ret, stdout, stderr = run_command(["sleep", "10"], timeout=1)
        self.assertEqual(ret, -1)
        self.assertIn("timed out", stderr.lower())

    def test_sudo_prepends(self):
        """Verify sudo is prepended (will fail if sudo not available, but tests the logic)."""
        with patch("meshing_around_clients.setup.system_maintenance.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            run_command(["ls"], sudo=True)
            called_cmd = mock_run.call_args[0][0]
            self.assertEqual(called_cmd[0], "sudo")
            self.assertEqual(called_cmd[1], "ls")

    def test_cwd_passed_through(self):
        """Verify cwd is passed to subprocess."""
        with patch("meshing_around_clients.setup.system_maintenance.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            run_command(["ls"], cwd=Path("/tmp"))
            self.assertEqual(mock_run.call_args[1]["cwd"], "/tmp")


class TestShouldCheckUpdates(unittest.TestCase):
    """Test should_check_updates scheduling logic."""

    def test_no_last_check_returns_true(self):
        self.assertTrue(should_check_updates("daily", last_check=None))
        self.assertTrue(should_check_updates("weekly", last_check=None))
        self.assertTrue(should_check_updates("monthly", last_check=None))

    def test_daily_stale(self):
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        self.assertTrue(should_check_updates("daily", last_check=two_days_ago))

    def test_daily_fresh(self):
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        self.assertFalse(should_check_updates("daily", last_check=one_hour_ago))

    def test_weekly_stale(self):
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        self.assertTrue(should_check_updates("weekly", last_check=ten_days_ago))

    def test_weekly_fresh(self):
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        self.assertFalse(should_check_updates("weekly", last_check=three_days_ago))

    def test_monthly_stale(self):
        forty_days_ago = datetime.now(timezone.utc) - timedelta(days=40)
        self.assertTrue(should_check_updates("monthly", last_check=forty_days_ago))

    def test_monthly_fresh(self):
        two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)
        self.assertFalse(should_check_updates("monthly", last_check=two_weeks_ago))

    def test_unknown_schedule_defaults_weekly(self):
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        self.assertTrue(should_check_updates("unknown_schedule", last_check=ten_days_ago))

        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        self.assertFalse(should_check_updates("unknown_schedule", last_check=three_days_ago))


class TestGitHelpers(unittest.TestCase):
    """Test git helper functions."""

    def test_get_git_commit_hash(self):
        from meshing_around_clients.setup.system_maintenance import get_git_commit_hash

        # Should work if run inside a git repo
        result = get_git_commit_hash(Path("."), short=True)
        if result is not None:
            self.assertGreater(len(result), 0)
            self.assertLessEqual(len(result), 12)

    def test_get_git_current_branch(self):
        from meshing_around_clients.setup.system_maintenance import get_git_current_branch

        result = get_git_current_branch(Path("."))
        if result is not None:
            self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()

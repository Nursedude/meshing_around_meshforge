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
    check_for_updates,
    check_required_packages,
    check_service_status,
    clone_meshing_around,
    create_systemd_service,
    find_meshing_around,
    get_git_commit_hash,
    get_git_current_branch,
    get_git_remote_url,
    get_pip_command,
    get_pip_install_flags,
    git_pull,
    install_package,
    install_python_dependencies,
    manage_service,
    perform_scheduled_update_check,
    run_command,
    should_check_updates,
    system_update,
    update_meshforge,
    update_upstream,
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


class TestInstallPackage(unittest.TestCase):
    """Test install_package() with mocked subprocess."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_already_installed(self, mock_run):
        mock_run.return_value = (0, "", "")  # dpkg -l succeeds
        success, msg = install_package("git")
        self.assertTrue(success)
        self.assertIn("already installed", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_install_success(self, mock_run):
        mock_run.side_effect = [
            (1, "", ""),  # dpkg -l fails (not installed)
            (0, "", ""),  # apt install succeeds
        ]
        success, msg = install_package("git")
        self.assertTrue(success)
        self.assertIn("Installed", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_install_failure(self, mock_run):
        mock_run.side_effect = [
            (1, "", ""),  # dpkg -l fails
            (1, "", "E: Unable to locate"),  # apt install fails
        ]
        success, msg = install_package("nonexistent-pkg")
        self.assertFalse(success)
        self.assertIn("Failed", msg)


class TestCheckRequiredPackages(unittest.TestCase):
    """Test check_required_packages()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_all_installed(self, mock_run):
        mock_run.return_value = (0, "", "")  # All dpkg -s succeed
        missing = check_required_packages(["git", "python3"])
        self.assertEqual(missing, [])

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_some_missing(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git installed
            (1, "", ""),  # missing-pkg not installed
        ]
        missing = check_required_packages(["git", "missing-pkg"])
        self.assertEqual(missing, ["missing-pkg"])


class TestGitRemoteUrl(unittest.TestCase):
    """Test get_git_remote_url()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_returns_url(self, mock_run):
        mock_run.return_value = (0, "https://github.com/user/repo.git\n", "")
        url = get_git_remote_url(Path("/tmp"))
        self.assertEqual(url, "https://github.com/user/repo.git")

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_returns_none_on_failure(self, mock_run):
        mock_run.return_value = (1, "", "error")
        url = get_git_remote_url(Path("/nonexistent"))
        self.assertIsNone(url)


class TestCheckForUpdates(unittest.TestCase):
    """Test check_for_updates()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_has_updates(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git fetch succeeds
            (0, "3\n", ""),  # 3 commits behind
        ]
        has_updates, msg, count = check_for_updates(Path("/tmp"))
        self.assertTrue(has_updates)
        self.assertEqual(count, 3)
        self.assertIn("3 commits", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_up_to_date(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git fetch succeeds
            (0, "0\n", ""),  # 0 commits behind
        ]
        has_updates, msg, count = check_for_updates(Path("/tmp"))
        self.assertFalse(has_updates)
        self.assertEqual(count, 0)
        self.assertIn("Up to date", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_fetch_fails(self, mock_run):
        mock_run.return_value = (1, "", "network error")
        has_updates, msg, count = check_for_updates(Path("/tmp"))
        self.assertFalse(has_updates)
        self.assertIn("Failed", msg)


class TestGitPull(unittest.TestCase):
    """Test git_pull()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_pull_success(self, mock_run):
        mock_run.side_effect = [
            (0, "M file.txt\n", ""),  # git status --porcelain (has changes)
            (0, "", ""),  # git stash
            (0, "Already up to date.\n", ""),  # git pull
            (0, "", ""),  # git stash pop
        ]
        result = git_pull(Path("/tmp"), stash_changes=True)
        self.assertTrue(result.success)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_pull_failure(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git status --porcelain (no changes)
            (1, "", "merge conflict"),  # git pull main fails
            (1, "", "merge conflict"),  # git pull master fails (retry)
            (1, "", "merge conflict"),  # git pull develop fails (retry)
        ]
        result = git_pull(Path("/tmp"), stash_changes=False)
        self.assertFalse(result.success)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_pull_no_stash(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git status --porcelain (no changes)
            (0, "Updating abc..def\n", ""),  # git pull succeeds
        ]
        result = git_pull(Path("/tmp"), stash_changes=False)
        self.assertTrue(result.success)


class TestSystemUpdate(unittest.TestCase):
    """Test system_update()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_update_success(self, mock_run):
        mock_run.return_value = (0, "newly installed", "")
        result = system_update(upgrade=True, autoremove=True)
        self.assertTrue(result.success)
        self.assertGreater(len(result.changes), 0)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_update_apt_fails(self, mock_run):
        mock_run.return_value = (1, "", "apt error")
        result = system_update(upgrade=False, autoremove=False)
        self.assertFalse(result.success)
        self.assertGreater(len(result.errors), 0)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_update_with_callback(self, mock_run):
        mock_run.return_value = (0, "upgraded", "")
        messages = []
        result = system_update(upgrade=True, autoremove=True, progress_callback=messages.append)
        self.assertTrue(result.success)
        self.assertGreater(len(messages), 0)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_update_upgrade_fails(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # apt update succeeds
            (1, "", "upgrade error"),  # apt upgrade fails
            (0, "", ""),  # apt autoremove succeeds
        ]
        result = system_update(upgrade=True, autoremove=True)
        self.assertFalse(result.success)
        self.assertIn("apt upgrade failed", result.errors[0])

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_update_no_upgrade(self, mock_run):
        mock_run.return_value = (0, "", "")
        result = system_update(upgrade=False, autoremove=False)
        self.assertTrue(result.success)


class TestFindMeshingAround(unittest.TestCase):
    """Test find_meshing_around()."""

    @patch("meshing_around_clients.setup.system_maintenance.subprocess.run")
    def test_not_found_find_fails(self, mock_subproc):
        """When find command returns nothing."""
        mock_subproc.return_value = MagicMock(returncode=1, stdout="", stderr="")
        # This relies on none of the common_paths existing with mesh_bot.py,
        # which is true in the test environment
        result = find_meshing_around()
        self.assertIsNone(result)

    @patch("meshing_around_clients.setup.system_maintenance.subprocess.run")
    def test_found_via_find(self, mock_subproc):
        """When find returns a path."""
        mock_subproc.return_value = MagicMock(returncode=0, stdout="/home/user/meshing-around/mesh_bot.py\n", stderr="")
        result = find_meshing_around()
        # Will either find via common paths (if they exist) or via find
        # In test env, common paths don't exist, so it uses find result
        if result is not None:
            self.assertIsInstance(result, Path)


class TestGetPipCommand(unittest.TestCase):
    """Test get_pip_command()."""

    def test_no_venv(self):
        result = get_pip_command(None)
        self.assertEqual(result, ["pip3"])

    @patch("meshing_around_clients.setup.pi_utils.Path")
    def test_with_venv(self, mock_path_cls):
        venv = MagicMock()
        venv.exists.return_value = True
        pip_path = MagicMock()
        pip_path.exists.return_value = True
        pip_path.__str__ = MagicMock(return_value="/fake/venv/bin/pip3")
        venv.__truediv__ = MagicMock(side_effect=lambda x: pip_path if x == "bin" else pip_path)
        pip_path.__truediv__ = MagicMock(return_value=pip_path)
        result = get_pip_command(venv)
        self.assertEqual(len(result), 1)


class TestGetPipInstallFlags(unittest.TestCase):
    """Test get_pip_install_flags()."""

    @patch("meshing_around_clients.setup.pi_utils.check_pep668_environment")
    def test_no_pep668(self, mock_check):
        mock_check.return_value = False
        result = get_pip_install_flags()
        self.assertEqual(result, [])

    @patch("meshing_around_clients.setup.pi_utils.check_pep668_environment")
    def test_pep668_active(self, mock_check):
        mock_check.return_value = True
        result = get_pip_install_flags()
        self.assertEqual(result, ["--break-system-packages"])


class TestInstallPythonDependencies(unittest.TestCase):
    """Test install_python_dependencies()."""

    @patch("meshing_around_clients.setup.system_maintenance.get_pip_install_flags")
    @patch("meshing_around_clients.setup.system_maintenance.get_pip_command")
    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_success(self, mock_run, mock_pip_cmd, mock_flags):
        mock_pip_cmd.return_value = ["pip3"]
        mock_flags.return_value = []
        mock_run.return_value = (0, "Successfully installed", "")
        req_file = MagicMock()
        req_file.exists.return_value = True
        req_file.__str__ = MagicMock(return_value="/tmp/requirements.txt")
        result = install_python_dependencies(req_file)
        self.assertTrue(result.success)
        self.assertIn("Dependencies installed", result.message)

    @patch("meshing_around_clients.setup.system_maintenance.get_pip_install_flags")
    @patch("meshing_around_clients.setup.system_maintenance.get_pip_command")
    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_failure_falls_back_to_individual(self, mock_run, mock_pip_cmd, mock_flags):
        mock_pip_cmd.return_value = ["pip3"]
        mock_flags.return_value = []
        # First call (bulk install) fails, individual installs succeed
        mock_run.side_effect = [
            (1, "", "error"),  # bulk install fails
        ] + [
            (0, "", "")
        ] * 7  # individual installs succeed
        req_file = MagicMock()
        req_file.exists.return_value = True
        req_file.__str__ = MagicMock(return_value="/tmp/requirements.txt")
        result = install_python_dependencies(req_file)
        self.assertTrue(result.success)
        self.assertGreater(len(result.changes), 0)

    @patch("meshing_around_clients.setup.system_maintenance.get_pip_install_flags")
    @patch("meshing_around_clients.setup.system_maintenance.get_pip_command")
    def test_no_requirements_file(self, mock_pip_cmd, mock_flags):
        mock_pip_cmd.return_value = ["pip3"]
        mock_flags.return_value = []
        req_file = MagicMock()
        req_file.exists.return_value = False
        result = install_python_dependencies(req_file)
        self.assertTrue(result.success)
        self.assertIn("No requirements.txt", result.message)

    @patch("meshing_around_clients.setup.system_maintenance.get_pip_install_flags")
    @patch("meshing_around_clients.setup.system_maintenance.get_pip_command")
    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_with_callback(self, mock_run, mock_pip_cmd, mock_flags):
        mock_pip_cmd.return_value = ["pip3"]
        mock_flags.return_value = []
        mock_run.return_value = (0, "installed", "")
        req_file = MagicMock()
        req_file.exists.return_value = True
        req_file.__str__ = MagicMock(return_value="/tmp/requirements.txt")
        messages = []
        install_python_dependencies(req_file, progress_callback=messages.append)
        self.assertGreater(len(messages), 0)


class TestUpdateUpstream(unittest.TestCase):
    """Test update_upstream()."""

    @patch("meshing_around_clients.setup.system_maintenance.git_pull")
    def test_with_path(self, mock_pull):
        mock_pull.return_value = UpdateResult(success=True, message="Updated")
        result = update_upstream(meshing_around_path=Path("/tmp/meshing-around"))
        self.assertTrue(result.success)

    @patch("meshing_around_clients.setup.system_maintenance.find_meshing_around")
    def test_not_found(self, mock_find):
        mock_find.return_value = None
        result = update_upstream()
        self.assertFalse(result.success)
        self.assertIn("not found", result.message)

    @patch("meshing_around_clients.setup.system_maintenance.git_pull")
    def test_with_callback(self, mock_pull):
        mock_pull.return_value = UpdateResult(success=True, message="Updated")
        messages = []
        update_upstream(meshing_around_path=Path("/tmp"), progress_callback=messages.append)
        self.assertGreater(len(messages), 0)


class TestUpdateMeshforge(unittest.TestCase):
    """Test update_meshforge()."""

    @patch("meshing_around_clients.setup.system_maintenance.git_pull")
    def test_with_path(self, mock_pull):
        mock_pull.return_value = UpdateResult(success=True, message="Updated")
        result = update_meshforge(meshforge_path=Path("/tmp/meshforge"))
        self.assertTrue(result.success)

    @patch("meshing_around_clients.setup.system_maintenance.git_pull")
    def test_default_path(self, mock_pull):
        mock_pull.return_value = UpdateResult(success=True, message="Updated")
        result = update_meshforge()
        self.assertTrue(result.success)

    @patch("meshing_around_clients.setup.system_maintenance.git_pull")
    def test_with_callback(self, mock_pull):
        mock_pull.return_value = UpdateResult(success=True, message="Updated")
        messages = []
        update_meshforge(meshforge_path=Path("/tmp"), progress_callback=messages.append)
        self.assertGreater(len(messages), 0)


class TestManageService(unittest.TestCase):
    """Test manage_service()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_start_success(self, mock_run):
        mock_run.return_value = (0, "", "")
        success, msg = manage_service("meshforge", "start")
        self.assertTrue(success)
        self.assertIn("started", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_status(self, mock_run):
        mock_run.return_value = (0, "active (running)", "")
        success, msg = manage_service("meshforge", "status")
        self.assertTrue(success)
        self.assertIn("active", msg)

    def test_invalid_action(self):
        success, msg = manage_service("meshforge", "invalid")
        self.assertFalse(success)
        self.assertIn("Invalid action", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_stop_failure(self, mock_run):
        mock_run.return_value = (1, "", "unit not found")
        success, msg = manage_service("meshforge", "stop")
        self.assertFalse(success)
        self.assertIn("Failed", msg)


class TestCheckServiceStatus(unittest.TestCase):
    """Test check_service_status()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_running(self, mock_run):
        mock_run.return_value = (0, "active\n", "")
        is_running, status = check_service_status("meshforge")
        self.assertTrue(is_running)
        self.assertEqual(status, "active")

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_stopped(self, mock_run):
        mock_run.return_value = (3, "inactive\n", "")
        is_running, status = check_service_status("meshforge")
        self.assertFalse(is_running)
        self.assertEqual(status, "inactive")


class TestCreateSystemdService(unittest.TestCase):
    """Test create_systemd_service()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_create_success(self, mock_run):
        mock_run.return_value = (0, "", "")
        success, msg = create_systemd_service(
            name="meshforge",
            exec_start="/usr/bin/python3 mesh_client.py",
            working_dir=Path("/opt/meshforge"),
            user="pi",
        )
        self.assertTrue(success)
        self.assertIn("Service created", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_create_with_venv(self, mock_run):
        mock_run.return_value = (0, "", "")
        success, msg = create_systemd_service(
            name="meshforge",
            exec_start="/usr/bin/python3 mesh_client.py",
            working_dir=Path("/opt/meshforge"),
            venv_path=Path("/opt/venv"),
        )
        self.assertTrue(success)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_create_copy_fails(self, mock_run):
        mock_run.return_value = (1, "", "permission denied")
        success, msg = create_systemd_service(
            name="meshforge",
            exec_start="/usr/bin/python3 mesh_client.py",
            working_dir=Path("/opt/meshforge"),
        )
        self.assertFalse(success)
        self.assertIn("Failed", msg)


class TestCloneMeshingAround(unittest.TestCase):
    """Test clone_meshing_around()."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_clone_success(self, mock_run):
        mock_run.return_value = (0, "", "")
        with patch("meshing_around_clients.setup.system_maintenance.Path") as mock_path_cls:
            install_path = MagicMock()
            install_path.exists.return_value = False
            install_path.__str__ = MagicMock(return_value="/tmp/meshing-around")
            result = clone_meshing_around(install_path=install_path)
            self.assertTrue(result.success)
            self.assertIn("Cloned", result.message)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_clone_already_exists(self, mock_run):
        install_path = MagicMock()
        install_path.exists.return_value = True
        mesh_bot = MagicMock()
        mesh_bot.exists.return_value = True
        install_path.__truediv__ = MagicMock(return_value=mesh_bot)
        result = clone_meshing_around(install_path=install_path)
        self.assertTrue(result.success)
        self.assertIn("already installed", result.message)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_clone_dir_exists_no_bot(self, mock_run):
        install_path = MagicMock()
        install_path.exists.return_value = True
        mesh_bot = MagicMock()
        mesh_bot.exists.return_value = False
        install_path.__truediv__ = MagicMock(return_value=mesh_bot)
        result = clone_meshing_around(install_path=install_path)
        self.assertFalse(result.success)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_clone_failure(self, mock_run):
        mock_run.return_value = (1, "", "network error")
        install_path = MagicMock()
        install_path.exists.return_value = False
        install_path.__str__ = MagicMock(return_value="/tmp/meshing-around")
        result = clone_meshing_around(install_path=install_path)
        self.assertFalse(result.success)
        self.assertIn("Clone failed", result.message)


class TestPerformScheduledUpdateCheck(unittest.TestCase):
    """Test perform_scheduled_update_check()."""

    @patch("meshing_around_clients.setup.system_maintenance.find_meshing_around")
    @patch("meshing_around_clients.setup.system_maintenance.check_for_updates")
    def test_no_updates(self, mock_check, mock_find):
        mock_check.return_value = (False, "Up to date", 0)
        mock_find.return_value = Path("/tmp/meshing-around")
        results = perform_scheduled_update_check(check_meshforge=True, check_upstream=True)
        self.assertEqual(len(results), 0)

    @patch("meshing_around_clients.setup.system_maintenance.find_meshing_around")
    @patch("meshing_around_clients.setup.system_maintenance.check_for_updates")
    def test_meshforge_update_available(self, mock_check, mock_find):
        mock_check.return_value = (True, "3 commits behind", 3)
        mock_find.return_value = None  # no upstream
        results = perform_scheduled_update_check(check_meshforge=True, check_upstream=False, auto_apply=False)
        self.assertEqual(len(results), 1)
        self.assertIn("MeshForge update available", results[0].message)

    @patch("meshing_around_clients.setup.system_maintenance.update_meshforge")
    @patch("meshing_around_clients.setup.system_maintenance.check_for_updates")
    def test_auto_apply(self, mock_check, mock_update):
        mock_check.return_value = (True, "3 commits behind", 3)
        mock_update.return_value = UpdateResult(success=True, message="Updated")
        results = perform_scheduled_update_check(check_meshforge=True, check_upstream=False, auto_apply=True)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)


class TestGitHelpersExtended(unittest.TestCase):
    """Extended tests for git helper edge cases."""

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_get_git_commit_hash_full(self, mock_run):
        mock_run.return_value = (0, "abc123def456\n", "")
        result = get_git_commit_hash(Path("/tmp"), short=False)
        self.assertEqual(result, "abc123def456")

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_get_git_commit_hash_failure(self, mock_run):
        mock_run.return_value = (1, "", "error")
        result = get_git_commit_hash(Path("/tmp"), short=True)
        self.assertIsNone(result)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_get_git_current_branch_detached(self, mock_run):
        mock_run.return_value = (0, "\n", "")  # empty output = detached HEAD
        result = get_git_current_branch(Path("/tmp"))
        self.assertIsNone(result)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_get_git_current_branch_failure(self, mock_run):
        mock_run.return_value = (1, "", "error")
        result = get_git_current_branch(Path("/tmp"))
        self.assertIsNone(result)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_check_for_updates_rev_list_fail(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # git fetch succeeds
            (1, "", "error"),  # rev-list fails
        ]
        has_updates, msg, count = check_for_updates(Path("/tmp"))
        self.assertFalse(has_updates)
        self.assertIn("Could not determine", msg)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_git_pull_stash_fails(self, mock_run):
        mock_run.side_effect = [
            (0, "M file.txt\n", ""),  # has changes
            (1, "", "stash error"),  # stash fails
            (0, "Updating abc..def\n", ""),  # pull succeeds
            (0, "", ""),  # stash pop
        ]
        result = git_pull(Path("/tmp"), stash_changes=True)
        self.assertTrue(result.success)
        self.assertGreater(len(result.errors), 0)

    @patch("meshing_around_clients.setup.system_maintenance.run_command")
    def test_git_pull_with_changes(self, mock_run):
        mock_run.side_effect = [
            (0, "", ""),  # no local changes
            (0, "Updating 123..456\n3 files changed\n", ""),  # pull succeeds with changes
        ]
        result = git_pull(Path("/tmp"), stash_changes=False)
        self.assertTrue(result.success)
        self.assertTrue(result.requires_restart)
        self.assertIn("Updated", result.message)


if __name__ == "__main__":
    unittest.main()

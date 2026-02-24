"""
System Maintenance and Auto-Update for MeshForge.

Provides:
- System updates (apt update/upgrade)
- MeshForge self-update (git pull from this repo)
- Upstream meshing-around sync (git pull from SpudGunMan)
- Dependency installation
- Service management (systemd)
- Scheduled update checks (weekly/monthly)

Extracted from configure_bot.py for reusability.
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .pi_utils import (
    get_pip_command,
    get_pip_install_flags,
)

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class UpdateResult:
    """Result of an update operation."""

    success: bool
    message: str
    changes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    requires_restart: bool = False


@dataclass
class VersionInfo:
    """Version information for a component."""

    current: str
    latest: str
    has_update: bool
    source: str  # "local", "upstream", "meshforge"


# =============================================================================
# Command Execution
# =============================================================================


def run_command(
    cmd: List[str], timeout: int = 600, capture: bool = True, sudo: bool = False, cwd: Optional[Path] = None
) -> Tuple[int, str, str]:
    """Run a shell command with optional sudo.

    Args:
        cmd: Command and arguments as list
        timeout: Timeout in seconds (default 10 minutes)
        capture: Whether to capture output
        sudo: Whether to prepend sudo
        cwd: Working directory

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    if sudo:
        cmd = ["sudo"] + cmd

    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout, cwd=str(cwd) if cwd else None)
        stdout = result.stdout if capture else ""
        stderr = result.stderr if capture else ""
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.SubprocessError as e:
        return -1, "", str(e)


# =============================================================================
# System Updates (apt)
# =============================================================================


def system_update(
    upgrade: bool = True, autoremove: bool = True, progress_callback: Optional[Callable[[str], None]] = None
) -> UpdateResult:
    """Run apt update and optionally upgrade.

    Args:
        upgrade: Whether to also run apt upgrade
        autoremove: Whether to run apt autoremove
        progress_callback: Optional callback for progress messages

    Returns:
        UpdateResult with success status and messages
    """

    def report(msg: str):
        if progress_callback:
            progress_callback(msg)

    result = UpdateResult(success=True, message="")
    messages = []

    # apt update
    report("Updating package lists...")
    ret, stdout, stderr = run_command(["apt", "update"], sudo=True)
    if ret != 0:
        result.errors.append(f"apt update failed: {stderr[:100]}")
        result.success = False
    else:
        messages.append("Package lists updated")
        result.changes.append("Updated package lists")

    # apt upgrade
    if upgrade:
        report("Upgrading packages...")
        ret, stdout, stderr = run_command(["apt", "upgrade", "-y"], sudo=True)
        if ret != 0:
            result.errors.append(f"apt upgrade failed: {stderr[:100]}")
            result.success = False
        else:
            messages.append("Packages upgraded")
            if "newly installed" in stdout or "upgraded" in stdout:
                result.changes.append("Upgraded system packages")

    # apt autoremove
    if autoremove:
        report("Cleaning up...")
        run_command(["apt", "autoremove", "-y"], sudo=True)
        messages.append("Cleaned up")

    result.message = "; ".join(messages) if messages else "Update completed"
    return result


def install_package(package: str, sudo: bool = True) -> Tuple[bool, str]:
    """Install a single apt package.

    Args:
        package: Package name
        sudo: Whether to use sudo

    Returns:
        Tuple of (success, message)
    """
    # Check if already installed
    ret, _, _ = run_command(["dpkg", "-l", package], capture=True)
    if ret == 0:
        return True, f"{package} already installed"

    ret, _, stderr = run_command(["apt", "install", "-y", package], sudo=sudo)
    if ret == 0:
        return True, f"Installed {package}"
    else:
        return False, f"Failed to install {package}: {stderr[:100]}"


def check_required_packages(packages: List[str]) -> List[str]:
    """Check which packages from a list are missing.

    Args:
        packages: List of package names

    Returns:
        List of missing package names
    """
    missing = []
    for pkg in packages:
        ret, _, _ = run_command(["dpkg", "-s", pkg], capture=True)
        if ret != 0:
            missing.append(pkg)
    return missing


# =============================================================================
# Git-based Updates
# =============================================================================


def find_meshing_around() -> Optional[Path]:
    """Find the meshing-around installation directory."""
    common_paths = [
        Path.home() / "meshing-around",
        Path.home() / "mesh-bot",
        Path("/opt/meshing-around"),
        Path("/opt/mesh-bot"),
        Path.cwd().parent / "meshing-around",
        Path.cwd() / "meshing-around",
    ]

    for path in common_paths:
        if path.exists() and (path / "mesh_bot.py").exists():
            return path

    # Try to find with locate
    try:
        result = subprocess.run(
            ["find", str(Path.home()), "-name", "mesh_bot.py", "-type", "f", "-maxdepth", "4"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            bot_path = Path(result.stdout.strip().split("\n")[0]).parent
            return bot_path
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass

    return None


def get_git_remote_url(repo_path: Path, remote: str = "origin") -> Optional[str]:
    """Get the URL of a git remote."""
    ret, stdout, _ = run_command(["git", "remote", "get-url", remote], cwd=repo_path)
    if ret == 0:
        return stdout.strip()
    return None


def get_git_current_branch(repo_path: Path) -> Optional[str]:
    """Get the current git branch."""
    ret, stdout, _ = run_command(["git", "branch", "--show-current"], cwd=repo_path)
    if ret == 0:
        return stdout.strip()
    return None


def get_git_commit_hash(repo_path: Path, short: bool = True) -> Optional[str]:
    """Get the current commit hash."""
    cmd = ["git", "rev-parse"]
    if short:
        cmd.append("--short")
    cmd.append("HEAD")

    ret, stdout, _ = run_command(cmd, cwd=repo_path)
    if ret == 0:
        return stdout.strip()
    return None


def check_for_updates(repo_path: Path, remote: str = "origin", branch: str = "main") -> Tuple[bool, str, int]:
    """Check if a git repository has updates available.

    Args:
        repo_path: Path to git repository
        remote: Remote name
        branch: Branch to check

    Returns:
        Tuple of (has_updates, message, commits_behind)
    """
    # Fetch latest
    ret, _, stderr = run_command(["git", "fetch", remote, branch], cwd=repo_path)
    if ret != 0:
        return False, f"Failed to fetch: {stderr[:50]}", 0

    # Count commits behind
    ret, stdout, _ = run_command(["git", "rev-list", "--count", f"HEAD..{remote}/{branch}"], cwd=repo_path)
    if ret == 0:
        commits_behind = int(stdout.strip())
        if commits_behind > 0:
            return True, f"{commits_behind} commits behind {remote}/{branch}", commits_behind
        else:
            return False, "Up to date", 0

    return False, "Could not determine update status", 0


def git_pull(repo_path: Path, remote: str = "origin", branch: str = "main", stash_changes: bool = True) -> UpdateResult:
    """Pull latest changes from git remote.

    Args:
        repo_path: Path to git repository
        remote: Remote name
        branch: Branch to pull
        stash_changes: Whether to stash local changes first

    Returns:
        UpdateResult with details
    """
    result = UpdateResult(success=True, message="")

    # Check for uncommitted changes
    ret, stdout, _ = run_command(["git", "status", "--porcelain"], cwd=repo_path)
    has_changes = bool(stdout.strip())

    if has_changes and stash_changes:
        ret, _, stderr = run_command(["git", "stash"], cwd=repo_path)
        if ret != 0:
            result.errors.append(f"Failed to stash changes: {stderr[:50]}")

    # Pull
    ret, stdout, stderr = run_command(["git", "pull", remote, branch], cwd=repo_path)

    if ret != 0:
        # Try other common branch names
        for alt_branch in ["master", "develop"]:
            if alt_branch != branch:
                ret, stdout, stderr = run_command(["git", "pull", remote, alt_branch], cwd=repo_path)
                if ret == 0:
                    branch = alt_branch
                    break

    if ret == 0:
        if "Already up to date" in stdout:
            result.message = "Already up to date"
        else:
            result.message = f"Updated from {remote}/{branch}"
            result.changes.append(stdout.strip())
            result.requires_restart = True
    else:
        result.success = False
        result.message = f"Pull failed: {stderr[:100]}"
        result.errors.append(stderr)

    # Restore stashed changes
    if has_changes and stash_changes:
        run_command(["git", "stash", "pop"], cwd=repo_path)

    return result


def update_upstream(
    meshing_around_path: Optional[Path] = None, progress_callback: Optional[Callable[[str], None]] = None
) -> UpdateResult:
    """Update the upstream meshing-around repository.

    Args:
        meshing_around_path: Path to meshing-around. Auto-detected if None.
        progress_callback: Optional callback for progress messages

    Returns:
        UpdateResult with details
    """

    def report(msg: str):
        if progress_callback:
            progress_callback(msg)

    if meshing_around_path is None:
        meshing_around_path = find_meshing_around()

    if meshing_around_path is None:
        return UpdateResult(
            success=False, message="meshing-around not found", errors=["Could not locate meshing-around installation"]
        )

    report(f"Updating meshing-around at {meshing_around_path}...")
    return git_pull(meshing_around_path)


def update_meshforge(
    meshforge_path: Optional[Path] = None, progress_callback: Optional[Callable[[str], None]] = None
) -> UpdateResult:
    """Update the MeshForge repository.

    Args:
        meshforge_path: Path to MeshForge. Uses cwd if None.
        progress_callback: Optional callback for progress messages

    Returns:
        UpdateResult with details
    """

    def report(msg: str):
        if progress_callback:
            progress_callback(msg)

    if meshforge_path is None:
        meshforge_path = Path.cwd()

    report(f"Updating MeshForge at {meshforge_path}...")
    return git_pull(meshforge_path)


# =============================================================================
# Auto-Update Scheduler
# =============================================================================


def should_check_updates(schedule: str, last_check: Optional[datetime] = None) -> bool:
    """Determine if updates should be checked based on schedule.

    Args:
        schedule: "daily", "weekly", or "monthly"
        last_check: Datetime of last check

    Returns:
        True if updates should be checked
    """
    if last_check is None:
        return True

    now = datetime.now(timezone.utc)
    if schedule == "daily":
        threshold = timedelta(days=1)
    elif schedule == "weekly":
        threshold = timedelta(weeks=1)
    elif schedule == "monthly":
        threshold = timedelta(days=30)
    else:
        threshold = timedelta(weeks=1)  # Default to weekly

    return (now - last_check) >= threshold


def perform_scheduled_update_check(
    check_meshforge: bool = True,
    check_upstream: bool = True,
    auto_apply: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[UpdateResult]:
    """Perform scheduled update checks for all configured repositories.

    Args:
        check_meshforge: Whether to check MeshForge updates
        check_upstream: Whether to check upstream meshing-around updates
        auto_apply: Whether to automatically apply updates
        progress_callback: Optional callback for progress messages

    Returns:
        List of UpdateResult for each checked repository
    """
    results = []

    if check_meshforge:
        meshforge_path = Path.cwd()
        has_update, msg, _ = check_for_updates(meshforge_path)
        if has_update:
            if auto_apply:
                result = update_meshforge(meshforge_path, progress_callback)
            else:
                result = UpdateResult(success=True, message=f"MeshForge update available: {msg}")
            results.append(result)

    if check_upstream:
        upstream_path = find_meshing_around()
        if upstream_path:
            has_update, msg, _ = check_for_updates(upstream_path)
            if has_update:
                if auto_apply:
                    result = update_upstream(upstream_path, progress_callback)
                else:
                    result = UpdateResult(success=True, message=f"Upstream update available: {msg}")
                results.append(result)

    return results


# =============================================================================
# Python Dependencies
# =============================================================================


def install_python_dependencies(
    requirements_file: Path, venv_path: Optional[Path] = None, progress_callback: Optional[Callable[[str], None]] = None
) -> UpdateResult:
    """Install Python dependencies from requirements.txt.

    Args:
        requirements_file: Path to requirements.txt
        venv_path: Path to virtual environment (optional)
        progress_callback: Optional callback for progress messages

    Returns:
        UpdateResult with details
    """

    def report(msg: str):
        if progress_callback:
            progress_callback(msg)

    result = UpdateResult(success=True, message="")

    if not requirements_file.exists():
        return UpdateResult(success=True, message="No requirements.txt found")

    pip_cmd = get_pip_command(venv_path)
    extra_flags = get_pip_install_flags()

    report("Installing Python dependencies...")
    install_cmd = pip_cmd + ["install"] + extra_flags + ["-r", str(requirements_file)]

    ret, stdout, stderr = run_command(install_cmd, timeout=300)

    if ret != 0:
        result.errors.append(f"pip install failed: {stderr[:100]}")

        # Try installing core packages individually
        core_packages = ["meshtastic", "PyPubSub", "requests", "paho-mqtt", "rich", "fastapi", "uvicorn"]

        report("Trying individual package installation...")
        for pkg in core_packages:
            install_cmd = pip_cmd + ["install"] + extra_flags + [pkg]
            ret, _, pkg_stderr = run_command(install_cmd, timeout=60)
            if ret == 0:
                result.changes.append(f"Installed {pkg}")
            else:
                result.errors.append(f"Failed to install {pkg}")

        result.success = len(result.changes) > 0
    else:
        result.message = "Dependencies installed successfully"
        result.changes.append("All dependencies installed")

    return result


# =============================================================================
# Systemd Service Management
# =============================================================================


def create_systemd_service(
    name: str,
    exec_start: str,
    working_dir: Path,
    user: Optional[str] = None,
    description: str = "MeshForge Service",
    venv_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Create a systemd service file.

    Args:
        name: Service name (without .service extension)
        exec_start: Full command to execute
        working_dir: Working directory for the service
        user: User to run as (defaults to current user)
        description: Service description
        venv_path: Optional virtual environment path

    Returns:
        Tuple of (success, message)
    """
    if user is None:
        user = os.environ.get("USER", os.environ.get("LOGNAME", "pi"))

    venv_env = f"Environment=VIRTUAL_ENV={venv_path}" if venv_path else ""

    service_content = f"""[Unit]
Description={description}
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={working_dir}
ExecStart={exec_start}
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1
{venv_env}

[Install]
WantedBy=multi-user.target
"""

    service_path = Path(f"/etc/systemd/system/{name}.service")

    try:
        # Write to temp file first
        with tempfile.NamedTemporaryFile(mode="w", suffix=".service", delete=False) as tf:
            tf.write(service_content)
            temp_path = Path(tf.name)

        # Copy to systemd directory
        ret, _, stderr = run_command(["cp", str(temp_path), str(service_path)], sudo=True)
        if ret != 0:
            return False, f"Failed to copy service file: {stderr[:50]}"

        # Set permissions
        run_command(["chmod", "644", str(service_path)], sudo=True)

        # Reload systemd
        ret, _, stderr = run_command(["systemctl", "daemon-reload"], sudo=True)
        if ret != 0:
            return False, f"Failed to reload systemd: {stderr[:50]}"

        return True, f"Service created: {service_path}"

    except (IOError, OSError) as e:
        return False, f"Failed to create service: {e}"
    finally:
        # Cleanup temp file
        if "temp_path" in dir() and temp_path.exists():
            temp_path.unlink()


def manage_service(name: str, action: str) -> Tuple[bool, str]:
    """Manage a systemd service.

    Args:
        name: Service name
        action: One of "start", "stop", "restart", "enable", "disable", "status"

    Returns:
        Tuple of (success, message/status)
    """
    valid_actions = ["start", "stop", "restart", "enable", "disable", "status"]
    if action not in valid_actions:
        return False, f"Invalid action. Use: {', '.join(valid_actions)}"

    ret, stdout, stderr = run_command(["systemctl", action, name], sudo=True)

    if action == "status":
        # Status returns non-zero for stopped services
        return True, stdout or stderr
    elif ret == 0:
        return True, f"Service {name} {action}ed successfully"
    else:
        return False, f"Failed to {action} {name}: {stderr[:50]}"


def check_service_status(name: str) -> Tuple[bool, str]:
    """Check if a systemd service is running.

    Args:
        name: Service name

    Returns:
        Tuple of (is_running, status_message)
    """
    ret, stdout, _ = run_command(["systemctl", "is-active", name], sudo=False)
    is_running = stdout.strip() == "active"
    return is_running, stdout.strip()


# =============================================================================
# Clone/Install meshing-around
# =============================================================================


def clone_meshing_around(
    install_path: Optional[Path] = None, progress_callback: Optional[Callable[[str], None]] = None
) -> UpdateResult:
    """Clone the meshing-around repository.

    Args:
        install_path: Where to clone. Defaults to ~/meshing-around
        progress_callback: Optional callback for progress messages

    Returns:
        UpdateResult with details
    """

    def report(msg: str):
        if progress_callback:
            progress_callback(msg)

    if install_path is None:
        install_path = Path.home() / "meshing-around"

    result = UpdateResult(success=True, message="")

    if install_path.exists():
        if (install_path / "mesh_bot.py").exists():
            return UpdateResult(success=True, message=f"meshing-around already installed at {install_path}")
        else:
            return UpdateResult(
                success=False,
                message=f"Directory exists but doesn't contain meshing-around: {install_path}",
                errors=["Path exists but is not meshing-around"],
            )

    report(f"Cloning meshing-around to {install_path}...")

    ret, stdout, stderr = run_command(
        ["git", "clone", "https://github.com/SpudGunMan/meshing-around.git", str(install_path)]
    )

    if ret == 0:
        result.message = f"Cloned meshing-around to {install_path}"
        result.changes.append("Repository cloned")
    else:
        result.success = False
        result.message = f"Clone failed: {stderr[:100]}"
        result.errors.append(stderr)

    return result

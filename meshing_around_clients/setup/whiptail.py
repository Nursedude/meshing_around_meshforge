"""Whiptail dialog helpers with print/input fallback.

Provides raspi-config-style menus using whiptail (pre-installed on Raspberry
Pi OS). Falls back to numbered print/input menus when whiptail is unavailable
(e.g. macOS, non-Debian Linux, piped stdin).

All functions accept height/width but auto-size when omitted.
"""

import os
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

HAS_WHIPTAIL: bool = bool(shutil.which("whiptail"))
BACKTITLE: str = "MeshForge"

# ANSI codes — duplicated here to avoid circular imports with mesh_client
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _is_tty() -> bool:
    """Check if stdin/stdout are connected to a real terminal."""
    return hasattr(sys.stdin, "fileno") and os.isatty(sys.stdin.fileno())


def _can_use_whiptail() -> bool:
    """Return True if whiptail is available AND we have a real terminal."""
    return HAS_WHIPTAIL and _is_tty()


_WHIPTAIL_TIMEOUT: int = 30  # seconds


def _reset_terminal() -> None:
    """Restore terminal to sane state after whiptail corruption.

    Whiptail uses newt/ncurses which changes terminal mode.  If it is
    killed (timeout) or crashes before restoring, \n no longer implies
    \r and the fallback menus render garbled.  ``stty sane`` fixes this.
    """
    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
        subprocess.run(["stty", "sane"], stdin=tty_fd, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        os.close(tty_fd)
    except OSError:
        pass


def _run_whiptail(cmd: List[str]) -> Optional[subprocess.CompletedProcess]:
    """Run a whiptail command safely.

    Lets whiptail render its UI via /dev/tty (stdout not piped),
    captures only stderr (where whiptail returns user selections),
    and enforces a timeout to prevent hangs in broken terminal environments.

    Returns the CompletedProcess on success, or None on timeout/error.
    """
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_WHIPTAIL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _reset_terminal()
        return None
    except OSError:
        _reset_terminal()
        return None


# ---------------------------------------------------------------------------
# Whiptail wrappers
# ---------------------------------------------------------------------------


def menu(
    title: str,
    items: List[Tuple[str, str]],
    default: str = "",
    height: int = 0,
    width: int = 60,
) -> Optional[str]:
    """Show a menu. Returns selected tag or None if user cancelled.

    Args:
        title: Menu title shown at the top.
        items: List of (tag, description) tuples.
        default: Tag to highlight initially.
        height: Dialog height (0 = auto).
        width: Dialog width.
    """
    if not _can_use_whiptail():
        return _fallback_menu(title, items, default)

    menu_height = len(items)
    if height == 0:
        height = menu_height + 8
    cmd = [
        "whiptail",
        "--backtitle",
        BACKTITLE,
        "--title",
        title,
        "--menu",
        "",
        str(height),
        str(width),
        str(menu_height),
    ]
    if default:
        cmd.extend(["--default-item", default])
    for tag, desc in items:
        cmd.extend([tag, desc])

    result = _run_whiptail(cmd)
    if result is None:
        return _fallback_menu(title, items, default)
    if result.returncode != 0:
        return None
    return result.stderr.strip()


def yesno(
    question: str,
    default_yes: bool = True,
    height: int = 8,
    width: int = 60,
) -> bool:
    """Yes/No dialog. Returns True for yes."""
    if not _can_use_whiptail():
        return _fallback_yesno(question, default_yes)

    cmd = [
        "whiptail",
        "--backtitle",
        BACKTITLE,
        "--title",
        "Confirm",
        "--yesno",
        question,
        str(height),
        str(width),
    ]
    if not default_yes:
        cmd.append("--defaultno")
    result = _run_whiptail(cmd)
    if result is None:
        return _fallback_yesno(question, default_yes)
    return result.returncode == 0


def msgbox(
    message: str,
    title: str = "Info",
    height: int = 10,
    width: int = 60,
) -> None:
    """Information dialog box."""
    if not _can_use_whiptail():
        _fallback_msgbox(message, title)
        return

    cmd = [
        "whiptail",
        "--backtitle",
        BACKTITLE,
        "--title",
        title,
        "--msgbox",
        message,
        str(height),
        str(width),
    ]
    result = _run_whiptail(cmd)
    if result is None:
        _fallback_msgbox(message, title)


def inputbox(
    prompt: str,
    default: str = "",
    height: int = 8,
    width: int = 60,
) -> Optional[str]:
    """Text input dialog. Returns entered text or None if cancelled."""
    if not _can_use_whiptail():
        return _fallback_inputbox(prompt, default)

    cmd = [
        "whiptail",
        "--backtitle",
        BACKTITLE,
        "--title",
        "Input",
        "--inputbox",
        prompt,
        str(height),
        str(width),
        default,
    ]
    result = _run_whiptail(cmd)
    if result is None:
        return _fallback_inputbox(prompt, default)
    if result.returncode != 0:
        return None
    return result.stderr.strip()


def radiolist(
    title: str,
    items: List[Tuple[str, str, bool]],
    height: int = 0,
    width: int = 60,
) -> Optional[str]:
    """Radio-button list. Returns selected tag or None if cancelled.

    Args:
        title: Dialog title.
        items: List of (tag, description, is_selected) tuples.
        height: Dialog height (0 = auto).
        width: Dialog width.
    """
    if not _can_use_whiptail():
        return _fallback_radiolist(title, items)

    list_height = len(items)
    if height == 0:
        height = list_height + 8
    cmd = [
        "whiptail",
        "--backtitle",
        BACKTITLE,
        "--title",
        title,
        "--radiolist",
        "",
        str(height),
        str(width),
        str(list_height),
    ]
    for tag, desc, selected in items:
        cmd.extend([tag, desc, "ON" if selected else "OFF"])

    result = _run_whiptail(cmd)
    if result is None:
        return _fallback_radiolist(title, items)
    if result.returncode != 0:
        return None
    return result.stderr.strip()


# ---------------------------------------------------------------------------
# Fallback implementations (print/input, no external deps)
# ---------------------------------------------------------------------------


def _fallback_menu(
    title: str,
    items: List[Tuple[str, str]],
    default: str = "",
) -> Optional[str]:
    """Numbered menu using print/input."""
    print(f"\n{_CYAN}{_BOLD}{title}{_RESET}\n", flush=True)
    for i, (tag, desc) in enumerate(items, 1):
        marker = f" {_DIM}(default){_RESET}" if tag == default else ""
        print(f"  {i}. {desc}{marker}", flush=True)
    print("  0. Cancel / Back", flush=True)

    default_num = "0"
    for i, (tag, _) in enumerate(items, 1):
        if tag == default:
            default_num = str(i)
            break

    try:
        raw = input(f"\n{_CYAN}Select [{default_num}]:{_RESET} ").strip()
        choice = raw or default_num
    except (KeyboardInterrupt, EOFError):
        print()
        return None

    if choice == "0":
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return items[idx][0]
    except ValueError:
        # Try matching by tag directly
        for tag, _ in items:
            if tag == choice:
                return tag

    return None


def _fallback_yesno(question: str, default_yes: bool = True) -> bool:
    """Yes/No prompt using input()."""
    hint = "Y/n" if default_yes else "y/N"
    try:
        answer = input(f"{question} [{hint}]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return default_yes
    if not answer:
        return default_yes
    return answer in ("y", "yes")


def _fallback_msgbox(message: str, title: str = "Info") -> None:
    """Print a message."""
    print(f"\n{_CYAN}{_BOLD}{title}{_RESET}", flush=True)
    print(message, flush=True)
    try:
        input("\nPress Enter to continue...")
    except (KeyboardInterrupt, EOFError):
        print()


def _fallback_inputbox(prompt: str, default: str = "") -> Optional[str]:
    """Input prompt using input()."""
    hint = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{hint}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    return value or default


def _fallback_radiolist(
    title: str,
    items: List[Tuple[str, str, bool]],
) -> Optional[str]:
    """Radio list using numbered print/input."""
    print(f"\n{_CYAN}{_BOLD}{title}{_RESET}\n", flush=True)
    default_num = "1"
    for i, (tag, desc, selected) in enumerate(items, 1):
        marker = " *" if selected else ""
        print(f"  {i}. {desc}{marker}", flush=True)
        if selected:
            default_num = str(i)
    print("  0. Cancel", flush=True)

    try:
        raw = input(f"\n{_CYAN}Select [{default_num}]:{_RESET} ").strip()
        choice = raw or default_num
    except (KeyboardInterrupt, EOFError):
        print()
        return None

    if choice == "0":
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return items[idx][0]
    except ValueError:
        pass

    return None

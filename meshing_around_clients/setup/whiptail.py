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

    result = subprocess.run(cmd, capture_output=True, text=True)
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
    result = subprocess.run(cmd)
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
    subprocess.run(cmd)


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
    result = subprocess.run(cmd, capture_output=True, text=True)
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

    result = subprocess.run(cmd, capture_output=True, text=True)
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
    print(f"\n{_CYAN}{_BOLD}{title}{_RESET}\n")
    for i, (tag, desc) in enumerate(items, 1):
        marker = f" {_DIM}(default){_RESET}" if tag == default else ""
        print(f"  {i}. {desc}{marker}")
    print(f"  0. Cancel / Back")

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
    print(f"\n{_CYAN}{_BOLD}{title}{_RESET}")
    print(message)
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
    print(f"\n{_CYAN}{_BOLD}{title}{_RESET}\n")
    default_num = "1"
    for i, (tag, desc, selected) in enumerate(items, 1):
        marker = " *" if selected else ""
        print(f"  {i}. {desc}{marker}")
        if selected:
            default_num = str(i)
    print(f"  0. Cancel")

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

"""Shared formatting helpers for TUI screens.

Centralises repeated rendering logic (battery, SNR, health colours, severity
icons) so every screen uses the same thresholds and styling.
"""

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Health status colour map (used in DashboardScreen & TopologyScreen)
# ---------------------------------------------------------------------------
HEALTH_STATUS_COLORS = {
    "excellent": "green bold",
    "good": "green",
    "fair": "yellow",
    "poor": "orange1",
    "critical": "red bold",
    "unknown": "dim",
}

# ---------------------------------------------------------------------------
# Alert severity styling
# ---------------------------------------------------------------------------
SEVERITY_COLORS = {1: "blue", 2: "yellow", 3: "orange1", 4: "red bold"}
SEVERITY_ICONS = {1: "i", 2: "!", 3: "!!", 4: "!!!"}


def format_time_ago(seconds: float) -> str:
    """Return a human-readable 'time ago' string from a delta in seconds."""
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    else:
        return f"{int(seconds / 86400)}d ago"


def format_battery(level: Optional[int]) -> str:
    """Return a Rich-markup string for a battery percentage.

    Returns ``"-"`` when the level is None or <= 0.
    """
    if level is None or level <= 0:
        return "-"
    if level > 50:
        return f"[green]{level}%[/green]"
    if level > 20:
        return f"[yellow]{level}%[/yellow]"
    return f"[red]{level}%[/red]"


def format_snr(snr: Optional[float], *, unit: bool = False, styled: bool = False) -> str:
    """Return a formatted SNR string.

    Args:
        snr: Signal-to-noise ratio value, or None.
        unit: Append ``dB`` suffix when True.
        styled: Wrap in Rich colour markup when True.
    """
    if snr is None:
        return "-"
    suffix = "dB" if unit else ""
    value_str = f"{snr:.1f}{suffix}"
    if not styled:
        return value_str
    if snr > 0:
        style = "green"
    elif snr > -10:
        style = "yellow"
    else:
        style = "red"
    return f"[{style}]{value_str}[/{style}]"


def safe_num(value: Any, default: float = 0.0) -> float:
    """Coerce a JSON/API value to a number; None / non-numeric -> *default*.

    MapsScreen renders the meshforge-maps REST JSON, where a field can arrive as
    a JSON ``null`` or a wrong type. Such a value reaching a format spec
    (``f"{x:.1f}"``) or a comparison (``x > 5``) would raise and — via the
    screen-render guard — blank the Maps panel. ``bool`` is rejected (an ``int``
    subclass, but never a real metric here).
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    return default


def safe_str(value: Any, default: str = "") -> str:
    """Coerce a JSON/API value to a display ``str``; ``None`` -> *default*.

    Guards string fields handed to ``.lower()`` / slicing / a format spec — a
    JSON ``null`` (``None[-6:]``) would otherwise raise.
    """
    if value is None:
        return default
    return value if isinstance(value, str) else str(value)


def safe_panel_render(func: Callable, fallback_title: str = "") -> Any:
    """Wrap a panel-rendering callable so exceptions return an error Panel.

    Catches any exception, logs it at debug level, and returns a Rich Panel
    with an error placeholder instead of letting one sub-panel crash take
    down the entire screen.
    """
    try:
        return func()
    except Exception as e:
        logger.debug("Panel render error in %s: %s", fallback_title, e)
        try:
            from rich.panel import Panel

            return Panel(f"[dim]Error loading {fallback_title}[/dim]", border_style="dim")
        except ImportError:
            return None

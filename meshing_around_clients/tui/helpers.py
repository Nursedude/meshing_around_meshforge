"""Shared formatting helpers for TUI screens.

Centralises repeated rendering logic (battery, SNR, health colours, severity
icons) so every screen uses the same thresholds and styling.
"""

from typing import Optional

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

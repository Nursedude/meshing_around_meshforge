#!/usr/bin/env python3
"""
Meshing-Around TUI Application
A rich terminal interface for monitoring and managing Meshtastic mesh networks.

Based on MeshForge foundation principles:
- Beautiful UI with Rich library
- Modular and extensible design
- Graceful fallbacks for missing dependencies
"""

import json
import logging
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from meshing_around_clients.tui.helpers import (  # noqa: E402
    HEALTH_STATUS_COLORS,
    SEVERITY_COLORS,
    SEVERITY_ICONS,
    format_battery,
    format_snr,
    format_time_ago,
    safe_panel_render,
)

# Check for Rich library - do NOT auto-install (PEP 668 compliance)
try:
    from rich import box
    from rich.align import Align
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
    from rich.text import Text
    from rich.tree import Tree

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    # Provide stub classes for type hints when Rich is not available
    Panel = Any  # type: ignore
    Console = Any  # type: ignore
    Table = Any  # type: ignore
    Layout = Any  # type: ignore
    Live = Any  # type: ignore
    Text = Any  # type: ignore
    Prompt = Any  # type: ignore
    Confirm = Any  # type: ignore
    Progress = Any  # type: ignore
    SpinnerColumn = Any  # type: ignore
    TextColumn = Any  # type: ignore
    box = None  # type: ignore
    Group = Any  # type: ignore
    Align = Any  # type: ignore
    Columns = Any  # type: ignore
    Markdown = Any  # type: ignore
    Syntax = Any  # type: ignore
    Tree = Any  # type: ignore

from meshing_around_clients import __version__ as VERSION  # noqa: E402
from meshing_around_clients.core import Config, MeshtasticAPI  # noqa: E402
from meshing_around_clients.core.config import InterfaceConfig  # noqa: E402
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI  # noqa: E402
from meshing_around_clients.core.models import DATETIME_MIN_UTC, MAX_MESSAGE_BYTES, Message, MessageType  # noqa: E402


class PlainTextTUI:
    """Minimal plain-text fallback TUI for when Rich is not available.

    Displays a polling dashboard using only stdlib print(). Refreshes every
    2 seconds. Exit with Ctrl+C.
    """

    def __init__(self, config: Optional[Config] = None, demo_mode: bool = False):
        self.config = config or Config()
        self.demo_mode = demo_mode
        if demo_mode:
            self.api = MockMeshtasticAPI(self.config)
        else:
            self.api = MeshtasticAPI(self.config)

    def run(self) -> None:
        """Run the plain-text dashboard loop."""
        import os

        print("=" * 60)
        print(f"  MESHING-AROUND v{VERSION}  (plain-text mode)")
        print("  Rich library not found — install for full TUI")
        print("=" * 60)
        print()

        # Show config warnings
        try:
            issues = self.config.validate()
            for issue in issues:
                print(f"  WARNING: {issue}")
            if issues:
                print()
        except Exception:
            pass

        # Connect
        if not self.demo_mode:
            print("Connecting...")
            if not self.api.connect():
                print("Connection failed. Starting in demo mode.")
                self.demo_mode = True
                self.api = MockMeshtasticAPI(self.config)
                self.api.connect()
            else:
                print("Connected!")
        else:
            self.api.connect()
            print("Running in demo mode.")

        print("Press Ctrl+C to exit.\n")

        try:
            while True:
                # ANSI escape to clear screen and home cursor (no shell invocation)
                print("\033[2J\033[H", end="", flush=True)

                health = self.api.connection_health
                status = health.get("status", "unknown").upper()
                network = self.api.network

                print(f"MESHING-AROUND v{VERSION}  [{status}]")
                if self.demo_mode:
                    print("[DEMO MODE]")
                print("-" * 60)

                # Stats
                nodes = network.get_nodes_snapshot()
                messages = network.get_messages_snapshot()
                alerts = network.get_alerts_snapshot()
                print(f"  Nodes: {len(nodes)}  |  Messages: {len(messages)}  |  Alerts: {len(alerts)}")

                msg_rate = health.get("messages_per_minute")
                if msg_rate is not None:
                    print(f"  Message rate: {msg_rate:.1f} msg/min")
                print()

                # Last 5 messages
                print("Recent Messages:")
                recent = messages[-5:] if messages else []
                if not recent:
                    print("  (no messages)")
                for msg in reversed(recent):
                    ts = msg.timestamp.strftime("%H:%M:%S") if msg.timestamp else "??:??:??"
                    sender = msg.sender_name or msg.sender_id or "unknown"
                    text = (msg.text or "")[:50]
                    print(f"  [{ts}] {sender}: {text}")

                print(f"\n{'─' * 60}")
                print("Press Ctrl+C to exit.")
                time.sleep(2)
        except KeyboardInterrupt:
            pass
        finally:
            self.api.disconnect()
            print("\nGoodbye!")


class TUILogHandler(logging.Handler):
    """Captures log records in a circular buffer for the TUI log screen."""

    def __init__(self, maxlen: int = 500):
        super().__init__()
        from collections import deque

        self.records: deque = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord):
        self.records.append(record)


class Screen:
    """Base class for TUI screens."""

    def __init__(self, app: "MeshingAroundTUI"):
        self.app = app
        self.console = app.console

    def render(self) -> Panel:
        """Render the screen content."""
        raise NotImplementedError

    def handle_input(self, key: str) -> bool:
        """Handle keyboard input. Return True if handled."""
        return False


class DashboardScreen(Screen):
    """Main dashboard screen — message-centric live feed with network status."""

    def render(self) -> Panel:
        layout = Layout()

        # Create sub-panels with crash isolation
        stats = safe_panel_render(self._create_stats_panel, "stats")
        feed = safe_panel_render(self._create_feed_panel, "feed")
        sidebar = safe_panel_render(self._create_sidebar_panel, "sidebar")

        # Combine into layout — message feed is primary
        if not self.app.api.is_connected:
            hint = Text(
                "Press [c] to connect  ·  [?] help  ·  [q] quit",
                style="bold yellow",
                justify="center",
            )
            layout.split_column(
                Layout(stats, name="stats", size=7),
                Layout(hint, name="hint", size=1),
                Layout(name="main"),
            )
        else:
            layout.split_column(Layout(stats, name="stats", size=7), Layout(name="main"))

        layout["main"].split_row(
            Layout(feed, name="feed", ratio=3),
            Layout(sidebar, name="sidebar", ratio=1),
        )

        return Panel(
            layout,
            title="[bold cyan]Meshing-Around Dashboard[/bold cyan]",
            subtitle=f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
            border_style="cyan",
        )

    def _create_stats_panel(self) -> Panel:
        """Create compact network status panel with connection, MQTT, and health info."""
        network = self.app.api.network
        conn = self.app.api.connection_info

        # Connection health status
        conn_health = self.app.api.connection_health
        conn_status = conn_health.get("status", "unknown")
        conn_status_map = {
            "healthy": ("CONNECTED", "bold green"),
            "slow": ("SLOW", "bold yellow"),
            "stale": ("STALE", "bold yellow"),
            "degraded": ("DEGRADED", "bold yellow"),
            "connected_no_traffic": ("NO TRAFFIC", "dim yellow"),
            "disconnected": ("DISCONNECTED", "bold red"),
        }
        label, style = conn_status_map.get(conn_status, (conn_status.upper(), "white"))

        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Label", style="cyan")
        stats_table.add_column("Value", style="white bold")
        stats_table.add_column("Label2", style="cyan")
        stats_table.add_column("Value2", style="white bold")
        stats_table.add_column("Label3", style="cyan")
        stats_table.add_column("Value3", style="white bold")

        # Row 1: Connection + nodes + messages
        stats_table.add_row(
            "Status", Text(label, style=style),
            "Nodes", f"{len(network.online_nodes)}/{len(network.nodes)}",
            "Messages", str(network.total_messages),
        )

        # Row 2: Interface info — adapt labels to connection type
        iface_str = f"{conn.interface_type}"
        if conn.device_path:
            iface_str += f" ({conn.device_path})"

        iface_type = conn.interface_type or ""
        if iface_type == "mqtt" and hasattr(self.app, "config"):
            mqtt_cfg = self.app.config.mqtt
            col2_label, col2_val = "Topic", mqtt_cfg.topic_root or "--"
            col3_label, col3_val = "Channels", mqtt_cfg.channels or str(mqtt_cfg.channel)
        elif iface_type in ("tcp", "serial", "ble"):
            col2_label, col2_val = "Device", "Meshtastic"
            col3_label, col3_val = "", ""
        else:
            col2_label, col2_val = "", ""
            col3_label, col3_val = "", ""

        stats_table.add_row("Interface", iface_str, col2_label, col2_val, col3_label, col3_val)

        # Row 3: Health + rx stats + alerts
        health = network.mesh_health
        health_status = health.get("status", "unknown")
        health_score = health.get("score", 0)
        health_style = HEALTH_STATUS_COLORS.get(health_status, "white")

        rx_str = str(network.total_messages) if network.total_messages else "--"
        if hasattr(self.app.api, "stats"):
            mqtt_stats = self.app.api.stats
            rx = mqtt_stats.get("messages_received", 0)
            rej = mqtt_stats.get("messages_rejected", 0)
            if rx:
                rx_str = str(rx)
                if rej:
                    rx_str += f" ({rej} rej)"

        alert_count = len(network.unread_alerts)
        alert_str = f"[red bold]{alert_count} unread[/red bold]" if alert_count else "[dim green]none[/dim green]"
        stats_table.add_row(
            "Health", Text(f"{health_status.upper()} ({health_score}%)", style=health_style),
            "Rx Msgs", rx_str,
            "Alerts", Text.from_markup(alert_str),
        )

        # Row 4: Default channel + avg SNR + channel utilization
        default_ch = "--"
        if hasattr(self.app, "config"):
            upstream = self.app.config.read_upstream_settings()
            if upstream and "defaultchannel" in upstream:
                default_ch = "ch" + str(upstream["defaultchannel"])
        avg_snr = health.get("avg_snr", 0)
        avg_util = health.get("avg_channel_utilization", 0)
        if avg_util >= 40.0:
            util_str = f"[red bold]{avg_util:.1f}%[/red bold]"
        elif avg_util >= 25.0:
            util_str = f"[yellow]{avg_util:.1f}%[/yellow]"
        elif avg_util > 0:
            util_str = f"[green]{avg_util:.1f}%[/green]"
        else:
            util_str = "--"
        stats_table.add_row(
            "Default Ch", default_ch,
            "Avg SNR", f"{avg_snr:.1f} dB" if avg_snr else "--",
            "Ch Util", Text.from_markup(util_str),
        )

        return Panel(stats_table, title="[bold]Network Status[/bold]", border_style="blue")

    def _create_feed_panel(self) -> Panel:
        """Create the live message feed — primary display showing all channel traffic."""
        messages = self.app.api.network.get_messages_snapshot()[-30:]

        # Channel name/color mapping for visual distinction
        ch_colors = ["cyan", "green", "yellow", "magenta", "blue", "red", "white", "bright_cyan"]

        content = []
        for msg in reversed(messages):
            time_str = msg.time_formatted
            sender = msg.sender_name or (msg.sender_id or "unknown")[-6:]
            ch_idx = msg.channel if isinstance(msg.channel, int) else 0
            ch_color = ch_colors[ch_idx % len(ch_colors)]

            if msg.is_incoming:
                direction = "<<"
                dir_style = "cyan"
            else:
                direction = ">>"
                dir_style = "green"

            # Check for emergency keywords
            is_emergency = msg.text and any(
                kw.lower() in msg.text.lower() for kw in self.app.config.alerts.emergency_keywords
            )

            text = msg.text or ""
            line = Text()
            line.append(f"{time_str} ", style="dim")
            line.append(f"ch{ch_idx}", style=f"bold {ch_color}")
            line.append(f" {direction} ", style=dir_style)
            line.append(f"{sender}: ", style="cyan bold" if msg.is_incoming else "green")
            line.append(
                text[:120] if not is_emergency else text[:120],
                style="bold red" if is_emergency else "white",
            )
            if len(text) > 120:
                line.append("...", style="dim")

            content.append(line)

        if not content:
            if self.app.api.is_connected:
                content.append(Text("Listening for messages...", style="dim yellow"))
                content.append(Text(""))
                conn = self.app.api.connection_info
                if conn.interface_type == "mqtt" and hasattr(self.app, "config"):
                    mqtt_cfg = self.app.config.mqtt
                    topic = mqtt_cfg.topic_root or "msh/US"
                    ch = mqtt_cfg.channels if mqtt_cfg.channels else mqtt_cfg.channel
                    content.append(Text(f"  Subscribed to: {topic}/{ch}", style="dim"))
                content.append(Text("  Messages will appear here as they arrive", style="dim"))
            else:
                content.append(Text("Not connected", style="dim red"))
                content.append(Text(""))
                content.append(Text("  Press [c] to connect to MQTT/serial/TCP", style="dim"))
                content.append(Text("  Press [r] to run local commands (weather, volcano, tsunami)", style="dim"))

        return Panel(
            Group(*content),
            title="[bold]Live Feed[/bold]",
            subtitle="[dim]\\[3] Messages  \\[s] send  \\[r] run cmd[/dim]",
            border_style="magenta",
        )

    def _create_sidebar_panel(self) -> Panel:
        """Create sidebar with nodes, alerts, and bot status."""
        network = self.app.api.network
        content = []

        # --- Active Nodes (compact) ---
        nodes = sorted(
            network.get_nodes_snapshot(),
            key=lambda n: n.last_heard or DATETIME_MIN_UTC,
            reverse=True,
        )[:8]

        content.append(Text(f"Nodes ({len(network.online_nodes)} online)", style="bold green"))
        if nodes:
            for node in nodes:
                name = node.display_name[:14]
                heard = node.time_since_heard
                if node.is_favorite:
                    nstyle = "yellow bold"
                elif not node.is_online:
                    nstyle = "dim"
                else:
                    nstyle = "white"
                line = Text()
                line.append(f"  {name:<14s}", style=nstyle)
                line.append(f" {heard}", style="dim")
                batt = node.telemetry.battery_level if node.telemetry else None
                if batt is not None:
                    line.append(f" {batt}%", style="green" if batt > 20 else "red")
                content.append(line)
        else:
            content.append(Text("  Waiting for nodes...", style="dim"))
        content.append(Text(""))

        # --- Alerts (compact) ---
        alerts = network.get_alerts_snapshot()[-3:]
        alert_count = len(network.unread_alerts)
        alert_label = f"Alerts ({alert_count} unread)" if alert_count else "Alerts"
        content.append(Text(alert_label, style="bold red" if alert_count else "bold blue"))
        if alerts:
            for alert in reversed(alerts):
                style = SEVERITY_COLORS.get(alert.severity, "white")
                icon = SEVERITY_ICONS.get(alert.severity, "*")
                content.append(Text(f"  {icon} {alert.title[:25]}", style=style))
        else:
            content.append(Text("  No alerts", style="dim green"))
        content.append(Text(""))

        # --- Bot Status (upstream features) ---
        content.append(Text("Bot Features", style="bold cyan"))
        if hasattr(self.app, "config") and hasattr(self.app.config, "read_upstream_commands"):
            try:
                upstream = self.app.config.read_upstream_commands()
                if upstream:
                    on_features = [name for name, enabled in sorted(upstream.items()) if enabled]
                    off_features = [name for name, enabled in sorted(upstream.items()) if not enabled]
                    if on_features:
                        content.append(Text(f"  ON: {', '.join(on_features[:6])}", style="green"))
                        if len(on_features) > 6:
                            content.append(Text(f"      +{len(on_features)-6} more", style="dim green"))
                    if off_features:
                        content.append(Text(f"  off: {', '.join(off_features[:4])}", style="dim"))
                else:
                    template = self.app.config.get_upstream_template_path()
                    if template:
                        content.append(Text("  config.template found (no config.ini)", style="dim yellow"))
                    else:
                        content.append(Text("  No upstream config found", style="dim"))
            except (OSError, ValueError):
                content.append(Text("  Could not read bot config", style="dim"))
        else:
            content.append(Text("  N/A", style="dim"))

        return Panel(
            Group(*content),
            title="[bold]Status[/bold]",
            border_style="green",
        )


class NodesScreen(Screen):
    """Detailed nodes view screen with pagination, search, and environment telemetry."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self.page = 0
        self.page_size = 20
        self.search_query = ""
        self.search_active = False

    def _filter_nodes(self, nodes):
        """Apply search filter to node list."""
        if not self.search_query:
            return nodes
        query = self.search_query.lower()
        return [
            n
            for n in nodes
            if query in (n.display_name or "").lower()
            or query in (n.node_id or "").lower()
            or query in (n.hardware_model or "").lower()
            or query in (n.short_name or "").lower()
        ]

    def render(self) -> Panel:
        all_nodes = sorted(
            self.app.api.network.get_nodes_snapshot(), key=lambda n: n.last_heard or DATETIME_MIN_UTC, reverse=True
        )
        total_all = len(all_nodes)
        nodes = self._filter_nodes(all_nodes)

        # Pagination
        total_pages = max(1, (len(nodes) + self.page_size - 1) // self.page_size)
        self.page = min(self.page, total_pages - 1)
        start = self.page * self.page_size
        page_nodes = nodes[start : start + self.page_size]

        # Check if any node on this page has environment data
        has_env = any(n.telemetry and n.telemetry.has_environment_data for n in page_nodes)

        table = Table(
            show_header=True, header_style="bold cyan", box=box.ROUNDED, expand=True, title="Mesh Network Nodes"
        )

        table.add_column("#", style="dim", width=4)
        table.add_column("Node ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="white")
        table.add_column("Hardware", style="blue")
        table.add_column("Role", style="magenta")
        table.add_column("Last Heard", style="dim")
        table.add_column("Battery", justify="right")
        table.add_column("SNR", justify="right")
        table.add_column("Hops", justify="center")
        if has_env:
            table.add_column("Temp", justify="right")
            table.add_column("Hum", justify="right")

        for idx, node in enumerate(page_nodes, start + 1):
            # Status indicator
            if node.is_favorite:
                status_style = "yellow"
            elif node.is_online:
                status_style = "green"
            else:
                status_style = "red"

            # Battery
            batt_level = node.telemetry.battery_level if node.telemetry else None
            batt_str = format_battery(batt_level)

            # SNR
            snr = node.telemetry.snr if node.telemetry else None
            snr_str = format_snr(snr, unit=True)

            row = [
                f"[{status_style}]{idx}[/{status_style}]",
                node.node_id[-8:],
                node.display_name,
                node.hardware_model,
                node.role.value if node.role else "UNKNOWN",
                node.time_since_heard,
                batt_str,
                snr_str,
                str(node.hop_count) if node.hop_count else "0",
            ]

            # Environment telemetry columns
            if has_env:
                if node.telemetry and node.telemetry.temperature is not None:
                    row.append(f"{node.telemetry.temperature:.1f}C")
                else:
                    row.append("-")
                if node.telemetry and node.telemetry.humidity is not None:
                    row.append(f"{node.telemetry.humidity:.0f}%")
                else:
                    row.append("-")

            table.add_row(*row)

        # Build subtitle with search state
        if self.search_active:
            subtitle = f"[bold yellow]Search: {self.search_query}_[/bold yellow] | Esc: cancel | Enter: confirm"
        elif self.search_query:
            page_info = f"Page {self.page + 1}/{total_pages} ({len(nodes)}/{total_all} match)"
            subtitle = f"[dim]{page_info} | /: search | Esc: clear | j/k: page | q: return[/dim]"
        else:
            page_info = f"Page {self.page + 1}/{total_pages} ({total_all} nodes)"
            subtitle = f"[dim]{page_info} | /: search | j/k: page down/up | q: return[/dim]"

        return Panel(
            table,
            title="[bold cyan]Nodes[/bold cyan]",
            subtitle=subtitle,
            border_style="cyan",
        )

    def handle_input(self, key: str) -> bool:
        # Search mode: consume all keys
        if self.search_active:
            if key == "\x1b":  # Escape — cancel search
                self.search_query = ""
                self.search_active = False
            elif key in ("\n", "\r"):  # Enter — confirm search
                self.search_active = False
            elif key in ("\x7f", "\x08"):  # Backspace
                self.search_query = self.search_query[:-1]
            elif key.isprintable() and len(key) == 1:
                self.search_query += key
            return True

        if key == "/":
            self.search_active = True
            self.search_query = ""
            self.page = 0
            return True
        elif key == "\x1b" and self.search_query:
            # Escape clears confirmed search filter
            self.search_query = ""
            self.page = 0
            return True
        elif key == "j":
            total_nodes = len(self._filter_nodes(self.app.api.network.get_nodes_snapshot()))
            total_pages = max(1, (total_nodes + self.page_size - 1) // self.page_size)
            self.page = min(self.page + 1, total_pages - 1)
            return True
        elif key == "k":
            self.page = max(0, self.page - 1)
            return True
        return False


class MessagesScreen(Screen):
    """Detailed messages view screen with channel filtering and text search."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self.channel_filter: Optional[int] = None
        self.search_query = ""
        self.search_active = False

    def _filter_messages(self, messages):
        """Apply search filter to message list."""
        if not self.search_query:
            return messages
        query = self.search_query.lower()
        return [
            m
            for m in messages
            if query in (m.text or "").lower()
            or query in (m.sender_name or "").lower()
            or query in (m.sender_id or "").lower()
        ]

    def render(self) -> Panel:
        all_messages = self.app.api.network.get_messages_snapshot()
        if self.channel_filter is not None:
            all_messages = [m for m in all_messages if m.channel == self.channel_filter]

        total_all = len(all_messages)
        filtered = self._filter_messages(all_messages)
        messages = filtered[-30:]  # Last 30 messages

        table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE, expand=True)

        table.add_column("Time", style="dim", width=8)
        table.add_column("Ch", justify="center", width=3)
        table.add_column("Dir", width=3)
        table.add_column("From", style="cyan", width=15)
        table.add_column("To", style="blue", width=15)
        table.add_column("Message", style="white")
        table.add_column("SNR", justify="right", width=6)

        for msg in reversed(messages):
            direction = "[green]>>[/green]" if not msg.is_incoming else "[cyan]<<[/cyan]"

            to_str = "broadcast" if msg.is_broadcast else (msg.recipient_id or "?")[-6:]
            from_str = msg.sender_name or (msg.sender_id or "?")[-6:]

            # Truncate message
            text = (msg.text or "")[:50]
            if len(msg.text or "") > 50:
                text += "..."

            snr_str = format_snr(msg.snr)

            table.add_row(msg.time_formatted, str(msg.channel), direction, from_str, to_str, text, snr_str)

        filter_text = f"Channel {self.channel_filter}" if self.channel_filter is not None else "All channels"

        # Build subtitle with search state
        if self.search_active:
            subtitle = f"[bold yellow]Search: {self.search_query}_[/bold yellow] | Esc: cancel | Enter: confirm"
        elif self.search_query:
            subtitle = (
                f"[dim]{len(filtered)}/{total_all} match | "
                "/: search | Esc: clear | 0-7: channel | a: all | e: export | q: return[/dim]"
            )
        else:
            subtitle = "[dim]/: search | 0-7: channel | a: all | e: JSON | E: CSV | q: return[/dim]"

        return Panel(
            table,
            title=f"[bold cyan]Messages[/bold cyan] - {filter_text}",
            subtitle=subtitle,
            border_style="magenta",
        )

    def handle_input(self, key: str) -> bool:
        # Search mode: consume all keys
        if self.search_active:
            if key == "\x1b":  # Escape — cancel search
                self.search_query = ""
                self.search_active = False
            elif key in ("\n", "\r"):  # Enter — confirm search
                self.search_active = False
            elif key in ("\x7f", "\x08"):  # Backspace
                self.search_query = self.search_query[:-1]
            elif key.isprintable() and len(key) == 1:
                self.search_query += key
            return True

        if key == "/":
            self.search_active = True
            self.search_query = ""
            return True
        elif key == "\x1b" and self.search_query:
            # Escape clears confirmed search filter
            self.search_query = ""
            return True
        elif key.isdigit() and int(key) < 8:
            self.channel_filter = int(key)
            return True
        elif key == "a":
            self.channel_filter = None
            return True
        elif key == "e":
            self._export_messages(fmt="json")
            return True
        elif key == "E":
            self._export_messages(fmt="csv")
            return True
        return False

    def _export_messages(self, fmt: str = "json") -> None:
        """Export current message view to a file."""
        try:
            from datetime import datetime as dt

            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            filename = f"meshforge_messages_{timestamp}.{fmt}"
            data = self.app.api.network.export_messages(
                fmt=fmt,
                channel=self.channel_filter,
            )
            with open(filename, "w", encoding="utf-8") as f:
                f.write(data)
            logger.info("Messages exported to %s", filename)
        except (OSError, ValueError) as e:
            logger.error("Failed to export messages: %s", e)


class AlertsScreen(Screen):
    """Detailed alerts view screen with severity filtering, search, and acknowledgment."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self.severity_filter: Optional[int] = None
        self.search_query: str = ""
        self.search_active: bool = False

    def render(self) -> Panel:
        all_alerts = self.app.api.network.get_alerts_snapshot()
        if self.severity_filter is not None:
            all_alerts = [a for a in all_alerts if a.severity == self.severity_filter]

        # Text search filter
        if self.search_query:
            q = self.search_query.lower()
            all_alerts = [a for a in all_alerts if q in (a.title or "").lower() or q in (a.message or "").lower()]

        alerts = all_alerts[-20:]

        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED, expand=True)

        table.add_column("Time", style="dim", width=12)
        table.add_column("Sev", justify="center", width=4)
        table.add_column("Type", style="blue", width=12)
        table.add_column("Title", style="white")
        table.add_column("Message", style="dim")
        table.add_column("Ack", justify="center", width=4)

        for alert in reversed(alerts):
            sev_color = SEVERITY_COLORS.get(alert.severity, "white")
            sev_icon = SEVERITY_ICONS.get(alert.severity, "*")

            ack = "[green]Yes[/green]" if alert.acknowledged else "[red]No[/red]"

            table.add_row(
                alert.timestamp.strftime("%H:%M:%S") if alert.timestamp else "-",
                f"[{sev_color}]{sev_icon}[/{sev_color}]",
                alert.alert_type.value,
                alert.title[:25],
                alert.message[:40],
                ack,
            )

        sev_labels = {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}
        filter_text = sev_labels.get(self.severity_filter, "All severities")
        unread = len(self.app.api.network.unread_alerts)

        title = f"[bold cyan]Alerts[/bold cyan] - {filter_text} ({unread} unread)"
        if self.search_active:
            title += f"  [yellow]Search: {self.search_query}_[/yellow]"
        elif self.search_query:
            title += f"  [green]Filter: {self.search_query}[/green]"

        return Panel(
            table,
            title=title,
            subtitle="[dim]/: search | l/m/H/C: severity | a: all | x: ack all | q: return[/dim]",
            border_style="red",
        )

    def handle_input(self, key: str) -> bool:
        # Search mode input handling
        if self.search_active:
            if key == "\n" or key == "\r":
                self.search_active = False
            elif key == "\x1b":  # Escape
                self.search_query = ""
                self.search_active = False
            elif key in ("\x7f", "\x08"):  # Backspace
                self.search_query = self.search_query[:-1]
            elif key.isprintable() and len(key) == 1:
                self.search_query += key
            return True

        if key == "/":
            self.search_active = True
            self.search_query = ""
            return True
        elif key == "\x1b" and self.search_query:
            # Escape clears confirmed search filter
            self.search_query = ""
            return True
        elif key == "l":
            self._cycle_severity_filter(1)
            return True
        elif key == "m":
            self._cycle_severity_filter(2)
            return True
        elif key == "H":
            self._cycle_severity_filter(3)
            return True
        elif key == "C":
            self._cycle_severity_filter(4)
            return True
        elif key == "a":
            self.severity_filter = None
            return True
        elif key == "x":
            # Acknowledge all unread alerts (snapshot for safe iteration)
            for alert in self.app.api.network.get_alerts_snapshot():
                alert.acknowledged = True
            return True
        return False

    def _cycle_severity_filter(self, severity: int) -> None:
        """Toggle severity filter: set if different, clear if same."""
        if self.severity_filter == severity:
            self.severity_filter = None
        else:
            self.severity_filter = severity


class TopologyScreen(Screen):
    """Mesh topology and health visualization screen."""

    def render(self) -> Panel:
        layout = Layout()

        # Create sub-panels with crash isolation
        health_panel = safe_panel_render(self._create_health_panel, "health")
        topology_panel = safe_panel_render(self._create_topology_panel, "topology")
        routes_panel = safe_panel_render(self._create_routes_panel, "routes")
        channels_panel = safe_panel_render(self._create_channels_panel, "channels")

        # Layout: Health at top, then topology/routes, channels at bottom
        layout.split_column(
            Layout(health_panel, name="health", size=7),
            Layout(name="main"),
            Layout(channels_panel, name="channels", size=10),
        )
        layout["main"].split_row(Layout(topology_panel, name="topology"), Layout(routes_panel, name="routes"))

        return Panel(
            layout,
            title="[bold cyan]Mesh Topology[/bold cyan]",
            subtitle="[dim]Press 'q' to return to dashboard[/dim]",
            border_style="cyan",
        )

    def _create_health_panel(self) -> Panel:
        """Create mesh health overview panel."""
        health = self.app.api.network.mesh_health

        # Status color mapping
        status_style = HEALTH_STATUS_COLORS.get(health["status"], "white")

        # Create health bar visualization
        score = health.get("score", 0)
        bar_width = 30
        filled = int((score / 100) * bar_width)
        health_bar = "[green]" + "" * filled + "[/green][dim]" + "" * (bar_width - filled) + "[/dim]"

        table = Table(show_header=False, box=None, padding=(0, 3))
        table.add_column("Label", style="cyan")
        table.add_column("Value")

        table.add_row("Status", f"[{status_style}]{health['status'].upper()}[/{status_style}]")
        table.add_row("Health Score", f"{health_bar} {score}%")
        table.add_row(
            "Online Nodes", f"[green]{health.get('online_nodes', 0)}[/green] / {health.get('total_nodes', 0)}"
        )
        table.add_row("Avg SNR", f"{health.get('avg_snr', 0):.1f} dB")
        table.add_row("Channel Util", f"{health.get('avg_channel_utilization', 0):.1f}%")

        return Panel(table, title="[bold]Mesh Health[/bold]", border_style="green")

    def _create_topology_panel(self) -> Panel:
        """Create mesh topology tree visualization."""
        network = self.app.api.network

        # Build tree showing node relationships
        tree = Tree("[bold cyan]Mesh Network[/bold cyan]")

        # Group nodes by hop count
        direct_nodes = []
        one_hop = []
        multi_hop = []

        for node in network.get_nodes_snapshot():
            if node.hop_count == 0:
                direct_nodes.append(node)
            elif node.hop_count == 1:
                one_hop.append(node)
            else:
                multi_hop.append(node)

        # Add direct nodes
        if direct_nodes:
            direct_branch = tree.add("[green]Direct (0 hops)[/green]")
            for node in sorted(direct_nodes, key=lambda n: n.display_name):
                self._add_node_to_tree(direct_branch, node)

        # Add 1-hop nodes
        if one_hop:
            one_hop_branch = tree.add("[yellow]1 Hop[/yellow]")
            for node in sorted(one_hop, key=lambda n: n.display_name):
                self._add_node_to_tree(one_hop_branch, node)

        # Add multi-hop nodes
        if multi_hop:
            multi_branch = tree.add("[orange1]Multi-hop[/orange1]")
            for node in sorted(multi_hop, key=lambda n: n.display_name):
                self._add_node_to_tree(multi_branch, node)

        return Panel(tree, title="[bold]Topology[/bold]", border_style="blue")

    def _add_node_to_tree(self, parent, node) -> None:
        """Add a node entry to the tree."""
        # Build node label with quality info
        quality = ""
        if node.link_quality and node.link_quality.packet_count > 0:
            q_pct = node.link_quality.quality_percent
            if q_pct >= 70:
                q_color = "green"
            elif q_pct >= 40:
                q_color = "yellow"
            else:
                q_color = "red"
            quality = f" [{q_color}]{q_pct}%[/{q_color}]"

        online = "[green][/green]" if node.is_online else "[red][/red]"
        label = f"{online} {node.display_name[:20]}{quality}"

        node_branch = parent.add(label)

        # Add neighbor info if available
        if node.neighbors:
            neighbors_str = ", ".join(n[-6:] for n in node.neighbors[:5])
            if len(node.neighbors) > 5:
                neighbors_str += f" +{len(node.neighbors) - 5} more"
            node_branch.add(f"[dim]Hears: {neighbors_str}[/dim]")

        if node.heard_by:
            heard_str = ", ".join(h[-6:] for h in node.heard_by[:5])
            if len(node.heard_by) > 5:
                heard_str += f" +{len(node.heard_by) - 5} more"
            node_branch.add(f"[dim]Heard by: {heard_str}[/dim]")

    def _create_routes_panel(self) -> Panel:
        """Create known routes panel."""
        network = self.app.api.network

        table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE, expand=True)

        table.add_column("Destination", style="white")
        table.add_column("Hops", justify="center")
        table.add_column("Avg SNR", justify="right")
        table.add_column("Via", style="dim")

        routes = list(network.routes.values())[:15]

        for route in routes:
            dest_name = route.destination_id[-8:]
            dest_node = network.nodes.get(route.destination_id)
            if dest_node:
                dest_name = dest_node.display_name[:15]

            hop_count = route.hop_count
            hop_style = "green" if hop_count <= 1 else "yellow" if hop_count <= 3 else "orange1"

            avg_snr = route.avg_snr

            via = ""
            if route.hops and hasattr(route.hops[0], "node_id"):
                first_hop = route.hops[0].node_id[-6:]
                via = f"via {first_hop}"
                if len(route.hops) > 1:
                    via += f" (+{len(route.hops)-1})"

            table.add_row(dest_name, f"[{hop_style}]{hop_count}[/{hop_style}]", format_snr(avg_snr, styled=True), via)

        if not routes:
            table.add_row("[dim]No routes discovered[/dim]", "", "", "")

        return Panel(table, title="[bold]Known Routes[/bold]", border_style="magenta")

    def _create_channels_panel(self) -> Panel:
        """Create channels overview panel."""
        network = self.app.api.network

        table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE, expand=True)

        table.add_column("Ch", justify="center", width=3)
        table.add_column("Name", style="white")
        table.add_column("Role", style="blue")
        table.add_column("Encrypted", justify="center")
        table.add_column("Messages", justify="right")
        table.add_column("Last Activity", style="dim")
        table.add_column("Uplink", justify="center")
        table.add_column("Downlink", justify="center")

        for idx, channel in sorted(network.channels.items()):
            if not channel.role or channel.role.value == "DISABLED":
                continue

            role_style = "green" if channel.role.value == "PRIMARY" else "blue"
            encrypted = "[green]Yes[/green]" if channel.is_encrypted else "[yellow]No[/yellow]"

            last_activity = "-"
            if channel.last_activity:
                delta = (datetime.now(timezone.utc) - channel.last_activity).total_seconds()
                last_activity = format_time_ago(delta)

            uplink = "[green]Y[/green]" if channel.uplink_enabled else "[dim]N[/dim]"
            downlink = "[green]Y[/green]" if channel.downlink_enabled else "[dim]N[/dim]"

            table.add_row(
                str(idx),
                channel.display_name,
                f"[{role_style}]{channel.role.value if channel.role else 'UNKNOWN'}[/{role_style}]",
                encrypted,
                str(channel.message_count),
                last_activity,
                uplink,
                downlink,
            )

        # If no hardware channels shown, display MQTT subscription info
        has_rows = any(
            ch.role and ch.role.value != "DISABLED"
            for ch in network.channels.values()
        )
        if not has_rows and hasattr(self.app, "config"):
            conn = self.app.api.connection_info
            if conn.interface_type == "mqtt":
                mqtt_cfg = self.app.config.mqtt
                ch_str = mqtt_cfg.channels if mqtt_cfg.channels else str(mqtt_cfg.channel)
                topic = mqtt_cfg.topic_root or "msh/US"
                for i, ch_name in enumerate(ch_str.split(",")):
                    ch_name = ch_name.strip()
                    # Count messages observed on this channel index
                    msg_count = sum(1 for m in network.messages if str(m.channel) == ch_name)
                    table.add_row(
                        ch_name,
                        f"{topic}/{ch_name}",
                        "[cyan]MQTT[/cyan]",
                        "[dim]-[/dim]",
                        str(msg_count),
                        "-",
                        "[green]Y[/green]",
                        "[green]Y[/green]",
                    )

        return Panel(table, title="[bold]Channels[/bold]", border_style="yellow")


class DevicesScreen(Screen):
    """Device/interface management screen."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self._selected_index = 0

    def _get_iface_status(self, index: int, iface) -> str:
        """Get status string for an interface."""
        if not iface.enabled:
            return "[dim]Disabled[/dim]"
        # The primary interface (index 0) is the active connection
        if index == 0 and self.app.api.is_connected:
            return "[green]Connected[/green]"
        if index == 0:
            return "[red]Disconnected[/red]"
        return "[yellow]Standby[/yellow]"

    def _get_iface_target(self, iface) -> str:
        """Get display target for an interface."""
        if iface.type == "serial":
            return iface.port or "auto-detect"
        elif iface.type == "tcp":
            return iface.hostname or "-"
        elif iface.type == "http":
            return iface.http_url or "-"
        elif iface.type == "ble":
            return iface.mac or "scan"
        elif iface.type == "mqtt":
            return getattr(self.app.config, "mqtt", None) and self.app.config.mqtt.broker or "broker"
        return "-"

    def render(self) -> Panel:
        layout = Table.grid(padding=(1, 0))

        # Configured interfaces table
        iface_table = Table(title="Configured Devices", box=box.ROUNDED, expand=True)
        iface_table.add_column("#", width=3, justify="center")
        iface_table.add_column("Type", width=8)
        iface_table.add_column("Target", width=25)
        iface_table.add_column("Hardware", width=15)
        iface_table.add_column("Label", width=15)
        iface_table.add_column("Status", width=14)
        iface_table.add_column("Active", width=8, justify="center")

        interfaces = self.app.config.interfaces
        # Clamp selected index
        if interfaces:
            self._selected_index = max(0, min(self._selected_index, len(interfaces) - 1))

        for i, iface in enumerate(interfaces):
            target = self._get_iface_target(iface)
            hw = iface.hardware_model or "-"
            label = iface.label or "-"
            status = self._get_iface_status(i, iface)
            active = "[bold green]\u2713[/bold green]" if i == 0 else "[dim]-[/dim]"
            style = "bold cyan" if i == self._selected_index else ""
            marker = "\u25b6 " if i == self._selected_index else "  "
            iface_table.add_row(
                f"{marker}{i + 1}",
                iface.type.upper(),
                target,
                hw,
                label,
                status,
                active,
                style=style,
            )

        if not interfaces:
            iface_table.add_row("-", "-", "No devices configured", "-", "-", "-", "-")

        layout.add_row(iface_table)

        # Discovered mesh nodes table
        nodes = list(self.app.api.network.online_nodes)[:15]
        if nodes:
            nodes_table = Table(title="Discovered Mesh Nodes", box=box.SIMPLE, expand=True)
            nodes_table.add_column("Name", width=18)
            nodes_table.add_column("ID", width=12)
            nodes_table.add_column("Hardware", width=15)
            nodes_table.add_column("Role", width=14)
            nodes_table.add_column("Battery", width=10)
            nodes_table.add_column("Last Heard", width=12)

            for node in nodes:
                name = node.long_name or node.short_name or "Unknown"
                node_id = node.node_id[:12] if node.node_id else "-"
                hw = node.hardware_model or "-"
                role = node.role.value if node.role else "-"
                batt = format_battery(node.telemetry.battery_level) if node.telemetry else "-"

                last_heard = "-"
                if node.last_heard:
                    delta = (datetime.now(timezone.utc) - node.last_heard).total_seconds()
                    last_heard = format_time_ago(delta)

                nodes_table.add_row(name, node_id, hw, role, batt, last_heard)

            layout.add_row(nodes_table)

        footer = (
            "[dim]a[/dim]=Add  [dim]d[/dim]=Remove  [dim]e[/dim]=Enable/Disable  "
            "[dim]t[/dim]=Test  [dim]r[/dim]=Set bot radio  [dim]j/k[/dim]=Navigate"
        )
        return Panel(
            layout,
            title="[bold cyan]Devices[/bold cyan]",
            subtitle=footer,
            border_style="cyan",
        )

    def handle_input(self, key: str) -> bool:
        interfaces = self.app.config.interfaces
        if key == "a":
            self.app._add_device_prompt()
            return True
        elif key == "d" and interfaces:
            self.app._remove_device_prompt(self._selected_index)
            return True
        elif key == "e" and interfaces:
            iface = interfaces[self._selected_index]
            iface.enabled = not iface.enabled
            return True
        elif key == "t" and interfaces:
            self.app._test_device_connection(self._selected_index)
            return True
        elif key == "r" and interfaces:
            self.app._set_bot_radio(self._selected_index)
            return True
        elif key == "j" and interfaces:
            self._selected_index = min(self._selected_index + 1, len(interfaces) - 1)
            return True
        elif key == "k":
            self._selected_index = max(self._selected_index - 1, 0)
            return True
        return False


class ConfigScreen(Screen):
    """Config editor for meshing-around config.ini — view and edit all settings."""

    # Preferred section display order
    _SECTION_ORDER = [
        "general", "location", "interface", "interface2", "bbs", "sentry",
        "emergencyHandler", "scheduler", "games", "radioMon", "fileMon",
        "smtp", "messagingSettings", "repeater", "checklist", "inventory",
        "qrz", "dataPersistence", "weatherAlert", "femaAlert", "deAlert",
    ]

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self._parser = None  # type: ignore
        self._config_path = None  # type: Optional[Path]
        self._items = []  # flat list of (section, key, value) for scrolling
        self._cursor = 0
        self._scroll_top = 0  # stable scroll position
        self._dirty = False  # config has unsaved changes
        self._error = ""
        self._loaded = False  # lazy load on first render

    def _get_search_paths(self) -> "list[Path]":
        """Get deduplicated upstream config search paths.

        Delegates to Config._get_upstream_config_paths() for consistency,
        then adds ConfigScreen-specific paths.
        """
        paths: list[Path] = []
        seen: set[str] = set()

        # Primary: use Config's canonical search paths
        if hasattr(self.app, "config"):
            for p in self.app.config._get_upstream_config_paths():
                key = str(p)
                if key not in seen:
                    paths.append(p)
                    seen.add(key)

        # Additional path (underscore variant)
        for p in [Path("/opt/meshing_around/config.ini")]:
            key = str(p)
            if key not in seen:
                paths.append(p)
                seen.add(key)

        return paths

    def _find_config(self) -> Optional[Path]:
        """Find upstream config.ini, falling back to config.template."""
        # Try Config's canonical search first
        if hasattr(self.app, "config") and hasattr(self.app.config, "find_upstream_config"):
            try:
                found = self.app.config.find_upstream_config()
                if found:
                    return found
            except (OSError, ValueError):
                pass

        # Comprehensive search for config.ini
        for p in self._get_search_paths():
            try:
                if p.exists():
                    return p
            except (OSError, PermissionError):
                continue

        # Fallback: search for config.template
        for p in self._get_search_paths():
            template = p.with_name("config.template")
            try:
                if template.exists():
                    return template
            except (OSError, PermissionError):
                continue

        return None

    @property
    def _is_template(self) -> bool:
        """True if currently viewing a config.template (read-only)."""
        return bool(self._config_path and self._config_path.name == "config.template")

    def _load(self) -> None:
        """Load the upstream config.ini (or config.template) into memory."""
        import configparser as _cp
        self._parser = _cp.ConfigParser()
        self._error = ""
        self._loaded = True
        self._config_path = self._find_config()
        if self._config_path:
            try:
                self._parser.read(str(self._config_path))
            except _cp.Error as e:
                self._error = f"Parse error: {e}"
        else:
            # Nothing found — show helpful error
            searched = ", ".join(str(p) for p in self._get_search_paths())
            self._error = (
                f"meshing-around config not found.\n"
                f"Searched: {searched}\n\n"
                f"If meshing-around is installed elsewhere, create a symlink:\n"
                f"  ln -s /path/to/meshing-around/config.ini /opt/meshing-around/config.ini"
            )
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        """Build flat list of (section, key, value) for display/scroll."""
        if not self._parser:
            self._items = []
            return
        items = []
        # Ordered sections first, then any remaining
        seen = set()
        ordered = [s for s in self._SECTION_ORDER if self._parser.has_section(s)]
        remaining = [s for s in self._parser.sections() if s not in self._SECTION_ORDER]
        for section in ordered + remaining:
            seen.add(section)
            items.append((section, None, None))  # section header
            for key, value in self._parser.items(section):
                if key == "__name__":
                    continue
                items.append((section, key, value))
        self._items = items

    def render(self) -> Panel:
        if not self._loaded:
            self._load()
        if self._error:
            return Panel(
                Text(self._error, style="yellow"),
                title="[bold]Config Editor[/bold]",
                border_style="yellow",
            )

        table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE, expand=True)
        table.add_column("Section", style="cyan", width=20)
        table.add_column("Key", style="white", width=28)
        table.add_column("Value", style="green")

        # Stable scroll — only moves when cursor exits visible range
        window = 28
        if self._cursor < self._scroll_top:
            self._scroll_top = self._cursor
        elif self._cursor >= self._scroll_top + window:
            self._scroll_top = self._cursor - window + 1
        self._scroll_top = max(0, min(self._scroll_top, max(0, len(self._items) - window)))
        start = self._scroll_top
        end = min(len(self._items), start + window)

        for i in range(start, end):
            section, key, value = self._items[i]
            is_selected = i == self._cursor

            if key is None:
                # Section header
                sec_style = "bold cyan on dark_blue" if is_selected else "bold cyan"
                table.add_row(f"[{sec_style}][{section}][/{sec_style}]", "", "")
            else:
                # Key-value pair
                row_style = "bold white on blue" if is_selected else ""
                val_display = value if value else "[dim](empty)[/dim]"
                # Highlight booleans
                if value and value.lower() in ("true", "false"):
                    val_color = "green" if value.lower() == "true" else "red"
                    val_display = f"[{val_color}]{value}[/{val_color}]"
                # Truncate long values
                if value and len(value) > 50:
                    val_display = value[:47] + "..."

                if is_selected:
                    table.add_row(
                        f"[dim]{section}[/dim]",
                        f"[bold white on blue]{key}[/bold white on blue]",
                        f"[bold on blue]{val_display}[/bold on blue]",
                    )
                else:
                    table.add_row(f"[dim]{section}[/dim]", key, val_display)

        save_indicator = " [yellow]*UNSAVED*[/yellow]" if self._dirty else ""
        if self._is_template:
            subtitle = f"[dim]\\[j/k] scroll  \\[Enter] edit  \\[t] toggle  \\[w] save  \\[C] create .ini  \\[R] reload  \\[q] back[/dim]{save_indicator}"
            title_suffix = " [yellow](template)[/yellow]"
        else:
            subtitle = f"[dim]\\[j/k] scroll  \\[Enter] edit  \\[t] toggle  \\[w] save  \\[R] reload  \\[q] back[/dim]{save_indicator}"
            title_suffix = ""

        return Panel(
            table,
            title=f"[bold]Config Editor[/bold] [dim]({self._config_path})[/dim]{title_suffix}",
            subtitle=subtitle,
            border_style="yellow",
        )

    def handle_input(self, key: str) -> bool:
        if key == "j":
            self._cursor = min(self._cursor + 1, len(self._items) - 1)
            return True
        elif key == "k":
            self._cursor = max(self._cursor - 1, 0)
            return True
        elif key == "t":
            # Toggle boolean values
            if self._cursor < len(self._items):
                section, k, v = self._items[self._cursor]
                if k and v and v.lower() in ("true", "false"):
                    new_val = "False" if v.lower() == "true" else "True"
                    self._parser.set(section, k, new_val)
                    self._items[self._cursor] = (section, k, new_val)
                    self._dirty = True
            return True
        elif key == "\n" or key == "\r":
            # Edit value
            if self._cursor < len(self._items):
                section, k, v = self._items[self._cursor]
                if k is not None:
                    self._edit_value(section, k, v or "")
            return True
        elif key == "w":
            self._save()
            return True
        elif key == "C":
            if self._is_template and self._config_path:
                self._create_from_template()
            return True
        elif key == "R":
            self._load()
            self._dirty = False
            return True
        return False

    def _create_from_template(self) -> None:
        """Create config.ini from the current config.template."""
        import shutil as _shutil
        if not self._config_path:
            return
        target = self._config_path.with_name("config.ini")
        if target.exists():
            self._error = f"config.ini already exists at {target}"
            return
        try:
            _shutil.copy2(str(self._config_path), str(target))
            target.chmod(0o600)
            self._load()  # reload — will now find the new config.ini
        except OSError as e:
            self._error = f"Failed to create config.ini: {e}"

    def _edit_value(self, section: str, key: str, current: str) -> None:
        """Edit a config value using prompt mode."""
        with self.app._prompt_mode():
            self.console.clear()
            self.console.print(f"[cyan][{section}] {key}[/cyan]")
            self.console.print(f"[dim]Current: {current}[/dim]\n")
            try:
                new_val = Prompt.ask("New value", default=current)
                if new_val != current:
                    self._parser.set(section, key, new_val)
                    self._rebuild_items()
                    self._dirty = True
                    self.console.print("[green]Value updated (press \\[w] to save)[/green]")
                else:
                    self.console.print("[dim]No change[/dim]")
                time.sleep(0.5)
            except KeyboardInterrupt:
                pass

    def _save(self) -> None:
        """Save config back to file with backup."""
        import shutil as _shutil
        if not self._dirty or not self._config_path:
            return
        try:
            # Backup
            if self._config_path.exists():
                bak = self._config_path.with_suffix(".ini.bak")
                _shutil.copy2(str(self._config_path), str(bak))
            with open(self._config_path, "w") as f:
                self._parser.write(f)
            self._config_path.chmod(0o600)
            self._dirty = False
        except OSError as e:
            self._error = f"Save failed: {e}"


class MapsScreen(Screen):
    """meshforge-maps integration — shows node health, topology, alerts, analytics."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self._client = None
        self._data = {}  # cached API responses
        self._last_fetch = 0.0
        self._status_msg = ""

    def _get_client(self):
        """Lazy-init maps client from config."""
        if self._client is None and hasattr(self.app, "config"):
            from meshing_around_clients.core.maps_client import MapsClient
            self._client = MapsClient(self.app.config.maps.base_url)
        return self._client

    def _refresh(self, force: bool = False) -> None:
        """Fetch data from maps API (throttled to 10s)."""
        now = time.monotonic()
        if not force and now - self._last_fetch < 10:
            return
        client = self._get_client()
        if not client:
            self._status_msg = "Maps not configured"
            return
        status = client.get_status()
        if not status:
            self._status_msg = f"Maps server not found at {self.app.config.maps.base_url}"
            self._data = {}
            return
        self._status_msg = ""
        self._data = {
            "status": status,
            "health": client.get_health_summary(),
            "alerts": client.get_active_alerts(),
            "analytics": client.get_analytics_summary(),
            "topology": client.get_topology(),
        }
        self._last_fetch = now

    def render(self) -> Panel:
        self._refresh()

        if self._status_msg:
            content = []
            content.append(Text(self._status_msg, style="yellow"))
            content.append(Text(""))
            content.append(Text("Configure in mesh_client.ini:", style="dim"))
            content.append(Text("  [maps]", style="cyan"))
            content.append(Text("  host = 127.0.0.1  (or remote IP)", style="dim"))
            content.append(Text("  port = 8808", style="dim"))
            content.append(Text(""))
            content.append(Text("Start maps: cd /opt/meshforge-maps && python -m src.main", style="dim"))
            return Panel(
                Group(*content),
                title="[bold]Maps[/bold]",
                subtitle="[dim]\\[r] retry  \\[q] back[/dim]",
                border_style="yellow",
            )

        # Build the 4-quadrant layout
        layout = Layout()
        layout.split_row(Layout(name="left"), Layout(name="right"))
        layout["left"].split_column(
            Layout(name="health", ratio=1),
            Layout(name="topology", ratio=1),
        )
        layout["right"].split_column(
            Layout(name="alerts", ratio=1),
            Layout(name="analytics", ratio=1),
        )

        # Status bar
        status = self._data.get("status", {})
        node_count = status.get("total_nodes", 0)
        sources = status.get("sources", {})
        active_sources = sum(1 for s in sources.values() if isinstance(s, dict) and s.get("enabled"))
        url = self.app.config.maps.base_url

        # Health quadrant
        health = self._data.get("health", {})
        dist = health.get("distribution", {})
        health_content = []
        health_content.append(Text("Node Health", style="bold green"))
        for level in ["excellent", "good", "fair", "poor", "critical"]:
            count = dist.get(level, 0)
            colors = {"excellent": "green", "good": "cyan", "fair": "yellow", "poor": "red", "critical": "bold red"}
            style = colors.get(level, "white")
            health_content.append(Text(f"  {level:10s} {count}", style=style))
        avg = health.get("average_score", 0)
        if avg:
            health_content.append(Text(f"  Average:   {avg:.0f}%", style="white bold"))
        layout["health"].update(Panel(Group(*health_content), border_style="green"))

        # Topology quadrant
        topo = self._data.get("topology", {})
        links = topo.get("links", [])[:8]
        topo_content = []
        topo_content.append(Text("Topology Links", style="bold magenta"))
        if links:
            for link in links:
                src = link.get("source", "?")[-6:]
                tgt = link.get("target", "?")[-6:]
                snr = link.get("snr", 0)
                snr_style = "green" if snr > 5 else "yellow" if snr > 0 else "red"
                line = Text()
                line.append(f"  {src} ", style="cyan")
                line.append("- ", style="dim")
                line.append(f"{tgt} ", style="cyan")
                line.append(f"SNR:{snr:.1f}", style=snr_style)
                topo_content.append(line)
        else:
            topo_content.append(Text("  No links", style="dim"))
        layout["topology"].update(Panel(Group(*topo_content), border_style="magenta"))

        # Alerts quadrant
        alerts = self._data.get("alerts", {})
        alert_list = alerts.get("alerts", []) if isinstance(alerts, dict) else []
        alert_content = []
        alert_content.append(Text("Active Alerts", style="bold red"))
        if alert_list:
            for a in alert_list[:6]:
                rule = a.get("rule_name", "?")
                node = a.get("node_id", "?")[-6:]
                sev = a.get("severity", "info")
                sev_style = {"critical": "bold red", "warning": "yellow", "info": "cyan"}.get(sev, "white")
                alert_content.append(Text(f"  {rule}: {node}", style=sev_style))
        else:
            alert_content.append(Text("  No active alerts", style="dim green"))
        layout["alerts"].update(Panel(Group(*alert_content), border_style="red"))

        # Analytics quadrant
        analytics = self._data.get("analytics", {})
        analytics_content = []
        analytics_content.append(Text("Analytics", style="bold blue"))
        growth = analytics.get("growth", {})
        if growth:
            total = growth.get("total_tracked", 0)
            new_24h = growth.get("new_last_24h", 0)
            analytics_content.append(Text(f"  Tracked:  {total} nodes", style="white"))
            analytics_content.append(Text(f"  New 24h:  {new_24h}", style="green" if new_24h else "dim"))
        activity = analytics.get("activity", {})
        if activity:
            active = activity.get("active_last_hour", 0)
            analytics_content.append(Text(f"  Active 1h: {active}", style="white"))
        if not growth and not activity:
            analytics_content.append(Text("  No data yet", style="dim"))
        layout["analytics"].update(Panel(Group(*analytics_content), border_style="blue"))

        status_line = f"CONNECTED | {node_count} nodes | {active_sources} sources | {url}"
        return Panel(
            layout,
            title=f"[bold]Maps[/bold] [dim]({url})[/dim]",
            subtitle=f"[dim][green]{status_line}[/green] | \\[o] open browser  \\[r] refresh  \\[q] back[/dim]",
            border_style="cyan",
        )

    def handle_input(self, key: str) -> bool:
        if key == "r":
            self._refresh(force=True)
            return True
        elif key == "o":
            import webbrowser
            try:
                webbrowser.open(self.app.config.maps.base_url)
            except (OSError, ValueError):
                pass
            return True
        return False


class HelpScreen(Screen):
    """Help screen showing keyboard shortcuts."""

    def render(self) -> Panel:
        help_text = """
# Keyboard Shortcuts

## Navigation
- **1** - Dashboard
- **2** - Nodes view
- **3** - Messages view
- **4** - Alerts view
- **5** - Topology view
- **6** - Devices view
- **7** - Log / Diagnostics
- **8** - Config Editor (meshing-around config.ini)
- **9** - Maps (meshforge-maps integration)
- **q** - Return to dashboard / Quit

## Actions
- **s** - Send message (commands auto-detected)
- **r** - Run command (sends to bot via mesh; local if disconnected)
- **c** - Connect/Disconnect
- **?** / **h** - This help

## Search (Nodes & Messages)
- **/** - Start search (type query, results filter live)
- **Enter** - Confirm search filter
- **Esc** - Clear search / cancel
- **Backspace** - Delete character

## Nodes View
- **j** - Next page
- **k** - Previous page
- **/** - Search by name, ID, or hardware
- Environment telemetry (temp/humidity) shown when available

## Message View
- **/** - Search by text, sender name, or sender ID
- **0-7** - Filter by channel
- **a** - Show all channels
- **e** - Export messages as JSON
- **E** - Export messages as CSV

## Alerts View
- **/** - Search by title or message text
- **l** - Filter: Low severity
- **m** - Filter: Medium severity
- **H** - Filter: High severity
- **C** - Filter: Critical severity
- **a** - Show all severities
- **x** - Acknowledge all alerts

## Topology View
- Mesh health score, node relationships, routes, and channels
- Link quality percentages and hop counts
- Neighbor relationships

## Devices View
- **a** - Add new device/interface
- **d** - Remove selected device
- **e** - Enable/Disable device
- **t** - Test connection to device
- **r** - Set as bot output radio
- **j/k** - Navigate device list

## Config Editor (screen 8)
- **j/k** - Scroll through settings
- **t** - Toggle boolean (True/False)
- **Enter** - Edit selected value
- **w** - Save changes (creates .bak backup)
- **R** - Reload from disk (discard unsaved changes)

## Maps (screen 9)
- **o** - Open web map in browser (http://host:port)
- **r** - Refresh data from meshforge-maps API
- Shows: node health, topology links, active alerts, analytics
"""
        return Panel(
            Markdown(help_text),
            title="[bold cyan]Help[/bold cyan]",
            subtitle="[dim]Press any key to return[/dim]",
            border_style="yellow",
        )


class LogScreen(Screen):
    """Diagnostic log viewer screen."""

    _LEVEL_STYLES = {
        "DEBUG": "dim",
        "INFO": "cyan",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold red",
    }

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self._scroll_offset = 0

    def render(self) -> Panel:
        handler: Optional[TUILogHandler] = getattr(self.app, "_log_handler", None)
        if handler is None or not handler.records:
            return Panel(
                "[dim]No log entries yet.[/dim]",
                title="[bold cyan]Log / Diagnostics[/bold cyan]",
                subtitle="[dim]j/k scroll · x clear · q back[/dim]",
                border_style="green",
            )

        records = list(handler.records)
        total = len(records)

        # Show most recent entries, scrollable with j/k
        visible_lines = 30
        end = max(0, total - self._scroll_offset)
        start = max(0, end - visible_lines)
        page = records[start:end]

        table = Table(box=box.SIMPLE, expand=True, show_header=True, padding=(0, 1))
        table.add_column("Time", style="dim", width=8, no_wrap=True)
        table.add_column("Level", width=8, no_wrap=True)
        table.add_column("Source", style="dim", width=20, no_wrap=True)
        table.add_column("Message", ratio=1)

        for rec in page:
            ts = datetime.fromtimestamp(rec.created).strftime("%H:%M:%S")
            style = self._LEVEL_STYLES.get(rec.levelname, "")
            level_text = f"[{style}]{rec.levelname}[/{style}]" if style else rec.levelname
            msg = rec.getMessage()
            if len(msg) > 120:
                msg = msg[:117] + "..."
            table.add_row(ts, level_text, rec.name[:20], msg)

        position = f" ({total} entries, viewing {start + 1}-{end})" if total > visible_lines else f" ({total} entries)"

        return Panel(
            table,
            title=f"[bold cyan]Log / Diagnostics{position}[/bold cyan]",
            subtitle="[dim]j/k scroll · x clear · q back[/dim]",
            border_style="green",
        )

    def handle_input(self, key: str) -> bool:
        handler: Optional[TUILogHandler] = getattr(self.app, "_log_handler", None)
        if key == "j":
            self._scroll_offset = max(0, self._scroll_offset - 5)
            return True
        elif key == "k":
            if handler:
                self._scroll_offset = min(len(handler.records), self._scroll_offset + 5)
            return True
        elif key == "x":
            if handler:
                handler.records.clear()
                self._scroll_offset = 0
            return True
        return False


class MeshingAroundTUI:
    """
    Main TUI application for Meshing-Around.
    Provides an interactive terminal interface for mesh network management.
    """

    def __init__(self, config: Optional[Config] = None, demo_mode: bool = False, api=None):
        self.console = Console()
        self.config = config or Config()
        self.demo_mode = demo_mode

        # Initialize API
        if api is not None:
            self.api = api
        elif demo_mode:
            self.api = MockMeshtasticAPI(self.config)
        else:
            self.api = MeshtasticAPI(self.config)

        # In-memory log handler for the TUI log screen
        self._log_handler = TUILogHandler(maxlen=500)
        self._log_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(self._log_handler)

        # Screens
        self.screens = {
            "dashboard": DashboardScreen(self),
            "nodes": NodesScreen(self),
            "messages": MessagesScreen(self),
            "alerts": AlertsScreen(self),
            "topology": TopologyScreen(self),
            "devices": DevicesScreen(self),
            "log": LogScreen(self),
            "config": ConfigScreen(self),
            "maps": MapsScreen(self),
            "help": HelpScreen(self),
        }
        self.current_screen = "dashboard"

        # State
        self._running = False
        self._interactive = False  # True when run_interactive() has input handling
        self._dirty = True  # Render flag — set on data changes or user input
        self._last_refresh = datetime.now()
        self._unread_messages = 0  # Incoming messages while not on messages screen
        self._unread_lock = threading.Lock()

        # Alert flash banner — shows briefly when a new alert fires
        self._alert_flash_text: str = ""
        self._alert_flash_time: float = 0.0
        self._alert_flash_lock = threading.Lock()
        _ALERT_FLASH_DURATION = 10  # seconds

        # Command activity log (last N commands seen)
        self._recent_commands: list = []
        self._command_lock = threading.Lock()

        # Space weather (RF propagation) — cached, fetched in background
        self._space_weather: Optional[Dict[str, Any]] = None
        self._space_weather_lock = threading.Lock()
        self._space_weather_fetching = False

        # Live display and terminal state (set by run_interactive)
        self._live: Optional[Any] = None
        self._old_terminal_settings: Optional[Any] = None

        # Render debouncing — minimum interval between re-renders (seconds)
        self._last_render_time: float = 0.0
        self._min_render_interval: float = 0.25

        # Register API callbacks to mark display dirty on data changes
        self._register_dirty_callbacks()

    def _mark_dirty(self, *args, **kwargs) -> None:
        """Callback to mark the display as needing a re-render.

        Debounces rapid callbacks (e.g. telemetry storms) by only setting
        the dirty flag if enough time has passed since the last render.
        """
        now = time.monotonic()
        if now - self._last_render_time >= self._min_render_interval:
            self._dirty = True

    def _register_dirty_callbacks(self) -> None:
        """Register API callbacks that trigger display refresh on data changes."""
        for event in ("on_message", "on_node_update", "on_alert", "on_connect", "on_disconnect", "on_telemetry", "on_command"):
            self.api.register_callback(event, self._mark_dirty)
        # Track unread incoming messages when not viewing messages screen
        self.api.register_callback("on_message", self._on_message_received)
        # Alert flash banner
        self.api.register_callback("on_alert", self._on_alert_received)
        # Command activity tracking
        self.api.register_callback("on_command", self._on_command_received)

    def _on_message_received(self, *args, **kwargs) -> None:
        """Increment unread counter for incoming messages when not on messages screen."""
        if self.current_screen != "messages":
            with self._unread_lock:
                self._unread_messages += 1

    def _on_alert_received(self, alert, *args, **kwargs) -> None:
        """Set the alert flash banner when a new alert fires."""
        title = getattr(alert, "title", "Alert")
        message = getattr(alert, "message", "")
        severity = getattr(alert, "severity", 1)
        flash = f"sev={severity}: {title}"
        if message:
            flash += f" -- {message[:60]}"
        with self._alert_flash_lock:
            self._alert_flash_text = flash
            self._alert_flash_time = time.monotonic()

    def _on_command_received(self, message, command_text, *args, **kwargs) -> None:
        """Track command activity for the Dashboard."""
        sender = getattr(message, "sender_name", "?") or "?"
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        entry = f"{ts} {command_text} from {sender}"
        with self._command_lock:
            self._recent_commands.append(entry)
            # Keep last 5 commands
            if len(self._recent_commands) > 5:
                self._recent_commands = self._recent_commands[-5:]

    # ------------------------------------------------------------------
    # Space weather (RF propagation) — NOAA SWPC public API
    # ------------------------------------------------------------------

    def _start_space_weather_fetch(self) -> None:
        """Launch a background thread to fetch space weather data.

        Called once at startup and then every 5 minutes by the render loop.
        Uses daemon thread so it won't block app exit.
        """
        if not self.config.tui.space_weather:
            return
        if self._space_weather_fetching:
            return
        self._space_weather_fetching = True
        t = threading.Thread(target=self._fetch_space_weather, daemon=True)
        t.start()

    def _fetch_space_weather(self) -> None:
        """Fetch SFI and K-index from NOAA SWPC (runs in background thread)."""
        result: Dict[str, Any] = {}
        try:
            # Solar Flux Index (F10.7 cm)
            try:
                resp = urlopen(
                    "https://services.swpc.noaa.gov/json/f107_cm_flux.json",
                    timeout=5,
                )
                data = json.loads(resp.read().decode())
                if data:
                    # Most recent entry is last in the list
                    latest = data[-1]
                    flux = latest.get("flux")
                    if flux is not None:
                        result["sfi"] = int(float(flux))
            except (URLError, ValueError, KeyError, IndexError, OSError):
                pass

            # Planetary K-index
            try:
                resp = urlopen(
                    "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json",
                    timeout=5,
                )
                data = json.loads(resp.read().decode())
                if data and len(data) > 1:
                    # First row is header, most recent observed is second row
                    latest = data[1]
                    k_val = latest[1] if len(latest) > 1 else None
                    if k_val is not None:
                        result["k_index"] = int(float(k_val))
            except (URLError, ValueError, KeyError, IndexError, OSError):
                pass

            if result:
                result["fetched_at"] = time.monotonic()
                with self._space_weather_lock:
                    self._space_weather = result
        except Exception as e:
            logger.debug("Space weather fetch error: %s", e)
        finally:
            self._space_weather_fetching = False

    def _append_space_weather(self, title) -> None:
        """Append compact space weather info to header Text object."""
        with self._space_weather_lock:
            sw = self._space_weather
        if not sw:
            return

        # Re-fetch if stale (>5 minutes)
        fetched = sw.get("fetched_at", 0)
        if time.monotonic() - fetched > 300:
            self._start_space_weather_fetch()

        sfi = sw.get("sfi")
        if sfi is not None:
            title.append(f"  SFI:{sfi}", style="dim")

        k = sw.get("k_index")
        if k is not None:
            # Color-code: 0-3 quiet (green), 4 unsettled (yellow), 5+ storm (red)
            if k <= 3:
                style = "green"
            elif k == 4:
                style = "yellow"
            else:
                style = "red bold"
            title.append(f" K:{k}", style=style)

    def _get_header(self) -> Panel:
        """Create the application header with connection health."""
        title = Text()
        title.append("MESHING-AROUND ", style="bold cyan")
        title.append(f"v{VERSION}", style="dim")

        if self.demo_mode:
            title.append(" [DEMO MODE]", style="yellow")

        # Connection health indicator
        health = self.api.connection_health
        status = health.get("status", "unknown")

        status_display = {
            "healthy": ("bold green", "HEALTHY"),
            "slow": ("bold yellow", "SLOW"),
            "stale": ("bold yellow", "STALE"),
            "degraded": ("bold yellow", "DEGRADED"),
            "connected_no_traffic": ("dim yellow", "NO TRAFFIC"),
            "disconnected": ("bold red", "DISCONNECTED"),
        }
        style, label = status_display.get(status, ("dim", status.upper()))
        title.append(f" [{label}]", style=style)

        # Node count — quick-glance metric visible on every screen
        try:
            node_count = len(self.api.network.get_nodes_snapshot())
            if node_count > 0:
                title.append(f"  {node_count} nodes", style="dim")
        except Exception:
            pass

        # Show message rate if available (MQTT provides this)
        msg_rate = health.get("messages_per_minute")
        if msg_rate is not None and health.get("connected"):
            title.append(f"  {msg_rate:.1f} msg/min", style="dim")

        # Unread message counter
        with self._unread_lock:
            unread = self._unread_messages
        if unread > 0:
            title.append(f"  {unread} new", style="green bold")

        # Unread alert badge — visible on all screens
        try:
            unread_alerts = len(self.api.network.unread_alerts)
            if unread_alerts > 0:
                title.append(f"  [!] {unread_alerts} alert{'s' if unread_alerts != 1 else ''}", style="red bold")
        except Exception:
            pass

        # Show queue metrics when relevant (>50% full or drops occurred)
        q_size = health.get("queue_size")
        q_max = health.get("queue_maxsize")
        dropped = health.get("messages_dropped", 0)
        if q_size is not None and q_max and q_size > q_max * 0.5:
            title.append(f"  Q:{q_size}/{q_max}", style="yellow")
        if dropped:
            title.append(f"  ({dropped} dropped)", style="red")

        # Space weather / RF propagation (SFI + K-index from NOAA)
        self._append_space_weather(title)

        return Panel(Align.center(title), box=box.DOUBLE, border_style="cyan", padding=(0, 2))

    def _get_footer(self) -> Panel:
        """Create the application footer with active screen highlighted."""
        shortcuts = Text()

        if not self._interactive:
            # Display-only mode — only Ctrl+C works
            shortcuts.append("Display-only mode ", style="dim")
            shortcuts.append("[Ctrl+C]", style="red bold")
            shortcuts.append(" Exit", style="dim")
            return Panel(Align.center(shortcuts), box=box.SIMPLE, border_style="dim")

        # Map screen keys to names and their screen identifiers
        nav_items = [
            ("1", "Dashboard", "dashboard"),
            ("2", "Nodes", "nodes"),
            ("3", "Messages", "messages"),
            ("4", "Alerts", "alerts"),
            ("5", "Topology", "topology"),
            ("6", "Devices", "devices"),
            ("7", "Log", "log"),
            ("8", "Config", "config"),
            ("9", "Maps", "maps"),
        ]

        for key, label, screen_id in nav_items:
            is_active = self.current_screen == screen_id
            if is_active:
                shortcuts.append(f"[{key}]", style="white bold on cyan")
                shortcuts.append(f"{label} ", style="white bold")
            else:
                shortcuts.append(f"[{key}]", style="cyan bold")
                shortcuts.append(f"{label} ", style="dim")

        shortcuts.append("[s]", style="green bold")
        shortcuts.append("Send ", style="white")
        shortcuts.append("[r]", style="green bold")
        shortcuts.append("Run Cmd ", style="white")
        shortcuts.append("[?]", style="yellow bold")
        shortcuts.append("Help ", style="white")
        shortcuts.append("[q]", style="red bold")
        shortcuts.append("Quit", style="dim")

        return Panel(Align.center(shortcuts), box=box.SIMPLE, border_style="dim")

    def _get_alert_flash(self) -> Optional[Panel]:
        """Return an alert flash banner if one is active, else None."""
        with self._alert_flash_lock:
            text = self._alert_flash_text
            flash_time = self._alert_flash_time
        if not text:
            return None
        # Auto-expire after 10 seconds
        if time.monotonic() - flash_time > 10:
            with self._alert_flash_lock:
                self._alert_flash_text = ""
            return None
        flash = Text()
        flash.append(" ALERT ", style="bold white on red")
        flash.append(f" {text}", style="bold yellow")
        return Panel(Align.center(flash), box=box.HEAVY, border_style="red", padding=(0, 1))

    def _render(self) -> Layout:
        """Render the full application layout."""
        layout = Layout()

        # Check for active alert flash banner
        flash_panel = self._get_alert_flash()

        parts = [Layout(self._get_header(), name="header", size=3)]
        if flash_panel is not None:
            parts.append(Layout(flash_panel, name="flash", size=3))
        parts.append(Layout(name="body"))
        parts.append(Layout(self._get_footer(), name="footer", size=3))
        layout.split_column(*parts)

        # Render current screen with connection-safety guard
        screen = self.screens.get(self.current_screen)
        if screen:
            try:
                layout["body"].update(screen.render())
            except Exception as e:
                # Guard against stale/missing API data during reconnection
                logger.debug("Render error on %s: %s", self.current_screen, e)
                msg = (
                    "[red]DISCONNECTED - press 'c' to reconnect[/red]"
                    if not self.api.is_connected
                    else f"[yellow]Waiting for data... ({e})[/yellow]"
                )
                layout["body"].update(Panel(msg, border_style="yellow"))

        return layout

    def connect(self) -> bool:
        """Connect to the Meshtastic device with retry and progress display."""
        self.console.print("[cyan]Connecting to Meshtastic device...[/cyan]")

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console
        ) as progress:
            task = progress.add_task("Connecting...", total=None)

            def on_retry(attempt, delay, error_msg):
                progress.update(
                    task,
                    description=f"[yellow]Attempt {attempt} failed: {error_msg}. Retrying in {delay:.0f}s...[/yellow]",
                )

            if hasattr(self.api, "connect_with_retry"):
                success = self.api.connect_with_retry(max_retries=3, on_retry=on_retry)
            else:
                success = self.api.connect()

            if success:
                progress.update(task, description="[green]Connected![/green]")
            else:
                progress.update(task, description=f"[red]Failed: {self.api.connection_info.error_message}[/red]")

        return success

    def disconnect(self) -> None:
        """Disconnect from the device."""
        self.api.disconnect()

    def _connect_mqtt(self, broker: str, port: int, username: str, password: str,
                      topic: str, channel: str, use_tls: bool = False) -> bool:
        """Configure MQTT settings, create client, and connect.

        Raises ImportError if paho-mqtt is not installed.
        """
        self.config.mqtt.enabled = True
        self.config.mqtt.broker = broker
        self.config.mqtt.port = port
        self.config.mqtt.username = username
        self.config.mqtt.password = password
        self.config.mqtt.topic_root = topic
        self.config.mqtt.channel = channel
        self.config.mqtt.use_tls = use_tls

        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

        self.api = MQTTMeshtasticClient(self.config)
        self._register_dirty_callbacks()
        return self.connect()

    def _connection_fallback_menu(self) -> bool:
        """Show connection type selection menu after a connection failure.

        Returns True if a connection was established, False to exit.
        Uses a loop instead of recursion to prevent stack overflow on repeated failures.
        """
        while True:
            with self._prompt_mode():
                error_msg = ""
                if hasattr(self.api, "connection_info"):
                    error_msg = getattr(self.api.connection_info, "error_message", "")

                self.console.print(f"\n[red]Connection failed: {error_msg}[/red]\n" if error_msg else "")
                self.console.print("[bold cyan]Select a connection option:[/bold cyan]\n")
                self.console.print("  [white]1)[/white] MQTT - Public broker (mqtt.meshtastic.org)")
                self.console.print("  [white]2)[/white] MQTT - Custom broker")
                self.console.print("  [white]3)[/white] MQTT - Local broker (no auth)")
                self.console.print("  [white]4)[/white] TCP  - Remote Meshtastic device")
                self.console.print("  [white]5)[/white] Install Meshtastic library")
                self.console.print("  [white]6)[/white] Demo mode (simulated data)")
                self.console.print("  [white]7)[/white] Exit\n")

                choice = Prompt.ask("Choice", choices=["1", "2", "3", "4", "5", "6", "7"], default="6")

                if choice == "1":
                    # MQTT public broker — credentials come from config defaults
                    mqtt = self.config.mqtt
                    topic = Prompt.ask("Topic root", default=mqtt.topic_root or "msh/US")
                    channel = Prompt.ask("Channel", default=mqtt.channel or "LongFast")
                    try:
                        return self._connect_mqtt(
                            broker="mqtt.meshtastic.org", port=1883,
                            username=mqtt.username, password=mqtt.password,
                            topic=topic, channel=channel,
                        )
                    except ImportError:
                        self.console.print("[red]MQTT library (paho-mqtt) not installed[/red]")
                        continue

                elif choice == "2":
                    # MQTT custom broker — pre-fill from config
                    mqtt = self.config.mqtt
                    broker = Prompt.ask("Broker hostname", default=mqtt.broker or "localhost")
                    # Parse embedded port from hostname (e.g. "host:1884")
                    if ":" in broker:
                        _parts = broker.rsplit(":", 1)
                        try:
                            port = int(_parts[1])
                            broker = _parts[0]
                        except ValueError:
                            port = int(Prompt.ask("Broker port", default=str(mqtt.port or 1883)))
                    else:
                        port = int(Prompt.ask("Broker port", default=str(mqtt.port or 1883)))
                    username = Prompt.ask("Username", default=mqtt.username or "")
                    password = Prompt.ask("Password", default=mqtt.password or "")
                    topic = Prompt.ask("Topic root", default=mqtt.topic_root or "msh/US")
                    channel = Prompt.ask("Channel", default=mqtt.channel or "LongFast")
                    try:
                        return self._connect_mqtt(
                            broker=broker, port=port,
                            username=username, password=password,
                            topic=topic, channel=channel,
                        )
                    except ImportError:
                        self.console.print("[red]MQTT library (paho-mqtt) not installed[/red]")
                        continue

                elif choice == "3":
                    # MQTT local broker — no auth, no TLS
                    topic = Prompt.ask("Topic root", default="msh/local")
                    channel = Prompt.ask("Channel", default="meshforge")
                    try:
                        return self._connect_mqtt(
                            broker="localhost", port=1883,
                            username="", password="",
                            topic=topic, channel=channel, use_tls=False,
                        )
                    except ImportError:
                        self.console.print("[red]MQTT library (paho-mqtt) not installed[/red]")
                        continue

                elif choice == "4":
                    # TCP remote device
                    hostname = Prompt.ask("Device hostname/IP")
                    self.config.interface.type = "tcp"
                    self.config.interface.hostname = hostname
                    self.api = MeshtasticAPI(self.config)
                    self._register_dirty_callbacks()
                    return self.connect()

                elif choice == "5":
                    # Install Meshtastic library
                    return self._install_meshtastic_library()

                elif choice == "6":
                    # Demo mode
                    self.demo_mode = True
                    self.api = MockMeshtasticAPI(self.config)
                    self._register_dirty_callbacks()
                    self.api.connect()
                    return True

                else:
                    # Exit
                    return False

    def _install_meshtastic_library(self) -> bool:
        """Install the Meshtastic library and dependencies, then reconnect."""
        try:
            from mesh_client import OPTIONAL_DEPS, check_internet, install_dependencies
        except ImportError:
            self.console.print("[red]Cannot import installer (mesh_client.py not found)[/red]")
            time.sleep(2)
            return False

        # Pre-flight internet check
        self.console.print("[cyan]Checking internet connectivity...[/cyan]")
        if not check_internet():
            self.console.print("[red]No internet connection. Cannot install packages.[/red]")
            time.sleep(2)
            return False

        deps = OPTIONAL_DEPS.get("meshtastic", [])
        self.console.print(f"[cyan]Installing: {', '.join(deps)}[/cyan]")
        self.console.print("[dim]This may take a few minutes on ARM devices...[/dim]\n")

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console
        ) as progress:
            task = progress.add_task("Installing Meshtastic library...", total=None)
            success = install_dependencies(deps)
            if success:
                progress.update(task, description="[green]Installation complete![/green]")
            else:
                progress.update(task, description="[red]Installation failed[/red]")

        if not success:
            self.console.print("[red]Failed to install Meshtastic library. Check logs for details.[/red]")
            time.sleep(2)
            return False

        # Refresh the module-level MESHTASTIC_AVAILABLE flag now that pip install succeeded
        from meshing_around_clients.core.meshtastic_api import refresh_meshtastic_availability

        refresh_meshtastic_availability()

        self.console.print("[green]Meshtastic library installed successfully![/green]")
        time.sleep(1)

        # Create a fresh API and attempt connection
        self.api = MeshtasticAPI(self.config)
        self._register_dirty_callbacks()
        return self.connect()

    def _show_config_warnings(self) -> None:
        """Run config validation and display any warnings before connecting."""
        try:
            issues = self.config.validate()
            if issues:
                warning_lines = "\n".join(f"[yellow]! {issue}[/yellow]" for issue in issues)
                self.console.print(
                    Panel(
                        warning_lines,
                        title="[bold yellow]Configuration Warnings[/bold yellow]",
                        border_style="yellow",
                    )
                )
                time.sleep(2)
        except Exception as e:
            logger.debug("Config validation error: %s", e)

    def run(self) -> None:
        """Run TUI in display-only mode (no keyboard input).

        This is the fallback when run_interactive() fails (e.g. termios
        unavailable on Windows, or stdin is not a terminal). Shows a
        live-updating dashboard; exit with Ctrl+C.
        """
        self.console.clear()

        # Show startup banner
        self._show_startup()

        # Pre-flight config check
        self._show_config_warnings()

        # Connect if not in demo mode
        if not self.demo_mode:
            if not self.connect():
                if not self._connection_fallback_menu():
                    return
        else:
            self.api.connect()

        self._running = True
        self._start_space_weather_fetch()

        try:
            with Live(self._render(), console=self.console, refresh_per_second=1, screen=True) as live:
                while self._running:
                    if self._dirty:
                        self._dirty = False
                        self._last_render_time = time.monotonic()
                        try:
                            live.update(self._render())
                        except (AttributeError, KeyError, TypeError, IndexError) as e:
                            # Guard against transient data issues during updates
                            logger.debug("Display-mode render error: %s", e)
                    time.sleep(1.0)

        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            # Remove TUI log handler from root logger (matches run_interactive cleanup)
            if self._log_handler in logging.getLogger().handlers:
                logging.getLogger().removeHandler(self._log_handler)
            self.disconnect()
            self.console.clear()
            self.console.print("[cyan]Goodbye![/cyan]")

    def _show_startup(self) -> None:
        """Show startup banner."""
        banner = """
    __  ___          __    _                ___                           __
   /  |/  /__  _____/ /_  (_)___  ____ _   /   |  _________  __  ______  / /
  / /|_/ / _ \\/ ___/ __ \\/ / __ \\/ __ `/  / /| | / ___/ __ \\/ / / / __ \\/ /
 / /  / /  __(__  ) / / / / / / / /_/ /  / ___ |/ /  / /_/ / /_/ / / / / /_
/_/  /_/\\___/____/_/ /_/_/_/ /_/\\__, /  /_/  |_/_/   \\____/\\__,_/_/ /_/\\__/
                               /____/

        """
        self.console.print(banner, style="cyan")
        self.console.print(Align.center(f"TUI Client v{VERSION}"), style="dim")
        self.console.print()

    def run_interactive(self) -> None:
        """Run in interactive mode with keyboard input."""
        import select
        import sys
        import termios
        import tty

        self.console.clear()
        self._show_startup()

        # Pre-flight config check
        self._show_config_warnings()

        # Connect
        if not self.demo_mode:
            if not self.connect():
                if not self._connection_fallback_menu():
                    return
        else:
            self.api.connect()

        self._running = True
        self._interactive = True
        self._start_space_weather_fetch()

        # Guard: TUI requires a real terminal (fails under systemd/pipes)
        if not sys.stdin.isatty():
            self.console.print(
                "[red]Error: No terminal detected (running under systemd?).[/red]\n"
                "[yellow]Use --web mode for headless/service deployments.[/yellow]"
            )
            self._running = False
            self.disconnect()
            return

        # Save terminal settings (guard: tcgetattr can raise OSError)
        old_settings = None
        try:
            old_settings = termios.tcgetattr(sys.stdin)
            self._old_terminal_settings = old_settings
            # Set terminal to raw mode
            tty.setcbreak(sys.stdin.fileno())

            last_refresh = time.monotonic()

            # Use Rich Live for flicker-free in-place updates instead of
            # console.clear() + console.print() which causes visible blanking.
            with Live(self._render(), console=self.console, auto_refresh=False, screen=True) as live:
                self._live = live
                while self._running:
                    # Only re-render when data changed or user interacted (dirty flag)
                    if self._dirty:
                        self._dirty = False
                        last_refresh = time.monotonic()
                        self._last_render_time = last_refresh
                        try:
                            live.update(self._render())
                            live.refresh()
                        except (AttributeError, KeyError, TypeError, IndexError) as e:
                            logger.debug("Interactive render error: %s", e)

                    # Check for input (0.5s timeout doubles as minimum refresh interval)
                    if select.select([sys.stdin], [], [], 0.5)[0]:
                        key = sys.stdin.read(1)
                        self._dirty = True  # Any input triggers re-render
                        self._handle_key(key)
                    else:
                        # Periodic refresh for health/status updates (not every tick)
                        if time.monotonic() - last_refresh >= 5.0:
                            self._dirty = True

        except (KeyboardInterrupt, EOFError):
            pass  # Normal exit
        except OSError as e:
            self.console.print(f"[red]I/O Error: {e}[/red]")
        finally:
            self._live = None
            self._old_terminal_settings = None
            # Restore terminal settings if we saved them successfully
            if old_settings is not None:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                # Flush stale input buffered during cbreak mode so the
                # launcher menu doesn't consume leftover keystrokes.
                try:
                    termios.tcflush(sys.stdin, termios.TCIFLUSH)
                except (OSError, ValueError):
                    pass
            self._running = False
            # Remove TUI log handler from root logger
            if self._log_handler in logging.getLogger().handlers:
                logging.getLogger().removeHandler(self._log_handler)
            self.disconnect()
            self.console.clear()
            self.console.print("[cyan]Goodbye![/cyan]")

    # Screen navigation keys — maps key to screen name
    _SCREEN_KEYS = {
        "1": "dashboard",
        "2": "nodes",
        "3": "messages",
        "4": "alerts",
        "5": "topology",
        "6": "devices",
        "7": "log",
        "8": "config",
        "9": "maps",
        "?": "help",
        "h": "help",
    }

    def _handle_key(self, key: str) -> None:
        """Handle keyboard input."""
        # Screen-specific handling first
        screen = self.screens.get(self.current_screen)
        if screen and screen.handle_input(key):
            return

        # Screen navigation via lookup
        if key in self._SCREEN_KEYS:
            self.current_screen = self._SCREEN_KEYS[key]
            if key == "3":
                with self._unread_lock:
                    self._unread_messages = 0
        elif key == "q":
            if self.current_screen != "dashboard":
                self.current_screen = "dashboard"
            else:
                self._running = False
        elif key == "s":
            self._send_message_prompt()
        elif key == "r":
            self._run_command_prompt()
        elif key == "c":
            if self.api.is_connected:
                self.disconnect()
            else:
                with self._prompt_mode():
                    self.console.clear()
                    if not self.connect():
                        self._connection_fallback_menu()

    @contextmanager
    def _prompt_mode(self):
        """Temporarily suspend Live display and restore cooked terminal for prompts."""
        try:
            import termios
            import tty

            _has_termios = True
        except ImportError:
            _has_termios = False

        live = self._live
        saved = self._old_terminal_settings

        # Stop Live display (exits alternate screen buffer)
        if live is not None:
            try:
                live.stop()
            except Exception:
                logger.debug("Failed to stop Live display for prompt mode")

        # Restore cooked terminal mode so input()/Prompt.ask() works
        if _has_termios and saved is not None:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
            except (termios.error, OSError) as e:
                logger.debug("Failed to restore terminal settings: %s", e)

        try:
            yield
        finally:
            # Re-enter cbreak mode
            if _has_termios and saved is not None:
                try:
                    tty.setcbreak(sys.stdin.fileno())
                except (termios.error, OSError) as e:
                    logger.debug("Failed to re-enter cbreak mode: %s", e)

            # Restart Live display
            if live is not None:
                try:
                    live.start()
                except Exception as e:
                    logger.debug("Failed to restart Live display: %s", e)

            self._dirty = True

    def _run_command_prompt(self) -> None:
        """Smart command router: local, upstream venv, or send to bot via mesh."""
        from meshing_around_clients.core.meshtastic_api import (
            _BOT_ONLY_COMMANDS, _LOCAL_COMMANDS, _UPSTREAM_CMD_MAP,
        )

        default_ch = self.config.network_cfg.default_channel
        connected = self.api.is_connected
        with self._prompt_mode():
            self.console.clear()
            self.console.print(Panel("[bold cyan]Run Command[/bold cyan]", border_style="cyan"))
            if connected:
                self.console.print(
                    f"[bold green]Connected on ch{default_ch}[/bold green] — "
                    "data cmds run locally, bot cmds sent via mesh\n"
                )
            else:
                self.console.print(
                    f"[yellow]Not connected — data cmds run locally, "
                    "bot cmds unavailable[/yellow]\n"
                )
            self.console.print(MeshtasticAPI.get_command_list(self.config))
            self.console.print()

            try:
                cmd = Prompt.ask("Command").strip().lower()
                if not cmd:
                    return

                # Route 1: Local commands — always run locally
                # Route 2: Upstream venv commands — run locally via bot engine
                if cmd in _LOCAL_COMMANDS or cmd in _UPSTREAM_CMD_MAP:
                    self._run_command_local(cmd)
                    return

                # Route 3: Bot-only commands — send via mesh
                if cmd in _BOT_ONLY_COMMANDS:
                    if connected:
                        if self.api.send_message(cmd, "^all", default_ch):
                            self.console.print(
                                f"\n[green]Sent '{cmd}' to bot on ch{default_ch}[/green]"
                                f"\n[dim]Bot response will appear in Live Feed (screen 1)."
                                f"\nIf no response, bot may not be running or listening on ch{default_ch}."
                                f"\nPress Enter...[/dim]"
                            )
                            self._dirty = True
                            input()
                        else:
                            self.console.print("[red]Failed to send message[/red]")
                            time.sleep(1)
                    else:
                        self.console.print(
                            f"\n[yellow]'{cmd}' requires the running meshing-around bot.[/yellow]"
                            "\n[dim]Connect to mesh first, then this sends via mesh to the bot.[/dim]"
                        )
                        time.sleep(2)
                    return

                # Route 4: Try local execution first, then send via mesh
                response = self.api._get_command_response(cmd)
                if response and not response.startswith("__BOT_ONLY__"):
                    self._run_command_local(cmd)
                elif connected:
                    if self.api.send_message(cmd, "^all", default_ch):
                        self.console.print(
                            f"\n[green]Sent '{cmd}' on ch{default_ch}[/green]"
                            "\n[dim]Watch Live Feed for response. Press Enter...[/dim]"
                        )
                        self._dirty = True
                        input()
                    else:
                        self.console.print(f"[red]Unknown command: {cmd}[/red]")
                        time.sleep(1)
                else:
                    self.console.print(f"[red]Unknown command: {cmd}[/red]")
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    def _send_message_prompt(self) -> None:
        """Prompt user to send a message.

        Intercepts recognized commands and runs them locally with output
        on default_channel, or sends a regular message.
        """
        default_ch = str(self.config.network_cfg.default_channel)
        with self._prompt_mode():
            self.console.clear()
            self.console.print(Panel("[bold cyan]Send Message[/bold cyan]", border_style="cyan"))
            self.console.print("[dim]Type 'cmd' for commands, or a message to send[/dim]\n")

            try:
                text = Prompt.ask("Message")
                if not text:
                    return

                # Intercept recognized commands — run locally
                text_lower = text.strip().lower()
                if self.config.commands.enabled:
                    recognized = [c.lower() for c in self.config.commands.commands]
                    if text_lower in recognized:
                        self._run_command_local(text_lower)
                        return

                msg_len = len(text.encode("utf-8"))
                if msg_len > MAX_MESSAGE_BYTES:
                    self.console.print(
                        f"[red]Message too long: {msg_len}/{MAX_MESSAGE_BYTES} bytes. "
                        f"Please shorten by {msg_len - MAX_MESSAGE_BYTES} bytes.[/red]"
                    )
                    time.sleep(2)
                    return

                try:
                    channel = int(Prompt.ask("Channel", default=default_ch))
                except ValueError:
                    self.console.print("[red]Invalid channel number[/red]")
                    time.sleep(1)
                    return
                if channel < 0 or channel > 7:
                    self.console.print("[red]Channel must be 0-7[/red]")
                    time.sleep(1)
                    return
                dest = Prompt.ask("Destination (^all for broadcast)", default="^all")
                if dest != "^all":
                    try:
                        int(dest.lstrip("!"), 16) if dest.startswith("!") else int(dest)
                    except ValueError:
                        self.console.print(
                            "[red]Invalid destination: use ^all, a node number, or !hex_id[/red]"
                        )
                        time.sleep(1)
                        return

                if self.api.send_message(text, dest, channel):
                    self.console.print("[green]Message sent![/green]")
                else:
                    self.console.print("[red]Failed to send message[/red]")

                time.sleep(1)
            except KeyboardInterrupt:
                pass

    def _run_command_local(self, command: str) -> None:
        """Execute a command locally and show output on default_channel."""
        import uuid as _uuid

        response = self.api._get_command_response(command)
        if not response:
            self.console.print(f"[yellow]No response for: {command}[/yellow]")
            time.sleep(1)
            return
        # Bot-only commands can't run locally
        if response.startswith("__BOT_ONLY__"):
            self.console.print(f"[yellow]'{command}' requires the running bot (send via mesh)[/yellow]")
            time.sleep(1.5)
            return

        default_ch = self.config.network_cfg.default_channel
        self.console.print()
        self.console.print(Panel(response, title=f"[green]{command}[/green]", border_style="green"))

        # Add as a local message on default_channel
        msg = Message(
            id=str(_uuid.uuid4()),
            sender_id=getattr(self.api.network, "my_node_id", "") or "local",
            sender_name=f"{self.config.bot_name} (local)",
            channel=default_ch,
            text=f"[{command}] {response}",
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            is_incoming=False,
        )
        self.api.network.add_message(msg)
        self._dirty = True

        self.console.print(f"\n[dim]Output on ch{default_ch}. Press Enter...[/dim]")
        input()

    def _add_device_prompt(self) -> None:
        """Prompt user to add a new device/interface."""
        with self._prompt_mode():
            self.console.clear()
            self.console.print(Panel("[bold cyan]Add Device[/bold cyan]", border_style="cyan"))

            self.console.print("  1. Serial (USB radio)")
            self.console.print("  2. TCP (Remote device)")
            self.console.print("  3. MQTT (Broker)")
            self.console.print("  4. BLE (Bluetooth)")
            self.console.print("  5. Cancel")

            try:
                choice = Prompt.ask("Select type", choices=["1", "2", "3", "4", "5"], default="5")
            except KeyboardInterrupt:
                return

            if choice == "5":
                return

            type_map = {"1": "serial", "2": "tcp", "3": "mqtt", "4": "ble"}
            iface_type = type_map[choice]
            iface = InterfaceConfig(type=iface_type)

            try:
                if iface_type == "serial":
                    port = Prompt.ask("Serial port", default="auto-detect")
                    if port != "auto-detect":
                        iface.port = port
                elif iface_type == "tcp":
                    iface.hostname = Prompt.ask("Hostname/IP")
                    iface.label = Prompt.ask("Label (optional)", default="")
                elif iface_type == "mqtt":
                    self.console.print("[dim]MQTT uses broker settings from mesh_client.ini[/dim]")
                elif iface_type == "ble":
                    iface.mac = Prompt.ask("BLE MAC address", default="scan")

                # Hardware model (optional for all types)
                hw = Prompt.ask(
                    "Hardware model",
                    choices=["TBEAM", "TLORA", "TECHO", "TDECK", "HELTEC", "RAK4631", "STATION_G2", "skip"],
                    default="skip",
                )
                if hw != "skip":
                    iface.hardware_model = hw

                if self.config.add_interface(iface):
                    self.console.print(f"[green]Added {iface_type.upper()} device[/green]")
                else:
                    self.console.print("[red]Max 9 interfaces reached[/red]")

            except KeyboardInterrupt:
                return

            time.sleep(1)

    def _remove_device_prompt(self, index: int) -> None:
        """Remove a device/interface by index."""
        interfaces = self.config.interfaces
        if not interfaces or index >= len(interfaces):
            return

        with self._prompt_mode():
            iface = interfaces[index]
            self.console.clear()
            target = iface.port or iface.hostname or iface.mac or iface.type
            self.console.print(f"Remove device #{index + 1}: {iface.type.upper()} ({target})?")

            try:
                if Confirm.ask("Confirm removal", default=False):
                    if index == 0 and self.api.is_connected:
                        self.console.print("[yellow]Disconnecting active device first...[/yellow]")
                        self.disconnect()
                    self.config._interfaces.pop(index)
                    self.console.print("[green]Device removed[/green]")
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    def _test_device_connection(self, index: int) -> None:
        """Test connection to a device."""
        interfaces = self.config.interfaces
        if not interfaces or index >= len(interfaces):
            return

        with self._prompt_mode():
            iface = interfaces[index]
            self.console.clear()
            target = iface.port or iface.hostname or iface.mac or iface.type
            self.console.print(f"Testing connection to {iface.type.upper()} ({target})...")

            try:
                if iface.type == "tcp" and iface.hostname:
                    import socket

                    host, tcp_port = (
                        iface.hostname.rsplit(":", 1) if ":" in iface.hostname else (iface.hostname, "4403")
                    )
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    try:
                        sock.connect((host, int(tcp_port)))
                        sock.close()
                        self.console.print(f"[green]TCP connection to {host}:{tcp_port} successful![/green]")
                    except (ConnectionRefusedError, TimeoutError, OSError) as e:
                        self.console.print(f"[red]TCP connection failed: {e}[/red]")
                elif iface.type == "serial":
                    port = iface.port or "auto"
                    if port != "auto" and Path(port).exists():
                        self.console.print(f"[green]Serial port {port} exists[/green]")
                    elif port == "auto":
                        self.console.print("[yellow]Auto-detect requires meshtastic library[/yellow]")
                    else:
                        self.console.print(f"[red]Serial port {port} not found[/red]")
                elif iface.type == "mqtt":
                    import socket

                    broker = self.config.mqtt.broker if hasattr(self.config, "mqtt") else "mqtt.meshtastic.org"
                    port = self.config.mqtt.port if hasattr(self.config, "mqtt") else 1883
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    try:
                        sock.connect((broker, port))
                        sock.close()
                        self.console.print(f"[green]MQTT broker {broker}:{port} reachable![/green]")
                    except (ConnectionRefusedError, TimeoutError, OSError) as e:
                        self.console.print(f"[red]MQTT broker unreachable: {e}[/red]")
                else:
                    self.console.print(f"[yellow]Test not available for {iface.type} connections[/yellow]")
            except ImportError as e:
                self.console.print(f"[red]Missing dependency: {e}[/red]")

            try:
                Prompt.ask("Press Enter to continue", default="")
            except KeyboardInterrupt:
                pass

    def _set_bot_radio(self, index: int) -> None:
        """Set a device as the primary bot output radio."""
        interfaces = self.config.interfaces
        if not interfaces or index >= len(interfaces) or index == 0:
            if index == 0:
                self.console.clear()
                self.console.print("[dim]This device is already the active radio[/dim]")
                time.sleep(1)
                self._dirty = True
            return

        with self._prompt_mode():
            iface = interfaces[index]
            target = iface.port or iface.hostname or iface.mac or iface.type
            self.console.clear()
            self.console.print(f"Set {iface.type.upper()} ({target}) as active bot radio?")
            self.console.print("[dim]This will disconnect the current radio and switch to this one.[/dim]")

            try:
                if Confirm.ask("Confirm switch", default=False):
                    self._switch_to_interface(iface, index)
            except KeyboardInterrupt:
                pass

    def _switch_to_interface(self, iface, index: int) -> bool:
        """Switch the active API connection to a different interface."""
        self.console.print("[yellow]Switching interface...[/yellow]")

        # Disconnect current
        self.disconnect()

        # Swap selected interface to position 0 (primary)
        interfaces = self.config._interfaces
        interfaces[0], interfaces[index] = interfaces[index], interfaces[0]
        self.config.interface = interfaces[0]

        # Create new API for the interface type
        if interfaces[0].type == "mqtt":
            try:
                from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

                self.api = MQTTMeshtasticClient(self.config)
            except ImportError:
                self.console.print("[red]MQTT library (paho-mqtt) not installed[/red]")
                time.sleep(2)
                return False
        else:
            self.api = MeshtasticAPI(self.config)

        self._register_dirty_callbacks()

        if self.connect():
            self.console.print("[green]Switched successfully![/green]")
            time.sleep(1)
            return True
        else:
            self.console.print("[red]Connection failed[/red]")
            time.sleep(2)
            return False


def main():
    """Main entry point for the TUI application."""
    import argparse

    parser = argparse.ArgumentParser(description="Meshing-Around TUI Client")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode without hardware")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--serial", type=str, help="Serial port to connect to")
    parser.add_argument("--tcp", type=str, help="TCP hostname to connect to")
    args = parser.parse_args()

    # Load config
    config = Config(args.config) if args.config else Config()

    # Override connection settings
    if args.serial:
        config.interface.type = "serial"
        config.interface.port = args.serial
    elif args.tcp:
        config.interface.type = "tcp"
        config.interface.hostname = args.tcp

    if not RICH_AVAILABLE:
        print("Note: 'rich' library not found — running in plain-text mode.")
        print("Install Rich for the full TUI: pip install rich")
        print()
        tui = PlainTextTUI(config=config, demo_mode=args.demo)
        tui.run()
        return

    # Create and run TUI
    tui = MeshingAroundTUI(config=config, demo_mode=args.demo)

    try:
        # Try interactive mode with keyboard input
        tui.run_interactive()
    except (ImportError, OSError):
        # Fall back to basic mode
        tui.run()


if __name__ == "__main__":
    main()

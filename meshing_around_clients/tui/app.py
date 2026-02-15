#!/usr/bin/env python3
"""
Meshing-Around TUI Application
A rich terminal interface for monitoring and managing Meshtastic mesh networks.

Based on MeshForge foundation principles:
- Beautiful UI with Rich library
- Modular and extensible design
- Graceful fallbacks for missing dependencies
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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

from meshing_around_clients.core import Config, MeshtasticAPI, MessageHandler  # noqa: E402
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI  # noqa: E402
from meshing_around_clients.core.models import DATETIME_MIN_UTC  # noqa: E402

# Version
VERSION = "0.5.0-beta"


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
    """Main dashboard screen showing overview of mesh network."""

    def render(self) -> Panel:
        layout = Layout()

        # Create stats row
        stats = self._create_stats_panel()

        # Create node list
        nodes = self._create_nodes_panel()

        # Create messages panel
        messages = self._create_messages_panel()

        # Create alerts panel
        alerts = self._create_alerts_panel()

        # Combine into layout
        layout.split_column(Layout(stats, name="stats", size=5), Layout(name="main"))
        layout["main"].split_row(Layout(name="left"), Layout(name="right", ratio=2))
        layout["left"].split_column(Layout(nodes, name="nodes"), Layout(alerts, name="alerts"))
        layout["right"].update(messages)

        return Panel(
            layout,
            title="[bold cyan]Meshing-Around Dashboard[/bold cyan]",
            subtitle=f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
            border_style="cyan",
        )

    def _create_stats_panel(self) -> Panel:
        """Create the statistics overview panel with mesh health and congestion."""
        network = self.app.api.network
        conn = self.app.api.connection_info

        # Connection status
        if conn.connected:
            status = Text("CONNECTED", style="bold green")
        else:
            status = Text("DISCONNECTED", style="bold red")

        # Mesh health
        health = network.mesh_health
        health_status = health.get("status", "unknown")
        health_score = health.get("score", 0)
        health_colors = {
            "excellent": "green bold",
            "good": "green",
            "fair": "yellow",
            "poor": "orange1",
            "critical": "red bold",
            "unknown": "dim",
        }
        health_style = health_colors.get(health_status, "white")

        # Congestion indicator from avg channel utilization
        avg_util = health.get("avg_channel_utilization", 0)
        if avg_util >= 40.0:
            util_str = f"[red bold]{avg_util:.1f}% CRITICAL[/red bold]"
        elif avg_util >= 25.0:
            util_str = f"[yellow]{avg_util:.1f}% WARNING[/yellow]"
        elif avg_util > 0:
            util_str = f"[green]{avg_util:.1f}%[/green]"
        else:
            util_str = "[dim]-[/dim]"

        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Label", style="cyan")
        stats_table.add_column("Value", style="white bold")
        stats_table.add_column("Label2", style="cyan")
        stats_table.add_column("Value2", style="white bold")

        stats_table.add_row(
            "Status",
            status,
            "Health",
            Text(f"{health_status.upper()} ({health_score}%)", style=health_style),
        )
        stats_table.add_row(
            "Interface",
            f"{conn.interface_type} ({conn.device_path})",
            "Ch Util",
            Text.from_markup(util_str),
        )
        stats_table.add_row(
            "Nodes",
            f"{len(network.online_nodes)}/{len(network.nodes)}",
            "Avg SNR",
            f"{health.get('avg_snr', 0):.1f} dB",
        )
        stats_table.add_row(
            "Messages",
            str(network.total_messages),
            "Alerts",
            f"{len(network.unread_alerts)} unread",
        )

        return Panel(stats_table, title="[bold]Network Status[/bold]", border_style="blue")

    def _create_nodes_panel(self) -> Panel:
        """Create the nodes list panel."""
        nodes = sorted(
            self.app.api.network.nodes.values(), key=lambda n: n.last_heard or DATETIME_MIN_UTC, reverse=True
        )[:10]

        table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE, expand=True)
        table.add_column("Name", style="white", no_wrap=True)
        table.add_column("Last", style="dim", justify="right")
        table.add_column("Batt", justify="right")
        table.add_column("SNR", justify="right")

        for node in nodes:
            # Determine style based on status
            if node.is_favorite:
                name_style = "yellow bold"
            elif not node.is_online:
                name_style = "dim"
            else:
                name_style = "white"

            # Battery indicator
            if node.telemetry and node.telemetry.battery_level > 0:
                batt = node.telemetry.battery_level
                if batt > 50:
                    batt_str = f"[green]{batt}%[/green]"
                elif batt > 20:
                    batt_str = f"[yellow]{batt}%[/yellow]"
                else:
                    batt_str = f"[red]{batt}%[/red]"
            else:
                batt_str = "-"

            # SNR
            snr = node.telemetry.snr if node.telemetry else 0
            snr_str = f"{snr:.1f}" if snr else "-"

            table.add_row(
                f"[{name_style}]{node.display_name[:15]}[/{name_style}]", node.time_since_heard, batt_str, snr_str
            )

        if not nodes:
            table.add_row("[dim]No nodes yet[/dim]", "", "", "")

        return Panel(table, title="[bold]Nodes[/bold]", border_style="green")

    def _create_messages_panel(self) -> Panel:
        """Create the messages panel."""
        messages = list(self.app.api.network.messages)[-15:]

        content = []
        for msg in reversed(messages):
            time_str = msg.time_formatted
            sender = msg.sender_name or msg.sender_id[-6:]

            if msg.is_incoming:
                prefix = "[cyan]<<[/cyan]"
            else:
                prefix = "[green]>>[/green]"

            # Check for emergency keywords
            is_emergency = any(kw.lower() in msg.text.lower() for kw in self.app.config.alerts.emergency_keywords)

            if is_emergency:
                text_style = "bold red"
            else:
                text_style = "white"

            line = Text()
            line.append(f"{time_str} ", style="dim")
            line.append(f"{prefix} ")
            line.append(f"{sender}: ", style="cyan")
            line.append(msg.text[:60], style=text_style)
            if len(msg.text) > 60:
                line.append("...", style="dim")

            content.append(line)

        if not content:
            content.append(Text("No messages yet", style="dim"))

        return Panel(Group(*content), title="[bold]Messages[/bold]", border_style="magenta")

    def _create_alerts_panel(self) -> Panel:
        """Create the alerts panel."""
        alerts = list(self.app.api.network.alerts)[-5:]

        content = []
        for alert in reversed(alerts):
            style = {1: "blue", 2: "yellow", 3: "orange1", 4: "red bold"}.get(alert.severity, "white")

            icon = {1: "i", 2: "!", 3: "!!", 4: "!!!"}.get(alert.severity, "*")

            line = Text()
            line.append(f"[{icon}] ", style=style)
            line.append(alert.title[:30], style=style)

            content.append(line)

        if not content:
            content.append(Text("No alerts", style="dim green"))

        return Panel(Group(*content), title="[bold]Alerts[/bold]", border_style="red")


class NodesScreen(Screen):
    """Detailed nodes view screen with pagination and environment telemetry."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self.page = 0
        self.page_size = 20

    def render(self) -> Panel:
        nodes = sorted(
            self.app.api.network.nodes.values(), key=lambda n: n.last_heard or DATETIME_MIN_UTC, reverse=True
        )

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
            if node.telemetry and node.telemetry.battery_level > 0:
                batt = node.telemetry.battery_level
                if batt > 50:
                    batt_str = f"[green]{batt}%[/green]"
                elif batt > 20:
                    batt_str = f"[yellow]{batt}%[/yellow]"
                else:
                    batt_str = f"[red]{batt}%[/red]"
            else:
                batt_str = "-"

            # SNR
            snr = node.telemetry.snr if node.telemetry else 0
            snr_str = f"{snr:.1f}dB" if snr else "-"

            row = [
                f"[{status_style}]{idx}[/{status_style}]",
                node.node_id[-8:],
                node.display_name,
                node.hardware_model,
                node.role.value,
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

        page_info = f"Page {self.page + 1}/{total_pages} ({len(nodes)} nodes)"

        return Panel(
            table,
            title="[bold cyan]Nodes[/bold cyan]",
            subtitle=f"[dim]{page_info} | j/k: page down/up | q: return[/dim]",
            border_style="cyan",
        )

    def handle_input(self, key: str) -> bool:
        if key == "j":
            self.page += 1
            return True
        elif key == "k":
            self.page = max(0, self.page - 1)
            return True
        return False


class MessagesScreen(Screen):
    """Detailed messages view screen."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self.channel_filter: Optional[int] = None

    def render(self) -> Panel:
        all_messages = list(self.app.api.network.messages)
        if self.channel_filter is not None:
            all_messages = [m for m in all_messages if m.channel == self.channel_filter]

        messages = all_messages[-30:]  # Last 30 messages

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

            to_str = "broadcast" if msg.is_broadcast else msg.recipient_id[-6:]
            from_str = msg.sender_name or msg.sender_id[-6:]

            # Truncate message
            text = msg.text[:50]
            if len(msg.text) > 50:
                text += "..."

            snr_str = f"{msg.snr:.1f}" if msg.snr else "-"

            table.add_row(msg.time_formatted, str(msg.channel), direction, from_str, to_str, text, snr_str)

        filter_text = f"Channel {self.channel_filter}" if self.channel_filter is not None else "All channels"

        return Panel(
            table,
            title=f"[bold cyan]Messages[/bold cyan] - {filter_text}",
            subtitle="[dim]Press 0-7 to filter by channel, 'a' for all, 'q' to return[/dim]",
            border_style="magenta",
        )

    def handle_input(self, key: str) -> bool:
        if key.isdigit() and int(key) < 8:
            self.channel_filter = int(key)
            return True
        elif key == "a":
            self.channel_filter = None
            return True
        return False


class AlertsScreen(Screen):
    """Detailed alerts view screen with severity filtering and acknowledgment."""

    def __init__(self, app: "MeshingAroundTUI"):
        super().__init__(app)
        self.severity_filter: Optional[int] = None

    def render(self) -> Panel:
        all_alerts = list(self.app.api.network.alerts)
        if self.severity_filter is not None:
            all_alerts = [a for a in all_alerts if a.severity == self.severity_filter]

        alerts = all_alerts[-20:]

        table = Table(show_header=True, header_style="bold cyan", box=box.ROUNDED, expand=True)

        table.add_column("Time", style="dim", width=12)
        table.add_column("Sev", justify="center", width=4)
        table.add_column("Type", style="blue", width=12)
        table.add_column("Title", style="white")
        table.add_column("Message", style="dim")
        table.add_column("Ack", justify="center", width=4)

        for alert in reversed(alerts):
            severity_colors = {1: "blue", 2: "yellow", 3: "orange1", 4: "red"}
            sev_color = severity_colors.get(alert.severity, "white")
            sev_icons = {1: "i", 2: "!", 3: "!!", 4: "!!!"}
            sev_icon = sev_icons.get(alert.severity, "*")

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

        return Panel(
            table,
            title=f"[bold cyan]Alerts[/bold cyan] - {filter_text} ({unread} unread)",
            subtitle="[dim]l/m/H/C: low/med/high/crit | a: all | x: ack all | q: return[/dim]",
            border_style="red",
        )

    def handle_input(self, key: str) -> bool:
        if key == "l":
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
            # Acknowledge all unread alerts
            for alert in self.app.api.network.alerts:
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

        # Create mesh health panel
        health_panel = self._create_health_panel()

        # Create topology tree
        topology_panel = self._create_topology_panel()

        # Create routes panel
        routes_panel = self._create_routes_panel()

        # Create channels panel
        channels_panel = self._create_channels_panel()

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
        status_colors = {
            "excellent": "green bold",
            "good": "green",
            "fair": "yellow",
            "poor": "orange1",
            "critical": "red bold",
            "unknown": "dim",
        }
        status_style = status_colors.get(health["status"], "white")

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

        for node in network.nodes.values():
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
            if route.destination_id in network.nodes:
                dest_name = network.nodes[route.destination_id].display_name[:15]

            hop_count = route.hop_count
            hop_style = "green" if hop_count <= 1 else "yellow" if hop_count <= 3 else "orange1"

            avg_snr = route.avg_snr
            snr_style = "green" if avg_snr > 0 else "yellow" if avg_snr > -10 else "red"

            via = ""
            if route.hops:
                first_hop = route.hops[0].node_id[-6:]
                via = f"via {first_hop}"
                if len(route.hops) > 1:
                    via += f" (+{len(route.hops)-1})"

            table.add_row(
                dest_name, f"[{hop_style}]{hop_count}[/{hop_style}]", f"[{snr_style}]{avg_snr:.1f}[/{snr_style}]", via
            )

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
            if channel.role.value == "DISABLED":
                continue

            role_style = "green" if channel.role.value == "PRIMARY" else "blue"
            encrypted = "[green]Yes[/green]" if channel.is_encrypted else "[yellow]No[/yellow]"

            last_activity = "-"
            if channel.last_activity:
                delta = datetime.now(timezone.utc) - channel.last_activity
                if delta.total_seconds() < 60:
                    last_activity = f"{int(delta.total_seconds())}s ago"
                elif delta.total_seconds() < 3600:
                    last_activity = f"{int(delta.total_seconds() / 60)}m ago"
                else:
                    last_activity = f"{int(delta.total_seconds() / 3600)}h ago"

            uplink = "[green]Y[/green]" if channel.uplink_enabled else "[dim]N[/dim]"
            downlink = "[green]Y[/green]" if channel.downlink_enabled else "[dim]N[/dim]"

            table.add_row(
                str(idx),
                channel.display_name,
                f"[{role_style}]{channel.role.value}[/{role_style}]",
                encrypted,
                str(channel.message_count),
                last_activity,
                uplink,
                downlink,
            )

        return Panel(table, title="[bold]Channels[/bold]", border_style="yellow")


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
- **q** - Return to dashboard / Quit

## Actions
- **s** - Send message
- **r** - Refresh data
- **c** - Connect/Disconnect
- **?** / **h** - This help

## Nodes View
- **j** - Next page
- **k** - Previous page
- Environment telemetry (temp/humidity) shown when available

## Message View
- **0-7** - Filter by channel
- **a** - Show all channels

## Alerts View
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
"""
        return Panel(
            Markdown(help_text),
            title="[bold cyan]Help[/bold cyan]",
            subtitle="[dim]Press any key to return[/dim]",
            border_style="yellow",
        )


class MeshingAroundTUI:
    """
    Main TUI application for Meshing-Around.
    Provides an interactive terminal interface for mesh network management.
    """

    def __init__(self, config: Optional[Config] = None, demo_mode: bool = False):
        self.console = Console()
        self.config = config or Config()
        self.demo_mode = demo_mode

        # Initialize API
        if demo_mode:
            self.api = MockMeshtasticAPI(self.config)
        else:
            self.api = MeshtasticAPI(self.config)

        # Message handler
        self.message_handler = MessageHandler(self.config)

        # Screens
        self.screens = {
            "dashboard": DashboardScreen(self),
            "nodes": NodesScreen(self),
            "messages": MessagesScreen(self),
            "alerts": AlertsScreen(self),
            "topology": TopologyScreen(self),
            "help": HelpScreen(self),
        }
        self.current_screen = "dashboard"

        # State
        self._running = False
        self._last_refresh = datetime.now()

    def _get_header(self) -> Panel:
        """Create the application header."""
        title = Text()
        title.append("MESHING-AROUND ", style="bold cyan")
        title.append(f"v{VERSION}", style="dim")

        if self.demo_mode:
            title.append(" [DEMO MODE]", style="yellow")

        return Panel(Align.center(title), box=box.DOUBLE, border_style="cyan", padding=(0, 2))

    def _get_footer(self) -> Panel:
        """Create the application footer with active screen highlighted."""
        shortcuts = Text()

        # Map screen keys to names and their screen identifiers
        nav_items = [
            ("1", "Dashboard", "dashboard"),
            ("2", "Nodes", "nodes"),
            ("3", "Messages", "messages"),
            ("4", "Alerts", "alerts"),
            ("5", "Topology", "topology"),
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
        shortcuts.append("Send ", style="dim")
        shortcuts.append("[?]", style="yellow bold")
        shortcuts.append("Help ", style="dim")
        shortcuts.append("[q]", style="red bold")
        shortcuts.append("Quit", style="dim")

        return Panel(Align.center(shortcuts), box=box.SIMPLE, border_style="dim")

    def _render(self) -> Layout:
        """Render the full application layout."""
        layout = Layout()

        layout.split_column(
            Layout(self._get_header(), name="header", size=3),
            Layout(name="body"),
            Layout(self._get_footer(), name="footer", size=3),
        )

        # Render current screen with connection-safety guard
        screen = self.screens.get(self.current_screen)
        if screen:
            try:
                layout["body"].update(screen.render())
            except (AttributeError, KeyError, TypeError) as e:
                # Guard against stale/missing API data during reconnection
                layout["body"].update(Panel(f"[yellow]Waiting for connection... ({e})[/yellow]", border_style="yellow"))

        return layout

    def connect(self) -> bool:
        """Connect to the Meshtastic device."""
        self.console.print("[cyan]Connecting to Meshtastic device...[/cyan]")

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console
        ) as progress:
            task = progress.add_task("Connecting...", total=None)

            success = self.api.connect()

            if success:
                progress.update(task, description="[green]Connected![/green]")
            else:
                progress.update(task, description=f"[red]Failed: {self.api.connection_info.error_message}[/red]")

        return success

    def disconnect(self) -> None:
        """Disconnect from the device."""
        self.api.disconnect()

    def run(self) -> None:
        """Run the TUI application."""
        self.console.clear()

        # Show startup banner
        self._show_startup()

        # Connect if not in demo mode
        if not self.demo_mode:
            if not self.connect():
                if not Confirm.ask("Connection failed. Run in demo mode?", default=True):
                    return
                self.demo_mode = True
                self.api = MockMeshtasticAPI(self.config)
                self.api.connect()
        else:
            self.api.connect()

        self._running = True

        try:
            with Live(self._render(), console=self.console, refresh_per_second=2, screen=True) as live:
                while self._running:
                    try:
                        # Update display — match Rich.Live refresh rate (2Hz = 0.5s)
                        live.update(self._render())
                    except (AttributeError, KeyError, TypeError, IndexError):
                        # Guard against transient data issues during updates
                        pass
                    time.sleep(0.5)

        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
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

        # Connect
        if not self.demo_mode:
            if not self.connect():
                if Confirm.ask("Connection failed. Run in demo mode?", default=True):
                    self.demo_mode = True
                    self.api = MockMeshtasticAPI(self.config)
                    self.api.connect()
                else:
                    return
        else:
            self.api.connect()

        self._running = True

        # Save terminal settings
        old_settings = termios.tcgetattr(sys.stdin)

        try:
            # Set terminal to raw mode
            tty.setcbreak(sys.stdin.fileno())

            while self._running:
                # Render screen with error guard
                try:
                    self.console.clear()
                    self.console.print(self._render())
                except (AttributeError, KeyError, TypeError, IndexError):
                    # Transient data issue during render - show minimal output
                    self.console.clear()
                    self.console.print("[yellow]Updating...[/yellow]")

                # Check for input
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    key = sys.stdin.read(1)
                    self._handle_key(key)

        except (KeyboardInterrupt, EOFError):
            pass  # Normal exit
        except OSError as e:
            self.console.print(f"[red]I/O Error: {e}[/red]")
        finally:
            # Restore terminal settings
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            self._running = False
            self.disconnect()
            self.console.clear()
            self.console.print("[cyan]Goodbye![/cyan]")

    def _handle_key(self, key: str) -> None:
        """Handle keyboard input."""
        # Screen-specific handling first
        screen = self.screens.get(self.current_screen)
        if screen and screen.handle_input(key):
            return

        # Global shortcuts
        if key == "q":
            if self.current_screen != "dashboard":
                self.current_screen = "dashboard"
            else:
                self._running = False
        elif key == "1":
            self.current_screen = "dashboard"
        elif key == "2":
            self.current_screen = "nodes"
        elif key == "3":
            self.current_screen = "messages"
        elif key == "4":
            self.current_screen = "alerts"
        elif key == "5":
            self.current_screen = "topology"
        elif key == "s":
            self._send_message_prompt()
        elif key == "?" or key == "h":
            self.current_screen = "help"
        elif key == "r":
            # Refresh - just let the next render cycle handle it
            pass
        elif key == "c":
            if self.api.is_connected:
                self.disconnect()
            else:
                self.connect()

    def _send_message_prompt(self) -> None:
        """Prompt user to send a message."""
        self.console.clear()
        self.console.print(Panel("[bold cyan]Send Message[/bold cyan]", border_style="cyan"))

        try:
            text = Prompt.ask("Message")
            if text:
                channel = int(Prompt.ask("Channel", default="0"))
                dest = Prompt.ask("Destination (^all for broadcast)", default="^all")

                if self.api.send_message(text, dest, channel):
                    self.console.print("[green]Message sent![/green]")
                else:
                    self.console.print("[red]Failed to send message[/red]")

                time.sleep(1)
        except KeyboardInterrupt:
            pass


def main():
    """Main entry point for the TUI application."""
    if not RICH_AVAILABLE:
        print("Error: 'rich' library not found.")
        print("The TUI requires the Rich library for terminal rendering.")
        print("Please install it with: pip install rich")
        print("  or: python3 -m pip install rich")
        print("  or run: python3 mesh_client.py --install-deps")
        print()
        print("Alternatively, use the web interface: python3 mesh_client.py --web")
        sys.exit(1)

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

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
import os
import asyncio
import threading
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, TYPE_CHECKING
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Check for Rich library - do NOT auto-install (PEP 668 compliance)
try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box
    from rich.align import Align
    from rich.columns import Columns
    from rich.markdown import Markdown
    from rich.syntax import Syntax
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

from meshing_around_clients.core import (
    Config, MeshtasticAPI, MessageHandler,
    Node, Message, Alert, MeshNetwork
)
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI

# Version
VERSION = "0.5.0-beta"


class Screen:
    """Base class for TUI screens."""

    def __init__(self, app: 'MeshingAroundTUI'):
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
        layout.split_column(
            Layout(stats, name="stats", size=5),
            Layout(name="main")
        )
        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right", ratio=2)
        )
        layout["left"].split_column(
            Layout(nodes, name="nodes"),
            Layout(alerts, name="alerts")
        )
        layout["right"].update(messages)

        return Panel(
            layout,
            title="[bold cyan]Meshing-Around Dashboard[/bold cyan]",
            subtitle=f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
            border_style="cyan"
        )

    def _create_stats_panel(self) -> Panel:
        """Create the statistics overview panel."""
        network = self.app.api.network
        conn = self.app.api.connection_info

        # Connection status
        if conn.connected:
            status = Text("CONNECTED", style="bold green")
        else:
            status = Text("DISCONNECTED", style="bold red")

        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Label", style="cyan")
        stats_table.add_column("Value", style="white bold")

        stats_table.add_row("Status", status)
        stats_table.add_row("Interface", f"{conn.interface_type} ({conn.device_path})")
        stats_table.add_row("My Node", network.my_node_id or "N/A")
        stats_table.add_row("Nodes", f"{len(network.online_nodes)}/{len(network.nodes)}")
        stats_table.add_row("Messages", str(network.total_messages))
        stats_table.add_row("Alerts", f"{len(network.unread_alerts)} unread")

        return Panel(stats_table, title="[bold]Network Status[/bold]", border_style="blue")

    def _create_nodes_panel(self) -> Panel:
        """Create the nodes list panel."""
        nodes = sorted(
            self.app.api.network.nodes.values(),
            key=lambda n: n.last_heard or datetime.min,
            reverse=True
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
                f"[{name_style}]{node.display_name[:15]}[/{name_style}]",
                node.time_since_heard,
                batt_str,
                snr_str
            )

        if not nodes:
            table.add_row("[dim]No nodes yet[/dim]", "", "", "")

        return Panel(table, title="[bold]Nodes[/bold]", border_style="green")

    def _create_messages_panel(self) -> Panel:
        """Create the messages panel."""
        messages = self.app.api.network.messages[-15:]

        content = []
        for msg in reversed(messages):
            time_str = msg.time_formatted
            sender = msg.sender_name or msg.sender_id[-6:]

            if msg.is_incoming:
                prefix = "[cyan]<<[/cyan]"
            else:
                prefix = "[green]>>[/green]"

            # Check for emergency keywords
            is_emergency = any(
                kw.lower() in msg.text.lower()
                for kw in self.app.config.alerts.emergency_keywords
            )

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

        return Panel(
            Group(*content),
            title="[bold]Messages[/bold]",
            border_style="magenta"
        )

    def _create_alerts_panel(self) -> Panel:
        """Create the alerts panel."""
        alerts = self.app.api.network.alerts[-5:]

        content = []
        for alert in reversed(alerts):
            style = {
                1: "blue",
                2: "yellow",
                3: "orange1",
                4: "red bold"
            }.get(alert.severity, "white")

            icon = {
                1: "i",
                2: "!",
                3: "!!",
                4: "!!!"
            }.get(alert.severity, "*")

            line = Text()
            line.append(f"[{icon}] ", style=style)
            line.append(alert.title[:30], style=style)

            content.append(line)

        if not content:
            content.append(Text("No alerts", style="dim green"))

        return Panel(
            Group(*content),
            title="[bold]Alerts[/bold]",
            border_style="red"
        )


class NodesScreen(Screen):
    """Detailed nodes view screen."""

    def render(self) -> Panel:
        table = Table(
            show_header=True,
            header_style="bold cyan",
            box=box.ROUNDED,
            expand=True,
            title="Mesh Network Nodes"
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

        nodes = sorted(
            self.app.api.network.nodes.values(),
            key=lambda n: n.last_heard or datetime.min,
            reverse=True
        )

        for idx, node in enumerate(nodes, 1):
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

            table.add_row(
                f"[{status_style}]{idx}[/{status_style}]",
                node.node_id[-8:],
                node.display_name,
                node.hardware_model,
                node.role.value,
                node.time_since_heard,
                batt_str,
                snr_str,
                str(node.hop_count) if node.hop_count else "0"
            )

        return Panel(
            table,
            title="[bold cyan]Nodes[/bold cyan]",
            subtitle="[dim]Press 'q' to return to dashboard[/dim]",
            border_style="cyan"
        )


class MessagesScreen(Screen):
    """Detailed messages view screen."""

    def __init__(self, app: 'MeshingAroundTUI'):
        super().__init__(app)
        self.channel_filter: Optional[int] = None

    def render(self) -> Panel:
        messages = self.app.api.network.messages
        if self.channel_filter is not None:
            messages = [m for m in messages if m.channel == self.channel_filter]

        messages = messages[-30:]  # Last 30 messages

        table = Table(
            show_header=True,
            header_style="bold cyan",
            box=box.SIMPLE,
            expand=True
        )

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

            table.add_row(
                msg.time_formatted,
                str(msg.channel),
                direction,
                from_str,
                to_str,
                text,
                snr_str
            )

        filter_text = f"Channel {self.channel_filter}" if self.channel_filter is not None else "All channels"

        return Panel(
            table,
            title=f"[bold cyan]Messages[/bold cyan] - {filter_text}",
            subtitle="[dim]Press 0-7 to filter by channel, 'a' for all, 'q' to return[/dim]",
            border_style="magenta"
        )

    def handle_input(self, key: str) -> bool:
        if key.isdigit() and int(key) < 8:
            self.channel_filter = int(key)
            return True
        elif key == 'a':
            self.channel_filter = None
            return True
        return False


class AlertsScreen(Screen):
    """Detailed alerts view screen."""

    def render(self) -> Panel:
        alerts = self.app.api.network.alerts[-20:]

        table = Table(
            show_header=True,
            header_style="bold cyan",
            box=box.ROUNDED,
            expand=True
        )

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
                ack
            )

        return Panel(
            table,
            title=f"[bold cyan]Alerts[/bold cyan] - {len(self.app.api.network.unread_alerts)} unread",
            subtitle="[dim]Press 'q' to return to dashboard[/dim]",
            border_style="red"
        )


class SendMessageScreen(Screen):
    """Screen for composing and sending messages."""

    def __init__(self, app: 'MeshingAroundTUI'):
        super().__init__(app)
        self.message = ""
        self.channel = 0
        self.destination = "^all"

    def render(self) -> Panel:
        content = []

        # Destination selection
        content.append(Text(f"Destination: {self.destination}", style="cyan"))
        content.append(Text(f"Channel: {self.channel}", style="blue"))
        content.append(Text(""))
        content.append(Text("Message:", style="bold"))
        content.append(Text(self.message or "(type your message)", style="white" if self.message else "dim"))

        return Panel(
            Group(*content),
            title="[bold cyan]Send Message[/bold cyan]",
            subtitle="[dim]Press Enter to send, Esc to cancel[/dim]",
            border_style="green"
        )


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
- **q** - Return to dashboard / Quit

## Actions
- **s** - Send message
- **r** - Refresh data
- **c** - Connect/Disconnect
- **?** - This help

## Message View
- **0-7** - Filter by channel
- **a** - Show all channels

## Dashboard
- **Enter** - Select highlighted item
- **Arrow keys** - Navigate
"""
        return Panel(
            Markdown(help_text),
            title="[bold cyan]Help[/bold cyan]",
            subtitle="[dim]Press any key to return[/dim]",
            border_style="yellow"
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
            "send": SendMessageScreen(self),
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

        return Panel(
            Align.center(title),
            box=box.DOUBLE,
            border_style="cyan",
            padding=(0, 2)
        )

    def _get_footer(self) -> Panel:
        """Create the application footer."""
        shortcuts = Text()
        shortcuts.append("[1]", style="cyan bold")
        shortcuts.append("Dashboard ", style="dim")
        shortcuts.append("[2]", style="cyan bold")
        shortcuts.append("Nodes ", style="dim")
        shortcuts.append("[3]", style="cyan bold")
        shortcuts.append("Messages ", style="dim")
        shortcuts.append("[4]", style="cyan bold")
        shortcuts.append("Alerts ", style="dim")
        shortcuts.append("[s]", style="green bold")
        shortcuts.append("Send ", style="dim")
        shortcuts.append("[?]", style="yellow bold")
        shortcuts.append("Help ", style="dim")
        shortcuts.append("[q]", style="red bold")
        shortcuts.append("Quit", style="dim")

        return Panel(
            Align.center(shortcuts),
            box=box.SIMPLE,
            border_style="dim"
        )

    def _render(self) -> Layout:
        """Render the full application layout."""
        layout = Layout()

        layout.split_column(
            Layout(self._get_header(), name="header", size=3),
            Layout(name="body"),
            Layout(self._get_footer(), name="footer", size=3)
        )

        # Render current screen
        screen = self.screens.get(self.current_screen)
        if screen:
            layout["body"].update(screen.render())

        return layout

    def connect(self) -> bool:
        """Connect to the Meshtastic device."""
        self.console.print("[cyan]Connecting to Meshtastic device...[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
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
            with Live(
                self._render(),
                console=self.console,
                refresh_per_second=2,
                screen=True
            ) as live:
                while self._running:
                    # Update display — match Rich.Live refresh rate (2Hz = 0.5s)
                    live.update(self._render())
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
                # Render screen
                self.console.clear()
                self.console.print(self._render())

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
        if key == 'q':
            if self.current_screen != "dashboard":
                self.current_screen = "dashboard"
            else:
                self._running = False
        elif key == '1':
            self.current_screen = "dashboard"
        elif key == '2':
            self.current_screen = "nodes"
        elif key == '3':
            self.current_screen = "messages"
        elif key == '4':
            self.current_screen = "alerts"
        elif key == 's':
            self._send_message_prompt()
        elif key == '?' or key == 'h':
            self.current_screen = "help"
        elif key == 'r':
            # Refresh - just let the next render cycle handle it
            pass
        elif key == 'c':
            if self.api.is_connected:
                self.disconnect()
            else:
                self.connect()

    def _send_message_prompt(self) -> None:
        """Prompt user to send a message."""
        self.console.clear()
        self.console.print(Panel(
            "[bold cyan]Send Message[/bold cyan]",
            border_style="cyan"
        ))

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

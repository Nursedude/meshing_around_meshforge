"""Whiptail-based TUI for Raspberry Pi.

Provides a raspi-config style monitoring interface using whiptail dialogs.
Used instead of the Rich TUI on Raspberry Pi for a consistent look and
lower resource usage.
"""

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from meshing_around_clients.core import Config, MeshtasticAPI
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI
from meshing_around_clients.core.models import Node
from meshing_around_clients.setup.whiptail import infobox, inputbox, menu, msgbox, yesno

logger = logging.getLogger(__name__)

# Severity labels for alert formatting
_SEVERITY_LABELS: Dict[int, str] = {
    1: "INFO",
    2: "WARNING",
    3: "HIGH",
    4: "CRITICAL",
}


class WhiptailTUI:
    """Whiptail-based monitoring TUI for Raspberry Pi.

    Uses whiptail dialogs (same as raspi-config) for all screens.
    Menu-driven: user picks a screen, views data, presses OK to return.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        demo_mode: bool = False,
    ) -> None:
        self.config = config or Config()
        self.demo_mode = demo_mode
        if demo_mode:
            self.api = MockMeshtasticAPI(self.config)
        else:
            self.api = MeshtasticAPI(self.config)

    def run_interactive(self) -> None:
        """Main loop: connect, show menu, display screens, repeat."""
        self._connect()
        try:
            while True:
                choice = self._main_menu()
                if choice is None or choice == "e":
                    break
                self._show_screen(choice)
        except KeyboardInterrupt:
            pass
        finally:
            self.api.disconnect()

    def _connect(self) -> None:
        """Connect to the mesh network."""
        infobox("Connecting to mesh network...", title="Connecting")
        if self.demo_mode:
            self.api.connect()
        elif not self.api.connect():
            msgbox(
                "Connection failed. Starting in demo mode.",
                title="Connection Error",
            )
            self.demo_mode = True
            self.api = MockMeshtasticAPI(self.config)
            self.api.connect()

    def _main_menu(self) -> Optional[str]:
        """Show the main screen selection menu."""
        network = self.api.network
        nodes = network.get_nodes_snapshot()
        messages = network.get_messages_snapshot()
        alerts = network.get_alerts_snapshot()

        # Build menu items with live counts
        items = [
            ("dashboard", f"Dashboard ({len(nodes)} nodes, {len(messages)} msgs)"),
            ("nodes", f"Nodes ({len(nodes)})"),
            ("messages", f"Messages ({len(messages)})"),
            ("alerts", f"Alerts ({len(alerts)})"),
            ("topology", "Topology"),
            ("config", "Bot Config (edit /opt/meshing-around/config.ini)"),
            ("radio", "Radio Settings (rename longName / shortName)"),
            ("e", "Exit"),
        ]
        return menu("Mesh Monitor", items, default="dashboard")

    def _show_screen(self, screen: str) -> None:
        """Dispatch to the appropriate screen renderer."""
        handlers = {
            "dashboard": self._show_dashboard,
            "nodes": self._show_nodes,
            "messages": self._show_messages,
            "alerts": self._show_alerts,
            "topology": self._show_topology,
            "config": self._show_bot_config,
            "radio": self._show_radio_settings,
        }
        handler = handlers.get(screen)
        if handler:
            handler()

    # ------------------------------------------------------------------
    # Screen renderers
    # ------------------------------------------------------------------

    def _show_dashboard(self) -> None:
        """Dashboard: summary stats + recent messages."""
        network = self.api.network
        health = self.api.connection_health
        nodes = network.get_nodes_snapshot()
        messages = network.get_messages_snapshot()
        alerts = network.get_alerts_snapshot()

        status = health.get("status", "unknown").upper()
        conn_type = self.config.interface.type if self.config else "unknown"
        if self.demo_mode:
            conn_type = "demo"

        lines = [
            f"Status: {status:<20s} Mode: {conn_type}",
            f"Nodes: {len(nodes):<6d} Messages: {len(messages):<6d} Alerts: {len(alerts)}",
        ]

        msg_rate = health.get("messages_per_minute")
        if msg_rate is not None:
            lines.append(f"Message rate: {msg_rate:.1f} msg/min")

        lines.append("")
        lines.append("--- Recent Messages ---")
        recent = messages[-8:] if messages else []
        if not recent:
            lines.append("  (no messages)")
        for msg in reversed(recent):
            ts = msg.time_formatted or "??:??:??"
            sender = msg.sender_name or msg.sender_id or "unknown"
            text = (msg.text or "")[:40]
            lines.append(f"  [{ts}] {sender}: {text}")

        # Alert summary
        if alerts:
            lines.append("")
            lines.append("--- Alerts ---")
            for alert in alerts[-5:]:
                label = _SEVERITY_LABELS.get(alert.severity, "?")
                lines.append(f"  [{label}] {alert.title}")

        msgbox("\n".join(lines), title="Dashboard", height=22, width=70)

    def _show_nodes(self) -> None:
        """Nodes: list of nodes as menu items, select for details."""
        network = self.api.network
        nodes = network.get_nodes_snapshot()

        if not nodes:
            msgbox("No nodes discovered yet.", title="Nodes")
            return

        # Sort by last heard (most recent first)
        nodes.sort(
            key=lambda n: n.last_heard or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Build menu items — show up to 20 nodes
        items: list = []
        for node in nodes[:20]:
            snr = f"SNR:{node.link_quality.snr:.0f}" if node.link_quality else ""
            bat = ""
            if node.telemetry and node.telemetry.battery_level is not None:
                bat = f"Bat:{node.telemetry.battery_level}%"
            heard = node.time_since_heard
            desc = f"{node.display_name:<16s} {snr:<8s} {bat:<8s} {heard}"
            items.append((node.node_id, desc))

        if len(nodes) > 20:
            items.append(("more", f"... and {len(nodes) - 20} more nodes"))

        selected = menu("Nodes", items)
        if selected and selected != "more":
            self._show_node_detail(selected, nodes)

    def _show_node_detail(self, node_id: str, nodes: List[Node]) -> None:
        """Show detailed info for a single node."""
        node = next((n for n in nodes if n.node_id == node_id), None)
        if not node:
            return

        lines = [
            f"Name:     {node.display_name}",
            f"ID:       {node.node_id}",
            f"Role:     {node.role.value}",
            f"Hardware: {node.hardware_model}",
            f"Heard:    {node.time_since_heard}",
            f"Hops:     {node.hop_count}",
        ]

        if node.link_quality:
            lq = node.link_quality
            lines.append(f"SNR:      {lq.snr:.1f} dB (avg {lq.snr_avg:.1f})")
            lines.append(f"RSSI:     {lq.rssi} dBm")
            lines.append(f"Quality:  {lq.quality_percent}%")

        if node.telemetry:
            t = node.telemetry
            if t.battery_level is not None:
                lines.append(f"Battery:  {t.battery_level}%")
            if t.voltage is not None:
                lines.append(f"Voltage:  {t.voltage:.2f}V")
            if t.channel_utilization is not None:
                lines.append(f"ChUtil:   {t.channel_utilization:.1f}%")
            if t.air_util_tx is not None:
                lines.append(f"AirUtil:  {t.air_util_tx:.1f}%")

        if node.position and (node.position.latitude or node.position.longitude):
            p = node.position
            lines.append(f"Position: {p.latitude:.5f}, {p.longitude:.5f}")
            if p.altitude:
                lines.append(f"Altitude: {p.altitude}m")

        if node.neighbors:
            lines.append(f"Neighbors: {len(node.neighbors)}")

        msgbox("\n".join(lines), title=node.display_name, height=20, width=60)

    def _show_messages(self) -> None:
        """Messages: scrollable list of recent messages."""
        network = self.api.network
        messages = network.get_messages_snapshot()

        if not messages:
            msgbox("No messages yet.", title="Messages")
            return

        lines: list = []
        for msg in reversed(messages[-50:]):
            ts = msg.time_formatted or "??:??:??"
            sender = msg.sender_name or msg.sender_id or "unknown"
            ch = f"ch{msg.channel}" if msg.channel else ""
            text = msg.text or f"[{msg.message_type.value}]"
            lines.append(f"[{ts}] {sender} {ch}: {text}")

        msgbox(
            "\n".join(lines),
            title=f"Messages ({len(messages)} total)",
            height=22,
            width=76,
            scrolltext=True,
        )

    def _show_alerts(self) -> None:
        """Alerts: list of alerts with severity."""
        network = self.api.network
        alerts = network.get_alerts_snapshot()

        if not alerts:
            msgbox("No alerts.", title="Alerts")
            return

        lines: list = []
        for alert in reversed(alerts[-30:]):
            label = _SEVERITY_LABELS.get(alert.severity, "?")
            ts = ""
            if alert.timestamp:
                ts = alert.timestamp.strftime("%H:%M:%S")
            lines.append(f"[{label:<8s}] {ts} - {alert.title}")
            if alert.message and alert.message != alert.title:
                lines.append(f"           {alert.message[:60]}")

        msgbox(
            "\n".join(lines),
            title=f"Alerts ({len(alerts)} total)",
            height=22,
            width=76,
            scrolltext=True,
        )

    def _show_topology(self) -> None:
        """Topology: ASCII tree of mesh network."""
        network = self.api.network
        nodes = network.get_nodes_snapshot()

        if not nodes:
            msgbox("No nodes discovered yet.", title="Topology")
            return

        # Build a simple tree: group nodes by role, show neighbors
        routers = [n for n in nodes if n.role.value in ("ROUTER", "ROUTER_CLIENT")]
        clients = [n for n in nodes if n.role.value in ("CLIENT", "CLIENT_MUTE")]
        repeaters = [n for n in nodes if n.role.value == "REPEATER"]

        lines = [f"Mesh Network ({len(nodes)} nodes)", ""]

        if routers:
            lines.append(f"Routers ({len(routers)}):")
            for node in routers[:10]:
                n_count = len(node.neighbors) if node.neighbors else 0
                lines.append(f"  +-- {node.display_name} ({node.role.value}) - {n_count} neighbors")
                for nb_id in (node.neighbors or [])[:5]:
                    nb = next((n for n in nodes if n.node_id == nb_id), None)
                    nb_name = nb.display_name if nb else nb_id
                    lines.append(f"  |   +-- {nb_name}")
            lines.append("")

        if clients:
            lines.append(f"Clients ({len(clients)}):")
            for node in clients[:15]:
                heard = node.time_since_heard
                lines.append(f"  +-- {node.display_name} ({heard})")
            if len(clients) > 15:
                lines.append(f"  ... and {len(clients) - 15} more")
            lines.append("")

        if repeaters:
            lines.append(f"Repeaters ({len(repeaters)}):")
            for node in repeaters[:5]:
                lines.append(f"  +-- {node.display_name}")

        # Channel info
        channels = network.get_channels() if hasattr(network, "get_channels") else []
        if channels:
            lines.append("")
            lines.append("Channels:")
            for ch in channels:
                enc = "encrypted" if ch.is_encrypted else "open"
                lines.append(f"  [{ch.index}] {ch.display_name} ({enc}) - {ch.message_count} msgs")

        msgbox(
            "\n".join(lines),
            title="Topology",
            height=22,
            width=76,
            scrolltext=True,
        )

    # ------------------------------------------------------------------
    # Bot Config editor (raspi-config style — nested menus)
    # ------------------------------------------------------------------

    def _find_bot_config(self) -> Optional[Path]:
        """Locate the meshing-around bot's config.ini."""
        if self.config and hasattr(self.config, "find_upstream_config"):
            try:
                found = self.config.find_upstream_config()
                if found:
                    return found
            except (OSError, AttributeError) as e:
                logger.debug("find_upstream_config failed: %s", e)
        primary = Path("/opt/meshing-around/config.ini")
        try:
            if primary.exists():
                return primary
        except OSError:
            pass
        return None

    def _show_bot_config(self) -> None:
        """Edit the bot's config.ini section by section.

        Nested raspi-config style: sections menu -> keys menu -> input
        prompt -> save with .ini.bak backup.  This is the
        rename-the-bot entry point: [general] bot_name is the field
        the BA5E owner wants.
        """
        import configparser

        path = self._find_bot_config()
        if not path:
            msgbox(
                "Bot config.ini not found.\n"
                "Install meshing-around or create a symlink:\n"
                "  sudo ln -s /path/to/config.ini "
                "/opt/meshing-around/config.ini",
                title="Bot Config",
            )
            return

        parser = configparser.ConfigParser()
        try:
            parser.read(str(path))
        except (configparser.Error, OSError) as e:
            msgbox(f"Failed to read {path}:\n{e}", title="Bot Config")
            return

        if not parser.sections():
            msgbox(f"{path} has no sections.", title="Bot Config")
            return

        while True:
            section_items: List[tuple] = [(s, s) for s in parser.sections()]
            section_items.append(("e", "[ Back to main menu ]"))
            section = menu(f"Bot Config ({path.name})", section_items)
            if section is None or section == "e":
                return

            self._edit_config_section(parser, path, section)

    def _edit_config_section(
        self,
        parser,  # configparser.ConfigParser — annotation omitted to avoid
        # forward-ref to a function-local import.
        path: Path,
        section: str,
    ) -> None:
        """Inner loop: pick a key in `section`, edit, save with .bak backup."""
        import shutil

        while True:
            keys = parser.options(section)
            kv_items: List[tuple] = []
            for key in keys:
                value = parser.get(section, key)
                # whiptail menu rows are one line — truncate long values.
                shown = value if len(value) <= 40 else value[:37] + "..."
                kv_items.append((key, f"{key} = {shown}"))
            kv_items.append(("e", "[ Back ]"))

            key = menu(f"[{section}]", kv_items)
            if key is None or key == "e":
                return

            current = parser.get(section, key)
            new = inputbox(f"{section}.{key} =", default=current)
            if new is None:
                continue  # user cancelled the edit, stay in section menu
            if new == current:
                continue

            parser.set(section, key, new)

            # Save with .ini.bak backup (feedback_config_protection.md).
            try:
                if path.exists():
                    bak = path.with_suffix(".ini.bak")
                    shutil.copy2(str(path), str(bak))
                with open(path, "w") as f:
                    parser.write(f)
            except OSError as e:
                msgbox(f"Save failed:\n{e}", title="Error")
                # Roll back the in-memory change so we don't show stale state
                parser.set(section, key, current)
                continue

            msgbox(
                f"Saved {section}.{key}.\n"
                "Restart bot for changes to take effect:\n"
                "  sudo systemctl restart mesh_bot.service",
                title="Saved",
            )

    # ------------------------------------------------------------------
    # Radio Settings (meshtastic --set-owner)
    # ------------------------------------------------------------------

    def _show_radio_settings(self) -> None:
        """Radio Settings menu — currently only rename."""
        items = [
            ("rename", "Rename radio (longName / shortName)"),
            ("e", "[ Back ]"),
        ]
        choice = menu("Radio Settings", items)
        if choice == "rename":
            self._radio_rename()

    def _resolve_radio_connection_args(self) -> Optional[List[str]]:
        """Pick the right --port/--host args for `meshtastic` CLI.

        Returns None if the user cancels or the connection mode is
        unrenamable through this code path.
        """
        iface_type = (self.config.interface.type or "").lower() if self.config else ""

        if iface_type == "serial":
            port = self.config.interface.port if self.config else ""
            if not port:
                msgbox(
                    "Serial interface configured but no port set.\n" "Set [interface] port in mesh_client.ini first.",
                    title="Radio Rename",
                )
                return None
            return ["--port", port]

        if iface_type == "tcp":
            host = self.config.interface.hostname if self.config else ""
            if not host:
                msgbox(
                    "TCP interface configured but no hostname set.\n"
                    "Set [interface] hostname in mesh_client.ini first.",
                    title="Radio Rename",
                )
                return None
            return ["--host", host]

        # MQTT (and anything else): mesh_client is not on a direct path to
        # the radio, so we cannot use the existing config.  Prompt for
        # the radio's IP separately.  On BA5E this is the G2 WiFi Radio
        # address that the bot is also wired into.
        host = inputbox(
            "Mesh client is on MQTT (no direct radio path).\n" "Enter the radio's TCP host (e.g. 192.168.1.50):",
            default="",
        )
        if not host:
            return None
        return ["--host", host]

    def _meshtastic_cli_path(self) -> str:
        """Prefer the project's venv meshtastic CLI, fall back to PATH."""
        repo_root = Path(__file__).resolve().parents[2]
        venv_cli = repo_root / ".venv" / "bin" / "meshtastic"
        if venv_cli.exists():
            return str(venv_cli)
        return "meshtastic"

    def _radio_rename(self) -> None:
        """Prompt for new long/short names and exec `meshtastic --set-owner`.

        This is the OTHER half of the BA5E rename — the bot config edit
        changes the bot's internal identity; this changes what the rest
        of the mesh sees.  Both edits land separately.
        """
        conn_args = self._resolve_radio_connection_args()
        if conn_args is None:
            return

        long_name = inputbox(
            "New longName (max 39 chars):",
            default="",
        )
        if not long_name:
            return
        long_name = long_name[:39]

        # Default shortName: first 4 chars of longName, uppercased
        default_short = long_name[:4].upper()
        short_name = inputbox(
            "New shortName (max 4 chars):",
            default=default_short,
        )
        if not short_name:
            return
        short_name = short_name[:4]

        if not yesno(
            f"Set radio name to:\n"
            f"  long:  {long_name}\n"
            f"  short: {short_name}\n\n"
            f"Connection: {' '.join(conn_args)}\n\n"
            "Proceed?",
            default_yes=False,
        ):
            return

        cmd = [
            self._meshtastic_cli_path(),
            *conn_args,
            "--set-owner",
            long_name,
            "--set-owner-short",
            short_name,
        ]

        infobox(
            "Setting radio name...\n" "This takes 10-20 seconds while the radio reboots.",
            title="Radio Rename",
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            msgbox(
                "meshtastic command timed out after 60s.\n"
                "Radio may still be applying the rename — check with\n"
                "  meshtastic --info\n"
                "after another 30 seconds.",
                title="Timeout",
            )
            return
        except (OSError, FileNotFoundError) as e:
            msgbox(
                f"Cannot run meshtastic CLI:\n{e}\n\n" "Install with: pip install meshtastic",
                title="Error",
            )
            return

        if result.returncode == 0:
            msgbox(
                f"Radio renamed.\n\n"
                f"long:  {long_name}\n"
                f"short: {short_name}\n\n"
                "The radio will reboot to apply the change.",
                title="Success",
            )
        else:
            err = (result.stderr or result.stdout or "Unknown error")[:300]
            msgbox(
                f"Rename failed (exit {result.returncode}):\n\n{err}",
                title="Error",
            )

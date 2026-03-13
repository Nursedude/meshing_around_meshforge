"""Whiptail-based TUI for Raspberry Pi.

Provides a raspi-config style monitoring interface using whiptail dialogs.
Used instead of the Rich TUI on Raspberry Pi for a consistent look and
lower resource usage.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from meshing_around_clients.core import Config, MeshtasticAPI
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI
from meshing_around_clients.core.models import Alert, Message, Node
from meshing_around_clients.setup.whiptail import infobox, menu, msgbox

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

"""
Unit tests for meshing_around_clients.tui.app

Tests TUI rendering crash guards and connection health indicator.
"""

import sys
import unittest

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

try:
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from meshing_around_clients.core.config import Config
from meshing_around_clients.core.meshtastic_api import MockMeshtasticAPI
from meshing_around_clients.core.models import MeshRoute, Message, MessageType, Node, RouteHop


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestDashboardMessagesNoneGuards(unittest.TestCase):
    """Test that DashboardScreen handles None text and sender_id."""

    def setUp(self):
        from meshing_around_clients.tui.app import DashboardScreen, MeshingAroundTUI

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = DashboardScreen(self.tui)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_render_with_none_text_message(self):
        """Messages with text=None should not crash rendering."""
        msg = Message(
            id="none-text",
            sender_id="!aabb1234",
            sender_name="TestNode",
            text=None,
            message_type=MessageType.POSITION,
        )
        self.tui.api.network.add_message(msg)

        # Should not raise
        panel = self.screen._create_feed_panel()
        self.assertIsNotNone(panel)

    def test_render_with_none_sender_id(self):
        """Messages with sender_id=None should not crash rendering."""
        msg = Message(
            id="none-sender",
            sender_id=None,
            sender_name=None,
            text="hello",
            message_type=MessageType.TEXT,
        )
        self.tui.api.network.add_message(msg)

        panel = self.screen._create_feed_panel()
        self.assertIsNotNone(panel)

    def test_render_with_all_none_fields(self):
        """Messages with both text=None and sender_id=None should not crash."""
        msg = Message(
            id="all-none",
            sender_id=None,
            sender_name=None,
            text=None,
            message_type=MessageType.TELEMETRY,
        )
        self.tui.api.network.add_message(msg)

        panel = self.screen._create_feed_panel()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestMessagesScreenNoneGuards(unittest.TestCase):
    """Test that MessagesScreen handles None fields."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI, MessagesScreen

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = MessagesScreen(self.tui)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_render_with_none_text_and_recipient(self):
        """MessagesScreen with None text and recipient_id should not crash."""
        msg = Message(
            id="msg-none",
            sender_id=None,
            sender_name=None,
            text=None,
            recipient_id=None,
            message_type=MessageType.POSITION,
        )
        self.tui.api.network.add_message(msg)

        panel = self.screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestConnectionHealthIndicator(unittest.TestCase):
    """Test that TUI header shows connection status."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()

    def tearDown(self):
        self.tui.api.disconnect()

    def test_header_shows_disconnected_when_not_connected(self):
        """Header should show DISCONNECTED when API is not connected."""
        self.tui.api.connection_info.connected = False
        header = self.tui._get_header()
        # The rendered text should contain DISCONNECTED
        rendered = str(header.renderable)
        self.assertIn("DISCONNECTED", rendered)

    def test_header_no_disconnected_when_connected(self):
        """Header should not show DISCONNECTED when API is connected."""
        self.tui.api.connection_info.connected = True
        header = self.tui._get_header()
        rendered = str(header.renderable)
        self.assertNotIn("DISCONNECTED", rendered)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestSnapshotUsageInScreens(unittest.TestCase):
    """Test that screens use snapshot methods for thread-safe rendering."""

    def setUp(self):
        from meshing_around_clients.tui.app import (
            AlertsScreen,
            DashboardScreen,
            MeshingAroundTUI,
            NodesScreen,
            TopologyScreen,
        )

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()

    def tearDown(self):
        self.tui.api.disconnect()

    def test_dashboard_renders_without_errors(self):
        """Full dashboard render should complete without errors."""
        screen = self.tui.screens["dashboard"]
        panel = screen.render()
        self.assertIsNotNone(panel)

    def test_nodes_screen_renders_without_errors(self):
        """Nodes screen render should complete without errors."""
        screen = self.tui.screens["nodes"]
        panel = screen.render()
        self.assertIsNotNone(panel)

    def test_alerts_screen_renders_without_errors(self):
        """Alerts screen render should complete without errors."""
        screen = self.tui.screens["alerts"]
        panel = screen.render()
        self.assertIsNotNone(panel)

    def test_topology_screen_renders_without_errors(self):
        """Topology screen render should complete without errors."""
        screen = self.tui.screens["topology"]
        panel = screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestTopologyRouteNoneGuards(unittest.TestCase):
    """Test that TopologyScreen handles missing nodes and empty hops."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI, TopologyScreen

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = TopologyScreen(self.tui)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_route_with_missing_destination_node(self):
        """Route whose destination_id is not in nodes dict should not crash."""
        route = MeshRoute(destination_id="!unknown99")
        self.tui.api.network.routes["!unknown99"] = route

        panel = self.screen.render()
        self.assertIsNotNone(panel)

    def test_route_with_empty_hops_list(self):
        """Route with empty hops list should render without crash."""
        route = MeshRoute(destination_id="!abc12345", hops=[])
        self.tui.api.network.routes["!abc12345"] = route

        panel = self.screen.render()
        self.assertIsNotNone(panel)

    def test_route_with_valid_hops(self):
        """Route with valid hops should render hop info."""
        hop = RouteHop(node_id="!hop11111")
        route = MeshRoute(destination_id="!dest2222", hops=[hop])
        self.tui.api.network.routes["!dest2222"] = route

        panel = self.screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestNodesScreenNoneRoleGuard(unittest.TestCase):
    """Test that NodesScreen handles nodes with None role."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI, NodesScreen

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = NodesScreen(self.tui)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_node_with_none_role_renders(self):
        """A node whose role is None should render as UNKNOWN, not crash."""
        node = Node(node_id="!nullrole1", node_num=0)
        node.role = None
        self.tui.api.network.nodes["!nullrole1"] = node

        panel = self.screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestChannelsNoneRoleGuard(unittest.TestCase):
    """Test that TopologyScreen channels panel handles None role."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI, TopologyScreen

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = TopologyScreen(self.tui)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_channel_with_none_role_skipped(self):
        """A channel with None role should be skipped (treated as DISABLED)."""
        from meshing_around_clients.core.models import Channel

        ch = Channel(index=5, name="nullrole")
        ch.role = None
        self.tui.api.network.channels[5] = ch

        panel = self.screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestNodesScreenSearch(unittest.TestCase):
    """Test NodesScreen text search functionality."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI, NodesScreen

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = NodesScreen(self.tui)

        # Add test nodes
        from meshing_around_clients.core.models import NodeRole

        node1 = Node(node_id="!aabb1111", node_num=1, long_name="AlphaNode", hardware_model="TBEAM")
        node1.role = NodeRole.CLIENT
        node2 = Node(node_id="!ccdd2222", node_num=2, long_name="BetaRouter", hardware_model="HELTEC")
        node2.role = NodeRole.ROUTER
        node3 = Node(node_id="!eeff3333", node_num=3, long_name="GammaNode", hardware_model="TBEAM")
        node3.role = NodeRole.CLIENT
        self.tui.api.network.nodes["!aabb1111"] = node1
        self.tui.api.network.nodes["!ccdd2222"] = node2
        self.tui.api.network.nodes["!eeff3333"] = node3

    def tearDown(self):
        self.tui.api.disconnect()

    def test_search_filters_by_name(self):
        """Search should filter nodes by display name."""
        self.screen.search_query = "alphanode"
        filtered = self.screen._filter_nodes(self.tui.api.network.get_nodes_snapshot())
        self.assertTrue(any(n.long_name == "AlphaNode" for n in filtered))
        # Every result should match the query
        for n in filtered:
            self.assertIn("alphanode", (n.display_name or "").lower())

    def test_search_filters_by_hardware(self):
        """Search should filter nodes by hardware model."""
        self.screen.search_query = "heltec"
        filtered = self.screen._filter_nodes(self.tui.api.network.get_nodes_snapshot())
        self.assertTrue(len(filtered) >= 1)
        for n in filtered:
            self.assertIn("heltec", (n.hardware_model or "").lower())

    def test_search_filters_by_node_id(self):
        """Search should filter nodes by node ID."""
        self.screen.search_query = "ccdd"
        filtered = self.screen._filter_nodes(self.tui.api.network.get_nodes_snapshot())
        self.assertEqual(len(filtered), 1)

    def test_empty_search_returns_all(self):
        """Empty search query should return all nodes."""
        self.screen.search_query = ""
        filtered = self.screen._filter_nodes(self.tui.api.network.get_nodes_snapshot())
        self.assertGreaterEqual(len(filtered), 3)  # 3 test nodes + any demo nodes

    def test_search_mode_activation(self):
        """Pressing / should activate search mode."""
        self.assertFalse(self.screen.search_active)
        result = self.screen.handle_input("/")
        self.assertTrue(result)
        self.assertTrue(self.screen.search_active)

    def test_search_mode_key_buffering(self):
        """Keys in search mode should be buffered into search_query."""
        self.screen.search_active = True
        self.screen.handle_input("a")
        self.screen.handle_input("l")
        self.screen.handle_input("p")
        self.assertEqual(self.screen.search_query, "alp")

    def test_search_mode_escape_cancels(self):
        """Escape should cancel search and clear query."""
        self.screen.search_active = True
        self.screen.search_query = "test"
        self.screen.handle_input("\x1b")
        self.assertFalse(self.screen.search_active)
        self.assertEqual(self.screen.search_query, "")

    def test_search_mode_enter_confirms(self):
        """Enter should confirm search and keep query."""
        self.screen.search_active = True
        self.screen.search_query = "alpha"
        self.screen.handle_input("\n")
        self.assertFalse(self.screen.search_active)
        self.assertEqual(self.screen.search_query, "alpha")

    def test_search_mode_backspace(self):
        """Backspace should delete last character."""
        self.screen.search_active = True
        self.screen.search_query = "test"
        self.screen.handle_input("\x7f")
        self.assertEqual(self.screen.search_query, "tes")

    def test_render_with_active_search(self):
        """Render should succeed with active search."""
        self.screen.search_active = True
        self.screen.search_query = "alpha"
        panel = self.screen.render()
        self.assertIsNotNone(panel)

    def test_render_with_confirmed_search(self):
        """Render should succeed with confirmed search filter."""
        self.screen.search_query = "tbeam"
        panel = self.screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestMessagesScreenSearch(unittest.TestCase):
    """Test MessagesScreen text search functionality."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI, MessagesScreen

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = MessagesScreen(self.tui)

        # Add test messages
        msg1 = Message(
            id="msg1", sender_id="!aabb1111", sender_name="AlphaNode", text="Hello world", message_type=MessageType.TEXT
        )
        msg2 = Message(
            id="msg2",
            sender_id="!ccdd2222",
            sender_name="BetaNode",
            text="Emergency SOS",
            message_type=MessageType.TEXT,
        )
        msg3 = Message(
            id="msg3",
            sender_id="!aabb1111",
            sender_name="AlphaNode",
            text="Weather update",
            message_type=MessageType.TEXT,
        )
        self.tui.api.network.add_message(msg1)
        self.tui.api.network.add_message(msg2)
        self.tui.api.network.add_message(msg3)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_search_filters_by_text(self):
        """Search should filter messages by text content."""
        self.screen.search_query = "emergency"
        all_msgs = self.tui.api.network.get_messages_snapshot()
        filtered = self.screen._filter_messages(all_msgs)
        self.assertTrue(any("Emergency" in (m.text or "") for m in filtered))

    def test_search_filters_by_sender(self):
        """Search should filter messages by sender name."""
        self.screen.search_query = "beta"
        all_msgs = self.tui.api.network.get_messages_snapshot()
        filtered = self.screen._filter_messages(all_msgs)
        self.assertTrue(all((m.sender_name or "").lower().find("beta") >= 0 for m in filtered))

    def test_search_combined_with_channel_filter(self):
        """Search should work alongside channel filter."""
        self.screen.channel_filter = 0
        self.screen.search_query = "hello"
        panel = self.screen.render()
        self.assertIsNotNone(panel)

    def test_search_mode_does_not_intercept_channel_keys(self):
        """In search mode, digit keys should be buffered, not change channel."""
        self.screen.search_active = True
        self.screen.handle_input("3")
        self.assertEqual(self.screen.search_query, "3")
        self.assertIsNone(self.screen.channel_filter)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestConnectionHealthInHeader(unittest.TestCase):
    """Test connection health indicator in TUI header."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()

    def tearDown(self):
        self.tui.api.disconnect()

    def test_header_shows_healthy_when_connected(self):
        """Header should show HEALTHY when connection is healthy."""
        self.tui.api.connection_info.connected = True
        header = self.tui._get_header()
        rendered = str(header.renderable)
        self.assertIn("HEALTHY", rendered)

    def test_header_shows_disconnected(self):
        """Header should show DISCONNECTED when not connected."""
        self.tui.api.connection_info.connected = False
        header = self.tui._get_header()
        rendered = str(header.renderable)
        self.assertIn("DISCONNECTED", rendered)

    def test_dashboard_stats_use_connection_health(self):
        """Dashboard stats panel should render connection health."""
        from meshing_around_clients.tui.app import DashboardScreen

        screen = DashboardScreen(self.tui)
        panel = screen._create_stats_panel()
        self.assertIsNotNone(panel)


class TestPlainTextTUI(unittest.TestCase):
    """Test PlainTextTUI fallback mode (no Rich required)."""

    def test_plain_text_tui_init(self):
        """PlainTextTUI should initialize without Rich."""
        from meshing_around_clients.tui.app import PlainTextTUI

        config = Config()
        tui = PlainTextTUI(config=config, demo_mode=True)
        self.assertTrue(tui.demo_mode)
        self.assertIsNotNone(tui.api)

    def test_plain_text_tui_default_config(self):
        """PlainTextTUI should work with default config."""
        from meshing_around_clients.tui.app import PlainTextTUI

        tui = PlainTextTUI(demo_mode=True)
        self.assertIsNotNone(tui.config)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestSafePanelRender(unittest.TestCase):
    """Test safe_panel_render crash isolation."""

    def setUp(self):
        from meshing_around_clients.tui.app import DashboardScreen, MeshingAroundTUI

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = DashboardScreen(self.tui)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_dashboard_survives_stats_panel_crash(self):
        """Dashboard should still render if _create_stats_panel crashes."""
        self.screen._create_stats_panel = lambda: (_ for _ in ()).throw(RuntimeError("test crash"))
        # Should not raise — safe_panel_render catches the error
        panel = self.screen.render()
        self.assertIsNotNone(panel)

    def test_dashboard_survives_nodes_panel_crash(self):
        """Dashboard should still render if _create_nodes_panel crashes."""
        self.screen._create_nodes_panel = lambda: (_ for _ in ()).throw(ValueError("test crash"))
        panel = self.screen.render()
        self.assertIsNotNone(panel)

    def test_topology_survives_health_panel_crash(self):
        """Topology should still render if _create_health_panel crashes."""
        from meshing_around_clients.tui.app import TopologyScreen

        screen = TopologyScreen(self.tui)
        screen._create_health_panel = lambda: (_ for _ in ()).throw(IndexError("test crash"))
        panel = screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestConfigValidationOnStartup(unittest.TestCase):
    """Test that config validation runs and doesn't crash the TUI."""

    def test_show_config_warnings_no_crash(self):
        """_show_config_warnings should not crash even with invalid config."""
        from meshing_around_clients.tui.app import MeshingAroundTUI

        config = Config()
        # Set an invalid MQTT port to trigger a validation issue
        config.mqtt.port = 99999
        tui = MeshingAroundTUI(config=config, demo_mode=True)
        # Should not raise
        tui._show_config_warnings()

    def test_show_config_warnings_valid_config(self):
        """_show_config_warnings should work with valid config too."""
        from meshing_around_clients.tui.app import MeshingAroundTUI

        config = Config()
        tui = MeshingAroundTUI(config=config, demo_mode=True)
        tui._show_config_warnings()


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestCSVExport(unittest.TestCase):
    """Test CSV message export."""

    def setUp(self):
        from meshing_around_clients.tui.app import MeshingAroundTUI, MessagesScreen

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = MessagesScreen(self.tui)

        msg = Message(
            id="csv-test", sender_id="!aabb1111", sender_name="TestNode", text="CSV test", message_type=MessageType.TEXT
        )
        self.tui.api.network.add_message(msg)

    def tearDown(self):
        self.tui.api.disconnect()
        import glob
        import os

        for f in glob.glob("meshforge_messages_*.csv"):
            os.remove(f)
        for f in glob.glob("meshforge_messages_*.json"):
            os.remove(f)

    def test_csv_export_creates_file(self):
        """E key should export CSV file."""
        import glob

        self.screen._export_messages(fmt="csv")
        files = glob.glob("meshforge_messages_*.csv")
        self.assertTrue(len(files) >= 1)

    def test_shift_e_triggers_csv_export(self):
        """E (shift-e) key should be handled."""
        result = self.screen.handle_input("E")
        self.assertTrue(result)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestAlertsScreenSearch(unittest.TestCase):
    """Test AlertsScreen text search functionality."""

    def setUp(self):
        from meshing_around_clients.tui.app import AlertsScreen, MeshingAroundTUI

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = AlertsScreen(self.tui)

        # Add test alerts
        from meshing_around_clients.core.models import Alert, AlertType

        alert1 = Alert(id="a1", title="Low battery", message="Node X at 10%", alert_type=AlertType.BATTERY, severity=3)
        alert2 = Alert(id="a2", title="New node", message="Node Y joined", alert_type=AlertType.NEW_NODE, severity=1)
        alert3 = Alert(id="a3", title="Emergency", message="SOS received", alert_type=AlertType.EMERGENCY, severity=4)
        self.tui.api.network.add_alert(alert1)
        self.tui.api.network.add_alert(alert2)
        self.tui.api.network.add_alert(alert3)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_search_activation(self):
        """Pressing / should activate search mode."""
        self.assertFalse(self.screen.search_active)
        result = self.screen.handle_input("/")
        self.assertTrue(result)
        self.assertTrue(self.screen.search_active)

    def test_search_key_buffering(self):
        """Keys in search mode should be buffered into search_query."""
        self.screen.search_active = True
        self.screen.handle_input("s")
        self.screen.handle_input("o")
        self.screen.handle_input("s")
        self.assertEqual(self.screen.search_query, "sos")

    def test_search_escape_cancels(self):
        """Escape should cancel search and clear query."""
        self.screen.search_active = True
        self.screen.search_query = "test"
        self.screen.handle_input("\x1b")
        self.assertFalse(self.screen.search_active)
        self.assertEqual(self.screen.search_query, "")

    def test_search_enter_confirms(self):
        """Enter should confirm search and keep query."""
        self.screen.search_active = True
        self.screen.search_query = "battery"
        self.screen.handle_input("\n")
        self.assertFalse(self.screen.search_active)
        self.assertEqual(self.screen.search_query, "battery")

    def test_search_backspace(self):
        """Backspace should delete last character."""
        self.screen.search_active = True
        self.screen.search_query = "test"
        self.screen.handle_input("\x7f")
        self.assertEqual(self.screen.search_query, "tes")

    def test_render_with_search_filter(self):
        """Render should succeed with search filter applied."""
        self.screen.search_query = "battery"
        panel = self.screen.render()
        self.assertIsNotNone(panel)

    def test_render_with_active_search(self):
        """Render should succeed while search is active."""
        self.screen.search_active = True
        self.screen.search_query = "emer"
        panel = self.screen.render()
        self.assertIsNotNone(panel)


class TestMeshtasticAPIConnectionHealth(unittest.TestCase):
    """Test connection_health property on MeshtasticAPI."""

    def test_healthy_when_connected(self):
        config = Config()
        api = MockMeshtasticAPI(config)
        api.connect()
        health = api.connection_health
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["connected"])
        api.disconnect()

    def test_disconnected_when_not_connected(self):
        config = Config()
        api = MockMeshtasticAPI(config)
        health = api.connection_health
        self.assertEqual(health["status"], "disconnected")
        self.assertFalse(health["connected"])


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestConfigScreenTemplateMerge(unittest.TestCase):
    """Test _BaseConfigEditor template merging (used by ClientConfigScreen)."""

    def setUp(self):
        import tempfile
        import configparser

        from meshing_around_clients.tui.app import ClientConfigScreen, MeshingAroundTUI

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = ClientConfigScreen(self.tui)

        # Create temp config.ini with minimal content
        self.tmp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmp_dir, "config.ini")
        self.template_path = os.path.join(self.tmp_dir, "config.template")

        # Minimal config.ini
        parser = configparser.ConfigParser()
        parser.add_section("general")
        parser.set("general", "motd", "Hello")
        parser.set("general", "ollama", "False")
        parser.add_section("location")
        parser.set("location", "lat", "0.0")
        with open(self.config_path, "w") as f:
            parser.write(f)

        # Template with additional keys (both uncommented and commented)
        with open(self.template_path, "w") as f:
            f.write("[general]\n")
            f.write("motd = Default MOTD\n")
            f.write("ollama = False\n")
            f.write("# ollamamodel = gemma2:2b\n")
            f.write("whoami = True\n")
            f.write("\n[location]\n")
            f.write("lat = 0.0\n")
            f.write("lon = 0.0\n")
            f.write("\n[sentry]\n")
            f.write("sentryenabled = False\n")

    def tearDown(self):
        import shutil
        self.tui.api.disconnect()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_parse_template_comments_extracts_keys(self):
        """Commented key=value lines are extracted from template."""
        from meshing_around_clients.tui.app import _BaseConfigEditor
        from pathlib import Path

        result = _BaseConfigEditor._parse_template_comments(Path(self.template_path))
        self.assertIn("general", result)
        self.assertIn("ollamamodel", result["general"])
        self.assertEqual(result["general"]["ollamamodel"], "gemma2:2b")

    def test_parse_template_comments_skips_documentation(self):
        """Documentation comments with multiple key=value are filtered."""
        from meshing_around_clients.tui.app import _BaseConfigEditor
        from pathlib import Path
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".template", delete=False) as f:
            f.write("[location]\n")
            f.write("# pz = Puget Sound, ph = Honolulu HI, gm = Florida Keys\n")
            f.write("# coastalenabled = True\n")
            doc_template = f.name

        try:
            result = _BaseConfigEditor._parse_template_comments(Path(doc_template))
            # "pz" should be filtered (documentation), "coastalenabled" should be kept
            location_keys = result.get("location", {})
            self.assertNotIn("pz", location_keys)
            self.assertIn("coastalenabled", location_keys)
        finally:
            os.unlink(doc_template)

    def _setup_merge_test(self):
        """Helper: set up screen with test config and test template."""
        from pathlib import Path
        import configparser
        self.screen._parser = configparser.ConfigParser()
        self.screen._parser.read(self.config_path)
        self.screen._config_path = Path(self.config_path)
        self.screen._template_keys = set()
        # Point _find_template at our test template, not the real one
        self.screen._find_template = lambda: Path(self.template_path)
        self.screen._merge_template_defaults()

    def test_merge_adds_missing_keys(self):
        """Template merge adds keys missing from config.ini."""
        self._setup_merge_test()

        # whoami was in template but not config.ini
        self.assertTrue(self.screen._parser.has_option("general", "whoami"))
        self.assertEqual(self.screen._parser.get("general", "whoami"), "True")
        self.assertIn(("general", "whoami"), self.screen._template_keys)

    def test_merge_does_not_overwrite_user_values(self):
        """Template merge never overwrites existing user values."""
        self._setup_merge_test()

        # User's motd should remain unchanged
        self.assertEqual(self.screen._parser.get("general", "motd"), "Hello")
        self.assertNotIn(("general", "motd"), self.screen._template_keys)

    def test_merge_adds_missing_sections(self):
        """Template merge adds entire sections missing from config.ini."""
        self._setup_merge_test()

        # [sentry] section was in template but not config.ini
        self.assertTrue(self.screen._parser.has_section("sentry"))
        self.assertIn(("sentry", "sentryenabled"), self.screen._template_keys)

    def test_merge_adds_commented_keys(self):
        """Template merge adds keys from commented lines (e.g., ollamamodel)."""
        self._setup_merge_test()

        # ollamamodel was commented in template, should now be available
        self.assertTrue(self.screen._parser.has_option("general", "ollamamodel"))
        self.assertIn(("general", "ollamamodel"), self.screen._template_keys)

    def test_find_regional_templates(self):
        """Regional client templates are discovered in profiles/ directory."""
        templates = self.screen._find_regional_templates()
        # Client profiles (not *_bot.ini) should be found
        self.assertTrue(len(templates) > 0,
                        "Expected at least one client profile")

    def test_render_shows_default_indicator(self):
        """Template-sourced values show (default) indicator in render output."""
        from pathlib import Path
        import configparser

        self.screen._parser = configparser.ConfigParser()
        self.screen._parser.read(self.config_path)
        self.screen._config_path = Path(self.config_path)
        self.screen._template_keys = set()
        self.screen._loaded = True
        self.screen._merge_template_defaults()
        self.screen._rebuild_items()

        panel = self.screen.render()
        # The panel should render without error
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestClientConfigScreen(unittest.TestCase):
    """Test ClientConfigScreen finds mesh_client.ini and merges template."""

    def setUp(self):
        from meshing_around_clients.tui.app import ClientConfigScreen, MeshingAroundTUI

        self.config = Config()
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()
        self.screen = ClientConfigScreen(self.tui)

    def tearDown(self):
        self.tui.api.disconnect()

    def test_find_config_returns_config_path(self):
        """ClientConfigScreen._find_config() returns the app's config path."""
        found = self.screen._find_config()
        if self.tui.config.config_path and self.tui.config.config_path.exists():
            self.assertIsNotNone(found)
            self.assertEqual(found, self.tui.config.config_path)

    def test_find_template_returns_template_path(self):
        """ClientConfigScreen._find_template() finds mesh_client.ini.template."""
        found = self.screen._find_template()
        # Template should exist in project root
        if found:
            self.assertIn("template", found.name)

    def test_section_order_is_client_sections(self):
        """ClientConfigScreen uses client-specific section ordering."""
        self.assertIn("interface", self.screen._SECTION_ORDER)
        self.assertIn("mqtt", self.screen._SECTION_ORDER)
        self.assertIn("advanced", self.screen._SECTION_ORDER)
        # Should NOT have bot sections
        self.assertNotIn("general", self.screen._SECTION_ORDER)
        self.assertNotIn("bbs", self.screen._SECTION_ORDER)

    def test_find_regional_templates_excludes_bot(self):
        """Client profiles exclude *_bot.ini files."""
        templates = self.screen._find_regional_templates()
        for name, path in templates:
            self.assertFalse(path.name.endswith("_bot.ini"),
                             f"Bot profile should be excluded: {path}")

    def test_post_edit_validate_tcp_no_hostname(self):
        """Warns when type set to tcp but hostname is empty."""
        import configparser
        self.screen._parser = configparser.ConfigParser()
        self.screen._parser.add_section("interface")
        self.screen._parser.set("interface", "type", "tcp")
        self.screen._parser.set("interface", "hostname", "")
        warning = self.screen._post_edit_validate("interface", "type", "tcp")
        self.assertIsNotNone(warning)
        self.assertIn("hostname", warning)

    def test_post_edit_validate_tcp_with_hostname(self):
        """No warning when type set to tcp and hostname is set."""
        import configparser
        self.screen._parser = configparser.ConfigParser()
        self.screen._parser.add_section("interface")
        self.screen._parser.set("interface", "type", "tcp")
        self.screen._parser.set("interface", "hostname", "192.168.1.100")
        warning = self.screen._post_edit_validate("interface", "type", "tcp")
        self.assertIsNone(warning)

    def test_panel_title_is_client(self):
        """ClientConfigScreen panel title should say 'Client'."""
        self.assertIn("Client", self.screen._panel_title)

    def test_render_does_not_crash(self):
        """Rendering ClientConfigScreen should not raise."""
        self.screen._load()
        panel = self.screen.render()
        self.assertIsNotNone(panel)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestScreenKeyBindings(unittest.TestCase):
    """Test screen navigation key mappings."""

    def setUp(self):
        self.config = Config()
        from meshing_around_clients.tui.app import MeshingAroundTUI
        self.tui = MeshingAroundTUI(config=self.config, demo_mode=True)
        self.tui.api.connect()

    def tearDown(self):
        self.tui.api.disconnect()

    def test_key_0_maps_to_client_config(self):
        """Key '0' should navigate to client_config screen."""
        self.assertIn("0", self.tui._SCREEN_KEYS)
        self.assertEqual(self.tui._SCREEN_KEYS["0"], "client_config")

    def test_key_8_maps_to_bot_config(self):
        """Key '8' should navigate to bot config screen."""
        self.assertIn("8", self.tui._SCREEN_KEYS)
        self.assertEqual(self.tui._SCREEN_KEYS["8"], "config")

    def test_client_config_screen_registered(self):
        """client_config screen should be in the screens dict."""
        self.assertIn("client_config", self.tui.screens)

    def test_nav_bar_includes_client_cfg(self):
        """Footer nav bar should include Cfg entry for screen 0."""
        footer = self.tui._get_footer()
        # The footer panel should render without error
        self.assertIsNotNone(footer)


@unittest.skipUnless(RICH_AVAILABLE, "Rich library not available")
class TestBaseConfigEditorInheritance(unittest.TestCase):
    """Test that both config screens inherit from _BaseConfigEditor."""

    def test_config_screen_is_screen(self):
        from meshing_around_clients.tui.app import ConfigScreen, Screen
        self.assertTrue(issubclass(ConfigScreen, Screen))

    def test_client_config_screen_is_base_editor(self):
        from meshing_around_clients.tui.app import ClientConfigScreen, _BaseConfigEditor
        self.assertTrue(issubclass(ClientConfigScreen, _BaseConfigEditor))

    def test_base_editor_has_open_in_editor(self):
        """_BaseConfigEditor should have _open_in_editor method."""
        from meshing_around_clients.tui.app import _BaseConfigEditor
        self.assertTrue(hasattr(_BaseConfigEditor, "_open_in_editor"))

    def test_e_key_handled_by_base_editor(self):
        """The 'e' key should be handled by _BaseConfigEditor.handle_input."""
        from meshing_around_clients.tui.app import ClientConfigScreen, MeshingAroundTUI
        config = Config()
        tui = MeshingAroundTUI(config=config, demo_mode=True)
        tui.api.connect()
        screen = ClientConfigScreen(tui)
        screen._loaded = True
        screen._config_path = None  # Prevents actual editor launch
        # 'e' should return True (handled) even if no file
        result = screen.handle_input("e")
        self.assertTrue(result)
        tui.api.disconnect()


class TestConfigHelperMethods(unittest.TestCase):
    """Test Config.get_client_template_path() and find_client_profiles()."""

    def test_get_client_template_path(self):
        """Should find mesh_client.ini.template in project root."""
        config = Config()
        path = config.get_client_template_path()
        if path:
            self.assertIn("template", path.name)
            self.assertTrue(path.exists())

    def test_find_client_profiles_excludes_bot(self):
        """find_client_profiles() should not include *_bot.ini."""
        config = Config()
        profiles = config.find_client_profiles()
        for name, path in profiles:
            self.assertFalse(path.name.endswith("_bot.ini"),
                             f"Bot profile should be excluded: {path}")

    def test_find_client_profiles_includes_regional(self):
        """Should find regional profiles like hawaii.ini, europe.ini."""
        config = Config()
        profiles = config.find_client_profiles()
        names = [name for name, _ in profiles]
        # At least one regional profile should exist
        self.assertTrue(len(profiles) > 0,
                        "Expected at least one client profile")


import os


if __name__ == "__main__":
    unittest.main()

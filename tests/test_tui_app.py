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
        panel = self.screen._create_messages_panel()
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

        panel = self.screen._create_messages_panel()
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

        panel = self.screen._create_messages_panel()
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


if __name__ == "__main__":
    unittest.main()

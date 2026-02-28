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
from meshing_around_clients.core.models import Message, MessageType


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


if __name__ == "__main__":
    unittest.main()

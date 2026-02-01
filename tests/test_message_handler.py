"""
Unit tests for meshing_around_clients.core.message_handler
"""

import unittest
from datetime import datetime

import sys
sys.path.insert(0, str(__file__).rsplit('/tests/', 1)[0])

from meshing_around_clients.core.message_handler import (
    CommandType, ParsedCommand, CommandResponse,
    MessageHandler, BBSHandler, GameHandler
)
from meshing_around_clients.core.models import Message, AlertType
from meshing_around_clients.core.config import Config


class TestCommandType(unittest.TestCase):
    """Test CommandType enum."""

    def test_command_type_values(self):
        self.assertEqual(CommandType.PING.value, "ping")
        self.assertEqual(CommandType.HELP.value, "help")
        self.assertEqual(CommandType.ADMIN.value, "admin")
        self.assertEqual(CommandType.UNKNOWN.value, "unknown")


class TestParsedCommand(unittest.TestCase):
    """Test ParsedCommand dataclass."""

    def test_creation(self):
        cmd = ParsedCommand(
            command_type=CommandType.PING,
            command="ping",
            args=[],
            raw_text="!ping",
            sender_id="!sender123"
        )
        self.assertEqual(cmd.command_type, CommandType.PING)
        self.assertEqual(cmd.command, "ping")
        self.assertEqual(cmd.sender_id, "!sender123")
        self.assertFalse(cmd.is_admin)

    def test_with_args(self):
        cmd = ParsedCommand(
            command_type=CommandType.WEATHER,
            command="weather",
            args=["New", "York"],
            raw_text="!weather New York",
            sender_id="!sender123"
        )
        self.assertEqual(cmd.args, ["New", "York"])

    def test_admin_flag(self):
        cmd = ParsedCommand(
            command_type=CommandType.ADMIN,
            command="admin",
            args=["status"],
            raw_text="!admin status",
            sender_id="!admin123",
            is_admin=True
        )
        self.assertTrue(cmd.is_admin)


class TestCommandResponse(unittest.TestCase):
    """Test CommandResponse dataclass."""

    def test_default_values(self):
        resp = CommandResponse(text="pong!")
        self.assertEqual(resp.text, "pong!")
        self.assertFalse(resp.is_private)
        self.assertEqual(resp.delay, 0.0)
        self.assertIsNone(resp.metadata)

    def test_custom_values(self):
        resp = CommandResponse(
            text="Secret message",
            is_private=True,
            delay=1.5,
            metadata={"key": "value"}
        )
        self.assertTrue(resp.is_private)
        self.assertEqual(resp.delay, 1.5)
        self.assertEqual(resp.metadata["key"], "value")


class TestMessageHandlerCommandParsing(unittest.TestCase):
    """Test MessageHandler command parsing."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.handler = MessageHandler(self.config)

    def test_parse_exclamation_prefix(self):
        """Parse command with ! prefix."""
        msg = Message(id="m1", sender_id="!s1", text="!ping")
        parsed = self.handler.parse_command(msg)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.command_type, CommandType.PING)
        self.assertEqual(parsed.command, "ping")

    def test_parse_slash_prefix(self):
        """Parse command with / prefix."""
        msg = Message(id="m1", sender_id="!s1", text="/help")
        parsed = self.handler.parse_command(msg)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.command_type, CommandType.HELP)

    def test_parse_at_bot_prefix(self):
        """Parse command with @bot prefix."""
        msg = Message(id="m1", sender_id="!s1", text="@bot info")
        parsed = self.handler.parse_command(msg)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.command_type, CommandType.INFO)

    def test_parse_with_args(self):
        """Parse command with arguments."""
        msg = Message(id="m1", sender_id="!s1", text="!weather Seattle WA")
        parsed = self.handler.parse_command(msg)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.command_type, CommandType.WEATHER)
        self.assertEqual(parsed.args, ["Seattle", "WA"])

    def test_parse_unknown_command(self):
        """Parse unknown command."""
        msg = Message(id="m1", sender_id="!s1", text="!unknownxyz")
        parsed = self.handler.parse_command(msg)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.command_type, CommandType.UNKNOWN)

    def test_no_command_prefix(self):
        """Regular message without command prefix."""
        msg = Message(id="m1", sender_id="!s1", text="Hello world")
        parsed = self.handler.parse_command(msg)

        self.assertIsNone(parsed)

    def test_empty_command(self):
        """Empty command after prefix."""
        msg = Message(id="m1", sender_id="!s1", text="!")
        parsed = self.handler.parse_command(msg)

        self.assertIsNone(parsed)

    def test_case_insensitive(self):
        """Commands are case insensitive."""
        msg = Message(id="m1", sender_id="!s1", text="!PING")
        parsed = self.handler.parse_command(msg)

        self.assertEqual(parsed.command_type, CommandType.PING)

    def test_admin_node_detection(self):
        """Admin nodes are marked."""
        msg = Message(id="m1", sender_id="!admin123", text="!admin status")
        parsed = self.handler.parse_command(msg, admin_nodes=["!admin123"])

        self.assertTrue(parsed.is_admin)

    def test_command_aliases(self):
        """Test command aliases."""
        # wx -> WEATHER
        msg1 = Message(id="m1", sender_id="!s1", text="!wx")
        parsed1 = self.handler.parse_command(msg1)
        self.assertEqual(parsed1.command_type, CommandType.WEATHER)

        # ? -> HELP
        msg2 = Message(id="m2", sender_id="!s1", text="!?")
        parsed2 = self.handler.parse_command(msg2)
        self.assertEqual(parsed2.command_type, CommandType.HELP)

        # loc -> LOCATION
        msg3 = Message(id="m3", sender_id="!s1", text="!loc")
        parsed3 = self.handler.parse_command(msg3)
        self.assertEqual(parsed3.command_type, CommandType.LOCATION)


class TestMessageHandlerResponses(unittest.TestCase):
    """Test MessageHandler command responses."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.bot_name = "TestBot"
        self.handler = MessageHandler(self.config)

    def test_ping_response(self):
        """Test ping command response."""
        msg = Message(id="m1", sender_id="!s1", text="!ping")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertEqual(response.text, "pong!")

    def test_pong_response(self):
        """Test pong command response."""
        msg = Message(id="m1", sender_id="!s1", text="!pong")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertEqual(response.text, "ping!")

    def test_help_response(self):
        """Test help command response."""
        msg = Message(id="m1", sender_id="!s1", text="!help")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("Available commands", response.text)
        self.assertIn("!ping", response.text)

    def test_info_response(self):
        """Test info command response."""
        msg = Message(id="m1", sender_id="!s1", text="!info")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("TestBot", response.text)

    def test_weather_usage(self):
        """Test weather command without args."""
        msg = Message(id="m1", sender_id="!s1", text="!weather")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("Usage", response.text)

    def test_weather_with_location(self):
        """Test weather command with location."""
        msg = Message(id="m1", sender_id="!s1", text="!weather Portland")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("Portland", response.text)

    def test_location_no_args(self):
        """Test location command without args."""
        msg = Message(id="m1", sender_id="!s1", text="!location")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("Location", response.text)

    def test_location_with_node(self):
        """Test location command for specific node."""
        msg = Message(id="m1", sender_id="!s1", text="!location NodeA")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("NodeA", response.text)

    def test_unknown_command_response(self):
        """Test unknown command response."""
        msg = Message(id="m1", sender_id="!s1", text="!foobar")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("Unknown command", response.text)

    def test_non_command_message(self):
        """Test regular message (no command)."""
        msg = Message(id="m1", sender_id="!s1", text="Hello there")
        response = self.handler.process_message(msg)

        self.assertIsNone(response)


class TestMessageHandlerAdmin(unittest.TestCase):
    """Test MessageHandler admin commands."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.admin_nodes = ["!admin123"]
        self.handler = MessageHandler(self.config)

    def test_admin_command_denied(self):
        """Non-admin cannot use admin commands."""
        msg = Message(id="m1", sender_id="!regular", text="!admin status")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertIn("Admin permission required", response.text)
        self.assertTrue(response.is_private)

    def test_admin_command_allowed(self):
        """Admin can use admin commands."""
        msg = Message(id="m1", sender_id="!admin123", text="!admin status")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertNotIn("permission required", response.text)

    def test_admin_help(self):
        """Test admin help without subcommand."""
        msg = Message(id="m1", sender_id="!admin123", text="!admin")
        response = self.handler.process_message(msg)

        self.assertIn("Admin Commands", response.text)

    def test_admin_broadcast(self):
        """Test admin broadcast command."""
        msg = Message(id="m1", sender_id="!admin123", text="!admin broadcast Hello all")
        response = self.handler.process_message(msg)

        self.assertIn("BROADCAST", response.text)
        self.assertIn("Hello all", response.text)
        self.assertTrue(response.metadata["broadcast"])


class TestMessageHandlerBBS(unittest.TestCase):
    """Test MessageHandler BBS commands."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.handler = MessageHandler(self.config)

    def test_bbs_help(self):
        """Test BBS help."""
        msg = Message(id="m1", sender_id="!s1", text="!bbs")
        response = self.handler.process_message(msg)

        self.assertIn("BBS Commands", response.text)
        self.assertIn("!bbs list", response.text)

    def test_bbs_list_empty(self):
        """Test BBS list with no messages."""
        msg = Message(id="m1", sender_id="!s1", text="!bbs list")
        response = self.handler.process_message(msg)

        self.assertIn("No BBS messages", response.text)

    def test_bbs_post_and_list(self):
        """Test posting and listing BBS messages."""
        # Post a message to public (which goes to 'public' recipient)
        post_msg = Message(id="m1", sender_id="!s1", text="!bbs post Hello BBS!")
        post_response = self.handler.process_message(post_msg)
        self.assertIn("posted", post_response.text)


class TestMessageHandlerMail(unittest.TestCase):
    """Test MessageHandler mail commands."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.handler = MessageHandler(self.config)

    def test_mail_help(self):
        """Test mail help."""
        msg = Message(id="m1", sender_id="!s1", text="!mail")
        response = self.handler.process_message(msg)

        self.assertIn("Mail", response.text)
        self.assertIn("!mail check", response.text)

    def test_mail_check_empty(self):
        """Test mail check with no messages."""
        msg = Message(id="m1", sender_id="!s1", text="!mail check")
        response = self.handler.process_message(msg)

        self.assertIn("No new mail", response.text)

    def test_mail_send(self):
        """Test sending mail."""
        msg = Message(id="m1", sender_id="!s1", text="!mail send !recipient Hello!")
        response = self.handler.process_message(msg)

        self.assertIn("Mail sent", response.text)


class TestMessageHandlerGame(unittest.TestCase):
    """Test MessageHandler game commands."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.handler = MessageHandler(self.config)

    def test_game_help(self):
        """Test game help."""
        msg = Message(id="m1", sender_id="!s1", text="!game")
        response = self.handler.process_message(msg)

        self.assertIn("Available Games", response.text)
        self.assertIn("dopewars", response.text)

    def test_start_game(self):
        """Test starting a game."""
        msg = Message(id="m1", sender_id="!s1", text="!game dopewars")
        response = self.handler.process_message(msg)

        self.assertIn("DopeWars", response.text)

    def test_quit_game(self):
        """Test quitting a game."""
        # Start a game first
        start_msg = Message(id="m1", sender_id="!s1", text="!game blackjack")
        self.handler.process_message(start_msg)

        # Then quit
        quit_msg = Message(id="m2", sender_id="!s1", text="!game quit")
        response = self.handler.process_message(quit_msg)

        self.assertIn("ended", response.text)

    def test_unknown_game(self):
        """Test unknown game name."""
        msg = Message(id="m1", sender_id="!s1", text="!game unknowngame")
        response = self.handler.process_message(msg)

        self.assertIn("Unknown game", response.text)


class TestMessageHandlerAlerts(unittest.TestCase):
    """Test MessageHandler alert detection."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.config.alerts.enabled = True
        self.config.alerts.emergency_keywords = ["help", "sos", "emergency", "911"]
        self.handler = MessageHandler(self.config)

    def test_emergency_keyword_detection(self):
        """Test emergency keyword triggers alert."""
        msg = Message(id="m1", sender_id="!s1", text="HELP! Need assistance!")
        alerts = self.handler.check_alerts(msg)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, AlertType.EMERGENCY)
        self.assertEqual(alerts[0].severity, 4)

    def test_no_alert_for_normal_message(self):
        """Test normal message doesn't trigger alert."""
        msg = Message(id="m1", sender_id="!s1", text="Hello, how are you?")
        alerts = self.handler.check_alerts(msg)

        self.assertEqual(len(alerts), 0)

    def test_case_insensitive_keywords(self):
        """Test keywords are case insensitive."""
        msg = Message(id="m1", sender_id="!s1", text="SOS SOS SOS")
        alerts = self.handler.check_alerts(msg)

        self.assertEqual(len(alerts), 1)

    def test_alerts_disabled(self):
        """Test no alerts when disabled."""
        self.config.alerts.enabled = False
        msg = Message(id="m1", sender_id="!s1", text="HELP! Emergency!")
        alerts = self.handler.check_alerts(msg)

        self.assertEqual(len(alerts), 0)

    def test_single_alert_per_message(self):
        """Only one emergency alert per message even with multiple keywords."""
        msg = Message(id="m1", sender_id="!s1", text="HELP! SOS! Emergency! 911!")
        alerts = self.handler.check_alerts(msg)

        # Should only be 1 alert (breaks after first match)
        self.assertEqual(len(alerts), 1)


class TestMessageHandlerFilters(unittest.TestCase):
    """Test MessageHandler message filters."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.handler = MessageHandler(self.config)

    def test_filter_blocks_message(self):
        """Test filter can block message processing."""
        def block_filter(msg):
            return False  # Block all

        self.handler.register_message_filter(block_filter)

        msg = Message(id="m1", sender_id="!s1", text="!ping")
        response = self.handler.process_message(msg)

        self.assertIsNone(response)

    def test_filter_allows_message(self):
        """Test filter can allow message processing."""
        def allow_filter(msg):
            return True  # Allow all

        self.handler.register_message_filter(allow_filter)

        msg = Message(id="m1", sender_id="!s1", text="!ping")
        response = self.handler.process_message(msg)

        self.assertIsNotNone(response)
        self.assertEqual(response.text, "pong!")

    def test_filter_error_handling(self):
        """Test filter errors are handled gracefully."""
        def bad_filter(msg):
            raise ValueError("Test error")

        self.handler.register_message_filter(bad_filter)

        # Should not raise - errors are caught and logged
        msg = Message(id="m1", sender_id="!s1", text="!ping")
        response = self.handler.process_message(msg)

        # Filter error is caught, processing continues
        self.assertIsNotNone(response)
        self.assertEqual(response.text, "pong!")


class TestMessageHandlerCustomHandler(unittest.TestCase):
    """Test MessageHandler custom command handlers."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.handler = MessageHandler(self.config)

    def test_custom_handler(self):
        """Test registering custom command handler."""
        def custom_ping(cmd):
            return CommandResponse(text="Custom pong!")

        self.handler.register_command_handler(CommandType.PING, custom_ping)

        msg = Message(id="m1", sender_id="!s1", text="!ping")
        response = self.handler.process_message(msg)

        self.assertEqual(response.text, "Custom pong!")


class TestBBSHandler(unittest.TestCase):
    """Test BBSHandler."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.bbs = BBSHandler(self.config)

    def test_post_message(self):
        """Test posting a message."""
        result = self.bbs.post_message("!sender", "!recipient", "Hello!")
        self.assertTrue(result)

    def test_get_messages(self):
        """Test getting messages."""
        self.bbs.post_message("!sender", "!recipient", "Message 1")
        self.bbs.post_message("!sender", "!recipient", "Message 2")

        messages = self.bbs.get_messages("!recipient")
        self.assertEqual(len(messages), 2)

    def test_get_messages_empty(self):
        """Test getting messages for node with none."""
        messages = self.bbs.get_messages("!nobody")
        self.assertEqual(len(messages), 0)

    def test_unread_only(self):
        """Test getting unread messages only."""
        self.bbs.post_message("!sender", "!recipient", "Message 1")
        self.bbs.post_message("!sender", "!recipient", "Message 2")

        # Mark first as read
        self.bbs.mark_read("!recipient", 0)

        unread = self.bbs.get_messages("!recipient", unread_only=True)
        self.assertEqual(len(unread), 1)

    def test_mark_read(self):
        """Test marking message as read."""
        self.bbs.post_message("!sender", "!recipient", "Message")

        result = self.bbs.mark_read("!recipient", 0)
        self.assertTrue(result)

        messages = self.bbs.get_messages("!recipient")
        self.assertTrue(messages[0]["read"])

    def test_mark_read_invalid_index(self):
        """Test marking invalid index as read."""
        result = self.bbs.mark_read("!recipient", 999)
        self.assertFalse(result)

    def test_get_unread_count(self):
        """Test getting unread message count."""
        self.bbs.post_message("!s1", "!r1", "Msg 1")
        self.bbs.post_message("!s2", "!r1", "Msg 2")
        self.bbs.post_message("!s3", "!r1", "Msg 3")

        self.assertEqual(self.bbs.get_unread_count("!r1"), 3)

        self.bbs.mark_read("!r1", 0)
        self.assertEqual(self.bbs.get_unread_count("!r1"), 2)


class TestGameHandler(unittest.TestCase):
    """Test GameHandler."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.game = GameHandler(self.config)

    def test_available_games(self):
        """Test available games list."""
        self.assertIn("dopewars", GameHandler.GAMES)
        self.assertIn("blackjack", GameHandler.GAMES)
        self.assertIn("quiz", GameHandler.GAMES)

    def test_start_game(self):
        """Test starting a game."""
        result = self.game.start_game("!player1", "dopewars")
        self.assertIn("DopeWars", result)

    def test_start_unknown_game(self):
        """Test starting unknown game."""
        result = self.game.start_game("!player1", "unknowngame")
        self.assertIn("Unknown game", result)

    def test_end_game(self):
        """Test ending a game."""
        self.game.start_game("!player1", "blackjack")
        result = self.game.end_game("!player1")
        self.assertIn("ended", result)

    def test_end_no_game(self):
        """Test ending when no game active."""
        result = self.game.end_game("!player1")
        self.assertIn("No active game", result)

    def test_get_active_games(self):
        """Test getting active games."""
        self.game.start_game("!p1", "dopewars")
        self.game.start_game("!p2", "blackjack")

        active = self.game.get_active_games()
        self.assertEqual(len(active), 2)
        self.assertEqual(active["!p1"], "dopewars")
        self.assertEqual(active["!p2"], "blackjack")

    def test_process_input(self):
        """Test processing game input."""
        self.game.start_game("!player1", "quiz")
        result = self.game.process_input("!player1", "answer A")
        self.assertIn("quiz", result)

    def test_process_input_no_game(self):
        """Test processing input with no active game."""
        result = self.game.process_input("!player1", "something")
        self.assertIn("No active game", result)


if __name__ == "__main__":
    unittest.main()

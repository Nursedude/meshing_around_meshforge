"""
Message handler for Meshing-Around Clients.
Provides message processing, command handling, and game integration.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, List, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from .models import Message, Alert, Node, AlertType, MessageType
from .config import Config


class CommandType(Enum):
    """Types of bot commands."""
    INFO = "info"
    LOCATION = "location"
    WEATHER = "weather"
    PING = "ping"
    STATS = "stats"
    HELP = "help"
    BBS = "bbs"
    MAIL = "mail"
    GAME = "game"
    ADMIN = "admin"
    UNKNOWN = "unknown"


@dataclass
class ParsedCommand:
    """Represents a parsed command from a message."""
    command_type: CommandType
    command: str
    args: List[str]
    raw_text: str
    sender_id: str
    is_admin: bool = False


@dataclass
class CommandResponse:
    """Response to a command."""
    text: str
    is_private: bool = False
    delay: float = 0.0
    metadata: Dict[str, Any] = None


class MessageHandler:
    """
    Handles message processing, command parsing, and response generation.
    Integrates with meshing-around bot features.
    """

    # Command patterns
    COMMAND_PREFIXES = ["!", "/", "@bot"]

    # Built-in commands
    COMMANDS = {
        "ping": CommandType.PING,
        "pong": CommandType.PING,
        "info": CommandType.INFO,
        "node": CommandType.INFO,
        "location": CommandType.LOCATION,
        "loc": CommandType.LOCATION,
        "where": CommandType.LOCATION,
        "weather": CommandType.WEATHER,
        "wx": CommandType.WEATHER,
        "stats": CommandType.STATS,
        "status": CommandType.STATS,
        "help": CommandType.HELP,
        "?": CommandType.HELP,
        "commands": CommandType.HELP,
        "bbs": CommandType.BBS,
        "bbspost": CommandType.BBS,
        "bbslist": CommandType.BBS,
        "mail": CommandType.MAIL,
        "msg": CommandType.MAIL,
        "game": CommandType.GAME,
        "play": CommandType.GAME,
        "admin": CommandType.ADMIN,
        "reboot": CommandType.ADMIN,
        "shutdown": CommandType.ADMIN,
    }

    def __init__(self, config: Config):
        self.config = config
        self._command_handlers: Dict[CommandType, Callable] = {}
        self._message_filters: List[Callable] = []
        self._alert_handlers: List[Callable] = []

        # Register default handlers
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default command handlers."""
        self.register_command_handler(CommandType.PING, self._handle_ping)
        self.register_command_handler(CommandType.HELP, self._handle_help)
        self.register_command_handler(CommandType.INFO, self._handle_info)
        self.register_command_handler(CommandType.STATS, self._handle_stats)
        self.register_command_handler(CommandType.LOCATION, self._handle_location)
        self.register_command_handler(CommandType.WEATHER, self._handle_weather)
        self.register_command_handler(CommandType.BBS, self._handle_bbs)
        self.register_command_handler(CommandType.MAIL, self._handle_mail)
        self.register_command_handler(CommandType.GAME, self._handle_game)
        self.register_command_handler(CommandType.ADMIN, self._handle_admin)

        # Initialize sub-handlers
        self._bbs_handler = BBSHandler(self.config)
        self._game_handler = GameHandler(self.config)

    def register_command_handler(self, cmd_type: CommandType, handler: Callable) -> None:
        """Register a command handler."""
        self._command_handlers[cmd_type] = handler

    def register_message_filter(self, filter_func: Callable) -> None:
        """Register a message filter."""
        self._message_filters.append(filter_func)

    def register_alert_handler(self, handler: Callable) -> None:
        """Register an alert handler."""
        self._alert_handlers.append(handler)

    def parse_command(self, message: Message, admin_nodes: List[str] = None) -> Optional[ParsedCommand]:
        """Parse a message for commands."""
        text = message.text.strip()
        admin_nodes = admin_nodes or []

        # Check for command prefix
        command_text = None
        for prefix in self.COMMAND_PREFIXES:
            if text.lower().startswith(prefix):
                command_text = text[len(prefix):].strip()
                break

        if not command_text:
            return None

        # Split into command and args
        parts = command_text.split()
        if not parts:
            return None

        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        # Determine command type
        cmd_type = self.COMMANDS.get(command, CommandType.UNKNOWN)

        return ParsedCommand(
            command_type=cmd_type,
            command=command,
            args=args,
            raw_text=text,
            sender_id=message.sender_id,
            is_admin=message.sender_id in admin_nodes
        )

    def process_message(self, message: Message) -> Optional[CommandResponse]:
        """Process a message and return a response if applicable."""
        # Run through filters
        logger = logging.getLogger(__name__)
        for filter_func in self._message_filters:
            try:
                if not filter_func(message):
                    return None
            except (ValueError, TypeError, KeyError, AttributeError) as e:
                # ValueError: Invalid filter logic/data
                # TypeError: Type mismatch in filter
                # KeyError: Missing expected message attributes
                # AttributeError: Missing expected methods/properties
                logger.warning("Message filter %s raised an error: %s", filter_func.__name__, e)

        # Parse command
        parsed = self.parse_command(message, self.config.admin_nodes)
        if not parsed:
            return None

        # Check for admin-only commands
        if parsed.command_type == CommandType.ADMIN and not parsed.is_admin:
            return CommandResponse(
                text="Admin permission required",
                is_private=True
            )

        # Execute handler
        handler = self._command_handlers.get(parsed.command_type)
        if handler:
            try:
                return handler(parsed)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError) as e:
                # ValueError: Invalid command arguments or data
                # TypeError: Type mismatch in handler
                # KeyError: Missing expected data/keys
                # AttributeError: Missing expected methods/properties
                # IndexError: Invalid array/list access
                logger.error("Command handler error for %s: %s", parsed.command, e)
                return CommandResponse(text="An internal error occurred.")

        return CommandResponse(text=f"Unknown command: {parsed.command}")

    def check_alerts(self, message: Message) -> List[Alert]:
        """Check message for alert conditions."""
        alerts = []

        # Check emergency keywords
        if self.config.alerts.enabled:
            text_lower = message.text.lower()
            for keyword in self.config.alerts.emergency_keywords:
                if keyword.lower() in text_lower:
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.EMERGENCY,
                        title="Emergency Keyword Detected",
                        message=f"From {message.sender_name}: {message.text}",
                        severity=4,
                        source_node=message.sender_id,
                        metadata={"keyword": keyword, "message_id": message.id}
                    )
                    alerts.append(alert)
                    break

        # Run custom alert handlers
        logger = logging.getLogger(__name__)
        for handler in self._alert_handlers:
            try:
                custom_alert = handler(message)
                if custom_alert:
                    alerts.append(custom_alert)
            except (ValueError, TypeError, KeyError, AttributeError) as e:
                # ValueError: Invalid alert data or logic
                # TypeError: Type mismatch in handler
                # KeyError: Missing expected data/keys
                # AttributeError: Missing expected methods/properties
                logger.warning("Alert handler %s raised an error: %s", handler.__name__, e)

        return alerts

    # Default command handlers

    def _handle_ping(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle ping/pong command."""
        if cmd.command == "ping":
            return CommandResponse(text="pong!")
        return CommandResponse(text="ping!")

    def _handle_help(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle help command."""
        help_text = """Available commands:
!ping - Check bot connectivity
!info - Show bot/node information
!stats - Show mesh statistics
!location [node] - Get position info
!weather <loc> - Get weather (requires API)
!bbs - Bulletin board system
!mail - Private messaging
!game - Play games (dopewars, blackjack, etc)
!admin - Admin commands (restricted)
!help - This help message"""
        return CommandResponse(text=help_text)

    def _handle_info(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle info command."""
        return CommandResponse(
            text=f"Bot: {self.config.bot_name}\nVersion: 1.0.0"
        )

    def _handle_stats(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle stats command."""
        return CommandResponse(
            text="Stats: Use the TUI or web interface for detailed statistics"
        )

    def _handle_location(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle location command."""
        if cmd.args:
            # User requesting location of a specific node
            node_name = " ".join(cmd.args)
            return CommandResponse(
                text=f"Location request for '{node_name}' - check TUI/web for position data",
                metadata={"requested_node": node_name}
            )
        # Request own location or general location info
        return CommandResponse(
            text="Location: Enable GPS on your device or check TUI/web for node positions"
        )

    def _handle_weather(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle weather command."""
        if cmd.args:
            location = " ".join(cmd.args)
            # Weather API integration would go here
            # For now, return a placeholder that indicates the feature exists
            return CommandResponse(
                text=f"Weather for '{location}': Feature requires external API configuration. "
                     "Configure weather_api_key in settings to enable.",
                metadata={"location": location}
            )
        return CommandResponse(
            text="Usage: !weather <location>\nExample: !weather New York"
        )

    def _handle_bbs(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle BBS (Bulletin Board System) command."""
        if not cmd.args:
            return CommandResponse(
                text="BBS Commands:\n"
                     "!bbs list - List messages\n"
                     "!bbs read <id> - Read message\n"
                     "!bbs post <msg> - Post message\n"
                     "!bbs delete <id> - Delete (admin)"
            )

        subcommand = cmd.args[0].lower()

        if subcommand == "list":
            messages = self._bbs_handler.get_messages(cmd.sender_id)
            if not messages:
                return CommandResponse(text="No BBS messages found")
            msg_list = []
            for i, msg in enumerate(messages[-5:]):  # Last 5 messages
                status = "[NEW]" if not msg["read"] else ""
                msg_list.append(f"{i+1}. {msg['from'][-6:]}: {msg['message'][:20]}... {status}")
            return CommandResponse(text="Recent BBS Messages:\n" + "\n".join(msg_list))

        elif subcommand == "read" and len(cmd.args) > 1:
            try:
                idx = int(cmd.args[1]) - 1
                messages = self._bbs_handler.get_messages(cmd.sender_id)
                if 0 <= idx < len(messages):
                    msg = messages[idx]
                    self._bbs_handler.mark_read(cmd.sender_id, idx)
                    return CommandResponse(
                        text=f"From: {msg['from']}\nTime: {msg['timestamp']}\n\n{msg['message']}"
                    )
                return CommandResponse(text="Message not found")
            except ValueError:
                return CommandResponse(text="Usage: !bbs read <number>")

        elif subcommand == "post" and len(cmd.args) > 1:
            message_text = " ".join(cmd.args[1:])
            # Post to public board (broadcast)
            self._bbs_handler.post_message(cmd.sender_id, "public", message_text)
            return CommandResponse(text="Message posted to BBS")

        elif subcommand == "delete" and len(cmd.args) > 1:
            if not cmd.is_admin:
                return CommandResponse(text="Admin permission required to delete")
            return CommandResponse(text="Message deleted (if existed)")

        return CommandResponse(text="Unknown BBS command. Try !bbs for help")

    def _handle_mail(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle mail/private message command."""
        if not cmd.args:
            unread = self._bbs_handler.get_unread_count(cmd.sender_id)
            return CommandResponse(
                text=f"Mail: {unread} unread message(s)\n"
                     "Commands:\n"
                     "!mail check - Check inbox\n"
                     "!mail send <node> <msg> - Send private message\n"
                     "!mail read <id> - Read message"
            )

        subcommand = cmd.args[0].lower()

        if subcommand == "check":
            messages = self._bbs_handler.get_messages(cmd.sender_id, unread_only=True)
            if not messages:
                return CommandResponse(text="No new mail")
            return CommandResponse(
                text=f"You have {len(messages)} unread message(s). Use !mail read <id> to read."
            )

        elif subcommand == "send" and len(cmd.args) > 2:
            recipient = cmd.args[1]
            message_text = " ".join(cmd.args[2:])
            self._bbs_handler.post_message(cmd.sender_id, recipient, message_text)
            return CommandResponse(text=f"Mail sent to {recipient}")

        elif subcommand == "read" and len(cmd.args) > 1:
            try:
                idx = int(cmd.args[1]) - 1
                messages = self._bbs_handler.get_messages(cmd.sender_id)
                if 0 <= idx < len(messages):
                    msg = messages[idx]
                    self._bbs_handler.mark_read(cmd.sender_id, idx)
                    return CommandResponse(
                        text=f"From: {msg['from']}\n{msg['message']}",
                        is_private=True
                    )
                return CommandResponse(text="Message not found")
            except ValueError:
                return CommandResponse(text="Usage: !mail read <number>")

        return CommandResponse(text="Unknown mail command. Try !mail for help")

    def _handle_game(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle game command."""
        if not cmd.args:
            active = self._game_handler.get_active_games()
            if cmd.sender_id in active:
                return CommandResponse(
                    text=f"Active game: {active[cmd.sender_id]}\n"
                         "Type !game quit to exit\n"
                         "Or continue playing..."
                )
            return CommandResponse(
                text="Available Games:\n"
                     "!game dopewars - Trade simulation\n"
                     "!game lemonade - Business sim\n"
                     "!game blackjack - Card game\n"
                     "!game quiz - Trivia\n"
                     "!game <name> - Start a game"
            )

        subcommand = cmd.args[0].lower()

        if subcommand == "quit":
            return CommandResponse(text=self._game_handler.end_game(cmd.sender_id))

        if subcommand in GameHandler.GAMES:
            return CommandResponse(text=self._game_handler.start_game(cmd.sender_id, subcommand))

        # If in active game, forward input
        active = self._game_handler.get_active_games()
        if cmd.sender_id in active:
            return CommandResponse(
                text=self._game_handler.process_input(cmd.sender_id, " ".join(cmd.args))
            )

        return CommandResponse(text=f"Unknown game: {subcommand}. Try !game for list")

    def _handle_admin(self, cmd: ParsedCommand) -> CommandResponse:
        """Handle admin command (requires admin privileges)."""
        if not cmd.is_admin:
            return CommandResponse(text="Admin permission required", is_private=True)

        if not cmd.args:
            return CommandResponse(
                text="Admin Commands:\n"
                     "!admin status - System status\n"
                     "!admin nodes - Node summary\n"
                     "!admin broadcast <msg> - Send to all\n"
                     "!admin mute <node> - Mute node\n"
                     "!admin unmute <node> - Unmute node\n"
                     "!admin reboot - Reboot bot (careful!)"
            )

        subcommand = cmd.args[0].lower()

        if subcommand == "status":
            return CommandResponse(
                text=f"Bot: {self.config.bot_name}\n"
                     f"Status: Online\n"
                     f"Admin nodes: {len(self.config.admin_nodes)}\n"
                     "Use TUI/web for detailed status"
            )

        elif subcommand == "nodes":
            return CommandResponse(
                text="Node summary available in TUI/web interface"
            )

        elif subcommand == "broadcast" and len(cmd.args) > 1:
            message = " ".join(cmd.args[1:])
            return CommandResponse(
                text=f"[BROADCAST] {message}",
                metadata={"broadcast": True, "message": message}
            )

        elif subcommand == "mute" and len(cmd.args) > 1:
            node = cmd.args[1]
            return CommandResponse(
                text=f"Node {node} muted",
                metadata={"action": "mute", "node": node}
            )

        elif subcommand == "unmute" and len(cmd.args) > 1:
            node = cmd.args[1]
            return CommandResponse(
                text=f"Node {node} unmuted",
                metadata={"action": "unmute", "node": node}
            )

        elif subcommand == "reboot":
            return CommandResponse(
                text="Reboot requested. Confirm with !admin reboot confirm",
                metadata={"action": "reboot_pending"}
            )

        return CommandResponse(text="Unknown admin command. Try !admin for help")


class BBSHandler:
    """
    Handler for BBS (Bulletin Board System) functionality.
    Implements store-and-forward messaging.
    """

    def __init__(self, config: Config):
        self.config = config
        self._messages: Dict[str, List[Dict]] = {}  # node_id -> messages

    def post_message(self, from_node: str, to_node: str, message: str) -> bool:
        """Post a message to a node's mailbox."""
        if to_node not in self._messages:
            self._messages[to_node] = []

        self._messages[to_node].append({
            "from": from_node,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False
        })
        return True

    def get_messages(self, node_id: str, unread_only: bool = False) -> List[Dict]:
        """Get messages for a node."""
        messages = self._messages.get(node_id, [])
        if unread_only:
            return [m for m in messages if not m["read"]]
        return messages

    def mark_read(self, node_id: str, index: int) -> bool:
        """Mark a message as read."""
        messages = self._messages.get(node_id, [])
        if 0 <= index < len(messages):
            messages[index]["read"] = True
            return True
        return False

    def get_unread_count(self, node_id: str) -> int:
        """Get unread message count for a node."""
        return len([m for m in self._messages.get(node_id, []) if not m["read"]])


class GameHandler:
    """
    Handler for game functionality.
    Supports DopeWars, Lemonade Stand, BlackJack, etc.
    """

    GAMES = ["dopewars", "lemonade", "blackjack", "poker", "quiz"]

    def __init__(self, config: Config):
        self.config = config
        self._sessions: Dict[str, Dict] = {}  # node_id -> game session

    def start_game(self, node_id: str, game_name: str) -> str:
        """Start a new game session."""
        game_name = game_name.lower()
        if game_name not in self.GAMES:
            return f"Unknown game. Available: {', '.join(self.GAMES)}"

        self._sessions[node_id] = {
            "game": game_name,
            "state": "started",
            "data": {},
            "started": datetime.now(timezone.utc)
        }

        if game_name == "dopewars":
            return "Welcome to DopeWars! Type 'help' for commands."
        elif game_name == "lemonade":
            return "Welcome to Lemonade Stand! Day 1. What's your price per cup?"
        elif game_name == "blackjack":
            return "Welcome to BlackJack! Type 'deal' to start a hand."
        elif game_name == "quiz":
            return "Welcome to Quiz Mode! Type 'start' to begin."

        return f"Starting {game_name}..."

    def end_game(self, node_id: str) -> str:
        """End a game session."""
        if node_id in self._sessions:
            del self._sessions[node_id]
            return "Game ended. Thanks for playing!"
        return "No active game session."

    def process_input(self, node_id: str, input_text: str) -> str:
        """Process game input."""
        if node_id not in self._sessions:
            return "No active game. Use !game <name> to start."

        session = self._sessions[node_id]
        # Game logic would go here
        return f"[{session['game']}] Processing: {input_text}"

    def get_active_games(self) -> Dict[str, str]:
        """Get all active game sessions."""
        return {node_id: session["game"] for node_id, session in self._sessions.items()}

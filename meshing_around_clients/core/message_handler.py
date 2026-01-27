"""
Message handler for Meshing-Around Clients.
Provides message processing, command handling, and game integration.
"""

import logging
import uuid
from datetime import datetime
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
            except Exception as e:
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
            except Exception as e:
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
            except Exception as e:
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
!info - Show node information
!stats - Show mesh statistics
!weather <loc> - Get weather
!bbs - Access bulletin board
!mail - Check messages
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
            "timestamp": datetime.now().isoformat(),
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
            "started": datetime.now()
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

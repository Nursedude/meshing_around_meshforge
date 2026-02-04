"""
CLI Utilities for MeshForge.

Provides:
- Terminal colors (ANSI codes)
- Formatted printing (headers, sections, status messages)
- User input handling (with validation)
- Progress indicators

Extracted from configure_bot.py for reusability across MeshForge CLI tools.
"""

import sys
import re
from typing import Any, Optional, TypeVar, Callable, List
from getpass import getpass


# =============================================================================
# ANSI Color Codes
# =============================================================================

class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    DIM = '\033[2m'

    @classmethod
    def disable(cls):
        """Disable all colors (for non-terminal output)."""
        cls.HEADER = ''
        cls.OKBLUE = ''
        cls.OKCYAN = ''
        cls.OKGREEN = ''
        cls.WARNING = ''
        cls.FAIL = ''
        cls.ENDC = ''
        cls.BOLD = ''
        cls.UNDERLINE = ''
        cls.DIM = ''


# Auto-disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


# =============================================================================
# Formatted Printing
# =============================================================================

def print_header(text: str, width: int = 70):
    """Print a formatted header with borders.

    Args:
        text: Header text
        width: Total width of header
    """
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * width}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text:^{width}}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * width}{Colors.ENDC}\n")


def print_section(text: str):
    """Print a section header with underline.

    Args:
        text: Section title
    """
    print(f"\n{Colors.OKCYAN}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.OKCYAN}{'-' * len(text)}{Colors.ENDC}")


def print_success(text: str):
    """Print a success message with checkmark.

    Args:
        text: Success message
    """
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")


def print_warning(text: str):
    """Print a warning message with warning icon.

    Args:
        text: Warning message
    """
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")


def print_error(text: str):
    """Print an error message with X icon.

    Args:
        text: Error message
    """
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")


def print_info(text: str):
    """Print an info message with info icon.

    Args:
        text: Info message
    """
    print(f"{Colors.OKBLUE}ℹ {text}{Colors.ENDC}")


def print_step(current: int, total: int, text: str):
    """Print a step progress indicator.

    Args:
        current: Current step number (1-indexed)
        total: Total number of steps
        text: Step description
    """
    print(f"{Colors.OKCYAN}[{current}/{total}] {text}{Colors.ENDC}")


def print_dim(text: str):
    """Print dimmed/subtle text.

    Args:
        text: Text to print
    """
    print(f"{Colors.DIM}{text}{Colors.ENDC}")


def print_list(items: List[str], numbered: bool = False, indent: int = 2):
    """Print a formatted list.

    Args:
        items: List items to print
        numbered: Whether to use numbers instead of bullets
        indent: Number of spaces to indent
    """
    prefix = " " * indent
    for i, item in enumerate(items, 1):
        if numbered:
            print(f"{prefix}{i}. {item}")
        else:
            print(f"{prefix}• {item}")


def print_table(headers: List[str], rows: List[List[str]], col_widths: Optional[List[int]] = None):
    """Print a simple ASCII table.

    Args:
        headers: Column headers
        rows: List of rows (each row is a list of column values)
        col_widths: Optional list of column widths
    """
    if col_widths is None:
        col_widths = []
        for i, header in enumerate(headers):
            max_width = len(header)
            for row in rows:
                if i < len(row):
                    max_width = max(max_width, len(str(row[i])))
            col_widths.append(max_width + 2)

    # Header
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * w for w in col_widths)

    print(f"{Colors.BOLD}{header_line}{Colors.ENDC}")
    print(separator)

    # Rows
    for row in rows:
        row_line = " | ".join(str(row[i] if i < len(row) else "").ljust(col_widths[i])
                             for i in range(len(headers)))
        print(row_line)


# =============================================================================
# User Input
# =============================================================================

T = TypeVar('T')


def get_input(
    prompt: str,
    default: str = "",
    input_type: type = str,
    password: bool = False,
    validator: Optional[Callable[[Any], bool]] = None,
    error_message: str = "Invalid input"
) -> Any:
    """Get user input with optional default value, type conversion, and validation.

    Args:
        prompt: Input prompt text
        default: Default value if user presses Enter
        input_type: Type to convert input to (str, int, float, bool)
        password: Whether to mask input
        validator: Optional validation function
        error_message: Message to show on validation failure

    Returns:
        User input converted to specified type
    """
    while True:
        # Build prompt with default
        if default:
            if password:
                full_prompt = f"{prompt} [****]: "
            else:
                full_prompt = f"{prompt} [{default}]: "
        else:
            full_prompt = f"{prompt}: "

        # Get input
        try:
            if password:
                value = getpass(full_prompt)
            else:
                value = input(full_prompt).strip()

            # Use default if empty
            if not value and default:
                value = str(default)

            # Type conversion
            if input_type == bool:
                value_lower = str(value).lower()
                if value_lower in ['true', 'yes', 'y', '1', 'on']:
                    result = True
                elif value_lower in ['false', 'no', 'n', '0', 'off']:
                    result = False
                else:
                    print_error("Please enter yes/no (y/n) or true/false")
                    continue
            elif input_type == int:
                result = int(value) if value else int(default) if default else 0
            elif input_type == float:
                result = float(value) if value else float(default) if default else 0.0
            else:
                result = value

            # Validation
            if validator and not validator(result):
                print_error(error_message)
                continue

            return result

        except ValueError:
            print_error(f"Invalid input. Expected {input_type.__name__}")
        except KeyboardInterrupt:
            print("\n")
            raise


def get_yes_no(prompt: str, default: bool = False) -> bool:
    """Get yes/no input from user.

    Args:
        prompt: Question to ask
        default: Default value (True for yes, False for no)

    Returns:
        True for yes, False for no
    """
    default_str = "Y/n" if default else "y/N"
    response = get_input(f"{prompt} ({default_str})", "y" if default else "n")
    return response.lower() in ['y', 'yes', 'true', '1']


def get_choice(
    prompt: str,
    choices: List[str],
    default: Optional[int] = None
) -> int:
    """Get a choice from a list of options.

    Args:
        prompt: Prompt text
        choices: List of choice strings
        default: Default choice index (1-indexed)

    Returns:
        Selected choice index (0-indexed)
    """
    print(f"\n{prompt}")
    for i, choice in enumerate(choices, 1):
        if default == i:
            print(f"  {Colors.BOLD}{i}. {choice} (default){Colors.ENDC}")
        else:
            print(f"  {i}. {choice}")

    while True:
        default_str = str(default) if default else ""
        choice_str = get_input(f"Select (1-{len(choices)})", default_str)

        try:
            choice_num = int(choice_str)
            if 1 <= choice_num <= len(choices):
                return choice_num - 1  # Return 0-indexed
            print_error(f"Please enter a number between 1 and {len(choices)}")
        except ValueError:
            print_error("Please enter a valid number")


def get_list_input(
    prompt: str,
    default: Optional[List[str]] = None,
    separator: str = ","
) -> List[str]:
    """Get a comma-separated list of values.

    Args:
        prompt: Input prompt
        default: Default list values
        separator: Value separator (default comma)

    Returns:
        List of string values
    """
    default_str = separator.join(default) if default else ""
    value = get_input(prompt, default_str)

    if not value:
        return []

    return [item.strip() for item in value.split(separator) if item.strip()]


# =============================================================================
# Validation Functions
# =============================================================================

def validate_mac_address(mac: str) -> bool:
    """Validate BLE MAC address format.

    Args:
        mac: MAC address string

    Returns:
        True if valid format
    """
    pattern = r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$'
    return bool(re.match(pattern, mac))


def validate_ip_address(ip: str) -> bool:
    """Validate IPv4 address format.

    Args:
        ip: IP address string

    Returns:
        True if valid format
    """
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            num = int(part)
            if not 0 <= num <= 255:
                return False
        except ValueError:
            return False
    return True


def validate_port(port: int) -> bool:
    """Validate port number.

    Args:
        port: Port number

    Returns:
        True if valid port
    """
    return 1 <= port <= 65535


def validate_email(email: str) -> bool:
    """Basic email format validation.

    Args:
        email: Email address

    Returns:
        True if valid format
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_coordinates(lat: float, lon: float) -> bool:
    """Validate latitude and longitude values.

    Args:
        lat: Latitude (-90 to 90)
        lon: Longitude (-180 to 180)

    Returns:
        True if valid coordinates
    """
    return -90 <= lat <= 90 and -180 <= lon <= 180


def validate_serial_port(port: str) -> bool:
    """Validate that a serial port path looks valid.

    Args:
        port: Serial port path

    Returns:
        True if path looks like a serial port
    """
    import os
    # Check if it exists or at least starts with /dev/
    return os.path.exists(port) or port.startswith('/dev/')


# =============================================================================
# Progress Indicators
# =============================================================================

class ProgressBar:
    """Simple console progress bar."""

    def __init__(self, total: int, width: int = 40, prefix: str = "Progress"):
        """Initialize progress bar.

        Args:
            total: Total number of items
            width: Bar width in characters
            prefix: Text prefix before bar
        """
        self.total = total
        self.width = width
        self.prefix = prefix
        self.current = 0

    def update(self, current: Optional[int] = None, message: str = ""):
        """Update progress bar.

        Args:
            current: Current progress value (auto-increments if None)
            message: Optional status message
        """
        if current is not None:
            self.current = current
        else:
            self.current += 1

        percent = min(100, int(100 * self.current / self.total))
        filled = int(self.width * self.current / self.total)
        bar = '█' * filled + '░' * (self.width - filled)

        status = f" {message}" if message else ""
        print(f'\r{self.prefix}: |{bar}| {percent}%{status}', end='', flush=True)

        if self.current >= self.total:
            print()  # Newline when complete

    def finish(self, message: str = "Complete"):
        """Mark progress as complete.

        Args:
            message: Completion message
        """
        self.update(self.total, message)


class Spinner:
    """Simple console spinner for indeterminate progress."""

    FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def __init__(self, message: str = "Loading"):
        """Initialize spinner.

        Args:
            message: Text to display with spinner
        """
        self.message = message
        self.frame = 0
        self._running = False

    def spin(self):
        """Display next spinner frame."""
        frame_char = self.FRAMES[self.frame % len(self.FRAMES)]
        print(f'\r{frame_char} {self.message}...', end='', flush=True)
        self.frame += 1

    def stop(self, success: bool = True, message: str = ""):
        """Stop spinner and show result.

        Args:
            success: Whether operation succeeded
            message: Optional result message
        """
        result_char = '✓' if success else '✗'
        color = Colors.OKGREEN if success else Colors.FAIL
        final_msg = message or ("Done" if success else "Failed")
        print(f'\r{color}{result_char} {final_msg}{Colors.ENDC}')


# =============================================================================
# Menu System
# =============================================================================

class Menu:
    """Simple menu system for CLI applications."""

    def __init__(self, title: str, items: List[tuple]):
        """Initialize menu.

        Args:
            title: Menu title
            items: List of (label, handler) tuples. Handler can be a function
                   or another Menu for submenus.
        """
        self.title = title
        self.items = items

    def display(self) -> Optional[int]:
        """Display menu and get user selection.

        Returns:
            Selected item index (0-indexed) or None if cancelled
        """
        print_section(self.title)

        for i, (label, _) in enumerate(self.items, 1):
            print(f"  {i}. {label}")

        print(f"  0. Back/Exit")

        try:
            choice = get_input(f"Select (0-{len(self.items)})", "0")
            choice_num = int(choice)

            if choice_num == 0:
                return None
            elif 1 <= choice_num <= len(self.items):
                return choice_num - 1

            print_error(f"Invalid choice. Enter 0-{len(self.items)}")
            return self.display()

        except ValueError:
            print_error("Please enter a number")
            return self.display()
        except KeyboardInterrupt:
            return None

    def run(self):
        """Run menu loop until exit.

        Calls handlers for selected items. If handler is a Menu,
        recursively runs that submenu.
        """
        while True:
            choice = self.display()

            if choice is None:
                break

            label, handler = self.items[choice]

            if isinstance(handler, Menu):
                handler.run()
            elif callable(handler):
                try:
                    handler()
                except KeyboardInterrupt:
                    print()
                    continue

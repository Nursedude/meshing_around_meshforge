#!/usr/bin/env python3
"""
Meshing-Around Enhanced Configuration Tool
Interactive setup for the meshing-around Meshtastic bot with modern UI

Supports:
- Raspberry Pi OS Bookworm (Debian 12)
- Raspberry Pi OS Trixie (Debian 13)
- Standard Debian/Ubuntu systems

Features:
- Beautiful terminal UI with rich library
- Automatic system updates at startup
- Virtual environment setup for PEP 668 compliance
- Serial port detection and configuration
- raspi-config integration for Raspberry Pi
"""

import os
import sys
import subprocess
import shutil
import re
import time
import configparser
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from getpass import getpass

# Check for rich library and provide fallback - do NOT auto-install (PEP 668 compliance)
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
    from rich.tree import Tree
    from rich.text import Text
    from rich import box
    from rich.padding import Padding
    from rich.columns import Columns
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    # Rich not available, will use fallback basic output

# Initialize console
console = Console() if RICH_AVAILABLE else None

# Version info
VERSION = "0.5.0-beta"
SUPPORTED_OS = ["bookworm", "trixie", "forky", "sid", "noble", "jammy"]

# ============================================================================
# UI HELPER FUNCTIONS
# ============================================================================

def print_header(text: str):
    """Print a formatted header with rich styling"""
    if RICH_AVAILABLE:
        console.print()
        console.print(Panel(
            f"[bold cyan]{text}[/bold cyan]",
            border_style="cyan",
            box=box.DOUBLE,
            padding=(1, 2)
        ))
    else:
        print(f"\n{'='*70}\n{text:^70}\n{'='*70}\n")

def print_section(text: str):
    """Print a section header"""
    if RICH_AVAILABLE:
        console.print(f"\n[bold blue]╔══ {text} ══╗[/bold blue]")
    else:
        print(f"\n{text}\n{'-'*len(text)}")

def print_success(text: str):
    """Print success message"""
    if RICH_AVAILABLE:
        console.print(f"[green]✓[/green] {text}")
    else:
        print(f"✓ {text}")

def print_warning(text: str):
    """Print warning message"""
    if RICH_AVAILABLE:
        console.print(f"[yellow]⚠[/yellow] {text}")
    else:
        print(f"⚠ {text}")

def print_error(text: str):
    """Print error message"""
    if RICH_AVAILABLE:
        console.print(f"[red]✗[/red] {text}")
    else:
        print(f"✗ {text}")

def print_info(text: str):
    """Print info message"""
    if RICH_AVAILABLE:
        console.print(f"[cyan]ℹ[/cyan] {text}")
    else:
        print(f"ℹ {text}")

def print_step(current: int, total: int, text: str):
    """Print step progress"""
    if RICH_AVAILABLE:
        console.print(f"[cyan][[/cyan][bold]{current}/{total}[/bold][cyan]][/cyan] {text}")
    else:
        print(f"[{current}/{total}] {text}")

def create_menu_table(title: str, items: List[Tuple[str, str]], columns: int = 1) -> None:
    """Create a beautiful menu table"""
    if RICH_AVAILABLE:
        table = Table(show_header=False, box=box.ROUNDED, border_style="cyan", padding=(0, 2))

        if columns == 1:
            table.add_column("Option", style="cyan bold", width=4)
            table.add_column("Description", style="white")

            for num, desc in items:
                table.add_row(num, desc)
        else:
            # Multi-column layout
            items_per_col = (len(items) + columns - 1) // columns
            for col in range(columns):
                table.add_column("Option", style="cyan bold", width=4)
                table.add_column("Description", style="white")

            for row_idx in range(items_per_col):
                row_data = []
                for col_idx in range(columns):
                    item_idx = col_idx * items_per_col + row_idx
                    if item_idx < len(items):
                        num, desc = items[item_idx]
                        row_data.extend([num, desc])
                    else:
                        row_data.extend(["", ""])
                table.add_row(*row_data)

        console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="blue"))
    else:
        print(f"\n{title}")
        for num, desc in items:
            print(f"  {num}. {desc}")

def get_input_rich(prompt: str, default: str = "", input_type: type = str,
                   password: bool = False, choices: List[str] = None) -> Any:
    """Get user input with rich prompts"""
    if not RICH_AVAILABLE:
        return get_input_basic(prompt, default, input_type, password)

    try:
        if password:
            return Prompt.ask(f"[yellow]{prompt}[/yellow]", password=True, default=default or None)

        if input_type == bool:
            return Confirm.ask(f"[yellow]{prompt}[/yellow]", default=bool(default) if default else False)

        if input_type == int:
            return IntPrompt.ask(f"[yellow]{prompt}[/yellow]", default=int(default) if default else None)

        if input_type == float:
            return FloatPrompt.ask(f"[yellow]{prompt}[/yellow]", default=float(default) if default else None)

        if choices:
            return Prompt.ask(f"[yellow]{prompt}[/yellow]", choices=choices, default=default or choices[0] if choices else None)

        return Prompt.ask(f"[yellow]{prompt}[/yellow]", default=default or None)

    except (KeyboardInterrupt, EOFError):
        raise
    except (ValueError, TypeError, AttributeError):
        # Fallback for Rich prompt failures
        return get_input_basic(prompt, default, input_type, password)

def get_input_basic(prompt: str, default: str = "", input_type: type = str, password: bool = False) -> Any:
    """Basic input without rich (fallback)"""
    if default:
        full_prompt = f"{prompt} [{default}]: " if not password else f"{prompt} [****]: "
    else:
        full_prompt = f"{prompt}: "

    while True:
        try:
            if password:
                value = getpass(full_prompt)
            else:
                value = input(full_prompt).strip()

            if not value and default:
                value = str(default)

            if input_type == bool:
                value_lower = str(value).lower()
                if value_lower in ['true', 'yes', 'y', '1', 'on']:
                    return True
                elif value_lower in ['false', 'no', 'n', '0', 'off']:
                    return False
                else:
                    print("Please enter yes/no")
                    continue
            elif input_type == int:
                return int(value) if value else (int(default) if default else 0)
            elif input_type == float:
                return float(value) if value else (float(default) if default else 0.0)
            else:
                return value
        except ValueError:
            print(f"Invalid input. Expected {input_type.__name__}")

def get_input(prompt: str, default: str = "", input_type: type = str,
              password: bool = False, choices: List[str] = None) -> Any:
    """Smart input function that uses rich if available"""
    if RICH_AVAILABLE:
        return get_input_rich(prompt, default, input_type, password, choices)
    return get_input_basic(prompt, default, input_type, password)

def get_yes_no(prompt: str, default: bool = False) -> bool:
    """Get yes/no input from user"""
    if RICH_AVAILABLE:
        return Confirm.ask(f"[yellow]{prompt}[/yellow]", default=default)
    else:
        default_str = "Y/n" if default else "y/N"
        response = get_input_basic(f"{prompt} ({default_str})", "y" if default else "n")
        return response.lower() in ['y', 'yes', 'true', '1']

# ============================================================================
# UTILITY FUNCTIONS FROM ORIGINAL (with bug fixes applied)
# ============================================================================

def run_command(cmd: List[str], desc: str = "", capture: bool = False,
                sudo: bool = False) -> Tuple[int, str, str]:
    """Run a shell command with optional sudo"""
    if sudo:
        cmd = ['sudo'] + cmd

    if desc:
        print_info(f"{desc}...")

    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, timeout=600)
        stdout = result.stdout if capture else ""
        stderr = result.stderr if capture else ""
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        print_error(f"Command timed out")
        return -1, "", "Timeout"
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        return -1, "", "Command not found"
    except (PermissionError, OSError) as e:
        print_error(f"Command failed: {e}")
        return -1, "", str(e)

def find_meshing_around() -> Optional[Path]:
    """Find the meshing-around installation directory"""
    common_paths = [
        Path.home() / "meshing-around",
        Path.home() / "mesh-bot",
        Path("/opt/meshing-around"),
        Path("/opt/mesh-bot"),
        Path.cwd().parent / "meshing-around",
        Path.cwd() / "meshing-around",
    ]

    for path in common_paths:
        if path.exists() and (path / "mesh_bot.py").exists():
            return path

    try:
        result = subprocess.run(
            ['find', str(Path.home()), '-name', 'mesh_bot.py', '-type', 'f'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            bot_path = Path(result.stdout.strip().split('\n')[0]).parent
            return bot_path
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    return None

def is_raspberry_pi() -> bool:
    """Detect if running on a Raspberry Pi"""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo:
                return True
    except (FileNotFoundError, PermissionError, IOError):
        pass

    if os.path.exists('/sys/firmware/devicetree/base/model'):
        try:
            with open('/sys/firmware/devicetree/base/model', 'r') as f:
                if 'Raspberry Pi' in f.read():
                    return True
        except (FileNotFoundError, PermissionError, IOError):
            pass

    return False

def get_pi_model() -> str:
    """Get Raspberry Pi model information"""
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as f:
            return f.read().strip().rstrip('\x00')
    except (FileNotFoundError, PermissionError, IOError):
        return "Unknown"

def get_os_info() -> Tuple[str, str]:
    """Get OS name and version (codename)"""
    os_name = "Unknown"
    os_version = "Unknown"

    try:
        with open('/etc/os-release', 'r') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    os_name = line.split('=')[1].strip().strip('"')
                elif line.startswith('VERSION_CODENAME='):
                    os_version = line.split('=')[1].strip().strip('"')
    except (FileNotFoundError, PermissionError, IOError):
        pass

    return os_name, os_version

def is_bookworm_or_newer() -> bool:
    """Check if running Debian Bookworm (12) or newer"""
    _, codename = get_os_info()
    new_codenames = ['bookworm', 'trixie', 'forky', 'sid']
    return codename.lower() in new_codenames

def check_pep668_environment() -> bool:
    """Check if PEP 668 externally managed environment is in effect"""
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    managed_file = Path(f"/usr/lib/python{python_version}/EXTERNALLY-MANAGED")
    return managed_file.exists()

def get_serial_ports() -> List[str]:
    """Get available serial ports, including Raspberry Pi specific ones"""
    ports = []

    usb_patterns = ['/dev/ttyUSB*', '/dev/ttyACM*']
    pi_ports = ['/dev/ttyAMA0', '/dev/serial0', '/dev/serial1', '/dev/ttyS0']

    for pattern in usb_patterns:
        ret, stdout, _ = run_command(['ls', pattern], capture=True)
        if ret == 0 and stdout.strip():
            ports.extend(stdout.strip().split('\n'))

    for port in pi_ports:
        if os.path.exists(port):
            ports.append(port)

    return list(set(ports))

def check_user_groups() -> Tuple[bool, bool]:
    """Check if user is in dialout and gpio groups"""
    try:
        groups = subprocess.run(['groups'], capture_output=True, text=True).stdout
        in_dialout = 'dialout' in groups
        in_gpio = 'gpio' in groups
        return in_dialout, in_gpio
    except (subprocess.SubprocessError, FileNotFoundError, Exception):
        return False, False

# ============================================================================
# IMPROVED SYSTEM INFO DISPLAY
# ============================================================================

def show_system_info_rich():
    """Display system information in a beautiful table"""
    print_section("System Information")

    # Create system info table
    table = Table(box=box.ROUNDED, show_header=False, border_style="cyan")
    table.add_column("Property", style="yellow bold", width=25)
    table.add_column("Value", style="white")

    # Platform
    if is_raspberry_pi():
        pi_model = get_pi_model()
        table.add_row("🥧 Platform", f"[green]{pi_model}[/green]")
    else:
        table.add_row("💻 Platform", "Standard Linux")

    # OS
    os_name, os_codename = get_os_info()
    table.add_row("🐧 OS", f"{os_name}")
    table.add_row("📦 Codename", f"{os_codename}")

    # Python
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_status = "✓" if sys.version_info >= (3, 9) else "⚠"
    table.add_row("🐍 Python", f"{py_status} {py_version}")

    # PEP 668
    if check_pep668_environment():
        table.add_row("📋 PEP 668", "[yellow]Active (use venv)[/yellow]")
    else:
        table.add_row("📋 PEP 668", "[green]Not active[/green]")

    console.print(table)

    # Serial ports
    print_section("Serial Ports")
    ports = get_serial_ports()

    if ports:
        port_table = Table(box=box.SIMPLE, show_header=False)
        port_table.add_column("Port", style="cyan")
        port_table.add_column("Status", style="green")

        for port in ports:
            accessible = "✓ Ready" if os.access(port, os.R_OK | os.W_OK) else "⚠ No permission"
            port_table.add_row(port, accessible)

        console.print(port_table)
    else:
        console.print("[yellow]No serial ports detected[/yellow]")

    # Meshing-around status
    print_section("Meshing-Around Status")
    meshing_path = find_meshing_around()

    status_table = Table(box=box.SIMPLE, show_header=False)
    status_table.add_column(width=20)
    status_table.add_column()

    if meshing_path:
        status_table.add_row("📁 Installation", f"[green]✓ {meshing_path}[/green]")

        if (meshing_path / "config.ini").exists():
            status_table.add_row("⚙️  Config", "[green]✓ Found[/green]")
        else:
            status_table.add_row("⚙️  Config", "[yellow]⚠ Not found[/yellow]")
    else:
        status_table.add_row("📁 Installation", "[red]✗ Not found[/red]")

    console.print(status_table)

def show_system_info():
    """Display system info (uses rich if available)"""
    if RICH_AVAILABLE:
        show_system_info_rich()
    else:
        print("\n" + "="*50)
        print("SYSTEM INFORMATION")
        print("="*50)

        if is_raspberry_pi():
            print(f"\nPlatform: {get_pi_model()}")
        else:
            print("\nPlatform: Standard Linux")

        os_name, os_codename = get_os_info()
        print(f"OS: {os_name} ({os_codename})")
        print(f"Python: {sys.version.split()[0]}")

        print("\nSerial Ports:")
        for port in get_serial_ports():
            print(f"  - {port}")

        meshing_path = find_meshing_around()
        if meshing_path:
            print(f"\nMeshing-around: {meshing_path}")

# ============================================================================
# CONFIGURATION FUNCTIONS (Enhanced with Rich UI)
# ============================================================================

def configure_interface(config: configparser.ConfigParser):
    """Configure interface settings with improved UI"""
    print_section("Interface Configuration")

    items = [
        ("1", "🔌 Serial (recommended)"),
        ("2", "🌐 TCP"),
        ("3", "📡 BLE")
    ]

    if RICH_AVAILABLE:
        create_menu_table("Connection Types", items, columns=3)
    else:
        print("\nConnection types:")
        for num, desc in items:
            print(f"  {num}. {desc}")

    conn_type = get_input("Select connection type", "1", choices=["1", "2", "3"])
    type_map = {"1": "serial", "2": "tcp", "3": "ble"}
    conn_type_str = type_map.get(conn_type, "serial")

    config['interface']['type'] = conn_type_str

    if conn_type_str == "serial":
        use_auto = get_yes_no("Use auto-detect for serial port?", True)
        if not use_auto:
            ports = get_serial_ports()
            if ports:
                print_info(f"Available ports: {', '.join(ports)}")
            port = get_input("Enter serial port", "/dev/ttyUSB0")
            config['interface']['port'] = port
    elif conn_type_str == "tcp":
        hostname = get_input("Enter TCP hostname/IP", "192.168.1.100")
        config['interface']['hostname'] = hostname
    elif conn_type_str == "ble":
        mac = get_input("Enter BLE MAC address", "AA:BB:CC:DD:EE:FF")
        config['interface']['mac'] = mac

    print_success(f"Interface configured: {conn_type_str}")

def configure_general(config: configparser.ConfigParser):
    """Configure general settings"""
    print_section("General Settings")

    bot_name = get_input("Bot name", "MeshBot")
    config['general']['bot_name'] = bot_name

    if get_yes_no("Configure admin nodes?", False):
        admin_list = get_input("Admin node numbers (comma-separated)", "")
        config['general']['bbs_admin_list'] = admin_list

    if get_yes_no("Configure favorite nodes?", False):
        fav_list = get_input("Favorite node numbers (comma-separated)", "")
        config['general']['favoriteNodeList'] = fav_list

    print_success("General settings configured")

def configure_emergency_alerts(config: configparser.ConfigParser):
    """Configure emergency alert settings"""
    print_section("Emergency Alert Configuration")

    if not get_yes_no("Enable emergency keyword detection?", True):
        config['emergencyHandler']['enabled'] = 'False'
        return

    config['emergencyHandler']['enabled'] = 'True'

    if RICH_AVAILABLE:
        console.print("\n[cyan]Default keywords:[/cyan] emergency, 911, 112, 999, police, fire, ambulance")

    if get_yes_no("Use default emergency keywords?", True):
        config['emergencyHandler']['emergency_keywords'] = 'emergency,911,112,999,police,fire,ambulance,rescue,help,sos,mayday'
    else:
        keywords = get_input("Enter emergency keywords (comma-separated)", "")
        config['emergencyHandler']['emergency_keywords'] = keywords

    channel = get_input("Alert channel number", "2", int)
    config['emergencyHandler']['alert_channel'] = str(channel)

    print_success("Emergency alerts configured")

def load_config(config_file: str) -> configparser.ConfigParser:
    """Load existing config or create new one"""
    config = configparser.ConfigParser()

    if os.path.exists(config_file):
        print_success(f"Loading existing config from {config_file}")
        config.read(config_file)
    else:
        print_warning(f"No existing config found, creating new configuration")
        sections = [
            'interface', 'general', 'emergencyHandler', 'proximityAlert',
            'altitudeAlert', 'weatherAlert', 'batteryAlert', 'noisyNodeAlert',
            'newNodeAlert', 'alertGlobal', 'smtp', 'sms'
        ]
        for section in sections:
            if not config.has_section(section):
                config.add_section(section)

    return config

def save_config(config: configparser.ConfigParser, config_file: str):
    """Save configuration to file"""
    try:
        with open(config_file, 'w') as f:
            config.write(f)
        print_success(f"Configuration saved to {config_file}")
    except (IOError, OSError, PermissionError) as e:
        print_error(f"Failed to save config: {e}")

# ============================================================================
# MAIN MENU AND WIZARDS
# ============================================================================

def startup_system_check() -> bool:
    """Run system checks with beautiful display"""
    if RICH_AVAILABLE:
        console.clear()

        # Animated header
        header_text = Text()
        header_text.append("⚡ ", style="yellow bold")
        header_text.append("Meshing-Around Enhanced Configuration Tool", style="bold cyan")
        header_text.append(" ⚡", style="yellow bold")

        console.print()
        console.print(Panel(
            header_text,
            subtitle=f"[dim]v{VERSION}[/dim]",
            border_style="cyan",
            box=box.DOUBLE
        ))
        console.print()
    else:
        print(f"\n{'='*70}")
        print(f"Meshing-Around Enhanced Configuration Tool v{VERSION}".center(70))
        print(f"{'='*70}\n")

    # Show system info
    show_system_info()

    # Offer system update
    print_section("System Update")
    print_info("It's recommended to update your system before proceeding")

    if get_yes_no("Run system update now (apt update && apt upgrade)?", False):
        if RICH_AVAILABLE:
            with console.status("[cyan]Updating system...", spinner="dots"):
                run_command(['apt', 'update'], sudo=True, capture=True)
                run_command(['apt', 'upgrade', '-y'], sudo=True, capture=True)
                run_command(['apt', 'autoremove', '-y'], sudo=True, capture=True)
            print_success("System updated successfully!")
        else:
            run_command(['apt', 'update'], sudo=True, desc="Updating")
            run_command(['apt', 'upgrade', '-y'], sudo=True, desc="Upgrading")

    return True

def quick_setup():
    """Quick setup wizard"""
    print_header("Quick Setup Wizard")

    if RICH_AVAILABLE:
        steps_panel = Panel(
            "[cyan]This wizard will:[/cyan]\n\n"
            "  1. ✓ Check system requirements\n"
            "  2. ✓ Create basic configuration\n"
            "  3. ✓ Configure interface and alerts",
            title="[bold]Setup Steps[/bold]",
            border_style="green"
        )
        console.print(steps_panel)
        console.print()

    if not get_yes_no("Continue with quick setup?", True):
        return None

    # Create basic config
    config = configparser.ConfigParser()

    sections = [
        'interface', 'general', 'emergencyHandler', 'proximityAlert',
        'altitudeAlert', 'weatherAlert', 'batteryAlert', 'noisyNodeAlert',
        'newNodeAlert', 'alertGlobal', 'smtp', 'sms'
    ]
    for section in sections:
        config.add_section(section)

    # Configure basic settings
    configure_interface(config)
    configure_general(config)
    configure_emergency_alerts(config)

    # Set defaults for other sections
    config['emergencyHandler']['alert_channel'] = '2'
    config['newNodeAlert']['enabled'] = 'True'
    config['newNodeAlert']['welcome_message'] = 'Welcome to the mesh!'
    config['alertGlobal']['global_enabled'] = 'True'

    print_success("Quick setup complete!")
    return config

def main_menu():
    """Main menu with beautiful UI"""
    startup_system_check()

    print_section("Main Menu")

    menu_items = [
        ("1", "🚀 Quick Setup (recommended)"),
        ("2", "⚙️  Advanced Configuration"),
        ("3", "📊 Show System Info"),
        ("4", "🚪 Exit")
    ]

    if RICH_AVAILABLE:
        create_menu_table("Start Menu", menu_items, columns=2)
    else:
        for num, desc in menu_items:
            print(f"  {num}. {desc}")

    choice = get_input("Select option", "1", choices=["1", "2", "3", "4"])

    if choice == "1":
        config = quick_setup()
        if config:
            config_file = get_input("Save config to", "config.ini")
            save_config(config, config_file)
    elif choice == "2":
        advanced_configuration()
    elif choice == "3":
        show_system_info()
        if get_yes_no("\nReturn to menu?", True):
            main_menu()
    elif choice == "4":
        print_success("Goodbye!")
        return

def advanced_configuration():
    """Advanced configuration menu"""
    print_header("Advanced Configuration")

    config_file = get_input("Config file path", "config.ini")
    config = load_config(config_file)

    while True:
        menu_items = [
            ("1", "⚙️  Interface Settings"),
            ("2", "👤 General Settings"),
            ("3", "🚨 Emergency Alerts"),
            ("4", "💾 Save and Exit"),
            ("5", "🚪 Exit without Saving")
        ]

        if RICH_AVAILABLE:
            create_menu_table("Configuration Menu", menu_items)
        else:
            for num, desc in menu_items:
                print(f"  {num}. {desc}")

        choice = get_input("Select option", "4", choices=["1", "2", "3", "4", "5"])

        if choice == "1":
            configure_interface(config)
        elif choice == "2":
            configure_general(config)
        elif choice == "3":
            configure_emergency_alerts(config)
        elif choice == "4":
            save_config(config, config_file)
            print_success("Configuration complete!")
            break
        elif choice == "5":
            if get_yes_no("Exit without saving?", False):
                break

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        if not RICH_AVAILABLE:
            print("Note: Install 'rich' library for better UI: pip install rich")
        main_menu()
    except KeyboardInterrupt:
        if RICH_AVAILABLE:
            console.print("\n[yellow]⚠ Configuration cancelled by user[/yellow]")
        else:
            print("\nConfiguration cancelled by user")
        sys.exit(0)
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"\n[red]✗ An error occurred: {e}[/red]")
        else:
            print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

"""
Unit tests for cli_utils module.

Tests:
- Color codes
- Validation functions
- Progress indicators
"""

import pytest
import sys
from io import StringIO

from meshing_around_clients.core.cli_utils import (
    Colors, validate_mac_address, validate_ip_address, validate_port,
    validate_email, validate_coordinates, validate_serial_port,
    ProgressBar, Spinner, print_success, print_error, print_warning,
    print_info, print_section, print_header
)


class TestColors:
    """Test color code class."""

    def test_colors_defined(self):
        """Verify all color codes are defined."""
        assert hasattr(Colors, 'HEADER')
        assert hasattr(Colors, 'OKBLUE')
        assert hasattr(Colors, 'OKCYAN')
        assert hasattr(Colors, 'OKGREEN')
        assert hasattr(Colors, 'WARNING')
        assert hasattr(Colors, 'FAIL')
        assert hasattr(Colors, 'ENDC')
        assert hasattr(Colors, 'BOLD')

    def test_colors_are_strings(self):
        """Verify colors are strings."""
        assert isinstance(Colors.HEADER, str)
        assert isinstance(Colors.OKGREEN, str)
        assert isinstance(Colors.FAIL, str)


class TestValidation:
    """Test validation functions."""

    def test_validate_mac_address_valid(self):
        """Test valid MAC addresses."""
        assert validate_mac_address("AA:BB:CC:DD:EE:FF")
        assert validate_mac_address("00:11:22:33:44:55")
        assert validate_mac_address("aa:bb:cc:dd:ee:ff")

    def test_validate_mac_address_invalid(self):
        """Test invalid MAC addresses."""
        assert not validate_mac_address("")
        assert not validate_mac_address("AA:BB:CC:DD:EE")
        assert not validate_mac_address("AA:BB:CC:DD:EE:FF:GG")
        assert not validate_mac_address("AA-BB-CC-DD-EE-FF")
        assert not validate_mac_address("AABBCCDDEEFF")
        assert not validate_mac_address("GG:HH:II:JJ:KK:LL")

    def test_validate_ip_address_valid(self):
        """Test valid IP addresses."""
        assert validate_ip_address("192.168.1.1")
        assert validate_ip_address("10.0.0.1")
        assert validate_ip_address("255.255.255.255")
        assert validate_ip_address("0.0.0.0")

    def test_validate_ip_address_invalid(self):
        """Test invalid IP addresses."""
        assert not validate_ip_address("")
        assert not validate_ip_address("192.168.1")
        assert not validate_ip_address("192.168.1.256")
        assert not validate_ip_address("192.168.1.1.1")
        assert not validate_ip_address("abc.def.ghi.jkl")
        assert not validate_ip_address("192.168.1.-1")

    def test_validate_port_valid(self):
        """Test valid port numbers."""
        assert validate_port(1)
        assert validate_port(80)
        assert validate_port(443)
        assert validate_port(8080)
        assert validate_port(65535)

    def test_validate_port_invalid(self):
        """Test invalid port numbers."""
        assert not validate_port(0)
        assert not validate_port(-1)
        assert not validate_port(65536)
        assert not validate_port(100000)

    def test_validate_email_valid(self):
        """Test valid email addresses."""
        assert validate_email("test@example.com")
        assert validate_email("user.name@domain.org")
        assert validate_email("user+tag@example.co.uk")

    def test_validate_email_invalid(self):
        """Test invalid email addresses."""
        assert not validate_email("")
        assert not validate_email("test")
        assert not validate_email("test@")
        assert not validate_email("@example.com")
        assert not validate_email("test@.com")

    def test_validate_coordinates_valid(self):
        """Test valid coordinates."""
        assert validate_coordinates(0, 0)
        assert validate_coordinates(45.0, -93.0)
        assert validate_coordinates(-90, -180)
        assert validate_coordinates(90, 180)

    def test_validate_coordinates_invalid(self):
        """Test invalid coordinates."""
        assert not validate_coordinates(91, 0)
        assert not validate_coordinates(-91, 0)
        assert not validate_coordinates(0, 181)
        assert not validate_coordinates(0, -181)


class TestProgressIndicators:
    """Test progress bar and spinner."""

    def test_progress_bar_creation(self):
        """Test progress bar can be created."""
        pb = ProgressBar(total=100, width=40, prefix="Test")
        assert pb.total == 100
        assert pb.width == 40
        assert pb.current == 0

    def test_progress_bar_update(self):
        """Test progress bar updates."""
        pb = ProgressBar(total=10)
        pb.update(5)
        assert pb.current == 5

        pb.update()
        assert pb.current == 6

    def test_spinner_creation(self):
        """Test spinner can be created."""
        spinner = Spinner(message="Loading")
        assert spinner.message == "Loading"
        assert spinner.frame == 0

    def test_spinner_spin(self):
        """Test spinner frame advances."""
        spinner = Spinner()
        initial_frame = spinner.frame
        spinner.spin()
        assert spinner.frame == initial_frame + 1


class TestPrintFunctions:
    """Test print helper functions."""

    def test_print_success(self, capsys):
        """Test print_success outputs correctly."""
        print_success("Test message")
        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_print_error(self, capsys):
        """Test print_error outputs correctly."""
        print_error("Error message")
        captured = capsys.readouterr()
        assert "Error message" in captured.out

    def test_print_warning(self, capsys):
        """Test print_warning outputs correctly."""
        print_warning("Warning message")
        captured = capsys.readouterr()
        assert "Warning message" in captured.out

    def test_print_info(self, capsys):
        """Test print_info outputs correctly."""
        print_info("Info message")
        captured = capsys.readouterr()
        assert "Info message" in captured.out

    def test_print_section(self, capsys):
        """Test print_section outputs correctly."""
        print_section("Section Title")
        captured = capsys.readouterr()
        assert "Section Title" in captured.out

    def test_print_header(self, capsys):
        """Test print_header outputs correctly."""
        print_header("Header Title")
        captured = capsys.readouterr()
        assert "Header Title" in captured.out

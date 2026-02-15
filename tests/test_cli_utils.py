"""
Unit tests for cli_utils module.

Tests validation functions and progress indicators.
Removed: TestColors (attribute checks), TestPrintFunctions (stdout capture).
"""

import pytest

from meshing_around_clients.setup.cli_utils import (
    validate_mac_address, validate_ip_address, validate_port,
    validate_email, validate_coordinates, validate_serial_port,
    ProgressBar, Spinner
)


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

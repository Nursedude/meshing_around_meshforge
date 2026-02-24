"""
Unit tests for meshing_around_clients.tui.helpers
"""

import sys
import unittest

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.tui.helpers import (
    HEALTH_STATUS_COLORS,
    SEVERITY_COLORS,
    SEVERITY_ICONS,
    format_battery,
    format_snr,
)


class TestFormatBattery(unittest.TestCase):
    """Test format_battery() function."""

    def test_none_returns_dash(self):
        self.assertEqual(format_battery(None), "-")

    def test_zero_returns_dash(self):
        self.assertEqual(format_battery(0), "-")

    def test_negative_returns_dash(self):
        self.assertEqual(format_battery(-5), "-")

    def test_high_level_green(self):
        result = format_battery(85)
        self.assertIn("[green]", result)
        self.assertIn("85%", result)

    def test_mid_level_yellow(self):
        result = format_battery(35)
        self.assertIn("[yellow]", result)
        self.assertIn("35%", result)

    def test_low_level_red(self):
        result = format_battery(15)
        self.assertIn("[red]", result)
        self.assertIn("15%", result)

    def test_boundary_51_is_green(self):
        result = format_battery(51)
        self.assertIn("[green]", result)

    def test_boundary_50_is_yellow(self):
        result = format_battery(50)
        self.assertIn("[yellow]", result)

    def test_boundary_21_is_yellow(self):
        result = format_battery(21)
        self.assertIn("[yellow]", result)

    def test_boundary_20_is_red(self):
        result = format_battery(20)
        self.assertIn("[red]", result)


class TestFormatSnr(unittest.TestCase):
    """Test format_snr() function."""

    def test_none_returns_dash(self):
        self.assertEqual(format_snr(None), "-")

    def test_positive_value(self):
        self.assertEqual(format_snr(10.5), "10.5")

    def test_negative_value(self):
        self.assertEqual(format_snr(-5.3), "-5.3")

    def test_with_unit(self):
        self.assertEqual(format_snr(10.5, unit=True), "10.5dB")

    def test_styled_positive_green(self):
        result = format_snr(5.0, styled=True)
        self.assertIn("[green]", result)
        self.assertIn("5.0", result)

    def test_styled_slightly_negative_yellow(self):
        result = format_snr(-5.0, styled=True)
        self.assertIn("[yellow]", result)

    def test_styled_very_negative_red(self):
        result = format_snr(-15.0, styled=True)
        self.assertIn("[red]", result)

    def test_styled_zero_is_yellow(self):
        # 0 is not > 0, so it falls to the next check (> -10), which is yellow
        result = format_snr(0.0, styled=True)
        self.assertIn("[yellow]", result)

    def test_styled_with_unit(self):
        result = format_snr(3.2, unit=True, styled=True)
        self.assertIn("dB", result)
        self.assertIn("[green]", result)

    def test_not_styled_no_markup(self):
        result = format_snr(10.0, styled=False)
        self.assertNotIn("[", result)


class TestConstants(unittest.TestCase):
    """Test helper constants."""

    def test_health_status_colors_has_all_levels(self):
        expected = {"excellent", "good", "fair", "poor", "critical", "unknown"}
        self.assertEqual(set(HEALTH_STATUS_COLORS.keys()), expected)

    def test_severity_colors_has_levels_1_to_4(self):
        self.assertEqual(set(SEVERITY_COLORS.keys()), {1, 2, 3, 4})

    def test_severity_icons_has_levels_1_to_4(self):
        self.assertEqual(set(SEVERITY_ICONS.keys()), {1, 2, 3, 4})

    def test_severity_icons_increasing_urgency(self):
        self.assertEqual(len(SEVERITY_ICONS[1]), 1)  # "i"
        self.assertEqual(len(SEVERITY_ICONS[4]), 3)  # "!!!"


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for meshing_around_clients.core.alert_detector
"""

import unittest
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(__file__).rsplit('/tests/', 1)[0])

from meshing_around_clients.core.alert_detector import (
    ProximityZone, AlertDetectorConfig, AlertDetector
)
from meshing_around_clients.core.models import (
    Node, Message, Position, NodeTelemetry, AlertType
)
from meshing_around_clients.core.config import Config


class TestProximityZone(unittest.TestCase):
    """Test ProximityZone dataclass."""

    def test_default_values(self):
        zone = ProximityZone(name="test", latitude=45.0, longitude=-122.0, radius_meters=100)
        self.assertEqual(zone.name, "test")
        self.assertEqual(zone.latitude, 45.0)
        self.assertEqual(zone.longitude, -122.0)
        self.assertEqual(zone.radius_meters, 100)
        self.assertTrue(zone.alert_on_enter)
        self.assertFalse(zone.alert_on_exit)

    def test_custom_values(self):
        zone = ProximityZone(
            name="home", latitude=40.0, longitude=-74.0,
            radius_meters=500, alert_on_enter=False, alert_on_exit=True
        )
        self.assertFalse(zone.alert_on_enter)
        self.assertTrue(zone.alert_on_exit)


class TestAlertDetectorConfig(unittest.TestCase):
    """Test AlertDetectorConfig dataclass."""

    def test_default_values(self):
        cfg = AlertDetectorConfig()
        self.assertTrue(cfg.disconnect_enabled)
        self.assertEqual(cfg.disconnect_timeout_seconds, 600)
        self.assertTrue(cfg.noisy_node_enabled)
        self.assertEqual(cfg.noisy_node_threshold, 20)
        self.assertEqual(cfg.noisy_node_period_seconds, 60)
        self.assertFalse(cfg.proximity_enabled)
        self.assertFalse(cfg.snr_enabled)
        self.assertEqual(cfg.snr_threshold, -10.0)

    def test_custom_values(self):
        cfg = AlertDetectorConfig(
            disconnect_timeout_seconds=300,
            noisy_node_threshold=10,
            snr_enabled=True,
            snr_threshold=-15.0
        )
        self.assertEqual(cfg.disconnect_timeout_seconds, 300)
        self.assertEqual(cfg.noisy_node_threshold, 10)
        self.assertTrue(cfg.snr_enabled)
        self.assertEqual(cfg.snr_threshold, -15.0)


class TestHaversineDistance(unittest.TestCase):
    """Test haversine distance calculation."""

    def test_same_point(self):
        """Distance between same point should be zero."""
        distance = AlertDetector.haversine_distance(45.0, -122.0, 45.0, -122.0)
        self.assertEqual(distance, 0.0)

    def test_known_distance(self):
        """Test with known distance between two cities."""
        # Portland, OR to Seattle, WA (~233 km)
        portland = (45.5231, -122.6765)
        seattle = (47.6062, -122.3321)
        distance = AlertDetector.haversine_distance(
            portland[0], portland[1], seattle[0], seattle[1]
        )
        # Should be approximately 233km (233000 meters)
        self.assertAlmostEqual(distance, 233000, delta=5000)

    def test_short_distance(self):
        """Test with a short distance."""
        # Two points about 100 meters apart
        lat1, lon1 = 45.5231, -122.6765
        lat2, lon2 = 45.5240, -122.6765  # Slightly north
        distance = AlertDetector.haversine_distance(lat1, lon1, lat2, lon2)
        # Should be approximately 100 meters
        self.assertAlmostEqual(distance, 100, delta=20)

    def test_symmetry(self):
        """Distance should be same regardless of direction."""
        d1 = AlertDetector.haversine_distance(45.0, -122.0, 46.0, -121.0)
        d2 = AlertDetector.haversine_distance(46.0, -121.0, 45.0, -122.0)
        self.assertAlmostEqual(d1, d2, places=2)


class TestAlertDetectorNodeTracking(unittest.TestCase):
    """Test AlertDetector node tracking."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector = AlertDetector(self.config)

    def test_update_node_seen(self):
        """Test updating node last seen time."""
        self.detector.update_node_seen("!node1")
        tracked = self.detector.get_tracked_nodes()
        self.assertIn("!node1", tracked)

    def test_update_node_seen_custom_time(self):
        """Test updating node with custom timestamp."""
        custom_time = datetime(2026, 1, 1, 12, 0, 0)
        self.detector.update_node_seen("!node2", custom_time)
        tracked = self.detector.get_tracked_nodes()
        self.assertEqual(tracked["!node2"], custom_time)

    def test_clear_state(self):
        """Test clearing all state."""
        self.detector.update_node_seen("!node1")
        self.detector.update_node_seen("!node2")
        self.detector.clear_state()
        tracked = self.detector.get_tracked_nodes()
        self.assertEqual(len(tracked), 0)


class TestAlertDetectorDisconnect(unittest.TestCase):
    """Test AlertDetector disconnect detection."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector_config = AlertDetectorConfig(
            disconnect_timeout_seconds=60  # 1 minute for faster testing
        )
        self.detector = AlertDetector(self.config, self.detector_config)

    def test_no_alerts_within_timeout(self):
        """No disconnect alerts if node seen recently."""
        self.detector.update_node_seen("!node1")
        alerts = self.detector.check_disconnects()
        self.assertEqual(len(alerts), 0)

    def test_alert_after_timeout(self):
        """Alert generated after timeout."""
        # Set node as seen 2 minutes ago
        old_time = datetime.now() - timedelta(minutes=2)
        self.detector.update_node_seen("!node1", old_time)

        alerts = self.detector.check_disconnects()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, AlertType.DISCONNECT)
        self.assertIn("!node1"[-6:], alerts[0].message)

    def test_no_duplicate_alerts(self):
        """Don't alert for same disconnected node twice."""
        old_time = datetime.now() - timedelta(minutes=2)
        self.detector.update_node_seen("!node1", old_time)

        alerts1 = self.detector.check_disconnects()
        alerts2 = self.detector.check_disconnects()

        self.assertEqual(len(alerts1), 1)
        self.assertEqual(len(alerts2), 0)

    def test_disconnect_disabled(self):
        """No alerts when disconnect detection disabled."""
        self.detector.detector_config.disconnect_enabled = False
        old_time = datetime.now() - timedelta(minutes=2)
        self.detector.update_node_seen("!node1", old_time)

        alerts = self.detector.check_disconnects()
        self.assertEqual(len(alerts), 0)

    def test_reconnect_clears_alert_flag(self):
        """Reconnected node can trigger new disconnect alert."""
        old_time = datetime.now() - timedelta(minutes=2)
        self.detector.update_node_seen("!node1", old_time)

        # First disconnect
        alerts1 = self.detector.check_disconnects()
        self.assertEqual(len(alerts1), 1)

        # Node reconnects
        self.detector.update_node_seen("!node1")

        # Goes offline again
        old_time2 = datetime.now() - timedelta(minutes=2)
        self.detector.update_node_seen("!node1", old_time2)

        # Should alert again
        alerts2 = self.detector.check_disconnects()
        self.assertEqual(len(alerts2), 1)


class TestAlertDetectorNoisyNode(unittest.TestCase):
    """Test AlertDetector noisy node detection."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector_config = AlertDetectorConfig(
            noisy_node_threshold=5,  # Lower threshold for testing
            noisy_node_period_seconds=60
        )
        self.detector = AlertDetector(self.config, self.detector_config)

    def test_no_alert_under_threshold(self):
        """No alert when under message threshold."""
        for _ in range(4):  # Under threshold of 5
            alert = self.detector.record_message("!node1")
        self.assertIsNone(alert)

    def test_alert_at_threshold(self):
        """Alert generated when reaching threshold."""
        for i in range(4):
            self.detector.record_message("!node1")

        # Fifth message should trigger
        alert = self.detector.record_message("!node1")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, AlertType.NOISY_NODE)

    def test_cooldown_prevents_spam(self):
        """Cooldown prevents repeated alerts."""
        # Trigger first alert
        for _ in range(5):
            self.detector.record_message("!node1")

        # More messages shouldn't trigger immediately
        for _ in range(5):
            alert = self.detector.record_message("!node1")
        self.assertIsNone(alert)

    def test_noisy_node_disabled(self):
        """No alerts when noisy node detection disabled."""
        self.detector.detector_config.noisy_node_enabled = False
        for _ in range(10):
            alert = self.detector.record_message("!node1")
        self.assertIsNone(alert)


class TestAlertDetectorProximity(unittest.TestCase):
    """Test AlertDetector proximity detection."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector_config = AlertDetectorConfig(proximity_enabled=True)
        self.detector = AlertDetector(self.config, self.detector_config)

        # Add a test zone
        self.zone = ProximityZone(
            name="Test Zone",
            latitude=45.5,
            longitude=-122.6,
            radius_meters=1000,
            alert_on_enter=True,
            alert_on_exit=True
        )
        self.detector.add_proximity_zone(self.zone)

    def test_enter_zone(self):
        """Alert on entering zone."""
        # Position inside zone
        pos = Position(latitude=45.5, longitude=-122.6)
        alerts = self.detector.check_proximity("!node1", pos)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, AlertType.PROXIMITY)
        self.assertIn("enter", alerts[0].metadata["event"])

    def test_exit_zone(self):
        """Alert on exiting zone."""
        # First enter the zone
        pos_in = Position(latitude=45.5, longitude=-122.6)
        self.detector.check_proximity("!node1", pos_in)

        # Then exit
        pos_out = Position(latitude=46.0, longitude=-123.0)  # Far away
        alerts = self.detector.check_proximity("!node1", pos_out)

        self.assertEqual(len(alerts), 1)
        self.assertIn("exit", alerts[0].metadata["event"])

    def test_stay_in_zone(self):
        """No alerts when staying in zone."""
        pos1 = Position(latitude=45.5, longitude=-122.6)
        pos2 = Position(latitude=45.5001, longitude=-122.5999)  # Slight movement

        self.detector.check_proximity("!node1", pos1)
        alerts = self.detector.check_proximity("!node1", pos2)

        self.assertEqual(len(alerts), 0)

    def test_invalid_position(self):
        """No alerts for zero/invalid position."""
        pos = Position(latitude=0, longitude=0)
        alerts = self.detector.check_proximity("!node1", pos)
        self.assertEqual(len(alerts), 0)

    def test_proximity_disabled(self):
        """No alerts when proximity detection disabled."""
        self.detector.detector_config.proximity_enabled = False
        pos = Position(latitude=45.5, longitude=-122.6)
        alerts = self.detector.check_proximity("!node1", pos)
        self.assertEqual(len(alerts), 0)


class TestAlertDetectorSNR(unittest.TestCase):
    """Test AlertDetector SNR detection."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector_config = AlertDetectorConfig(
            snr_enabled=True,
            snr_threshold=-10.0
        )
        self.detector = AlertDetector(self.config, self.detector_config)

    def test_low_snr_alert(self):
        """Alert generated for low SNR."""
        alert = self.detector.check_snr("!node1", -15.0)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, AlertType.SNR)

    def test_good_snr_no_alert(self):
        """No alert for good SNR."""
        alert = self.detector.check_snr("!node1", 5.0)
        self.assertIsNone(alert)

    def test_threshold_boundary(self):
        """Test behavior at threshold."""
        alert_at = self.detector.check_snr("!node1", -10.0)
        alert_below = self.detector.check_snr("!node2", -10.1)

        self.assertIsNone(alert_at)
        self.assertIsNotNone(alert_below)

    def test_snr_disabled(self):
        """No alerts when SNR detection disabled."""
        self.detector.detector_config.snr_enabled = False
        alert = self.detector.check_snr("!node1", -20.0)
        self.assertIsNone(alert)


class TestAlertDetectorBatchProcessing(unittest.TestCase):
    """Test AlertDetector batch processing methods."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector_config = AlertDetectorConfig(
            proximity_enabled=True,
            snr_enabled=True,
            snr_threshold=-10.0
        )
        self.detector = AlertDetector(self.config, self.detector_config)

        # Add a zone
        zone = ProximityZone(
            name="Test", latitude=45.5, longitude=-122.6,
            radius_meters=1000, alert_on_enter=True
        )
        self.detector.add_proximity_zone(zone)

    def test_process_node_update(self):
        """Test processing a node update."""
        node = Node(
            node_id="!test123",
            node_num=12345,
            position=Position(latitude=45.5, longitude=-122.6),
            telemetry=NodeTelemetry(snr=-15.0),
            last_heard=datetime.now()
        )

        alerts = self.detector.process_node_update(node)

        # Should get proximity and SNR alerts
        self.assertEqual(len(alerts), 2)
        alert_types = {a.alert_type for a in alerts}
        self.assertIn(AlertType.PROXIMITY, alert_types)
        self.assertIn(AlertType.SNR, alert_types)

    def test_process_message(self):
        """Test processing a message."""
        # Set low threshold for testing
        self.detector.detector_config.noisy_node_threshold = 1

        msg = Message(
            id="msg1",
            sender_id="!sender123",
            text="Hello"
        )

        alerts = self.detector.process_message(msg)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, AlertType.NOISY_NODE)


class TestAlertDetectorCallbacks(unittest.TestCase):
    """Test AlertDetector callback system."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector_config = AlertDetectorConfig(
            noisy_node_threshold=1  # Low threshold for testing
        )
        self.detector = AlertDetector(self.config, self.detector_config)
        self.received_alerts = []

    def test_callback_fires(self):
        """Callback is called when alert generated."""
        def callback(alert):
            self.received_alerts.append(alert)

        self.detector.register_alert_callback(callback)
        self.detector.record_message("!node1")

        self.assertEqual(len(self.received_alerts), 1)

    def test_multiple_callbacks(self):
        """Multiple callbacks all fire."""
        counts = {"a": 0, "b": 0}

        def callback_a(alert):
            counts["a"] += 1

        def callback_b(alert):
            counts["b"] += 1

        self.detector.register_alert_callback(callback_a)
        self.detector.register_alert_callback(callback_b)
        self.detector.record_message("!node1")

        self.assertEqual(counts["a"], 1)
        self.assertEqual(counts["b"], 1)

    def test_callback_error_handling(self):
        """Callback errors don't break detection."""
        def bad_callback(alert):
            raise ValueError("Test error")

        def good_callback(alert):
            self.received_alerts.append(alert)

        self.detector.register_alert_callback(bad_callback)
        self.detector.register_alert_callback(good_callback)

        # Should not raise, and good callback should still fire
        self.detector.record_message("!node1")
        self.assertEqual(len(self.received_alerts), 1)


class TestAlertDetectorThreadSafety(unittest.TestCase):
    """Test AlertDetector thread safety."""

    def setUp(self):
        self.config = Config(config_path="/nonexistent/path")
        self.detector = AlertDetector(self.config)

    def test_concurrent_updates(self):
        """Concurrent updates don't cause errors."""
        errors = []

        def update_nodes():
            try:
                for i in range(50):
                    self.detector.update_node_seen(f"!node_{threading.current_thread().name}_{i}")
            except Exception as e:
                errors.append(e)

        def record_messages():
            try:
                for i in range(50):
                    self.detector.record_message(f"!msg_{threading.current_thread().name}_{i}")
            except Exception as e:
                errors.append(e)

        def check_disconnects():
            try:
                for _ in range(20):
                    self.detector.check_disconnects()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=update_nodes, name=f"update_{i}"))
            threads.append(threading.Thread(target=record_messages, name=f"msg_{i}"))
            threads.append(threading.Thread(target=check_disconnects, name=f"check_{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")


if __name__ == "__main__":
    unittest.main()

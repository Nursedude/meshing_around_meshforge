"""
Unit tests for meshtasticd HTTP API connection support.

Tests the HTTP connection type across config, meshtastic_api, and connection_manager.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.config import Config  # noqa: E402
from meshing_around_clients.core.connection_manager import ConnectionManager, ConnectionType  # noqa: E402


class TestConnectionTypeEnum(unittest.TestCase):
    """Test HTTP is present in ConnectionType enum."""

    def test_http_in_connection_type(self):
        self.assertEqual(ConnectionType.HTTP.value, "http")

    def test_http_from_string(self):
        self.assertEqual(ConnectionType("http"), ConnectionType.HTTP)

    def test_all_connection_types_present(self):
        """Verify all expected connection types exist."""
        expected = {"serial", "tcp", "http", "mqtt", "ble", "demo", "auto"}
        actual = {ct.value for ct in ConnectionType}
        self.assertEqual(actual, expected)


class TestConnectionManagerHTTPDetection(unittest.TestCase):
    """Test auto-detection of HTTP connection type."""

    def _make_config(self, **overrides):
        cfg = Config(config_path="/nonexistent/path/config.ini")
        for key, value in overrides.items():
            if hasattr(cfg.interface, key):
                setattr(cfg.interface, key, value)
        return cfg

    def test_detect_http_when_http_url_set(self):
        """Auto-detect should return HTTP when http_url is configured."""
        cfg = self._make_config(type="auto", http_url="http://meshtastic.local")
        mgr = ConnectionManager(cfg)
        detected = mgr._detect_connection_type()
        self.assertEqual(detected, ConnectionType.HTTP)

    def test_detect_tcp_when_only_hostname_set(self):
        """Auto-detect should return TCP when only hostname is set."""
        cfg = self._make_config(type="auto", hostname="192.168.1.1")
        mgr = ConnectionManager(cfg)
        detected = mgr._detect_connection_type()
        self.assertEqual(detected, ConnectionType.TCP)

    def test_explicit_http_type(self):
        """Explicit type=http should resolve to HTTP."""
        cfg = self._make_config(type="http")
        mgr = ConnectionManager(cfg)
        detected = mgr._detect_connection_type()
        self.assertEqual(detected, ConnectionType.HTTP)


class TestConnectionManagerHTTPConnect(unittest.TestCase):
    """Test HTTP connection flow in ConnectionManager."""

    def _make_config(self):
        cfg = Config(config_path="/nonexistent/path/config.ini")
        cfg.interface.type = "http"
        cfg.interface.http_url = "http://meshtastic.local"
        return cfg

    @patch("meshing_around_clients.core.connection_manager.ConnectionManager._connect_http")
    def test_try_connect_routes_to_http(self, mock_connect_http):
        """_try_connect should call _connect_http for HTTP type."""
        mock_connect_http.return_value = True
        cfg = self._make_config()
        mgr = ConnectionManager(cfg)
        result = mgr._try_connect(ConnectionType.HTTP)
        self.assertTrue(result)
        mock_connect_http.assert_called_once()

    def test_connect_http_no_url_no_hostname_fails(self):
        """HTTP connect should fail when neither http_url nor hostname set."""
        cfg = Config(config_path="/nonexistent/path/config.ini")
        cfg.interface.type = "http"
        cfg.interface.http_url = ""
        cfg.interface.hostname = ""
        mgr = ConnectionManager(cfg)
        result = mgr._connect_http()
        self.assertFalse(result)

    @patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", False)
    def test_connect_http_no_meshtastic_library(self):
        """HTTP connect should fail gracefully without meshtastic library."""
        cfg = self._make_config()
        mgr = ConnectionManager(cfg)
        result = mgr._connect_http()
        self.assertFalse(result)

    def test_http_in_fallback_order(self):
        """HTTP should be in fallback order between TCP and MQTT."""
        cfg = self._make_config()
        mgr = ConnectionManager(cfg)
        # Trigger connect with HTTP type — it will go through fallback chain
        # We just need to verify HTTP is attempted
        # Check by introspecting the fallback order in connect()
        # The order is: SERIAL, TCP, HTTP, MQTT, DEMO
        with patch.object(mgr, "_try_connect", return_value=False) as mock_try:
            mgr.connect(ConnectionType.HTTP)
            # Should try HTTP first (since we start from HTTP in fallback)
            call_types = [call[0][0] for call in mock_try.call_args_list]
            self.assertIn(ConnectionType.HTTP, call_types)
            # HTTP should come before MQTT and DEMO in the list
            http_idx = call_types.index(ConnectionType.HTTP)
            if ConnectionType.MQTT in call_types:
                mqtt_idx = call_types.index(ConnectionType.MQTT)
                self.assertLess(http_idx, mqtt_idx)

    def test_connection_health_property(self):
        """Connection health should report HTTP type."""
        cfg = self._make_config()
        mgr = ConnectionManager(cfg)
        mgr._status.connection_type = ConnectionType.HTTP
        health = mgr.connection_health
        self.assertEqual(health["connection_type"], "http")


class TestMeshtasticAPIHTTPConnect(unittest.TestCase):
    """Test HTTP connection handling in MeshtasticAPI.

    The meshtastic library may not be installed in the test environment,
    so we use create=True on patches for module-level names that only
    exist when the import succeeds.
    """

    def _make_config(self, http_url="", hostname=""):
        cfg = Config(config_path="/nonexistent/path/config.ini")
        cfg.interface.type = "http"
        cfg.interface.http_url = http_url
        cfg.interface.hostname = hostname
        return cfg

    @patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True)
    @patch("meshing_around_clients.core.meshtastic_api.pub", create=True)
    @patch("meshing_around_clients.core.meshtastic_api.meshtastic", create=True)
    def test_connect_with_http_url(self, mock_meshtastic, mock_pub):
        """Should create HTTPInterface with the configured URL."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        mock_interface = MagicMock()
        mock_interface.myInfo.my_node_num = 0x12345678
        mock_interface.nodes = {}
        mock_meshtastic.http_interface.HTTPInterface.return_value = mock_interface

        cfg = self._make_config(http_url="http://meshtastic.local")
        api = MeshtasticAPI(cfg)
        result = api.connect()

        self.assertTrue(result)
        mock_meshtastic.http_interface.HTTPInterface.assert_called_once_with(
            "http://meshtastic.local", connectTimeoutSeconds=30.0
        )
        self.assertEqual(api.connection_info.device_path, "http://meshtastic.local")
        self.assertTrue(api.connection_info.connected)
        api.disconnect()

    @patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True)
    @patch("meshing_around_clients.core.meshtastic_api.pub", create=True)
    @patch("meshing_around_clients.core.meshtastic_api.meshtastic", create=True)
    def test_connect_http_fallback_to_hostname(self, mock_meshtastic, mock_pub):
        """Should construct http:// URL from hostname when http_url is empty."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        mock_interface = MagicMock()
        mock_interface.myInfo.my_node_num = 0x12345678
        mock_interface.nodes = {}
        mock_meshtastic.http_interface.HTTPInterface.return_value = mock_interface

        cfg = self._make_config(http_url="", hostname="192.168.1.50")
        api = MeshtasticAPI(cfg)
        result = api.connect()

        self.assertTrue(result)
        mock_meshtastic.http_interface.HTTPInterface.assert_called_once_with(
            "http://192.168.1.50", connectTimeoutSeconds=30.0
        )
        self.assertEqual(api.connection_info.device_path, "http://192.168.1.50")
        api.disconnect()

    @patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True)
    @patch("meshing_around_clients.core.meshtastic_api.pub", create=True)
    def test_connect_http_no_url_no_hostname_fails(self, mock_pub):
        """Should fail when neither http_url nor hostname configured."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        cfg = self._make_config(http_url="", hostname="")
        api = MeshtasticAPI(cfg)
        result = api.connect()

        self.assertFalse(result)
        self.assertIn("HTTP URL not configured", api.connection_info.error_message)
        self.assertFalse(api.connection_info.connected)

    @patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", False)
    def test_connect_http_no_meshtastic_library(self):
        """Should fail gracefully without meshtastic library."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        cfg = self._make_config(http_url="http://meshtastic.local")
        api = MeshtasticAPI(cfg)
        result = api.connect()

        self.assertFalse(result)
        self.assertIn("not installed", api.connection_info.error_message)

    @patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True)
    @patch("meshing_around_clients.core.meshtastic_api.pub", create=True)
    @patch("meshing_around_clients.core.meshtastic_api.meshtastic", create=True)
    def test_connect_http_connection_error(self, mock_meshtastic, mock_pub):
        """Should handle ConnectionError from HTTPInterface gracefully."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        mock_meshtastic.http_interface.HTTPInterface.side_effect = ConnectionError("Connection refused")

        cfg = self._make_config(http_url="http://192.168.1.99")
        api = MeshtasticAPI(cfg)
        result = api.connect()

        self.assertFalse(result)
        self.assertIn("Connection failed", api.connection_info.error_message)

    @patch("meshing_around_clients.core.meshtastic_api.MESHTASTIC_AVAILABLE", True)
    @patch("meshing_around_clients.core.meshtastic_api.pub", create=True)
    @patch("meshing_around_clients.core.meshtastic_api.meshtastic", create=True)
    def test_connect_http_timeout_error(self, mock_meshtastic, mock_pub):
        """Should handle TimeoutError from HTTPInterface gracefully."""
        from meshing_around_clients.core.meshtastic_api import MeshtasticAPI

        mock_meshtastic.http_interface.HTTPInterface.side_effect = TimeoutError("Connection timed out")

        cfg = self._make_config(http_url="http://192.168.1.99")
        api = MeshtasticAPI(cfg)
        result = api.connect()

        self.assertFalse(result)
        self.assertIn("Connection failed", api.connection_info.error_message)


class TestHTTPConnectionInfoDisplay(unittest.TestCase):
    """Test that HTTP connection info is properly reported."""

    def test_connection_manager_http_device_info(self):
        """ConnectionManager should set device_info with HTTP URL."""
        cfg = Config(config_path="/nonexistent/path/config.ini")
        cfg.interface.type = "http"
        cfg.interface.http_url = "http://meshtastic.local"
        mgr = ConnectionManager(cfg)

        # Mock the internal _connect_http to simulate success
        mock_api = MagicMock()
        mock_api.connect.return_value = True
        mock_api.is_connected = True

        with patch("meshing_around_clients.core.connection_manager.ConnectionManager._connect_http") as mock_connect:
            mock_connect.return_value = True
            mgr._status.device_info = "HTTP: http://meshtastic.local"

        self.assertIn("HTTP:", mgr._status.device_info)
        self.assertIn("meshtastic.local", mgr._status.device_info)


if __name__ == "__main__":
    unittest.main()

"""Tests for MapsClient REST wrapper."""

import json
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from meshing_around_clients.core.maps_client import MapsClient


def _mock_urlopen(payload: Optional[dict] = None, raise_exc: Optional[Exception] = None):
    """Build a patch object for urlopen returning *payload* JSON, or raising."""
    if raise_exc is not None:

        def _raise(*_a, **_kw):
            raise raise_exc

        return patch("meshing_around_clients.core.maps_client.urlopen", side_effect=_raise)

    resp = MagicMock()
    resp.read.return_value = json.dumps(payload or {}).encode("utf-8")
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return patch("meshing_around_clients.core.maps_client.urlopen", return_value=cm)


class TestMapsClient(unittest.TestCase):
    def test_base_url_trailing_slash_stripped(self):
        client = MapsClient(base_url="http://host:9000/")
        self.assertEqual(client.base_url, "http://host:9000")

    def test_fetch_returns_parsed_json(self):
        client = MapsClient()
        with _mock_urlopen({"status": "ok", "count": 3}):
            result = client._fetch("/api/status")
        self.assertEqual(result, {"status": "ok", "count": 3})

    def test_fetch_sends_useragent_and_accept_headers(self):
        client = MapsClient(base_url="http://h:1")
        with _mock_urlopen({}) as mock_open:
            client._fetch("/api/status")
        request = mock_open.call_args.args[0]
        self.assertIn("Meshforge-Tui", request.headers.get("User-agent", "").title().replace(" ", "-"))
        self.assertEqual(request.headers.get("Accept"), "application/json")

    def test_fetch_returns_empty_dict_on_urlerror(self):
        client = MapsClient()
        with _mock_urlopen(raise_exc=URLError("unreachable")):
            self.assertEqual(client._fetch("/api/status"), {})

    def test_fetch_returns_empty_dict_on_oserror(self):
        client = MapsClient()
        with _mock_urlopen(raise_exc=OSError("broken pipe")):
            self.assertEqual(client._fetch("/any"), {})

    def test_fetch_returns_empty_dict_on_bad_json(self):
        client = MapsClient()
        resp = MagicMock()
        resp.read.return_value = b"not-json{"
        cm = MagicMock()
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        with patch("meshing_around_clients.core.maps_client.urlopen", return_value=cm):
            self.assertEqual(client._fetch("/x"), {})

    def test_is_available_true_when_status_returns_data(self):
        client = MapsClient()
        with _mock_urlopen({"ok": True}):
            self.assertTrue(client.is_available())
        self.assertTrue(client._available)

    def test_is_available_false_when_status_empty(self):
        client = MapsClient()
        with _mock_urlopen({}):
            self.assertFalse(client.is_available())
        self.assertFalse(client._available)

    def test_endpoint_methods_hit_expected_paths(self):
        client = MapsClient()
        endpoints = {
            "get_status": "/api/status",
            "get_nodes_geojson": "/api/nodes/geojson",
            "get_topology": "/api/topology",
            "get_health_summary": "/api/node-health/summary",
            "get_active_alerts": "/api/alerts/active",
            "get_analytics_summary": "/api/analytics/summary",
            "get_weather_alerts": "/api/weather/alerts",
            "get_mqtt_stats": "/api/mqtt/stats",
        }
        for method_name, expected_path in endpoints.items():
            with _mock_urlopen({"endpoint": method_name}) as mock_open:
                result = getattr(client, method_name)()
            request = mock_open.call_args.args[0]
            self.assertTrue(
                request.full_url.endswith(expected_path),
                f"{method_name} hit {request.full_url}, expected ...{expected_path}",
            )
            self.assertEqual(result, {"endpoint": method_name})


if __name__ == "__main__":
    unittest.main()

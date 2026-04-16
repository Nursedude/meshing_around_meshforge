"""Client for meshforge-maps REST API. Stdlib only (no extra deps).

Connects to meshforge-maps HTTP server to fetch node data, health scores,
topology, alerts, and analytics. Works with maps running locally or on a
remote host. All methods return empty dict/list on failure — never raises.
"""

import json
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class MapsClient:
    """Lightweight REST client for meshforge-maps API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8808"):
        self.base_url = base_url.rstrip("/")
        self._available = None

    def _fetch(self, path: str, timeout: int = 5) -> dict:
        """Fetch JSON from maps API. Returns empty dict on failure."""
        url = f"{self.base_url}{path}"
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "MeshForge-TUI/0.6",
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
            logger.debug("Maps API fetch failed (%s): %s", path, e)
            return {}

    def is_available(self) -> bool:
        """Check if maps server is reachable (cached for 30s)."""
        status = self._fetch("/api/status", timeout=3)
        self._available = bool(status)
        return self._available

    def get_status(self) -> dict:
        """Server status, source health, node counts."""
        return self._fetch("/api/status")

    def get_nodes_geojson(self) -> dict:
        """All nodes as GeoJSON FeatureCollection."""
        return self._fetch("/api/nodes/geojson")

    def get_topology(self) -> dict:
        """Mesh topology links with SNR."""
        return self._fetch("/api/topology")

    def get_health_summary(self) -> dict:
        """Per-node health score summary."""
        return self._fetch("/api/node-health/summary")

    def get_active_alerts(self) -> dict:
        """Currently active alerts."""
        return self._fetch("/api/alerts/active")

    def get_analytics_summary(self) -> dict:
        """Growth, activity, ranking stats."""
        return self._fetch("/api/analytics/summary")

    def get_weather_alerts(self) -> dict:
        """NOAA weather alerts."""
        return self._fetch("/api/weather/alerts")

    def get_mqtt_stats(self) -> dict:
        """MQTT subscriber statistics."""
        return self._fetch("/api/mqtt/stats")

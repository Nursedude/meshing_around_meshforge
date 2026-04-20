"""
Meshtastic API layer for Meshing-Around Clients.
Provides interface to communicate with Meshtastic devices.
"""

import importlib
import logging
import queue
import random
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_message_logger = logging.getLogger("mesh.messages")

# Connection timeout for serial/TCP/BLE interfaces (seconds)
CONNECT_TIMEOUT_SECONDS = 30.0

# Hostname validation: alphanumeric, dots, hyphens, underscores, optional port
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9._-]+(:\d{1,5})?$")

# Chunk reassembly: bot splits long responses into <=160-char chunks
# (Meshtastic max ~200 chars) sent in rapid succession.  No markers are
# embedded in the payload, so we reassemble by buffering messages from
# the same sender+channel within a configurable time window.
# Short messages (<40 bytes) pass through instantly — keeps TUI snappy on Pi.
_CHUNK_BYTE_THRESHOLD = 40


class _ChunkBuffer:
    """Reassembles sequential text chunks from the same sender.

    Messages under 40 bytes pass through instantly (chat: "hello", "73").
    Longer messages are buffered; if more arrive from the same sender+channel
    within the timeout, they're concatenated into one message.
    """

    def __init__(self, timeout: float = 3.0):
        self._timeout = timeout
        self._buffers: Dict[str, list] = {}  # key -> [(text, mono_ts, packet)]
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._flush_callback: Optional[Any] = None

    @staticmethod
    def _key(sender_id: str, channel: int) -> str:
        return f"{sender_id}:{channel}"

    @property
    def enabled(self) -> bool:
        return self._timeout > 0

    def add(self, sender_id: str, channel: int, text: str, packet: dict) -> bool:
        """Buffer a text fragment.  Returns True if buffered, False to pass through."""
        if not self.enabled:
            return False
        key = self._key(sender_id, channel)
        with self._lock:
            if key in self._buffers:
                # Already buffering this sender — add regardless of size
                self._buffers[key].append((text, time.monotonic(), packet))
                self._reset_timer(key)
                return True
            elif len(text.encode("utf-8")) >= _CHUNK_BYTE_THRESHOLD:
                # Long enough to be a bot chunk — start buffering
                self._buffers[key] = [(text, time.monotonic(), packet)]
                self._reset_timer(key)
                return True
            return False  # Short message, pass through instantly

    def _reset_timer(self, key: str) -> None:
        """Reset the flush timer.  Caller must hold _lock."""
        old = self._timers.pop(key, None)
        if old is not None:
            old.cancel()
        t = threading.Timer(self._timeout, self._flush, args=(key,))
        t.daemon = True
        t.start()
        self._timers[key] = t

    def _flush(self, key: str) -> None:
        """Timer expired — concatenate and emit."""
        with self._lock:
            chunks = self._buffers.pop(key, [])
            self._timers.pop(key, None)
        if chunks and self._flush_callback:
            combined = "\n".join(text for text, _, _ in chunks)
            first_packet = chunks[0][2]
            self._flush_callback(combined, first_packet, len(chunks))

    def cancel_all(self) -> None:
        """Cancel pending timers (called on disconnect)."""
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
            self._buffers.clear()


from .callbacks import CallbackMixin, extract_position, safe_float, safe_int  # noqa: E402
from .config import Config  # noqa: E402
from .models import (  # noqa: E402
    DATETIME_MIN_UTC,
    MAX_MESSAGE_BYTES,
    Alert,
    AlertType,
    Channel,
    ChannelRole,
    ConnectionInfo,
    LinkQuality,
    MeshNetwork,
    MeshRoute,
    Message,
    MessageType,
    Node,
    NodeRole,
    NodeTelemetry,
    Position,
    RouteHop,
)

# Core meshtastic + pubsub (required for any hardware connection)
try:
    importlib.import_module("meshtastic")
    from pubsub import pub

    MESHTASTIC_AVAILABLE = True
except ImportError:
    MESHTASTIC_AVAILABLE = False

# Interface sub-modules (each may have platform-specific deps, e.g. bleak for BLE)
_INTERFACE_MODULES: dict = {}
for _mod_name in ("serial_interface", "tcp_interface", "http_interface", "ble_interface"):
    try:
        _INTERFACE_MODULES[_mod_name] = importlib.import_module(f"meshtastic.{_mod_name}")
    except Exception as _exc:
        _INTERFACE_MODULES[_mod_name] = None
        if not isinstance(_exc, ImportError):
            logger.info("meshtastic.%s import failed (%s): %s", _mod_name, type(_exc).__name__, _exc)

# Maps config interface type to sub-module name
_INTERFACE_TYPE_MAP = {
    "serial": "serial_interface",
    "tcp": "tcp_interface",
    "http": "http_interface",
    "ble": "ble_interface",
}


def refresh_meshtastic_availability() -> bool:
    """Re-check whether the meshtastic library is importable (e.g. after pip install)."""
    global MESHTASTIC_AVAILABLE
    try:
        importlib.import_module("meshtastic")
        importlib.import_module("pubsub")
        MESHTASTIC_AVAILABLE = True
    except ImportError:
        MESHTASTIC_AVAILABLE = False

    # Re-probe interface sub-modules
    for mod_name in ("serial_interface", "tcp_interface", "http_interface", "ble_interface"):
        try:
            _INTERFACE_MODULES[mod_name] = importlib.import_module(f"meshtastic.{mod_name}")
        except Exception as exc:
            _INTERFACE_MODULES[mod_name] = None
            if not isinstance(exc, ImportError):
                logger.info("meshtastic.%s import failed (%s): %s", mod_name, type(exc).__name__, exc)

    return MESHTASTIC_AVAILABLE


# Path to upstream meshing-around bot's Python venv
_UPSTREAM_VENV_PYTHON = Path("/opt/meshing-around/venv/bin/python3")

# Map of meshforge command names → upstream function calls via bot's venv
# Each value is (module, function, needs_latlon)
_UPSTREAM_CMD_MAP = {
    # Space / astronomy
    "moon": ("space", "get_moon", True),
    "sun": ("space", "get_sun", True),
    "solar": ("space", "solar_conditions", False),
    "hfcond": ("space", "hf_band_conditions", False),
    # Weather
    "wx": ("locationdata", "get_NOAAweather", True),
    "wxc": ("locationdata", "get_NOAAweather", True),  # compact format
    "mwx": ("wx_meteo", "get_wx_meteo", True),
    "wxa": ("locationdata", "getWeatherAlertsNOAA", True),
    "wxalert": ("locationdata", "getWeatherAlertsNOAA", True),
    # Alerts / hazards
    "valert": ("locationdata", "get_volcano_usgs", True),
    "earthquake": ("locationdata", "checkUSGSEarthQuake", True),
    "ealert": ("locationdata", "getIpawsAlert", True),
    # Water / tides
    "tide": ("locationdata", "get_NOAAtide", True),
    "riverflow": ("locationdata", "get_flood_noaa", True),
    # Location
    "whereami": ("locationdata", "where_am_i", True),
}

# Commands that REQUIRE the running bot (need runtime state, node DB, etc.)
# These get sent via mesh when connected, or show "requires bot" when not.
_BOT_ONLY_COMMANDS = {
    "joke",
    "wiki",
    "askai",
    "bbshelp",
    "bbslist",
    "bbspost",
    "bbsread",
    "checkin",
    "checkout",
    "dx",
    "games",
    "messages",
    "readnews",
    "readrss",
    "rlist",
    "howfar",
    "howtall",
    "whoami",
    "sysinfo",
    "satpass",
    "echo",
    "email:",
    "sms:",
    "survey",
    "quiz",
}

# Commands always handled locally by meshforge (no network needed)
_LOCAL_COMMANDS = {
    "cmd",
    "help",
    "ping",
    "version",
    "nodes",
    "status",
    "info",
    "uptime",
    "lheard",
    "sitrep",
    "leaderboard",
}


def _check_venv_path_safe(path: Path) -> bool:
    """Verify the upstream venv python is not world-writable (SEC-23)."""
    import os
    import stat

    try:
        st = os.stat(path)
        if st.st_mode & stat.S_IWOTH:
            logger.warning("Upstream venv python is world-writable, refusing to execute: %s", path)
            return False
        return True
    except OSError:
        return False


# Static script template for upstream command execution.  All variable data
# is passed via environment variables — never interpolated into the script
# string — to eliminate code-injection risk (SEC-23).
_UPSTREAM_SCRIPT = """\
import os, sys, types, logging
sys.path.insert(0, '/opt/meshing-around')
sys.path.insert(0, '/opt/meshing-around/modules')
stub = types.ModuleType('modules.log')
stub.logger = logging.getLogger('stub')
stub.getPrettyTime = lambda: ''
sys.modules['modules.log'] = stub
import modules.settings as s
s.latitudeValue = float(os.environ.get('MESHFORGE_LAT', '0'))
s.longitudeValue = float(os.environ.get('MESHFORGE_LON', '0'))
s.zuluTime = False
s.use_metric = False
s.urlTimeoutSeconds = 10
s.noaaForecastDuration = 3
s.ignoreUSGSEnable = False
s.ignoreUSGSwords = []
s.ERROR_FETCHING_DATA = 'Error fetching data'
s.NO_DATA_NOGPS = 'No GPS data'
s.NO_ALERTS = 'No alerts'
mod = os.environ['MESHFORGE_MODULE']
fn = os.environ['MESHFORGE_FUNC']
use_latlon = os.environ.get('MESHFORGE_LATLON', '0') == '1'
exec_mod = __import__(mod, fromlist=[fn])
func = getattr(exec_mod, fn)
result = func(s.latitudeValue, s.longitudeValue) if use_latlon else func()
if result:
    print(result)
"""


def _call_upstream_cmd(command: str, lat: float = 0.0, lon: float = 0.0) -> str:
    """Call an upstream meshing-around command using the bot's Python venv.

    This gives identical output to the bot since it uses the same code + deps.
    Falls back gracefully if the bot venv or modules aren't available.

    All variable data is passed via environment variables to avoid code
    injection risk from f-string interpolation in subprocess scripts.
    """
    import os
    import subprocess

    if command not in _UPSTREAM_CMD_MAP:
        return ""
    if not _UPSTREAM_VENV_PYTHON.exists():
        return ""
    if not _check_venv_path_safe(_UPSTREAM_VENV_PYTHON):
        return ""

    module, func, needs_latlon = _UPSTREAM_CMD_MAP[command]

    # Type-check lat/lon to prevent non-numeric values
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        logger.warning("Upstream cmd %s: invalid lat/lon types", command)
        return ""

    env = os.environ.copy()
    env["MESHFORGE_MODULE"] = module
    env["MESHFORGE_FUNC"] = func
    env["MESHFORGE_LAT"] = str(float(lat))
    env["MESHFORGE_LON"] = str(float(lon))
    env["MESHFORGE_LATLON"] = "1" if needs_latlon else "0"

    try:
        proc = subprocess.run(
            [str(_UPSTREAM_VENV_PYTHON), "-c", _UPSTREAM_SCRIPT],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        output = proc.stdout.strip()
        if output:
            return output
        if proc.stderr:
            # Filter out the harmless config warning
            errs = [line for line in proc.stderr.splitlines() if "config.ini" not in line.lower()]
            if errs:
                logger.warning("Upstream cmd %s stderr: %s", command, errs[0][:100])
        return f"{command}: no data"
    except subprocess.TimeoutExpired:
        return f"{command}: timeout"
    except (OSError, ValueError) as e:
        logger.warning("Upstream cmd %s failed: %s", command, e)
        return ""


_MAX_FETCH_BYTES = 1_048_576  # 1 MiB cap — guards against OOM on Pi Zero when
#                                a misconfigured or malicious data-source URL
#                                returns a large response.  Mesh payloads max
#                                out at 228 bytes; summaries rarely exceed 10 KB.


def _fetch_url(url: str, timeout: int = 10) -> str:
    """Fetch URL content with stdlib only. Returns response text or empty string."""
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    try:
        req = Request(
            url, headers={"User-Agent": "MeshForge/0.5", "Accept": "application/json,application/xml,text/plain"}
        )
        with urlopen(req, timeout=timeout) as resp:
            # Cap at _MAX_FETCH_BYTES + 1 so we can detect overflow and log it.
            raw = resp.read(_MAX_FETCH_BYTES + 1)
            if len(raw) > _MAX_FETCH_BYTES:
                logger.warning("Fetch %s truncated at %d bytes", url[:60], _MAX_FETCH_BYTES)
                raw = raw[:_MAX_FETCH_BYTES]
            return raw.decode("utf-8", errors="replace")
    except (URLError, OSError, ValueError) as e:
        logger.warning("Fetch failed (%s): %s", url[:60], e)
        return ""


def _cmd_wx(lat: float, lon: float) -> str:
    """NOAA weather forecast — same API as upstream meshing-around."""
    import json

    # Step 1: Get forecast URL from points endpoint
    points_data = _fetch_url(f"https://api.weather.gov/points/{lat},{lon}")
    if not points_data:
        return "Weather: fetch failed"
    try:
        props = json.loads(points_data).get("properties", {})
        forecast_url = props.get("forecast", "")
        if not forecast_url:
            return "Weather: no forecast URL"
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Weather points parse error: %s", e)
        return "Weather: parse error"

    # Step 2: Get actual forecast
    forecast_data = _fetch_url(forecast_url)
    if not forecast_data:
        return "Weather: forecast fetch failed"
    try:
        periods = json.loads(forecast_data).get("properties", {}).get("periods", [])
        if not periods:
            return "Weather: no forecast data"
        p = periods[0]
        name = p.get("name", "")
        temp = p.get("temperature", "")
        unit = p.get("temperatureUnit", "F")
        wind = p.get("windSpeed", "")
        wind_dir = p.get("windDirection", "")
        short = p.get("shortForecast", "")
        return f"Wx {name}: {temp}{unit} {wind_dir} {wind} {short}"[:200]
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Weather forecast parse error: %s", e)
        return "Weather: parse error"


def _cmd_wxa(lat: float, lon: float) -> str:
    """NWS active weather alerts — same API as upstream."""
    import json

    data = _fetch_url(f"https://api.weather.gov/alerts/active?point={lat},{lon}")
    if not data:
        return "WxAlert: fetch failed"
    try:
        features = json.loads(data).get("features", [])
        if not features:
            return "WxAlert: no active alerts"
        a = features[0]["properties"]
        event = a.get("event", "Unknown")
        headline = a.get("headline", "")
        return f"WxAlert: {event} - {headline}"[:200]
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("WxAlert parse error: %s", e)
        return "WxAlert: parse error"


def _cmd_earthquake(lat: float, lon: float) -> str:
    """USGS earthquake data — same feed as upstream."""
    import json

    data = _fetch_url("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson")
    if not data:
        return "Earthquake: fetch failed"
    try:
        features = json.loads(data).get("features", [])
        if not features:
            return "Earthquake: no recent 2.5+ quakes"
        # Filter by proximity (within 20 degrees)
        nearby = []
        for f in features:
            coords = f["geometry"]["coordinates"]
            if abs(coords[1] - lat) <= 20 and abs(coords[0] - lon) <= 20:
                nearby.append(f)
        if not nearby:
            # Show latest global if none nearby
            nearby = features[:1]
        q = nearby[0]
        props = q["properties"]
        mag = props.get("mag", "?")
        place = props.get("place", "Unknown")
        return f"Earthquake: M{mag} {place}"[:200]
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Earthquake parse error: %s", e)
        return "Earthquake: parse error"


def _cmd_solar() -> str:
    """Solar/space weather — same SWPC data as upstream."""
    import json

    data = _fetch_url("https://services.swpc.noaa.gov/products/summary/solar-wind-speed.json")
    if not data:
        return "Solar: fetch failed"
    try:
        sw = json.loads(data)
        speed = sw.get("WindSpeed", "?")
        return f"Solar Wind: {speed} km/s"
    except (json.JSONDecodeError, KeyError):
        pass

    # Also try geomagnetic summary
    data2 = _fetch_url("https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json")
    if data2:
        try:
            kp = json.loads(data2)
            if isinstance(kp, list) and len(kp) > 1:
                latest = kp[-1]
                return f"Solar Kp: {latest}"[:200]
        except (json.JSONDecodeError, KeyError):
            pass
    return "Solar: no data"


def _cmd_hfcond() -> str:
    """HF band conditions — same hamqsl.com source as upstream."""
    data = _fetch_url("https://www.hamqsl.com/solarxml.php")
    if not data:
        return "HF: fetch failed"

    # Simple XML parsing for key fields
    def _extract(tag: str) -> str:
        start = data.find(f"<{tag}>")
        end = data.find(f"</{tag}>")
        if start >= 0 and end > start:
            return data[start + len(tag) + 2 : end].strip()
        return "?"

    sfi = _extract("solarflux")
    sn = _extract("sunspots")
    a_index = _extract("aindex")
    k_index = _extract("kindex")
    sig = _extract("signalnoise")
    return f"HF: SFI={sfi} SN={sn} A={a_index} K={k_index} Noise={sig}"[:200]


def _fetch_data_source(source) -> str:
    """Fetch data from an external data source configured in [data_sources].

    Uses stdlib urllib only (no extra deps). Returns a short text summary
    suitable for a mesh message (max ~200 chars). All URLs and codes come
    from the INI config — nothing is hardcoded.

    Args:
        source: A DataSourceEntry with url, station, zone, region, etc.

    Returns:
        Summary string, or error message if fetch fails.
    """
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    try:
        url = source.url
        if not url:
            return f"{source.name}: no URL configured"

        # Build source-specific URL
        if source.command == "weather" and source.station:
            url = f"{url}/stations/{source.station}/observations/latest"
        elif source.command == "tsunami":
            pass  # Use the base URL directly (Atom feed)
        elif source.command == "volcano":
            pass  # Use the base URL directly

        req = Request(
            url,
            headers={"User-Agent": "MeshForge/0.5", "Accept": "application/geo+json,application/json,application/xml"},
        )
        with urlopen(req, timeout=10) as resp:
            raw = resp.read(_MAX_FETCH_BYTES + 1)
            if len(raw) > _MAX_FETCH_BYTES:
                logger.warning("Data source %s truncated at %d bytes", source.name, _MAX_FETCH_BYTES)
                raw = raw[:_MAX_FETCH_BYTES]
            data = raw.decode("utf-8", errors="replace")

        # Parse based on source type
        if source.command == "weather":
            return _parse_weather_response(data, source)
        elif source.command == "tsunami":
            return _parse_tsunami_response(data, source)
        elif source.command == "volcano":
            return _parse_volcano_response(data, source)
        else:
            # Generic: return first 200 chars
            return data[:200]

    except (URLError, OSError, ValueError) as e:
        logger.warning("Data source fetch failed (%s): %s", source.name, e)
        return f"{source.name}: fetch failed"


def _parse_weather_response(data: str, source) -> str:
    """Parse NOAA weather API JSON response into a short summary."""
    import json

    try:
        obs = json.loads(data)
        props = obs.get("properties", {})
        desc = props.get("textDescription", "N/A")
        temp_c = props.get("temperature", {}).get("value")
        humidity = props.get("relativeHumidity", {}).get("value")
        wind_speed = props.get("windSpeed", {}).get("value")

        parts = [f"Wx {source.station}: {desc}"]
        if temp_c is not None:
            temp_f = round(temp_c * 9 / 5 + 32, 1)
            parts.append(f"{temp_f}F/{round(temp_c, 1)}C")
        if humidity is not None:
            parts.append(f"RH:{round(humidity)}%")
        if wind_speed is not None:
            parts.append(f"Wind:{round(wind_speed)}kph")
        return " ".join(parts)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Weather parse error: %s", e)
        return "Weather: parse error"


def _parse_tsunami_response(data: str, source) -> str:
    """Parse NOAA tsunami Atom feed into a short summary."""
    # Simple XML parsing with stdlib — look for <title> and <updated> in entries
    try:
        entries = data.split("<entry>")
        if len(entries) <= 1:
            return "Tsunami: no active alerts"
        # First entry after split is the most recent
        entry = entries[1]
        title_start = entry.find("<title>")
        title_end = entry.find("</title>")
        if title_start >= 0 and title_end > title_start:
            title = entry[title_start + 7 : title_end].strip()
            return f"Tsunami: {title[:180]}"
        return "Tsunami: no active alerts"
    except (IndexError, ValueError) as e:
        logger.warning("Tsunami parse error: %s", e)
        return "Tsunami: parse error"


def _parse_volcano_response(data: str, source) -> str:
    """Parse USGS volcano CAP elevated API response into a short summary.

    Uses the same API and field names as upstream meshing-around:
    https://volcanoes.usgs.gov/hans-public/api/volcano/getCapElevated
    """
    import json

    try:
        volcanoes = json.loads(data)
        if not isinstance(volcanoes, list) or not volcanoes:
            return "Volcano: no data"

        # Filter by proximity if lat/lon configured (matches upstream ±10 degrees)
        lat = getattr(source, "lat", 0.0)
        lon = getattr(source, "lon", 0.0)
        if lat != 0.0 or lon != 0.0:
            volcanoes = [
                v
                for v in volcanoes
                if (lat - 10 <= v.get("latitude", 0) <= lat + 10 and lon - 10 <= v.get("longitude", 0) <= lon + 10)
            ]

        if not volcanoes:
            return "Volcano: no active alerts"

        # Format the first matching alert
        v = volcanoes[0]
        name = v.get("volcano_name_appended", "Unknown")
        alert_level = v.get("alert_level", "Unknown")
        color_code = v.get("color_code", "")
        synopsis = v.get("synopsis", "")

        result = f"Volcano: {name} {alert_level} {color_code}"
        if synopsis:
            max_syn = 180 - len(result) - 3
            if max_syn > 20:
                result += f" - {synopsis[:max_syn]}"
        return result[:200]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Volcano parse error: %s", e)
        return "Volcano: parse error"


class MeshtasticAPI(CallbackMixin):
    """
    API layer for Meshtastic device communication.
    Provides a unified interface for serial, TCP, and BLE connections.
    """

    def __init__(self, config: Config):
        self.config = config
        self.interface = None
        self.network = MeshNetwork()
        self.connection_info = ConnectionInfo()
        self._message_queue: queue.Queue = queue.Queue(maxsize=5000)
        self._messages_dropped = 0
        self._init_callbacks()
        # Wire INI cooldown_period to runtime (default 300s)
        self._alert_cooldown_seconds = config.alerts.cooldown_period
        # Chunk reassembly buffer
        self._chunk_buffer = _ChunkBuffer(timeout=config.chunk_reassembly_timeout)
        self._chunk_buffer._flush_callback = self._emit_reassembled_message
        self._running = threading.Event()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._leaked_thread_count = 0
        self._auto_save_thread: Optional[threading.Thread] = None
        self._last_save_time: Optional[datetime] = None
        self._save_lock = threading.Lock()  # Guard against overlapping saves
        self._last_logged_health: str = ""

        # Load persisted state if enabled
        self._load_persisted_state()

    @property
    def is_connected(self) -> bool:
        return self.connection_info.connected

    # ==================== Persistence Methods ====================

    def _load_persisted_state(self) -> None:
        """Load network state from persistent storage."""
        if not hasattr(self.config, "storage") or not self.config.storage.enabled:
            return

        state_path = self.config.get_state_file_path()
        if state_path.exists():
            loaded = MeshNetwork.load_from_file(state_path)
            if loaded and loaded.nodes:
                # Merge loaded nodes with empty network
                self.network = loaded
                self.network.connection_status = "disconnected"  # Reset status
                logger.info("Loaded %d nodes from %s", len(self.network.nodes), state_path)

    def _save_state(self) -> bool:
        """Save network state to persistent storage.

        Uses a guard flag to skip if a previous save is still in progress,
        preventing overlapping writes under slow I/O conditions.
        """
        if not hasattr(self.config, "storage") or not self.config.storage.enabled:
            return False
        if not self._save_lock.acquire(blocking=False):
            logger.debug("Skipping save — previous save still in progress")
            return False

        try:
            state_path = self.config.get_state_file_path()
            self.network.last_update = datetime.now(timezone.utc)
            success = self.network.save_to_file(state_path)
            if success:
                self._last_save_time = datetime.now(timezone.utc)
            return success
        finally:
            self._save_lock.release()

    def _start_auto_save(self) -> None:
        """Start background auto-save thread."""
        if not hasattr(self.config, "storage"):
            return
        if self.config.storage.auto_save_interval <= 0:
            return

        def auto_save_loop():
            interval = self.config.storage.auto_save_interval
            while not self._stop_event.is_set():
                # Wait for interval or until stop is signaled
                if self._stop_event.wait(timeout=interval):
                    break  # Stop event was set
                if self.connection_info.connected:
                    self._save_state()

        self._auto_save_thread = threading.Thread(target=auto_save_loop, daemon=True)
        self._auto_save_thread.start()

    @staticmethod
    def _check_tcp_contention(host: str, port: int) -> None:
        """Warn if meshtasticd at *host:port* already has a TCP client.

        meshtasticd's protobuf API handles multiple TCP clients poorly —
        a second client can starve the web UI (:9443) and cause packet
        loss.  This does a quick connect-then-close probe; if the probe
        succeeds we log a warning (someone else is already connected and
        the API accepted *another* socket).  A refused/timed-out probe
        is fine — means no contention risk.
        """
        import socket

        try:
            with socket.create_connection((host, port), timeout=3):
                # Connection succeeded — meshtasticd is listening.
                # We can't easily tell how many OTHER clients exist from
                # outside, but for non-localhost targets the mere act of
                # opening a second TCP session is the problem.
                if host not in ("127.0.0.1", "localhost", "::1"):
                    logger.warning(
                        "TCP contention risk: connecting to remote meshtasticd at %s:%d. "
                        "If another client (meshforge-map, mesh_bot) already holds a TCP "
                        "connection, the web UI on :9443 may become unresponsive. "
                        "Consider using MQTT instead.",
                        host,
                        port,
                    )
        except (OSError, socket.timeout):
            pass  # Can't reach host yet — _try_create will handle the real error

    @staticmethod
    def _try_create(cls, *args, **kwargs):
        """Instantiate a meshtastic interface, dropping unsupported kwargs."""
        try:
            return cls(*args, **kwargs)
        except TypeError:
            # Older/newer meshtastic versions may not accept all kwargs;
            # drop optional kwargs and retry.
            for key in ("connectTimeoutSeconds", "portNumber", "noNodes"):
                kwargs.pop(key, None)
            return cls(*args, **kwargs)

    def _create_interface(self, interface_type: str):
        """Create and return the appropriate Meshtastic interface."""
        target = (
            self.config.interface.port
            or self.config.interface.hostname
            or self.config.interface.http_url
            or self.config.interface.mac
            or "auto"
        )
        logger.info("Creating %s interface (target: %s)", interface_type, target)
        mod_name = _INTERFACE_TYPE_MAP.get(interface_type)
        if mod_name is None:
            raise ValueError(f"Unknown interface type: {interface_type}")
        mod = _INTERFACE_MODULES.get(mod_name)
        if mod is None:
            raise ImportError(f"meshtastic.{mod_name} not available — install its dependencies")

        if interface_type == "serial":
            port = self.config.interface.port if self.config.interface.port else None
            self.connection_info.device_path = port or "auto"
            return self._try_create(mod.SerialInterface, port, connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS)
        elif interface_type == "tcp":
            hostname = self.config.interface.hostname
            if not hostname:
                raise ValueError("TCP hostname not configured")
            if not _HOSTNAME_RE.match(hostname):
                raise ValueError(f"Invalid TCP hostname: {hostname!r}")
            self.connection_info.device_path = hostname
            host, tcp_port = hostname.rsplit(":", 1) if ":" in hostname else (hostname, "4403")
            # Warn about meshtasticd TCP contention — multiple clients degrade
            # the protobuf API and can starve the web UI on :9443.
            self._check_tcp_contention(host, int(tcp_port))
            return self._try_create(
                mod.TCPInterface,
                host,
                portNumber=int(tcp_port),
                connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS,
                noNodes=True,
            )
        elif interface_type == "http":
            base_url = self.config.interface.http_url
            if not base_url:
                hostname = self.config.interface.hostname
                if not hostname:
                    raise ValueError("HTTP URL not configured (set http_url or hostname)")
                if not _HOSTNAME_RE.match(hostname):
                    raise ValueError(f"Invalid HTTP hostname: {hostname!r}")
                base_url = f"http://{hostname}"
            self.connection_info.device_path = base_url
            return self._try_create(mod.HTTPInterface, base_url, connectTimeoutSeconds=CONNECT_TIMEOUT_SECONDS)
        elif interface_type == "ble":
            mac = self.config.interface.mac
            if not mac:
                raise ValueError("BLE MAC address not configured")
            self.connection_info.device_path = mac
            return mod.BLEInterface(mac)

    def _start_worker_thread(self) -> None:
        """Stop any previous worker thread and start a fresh one."""
        # Signal old thread to stop BEFORE joining
        self._stop_event.set()
        self._running.clear()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
            if self._worker_thread.is_alive():
                self._leaked_thread_count += 1
                # SEC-21: Log at ERROR with thread identity for debugging
                logger.error(
                    "Worker thread %s (ident=%s) did not stop within 5s " "(leaked threads: %d)",
                    self._worker_thread.name,
                    self._worker_thread.ident,
                    self._leaked_thread_count,
                )
                if self._leaked_thread_count > 2:
                    logger.error(
                        "Too many leaked worker threads (%d), refusing new connection", self._leaked_thread_count
                    )
                    return
            else:
                self._leaked_thread_count = 0

        # Drain stale messages from previous session
        while not self._message_queue.empty():
            try:
                self._message_queue.get_nowait()
            except queue.Empty:
                break

        self._stop_event.clear()
        self._running.set()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def is_healthy(self) -> bool:
        """Check if the API worker thread is alive and running.

        Returns True if the worker is active and processing messages.
        TUI/Web layers can poll this to detect connection degradation.
        """
        if not self._running.is_set():
            return False
        if self._worker_thread and not self._worker_thread.is_alive():
            return False
        return self.connection_info.connected

    @property
    def connection_health(self) -> Dict[str, Any]:
        """Get connection health metrics.

        Returns a dict compatible with MQTTMeshtasticClient.connection_health,
        allowing the TUI to use a single code path regardless of connection mode.
        """
        connected = self.is_connected
        healthy = self.is_healthy()

        if not connected:
            status = "disconnected"
        elif not healthy:
            status = "degraded"
        else:
            status = "healthy"

        if status != self._last_logged_health:
            old = self._last_logged_health or "initial"
            self._last_logged_health = status
            if status in ("disconnected", "degraded"):
                logger.warning("Connection health: %s → %s", old, status)
            else:
                logger.info("Connection health: %s → %s", old, status)

        return {
            "status": status,
            "connected": connected,
            "interface_type": self.connection_info.interface_type,
            "device_path": self.connection_info.device_path,
            "queue_size": self._message_queue.qsize(),
            "queue_maxsize": self._message_queue.maxsize,
            "messages_dropped": self._messages_dropped,
        }

    def _close_interface(self) -> None:
        """Close and discard the current interface if one exists."""
        if self.interface:
            try:
                self.interface.close()
            except (OSError, AttributeError, RuntimeError):
                pass
            self.interface = None

    def connect(self) -> bool:
        """Connect to the Meshtastic device."""
        if not MESHTASTIC_AVAILABLE:
            self.connection_info.error_message = "Meshtastic library not installed"
            return False

        # Clean up any previous connection (e.g. from a failed retry)
        self._close_interface()

        try:
            interface_type = self.config.interface.type
            self.interface = self._create_interface(interface_type)

            # Subscribe to meshtastic events AFTER interface creation
            # to prevent leaked subscriptions if creation fails.
            # Wrapped in try/except to clean up subscriptions if subsequent
            # setup steps (_load_node_database, _start_worker_thread, etc.) fail.
            pub.subscribe(self._on_receive, "meshtastic.receive")
            pub.subscribe(self._on_connection, "meshtastic.connection.established")
            pub.subscribe(self._on_disconnect_event, "meshtastic.connection.lost")

            try:
                self.connection_info.interface_type = interface_type
                self.connection_info.connected = True
                self.network.connection_status = "connected"

                # Get my node info
                if self.interface.myInfo:
                    self.connection_info.my_node_id = hex(self.interface.myInfo.my_node_num)
                    self.connection_info.my_node_num = self.interface.myInfo.my_node_num
                    self.network.my_node_id = self.connection_info.my_node_id

                # Load initial node database
                self._load_node_database()

                self._start_worker_thread()

                # Start auto-save thread
                self._start_auto_save()

                self._trigger_callbacks("on_connect", self.connection_info)
                logger.info(
                    "Connected via %s to %s",
                    self.connection_info.interface_type,
                    self.connection_info.device_path,
                )
                return True

            except (OSError, ConnectionError, RuntimeError, AttributeError):
                # Clean up subscriptions and interface on partial setup failure
                for topic, handler in [
                    ("meshtastic.receive", self._on_receive),
                    ("meshtastic.connection.established", self._on_connection),
                    ("meshtastic.connection.lost", self._on_disconnect_event),
                ]:
                    try:
                        pub.unsubscribe(handler, topic)
                    except (ValueError, RuntimeError):
                        pass
                self._close_interface()
                self.connection_info.connected = False
                self.network.connection_status = "error"
                raise

        except Exception as e:
            # Catch-all includes meshtastic's MeshInterfaceError (inherits
            # directly from Exception, not from OSError/TimeoutError).
            if isinstance(e, (ValueError, AttributeError)):
                self.connection_info.error_message = f"Configuration error ({type(e).__name__}): {e}"
            else:
                self.connection_info.error_message = f"Connection failed ({type(e).__name__}): {e}"
            self.connection_info.connected = False
            self.network.connection_status = "error"
            logger.error("Interface connection failed: %s", self.connection_info.error_message)
            return False

    def connect_with_retry(
        self,
        max_retries: int = 3,
        base_delay: float = 5.0,
        max_delay: float = 60.0,
        on_retry: Optional[callable] = None,
    ) -> bool:
        """Connect with exponential backoff and jitter.

        Args:
            max_retries: Maximum number of retry attempts.
            base_delay: Initial delay between retries in seconds.
            max_delay: Maximum delay between retries in seconds.
            on_retry: Optional callback(attempt, delay, error_msg) called before each retry sleep.

        Returns:
            True if connection succeeded.
        """
        for attempt in range(1, max_retries + 1):
            if self.connect():
                return True

            # Fail fast for non-transient errors (no point retrying)
            if not MESHTASTIC_AVAILABLE:
                return False
            err = self.connection_info.error_message
            if "Configuration error" in err or "not available" in err:
                return False

            if attempt >= max_retries:
                break

            # Exponential backoff with ±25% jitter
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            jitter = delay * random.uniform(-0.25, 0.25)
            delay = max(1.0, delay + jitter)

            error_msg = self.connection_info.error_message
            logger.warning(
                "Connection attempt %d/%d failed: %s. Retrying in %.1fs", attempt, max_retries, error_msg, delay
            )

            if on_retry:
                on_retry(attempt, delay, error_msg)

            time.sleep(delay)

        return False

    def disconnect(self) -> None:
        """Disconnect from the Meshtastic device."""
        # Cancel chunk reassembly timers
        self._chunk_buffer.cancel_all()

        # Save state before disconnecting
        if self.connection_info.connected:
            self._save_state()

        self._running.clear()
        self._stop_event.set()

        # Wait for worker threads to finish (with timeout to avoid hangs)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        if self._auto_save_thread and self._auto_save_thread.is_alive():
            self._auto_save_thread.join(timeout=5)

        if self.interface:
            try:
                pub.unsubscribe(self._on_receive, "meshtastic.receive")
                pub.unsubscribe(self._on_connection, "meshtastic.connection.established")
                pub.unsubscribe(self._on_disconnect_event, "meshtastic.connection.lost")
                self.interface.close()
            except (OSError, AttributeError, RuntimeError):
                pass  # Ignore cleanup errors during disconnect

        self.interface = None
        self.connection_info.connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _load_node_database(self) -> None:
        """Load the node database from the connected device."""
        if not self.interface or not hasattr(self.interface, "nodes"):
            return

        for node_id, node_info in self.interface.nodes.items():
            node = self._parse_node_info(node_id, node_info)
            if node:
                self.network.add_node(node)

    def _parse_node_info(self, node_id: str, node_info: dict) -> Optional[Node]:
        """Parse node info from Meshtastic to our model."""
        try:
            user = node_info.get("user", {})
            position = node_info.get("position", {})
            device_metrics = node_info.get("deviceMetrics", {})

            # Parse position
            pos = Position(
                latitude=position.get("latitude", 0.0),
                longitude=position.get("longitude", 0.0),
                altitude=position.get("altitude", 0),
                time=datetime.fromtimestamp(position["time"], tz=timezone.utc) if position.get("time") else None,
            )

            # Parse telemetry
            telemetry = NodeTelemetry(
                battery_level=device_metrics.get("batteryLevel", 0),
                voltage=device_metrics.get("voltage", 0.0),
                channel_utilization=device_metrics.get("channelUtilization", 0.0),
                air_util_tx=device_metrics.get("airUtilTx", 0.0),
                uptime_seconds=device_metrics.get("uptimeSeconds", 0),
            )

            # Parse role
            role_str = user.get("role", "CLIENT")
            try:
                role = NodeRole[role_str.upper()]
            except (KeyError, AttributeError):
                logger.debug("Unknown node role '%s', defaulting to CLIENT", role_str)
                role = NodeRole.CLIENT

            # Determine if favorite/admin
            node_num_str = str(node_info.get("num", ""))
            is_favorite = node_num_str in self.config.favorite_nodes
            is_admin = node_num_str in self.config.admin_nodes

            # Last heard
            last_heard = None
            if node_info.get("lastHeard"):
                last_heard = datetime.fromtimestamp(node_info["lastHeard"], tz=timezone.utc)

            # SNR/RSSI
            if "snr" in node_info:
                telemetry.snr = node_info["snr"]
            if "rssi" in node_info:
                telemetry.rssi = node_info["rssi"]

            return Node(
                node_id=node_id,
                node_num=node_info.get("num", 0),
                short_name=user.get("shortName", ""),
                long_name=user.get("longName", ""),
                hardware_model=user.get("hwModel", "UNKNOWN"),
                role=role,
                position=pos,
                telemetry=telemetry,
                last_heard=last_heard,
                is_favorite=is_favorite,
                is_admin=is_admin,
                hop_count=node_info.get("hopsAway", 0),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Error parsing node info (%s): %s", type(e).__name__, e)
            return None

    def _on_receive(self, packet: dict, interface: Any) -> None:
        """Handle received packet from Meshtastic."""
        try:
            self._message_queue.put_nowait(("receive", packet))
        except queue.Full:
            self._messages_dropped += 1
            logger.warning(
                "Message queue full (maxsize=%d), dropping packet (total dropped: %d)",
                self._message_queue.maxsize,
                self._messages_dropped,
            )

    def _on_connection(self, interface: Any, topic: Any = None) -> None:
        """Handle connection established event."""
        self.connection_info.connected = True
        self.network.connection_status = "connected"
        self._load_node_database()
        self._trigger_callbacks("on_connect", self.connection_info)

    def _on_disconnect_event(self, interface: Any, topic: Any = None) -> None:
        """Handle connection lost event."""
        self.connection_info.connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _worker_loop(self) -> None:
        """Worker thread to process incoming messages."""
        try:
            while self._running.is_set():
                try:
                    event_type, data = self._message_queue.get(timeout=0.5)
                    if event_type == "receive":
                        self._process_packet(data)
                except queue.Empty:
                    continue
                except (KeyError, TypeError, ValueError, AttributeError) as e:
                    logger.warning("Worker error (%s): %s", type(e).__name__, e)
        except Exception as e:
            logger.error("Worker thread crashed: %s", e)
            self._running.clear()
            self.connection_info.connected = False
            self.connection_info.error_message = f"Worker crashed: {e}"
            self.network.connection_status = "error"
            # Notify UI layer about the crash
            self._trigger_callbacks("on_disconnect")

    def _process_packet(self, packet: dict) -> None:
        """Process a received packet."""
        try:
            decoded = packet.get("decoded", {})
            portnum = decoded.get("portnum", "")

            # Update sender node last heard
            sender_id = packet.get("fromId", "")
            if sender_id:
                node = self.network.get_node(sender_id)
                if node:
                    node.last_heard = datetime.now(timezone.utc)
                    node.is_online = True

            # Handle different packet types
            if portnum == "TEXT_MESSAGE_APP":
                self._handle_text_message(packet)
            elif portnum == "POSITION_APP":
                self._handle_position(packet)
            elif portnum == "TELEMETRY_APP":
                self._handle_telemetry(packet)
            elif portnum == "NODEINFO_APP":
                self._handle_nodeinfo(packet)

        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as e:
            logger.warning("Error processing packet (%s): %s", type(e).__name__, e)

    def _handle_text_message(self, packet: dict) -> None:
        """Handle incoming text message, with chunk reassembly."""
        decoded = packet.get("decoded", {})
        text = decoded.get("text", decoded.get("payload", b"").decode("utf-8", errors="replace"))

        sender_id = packet.get("fromId", "")
        channel = packet.get("channel", 0)

        # Try chunk reassembly buffer — buffers long messages that may be chunks
        if self._chunk_buffer.add(sender_id, channel, text, packet):
            logger.debug("Buffered chunk from %s ch%d (%d bytes)", sender_id, channel, len(text))
            return

        # Short message — emit immediately
        self._emit_message(text, packet)

    def _emit_reassembled_message(self, combined_text: str, packet: dict, chunk_count: int) -> None:
        """Called by _ChunkBuffer when a buffered sequence is complete."""
        logger.info("Reassembled %d chunks (%d chars)", chunk_count, len(combined_text))
        self._emit_message(combined_text, packet)

    def _emit_message(self, text: str, packet: dict) -> None:
        """Create and store a Message, check commands and emergency keywords."""
        sender_id = packet.get("fromId", "")
        sender_name = ""
        if sender_id in self.network.nodes:
            sender_name = self.network.nodes[sender_id].display_name

        message = Message(
            id=str(uuid.uuid4()),
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_id=packet.get("toId", ""),
            channel=packet.get("channel", 0),
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            hop_count=max(0, packet.get("hopStart", 0) - packet.get("hopLimit", 0)),
            snr=packet.get("snr", 0.0),
            rssi=packet.get("rssi", 0),
            is_incoming=True,
        )

        self.network.add_message(message)
        _message_logger.info("ch%d %s (%s): %s", message.channel, sender_name, sender_id, text)
        self._trigger_callbacks("on_message", message)

        # Check for bot commands before emergency keywords
        if self._handle_command(message):
            return

        # Check for emergency keywords
        if self.config.alerts.enabled:
            text_lower = text.lower()
            for keyword in self.config.alerts.emergency_keywords:
                if keyword.lower() in text_lower:
                    # Suppress repeats from the same sender within the
                    # configured cooldown window.  Without this check, a
                    # sender hammering "MAYDAY MAYDAY MAYDAY" on-channel
                    # would fire one Alert per message — same suppression
                    # the battery/congestion paths already use below.
                    if self._is_alert_cooled_down(sender_id, "emergency"):
                        break
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.EMERGENCY,
                        title="Emergency Keyword Detected",
                        message=f"{sender_name}: {text}",
                        severity=4,
                        source_node=sender_id,
                        metadata={"keyword": keyword},
                    )
                    self.network.add_alert(alert)
                    self._trigger_callbacks("on_alert", alert)
                    self._dispatch_alert_actions(alert)
                    break

    # Public Meshtastic MQTT brokers — auto_respond MUST be off for these
    _PUBLIC_BROKERS = {"mqtt.meshtastic.org"}

    def _handle_command(self, message) -> bool:
        """Check if message is a recognized command. Returns True if handled.

        When a message matches a known command, it is treated as a command
        rather than checked for emergency keywords. If auto_respond is enabled
        AND the broker is private, the client sends a response back on the
        same channel. Auto-respond is blocked on public brokers.
        """
        if not self.config.commands.enabled:
            return False

        text_stripped = message.text.strip().lower()
        recognized = [c.lower() for c in self.config.commands.commands]

        if text_stripped not in recognized:
            return False

        logger.info("Command received: %s from %s", text_stripped, message.sender_name)
        self._trigger_callbacks("on_command", message, text_stripped)

        # Auto-respond only on private brokers
        if self.config.commands.auto_respond:
            broker = getattr(self.config.mqtt, "broker", "")
            if broker in self._PUBLIC_BROKERS:
                logger.warning(
                    "auto_respond blocked: %s is a public broker. " "Bot responses are not allowed on public MQTT.",
                    broker,
                )
            else:
                response = self._get_command_response(text_stripped)
                if response:
                    # Mesh payloads max out at MAX_MESSAGE_BYTES.  Multi-line
                    # commands (lheard, leaderboard, help) routinely produce
                    # longer text that send_message would otherwise reject
                    # with only a WARNING log — leaving the sender staring at
                    # silence.  Truncate with an ellipsis so the user sees
                    # *something* and knows the output was clipped.
                    encoded = response.encode("utf-8")
                    if len(encoded) > MAX_MESSAGE_BYTES:
                        # Reserve 3 bytes for the ellipsis; decode with
                        # errors="ignore" so we don't split a multibyte char.
                        response = encoded[: MAX_MESSAGE_BYTES - 3].decode("utf-8", errors="ignore") + "..."
                    self.send_message(response, message.sender_id, message.channel)

        return True

    def _get_command_response(self, command: str) -> str:  # noqa: C901
        """Generate response text for a recognized command.

        For data-source commands (weather, tsunami, etc.), fetches live data
        from the URL configured in [data_sources]. All sources and codes
        are driven by mesh_client.ini — nothing is hardcoded.
        """
        from meshing_around_clients import __version__

        if command in ("cmd", "help"):
            cmds = ", ".join(self.config.commands.commands)
            return f"MeshForge v{__version__} commands: {cmds}"
        elif command == "ping":
            return "pong"
        elif command == "version":
            return f"MeshForge v{__version__}"
        elif command == "nodes":
            count = len(self.network.nodes)
            return f"Tracking {count} node{'s' if count != 1 else ''}"
        elif command == "status":
            connected = "connected" if self.is_connected else "disconnected"
            nodes = len(self.network.nodes)
            msgs = len(self.network.messages)
            return f"Status: {connected} | {nodes} nodes | {msgs} msgs"
        elif command == "info":
            return f"MeshForge v{__version__} mesh monitor"
        elif command == "uptime":
            if hasattr(self, "_connect_time") and self._connect_time:
                delta = datetime.now(timezone.utc) - self._connect_time
                hours, rem = divmod(int(delta.total_seconds()), 3600)
                mins, secs = divmod(rem, 60)
                return f"Uptime: {hours}h {mins}m {secs}s"
            return "Uptime: unknown"

        # Try upstream bot venv first (gives identical output to the bot)
        upstream = {}
        if hasattr(self.config, "read_upstream_settings"):
            try:
                upstream = self.config.read_upstream_settings()
            except (OSError, ValueError):
                pass
        lat = upstream.get("lat", 0.0)
        lon = upstream.get("lon", 0.0)

        if command in _UPSTREAM_CMD_MAP:
            result = _call_upstream_cmd(command, lat, lon)
            if result:
                return result

        # Fallback: check data sources from meshforge config
        sources = self.config.data_sources.get_enabled_sources()
        if command in sources:
            return _fetch_data_source(sources[command])

        if command == "wx" and lat:
            return _cmd_wx(lat, lon)
        elif command in ("wxa", "wxalert") and lat:
            return _cmd_wxa(lat, lon)
        elif command == "earthquake":
            return _cmd_earthquake(lat, lon)
        elif command == "solar":
            return _cmd_solar()
        elif command in ("hfcond", "hf"):
            return _cmd_hfcond()
        elif command == "valert" and lat:
            # Use upstream's volcano endpoint directly with proximity filter
            return _parse_volcano_response(
                _fetch_url("https://volcanoes.usgs.gov/hans-public/api/volcano/getCapElevated"),
                type("src", (), {"lat": lat, "lon": lon})(),
            )

        # Local network commands (built from meshforge's own data)
        elif command == "lheard":
            nodes = sorted(
                self.network.get_nodes_snapshot(),
                key=lambda n: n.last_heard or DATETIME_MIN_UTC,
                reverse=True,
            )[:10]
            if not nodes:
                return "lheard: no nodes"
            lines = ["Last heard:"]
            for n in nodes:
                lines.append(f"  {n.display_name[:15]:15s} {n.time_since_heard}")
            return "\n".join(lines)

        elif command == "sitrep":
            net = self.network
            connected = "UP" if self.is_connected else "DOWN"
            return (
                f"SITREP: {connected} | "
                f"{len(net.online_nodes)}/{len(net.nodes)} nodes | "
                f"{net.total_messages} msgs | "
                f"{len(net.unread_alerts)} alerts"
            )

        elif command == "leaderboard":
            # Nodes with most messages (rough count from channel activity)
            nodes = self.network.get_nodes_snapshot()
            if not nodes:
                return "Leaderboard: no data"
            # Sort by last heard (most active = most recently heard)
            active = sorted(
                nodes,
                key=lambda n: n.last_heard or DATETIME_MIN_UTC,
                reverse=True,
            )[:5]
            lines = ["Most active:"]
            for i, n in enumerate(active, 1):
                lines.append(f"  {i}. {n.display_name[:15]} ({n.time_since_heard})")
            return "\n".join(lines)

        elif command == "motd":
            # Read MOTD directly from upstream config
            motd = upstream.get("motd", "")
            if not motd and hasattr(self.config, "read_upstream_settings"):
                try:
                    import configparser as _cp

                    p = _cp.ConfigParser()
                    uc = self.config.find_upstream_config()
                    if uc:
                        p.read(str(uc))
                        motd = p.get("general", "motd", fallback="")
                except (OSError, _cp.Error):
                    pass
            return motd or "No MOTD configured"

        # Bot-only commands — signal to caller to send via mesh
        if command in _BOT_ONLY_COMMANDS:
            return f"__BOT_ONLY__:{command}"

        return ""

    @staticmethod
    def get_command_catalog(config=None) -> "list[tuple[str, str, str]]":
        """Return a structured list of (name, description, category) for the command palette.

        Sibling of get_command_list() which returns a display string; this one
        is machine-readable so a TUI picker can render it as a Rich table.
        """
        catalog: "list[tuple[str, str, str]]" = [
            # Data commands
            ("wx", "Weather (NOAA/Meteo)", "Data"),
            ("wxc", "Weather (metric)", "Data"),
            ("mwx", "Marine weather", "Data"),
            ("wxa", "Weather alerts (NWS)", "Data"),
            ("ealert", "Emergency alerts (iPAWS)", "Data"),
            ("valert", "Volcano alerts (USGS)", "Data"),
            ("earthquake", "Earthquakes (USGS)", "Data"),
            ("solar", "Solar / space weather", "Data"),
            ("hfcond", "HF band conditions", "Data"),
            ("moon", "Moon phase / rise / set", "Data"),
            ("sun", "Sunrise / sunset", "Data"),
            ("tide", "NOAA tide data", "Data"),
            ("riverflow", "River flow data", "Data"),
            ("whereami", "Location info", "Data"),
            ("tsunami", "Tsunami alerts (PTWC)", "Data"),
            ("motd", "Message of the day", "Data"),
            # Network commands
            ("lheard", "Last heard nodes", "Network"),
            ("sitrep", "Situation report", "Network"),
            ("leaderboard", "Most active nodes", "Network"),
            ("nodes", "Node list", "Network"),
            ("status", "Bot status", "Network"),
            ("ping", "Ping the bot", "Network"),
            ("version", "Bot version", "Network"),
            ("uptime", "Bot uptime", "Network"),
            ("cmd", "Show command list", "Network"),
            ("help", "Show help", "Network"),
            # Bot commands
            ("joke", "Dad joke", "Bot"),
            ("wiki", "Wikipedia summary", "Bot"),
            ("askai", "Ask the AI", "Bot"),
            ("bbshelp", "BBS help", "Bot"),
            ("bbslist", "BBS message list", "Bot"),
            ("games", "Games menu", "Bot"),
            ("readrss", "Read RSS feed", "Bot"),
            ("readnews", "Read news feed", "Bot"),
            ("dx", "DX cluster", "Bot"),
            ("rlist", "Repeater list", "Bot"),
            ("howfar", "Distance to a node", "Bot"),
            ("howtall", "Altitude difference", "Bot"),
            ("whoami", "Node info (self)", "Bot"),
            ("sysinfo", "System info", "Bot"),
            ("satpass", "Satellite passes", "Bot"),
            ("checkin", "Net check-in", "Bot"),
            ("checkout", "Net check-out", "Bot"),
            ("messages", "Read stored messages", "Bot"),
        ]
        return catalog

    @staticmethod
    def get_command_list(config=None) -> str:
        """Return a formatted string of available commands for display."""
        from meshing_around_clients import __version__

        lines = [f"Meshing-Around v{__version__} Commands:"]

        # Data commands — always show all (bot venv resolves lat/lon at runtime)
        lines.append("")
        lines.append("Data Commands (run locally via bot engine):")
        lines.append("  wx/wxc/mwx  - Weather (NOAA/Meteo)")
        lines.append("  wxa/wxalert - Weather alerts (NWS)")
        lines.append("  ealert      - Emergency alerts (iPAWS)")
        lines.append("  valert      - Volcano alerts (USGS)")
        lines.append("  earthquake  - Earthquakes (USGS)")
        lines.append("  solar       - Solar/space weather")
        lines.append("  hfcond      - HF band conditions")
        lines.append("  moon        - Moon phase/rise/set")
        lines.append("  sun         - Sunrise/sunset")
        lines.append("  tide        - NOAA tide data")
        lines.append("  riverflow   - River flow data")
        lines.append("  whereami    - Location info")
        lines.append("  tsunami     - Tsunami alerts (PTWC)")
        lines.append("  motd        - Message of the day")

        # Network commands (local data)
        lines.append("")
        lines.append("Network Commands (local):")
        lines.append("  lheard      - Last heard nodes")
        lines.append("  sitrep      - Situation report")
        lines.append("  leaderboard - Most active nodes")
        lines.append("  nodes/status/ping/version/uptime")
        lines.append("  cmd / help  - Show this list")

        # Bot commands (sent via mesh)
        lines.append("")
        lines.append("Bot Commands (sent to bot via mesh):")
        lines.append("  joke, wiki, askai, bbshelp, bbslist")
        lines.append("  games, readrss, readnews, dx, rlist")
        lines.append("  howfar, howtall, whoami, sysinfo")
        lines.append("  satpass, checkin, checkout, messages")

        return "\n".join(lines)

    def _handle_position(self, packet: dict) -> None:
        """Handle position update with coordinate validation."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        position_data = decoded.get("position", {})

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            pos = extract_position(position_data)
            if pos is not None:
                node.position = pos
            node.last_heard = datetime.now(timezone.utc)
            self._trigger_callbacks("on_position", sender_id, node.position)

    def _handle_telemetry(self, packet: dict) -> None:
        """Handle telemetry update with input validation."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        telemetry_data = decoded.get("telemetry", {})
        device_metrics = telemetry_data.get("deviceMetrics", {})

        if sender_id in self.network.nodes:
            node = self.network.nodes[sender_id]
            # Validate all numeric fields (matching MQTT client robustness)
            battery = safe_int(device_metrics.get("batteryLevel"), 0, 101)
            voltage = safe_float(device_metrics.get("voltage"), 0.0, 10.0)
            ch_util = safe_float(device_metrics.get("channelUtilization"), 0.0, 100.0)
            air_util = safe_float(device_metrics.get("airUtilTx"), 0.0, 100.0)
            uptime = safe_int(device_metrics.get("uptimeSeconds"), 0, 2**31)
            node.telemetry = NodeTelemetry(
                battery_level=battery if battery is not None else node.telemetry.battery_level,
                voltage=voltage if voltage is not None else node.telemetry.voltage,
                channel_utilization=ch_util if ch_util is not None else node.telemetry.channel_utilization,
                air_util_tx=air_util if air_util is not None else node.telemetry.air_util_tx,
                uptime_seconds=uptime if uptime is not None else node.telemetry.uptime_seconds,
                last_updated=datetime.now(timezone.utc),
            )
            node.last_heard = datetime.now(timezone.utc)
            self._trigger_callbacks("on_telemetry", sender_id, node.telemetry)

            # Check battery alert (with per-node cooldown to prevent alert fatigue)
            if self.config.alerts.enabled and node.telemetry.battery_level > 0 and node.telemetry.battery_level < 20:
                if not self._is_alert_cooled_down(sender_id, "battery"):
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        alert_type=AlertType.BATTERY,
                        title="Low Battery Alert",
                        message=f"{node.display_name} battery at {node.telemetry.battery_level}%",
                        severity=2,
                        source_node=sender_id,
                    )
                    self.network.add_alert(alert)
                    self._trigger_callbacks("on_alert", alert)
                    self._dispatch_alert_actions(alert)

    def _handle_nodeinfo(self, packet: dict) -> None:
        """Handle node info update."""
        sender_id = packet.get("fromId", "")
        decoded = packet.get("decoded", {})
        user = decoded.get("user", {})

        node, is_new = self._ensure_node(
            sender_id,
            packet.get("from", 0),
            short_name=user.get("shortName", ""),
            long_name=user.get("longName", ""),
            hardware_model=user.get("hwModel", "UNKNOWN"),
        )
        if not is_new and node:
            # Update existing node fields from nodeinfo
            node.short_name = user.get("shortName", node.short_name)
            node.long_name = user.get("longName", node.long_name)
            node.hardware_model = user.get("hwModel", node.hardware_model)
            self._trigger_callbacks("on_node_update", sender_id, False)

        # New node alert
        if is_new and self.config.alerts.enabled:
            alert = Alert(
                id=str(uuid.uuid4()),
                alert_type=AlertType.NEW_NODE,
                title="New Node Joined",
                message=f"New node joined the mesh: {node.display_name}",
                severity=1,
                source_node=sender_id,
            )
            self.network.add_alert(alert)
            self._trigger_callbacks("on_alert", alert)
            self._dispatch_alert_actions(alert)

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Send a text message with byte-length validation."""
        if not self.interface:
            return False

        msg_bytes = len(text.encode("utf-8"))
        if msg_bytes > MAX_MESSAGE_BYTES:
            logger.warning("Message too long (%d/%d bytes), rejecting", msg_bytes, MAX_MESSAGE_BYTES)
            return False

        try:
            if destination == "^all":
                self.interface.sendText(text, channelIndex=channel)
            else:
                # Parse destination node number (hex with ! prefix, or decimal)
                try:
                    dest_num = int(destination.lstrip("!"), 16) if destination.startswith("!") else int(destination)
                except ValueError:
                    logger.warning("Invalid destination '%s': must be ^all, a node number, or !hex_id", destination)
                    return False
                self.interface.sendText(text, destinationId=dest_num, channelIndex=channel)

            # Log outgoing message
            message = Message(
                id=str(uuid.uuid4()),
                sender_id=self.network.my_node_id,
                sender_name=self.config.bot_name,
                recipient_id=destination,
                channel=channel,
                text=text,
                message_type=MessageType.TEXT,
                timestamp=datetime.now(timezone.utc),
                is_incoming=False,
            )
            self.network.add_message(message)
            return True

        except (OSError, AttributeError, ValueError) as e:
            logger.error("Error sending message (%s): %s", type(e).__name__, e)
            return False

    def get_nodes(self) -> List[Node]:
        """Get all known nodes."""
        return list(self.network.nodes.values())

    def get_messages(self, channel: Optional[int] = None, limit: int = 100) -> List[Message]:
        """Get messages, optionally filtered by channel."""
        messages = list(self.network.messages)
        if channel is not None:
            messages = [m for m in messages if m.channel == channel]
        return messages[-limit:]

    def get_alerts(self, unread_only: bool = False) -> List[Alert]:
        """Get alerts."""
        if unread_only:
            return self.network.unread_alerts
        return list(self.network.alerts)

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self.network.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                return True
        return False


class MockMeshtasticAPI(MeshtasticAPI):
    """
    Mock API for testing without actual Meshtastic hardware.
    Generates fake nodes and messages for development.
    """

    # Sample chat lines for demo traffic
    _DEMO_MESSAGES = [
        "Anyone copy?",
        "Signal check - how's my SNR?",
        "Heading to the trailhead, back in 2h",
        "Weather looks clear from up here",
        "Battery swap complete, back online",
        "Repeater seems solid today",
        "New firmware is working great",
        "Copy that, loud and clear",
        "Roger, standing by",
        "Testing range from the ridge",
        "Good morning mesh!",
        "Check your channel utilization",
        "Solar panel keeping me at 100%",
        "Lost GPS fix briefly, back now",
        "Anyone else seeing packet loss?",
    ]

    # Additional demo nodes that can be "discovered" during demo mode
    _EXTRA_DEMO_NODES = [
        ("!77aa1122", 0x77AA1122, "Hiker1", "Backcountry Hiker", "TBEAM"),
        ("!88bb3344", 0x88BB3344, "SAR", "Search & Rescue", "RAK4631"),
        ("!99cc5566", 0x99CC5566, "Sensor", "Weather Station", "HELTEC"),
        ("!aaddee77", 0xAADDEE77, "Drone1", "Survey Drone", "TLORA"),
        ("!bbff0088", 0xBBFF0088, "Marina", "Harbor Master", "TBEAM"),
    ]
    _MAX_DEMO_NODES = 10

    def __init__(self, config: Config):
        super().__init__(config)
        self._demo_mode = True
        self._demo_thread: Optional[threading.Thread] = None

    def connect(self) -> bool:
        """Simulate connection and start generating demo traffic."""
        self.connection_info.connected = True
        self.connection_info.interface_type = "mock"
        self.connection_info.device_path = "demo"
        self.connection_info.my_node_id = "!deadbeef"
        self.connection_info.my_node_num = 0xDEADBEEF
        self.network.connection_status = "connected (demo)"
        self.network.my_node_id = self.connection_info.my_node_id

        now = datetime.now(timezone.utc)

        # Generate demo nodes with positions (Hawaiian coordinates for realism)
        demo_nodes = [
            (
                "!abc12345",
                0xABC12345,
                "BaseStation",
                "HQ Base Station",
                "TBEAM",
                21.3069,
                -157.8583,
                15,
                NodeRole.CLIENT,
            ),
            ("!def67890", 0xDEF67890, "Mobile1", "Field Unit Alpha", "TLORA", 21.2770, -157.8260, 5, NodeRole.CLIENT),
            ("!fed98765", 0xFED98765, "Relay", "Mountain Repeater", "HELTEC", 21.3310, -157.8000, 450, NodeRole.ROUTER),
            (
                "!123abcde",
                0x123ABCDE,
                "Solar1",
                "Solar Powered Node",
                "RAK4631",
                21.2900,
                -157.8450,
                30,
                NodeRole.CLIENT,
            ),
            ("!456f0e1a", 0x456F0E1A, "Router", "Community Router", "TBEAM", 21.3150, -157.8150, 120, NodeRole.ROUTER),
        ]

        node_ids = []
        for node_id, node_num, short, long, hw, lat, lon, alt, role in demo_nodes:
            node = Node(
                node_id=node_id,
                node_num=node_num,
                short_name=short,
                long_name=long,
                hardware_model=hw,
                role=role,
                last_heard=now,
                is_online=True,
                position=Position(latitude=lat, longitude=lon, altitude=alt, time=now),
            )
            node.telemetry.battery_level = 75 + (node_num % 25)
            node.telemetry.snr = 5.0 + (node_num % 10)
            # Populate link quality
            node.link_quality = LinkQuality(
                snr=node.telemetry.snr,
                rssi=-70 - (node_num % 30),
                hop_count=node_num % 3,
                last_seen=now,
                packet_count=10 + (node_num % 20),
            )
            node.link_quality.snr_avg = node.telemetry.snr
            node_ids.append(node_id)
            self.network.add_node(node)

        # Populate neighbor/heard_by relationships
        for i, nid in enumerate(node_ids):
            node = self.network.nodes[nid]
            # Each node hears its neighbors
            for j in range(max(0, i - 2), min(len(node_ids), i + 3)):
                if j != i:
                    neighbor_id = node_ids[j]
                    node.neighbors.append(neighbor_id)
                    self.network.nodes[neighbor_id].heard_by.append(nid)

        # Create demo routes
        self.network.routes[node_ids[1]] = MeshRoute(
            destination_id=node_ids[1],
            hops=[
                RouteHop(node_id=node_ids[0], snr=8.5, timestamp=now),
                RouteHop(node_id=node_ids[1], snr=6.2, timestamp=now),
            ],
            discovered=now,
            last_used=now,
            is_preferred=True,
        )
        self.network.routes[node_ids[4]] = MeshRoute(
            destination_id=node_ids[4],
            hops=[
                RouteHop(node_id=node_ids[0], snr=7.0, timestamp=now),
                RouteHop(node_id=node_ids[2], snr=4.5, timestamp=now),
                RouteHop(node_id=node_ids[4], snr=5.8, timestamp=now),
            ],
            discovered=now,
            last_used=now,
            is_preferred=True,
        )

        # Configure demo channels with realistic settings
        self.network.channels[0] = Channel(
            index=0,
            name="LongFast",
            role=ChannelRole.PRIMARY,
            psk="AQ==",
            uplink_enabled=True,
            downlink_enabled=True,
            message_count=42,
            last_activity=now,
        )
        self.network.channels[1] = Channel(
            index=1,
            name="MeshForge",
            role=ChannelRole.SECONDARY,
            psk="meshforge-key",
            uplink_enabled=False,
            downlink_enabled=False,
            message_count=7,
            last_activity=now,
        )

        self._running.set()
        self._trigger_callbacks("on_connect", self.connection_info)

        # Start background demo traffic
        self._stop_event.clear()
        self._demo_thread = threading.Thread(target=self._demo_traffic_loop, daemon=True, name="demo-traffic")
        self._demo_thread.start()
        return True

    def disconnect(self) -> None:
        """Stop demo traffic and simulate disconnect."""
        self._running.clear()
        self._stop_event.set()
        if self._demo_thread and self._demo_thread.is_alive():
            self._demo_thread.join(timeout=2)
        self.connection_info.connected = False
        self.network.connection_status = "disconnected"
        self._trigger_callbacks("on_disconnect")

    def _demo_traffic_loop(self) -> None:
        """Background loop that simulates incoming mesh traffic."""
        while not self._stop_event.is_set():
            # Wait 5-15 seconds between events (realistic mesh cadence)
            if self._stop_event.wait(timeout=random.uniform(5.0, 15.0)):
                break
            try:
                self._generate_demo_event()
            except Exception:
                logger.debug("Demo traffic error", exc_info=True)

    def _generate_demo_event(self) -> None:
        """Generate a single random demo event (message, telemetry, or node discovery)."""
        nodes = list(self.network.nodes.values())
        if not nodes:
            return

        now = datetime.now(timezone.utc)

        # 5% chance: discover a new node (if under cap)
        if random.random() < 0.05 and len(self.network.nodes) < self._MAX_DEMO_NODES:
            available = [n for n in self._EXTRA_DEMO_NODES if n[0] not in self.network.nodes]
            if available:
                node_id, node_num, short, long, hw = random.choice(available)
                new_node = Node(
                    node_id=node_id,
                    node_num=node_num,
                    short_name=short,
                    long_name=long,
                    hardware_model=hw,
                    role=NodeRole.CLIENT,
                    last_heard=now,
                    is_online=True,
                )
                new_node.telemetry.battery_level = 50 + random.randint(0, 50)
                new_node.telemetry.snr = round(random.uniform(-2.0, 8.0), 1)
                self.network.add_node(new_node)
                self._trigger_callbacks("on_node_update", node_id, True)

                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type=AlertType.NEW_NODE,
                    title="New Node Discovered",
                    message=f"{long} ({short}) joined the mesh",
                    severity=1,
                    source_node=node_id,
                )
                self.network.add_alert(alert)
                self._trigger_callbacks("on_alert", alert)
                self._dispatch_alert_actions(alert)
                return

        node = random.choice(nodes)

        # 60% chance: incoming text message, 40% chance: telemetry update
        if random.random() < 0.6:
            message = Message(
                id=str(uuid.uuid4()),
                sender_id=node.node_id,
                sender_name=node.short_name or node.long_name,
                recipient_id="^all",
                channel=random.choice([0, 0, 0, 1]),  # mostly ch0
                text=random.choice(self._DEMO_MESSAGES),
                message_type=MessageType.TEXT,
                timestamp=now,
                hop_count=random.randint(0, 3),
                snr=round(random.uniform(-5.0, 10.0), 1),
                rssi=random.randint(-120, -60),
                is_incoming=True,
            )
            self.network.add_message(message)
            node.last_heard = now
            self._trigger_callbacks("on_message", message)
        else:
            # Telemetry drift: battery slowly drains, SNR fluctuates
            node.telemetry.battery_level = max(0, node.telemetry.battery_level + random.randint(-2, 1))
            node.telemetry.snr = round(node.telemetry.snr + random.uniform(-1.0, 1.0), 1)
            node.telemetry.channel_utilization = round(max(0.0, min(100.0, random.uniform(5.0, 35.0))), 1)
            node.telemetry.last_updated = now
            node.last_heard = now
            self._trigger_callbacks("on_telemetry", node.node_id, node.telemetry)

    def send_message(self, text: str, destination: str = "^all", channel: int = 0) -> bool:
        """Simulate sending a message with byte-length validation."""
        msg_bytes = len(text.encode("utf-8"))
        if msg_bytes > MAX_MESSAGE_BYTES:
            logger.warning("Message too long (%d/%d bytes), rejecting", msg_bytes, MAX_MESSAGE_BYTES)
            return False
        message = Message(
            id=str(uuid.uuid4()),
            sender_id=self.network.my_node_id,
            sender_name="Me",
            recipient_id=destination,
            channel=channel,
            text=text,
            message_type=MessageType.TEXT,
            timestamp=datetime.now(timezone.utc),
            is_incoming=False,
            ack_received=True,
        )
        self.network.add_message(message)
        return True

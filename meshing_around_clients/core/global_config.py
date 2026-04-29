"""
MeshForge ecosystem-wide shared identity / config layer.

Reads ~/.config/meshforge/global.ini — the canonical source of truth for
values that span multiple MeshForge apps (NOC, maps, meshing_around,
MeshAnchor). Each app reads it as a fallback BEFORE its own per-app
config, so per-app values still win. Missing file → no-op, current
behavior preserved.

The contract is documented in ``docs/global_config.md`` (this repo) and
mirrored in the other ecosystem repos as they adopt it.

Schema sections kept deliberately narrow — only domain-shared values:

  [node]      identity surfaces (callsign, display names, node id)
  [mqtt]      broker connection (most apps connect to the same broker)
  [region]    region preset + operator home coords (used by maps + alerts)
  [paths]     shared filesystem locations (data dir, cache dir)

Per-app feature toggles, schemas, and UI preferences DO NOT belong here.
"""

import configparser
import logging
import os
import pathlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Filename is fixed across the ecosystem. Path resolution honors SUDO_USER
# per MF001 — running under sudo must NOT read /root/.config/...
GLOBAL_CONFIG_FILENAME = "global.ini"
GLOBAL_CONFIG_DIRNAME = "meshforge"


def get_real_user_home() -> Path:
    """Return the invoking user's home, even under sudo (MF001)."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return pathlib.Path(f"/home/{sudo_user}")
    return pathlib.Path.home()


def global_config_path() -> Path:
    """Canonical path: ``~/.config/meshforge/global.ini``."""
    return get_real_user_home() / ".config" / GLOBAL_CONFIG_DIRNAME / GLOBAL_CONFIG_FILENAME


@dataclass
class GlobalNode:
    """Operator identity that all apps share."""

    short_name: str = ""
    long_name: str = ""
    node_id: str = ""  # e.g. "!a3b2c1d4"


@dataclass
class GlobalMqtt:
    """Shared broker connection. Apps may still override per-instance."""

    broker: str = ""
    port: int = 0  # 0 means "unset, let the per-app default win"
    use_tls: Optional[bool] = None
    username: str = ""
    password: str = ""
    topic_root: str = ""


@dataclass
class GlobalRegion:
    """Region preset + operator home coordinates."""

    preset: str = ""  # e.g. "us", "hawaii", "europe", "anz"
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None


@dataclass
class GlobalPaths:
    """Shared filesystem locations."""

    data_dir: str = ""  # e.g. /var/lib/meshforge


@dataclass
class GlobalConfig:
    """Snapshot of ~/.config/meshforge/global.ini."""

    node: GlobalNode = field(default_factory=GlobalNode)
    mqtt: GlobalMqtt = field(default_factory=GlobalMqtt)
    region: GlobalRegion = field(default_factory=GlobalRegion)
    paths: GlobalPaths = field(default_factory=GlobalPaths)
    # True only when the file was actually found and parsed cleanly.
    # Lets callers tell "global said nothing" from "global doesn't exist."
    loaded: bool = False
    source_path: Optional[Path] = None


def _coerce_int(value: object, default: int) -> int:
    """Mirror of core.config._coerce_int — INI values are strings."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, default: Optional[float]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: object) -> Optional[bool]:
    """None when the value is missing/blank; bool otherwise."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s == "":
        return None
    return s in ("true", "yes", "1", "on")


def load_global_config(path: Optional[Path] = None) -> GlobalConfig:
    """Read ``~/.config/meshforge/global.ini`` (or the override path).

    Always returns a :class:`GlobalConfig`. Missing file → all-defaults
    instance with ``loaded=False``. Malformed INI → all-defaults instance
    with ``loaded=False`` and a single DEBUG log line; callers proceed.
    """
    target = Path(path) if path else global_config_path()
    cfg = GlobalConfig(source_path=target)

    if not target.exists():
        return cfg

    parser = configparser.ConfigParser()
    try:
        parser.read(str(target))
    except (configparser.Error, OSError, UnicodeDecodeError) as e:
        # Malformed file shouldn't crash any caller — every app on the Pi
        # would die at boot if global.ini got corrupted. Log + bail.
        logger.debug("MeshForge global.ini parse failed (%s): %s", type(e).__name__, e)
        return cfg

    if parser.has_section("node"):
        cfg.node.short_name = parser.get("node", "short_name", fallback="")
        cfg.node.long_name = parser.get("node", "long_name", fallback="")
        cfg.node.node_id = parser.get("node", "node_id", fallback="")

    if parser.has_section("mqtt"):
        cfg.mqtt.broker = parser.get("mqtt", "broker", fallback="")
        cfg.mqtt.port = _coerce_int(parser.get("mqtt", "port", fallback="0"), 0)
        cfg.mqtt.use_tls = _coerce_bool(parser.get("mqtt", "use_tls", fallback=None))
        cfg.mqtt.username = parser.get("mqtt", "username", fallback="")
        cfg.mqtt.password = parser.get("mqtt", "password", fallback="")
        cfg.mqtt.topic_root = parser.get("mqtt", "topic_root", fallback="")

    if parser.has_section("region"):
        cfg.region.preset = parser.get("region", "preset", fallback="")
        cfg.region.home_lat = _coerce_float(parser.get("region", "home_lat", fallback=None), None)
        cfg.region.home_lon = _coerce_float(parser.get("region", "home_lon", fallback=None), None)

    if parser.has_section("paths"):
        cfg.paths.data_dir = parser.get("paths", "data_dir", fallback="")

    cfg.loaded = True
    return cfg

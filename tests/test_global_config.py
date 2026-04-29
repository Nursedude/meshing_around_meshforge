"""Tests for the MeshForge ecosystem-wide global config layer."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from meshing_around_clients.core.global_config import (
    GLOBAL_CONFIG_DIRNAME,
    GLOBAL_CONFIG_FILENAME,
    GlobalConfig,
    get_real_user_home,
    global_config_path,
    load_global_config,
)


# ---------------------------------------------------------------------------
# Path resolution (MF001 — sudo-aware)
# ---------------------------------------------------------------------------


def test_get_real_user_home_uses_sudo_user():
    with patch.dict(os.environ, {"SUDO_USER": "testuser"}, clear=False):
        home = get_real_user_home()
        assert home == Path("/home/testuser")


def test_get_real_user_home_no_sudo(monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    home = get_real_user_home()
    assert home == Path.home()


def test_global_config_path_layout(monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    p = global_config_path()
    assert p.name == GLOBAL_CONFIG_FILENAME
    assert p.parent.name == GLOBAL_CONFIG_DIRNAME
    assert p.parent.parent.name == ".config"


# ---------------------------------------------------------------------------
# load_global_config — happy path, missing, malformed
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_defaults(tmp_path):
    cfg = load_global_config(tmp_path / "does-not-exist.ini")
    assert isinstance(cfg, GlobalConfig)
    assert cfg.loaded is False
    assert cfg.mqtt.broker == ""
    assert cfg.node.short_name == ""
    assert cfg.region.preset == ""
    assert cfg.paths.data_dir == ""


def test_load_happy_path(tmp_path):
    target = tmp_path / "global.ini"
    target.write_text(textwrap.dedent("""\
        [node]
        short_name = SHWN
        long_name = Shawn (WH6GXZ)
        node_id = !a3b2c1d4

        [mqtt]
        broker = my-broker.local
        port = 1884
        use_tls = true
        username = wh6gxz
        password = secret123
        topic_root = msh/US/HI

        [region]
        preset = hawaii
        home_lat = 21.30
        home_lon = -157.85

        [paths]
        data_dir = /var/lib/meshforge
    """))

    cfg = load_global_config(target)
    assert cfg.loaded is True
    assert cfg.source_path == target

    assert cfg.node.short_name == "SHWN"
    assert cfg.node.long_name == "Shawn (WH6GXZ)"
    assert cfg.node.node_id == "!a3b2c1d4"

    assert cfg.mqtt.broker == "my-broker.local"
    assert cfg.mqtt.port == 1884
    assert cfg.mqtt.use_tls is True
    assert cfg.mqtt.username == "wh6gxz"
    assert cfg.mqtt.password == "secret123"
    assert cfg.mqtt.topic_root == "msh/US/HI"

    assert cfg.region.preset == "hawaii"
    assert cfg.region.home_lat == pytest.approx(21.30)
    assert cfg.region.home_lon == pytest.approx(-157.85)

    assert cfg.paths.data_dir == "/var/lib/meshforge"


def test_load_partial_sections(tmp_path):
    """Missing sections leave defaults; partial sections fill what's there."""
    target = tmp_path / "global.ini"
    target.write_text(textwrap.dedent("""\
        [mqtt]
        broker = only-broker.example
    """))
    cfg = load_global_config(target)
    assert cfg.loaded is True
    assert cfg.mqtt.broker == "only-broker.example"
    assert cfg.mqtt.port == 0  # unset
    assert cfg.mqtt.use_tls is None
    assert cfg.node.node_id == ""
    assert cfg.region.home_lat is None


def test_load_malformed_int_falls_back(tmp_path):
    """Hand-typed garbage in port doesn't crash — MF005 pattern."""
    target = tmp_path / "global.ini"
    target.write_text(textwrap.dedent("""\
        [mqtt]
        broker = b.example
        port = not-a-number
    """))
    cfg = load_global_config(target)
    assert cfg.loaded is True
    assert cfg.mqtt.broker == "b.example"
    assert cfg.mqtt.port == 0  # coerced to default


def test_load_malformed_float_falls_back(tmp_path):
    target = tmp_path / "global.ini"
    target.write_text(textwrap.dedent("""\
        [region]
        home_lat = not-a-float
    """))
    cfg = load_global_config(target)
    assert cfg.loaded is True
    assert cfg.region.home_lat is None


def test_load_garbage_file_does_not_crash(tmp_path):
    """A corrupted/unreadable file logs and returns defaults — never raises."""
    target = tmp_path / "global.ini"
    # Duplicate section header — configparser raises DuplicateSectionError
    target.write_text("[mqtt]\nbroker = a\n[mqtt]\nbroker = b\n")
    cfg = load_global_config(target)
    assert cfg.loaded is False  # parse failed, but no exception bubbled


def test_use_tls_blank_returns_none(tmp_path):
    target = tmp_path / "global.ini"
    target.write_text("[mqtt]\nuse_tls =\n")
    cfg = load_global_config(target)
    assert cfg.mqtt.use_tls is None


# ---------------------------------------------------------------------------
# Config integration — global seeds, per-app overrides
# ---------------------------------------------------------------------------


def test_config_applies_global_defaults(tmp_path, monkeypatch):
    """When per-app INI lacks a key, the global value persists."""
    from meshing_around_clients.core import config as config_mod

    # Point load_global_config at a temp file
    target = tmp_path / "global.ini"
    target.write_text(textwrap.dedent("""\
        [mqtt]
        broker = global-broker.example
        port = 8883
        topic_root = msh/SHARED
    """))

    monkeypatch.setattr(config_mod, "load_global_config", lambda: __import__(
        "meshing_around_clients.core.global_config",
        fromlist=["load_global_config"],
    ).load_global_config(target))

    # Per-app INI is empty (no [mqtt] section) → global values propagate
    per_app = tmp_path / "mesh_client.ini"
    per_app.write_text("")

    cfg = config_mod.Config(str(per_app))
    assert cfg.mqtt.broker == "global-broker.example"
    assert cfg.mqtt.port == 8883
    assert cfg.mqtt.topic_root == "msh/SHARED"


def test_config_per_app_overrides_global(tmp_path, monkeypatch):
    """When per-app INI sets a key, it wins over global."""
    from meshing_around_clients.core import config as config_mod

    target = tmp_path / "global.ini"
    target.write_text(textwrap.dedent("""\
        [mqtt]
        broker = global-broker.example
        port = 8883
    """))
    monkeypatch.setattr(config_mod, "load_global_config", lambda: __import__(
        "meshing_around_clients.core.global_config",
        fromlist=["load_global_config"],
    ).load_global_config(target))

    per_app = tmp_path / "mesh_client.ini"
    per_app.write_text(textwrap.dedent("""\
        [mqtt]
        broker = per-app-broker.example
        port = 1883
    """))

    cfg = config_mod.Config(str(per_app))
    assert cfg.mqtt.broker == "per-app-broker.example"
    assert cfg.mqtt.port == 1883


def test_config_with_no_global_uses_dataclass_defaults(tmp_path, monkeypatch):
    """Missing global.ini → behavior identical to pre-global-config."""
    from meshing_around_clients.core import config as config_mod

    monkeypatch.setattr(config_mod, "load_global_config", lambda: __import__(
        "meshing_around_clients.core.global_config",
        fromlist=["load_global_config"],
    ).load_global_config(tmp_path / "absent.ini"))

    per_app = tmp_path / "mesh_client.ini"
    per_app.write_text("")

    cfg = config_mod.Config(str(per_app))
    # Defaults from MQTTConfig dataclass — unaffected by global
    assert cfg.mqtt.broker == "mqtt.meshtastic.org"

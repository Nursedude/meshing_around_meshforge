# Cross-Repo Topology — MeshForge Ecosystem

> See canonical version at `/opt/meshforge/.claude/foundations/cross_repo_topology.md`

## This Repo's Role (v0.6.0)

**meshing_around_meshforge** is the **Full Companion Client** for the meshing-around bot.

### What belongs HERE:
- Rich TUI monitoring (9 screens: Dashboard, Nodes, Messages, Alerts, Topology, Devices, Log, Config Editor, Help)
- 51 mesh commands (15 data via bot venv, 11 local, 25 bot relay via mesh)
- Config Editor for meshing-around's config.ini (screen 8)
- Smart command routing (local / bot venv / mesh relay)
- 12 alert type definitions (AlertType enum, Alert dataclass)
- AES-256-CTR mesh packet decryption (`core/mesh_crypto.py`)
- MockMeshtasticAPI for hardware-free demo/testing
- MQTT client for standalone mesh monitoring
- Callback/cooldown mixin (`core/callbacks.py`)
- INI-based configuration with upstream config sync

### What belongs in meshforge (NOC):
- Protocol bridging (Meshtastic ↔ RNS), service management, RF tools
- Gateway bridge, MeshCore 3-way routing
- NOC-level alerting (service health, gateway status)

### What belongs in meshforge-maps:
- Interactive Leaflet.js web maps, REST API, topology graphs
- Multi-source collection (Meshtastic, RNS, AREDN, HamClock)
- Health scoring, NOAA alert polygons, analytics
- Standalone or MeshForge plugin via manifest.json

## Local Paths

| Repo | Path | Version |
|------|------|---------|
| meshforge (NOC) | /opt/meshforge | v0.5.5-beta |
| meshforge-maps | /opt/meshforge-maps | v0.7.0-beta |
| meshing_around_meshforge | /opt/meshing_around_meshforge | v0.6.0 |
| meshing-around (upstream) | /opt/meshing-around | v1.9.9.x |

## Integration Points

### NOC imports from this repo
```python
# In meshforge src/utils/mesh_alert_engine.py:
sys.path.insert(0, "/opt/meshing_around_meshforge")
AlertType, Alert = safe_import('meshing_around_clients.core.models', ...)
MockMeshtasticAPI = safe_import('meshing_around_clients.core.meshtastic_api', ...)
MeshPacketProcessor = safe_import('meshing_around_clients.core.mesh_crypto', ...)
```

### This repo calls upstream bot venv
```python
# In meshtastic_api.py _call_upstream_cmd():
/opt/meshing-around/venv/bin/python3 -c "from space import get_moon; print(get_moon(lat, lon))"
```

### This repo reads upstream config
```python
# Config.find_upstream_config() searches:
# 1. /opt/meshing-around/config.ini (primary)
# 2. ~/meshing-around/config.ini
# 3. ./config.ini
```

### Future: Data bridge to meshforge-maps
- Planned: publish node GeoJSON to maps REST API (:8808)
- Planned: subscribe to maps EventBus WebSocket (:8809) for shared MQTT

This repo does NOT depend on the NOC or maps. It runs independently.

## Shared Security Rules

MF001-MF004 apply across all repos. See `.claude/rules/security.md`.

---
name: Meshing Around
description: >
  Meshing Around mesh client assistant for Meshtastic monitoring, alerting, and MQTT integration.
  Handles alert configuration, MQTT connectivity, mesh crypto, demo mode, and TUI development.

  Use when working with: (1) Alert type configuration (12 types), (2) MQTT broker connectivity,
  (3) AES-256-CTR packet decryption, (4) MockMeshtasticAPI demo mode, (5) Rich TUI screens,
  (6) INI configuration management, (7) Callback/cooldown patterns.

  Triggers: meshing_around, mesh_client, alert, mqtt_client, mesh_crypto, demo, MockAPI, cooldown
---

# Meshing Around Development Assistant

## Project Context

meshing_around_meshforge is a companion toolkit for the meshing-around Meshtastic bot.
Provides TUI monitoring, MQTT client, 12-type alert engine, and AES-256-CTR decryption.
Part of the MeshForge ecosystem (Bot/Alerting layer).

**Version:** 0.5.0-beta
**Owner:** WH6GXZ (Nursedude)

## Security Rules (MUST FOLLOW)

### MF001-MF004
Same as MeshForge NOC. See `.claude/rules/security.md`.

### Rich Fallback
All TUI must check `HAS_RICH` before Rich features. Plain-text fallback required.

### Zero-Dep Bootstrap
`mesh_client.py` starts with stdlib only. Dependencies installed after user consent.

## Architecture

```
mesh_client.py              Zero-dep launcher
meshing_around_clients/
├── core/
│   ├── config.py           INI config management
│   ├── models.py           Node, Message, Alert, AlertType, MeshNetwork
│   ├── meshtastic_api.py   Device API + MockMeshtasticAPI
│   ├── mqtt_client.py      MQTT broker connection
│   ├── mesh_crypto.py      AES-256-CTR decryption
│   └── callbacks.py        CallbackMixin + cooldown logic
├── setup/                  Setup wizards (whiptail, Pi detect)
└── tui/                    Rich-based terminal UI (7 screens)
```

## 12 Alert Types

| Type | Trigger | Severity |
|------|---------|----------|
| EMERGENCY | Keywords (911, SOS, HELP) | Critical |
| PROXIMITY | Geofence radius | Medium |
| ALTITUDE | Altitude threshold | Medium |
| WEATHER | NOAA severe weather | High |
| IPAWS | FEMA emergency alerts | High |
| VOLCANO | USGS volcanic activity | High |
| BATTERY | Battery below threshold | Medium |
| NOISY_NODE | Excessive message rate | Low |
| NEW_NODE | First-seen node | Low |
| SNR | Signal quality drop | Low |
| DISCONNECT | Node goes offline | Medium |
| CUSTOM | User-defined keywords | Configurable |

## Key Commands

```bash
python3 mesh_client.py              # Interactive launcher
python3 mesh_client.py --demo       # Demo mode (no hardware)
python3 mesh_client.py --setup      # Configuration wizard
python3 -m pytest tests/ -v         # Run tests
```

## Integration with MeshForge NOC

NOC imports via `safe_import` from `/opt/meshing_around_meshforge`:
- `models.AlertType, Alert` — alert type definitions
- `meshtastic_api.MockMeshtasticAPI` — demo traffic generation
- `mesh_crypto.MeshPacketProcessor` — packet decryption
- `callbacks.CallbackMixin` — cooldown logic

This repo runs independently. It does NOT depend on the NOC.

## Cross-Repo Reference

See `.claude/foundations/cross_repo_topology.md` for ecosystem task delegation.

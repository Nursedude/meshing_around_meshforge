# MeshForge Global Config — Shared Identity Layer

**Path:** `~/.config/meshforge/global.ini`
**Status:** Proposed cross-repo standard. First implemented in `meshing_around_meshforge` v0.6.x.
**Owners:** all MeshForge ecosystem apps that read it (NOC, maps, meshing_around, MeshAnchor).

## Purpose

A single canonical source for values that span multiple MeshForge apps. When you change your callsign, MQTT broker, or region, you change it once — in `global.ini` — and every app picks it up.

Each app reads `global.ini` as a **fallback**, not an override. Per-app config files still take precedence, so anyone with custom per-app values is never surprised.

## Layering rule

Every MeshForge app applies config in this order, lowest to highest priority:

1. **Dataclass defaults** — what the app would do with no config files at all.
2. **`~/.config/meshforge/global.ini`** — ecosystem-wide shared values.
3. **Per-app config** — `mesh_client.ini`, NOC `settings.json`, maps `settings.json`, etc.
4. **Runtime args** — CLI flags, env vars, in-app overrides.

Higher steps win. `global.ini` is purely additive — missing file or missing section = no behavior change.

## What goes in global.ini

Only values that are genuinely the same across multiple apps in a typical deployment.

### `[node]` — operator identity

```ini
[node]
short_name = SHWN
long_name = Shawn (WH6GXZ)
node_id = !a3b2c1d4
```

### `[mqtt]` — broker connection

Most deployments connect every app to the same broker.

```ini
[mqtt]
broker = mqtt.meshtastic.org
port = 1883
use_tls = false
username = meshdev
password = large4cats
topic_root = msh/US
```

### `[region]` — region preset + operator coordinates

```ini
[region]
preset = hawaii
home_lat = 21.30
home_lon = -157.85
```

`preset` matches the regional profile names used by `meshing_around_meshforge --profile <name>` and the maps `region_preset` setting.

### `[paths]` — shared filesystem locations

```ini
[paths]
data_dir = /var/lib/meshforge
```

## What does NOT go in global.ini

These are explicitly per-app and stay in their own configs:

- Feature toggles (`alerts.enabled`, `maps.enable_meshcore`, etc.).
- TUI/UI preferences (refresh rates, color schemes, keybinds).
- Per-app schemas, data models, or workflow state.
- Plugin manifest values.
- Anything that's a per-instance preference rather than a shared identity.

When in doubt: if changing a value in one app shouldn't quietly affect another, it doesn't belong in global.

## File location

`~/.config/meshforge/global.ini`, with `~` resolved to the **invoking user's** home — not `/root` when running under sudo. Apps must use the SUDO_USER-aware pattern (MF001):

```python
import os, pathlib
def get_real_user_home():
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return pathlib.Path(f"/home/{sudo_user}")
    return pathlib.Path.home()
```

## Format

INI — chosen because every MeshForge app already has `configparser` available (stdlib) without adding dependencies. Boolean values use `true`/`false`/`yes`/`no`/`1`/`0`. Numeric values are coerced through each app's local `_coerce_int` / `_coerce_float` helper to survive hand-edited garbage (MF005).

## Reference implementation

`meshing_around_clients/core/global_config.py` in `Nursedude/meshing_around_meshforge` is the canonical reader. Other apps should mirror its shape:

- `load_global_config(path: Optional[Path]) -> GlobalConfig` — never raises, returns all-defaults instance on missing/malformed file.
- `GlobalConfig` dataclass with one nested dataclass per section.
- `loaded: bool` field so callers can tell "global said nothing" from "global doesn't exist."
- Per-app `Config.__init__` calls `_apply_global_defaults()` BEFORE its own `load()` so per-app fallbacks (`fallback=self.field`) preserve global-seeded values when the per-app INI omits a key.

## Adding a new field

1. Decide it actually belongs (re-read "What does NOT go in" above).
2. Add it to the relevant dataclass in `global_config.py` and the parser block in `load_global_config`.
3. Update this doc's schema section.
4. Open mirror PRs in any app that should consume it. Apps that don't care can ignore it forever — it's purely additive.

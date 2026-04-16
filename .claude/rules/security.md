# Security Rules — meshing_around_meshforge

Shared with the MeshForge ecosystem. See `meshforge/.claude/rules/security.md` for canonical versions.

## MF001: Path.home() — NEVER use directly

```python
# WRONG — returns /root when running with sudo
config = Path.home() / ".config"

# CORRECT — this repo's pattern
import os, pathlib
sudo_user = os.environ.get("SUDO_USER")
home = pathlib.Path(f"/home/{sudo_user}") if sudo_user else pathlib.Path.home()
```

## MF002: shell=True — NEVER use in subprocess

```python
# WRONG
subprocess.run(f"meshtastic --info {user_input}", shell=True)

# CORRECT
subprocess.run(["meshtastic", "--info", user_input], timeout=30)
```

## MF003: Bare except — Always specify exception type

```python
# WRONG
except:
    pass

# CORRECT
except (ValueError, ConnectionError) as e:
    logger.error("Operation failed: %s", e)
```

## MF004: subprocess timeout — ALWAYS include

```python
subprocess.run(["long", "command"], timeout=30)
```

## MF005: INI int/float coercion — NEVER call int()/float() raw

User-edited INI values arrive as strings; a hand-typed `port=abc` or
`baudrate=fast` crashes config load with an uncaught `ValueError` before
the UI or logger is up.  Use the local `_coerce_int` / `_coerce_float`
helpers.

```python
# WRONG — crashes on malformed INI
port = int(data.get("port", 1883))

# CORRECT — falls back to default on TypeError/ValueError
port = _coerce_int(data.get("port", 1883), 1883)
```

Helpers live in:
- `meshing_around_clients/core/config.py` (`_coerce_int`)
- `meshing_around_clients/setup/config_schema.py` (`_coerce_int`, `_coerce_float`)

## MF006: subprocess + glob — use glob.glob() NOT subprocess ls

`subprocess.run(["ls", "/dev/ttyUSB*"])` does NOT shell-expand the glob.
`ls` receives the literal `*` and exits "No such file or directory" every
time.  Use Python's glob module directly.

```python
# WRONG — USB port detection silently returns zero
subprocess.run(["ls", "/dev/ttyUSB*"], capture_output=True)

# CORRECT
import glob
for port in glob.glob("/dev/ttyUSB*"):
    ...
```

## Repo-Specific Rules

### No hardcoded MQTT credentials in code
MQTT credentials come from `mesh_client.ini` only. The public broker defaults
(`meshdev`/`large4cats`) are acceptable as INI template defaults but must never
appear in Python source as string literals.

### Rich library fallback
All TUI rendering must check `HAS_RICH` before using Rich features. Provide
plain-text fallback for all UI elements.

### Zero-dependency bootstrap
`mesh_client.py` must start with stdlib only. Auto-install after user consent.

### INI configuration
All user-facing settings in `mesh_client.ini`. No hardcoded values.

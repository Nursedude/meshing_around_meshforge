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

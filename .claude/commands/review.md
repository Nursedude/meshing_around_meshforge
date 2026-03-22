# Code Review

Review recent changes for security, quality, and MeshForge ecosystem compliance.

## Instructions

1. Check for security rule violations:
```bash
cd /opt/meshing_around_meshforge
# MF001: Path.home()
grep -rn "Path\.home()" meshing_around_clients/ mesh_client.py --include="*.py" | grep -v test | grep -v "def get_real"

# MF002: shell=True
grep -rn "shell=True" meshing_around_clients/ mesh_client.py --include="*.py"

# MF003: bare except
grep -rn "except:" meshing_around_clients/ mesh_client.py --include="*.py" | grep -v "except "

# MF004: missing timeout
grep -rn "subprocess\.\(run\|call\|check_output\)" meshing_around_clients/ mesh_client.py --include="*.py" | grep -v timeout
```

2. Run tests to verify no regressions
3. Check for Rich fallback compliance (`HAS_RICH` guards)
4. Report findings with severity and fix suggestions

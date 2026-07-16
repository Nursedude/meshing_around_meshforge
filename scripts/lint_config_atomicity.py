#!/usr/bin/env python3
"""Lint rule: ConfigParser persistence must be ATOMIC.

Born from the 2026-07-16 adversarial pass (MED3): every ``save()`` in this repo
opened the FINAL config path with ``O_TRUNC`` (or ``open(path, "w")``) and wrote
the parser directly. A crash / power-loss mid-write — a real event on the
fleet's SD-card Pis — leaves a truncated or empty config and strands the
operator's ONLY config. The reviewed instances were fixed, but the class was
spread across 8 sites; this rule keeps it closed and blocks reintroduction.

BANS, anywhere in first-party source except a line marked ``# atomic-write-ok``:
  - ``os.O_TRUNC``                        (truncating open of a real file)
  - ``<parser>.write(f)`` / ``.write(fp)``  (serialize a parser to a hand-opened
                                            file handle)

FIX: route the save through the single sanctioned writer
``meshing_around_clients.core.config._atomic_write_parser`` (temp-in-same-dir +
fsync + ``os.replace``). Keep any ``.ini.bak`` backup; just replace the
open+write+chmod.

Exit 0 = clean, 1 = violation(s). Run: ``python3 scripts/lint_config_atomicity.py``
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["meshing_around_clients"]
SCAN_FILES = ["mesh_client.py", "configure_bot.py"]
ALLOW_MARKER = "# atomic-write-ok"

# `<x>.write(f)` where the arg is a bare file handle — the ConfigParser.write
# idiom. Restricted to common handle names so ``f.write("text")`` never matches.
_WRITE_IDIOM = re.compile(r"\.write\(\s*(?:f|fp|fh|fd|fileobj|tf|outf)\s*\)")
_OTRUNC = re.compile(r"\bos\.O_TRUNC\b")


def _iter_py():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            s = str(p)
            if f"{'/'}tests{'/'}" in s or "/.venv/" in s or "/__pycache__/" in s:
                continue
            yield p
    for f in SCAN_FILES:
        p = ROOT / f
        if p.exists():
            yield p


def find_violations():
    """Return a list of (relpath, lineno, reason, code) for each violation."""
    violations = []
    for p in _iter_py():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            if ALLOW_MARKER in line:
                continue
            if _OTRUNC.search(line):
                reason = "os.O_TRUNC truncating write"
            elif _WRITE_IDIOM.search(line):
                reason = "non-atomic parser.write(<file handle>)"
            else:
                continue
            violations.append((str(p.relative_to(ROOT)), i, reason, line.strip()))
    return violations


def main():
    violations = find_violations()
    if violations:
        print(
            "config-atomicity: non-atomic config write(s) found — route through\n"
            "meshing_around_clients.core.config._atomic_write_parser "
            "(temp + fsync + os.replace):\n"
        )
        for rel, i, reason, code in violations:
            print(f"  {rel}:{i}: {reason}\n      {code}")
        print(
            f"\n{len(violations)} violation(s). If a line is genuinely atomic "
            f"(writes a temp file it then os.replace()s), mark it '{ALLOW_MARKER}'."
        )
        return 1
    print("config-atomicity: OK — all ConfigParser saves route through the atomic writer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

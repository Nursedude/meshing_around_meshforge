#!/usr/bin/env python3
"""Re-apply MeshForge code patches to the upstream meshing-around checkout.

The bot we deploy is upstream ``SpudGunMan/meshing-around``; this repo only
configures it. Two source-level fixes are NOT expressible as config and would be
lost on ``git pull`` of the upstream checkout (see ``update_meshing_around`` in
``configure_bot.py``). This script re-applies them idempotently.

Patches (verified live on the fleet 2026-05-24, base upstream commit ``3819791``):

  1. mesh_bot.py — strip leading bridge routing tags (``[RNS:xxxx]``, ``[Mesh:xxxx]``,
     ``[ch0:?]`` ...) from the message BEFORE command detection. Without this,
     ``messageTrap`` with ``explicitCmd=True`` only accepts a command word at index 0,
     so RNS/Mesh-bridged commands like ``[RNS:3dfb] wx`` are silently ignored.

  2. modules/system.py — ``send_message`` chunk loop used ``message_list.index(m)``,
     which returns the FIRST index for chunks with identical text (e.g. two
     "inch possible." continuations), mislabeling chunks and mistiming the
     ``% 4`` / ``% 5`` throttle. Replaced with ``enumerate``/``idx``.

Idempotent: each patch checks whether it is already applied and is a no-op if so.

Usage:
    python3 scripts/apply_meshforge_patches.py [/path/to/meshing-around]
If no path is given, common install locations are probed.
"""
from __future__ import annotations

import os
import py_compile
import sys
from pathlib import Path

MARKER = "MeshForge: strip leading bridge routing tags"

# ---- mesh_bot.py: bracket-strip ------------------------------------------------
_ANCHOR_BOT = "message_log_string = message_string.replace('\\r', ' ').replace('\\n', ' ')"
_BLOCK_BOT = (
    "            # MeshForge: strip leading bridge routing tags (e.g. [RNS:xxxx], [Mesh:xxxx], [ch0:?])\n"
    "            # so bridged commands like \"[RNS:3dfb] wx\" parse as commands. Log keeps the original tag.\n"
    "            if isinstance(message_string, str):\n"
    "                _mf_ms = message_string.lstrip()\n"
    "                while _mf_ms.startswith('['):\n"
    "                    _mf_close = _mf_ms.find(']')\n"
    "                    if _mf_close == -1:\n"
    "                        break\n"
    "                    _mf_ms = _mf_ms[_mf_close + 1:].lstrip()\n"
    "                message_string = _mf_ms\n"
)

# ---- modules/system.py: enumerate fix -----------------------------------------
_SYS_REPLACEMENTS = [
    (
        "            for m in message_list:\n"
        "                chunkOf = f\"{message_list.index(m)+1}/{num_chunks}\"\n",
        "            for idx, m in enumerate(message_list):\n"
        "                chunkOf = f\"{idx+1}/{num_chunks}\"\n",
    ),
    (
        "                if (message_list.index(m)+1) % 4 == 0:\n",
        "                if (idx+1) % 4 == 0:\n",
    ),
    (
        "                    if (message_list.index(m)+1) % 5 == 0:\n",
        "                    if (idx+1) % 5 == 0:\n",
    ),
]


def _log(msg: str) -> None:
    print(f"[meshforge-patch] {msg}")


def find_meshing_around() -> Path | None:
    home = Path(os.path.expanduser("~"))
    for p in (home / "meshing-around", Path("/opt/meshing-around"),
              Path.cwd().parent / "meshing-around", Path.cwd() / "meshing-around"):
        if (p / "mesh_bot.py").exists():
            return p
    return None


def patch_mesh_bot(path: Path) -> bool:
    f = path / "mesh_bot.py"
    text = f.read_text()
    if MARKER in text:
        _log(f"{f.name}: bracket-strip already present")
        return False
    if _ANCHOR_BOT not in text:
        _log(f"WARNING {f.name}: anchor not found — skipping (upstream may have changed)")
        return False
    text = text.replace(_ANCHOR_BOT + "\n", _ANCHOR_BOT + "\n" + _BLOCK_BOT, 1)
    f.write_text(text)
    _log(f"{f.name}: bracket-strip applied")
    return True


def patch_system(path: Path) -> bool:
    f = path / "modules" / "system.py"
    text = f.read_text()
    changed = False
    for old, new in _SYS_REPLACEMENTS:
        if new in text:
            continue
        if old not in text:
            _log(f"WARNING {f.name}: a send_message hunk not found — skipping (upstream may have changed)")
            continue
        text = text.replace(old, new, 1)
        changed = True
    if changed:
        f.write_text(text)
        _log(f"{f.name}: enumerate/idx fix applied")
    else:
        _log(f"{f.name}: enumerate/idx fix already present")
    return changed


def apply_all(meshing_path: Path) -> bool:
    meshing_path = Path(meshing_path)
    if not (meshing_path / "mesh_bot.py").exists():
        _log(f"ERROR: {meshing_path} is not a meshing-around checkout")
        return False
    patch_mesh_bot(meshing_path)
    patch_system(meshing_path)
    ok = True
    for rel in ("mesh_bot.py", "modules/system.py"):
        try:
            py_compile.compile(str(meshing_path / rel), doraise=True)
        except py_compile.PyCompileError as e:
            _log(f"ERROR: {rel} failed to compile after patch: {e}")
            ok = False
    if ok:
        _log("all patches present and files compile cleanly")
    return ok


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else find_meshing_around()
    if path is None:
        _log("ERROR: could not locate meshing-around; pass the path explicitly")
        return 1
    return 0 if apply_all(path) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

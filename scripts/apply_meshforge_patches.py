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

  3. modules/system.py — ``messageChunker`` sized chunks in CHARACTERS; emoji
     (3-4 bytes each) overflowed Meshtastic's ~237-byte payload cap, raising
     "Data payload too big" and aborting ``send_message``'s loop (dropping the
     rest of a reply). Route both return paths through a byte-safe re-splitter.

  4. mesh_bot.py — bot-side reply-dedup for DUAL-BRIDGED commands. A MeshCore
     command from one sender reaches the bot via two bridge paths ([MC:..] and
     [ch0:..]) seconds apart, so the bot answers twice. Coverage analysis
     2026-05-26 showed the two paths are NOT redundant — each delivers ~33% on
     the lossy segment, together ~55% — so they MUST both stay (dropping one at
     the bridge would halve command delivery). Instead, suppress the duplicate
     REPLY only: a guard after the ReceivedChannel log keys on
     (origin, command, channel) within ``MESHFORGE_REPLY_DEDUP_S`` seconds
     (default 30; <=0 disables). Receipt stays logged so the dual-inject watch
     still measures true ingress rate; only the second reply is dropped.

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
    '            # so bridged commands like "[RNS:3dfb] wx" parse as commands. Log keeps the original tag.\n'
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
        "            for m in message_list:\n" '                chunkOf = f"{message_list.index(m)+1}/{num_chunks}"\n',
        "            for idx, m in enumerate(message_list):\n" '                chunkOf = f"{idx+1}/{num_chunks}"\n',
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

# ---- modules/system.py: byte-aware chunking (patch 3) -------------------------
# messageChunker sized chunks in CHARACTERS (MESSAGE_CHUNK_SIZE). Meshtastic's
# on-air text payload is capped (~237 bytes) and the python lib raises
# "Data payload too big" above it; that exception aborts send_message's send
# loop and DROPS every remaining chunk. Emoji are 3-4 UTF-8 bytes each, so an
# emoji-dense reply (e.g. the `leaderboard` command) could produce a chunk that
# fit the char budget but blew the byte budget. We route both messageChunker
# return paths through a byte-safety post-pass that re-splits any over-budget
# chunk on word then codepoint boundaries (never mid-emoji). ASCII output is
# unaffected (1 char == 1 byte). Idempotent and additive — the internal
# char-based pre-splitting is left untouched; the post-pass only enforces the
# byte bound on whatever it produced.
_BYTE_SAFE_MARKER = "def _meshforge_byte_safe"

_BYTE_SAFE_ANCHOR = "def messageChunker(message):\n"

_BYTE_SAFE_HELPER = (
    "def _meshforge_byte_safe(chunks, max_bytes=None):\n"
    "    # MeshForge: guarantee no emitted chunk exceeds the Meshtastic byte\n"
    "    # budget. messageChunker sized chunks in characters; emoji (3-4 bytes\n"
    "    # each) overflowed the ~237-byte payload limit, making sendText raise\n"
    '    # "Data payload too big" and abort send_message\'s loop (dropping the\n'
    "    # rest of a multi-part reply). Re-split on UTF-8 byte boundaries:\n"
    "    # newline, then word, then a codepoint-safe hard split. ASCII is\n"
    "    # unaffected. Idempotent: chunks already within budget pass through.\n"
    "    if max_bytes is None:\n"
    "        max_bytes = MESSAGE_CHUNK_SIZE\n"
    "    was_str = isinstance(chunks, str)\n"
    "    items = [chunks] if was_str else list(chunks)\n"
    "\n"
    "    def _blen(s):\n"
    "        return len(s.encode('utf-8'))\n"
    "\n"
    "    def _char_split(token):\n"
    "        out, cur = [], ''\n"
    "        for ch in token:\n"
    "            if cur and _blen(cur) + _blen(ch) > max_bytes:\n"
    "                out.append(cur)\n"
    "                cur = ch\n"
    "            else:\n"
    "                cur += ch\n"
    "        if cur:\n"
    "            out.append(cur)\n"
    "        return out\n"
    "\n"
    "    def _pack(atoms, sep):\n"
    "        out, cur = [], ''\n"
    "        for atom in atoms:\n"
    "            add = _blen(atom) + (_blen(sep) if cur else 0)\n"
    "            if cur and _blen(cur) + add > max_bytes:\n"
    "                out.append(cur)\n"
    "                cur = ''\n"
    "            if not cur:\n"
    "                if _blen(atom) <= max_bytes:\n"
    "                    cur = atom\n"
    "                else:\n"
    "                    finer = _pack(atom.split(' '), ' ') if ' ' in atom else _char_split(atom)\n"
    "                    if finer:\n"
    "                        out.extend(finer[:-1])\n"
    "                        cur = finer[-1]\n"
    "            else:\n"
    "                cur = cur + sep + atom\n"
    "        if cur:\n"
    "            out.append(cur)\n"
    "        return out\n"
    "\n"
    "    result = []\n"
    "    for item in items:\n"
    "        if _blen(item) <= max_bytes:\n"
    "            result.append(item)\n"
    "        else:\n"
    "            result.extend(_pack(item.split('\\n'), '\\n'))\n"
    "    if was_str and len(result) == 1:\n"
    "        return result[0]\n"
    "    return result\n"
    "\n"
    "\n"
)

# Both messageChunker return paths, as one contiguous (and therefore
# unambiguous) anchor — the chunked path and the short-message early return.
_BYTE_SAFE_RETURNS_OLD = "            return final_message_list\n" "\n" "        return message\n"
_BYTE_SAFE_RETURNS_NEW = (
    "            return _meshforge_byte_safe(final_message_list)\n"
    "\n"
    "        return _meshforge_byte_safe(message)\n"
)


# ---- mesh_bot.py: bot-side reply-dedup for dual-bridged commands (patch 4) ----
# NOTE: injected blocks MUST be ASCII-only. write_text() uses the locale
# encoding; the bot's locale is latin-1, so a non-ASCII char (e.g. an em-dash)
# raises UnicodeEncodeError mid-write and TRUNCATES mesh_bot.py to empty.
_REPLY_DEDUP_HELPER_MARKER = "def _meshforge_reply_is_dup"
_REPLY_DEDUP_DEF_ANCHOR = "def onReceive(packet, interface):\n"
_REPLY_DEDUP_HELPER = (
    "def _meshforge_reply_is_dup(original_text, command, channel, from_id):\n"
    "    # MeshForge: dual-bridge reply guard. The same MeshCore command reaches\n"
    "    # the bot via two bridge paths ([MC:..] and [ch0:..]) seconds apart;\n"
    "    # BOTH are kept (each ~33% delivery, together ~55% -- load-bearing\n"
    "    # redundancy on the lossy segment, measured 2026-05-26), but the bot\n"
    "    # must REPLY only once. Returns True if (origin, command, channel) was\n"
    "    # already answered within MESHFORGE_REPLY_DEDUP_S seconds (default 30;\n"
    "    # <=0 disables). origin is parsed from the [MC:who]/[chN:who] tag so two\n"
    "    # senders' identical commands are never collapsed.\n"
    "    import os as _os, re as _re, time as _time\n"
    "    try:\n"
    "        window = int(_os.environ.get('MESHFORGE_REPLY_DEDUP_S', '30'))\n"
    "    except (TypeError, ValueError):\n"
    "        window = 30\n"
    "    if window <= 0 or not command:\n"
    "        return False\n"
    "    m = _re.search(r'\\[(?:MC|ch\\d+):([^\\]]+)\\]', original_text or '')\n"
    "    origin = m.group(1).strip() if m else str(from_id)\n"
    "    key = (origin, ' '.join(str(command).split()).lower(), channel)\n"
    "    now = _time.time()\n"
    "    cache = _meshforge_reply_is_dup.__dict__.setdefault('_seen', {})\n"
    "    for stale in [k for k, t in cache.items() if now - t > window]:\n"
    "        cache.pop(stale, None)\n"
    "    if key in cache and now - cache[key] <= window:\n"
    "        cache[key] = now\n"
    "        return True\n"
    "    cache[key] = now\n"
    "    return False\n"
    "\n"
    "\n"
)

_REPLY_DEDUP_GUARD_MARKER = "MeshForge: reply-dedup for dual-bridged"
# Byte-exact 2-line anchor: the channel-branch ReceivedChannel log statement.
_REPLY_DEDUP_ANCHOR = (
    '                        logger.info(f"Device:{rxNode} Channel:{channel_number} " + CustomFormatter.green + "ReceivedChannel: " + CustomFormatter.white + f"{message_log_string} " + CustomFormatter.purple +\\\n'
    '                                    "From: " + CustomFormatter.white + f"{get_name_from_number(message_from_id, \'long\', rxNode)}")\n'
)
_REPLY_DEDUP_GUARD = (
    "                        # MeshForge: reply-dedup for dual-bridged commands.\n"
    "                        # receipt is logged above (so the dual-inject watch\n"
    "                        # still sees both copies); suppress only the second\n"
    "                        # REPLY. See _meshforge_reply_is_dup.\n"
    "                        if _meshforge_reply_is_dup(message_log_string, message_string, channel_number, message_from_id):\n"
    '                            logger.info(f"Device:{rxNode} Channel:{channel_number} MeshForge: dropped duplicate reply (dual-bridged), kept receipt above")\n'
    "                            return\n"
)


def _atomic_write_py(target: Path, text: str) -> None:
    """Write Python source atomically (C1).

    The old ``f.write_text(text)`` truncated the live file first, so a mid-write
    failure (encode error — the module's own history — ENOSPC, power loss on an
    SD-card Pi) left ``mesh_bot.py`` torn or empty, and ``py_compile`` ran only
    AFTER the write, validating already-destroyed content.  Here: back up, write
    a same-dir temp with explicit utf-8, validate the NEW content in memory, then
    ``os.replace`` — a bad write can never replace a good file.
    """
    import shutil
    import tempfile

    target = Path(target)
    # Capture the target's mode/owner BEFORE the swap: mkstemp creates the temp
    # 0600 owned by the writer (root under the installer), and os.replace keeps
    # the temp's metadata — without restoring it, a world-readable bot source
    # became root:root 0600 and the User=<pi> service could no longer read it
    # (PermissionError at next restart, fleet-wide — 3rd-pass CRITICAL).
    target_stat = None
    if target.exists():
        try:
            target_stat = os.stat(str(target))
        except OSError:
            target_stat = None
        try:
            shutil.copy2(str(target), str(target) + ".bak")
        except OSError:
            pass
    # Validate before touching the target at all.
    compile(text, str(target), "exec")
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if target_stat is not None:
            # Restore the original mode; restore owner too when we're root and
            # able (best-effort — a non-root writer can't chown and shouldn't).
            try:
                os.chmod(tmp, target_stat.st_mode & 0o777)
            except OSError:
                pass
            if os.geteuid() == 0:
                try:
                    os.chown(tmp, target_stat.st_uid, target_stat.st_gid)
                except OSError:
                    pass
        os.replace(tmp, str(target))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _log(msg: str) -> None:
    print(f"[meshforge-patch] {msg}")


def find_meshing_around() -> Path | None:
    home = Path(os.path.expanduser("~"))
    for p in (
        home / "meshing-around",
        Path("/opt/meshing-around"),
        Path.cwd().parent / "meshing-around",
        Path.cwd() / "meshing-around",
    ):
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
    _atomic_write_py(f, text)
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
        _atomic_write_py(f, text)
        _log(f"{f.name}: enumerate/idx fix applied")
    else:
        _log(f"{f.name}: enumerate/idx fix already present")
    return changed


def patch_system_byte_safe(path: Path) -> bool:
    """Make messageChunker byte-aware (patch 3): inject the byte-safety
    helper and route both return paths through it."""
    f = path / "modules" / "system.py"
    text = f.read_text()
    if _BYTE_SAFE_MARKER in text:
        _log(f"{f.name}: byte-safe chunking already present")
        return False
    if _BYTE_SAFE_ANCHOR not in text or _BYTE_SAFE_RETURNS_OLD not in text:
        _log(f"WARNING {f.name}: byte-safe anchor not found — skipping " f"(upstream may have changed messageChunker)")
        return False
    # Insert the helper just above messageChunker, then rewire its returns.
    text = text.replace(_BYTE_SAFE_ANCHOR, _BYTE_SAFE_HELPER + _BYTE_SAFE_ANCHOR, 1)
    text = text.replace(_BYTE_SAFE_RETURNS_OLD, _BYTE_SAFE_RETURNS_NEW, 1)
    _atomic_write_py(f, text)
    _log(f"{f.name}: byte-safe chunking applied")
    return True


def patch_reply_dedup(path: Path) -> bool:
    """Patch 4: bot-side reply-dedup for dual-bridged commands. Inject the
    ``_meshforge_reply_is_dup`` helper (above onReceive) and a guard right
    after the channel ReceivedChannel log (receipt stays logged; only the
    duplicate reply is suppressed)."""
    f = path / "mesh_bot.py"
    text = f.read_text()
    changed = False
    if _REPLY_DEDUP_HELPER_MARKER in text:
        _log(f"{f.name}: reply-dedup helper already present")
    elif _REPLY_DEDUP_DEF_ANCHOR not in text:
        _log(f"WARNING {f.name}: onReceive anchor not found — skipping reply-dedup helper")
    else:
        text = text.replace(_REPLY_DEDUP_DEF_ANCHOR, _REPLY_DEDUP_HELPER + _REPLY_DEDUP_DEF_ANCHOR, 1)
        changed = True
    if _REPLY_DEDUP_GUARD_MARKER in text:
        _log(f"{f.name}: reply-dedup guard already present")
    elif _REPLY_DEDUP_ANCHOR not in text:
        _log(f"WARNING {f.name}: ReceivedChannel anchor not found — skipping reply-dedup guard")
    else:
        text = text.replace(_REPLY_DEDUP_ANCHOR, _REPLY_DEDUP_ANCHOR + _REPLY_DEDUP_GUARD, 1)
        changed = True
    if changed:
        _atomic_write_py(f, text)
        _log(f"{f.name}: reply-dedup applied")
    return changed


def apply_all(meshing_path: Path) -> bool:
    meshing_path = Path(meshing_path)
    if not (meshing_path / "mesh_bot.py").exists():
        _log(f"ERROR: {meshing_path} is not a meshing-around checkout")
        return False
    patch_mesh_bot(meshing_path)
    patch_system(meshing_path)
    patch_system_byte_safe(meshing_path)
    patch_reply_dedup(meshing_path)
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

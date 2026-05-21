"""Regression test: whiptail dialog text must be pure ASCII.

The Pi's default stdout locale is latin-1.  When `subprocess.run(["whiptail",
..., prompt])` is invoked with a prompt containing characters outside
latin-1 (em-dash U+2014, en-dash U+2013, curly quotes, etc.), the spawn
itself crashes with a UnicodeEncodeError before whiptail ever runs.

This bit the BA5E operator picking "Rename Radio" in the launcher menu
on 2026-05-21 — the inputbox prompt contained an em-dash.  See
feedback_whiptail_ascii_only.md and CLAUDE.md latent-bug pattern.

The check is AST-based so it's robust to indentation, line wrapping,
and f-string interpolation: we walk the AST looking for calls to the
whiptail dialog functions and scan every string literal in their args
for non-ASCII characters.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

import mesh_client  # noqa: E402

REPO_ROOT = Path(mesh_client.SCRIPT_DIR)

# Whiptail wrapper function names (from meshing_around_clients/setup/whiptail.py)
_WHIPTAIL_DIALOGS = {"menu", "yesno", "msgbox", "infobox", "inputbox", "radiolist"}

# Files that call into whiptail dialogs.  Extend if a new file starts using them.
_SOURCES = [
    REPO_ROOT / "mesh_client.py",
    REPO_ROOT / "meshing_around_clients" / "tui" / "whiptail_tui.py",
]


def _collect_string_pieces(node: ast.AST) -> list[tuple[str, int]]:
    """Return all string literal pieces (and their lineno) inside `node`.

    Handles plain Constant strings, JoinedStr (f-strings), and recursively
    walks BinOp/Call children so concatenations and method chains are
    covered.  Skips FormattedValue interpolation segments (those are
    runtime values, not literals — they can't be statically ASCII-checked).
    """
    pieces: list[tuple[str, int]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            pieces.append((child.value, child.lineno))
    return pieces


class TestWhiptailAsciiOnly(unittest.TestCase):
    """Every string literal passed to a whiptail dialog must be ASCII."""

    def test_no_non_ascii_in_whiptail_dialog_calls(self):
        offenders: list[str] = []

        for path in _SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                # Resolve the called name (handles bare "menu" and "wt_menu")
                callee = node.func
                if isinstance(callee, ast.Name):
                    name = callee.id
                elif isinstance(callee, ast.Attribute):
                    name = callee.attr
                else:
                    continue
                # Some local imports rename `menu` to `wt_menu`/`profile_menu` etc.
                # We catch those too — any callable whose name ends in our set.
                base_name = name.lstrip("_").rsplit("_", 1)[-1]
                if name not in _WHIPTAIL_DIALOGS and base_name not in _WHIPTAIL_DIALOGS:
                    continue

                # Walk every arg + keyword for string literals
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    for text, lineno in _collect_string_pieces(arg):
                        for ch in text:
                            if ord(ch) > 127:
                                offenders.append(
                                    f"{path.relative_to(REPO_ROOT)}:{lineno} {name}() "
                                    f"contains U+{ord(ch):04X} {ch!r}: {text[:60]!r}"
                                )
                                break  # one report per literal is enough

        if offenders:
            self.fail(
                "Non-ASCII characters in whiptail dialog text will crash under\n"
                "the Pi's latin-1 locale (subprocess argv encode).  See\n"
                "feedback_whiptail_ascii_only.md.  Offenders:\n  " + "\n  ".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()

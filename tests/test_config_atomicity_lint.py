"""Regression guard: config saves must stay atomic (MED3, 2026-07-16).

Runs the config-atomicity lint scanner as part of the test suite so CI blocks a
reintroduced torn-write `save()` even if healthcheck.sh isn't run. Also unit-
tests the detector itself so a passing repo scan is never vacuous.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load the standalone lint script as a module.
_spec = importlib.util.spec_from_file_location("lint_config_atomicity", ROOT / "scripts" / "lint_config_atomicity.py")
_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lint)


class TestConfigAtomicityLint(unittest.TestCase):
    def test_repo_has_no_non_atomic_config_writes(self):
        violations = _lint.find_violations()
        msg = "\n".join(f"  {rel}:{i}: {reason}\n      {code}" for rel, i, reason, code in violations)
        self.assertEqual(
            violations,
            [],
            f"\nNon-atomic config write(s) — route through _atomic_write_parser:\n{msg}",
        )

    def test_detector_flags_o_trunc(self):
        self.assertTrue(_lint._OTRUNC.search("fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)"))

    def test_detector_flags_parser_write_idiom(self):
        for bad in ("parser.write(f)", "self._parser.write(f)", "config.write(fp)"):
            self.assertIsNotNone(_lint._WRITE_IDIOM.search(bad), bad)

    def test_detector_ignores_text_write(self):
        # f.write("text") is not the parser-to-filehandle idiom.
        self.assertIsNone(_lint._WRITE_IDIOM.search('f.write("some text")'))
        self.assertIsNone(_lint._WRITE_IDIOM.search("f.write(data)"))

    def test_allow_marker_exempts_a_line(self):
        # The sanctioned atomic writer marks its temp-file write; confirm the
        # marker string is what the scanner honours.
        self.assertEqual(_lint.ALLOW_MARKER, "# atomic-write-ok")


if __name__ == "__main__":
    unittest.main()

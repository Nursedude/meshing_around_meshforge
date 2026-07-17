"""C1: apply_meshforge_patches writes live source atomically.

A mid-write failure must not truncate the target, and invalid content must be
rejected BEFORE it replaces a good file. Tests patch the SOURCE seam (the temp
write) rather than the caller.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import apply_meshforge_patches as amp  # noqa: E402


class TestAtomicWritePy(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "mesh_bot.py"
        self.target.write_text("original = True\n")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_successful_write_replaces_and_backs_up(self):
        amp._atomic_write_py(self.target, "patched = True\n")
        self.assertEqual(self.target.read_text(), "patched = True\n")
        self.assertTrue((self.tmp / "mesh_bot.py.bak").exists())

    def test_invalid_python_rejected_target_preserved(self):
        # Syntactically invalid content must not replace the good file.
        with self.assertRaises(SyntaxError):
            amp._atomic_write_py(self.target, "def broken(:\n")
        self.assertEqual(self.target.read_text(), "original = True\n")

    def test_mid_write_failure_preserves_target(self):
        # Simulate a failure during the temp write (e.g. ENOSPC): the original
        # must survive intact and no temp file is left behind.
        real_fdopen = amp.os.fdopen

        def boom(fd, *a, **k):
            # Close the fd so we don't leak it, then fail like a write error.
            import os as _os

            _os.close(fd)
            raise OSError("simulated disk full")

        with patch.object(amp.os, "fdopen", side_effect=boom):
            with self.assertRaises(OSError):
                amp._atomic_write_py(self.target, "patched = True\n")
        self.assertEqual(self.target.read_text(), "original = True\n")
        leftovers = [p for p in self.tmp.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()

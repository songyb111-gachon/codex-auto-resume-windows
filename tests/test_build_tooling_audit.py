"""The build, release and workflow findings of the v0.6.23 tooling audit (Area C), one class each.

* SidecarLineEndingTests (T1) - a .sha256 sidecar and release-notes.md are written with LF, so
  `sha256sum -c` finds the file it names; the digest is the file's, as before.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str, path: Path):
    here = str(path.parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SidecarLineEndingTests(unittest.TestCase):
    def test_a_sidecar_ends_in_lf_and_holds_the_files_digest(self):
        make_release = _load("make_release", ROOT / "build" / "make_release.py")
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "sample.bin"
            target.write_bytes(b"sample bytes")
            digest = make_release.write_sidecar(target)
            written = (Path(scratch) / "sample.bin.sha256").read_bytes()
        self.assertEqual(digest, hashlib.sha256(b"sample bytes").hexdigest())
        self.assertEqual(written, ("%s  sample.bin\n" % digest).encode("ascii"))

    def test_release_notes_are_written_with_lf(self):
        notes = _load("release_notes", ROOT / "build" / "release_notes.py")
        with tempfile.TemporaryDirectory() as scratch:
            changelog = Path(scratch) / "CHANGELOG.md"
            changelog.write_text("# Changelog\n\n## v9.9.9\n\nOne line.\nTwo lines.\n\n## v9.9.8\n\nOld.\n",
                                 encoding="utf-8")
            output = Path(scratch) / "release-notes.md"
            notes.main(["9.9.9", "--changelog", str(changelog), "--output", str(output)])
            written = output.read_bytes()
        self.assertIn(b"One line.", written)
        self.assertNotIn(b"\r", written)


if __name__ == "__main__":
    unittest.main()

"""The official folder is the same folder however the profile is reached.

config.candidate_codex_exes hands out resolved paths and pairing.at_official_location compared them with LOCALAPPDATA's
unresolved text. On a profile reached through a junction or a short 8.3 name the engine discovery had just found was not
"at the official location", and rested on its signature alone; where that could not be read, it was refused.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import config
from codex_auto_resume.codex import pairing


def junction(link: Path, target: Path) -> None:
    subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


class ThroughAJunction(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="official-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.real = self.root / "real"
        self.engine = self.real / "OpenAI" / "Codex" / "bin" / "abc123" / "codex.exe"
        self.engine.parent.mkdir(parents=True)
        self.engine.write_bytes(b"")
        self.link = self.root / "link"
        junction(self.link, self.real)

    def at(self, profile, path):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(profile)}):
            return pairing.at_official_location(path)

    def test_what_discovery_finds_through_a_linked_profile_is_at_the_official_location(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.link)}):
            found = config.candidate_codex_exes()
            self.assertEqual(len(found), 1)
            self.assertTrue(pairing.at_official_location(found[0]))

    def test_the_folder_written_through_the_link_is_the_folder(self):
        self.assertTrue(self.at(self.real, self.link / self.engine.relative_to(self.real)))

    def test_one_case_or_another(self):
        self.assertTrue(self.at(self.real, str(self.engine).upper()))

    def test_a_hex_folder_that_leads_elsewhere_is_not_the_folder(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "codex.exe").write_bytes(b"")
        junction(self.engine.parent.parent / "def456", outside)
        self.assertFalse(self.at(self.real, self.engine.parent.parent / "def456" / "codex.exe"))

    def test_no_profile_is_no_official_folder(self):
        with patch.dict(os.environ):
            os.environ.pop("LOCALAPPDATA", None)
            self.assertFalse(pairing.at_official_location(self.engine))


if __name__ == "__main__":
    unittest.main()

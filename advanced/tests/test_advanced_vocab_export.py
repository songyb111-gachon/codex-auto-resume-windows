"""build/vocab_export.py --advanced: the advanced edition's vocabularies, in a file of their own.

The standard `vocab.json` carries no name of the advanced edition (tests/test_vocab_export.py holds that on a small
repository and on this one); the advanced file carries its own vocabularies, and the few core constants that spell
the edition's package, which the standard file was relieved of. Run here on this repository's HEAD twice, because
the advanced tree has far more dicts and sets than core and one of them built from a set is a file that differs
from one run to the next.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "build" / "vocab_export.py"
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import edition_audit  # noqa: E402
import vocab_export  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _export(out: Path) -> None:
    done = subprocess.run([sys.executable, str(TOOL), "--ref", "HEAD", "--advanced", "--out", str(out)],
                          capture_output=True, timeout=900, creationflags=NO_WINDOW)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


class AdvancedExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls.first = Path(cls._temp.name) / "one" / "vocab.json"
        cls.second = Path(cls._temp.name) / "two" / "vocab.json"
        for target in (cls.first, cls.second):
            target.parent.mkdir()
            _export(target)
        cls.advanced = json.loads(cls.first.with_name("vocab-advanced.json").read_text(encoding="utf-8"))
        cls.standard = json.loads(cls.first.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def test_both_files_are_the_same_bytes_twice(self):
        for name in ("vocab.json", "vocab-advanced.json"):
            self.assertEqual((self.first.parent / name).read_bytes(), (self.second.parent / name).read_bytes(), name)

    def test_the_advanced_file_holds_the_edition_vocabularies(self):
        self.assertEqual(self.advanced["edition"], "advanced")
        self.assertEqual(self.advanced["unimportable"], [])
        enums = self.advanced["modules"]["vocabulary"]["enums"]
        self.assertGreater(len(enums), 20)
        for module in ("registry", "plug", "policy", "state.schema", "engine.anchor"):
            self.assertIn(module, self.advanced["modules"])

    def test_the_hand_run_tools_and_the_catalog_keys_are_left_out(self):
        for module in vocab_export.ADVANCED_EXCLUDED_MODULES:
            self.assertNotIn(module, self.advanced["modules"])
        self.assertFalse([name for name in self.advanced["modules"] if name.startswith("win")])

    def test_the_core_names_of_the_edition_are_here_and_not_in_the_standard_file(self):
        self.assertEqual(self.advanced["core_edition"], {"edition.ADVANCED_PACKAGE": vocab_export.ADVANCED})
        self.assertEqual(self.standard["withheld"], 1)
        text = self.first.read_text(encoding="utf-8")
        for name in vocab_export.SECRET_NAMES:
            self.assertNotIn(name, text)

    def test_the_standard_file_passes_the_edition_audits_name_check_and_this_one_does_not_need_to(self):
        found, _used = edition_audit.check_names({"vocab.json": self.first.read_bytes()}, edition_audit.inventory(ROOT))
        self.assertEqual(found, [])

    def test_the_name_check_finds_the_advanced_names_in_the_advanced_file(self):
        """So that the standard file passing it is not a check that finds nothing anywhere."""
        data = self.first.with_name("vocab-advanced.json").read_bytes()
        found, _used = edition_audit.check_names({"vocab.json": data}, edition_audit.inventory(ROOT))
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()

"""The settings panel's stylesheet and script, now that they are files.

Until v0.6.10-alpha they were two raw strings inside `mcpui.py` - 2,174 of its 2,332 lines -
and being Python they were shipped, scanned and read like the code around them for free. As
files they are none of those things by default, and each has to be said:

* the release has to pack them, or the panel in Codex is an empty white rectangle on a
  machine nobody here can see;
* the scans have to read them, or 2,172 lines of shipped code stop being checked - which is
  not hypothetical: `tests/test_compat_surfaces.py` asks where the word `compat-refresh`
  lives, and the answer moved out of Python the moment these did;
* they have to be read with universal newlines, because `.gitattributes` gives every text
  file CRLF in the working tree and in the release archive, while the page Codex receives
  has always carried LF and the golden replies are held to the byte.

The last of those is the one that would go wrong quietly: it is right on every machine that
builds the product and wrong on every machine that installs it.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import srcscan  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui  # noqa: E402

ROOT = Path(_HERE).parent
ASSETS = ROOT / "src" / "codex_auto_resume" / "mcp" / "assets"
FILES = {"panel.css": "_STYLE", "panel.js": "_SCRIPT"}


class AssetTests(unittest.TestCase):
    def test_both_files_are_there_and_tracked(self):
        listing = set(srcscan.tracked())
        for name in FILES:
            with self.subTest(name):
                path = ASSETS / name
                self.assertTrue(path.is_file())
                self.assertIn(("src/codex_auto_resume/mcp/assets/" + name), listing)

    def test_the_page_carries_only_line_feeds_whatever_the_files_carry(self):
        """The property that is right where it is built and wrong where it is installed.

        `.gitattributes` says `* text=auto eol=crlf`, so on a developer's machine and inside
        the release archive these files have CRLF on disk. Read with universal newlines - the
        default, and what `mcpui._asset` uses - they come back with LF, which is what the page
        has always carried. A `newline=""` here would put a carriage return into every line of
        the panel Codex renders, on installed copies only.
        """
        page = mcpui.settings_page()
        self.assertNotIn("\r", page)
        self.assertNotIn("\r", mcpui._STYLE)
        self.assertNotIn("\r", mcpui._SCRIPT)

    def test_the_constants_are_the_files(self):
        """`_STYLE` has brand's values substituted into it; the text around them is the file."""
        css = (ASSETS / "panel.css").read_text(encoding="utf-8")
        self.assertIn("@LIGHT@", css, "the file keeps the tokens; mcpui fills them in")
        self.assertNotIn("@LIGHT@", mcpui._STYLE)
        self.assertEqual(mcpui._SCRIPT, (ASSETS / "panel.js").read_text(encoding="utf-8"))
        self.assertGreater(len(mcpui._SCRIPT.splitlines()), 1000)

    def test_the_keys_are_read_out_of_the_script_file(self):
        """Step 13's own acceptance: `panel_keys()` works on a file read."""
        names, prefixes = mcpui.panel_keys()
        self.assertIn("panel.due", names)
        self.assertTrue(prefixes)
        self.assertLessEqual({"reason."}, set(prefixes))

    def test_the_release_refuses_to_build_without_them(self):
        """Nothing else would notice: the trees are copied by walking them, so a file that
        stopped being copied would be missing on a user's machine and nowhere else."""
        source = (ROOT / "build" / "make_release.py").read_text(encoding="utf-8")
        required = source.split("REQUIRED_APP_FILES = (", 1)[1].split(")", 1)[0]
        for name in FILES:
            with self.subTest(name):
                self.assertIn("src/codex_auto_resume/mcp/assets/" + name, required)

    def test_the_hygiene_scans_read_them_as_text(self):
        source = (ROOT / "tests" / "test_repo_hygiene.py").read_text(encoding="utf-8")
        suffixes = source.split("TEXT_SUFFIXES = {", 1)[1].split("}", 1)[0]
        self.assertIn('".css"', suffixes)
        self.assertIn('".js"', suffixes)


if __name__ == "__main__":
    unittest.main()

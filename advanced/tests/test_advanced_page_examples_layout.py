# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""See an example's view fits the screen (v0.6.20): every capability's example built and never shown on a working area
the audit stands in - GitHub's runners have a 1024 by 768 screen, and the window opens there at 175 % and 200 % too - and
held to the window's own audit (AdvancedExamplesAudit in advanced/gui/AdvancedExamples.cs): nothing cut off, nothing
scrolling sideways, every control named, each list on History's card with its columns within it, the two panes one above
the other where they have no room beside each other, and the dialog within the working area. In the languages that stretch
it most - German's long words, Japanese and Korean, Arabic written right to left - and in English, with a canary that shows
the audit finds a working area too small for it.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_examples_layout.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, IDS, POWERSHELL, Bridge, compile_window, probe, strings  # noqa: E402
from codex_auto_resume_advanced import registry  # noqa: E402

LOCALES = ("en", "de", "ja", "ko", "ar")
# CI's screen, less a taskbar: (scale, width, height) in physical pixels.
SMALL = 1024, 728
VIEWS = ((1.75,) + SMALL, (2.0,) + SMALL, (1.0, 1920, 1040))
# A working area no dialog of the window's fits at 200 %.
CANARY = (2.0, 400, 300)
# Every capability's example, the waiting ones' among them.
EXAMPLES = len(registry.DEFINITIONS) + len(registry.WAITING)


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        jobs = []
        for locale in LOCALES:
            bridge = Bridge(work / "homes" / locale)
            try:
                words = bridge("advanced-words", {"locale": locale})["result"]["words"]
                statements = {capability: bridge("advanced-statement", {"capability": capability, "locale": locale})["result"]
                              for capability in IDS}
            finally:
                bridge.close()
            for name, data in (("strings", strings(locale)), ("words", words), ("statements", statements)):
                (work / ("%s-%s.json" % (name, locale))).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            views = VIEWS + ((CANARY,) if locale == "en" else ())
            for scale, width, height in views:
                jobs.append({"kind": "examples", "name": "%s %s %dx%d" % (locale, scale, width, height),
                             "strings": "strings-%s.json" % locale, "words": "words-%s.json" % locale,
                             "statements": "statements-%s.json" % locale, "scale": scale, "width": width, "height": height})
        cls.run_, cls.results = probe(work, exe, jobs, timeout=1800)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.results:
            self.fail("the probe did not run: " + (self.run_.stderr or self.run_.stdout)[-3000:])

    def found(self, locale, scale, width, height):
        result = self.results.get("%s %s %dx%d" % (locale, scale, width, height))
        if result is None or "error" in result:
            self.fail("%s at %s did not run: %s" % (locale, scale, (result or {}).get("error")))
        return result

    def test_every_example_fits_ci_s_screen_and_a_large_one_in_every_language(self):
        for locale in LOCALES:
            for scale, width, height in VIEWS:
                with self.subTest(locale=locale, scale=scale, area="%dx%d" % (width, height)):
                    result = self.found(locale, scale, width, height)
                    self.assertEqual(result["audited"], EXAMPLES, "every example was looked at")
                    self.assertEqual(result["report"], "")

    def test_the_audit_finds_a_working_area_too_small(self):
        """The canary: on a working area 400 by 300 at 200 % the dialog cannot fit, and the audit says so - so a quiet
        report above is the audit finding nothing, not the audit not looking."""
        report = self.found("en", *CANARY)["report"]
        self.assertIn("on a working area of 400x300", report)


if __name__ == "__main__":
    unittest.main()

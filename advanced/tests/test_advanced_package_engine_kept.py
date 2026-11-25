"""v0.6.26 final (live acceptance R2b): a capability kept on stays on with the Codex app closed, on the app's own engine.

The watcher drives the engine the app runs from its package (#58) and keeps driving it after the app closes. Its own
arming read goes through the reader every surface uses (arming._view_of, compatio.reader_view), and that reader bound
the watcher's report only to an engine in bin or one the app runs now: with the app closed every capability that stands
on Codex read UNKNOWN, and `standing` held each kept on one off (COMPAT_UNKNOWN) - the meter, the wake timer, the window
anchor, the local API - until the app opened again. The stored rows never changed. Here the arming read is the real
one, over the watcher's real report; the package folder, the process list and the signatures are stand-ins
(tests/test_package_engine_bound.py). `standing`'s rules are unchanged: what cannot be read still holds it back.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.codex import pairing  # noqa: E402
from codex_auto_resume_advanced import arming  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, ArmingWarning, KeepOn  # noqa: E402
from test_package_engine_bound import BIN_VERSION, PACKAGE_VERSION, PackageCase  # noqa: E402

CAPABILITY = "test_wake"


class KeptOnCase(PackageCase, ac.AdvancedCase):
    def setUp(self):
        ac.AdvancedCase.setUp(self)
        PackageCase.setUp(self)
        self.definition = ac.definition(compat="usage_probe")
        self.catalogs = ac.catalogs(self.root / "catalogs", self.definition)

    def runtime(self, *definitions):
        options = dict(self.options(self.definition), view=lambda: arming._view_of(self.paths))
        made = ac.Runtime(self.paths, **options)
        self.addCleanup(made.state.close)
        return made

    def kept_on(self, version):
        """The capability armed for `version` and kept on, as a person does it on the Dashboard."""
        rt = self.runtime()
        self.assertTrue(self.arm(rt, CAPABILITY, acknowledged_version=version)["done"])
        found = rt.arming.set_keep_on(CAPABILITY, True, generation=rt.state.meta()["generation"],
                                      confirmed=[str(KeepOn.KEEP_ON)], actor=Actor.DASHBOARD)
        self.assertTrue(found["done"], found)
        return rt

    def state_now(self, rt):
        return rt.arming.current()[CAPABILITY]


class AppClosedTests(KeptOnCase):
    def test_kept_on_for_the_package_engine_it_stays_armed_with_the_app_closed(self):
        self.app_open(self.package)
        self.written_on(self.package)
        rt = self.kept_on(PACKAGE_VERSION)
        self.assertEqual(self.state_now(rt), ArmingState.ARMED)
        self.rows = []                                                      # the app closes; the file stays
        self.assertEqual(self.state_now(rt), ArmingState.ARMED, "held off with the app closed: %r" % rt.arming.why)
        self.assertNotIn(CAPABILITY, rt.arming.why)

    def test_kept_on_for_bin_it_stays_armed_after_the_watcher_took_up_the_app_s_engine(self):
        """The owner's case: armed on bin's 0.167, the watcher moved to the app's 0.171, then the app closed."""
        self.written_on(self.bin_exe)
        rt = self.kept_on(BIN_VERSION)
        self.app_open(self.package)
        self.written_on(self.package)
        self.rows = []
        self.assertEqual(self.state_now(rt), ArmingState.ARMED, "held off with the app closed: %r" % rt.arming.why)
        self.assertEqual(rt.state.arming()[CAPABILITY]["state"], ArmingState.ARMED, "the stored row never moves")


class StillHeldTests(KeptOnCase):
    def test_what_cannot_be_bound_still_holds_it_back_and_writes_nothing(self):
        for change in ("replaced", "gone", "not signed"):
            with self.subTest(change):
                self.setUp()
                self.app_open(self.package)
                self.written_on(self.package)
                rt = self.kept_on(PACKAGE_VERSION)
                self.rows = []
                if change == "replaced":
                    self.package.write_bytes(b"MZ-another-build-of-other-length")
                elif change == "gone":
                    self.package.unlink()
                else:
                    self.signed = set()
                    pairing._OFFICIAL.clear()
                self.assertEqual(self.state_now(rt), ArmingState.OFF)
                self.assertEqual(rt.arming.why.get(CAPABILITY), str(ArmingWarning.COMPAT_UNKNOWN))
                self.assertEqual(rt.state.arming()[CAPABILITY]["state"], ArmingState.ARMED, "held, not turned off")


if __name__ == "__main__":
    unittest.main()

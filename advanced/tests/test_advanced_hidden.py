"""A capability that cannot work on any Codex measured so far is hidden (the owner's rule of 2026-10-16): no row on the
Advanced features page, no statement, no switch - its definition and its probe kept - and offered once its
measurement passes. The one gate: registry.WAITING and registry.offered. Codex's own retry settings wait there - on MB
until v0.6.22, on MB2 (its new route) since; MB stays the plain route's failed record - (and, from v0.6.19, Continue
inside the turn, on M4 and M4B).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.measured import MEASURED  # noqa: E402
from codex_auto_resume_advanced.registry import CODEX_RETRY_SETTINGS, Registry, offered, problems  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict  # noqa: E402

ENGINE = "codex-cli 0.162.0-alpha.17.2"


class HiddenTests(unittest.TestCase):
    def test_on_a_fail_or_none_it_is_nowhere_a_person_looks(self):
        """Fails with the gate reverted: the switch for a capability that cannot work would be offered."""
        self.assertEqual(MEASURED[Measurement.MB][0], Verdict.FAIL)
        self.assertNotIn(Measurement.MB2, MEASURED)
        self.assertEqual(offered({}), ())
        self.assertEqual(offered({Measurement.MB2: (Verdict.FAIL, ENGINE)}), ())
        self.assertEqual(offered({Measurement.MB: (Verdict.PASS, ENGINE)}), (), "the plain route no longer lets it out")
        self.assertIsNone(registry.REGISTRY.get("codex_retry_settings"))
        self.assertNotIn(CODEX_RETRY_SETTINGS, registry.DEFINITIONS)
        self.assertNotIn("codex_retry_settings", registry.SHOWN_ORDER)
        # v0.6.22: its statement is written, as Continue inside the turn's is, so a pass offers it whole; it is shown
        # nowhere while no row is (test_advanced_page_* build the page from the registry this edition runs).
        english = statement.CATALOGS.words("en")
        self.assertIn("name.codex_retry_settings", english)

    def test_on_a_pass_it_is_offered_after_the_others(self):
        let_out = offered({Measurement.MB2: (Verdict.PASS, ENGINE)})
        self.assertEqual(let_out, (CODEX_RETRY_SETTINGS,))
        made = Registry(registry.DEFINITIONS + let_out)
        self.assertEqual(made.ids[-1], "codex_retry_settings")

    def test_its_definition_is_kept_whole(self):
        self.assertEqual(problems(CODEX_RETRY_SETTINGS), [])
        self.assertEqual(CODEX_RETRY_SETTINGS.measurements, (Measurement.MB2,))
        # v0.6.19 (#50): open_to_send waits there too, on MOPEN (test_advanced_open_target holds it); v0.6.20: Continue
        # inside the turn on MHK, M4 and M4B together (test_advanced_hook_claim).
        self.assertEqual([measurement for _definition, measurement in registry.WAITING],
                         [Measurement.MB2, Measurement.MOPEN, (Measurement.MHK, Measurement.M4, Measurement.M4B),
                          (Measurement.MPROFILE, Measurement.MSWAP)])


if __name__ == "__main__":
    unittest.main()

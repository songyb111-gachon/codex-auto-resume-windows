"""The wire goldens record core's kinds of notice, whatever an earlier test in the same process registered (v0.6.20-beta.2).

codex_auto_resume.notice_kinds keeps an edition's kinds for the life of a process. After the CI parts were dealt again, an
advanced test ran before test_wire_goldens in one part and left the plug's kinds in `describe` (dev CI 40761286107). Here a
kind is registered first, as such a test leaves it, and `describe`'s golden is still the recorded one; the kind is back after.
"""
from __future__ import annotations

import unittest

import wiregolden
from codex_auto_resume import l10n, notice_kinds


class GoldensHoldCoreKindsTests(unittest.TestCase):
    def setUp(self):
        with notice_kinds._lock:
            self.before = dict(notice_kinds._registered)
        self.addCleanup(self.put_back)

    def put_back(self):
        with notice_kinds._lock:
            notice_kinds._registered.clear()
            notice_kinds._registered.update(self.before)

    def test_a_kind_left_registered_does_not_reach_the_golden_and_is_kept(self):
        notice_kinds.register("left_by_an_earlier_test", ("left_by_an_earlier_test",),
                              {locale: "Left by an earlier test" for locale in l10n.LOCALES})
        made = wiregolden.generate(["bridge/describe.json"])["bridge/describe.json"]
        self.assertNotIn("left_by_an_earlier_test", made)
        self.assertEqual(made.replace("\r\n", "\n"), wiregolden.recorded("bridge/describe.json").replace("\r\n", "\n"))
        self.assertIn("left_by_an_earlier_test", notice_kinds.ids())


if __name__ == "__main__":
    unittest.main()

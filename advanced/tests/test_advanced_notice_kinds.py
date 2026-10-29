"""This edition's kinds of notice, registered with core's registry as its plug is made (v0.6.16).

Core lists the kinds a person can keep on screen until clicked (codex_auto_resume/notice_kinds.py); an edition adds
its own through `register`, which this package calls from `create`, so the standard build names none of them. This
edition's are every notice it raises - its usage meter's warning (issue #29) and (v0.6.16) the forced stop's three -
each named by its notice's own title in every language, each with somewhere a click on it goes (notifier.click_uri).
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "tests", ROOT / "advanced" / "src", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from codex_auto_resume import config, l10n, notice_kinds, notifier, notify, settings  # noqa: E402
from codex_auto_resume_advanced import plug as advanced  # noqa: E402


class NoticeKindTests(unittest.TestCase):
    def setUp(self):
        held = patch.dict(notice_kinds._registered, clear=True)
        held.start()
        self.addCleanup(held.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = config.Paths(Path(folder.name) / "home")

    def test_making_the_plug_registers_the_usage_warning_in_every_language(self):
        self.assertIsNone(notice_kinds.kind_of("near_limit"))
        advanced.create(self.paths)
        kind = notice_kinds.kind_of("near_limit")
        self.assertIsNotNone(kind)
        self.assertEqual((kind.id, kind.notices), ("near_limit", ("near_limit",)))
        self.assertEqual(notice_kinds.ids()[len(notice_kinds.CORE)], "near_limit", "after core's own")
        for locale in l10n.LOCALES:
            with self.subTest(locale=locale):
                self.assertEqual(kind.label(locale), l10n.text("msg.toast_near_limit", locale))
        advanced.create(self.paths)
        self.assertEqual(notice_kinds.ids().count("near_limit"), 1, "a second plug changes nothing")

    def test_its_notice_stays_when_chosen_and_the_window_is_given_its_words(self):
        advanced.create(self.paths)
        notice = notifier.build("near_limit", {"minutes": 300, "percent": 92, "reset_at": None},
                                stay=["near_limit"])
        self.assertTrue(notice.stays)
        self.assertFalse(notifier.build("near_limit", {"minutes": 300, "percent": 92, "reset_at": None}).stays)
        with patch.object(l10n, "current", lambda: "ko"):
            entry = [entry for entry in settings.describe() if entry["name"] == notice_kinds.FIELD][0]
        self.assertIn("near_limit", entry["kinds"])
        self.assertEqual(entry["labels"]["near_limit"], l10n.text("msg.toast_near_limit", "ko"))

    def test_every_notice_there_is_is_a_kind_once_the_plug_is_made(self):
        """v0.6.16: the forced stop's notices near a limit (beta.4) are kinds of their own, registered beside the
        warning - so with this edition's plug made, every notice the notifier raises but a demo is one kind's."""
        advanced.create(self.paths)
        covered = [notice for kind in notice_kinds.kinds() for notice in kind.notices]
        self.assertEqual(len(covered), len(set(covered)))
        self.assertEqual(set(covered), set(notifier.STATUS) - {"demo"})
        mine = notice_kinds.ids()[len(notice_kinds.CORE):]
        self.assertEqual(mine, ("near_limit",) + tuple("near_limit_" + said for said in notify.NEAR_LIMIT_KINDS)
                         + ("update_offered", "restart_gave_up"))
        with patch.object(l10n, "current", lambda: "ko"):
            entry = [entry for entry in settings.describe() if entry["name"] == notice_kinds.FIELD][0]
        for kind_id in mine:
            with self.subTest(kind=kind_id):
                self.assertIn(kind_id, entry["kinds"])
                self.assertEqual(entry["labels"][kind_id], l10n.text("msg.toast_" + kind_id, "ko"))
        self.assertEqual(len(set(entry["labels"][kind_id] for kind_id in mine)), 6, "six names, none twice")

    def test_each_forced_stop_notice_stays_by_its_own_choice_and_a_click_on_it_opens_a_page(self):
        advanced.create(self.paths)
        for said in notify.NEAR_LIMIT_KINDS:
            kind_id = "near_limit_" + said
            detail = {"minutes": 300, "percent": None, "reset_at": None, "kind": said}
            with self.subTest(kind=kind_id):
                notice = notifier.build("near_limit", detail, stay=[kind_id])
                self.assertEqual(notice.kind, kind_id)
                self.assertTrue(notice.stays)
                self.assertTrue(dict(notice.content).get("stays"))
                self.assertFalse(notifier.build("near_limit", detail, stay=["near_limit"]).stays,
                                 "the warning's choice keeps the warning alone")
                self.assertFalse(notifier.build("near_limit", detail).stays)
                # The click rule (v0.6.16): its Open button's page, the card's face and the toast's body alike.
                self.assertEqual(notify.parse_open_uri(notice.click), "overview")
                self.assertEqual(dict(notice.content)["launch"], notice.click)
        warning = notifier.build("near_limit", {"minutes": 300, "percent": 92, "reset_at": None},
                                 stay=["near_limit_" + said for said in notify.NEAR_LIMIT_KINDS])
        self.assertFalse(warning.stays, "a forced stop's choice keeps no warning")
        self.assertEqual(notify.parse_open_uri(warning.click), "overview")


if __name__ == "__main__":
    unittest.main()

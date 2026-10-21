"""Notices that stay on screen until clicked, chosen per kind (v0.6.16, notice_kinds.py).

The owner, 2026-10-16: "알림을 클릭하기 전까지 화면에 떠있게 할 수 있게도 설정 가능하게" - then, per kind of notice: a usage
limit detected may stay while "resumed" goes away as it always did. What these hold:

* one registry of kinds - core's, named by catalog keys every language has, and an edition's, registered with its
  words in every language through `register`, the one function an edition calls - covers every notice the notifier
  raises but a demo, each once (`RegistryTests`);
* the setting stores the ids chosen, none by default, and is offered in the Dashboard alone (`SettingTests`);
* every kind, and an edition's, keeps exactly its own notices on screen when chosen and none when not
  (`PerKindTests`); the card holds such a notice until it is clicked (`CardTests`), and Windows' toast is a reminder
  that stays until it is dismissed (`ToastTests`);
* the Dashboard draws one box per kind in its Notifications card and saves the ids ticked (`WindowTests`).

Scratch values only: no real settings, no toast raised, no card where a screen shows it.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ElementTree

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import l10n, notice_card, notice_kinds, notifier, notify, settings  # noqa: E402
from codex_auto_resume.domain.plug import NULL  # noqa: E402
import guiscan  # noqa: E402
from test_notice_card import EVENTS, FULL, THREAD, build, captured_xml  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CORE_IDS = ("interruption", "starting", "resumed", "failed", "stopped", "cancelled", "needs_you", "after_sleep",
            "memory", "power")


def words(text="A made-up kind"):
    return {locale: "%s (%s)" % (text, locale) for locale in l10n.LOCALES}


def notice_of(kind):
    """A notice of a notifier kind, as built: the click and the stay decided by the notifier itself."""
    return notifier._notice(kind, {"title": "t", "body": "b"}, key=None)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        held = patch.dict(notice_kinds._registered, clear=True)      # no edition's kinds unless a test registers one
        held.start()
        self.addCleanup(held.stop)

    def test_core_kinds_are_these_and_off_by_default(self):
        self.assertEqual(notice_kinds.ids(), CORE_IDS)
        self.assertEqual(settings.defaults()[notice_kinds.FIELD], [])

    def test_every_core_kind_has_its_words_in_every_language(self):
        for kind in notice_kinds.CORE:
            for locale in l10n.LOCALES:
                with self.subTest(kind=kind.id, locale=locale):
                    own = l10n._read(locale)
                    self.assertIn(kind.key, own, "the key is in the language's own catalog, not English underneath")
                    self.assertTrue(own[kind.key].strip())
                    self.assertNotIn("{", own[kind.key], "a name, with nothing to fill in")
                    self.assertEqual(kind.label(locale), own[kind.key])
        for key in ("field.notices_stay", "help.notices_stay", "stay.after_sleep"):
            for locale in l10n.LOCALES:
                with self.subTest(key=key, locale=locale):
                    self.assertTrue(l10n._read(locale).get(key, "").strip())

    def test_every_notice_but_a_demo_is_one_kind_s_and_an_edition_s_notice_is_none_until_registered(self):
        covered = [notice for kind in notice_kinds.kinds() for notice in kind.notices]
        self.assertEqual(len(covered), len(set(covered)), "a notice is one kind's")
        # The advanced edition's usage notices - the warning and (v0.6.16) the forced stop's three - are its own kinds.
        # v0.6.18: and its weekly update check's offer; v0.6.19: and another account signed in.
        edition_notices = ({"near_limit"} | {"near_limit_" + said for said in notify.NEAR_LIMIT_KINDS}
                           | {"update_offered", "account_changed"})
        self.assertEqual(len(edition_notices), 6)
        self.assertEqual(set(covered), set(notifier.STATUS) - {"demo"} - edition_notices)
        self.assertIsNone(notice_kinds.kind_of("demo"))
        for notice in sorted(edition_notices):
            with self.subTest(notice=notice):
                self.assertIsNone(notice_kinds.kind_of(notice), "the advanced edition registers its own")

    def test_an_edition_registers_a_kind_with_its_words_in_every_language(self):
        made = notice_kinds.register("near_limit", ("near_limit",), words("Near a limit"))
        self.assertEqual(notice_kinds.ids(), CORE_IDS + ("near_limit",))
        self.assertIs(notice_kinds.kind_of("near_limit"), made)
        self.assertEqual(notice_kinds.edition_labels("ko"), {"near_limit": "Near a limit (ko)"})
        again = notice_kinds.register("near_limit", ("near_limit",), words("Again"))
        self.assertEqual(notice_kinds.ids().count("near_limit"), 1, "registering again replaces")
        self.assertEqual(again.label("de"), "Again (de)")

    def test_what_cannot_be_registered(self):
        missing = words()
        missing.pop("ko")
        for kind_id, notices, given in (("Bad-Id", ("x",), words()), ("starting", ("x",), words()),
                                        ("mine", (), words()), ("mine", ("resumed",), words()),
                                        ("mine", ("x",), missing), ("mine", ("x",), dict(words(), en=" ")),
                                        ("mine", ("x",), None)):
            with self.subTest(kind_id=kind_id, notices=notices):
                with self.assertRaises(notice_kinds.KindError):
                    notice_kinds.register(kind_id, notices, given)
        self.assertEqual(notice_kinds.ids(), CORE_IDS)


class SettingTests(unittest.TestCase):
    def setUp(self):
        held = patch.dict(notice_kinds._registered, clear=True)
        held.start()
        self.addCleanup(held.stop)

    def test_the_ids_chosen_are_stored_and_a_write_is_held_to_them(self):
        self.assertEqual(settings.validate_update({notice_kinds.FIELD: ["interruption", "near_limit"]}),
                         {notice_kinds.FIELD: ["interruption", "near_limit"]},
                         "an edition's id outlives a switch to the standard edition")
        for value in (["a", "a"], ["Bad"], "interruption", [1], ["x"] * (notice_kinds.LIMIT + 1)):
            with self.subTest(value=value):
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({notice_kinds.FIELD: value})
        self.assertEqual(notice_kinds.chosen({notice_kinds.FIELD: "nonsense"}), frozenset())
        self.assertEqual(notice_kinds.chosen(None), frozenset())

    def test_it_is_offered_in_the_dashboard_alone(self):
        entry = [entry for entry in settings.describe() if entry["name"] == notice_kinds.FIELD][0]
        self.assertEqual((entry["type"], entry["group"], entry["default"]), ("array", "windows", []))
        self.assertEqual(entry["kinds"], list(CORE_IDS))
        self.assertEqual(entry["keys"], {kind.id: kind.key for kind in notice_kinds.CORE})
        self.assertEqual(entry["labels"], {}, "core's words are the window's own catalog's")
        from codex_auto_resume import mcpserver
        self.assertNotIn(notice_kinds.FIELD, mcpserver.settings_schema()["properties"])
        notice_kinds.register("near_limit", ("near_limit",), words("Near a limit"))
        with patch.object(l10n, "current", lambda: "ja"):
            entry = [entry for entry in settings.describe() if entry["name"] == notice_kinds.FIELD][0]
        self.assertEqual(entry["kinds"], list(CORE_IDS) + ["near_limit"])
        self.assertEqual(entry["labels"], {"near_limit": "Near a limit (ja)"})

    def test_a_save_where_an_edition_s_kind_has_no_box_keeps_it(self):
        """The standard Dashboard draws no box for an edition's kind, and its Save sends what its boxes say; the
        control layer keeps every stored id this process lists no kind for, so a choice made in the advanced
        edition outlives a switch to the standard one (notice_kinds.coerce) - and where the kind is listed, ticking
        it off removes it."""
        import tempfile
        from codex_auto_resume import config, control
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        paths = config.Paths(Path(folder.name) / "home")
        layer = control.Control(paths, plug=NULL)              # the standard edition's, whatever lane this is
        settings.update(paths.settings_file, {notice_kinds.FIELD: ["interruption", "near_limit"]})
        saved = layer.update_settings({notice_kinds.FIELD: ["starting"]})
        self.assertEqual(saved[notice_kinds.FIELD], ["starting", "near_limit"], "the edition's id is carried through")
        self.assertEqual(settings.load(paths.settings_file)[notice_kinds.FIELD], ["starting", "near_limit"])
        self.assertEqual(layer.update_settings({"notifications": True})[notice_kinds.FIELD], ["starting", "near_limit"])
        notice_kinds.register("near_limit", ("near_limit",), words())
        self.assertEqual(layer.update_settings({notice_kinds.FIELD: ["starting"]})[notice_kinds.FIELD], ["starting"],
                         "listed here, so ticked off here")


class PerKindTests(unittest.TestCase):
    def setUp(self):
        held = patch.dict(notice_kinds._registered, clear=True)
        held.start()
        self.addCleanup(held.stop)

    def check_kind(self, kind):
        others = [other.id for other in notice_kinds.kinds() if other.id != kind.id]
        for notice in kind.notices:
            with self.subTest(kind=kind.id, notice=notice):
                chosen = notifier._with_click(notice_of(notice), stay=[kind.id])
                self.assertTrue(chosen.stays)
                self.assertIs(dict(chosen.content).get("stays"), True)
                for stay in ((), others):
                    plain = notifier._with_click(notice_of(notice), stay=stay)
                    self.assertFalse(plain.stays)
                    self.assertNotIn("stays", dict(plain.content))

    def test_each_core_kind_keeps_its_own_notices_and_no_other_s(self):
        for kind in notice_kinds.CORE:
            self.check_kind(kind)

    def test_an_edition_s_kind_keeps_its_notices_once_registered(self):
        self.assertFalse(notifier._with_click(notice_of("near_limit"), stay=["near_limit"]).stays,
                         "a kind nobody registered keeps nothing")
        self.check_kind(notice_kinds.register("near_limit", ("near_limit",), words()))

    def test_the_events_the_watcher_announces_stay_as_chosen(self):
        for event, detail, identity in EVENTS:
            notice = notifier.build(event, dict(detail, thread_id=THREAD), identity, stay=CORE_IDS)
            with self.subTest(event=event):
                self.assertTrue(notice.stays)
                self.assertFalse(notifier.build(event, dict(detail, thread_id=THREAD), identity).stays)
        self.assertTrue(notifier.build_cancelled(THREAD, ["cancelled"]).stays)
        self.assertTrue(notifier.build_power_stopped(["power"]).stays)
        self.assertFalse(notifier.build_demo(0.0).stays)


class ToastTests(unittest.TestCase):
    def test_a_toast_that_stays_is_a_reminder_with_a_way_to_close_it_and_its_old_sound(self):
        root = ElementTree.fromstring(notify._toast_xml("t", "b", stays=True))
        self.assertEqual(root.get("scenario"), "reminder")
        actions = list(root.iter("action"))
        self.assertEqual([(a.get("activationType"), a.get("arguments"), a.get("content")) for a in actions],
                         [("system", "dismiss", "")], "Windows' own Dismiss, in Windows' own words")
        self.assertEqual(root.find("audio").get("src"), notify.DEFAULT_SOUND)

    def test_its_own_buttons_its_silence_and_a_chosen_sound_are_kept(self):
        root = ElementTree.fromstring(notify._toast_xml("t", "b", "Open", "u", stays=True))
        self.assertEqual([a.get("arguments") for a in root.iter("action")], ["u"])
        quiet = ElementTree.fromstring(notify._toast_xml("t", "b", stays=True, silent=True))
        self.assertEqual(quiet.find("audio").get("silent"), "true")
        chosen = ElementTree.fromstring(notify._toast_xml("t", "b", stays=True, sound=True))
        self.assertEqual(chosen.find("audio").get("src"), notify.NEEDS_YOU_SOUND)

    def test_a_toast_that_goes_is_what_it_always_was(self):
        self.assertEqual(notify._toast_xml("t", "b"), notify._toast_xml("t", "b", stays=False))
        self.assertNotIn("scenario", notify._toast_xml("t", "b"))

    def test_the_watcher_s_toast_carries_it(self):
        notice = notifier.build("starting", {"thread_id": THREAD}, FULL, stay=["starting"])
        documents = captured_xml(lambda: notifier.deliver(notice, inbox=None))
        self.assertEqual(ElementTree.fromstring(documents[0]["XML"]).get("scenario"), "reminder")


class CardTests(unittest.TestCase):
    def test_a_hold_until_clicked_never_runs_out_and_asks_for_no_timer(self):
        motion = notice_card.CardMotion(0.0, hold_ms=notice_card.UNTIL_CLICKED)
        self.assertTrue(math.isinf(notice_card.UNTIL_CLICKED))
        for now in (1_000.0, 600_000.0, 86_400_000.0):
            self.assertEqual(motion.frame(now).alpha, 1.0)
            self.assertFalse(motion.gone)
            self.assertIsNone(motion.wait_ms(now))
        motion.pause(90_000_000.0, True)
        motion.pause(90_000_100.0, False)
        self.assertEqual(motion.frame(99_000_000.0).alpha, 1.0, "pointed at and left, it still stays")
        motion.retire(99_000_000.0)
        self.assertTrue(motion.frame(99_000_000.0 + notice_card.EXIT_MS + 1).alpha == 0.0)

    @unittest.skipUnless(os.name == "nt", "the card is a Windows window")
    def test_the_card_of_a_notice_that_stays_holds_until_it_is_clicked(self):
        from codex_auto_resume import notice_window
        from codex_auto_resume.ui import popup as tray_popup
        tray_popup._gdiplus_acquire()
        self.addCleanup(tray_popup._gdiplus_release)
        now = [0.0]
        stack = notice_window.CardStack(
            clock=lambda: now[0], appearance=lambda: {"theme": "light", "contrast": False, "reduced": False},
            locate=lambda: {"work": (-24000, -24000, -22000, -22800), "monitor": (-24000, -24000, -22000, -22752),
                            "anchor": None, "dpi": 96},
            worker=lambda target, *args: target(*args)).create()
        self.addCleanup(stack.destroy)
        stays = stack.show(notifier.build("starting", {"thread_id": THREAD}, FULL, stay=["starting"]))
        goes = stack.show(build("resumed", {}, thread="0a1b2c3d-0002-7000-8000-000000000002"))
        now[0] = stack.hold() + notice_card.EXIT_MS + 60_000.0
        stack._tick()
        self.assertIn(stays, stack.cards)
        self.assertNotIn(goes, stack.cards)
        middle = ((stays.size[1] // 2) << 16) | 4
        stack._handle(stays.body.hwnd, notice_window.WM_LBUTTONDOWN, 0, middle)
        stack._handle(stays.body.hwnd, notice_window.WM_LBUTTONUP, 0, middle)
        now[0] += notice_card.EXIT_MS + 1
        stack._tick()
        self.assertEqual(stack.cards, [])


class WindowTests(unittest.TestCase):
    def test_the_dashboard_draws_a_box_per_kind_in_its_notifications_card_and_saves_the_ids_ticked(self):
        loop = guiscan.member_body("SettingsForm", "BuildPage") if "BuildPage" in guiscan.whole() else guiscan.whole()
        self.assertIn('if (name == StayField)', loop)
        self.assertIn('BuildStay(notifications, field, current);', loop)
        build_stay = guiscan.member_body("SettingsForm", "BuildStay")
        for needed in ('Items(field, "kinds")', 'Map(field, "keys")', 'Map(field, "labels")',
                       'NewCheck(label, chosen.Contains(id), true)', 'jsonValues["notices_stay"] = StayJson;',
                       'S("help.notices_stay"', 'S("field.notices_stay"'):
            self.assertIn(needed, build_stay)
        self.assertIn('json.Append(Json.Escape(pair.Key));', guiscan.member_body("SettingsForm", "StayJson"))
        self.assertIn('internal const string StayField = "notices_stay";', guiscan.whole())
        # The kinds are their own key: every drop-down still lists its `choices` (a rename of one once emptied them).
        self.assertIn('Items(field, "choices")', guiscan.member_body("SettingsForm", "ChoiceCombo"))
        self.assertNotIn('"kinds"', guiscan.member_body("SettingsForm", "ChoiceCombo"))
        self.assertEqual(notice_kinds.FIELD, "notices_stay")


if __name__ == "__main__":
    unittest.main()

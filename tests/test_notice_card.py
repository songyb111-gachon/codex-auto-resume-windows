"""The notification card (v0.6.5, requirements 4 and 6): one notification, one route.

What these tests hold, in the order the work item's plan lists it (PLAN v2, section 7):

* the fallback is one pure decision, and a notification is shown exactly once by exactly one
  route for every combination of what Windows says (`PolicyTests`, `RouteTests`);
* the toast route is byte for byte today's toast - pinned by XML captured from the v0.6.4
  code before anything changed (`tests/fixtures/toast_golden.json`), and each engine event
  raises the toast v0.6.4's watcher raised for it (`tests/fixtures/toast_events_golden.json`,
  captured from `git archive v0.6.4`), whatever App._notifier calls (`CharacterizationTests`);
* a notice the card takes ends exactly once: its silent history copy only after the card was
  seen whole, today's toast if it never was (`RouteTests`, and on Windows `WindowsTests`);
* the card says only what the toast says, and offers exactly the toast's buttons
  (`NoticeTests`, `PrivacyTests`); a button can cancel one interruption or open a page and
  nothing else (`ActivateTests`); the hand-over to the icon's thread never blocks
  (`InboxTests`);
* the entrance, the hold, the exit and the stack are pure curves and tables (`MotionTests`,
  `StackTests`), the layout fits in every language and scale (`LayoutTests`), the floating
  shadow only ever darkens (`ShadowTests`);
* what the card modules can reach is what their source says (`SafetyTests`);
* on Windows, the real card: its pixels, its windows (placed where no screen shows them), that
  it never takes the focus, and that it leaks nothing (`WindowsTests`).
"""
from __future__ import annotations

import ast
import itertools
import json
import os
from pathlib import Path
import re
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import (brand, l10n, messages, notice_card, notice_presence, notifier, notify,
                               pwsh, reasons, settings, tray_popup)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "codex_auto_resume"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "toast_golden.json"
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
INTERRUPTION = "a1" * 32
FULL = {"name": "A task", "project": "A project", "cwd_basename": "a-repo"}

# The toasts pinned in the golden file, as the v0.6.4 functions were called to make it.
CASES = (
    ("scheduled_usage_at", "scheduled", (THREAD, INTERRUPTION, 1788645827.0, "usage_limit", FULL), {}),
    ("scheduled_usage_soon", "scheduled", (THREAD, INTERRUPTION, None, "usage_limit", {"name": "A task"}), {}),
    ("scheduled_server", "scheduled", (THREAD, INTERRUPTION, None, "server_5xx",
                                       {"name": None, "project": None, "cwd_basename": None}), {}),
    ("scheduled_rate", "scheduled", (THREAD, INTERRUPTION, None, "rate_limit_transient",
                                     {"project": "proj", "cwd_basename": "repo"}), {}),
    ("scheduled_default", "scheduled", (THREAD, INTERRUPTION, None), {}),
    ("scheduled_markup", "scheduled", (THREAD, INTERRUPTION, None, "network_transient",
                                       {"name": 'Fix <b> & "quotes"', "project": "p&q"}), {}),
    ("starting_full", "starting", (THREAD, FULL), {}),
    ("starting_none", "starting", (THREAD, None), {}),
    ("resumed_full", "resumed", (THREAD, FULL), {}),
    ("resumed_none", "resumed", (THREAD, None), {}),
    ("failed_certain", "attempt_failed", (THREAD, FULL), {"certain": True}),
    ("failed_unknown", "attempt_failed", (THREAD, FULL), {"certain": False}),
    ("stopped_no_progress", "stopped", (THREAD, FULL), {"reason": "no_progress"}),
    ("stopped_attempts", "stopped", (THREAD, FULL), {"reason": "attempts"}),
    ("stopped_other", "stopped", (THREAD, None), {}),
    ("cancelled", "cancelled", (THREAD,), {}),
)

# Engine events as app.App._notifier receives them, with the identity the source found, each by
# the name its toast has in tests/fixtures/toast_events_golden.json. That file was captured from
# the v0.6.4 tree (`git archive v0.6.4`), App._notifier with PowerShell stubbed, in all nine
# languages, and it is the pin on "this event raises that toast" whatever _notifier becomes.
NAMED_EVENTS = (
    ("interruption_usage_at", "interruption",
     {"interruption_id": INTERRUPTION, "reset_at": 1788645827.0, "category": "usage_limit"}, FULL),
    ("interruption_usage_soon", "interruption",
     {"interruption_id": INTERRUPTION, "reset_at": None, "category": "usage_limit"}, None),
    ("interruption_no_category", "interruption",
     {"interruption_id": INTERRUPTION, "reset_at": None, "category": None}, FULL),
    ("interruption_server", "interruption",
     {"interruption_id": INTERRUPTION, "reset_at": None, "category": "server_5xx"}, FULL),
    ("interruption_stream", "interruption",
     {"interruption_id": INTERRUPTION, "reset_at": None, "category": "stream_interrupted"}, {"project": "p"}),
    ("starting_full", "starting", {}, FULL),
    ("starting_none", "starting", {}, None),
    ("result_turn_started", "result", {"state": "turn_started"}, FULL),
    ("result_resumed", "result", {"state": "resumed"}, None),
    ("result_failed", "result", {"state": "submission_failed"}, FULL),
    ("result_unknown", "result", {"state": "submission_unknown"}, FULL),
    ("stopped_no_progress", "stopped", {"state": "no_progress_exhausted"}, FULL),
    ("stopped_attempts", "stopped", {"state": "retry_budget_exhausted"}, FULL),
    ("stopped_cancelled", "stopped", {"state": "cancelled"}, None),
    # Two edges of the mapping: a result state the engine does not name is a certain failure
    # (never "may have gone through"), and an event nobody announces raises nothing.
    ("result_other", "result", {"state": "not_a_state_the_engine_names"}, FULL),
    ("unannounced", "tick", {}, FULL),
)
# The events every notice test walks: all of the above that raise a notification.
EVENTS = tuple((event, detail, identity) for _name, event, detail, identity in NAMED_EVENTS[:14])
EVENTS_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "toast_events_golden.json"

ALLOWED = {"notification_state": notice_presence.QUNS_ACCEPTS_NOTIFICATIONS,
           "notification_mode": notice_presence.MODE_UNRESTRICTED,
           "app_notifications": notice_presence.APP_ENABLED, "screen_reader": False,
           "remote_session": False, "session_locked": False}


def in_locale(locale):
    """Every notification is built in the process's Interface language; set it for a block."""
    class _Scope:
        def __enter__(self):
            self.previous = l10n.preference()
            l10n.set_preference(locale)

        def __exit__(self, *unused):
            l10n.set_preference(self.previous)
    return _Scope()


def captured_xml(call):
    """Run `call()` with PowerShell stubbed; return the one toast document it raised (and its values)."""
    seen = []

    def run(script, values, timeout=None):
        seen.append(dict(values))
        return 0

    with patch.object(pwsh, "executable", return_value="powershell.exe"), \
            patch.object(pwsh, "run", side_effect=run), \
            patch.object(notify, "_local_time", return_value="14:05"):
        call()
    return seen


def build(event, detail, identity=FULL, thread=THREAD):
    return notifier.build(event, dict(detail, thread_id=thread), identity)


# ============================================================================ the decision
class PolicyTests(unittest.TestCase):
    def test_the_card_needs_every_answer_to_be_exactly_the_allowing_one(self):
        values = {
            "setting": (True, False, None, 1),
            "tray_present": (True, False, None),
            "notification_state": notice_presence.NOTIFICATION_STATES + (None, True, "5"),
            "notification_mode": notice_presence.NOTIFICATION_MODES + (None, False),
            "app_notifications": notice_presence.APP_SETTINGS + (None, False, "0"),
            "screen_reader": (False, True, None, 0),
            "remote_session": (False, True, None),
            "session_locked": (False, True, None),
        }
        names = list(values)
        allowed = 0
        for combination in itertools.product(*(values[name] for name in names)):
            arguments = dict(zip(names, combination))
            expected = (arguments["setting"] is True and arguments["tray_present"] is True
                        and arguments["screen_reader"] is False and arguments["remote_session"] is False
                        and arguments["session_locked"] is False
                        and type(arguments["notification_state"]) is int
                        and arguments["notification_state"] == notice_presence.QUNS_ACCEPTS_NOTIFICATIONS
                        and type(arguments["notification_mode"]) is int
                        and arguments["notification_mode"] == notice_presence.MODE_UNRESTRICTED
                        and type(arguments["app_notifications"]) is int
                        and arguments["app_notifications"] == notice_presence.APP_ENABLED)
            self.assertIs(notice_presence.card_allowed(**arguments), expected, arguments)
            allowed += expected
        self.assertEqual(allowed, 1, "exactly one combination shows the card")

    def test_each_state_windows_names_is_a_toast_except_accepts_notifications(self):
        for state in notice_presence.NOTIFICATION_STATES:
            with self.subTest(state=state):
                self.assertIs(notice_presence.card_allowed(setting=True, tray_present=True,
                                                           **dict(ALLOWED, notification_state=state)),
                              state == notice_presence.QUNS_ACCEPTS_NOTIFICATIONS)
        for mode in notice_presence.NOTIFICATION_MODES:        # Do not disturb, Focus: the toast
            with self.subTest(mode=mode):
                self.assertIs(notice_presence.card_allowed(setting=True, tray_present=True,
                                                           **dict(ALLOWED, notification_mode=mode)),
                              mode == notice_presence.MODE_UNRESTRICTED)

    def test_windows_own_switches_for_this_app_keep_the_card_away(self):
        """Settings > System > Notifications: this app switched off, every app switched off, or a
        policy - Windows drops the toast, so v0.6.4 showed nothing, and the card must not either."""
        for setting in notice_presence.APP_SETTINGS:
            with self.subTest(setting=setting):
                self.assertIs(notice_presence.card_allowed(setting=True, tray_present=True,
                                                           **dict(ALLOWED, app_notifications=setting)),
                              setting == notice_presence.APP_ENABLED)
        for name in ("APP_DISABLED_FOR_APPLICATION", "APP_DISABLED_FOR_USER", "APP_DISABLED_BY_GROUP_POLICY",
                     "APP_DISABLED_BY_MANIFEST"):
            self.assertIn(getattr(notice_presence, name), notice_presence.APP_SETTINGS)
        # Windows.UI.Notifications.NotificationSetting, as the platform numbers it.
        self.assertEqual(notice_presence.APP_SETTINGS, (0, 1, 2, 3, 4))
        self.assertEqual(notice_presence.APP_ENABLED, 0)

    def test_the_snapshot_has_exactly_the_decisions_inputs(self):
        with patch.object(notice_presence, "notification_state", return_value=5), \
                patch.object(notice_presence, "notification_mode", return_value=0), \
                patch.object(notice_presence, "app_notifications", return_value=0) as app_setting, \
                patch.object(notice_presence, "screen_reader", return_value=False), \
                patch.object(notice_presence, "remote_session", return_value=False), \
                patch.object(notice_presence, "session_locked", return_value=False):
            answers = notice_presence.snapshot("CodexAutoResume.Watcher")
        app_setting.assert_called_once_with("CodexAutoResume.Watcher")
        self.assertEqual(set(answers), set(notifier.PROBES))
        self.assertTrue(notice_presence.card_allowed(setting=True, tray_present=True, **answers))

    def test_without_the_apps_identity_windows_cannot_be_asked_so_it_is_the_toast(self):
        for aumid in (None, "", "  ", 7):
            with self.subTest(aumid=aumid):
                self.assertIsNone(notice_presence.app_notifications(aumid))
        with patch.object(notice_presence, "notification_state", return_value=5), \
                patch.object(notice_presence, "notification_mode", return_value=0), \
                patch.object(notice_presence, "screen_reader", return_value=False), \
                patch.object(notice_presence, "remote_session", return_value=False), \
                patch.object(notice_presence, "session_locked", return_value=False):
            answers = notice_presence.snapshot()
        self.assertIsNone(answers["app_notifications"])
        self.assertFalse(notice_presence.card_allowed(setting=True, tray_present=True, **answers))

    def test_the_notifier_asks_about_the_products_own_identity(self):
        from codex_auto_resume import startup
        inbox = notifier.Inbox()
        inbox.attach(lambda: True)
        with patch.object(notice_presence, "snapshot", return_value=dict(ALLOWED)) as snapshot:
            route = notifier.deliver(build("starting", {}), inbox=inbox, show=lambda content, silent=False: True)
        snapshot.assert_called_once_with(startup.AUMID)
        self.assertEqual(route[0], "card")

    def test_the_hold_follows_windows_when_windows_keeps_notifications_longer(self):
        self.assertEqual(notice_card.hold_ms(None), notice_card.HOLD_MS)
        self.assertEqual(notice_card.hold_ms(5000), notice_card.HOLD_MS)
        self.assertEqual(notice_card.hold_ms(30000), 30000)
        self.assertEqual(notice_card.hold_ms(True), notice_card.HOLD_MS)

    @unittest.skipUnless(os.name == "nt", "the probes ask Windows")
    def test_the_live_probes_answer_in_their_own_vocabulary_or_not_at_all(self):
        from codex_auto_resume import startup
        answers = notice_presence.snapshot(startup.AUMID)
        self.assertIn(answers["notification_state"], notice_presence.NOTIFICATION_STATES + (None,))
        self.assertIn(answers["notification_mode"], notice_presence.NOTIFICATION_MODES + (None,))
        self.assertIn(answers["app_notifications"], notice_presence.APP_SETTINGS + (None,))
        for name in ("screen_reader", "remote_session", "session_locked"):
            self.assertIn(answers[name], (True, False, None), name)
        self.assertIsInstance(notice_presence.battery_saver(), bool)
        duration = notice_presence.message_duration_ms()
        self.assertTrue(duration is None or duration >= 1000)

    @unittest.skipUnless(os.name == "nt", "WinRT")
    def test_the_notification_mode_probe_survives_a_thread_with_com_already_up(self):
        import ctypes
        found = []

        def probe():
            ctypes.WinDLL("ole32").CoInitializeEx(None, 2)            # apartment-threaded first
            try:
                found.append(notice_presence.notification_mode())
                found.append(notice_presence.app_notifications("CodexAutoResume.Watcher"))
            finally:
                ctypes.WinDLL("ole32").CoUninitialize()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(30)
        self.assertEqual(len(found), 2)
        self.assertIn(found[0], notice_presence.NOTIFICATION_MODES + (None,))
        self.assertIn(found[1], notice_presence.APP_SETTINGS + (None,))

    IDENTITY = "CodexAutoResume.Watcher"      # asked about, never registered or changed by asking

    @unittest.skipUnless(os.name == "nt", "WinRT")
    def test_the_app_setting_probe_reads_windows_answer_again_and_again(self):
        """Every call brings COM up and down again and releases what it made: a hundred calls in
        a row answer the same, and the thread's own apartment is left as it was found."""
        import ctypes
        found = {}

        def probe():
            # A thread of its own, with no COM on it: afterwards there must still be none.
            found["answers"] = [notice_presence.app_notifications(self.IDENTITY) for _ in range(100)]
            ole32 = ctypes.WinDLL("ole32")
            ole32.CoInitializeEx.restype = ctypes.c_long
            ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            found["after"] = ole32.CoInitializeEx(None, 2)       # S_OK only on a thread without COM
            if found["after"] in (0, 1):
                ole32.CoUninitialize()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(60)
        answers = found["answers"]
        self.assertEqual(len(set(answers)), 1, sorted(set(answers), key=repr))
        # Windows' own answer, or none at all: a Windows where the watcher's identity was never
        # registered (a CI runner's) gives no answer, and must give none every time - the card is
        # then kept away and the toast decides, as card_allowed's own tests pin. Checked on every
        # machine rather than skipped where the answer is None, so the hundred-call round and the
        # apartment check run everywhere.
        self.assertIn(answers[0], notice_presence.APP_SETTINGS + (None,))
        self.assertEqual(found["after"], 0, "the probe left COM up on a thread that did not have it")


class _Host:
    """An inbox's far end: records what it was handed, and can refuse to wake."""

    def __init__(self, wakes=True):
        self.wakes = wakes
        self.woken = 0

    def wake(self):
        self.woken += 1
        return self.wakes


class RouteTests(unittest.TestCase):
    def deliver(self, notice, *, setting=True, attached=True, wakes=True, answers=ALLOWED):
        inbox = notifier.Inbox()
        host = _Host(wakes)
        if attached:
            inbox.attach(host.wake)
        shown = []

        def show(content, silent=False):
            shown.append(("silent" if silent else "toast", content))
            return True

        route = notifier.deliver(notice, inbox=inbox, setting=setting, probe=lambda: answers, show=show)
        return route, shown, inbox.take()

    def test_a_notification_is_shown_exactly_once_by_exactly_one_route(self):
        """For every answer Windows can give, and for both ways a card's host can end: the card
        was put on screen (then, and only then, the silent copy for history), or it could not be
        (then today's toast instead). Never both, never neither, and never two toasts."""
        notice = build("interruption", EVENTS[0][1])
        probes = [dict(ALLOWED)] + [dict(ALLOWED, **{name: value}) for name, value in (
            ("notification_state", notice_presence.QUNS_BUSY), ("notification_state", None),
            ("notification_mode", notice_presence.MODE_PRIORITY_ONLY), ("screen_reader", True),
            ("app_notifications", notice_presence.APP_DISABLED_FOR_APPLICATION),
            ("app_notifications", notice_presence.APP_DISABLED_FOR_USER), ("app_notifications", None),
            ("remote_session", True), ("session_locked", True), ("session_locked", None))]
        for setting, attached, wakes, answers, drawn in itertools.product(
                (True, False), (True, False), (True, False), probes, (True, False)):
            with self.subTest(setting=setting, attached=attached, wakes=wakes, answers=answers, drawn=drawn):
                (route, _), shown, handed = self.deliver(notice, setting=setting, attached=attached,
                                                         wakes=wakes, answers=answers)
                card = (setting and attached and wakes and answers == ALLOWED)
                self.assertEqual(route, "card" if card else "toast")
                self.assertEqual(bool(handed), card)
                # On the card route nothing is raised yet: the host decides how the notice ends.
                self.assertEqual([kind for kind, _ in shown], [] if card else ["toast"])
                if card:
                    notifier.complete(handed[0], drawn,
                                      show=lambda content, silent=False: shown.append(
                                          ("silent" if silent else "toast", content)) or True)
                visible = [kind for kind, _ in shown if kind == "toast"] + (["card"] if card and drawn else [])
                self.assertEqual(len(visible), 1, "one visible notification, by one route")
                self.assertEqual(len(shown), 1, "one entry in Windows' notification center, either way")
                self.assertEqual([kind for kind, _ in shown], ["silent" if card and drawn else "toast"])
                self.assertEqual(shown[0][1], notice.toast_content(), "the same toast either way")

    def test_completing_is_strict_about_what_counts_as_shown(self):
        notice = build("starting", {})
        for drawn, expected in ((True, [True]), (False, [False]), (None, [False]), (1, [False]), ("yes", [False])):
            with self.subTest(drawn=drawn):
                seen = []
                self.assertTrue(notifier.complete(notice, drawn, show=lambda content, silent=False:
                                                  seen.append(silent) or True))
                self.assertEqual(seen, expected)
        self.assertFalse(notifier.complete(notice, True, show=lambda content, silent=False: False))

    def test_a_probe_that_breaks_is_the_toast(self):
        notice = build("starting", {})
        inbox = notifier.Inbox()
        inbox.attach(lambda: True)
        shown = []
        route = notifier.deliver(notice, inbox=inbox, probe=MagicMock(side_effect=OSError("no")),
                                 show=lambda content, silent=False: shown.append(silent) or True)
        self.assertEqual(route, ("toast", True))
        self.assertEqual(shown, [False])
        self.assertEqual(inbox.take(), [])

    def test_without_an_inbox_nothing_is_probed(self):
        probe = MagicMock(return_value=ALLOWED)
        route = notifier.deliver(build("starting", {}), inbox=None, probe=probe,
                                 show=lambda content, silent=False: True)
        self.assertEqual(route, ("toast", True))
        probe.assert_not_called()


# ================================================================== what the toast says
class CharacterizationTests(unittest.TestCase):
    """Nothing about today's toast moved."""

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_the_golden_covers_every_language_and_case(self):
        self.assertEqual(set(self.golden), set(l10n.LOCALES))
        for locale in l10n.LOCALES:
            self.assertEqual(set(self.golden[locale]), {name for name, *_ in CASES})

    def test_every_toast_is_byte_for_byte_what_v064_raised(self):
        for locale in l10n.LOCALES:
            with in_locale(locale):
                for name, function, arguments, keywords in CASES:
                    with self.subTest(locale=locale, case=name):
                        seen = captured_xml(lambda: getattr(notify, function)(*arguments, **keywords))
                        self.assertEqual(len(seen), 1)
                        self.assertEqual(seen[0]["XML"], self.golden[locale][name])
                        self.assertNotIn("SILENT", seen[0], "the ordinary toast passes nothing new")

    def test_the_event_golden_is_complete(self):
        events = json.loads(EVENTS_GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(set(events), set(l10n.LOCALES))
        for locale in l10n.LOCALES:
            self.assertEqual(set(events[locale]), {name for name, *_ in NAMED_EVENTS})
            # Each announced event raised exactly one toast in v0.6.4; the unannounced one none.
            self.assertEqual({name: len(documents) for name, documents in events[locale].items()},
                             {name: 0 if name == "unannounced" else 1 for name, *_ in NAMED_EVENTS})

    def test_each_event_raises_the_toast_v064_raised_for_it(self):
        """The event -> toast mapping, pinned to documents captured from the v0.6.4 tree - not to
        App._notifier, which is about to call the very builder this checks."""
        events = json.loads(EVENTS_GOLDEN.read_text(encoding="utf-8"))
        for locale in l10n.LOCALES:
            with in_locale(locale):
                for name, event, detail, identity in NAMED_EVENTS:
                    with self.subTest(locale=locale, event=name):
                        def announce(event=event, detail=detail, identity=identity):
                            notice = notifier.build(event, dict(detail, thread_id=THREAD), identity)
                            return notice is not None and notifier.deliver(notice, inbox=None)
                        raised = captured_xml(announce)
                        self.assertEqual([values["XML"] for values in raised], events[locale][name])

    def test_the_watcher_still_raises_those_toasts_whatever_its_notifier_calls(self):
        """App._notifier end to end, against the same documents: this holds its wiring, before
        and after it is pointed at the notifier (a host with no card inbox raises the toast)."""
        from codex_auto_resume import app
        events = json.loads(EVENTS_GOLDEN.read_text(encoding="utf-8"))
        everything = dict(settings.defaults(), notifications=True,
                          **{"notify_" + event: True for event in settings.NOTIFICATION_EVENTS})
        for locale in ("en", "ko", "de"):
            with in_locale(locale):
                for name, event, detail, identity in NAMED_EVENTS:
                    with self.subTest(locale=locale, event=name):
                        source = types.SimpleNamespace(identity=lambda thread, identity=identity: identity)
                        host = types.SimpleNamespace(settings=everything, _inbox=None)
                        announce = app.App._notifier(host, source)
                        raised = captured_xml(lambda: announce(event, dict(detail, thread_id=THREAD)))
                        self.assertEqual([values["XML"] for values in raised], events[locale][name])

    def test_an_event_the_watcher_never_announced_builds_nothing(self):
        self.assertIsNone(notifier.build("tick", {"thread_id": THREAD}))
        self.assertIsNone(notifier.build(None, None))


class SilentCopyTests(unittest.TestCase):
    def test_the_history_copy_is_the_same_toast_made_silent(self):
        for name, function, arguments, keywords in CASES:
            content = getattr(notify, function + "_content")(*arguments, **keywords)
            loud = notify._toast_xml(content["title"], content["body"], content.get("button"),
                                     content.get("uri"), content.get("extra", ()), content.get("more", ()))
            quiet = notify._toast_xml(content["title"], content["body"], content.get("button"),
                                      content.get("uri"), content.get("extra", ()), content.get("more", ()),
                                      silent=True)
            with self.subTest(case=name):
                self.assertEqual(quiet.replace('<audio silent="true"/>', "", 1), loud)
                self.assertEqual(quiet.count('<audio silent="true"/>'), 1)
                self.assertIn('</visual><audio silent="true"/>', quiet)

    def test_silent_travels_as_a_value_and_only_when_asked(self):
        seen = captured_xml(lambda: notify.show("t", "b", silent=True))
        self.assertEqual(seen[0]["SILENT"], "1")
        self.assertIn("<audio silent=\"true\"/>", seen[0]["XML"])
        for value in (False, 1, "yes", None):
            with self.subTest(value=value):
                seen = captured_xml(lambda: notify.show("t", "b", silent=value))
                self.assertNotIn("SILENT", seen[0])
                self.assertNotIn("<audio", seen[0]["XML"])

    def test_the_script_turns_the_banner_off_from_the_value_alone(self):
        self.assertIn("if ($env:CODEX_AUTO_RESUME_ARG_SILENT -eq '1') { $toast.SuppressPopup = $true }",
                      notify._SCRIPT)
        # The toast is created before the line and shown after it.
        self.assertLess(notify._SCRIPT.index("$toast = New-Object"), notify._SCRIPT.index("SuppressPopup"))
        self.assertLess(notify._SCRIPT.index("SuppressPopup"), notify._SCRIPT.index(".Show($toast)"))


# ======================================================================= the notice
class NoticeTests(unittest.TestCase):
    def test_every_kind_wears_a_brand_status_light(self):
        for kind, state in notifier.STATUS.items():
            with self.subTest(kind=kind):
                self.assertIn(state, brand.STATUS_FILL)

    def test_the_cards_buttons_are_the_toasts_buttons(self):
        from xml.etree import ElementTree
        for event, detail, identity in EVENTS:
            notice = build(event, detail, identity)
            content = notice.toast_content()
            xml = notify._toast_xml(content["title"], content["body"], content.get("button"), content.get("uri"),
                                    content.get("extra", ()), content.get("more", ()))
            buttons = tuple((node.get("content"), node.get("arguments"))
                            for node in ElementTree.fromstring(xml).findall("./actions/action"))
            with self.subTest(event=event, detail=detail):
                self.assertEqual(notice.actions, buttons)
                vm = notice_card.view(notice)
                self.assertEqual(tuple((action["label"], action["uri"]) for action in vm["actions"]), buttons)

    def test_only_a_detected_interruption_offers_anything(self):
        for event, detail, identity in EVENTS:
            notice = build(event, detail, identity)
            with self.subTest(event=event, detail=detail):
                if event == "interruption":
                    self.assertEqual([uri for _, uri in notice.actions],
                                     [notify.cancel_uri(INTERRUPTION), notify.open_uri("pending")])
                    self.assertEqual([action["primary"] for action in notice_card.view(notice)["actions"]],
                                     [False, True])
                else:
                    self.assertEqual(notice.actions, ())

    def test_the_lines_are_the_toasts_lines(self):
        for event, detail, identity in EVENTS:
            notice = build(event, detail, identity)
            content = notice.toast_content()
            with self.subTest(event=event, detail=detail):
                self.assertEqual(notice.title, content["title"])
                self.assertEqual(notice.origin, content["body"])
                if event == "interruption" and (detail.get("category") or "usage_limit") != "usage_limit":
                    # The chip names the reason, so the line is the toast's line without its label.
                    self.assertEqual(notice.line, messages.text("toast_transient"))
                    self.assertTrue(content["extra"][0].endswith(notice.line))
                    self.assertTrue(content["extra"][0].startswith(notice.chip))
                else:
                    self.assertEqual(notice.line, content["extra"][0])

    def test_the_chip_is_the_reasons_catalog_label(self):
        for category in ("usage_limit", "server_5xx", "network_transient", "timeout"):
            with self.subTest(category=category):
                notice = build("interruption", {"interruption_id": INTERRUPTION, "category": category})
                self.assertEqual(notice.chip, l10n.text(reasons.label_key(category), messages.language()))
                self.assertIn(notice.chip_tone, brand.LIGHT)
        self.assertIsNone(build("starting", {}).chip)

    def test_a_newer_notice_about_a_conversation_knows_which_it_is(self):
        self.assertEqual(build("starting", {}).key, THREAD)
        self.assertEqual(notifier.build_cancelled(THREAD).key, THREAD)

    def test_the_cancelled_notice_is_what_the_toast_button_raised(self):
        notice = notifier.build_cancelled(THREAD)
        self.assertEqual(notice.toast_content(), notify.cancelled_content(THREAD))
        self.assertEqual(notice.status, "paused")

    def test_a_notice_speaks_the_interface_language(self):
        for locale in l10n.LOCALES:
            with in_locale(locale):
                notice = build("starting", {})
            with self.subTest(locale=locale):
                self.assertEqual(notice.locale, locale)
                self.assertEqual(notice.line, l10n.catalog(locale)["msg.toast_starting_body"])


class PrivacyTests(unittest.TestCase):
    """The card draws no field the toast does not: no prompt, no error text, no new identifier."""

    SECRET_PROMPT = "please refactor the payment module using the API key sk-12345"
    SECRET_ERROR = "HTTP 429: rate_limit_exceeded for org-abc on model gpt-x"

    def notices(self):
        detail = {"interruption_id": INTERRUPTION, "category": "rate_limit_transient", "reset_at": None,
                  # Whatever else a detail might carry, the builder reads only what the toast reads.
                  "prompt": self.SECRET_PROMPT, "error": self.SECRET_ERROR, "last_error": self.SECRET_ERROR}
        for event, extra, _identity in EVENTS:
            yield build(event, dict(detail, **extra))

    def test_the_card_draws_only_the_toasts_words_and_catalog_words(self):
        def flat(text):
            # The card sets a line on one line: runs of spaces are one space, and a line too long
            # for the card ends in an ellipsis. Neither adds a word.
            return " ".join(str(text).split()).rstrip("…")

        catalog_words = set()
        for locale in l10n.LOCALES:
            catalog_words.update(flat(value) for value in l10n.catalog(locale).values())
        for notice in self.notices():
            vm = notice_card.view(notice)
            content = notice.toast_content()
            toast_lines = [content["title"], content["body"]] + list(content.get("extra", ()))
            toast_words = flat(" ".join(toast_lines + [label for label, _ in notice.actions]))
            for text in notice_card.texts(vm):
                with self.subTest(kind=notice.kind, text=text):
                    self.assertTrue(flat(text) in toast_words or flat(text) in catalog_words, text)
            drawn = " ".join(notice_card.texts(vm))
            self.assertNotIn(self.SECRET_PROMPT, drawn)
            self.assertNotIn(self.SECRET_ERROR, drawn)
            self.assertNotIn("sk-12345", drawn)
            self.assertNotIn(INTERRUPTION, drawn, "the capability id stays in the button's URI")

    def test_the_notice_carries_no_field_it_was_not_built_from(self):
        for notice in self.notices():
            flat = repr(notice)
            self.assertNotIn(self.SECRET_PROMPT, flat)
            self.assertNotIn(self.SECRET_ERROR, flat)


# ============================================================================ the inbox
class InboxTests(unittest.TestCase):
    def test_nothing_is_accepted_without_a_host(self):
        inbox = notifier.Inbox()
        self.assertFalse(inbox.attached)
        self.assertFalse(inbox.post("n"))
        self.assertEqual(inbox.take(), [])

    def test_a_posted_notice_wakes_the_host_and_is_taken_once_in_order(self):
        inbox, host = notifier.Inbox(), _Host()
        inbox.attach(host.wake)
        self.assertTrue(inbox.post("a"))
        self.assertTrue(inbox.post("b"))
        self.assertEqual(host.woken, 2)
        self.assertEqual(inbox.take(), ["a", "b"])
        self.assertEqual(inbox.take(), [])

    def test_a_host_that_cannot_be_woken_leaves_nothing_behind(self):
        inbox, host = notifier.Inbox(), _Host(wakes=False)
        inbox.attach(host.wake)
        self.assertFalse(inbox.post("a"))
        self.assertEqual(inbox.take(), [])
        inbox.attach(MagicMock(side_effect=OSError("gone")))
        self.assertFalse(inbox.post("b"))
        self.assertEqual(inbox.take(), [])

    def test_a_host_that_has_fallen_behind_hands_the_rest_to_the_toast(self):
        inbox = notifier.Inbox()
        inbox.attach(lambda: True)
        results = [inbox.post(index) for index in range(notifier.Inbox.LIMIT + 3)]
        self.assertEqual(results, [True] * notifier.Inbox.LIMIT + [False] * 3)
        self.assertEqual(len(inbox.take()), notifier.Inbox.LIMIT)

    def test_detaching_hands_back_what_was_waiting_and_accepts_nothing_more(self):
        """A notice `post` said the host had is never simply dropped: the host going away gets
        it back, to raise as today's toast (notice_window.CardStack.destroy)."""
        inbox = notifier.Inbox()
        inbox.attach(lambda: True)
        inbox.post("a")
        inbox.post("b")
        self.assertEqual(inbox.detach(), ["a", "b"])
        self.assertFalse(inbox.attached)
        self.assertEqual(inbox.take(), [])
        self.assertEqual(inbox.detach(), [])
        self.assertFalse(inbox.post("c"))

    def test_many_threads_lose_nothing_and_duplicate_nothing(self):
        inbox = notifier.Inbox()
        inbox.attach(lambda: True)
        taken = []

        def producer(base):
            for index in range(50):
                while not inbox.post((base, index)):
                    taken.extend(inbox.take())

        threads = [threading.Thread(target=producer, args=(base,)) for base in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        taken.extend(inbox.take())
        self.assertEqual(sorted(taken), sorted((base, index) for base in range(6) for index in range(50)))


# ======================================================================== the buttons
class ActivateTests(unittest.TestCase):
    def test_an_open_uri_opens_one_of_the_windows_pages(self):
        opened = []
        result = notifier.activate(notify.open_uri("pending"), open_dashboard=lambda page: opened.append(page) or True)
        self.assertEqual((result, opened), ("opened", ["pending"]))
        self.assertEqual(notifier.activate(notify.open_uri("pending"), open_dashboard=lambda page: False),
                         "not_installed")
        self.assertEqual(notifier.activate("codex-auto-resume:open?page=elsewhere",
                                           open_dashboard=lambda page: self.fail("opened")), "ignored")

    def test_a_cancel_uri_cancels_exactly_that_interruption_as_the_toast(self):
        control = MagicMock()
        control.cancel_interruption.return_value = {"thread_id": THREAD, "changed": True}
        announced = []
        result = notifier.activate(notify.cancel_uri(INTERRUPTION), control=control, announce=announced.append)
        self.assertEqual(result, "cancelled")
        control.cancel_interruption.assert_called_once_with(INTERRUPTION, actor="toast")
        self.assertEqual([notice.kind for notice in announced], ["cancelled"])
        self.assertEqual(announced[0].toast_content(), notify.cancelled_content(THREAD))
        # The control layer is asked for one thing, and one thing only.
        self.assertEqual([call[0] for call in control.method_calls], ["cancel_interruption"])

    def test_a_refusal_and_a_failure_change_nothing_and_announce_nothing(self):
        refused = MagicMock()
        refused.cancel_interruption.side_effect = type("Refusal", (Exception,), {"code": "no_such_interruption"})()
        announce = MagicMock()
        self.assertEqual(notifier.activate(notify.cancel_uri(INTERRUPTION), control=refused, announce=announce),
                         "refused")
        broken = MagicMock()
        broken.cancel_interruption.side_effect = RuntimeError("busy")
        self.assertEqual(notifier.activate(notify.cancel_uri(INTERRUPTION), control=broken, announce=announce),
                         "failed")
        announce.assert_not_called()

    def test_a_malformed_uri_never_reaches_the_control_layer(self):
        control = MagicMock()
        for uri in ("codex-auto-resume:cancel?i=zz", "codex-auto-resume:resume?i=" + INTERRUPTION,
                    "https://example.test/cancel?i=" + INTERRUPTION, "", None, 7,
                    "codex-auto-resume:cancel?i=%s&i=%s" % (INTERRUPTION, "b" * 64)):
            with self.subTest(uri=repr(uri)[:40]):
                self.assertEqual(notifier.activate(uri, control=control, open_dashboard=MagicMock()), "ignored")
        control.assert_not_called()
        self.assertEqual(control.method_calls, [])

    def test_every_press_leaves_one_line_in_the_log_with_its_reason(self):
        """What the toast's buttons leave in the log (cli.cmd_activate), a card's buttons leave too - who
        cancelled which conversation, and why a cancel did not happen - so the log does not lose the
        record once most cancels come from the card. The reason is a code or an exception's type:
        never an exception's text."""
        secret = "a prompt's words"

        def control(result=None, error=None):
            made = MagicMock()
            made.cancel_interruption.return_value = result
            made.cancel_interruption.side_effect = error
            return made

        def refusal(code):
            return type("ControlError", (Exception,), {"code": code})(secret)

        def boom(page):
            raise OSError(secret)

        cancel, pending = notify.cancel_uri(INTERRUPTION), notify.open_uri("pending")
        cases = (
            ("opened", pending, {"open_dashboard": lambda page: True}, "dashboard opened from a notification card"),
            ("not_installed", pending, {"open_dashboard": lambda page: False}, "Dashboard is not installed here"),
            ("failed", pending, {"open_dashboard": boom}, "(OSError)"),
            ("cancelled", cancel, {"control": control({"thread_id": THREAD, "changed": True})},
             "thread %s: cancelled from a notification card" % THREAD),
            ("cancelled", cancel, {"control": control({"thread_id": THREAD, "changed": False})},
             "thread %s: " % THREAD),
            ("refused", cancel, {"control": control(error=refusal("no_such_interruption"))}, "(no_such_interruption)"),
            ("refused", cancel, {"control": control(error=refusal("state_busy"))}, "(state_busy)"),
            ("failed", cancel, {"control": control(error=RuntimeError(secret))}, "(RuntimeError)"),
            ("ignored", "codex-auto-resume:cancel?i=zz", {"control": control()}, "ignored"),
        )
        for outcome, uri, handlers, words in cases:
            with self.subTest(outcome=outcome, words=words):
                lines = []
                self.assertEqual(notifier.activate(uri, log=lines.append, **handlers), outcome)
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("notification card", lines[0])
                self.assertIn(words, lines[0])
                self.assertNotIn(secret, lines[0])
        # A cancel that changed nothing does not say it cancelled.
        lines = []
        notifier.activate(cancel, control=control({"thread_id": THREAD, "changed": False}), log=lines.append)
        self.assertNotIn("cancelled from", lines[0])

    def test_a_log_that_breaks_changes_nothing_a_press_does(self):
        def broken(line):
            raise OSError("disk full")
        control = MagicMock()
        control.cancel_interruption.return_value = {"thread_id": THREAD, "changed": True}
        announced = []
        self.assertEqual(notifier.activate(notify.cancel_uri(INTERRUPTION), control=control,
                                           announce=announced.append, log=broken), "cancelled")
        self.assertEqual([notice.kind for notice in announced], ["cancelled"])
        self.assertEqual(notifier.activate(notify.open_uri("pending"), open_dashboard=lambda page: True,
                                           log=broken), "opened")


# ============================================================================ motion
class MotionTests(unittest.TestCase):
    def test_the_entrance_rises_fades_grows_and_deepens_to_rest(self):
        start, end = notice_card.entrance(0), notice_card.entrance(notice_card.ENTRANCE_MS)
        self.assertEqual((start.alpha, start.offset, start.scale, start.depth),
                         (0.0, notice_card.RISE, notice_card.SCALE_FROM, 0.0))
        self.assertEqual(end, notice_card.SETTLED)
        previous = start
        for elapsed in range(4, notice_card.ENTRANCE_MS + 1, 4):
            frame = notice_card.entrance(elapsed)
            self.assertGreaterEqual(frame.alpha, previous.alpha)
            self.assertLessEqual(frame.offset, previous.offset)
            self.assertGreaterEqual(frame.scale, previous.scale)
            self.assertGreaterEqual(frame.depth, previous.depth)
            previous = frame
        self.assertEqual(notice_card.entrance(notice_card.ENTRANCE_MS * notice_card.ALPHA_SHARE).alpha, 1.0)
        # As tuned on a real screen: solid within the first half, and still rising softly after it.
        self.assertEqual((notice_card.SCALE_FROM, notice_card.RISE), (0.98, 20))
        self.assertLessEqual(notice_card.ALPHA_SHARE, 0.5)
        solid = notice_card.entrance(notice_card.ENTRANCE_MS * notice_card.ALPHA_SHARE)
        self.assertGreater(solid.offset, 0.1 * notice_card.RISE, "the rise goes on once the card is solid")

    def test_the_curve_is_the_brands_ease_out(self):
        for step in range(11):
            t = step / 10.0
            self.assertAlmostEqual(notice_card.ease_out(t), 1 - (1 - t) ** 3)
        if hasattr(brand, "ease"):                          # v0.6.5's transition curve, easeOutCubic
            for step in range(11):
                self.assertAlmostEqual(notice_card.ease_out(step / 10.0), brand.ease(step / 10.0), delta=0.02)

    def test_reduced_motion_appears_holds_and_disappears_without_a_frame_between(self):
        motion = notice_card.CardMotion(0, hold_ms=1000, reduced=True)
        self.assertEqual(motion.frame(0), notice_card.SETTLED)
        self.assertFalse(motion.moving(0))
        self.assertEqual(motion.frame(999).alpha, 1.0)
        self.assertEqual(motion.frame(1000).alpha, 0.0)
        self.assertTrue(motion.gone)
        self.assertEqual(notice_card.entrance(0, reduced=True), notice_card.SETTLED)
        self.assertEqual(notice_card.leaving(0, reduced=True), 0.0)
        still = notice_card.CardMotion(0, reduced=True, position=(0, 0))
        still.move_to(0, (0, -100))
        self.assertEqual(still.place(0), (0, -100), "no glide either")

    def test_a_card_lives_enter_hold_exit_gone(self):
        motion = notice_card.CardMotion(0, hold_ms=1000)
        self.assertEqual(motion.phase, "enter")
        self.assertTrue(motion.moving(10))
        self.assertEqual(motion.frame(notice_card.ENTRANCE_MS).alpha, 1.0)
        self.assertEqual(motion.phase, "hold")
        self.assertFalse(motion.moving(notice_card.ENTRANCE_MS + 1))
        self.assertAlmostEqual(motion.wait_ms(notice_card.ENTRANCE_MS + 100), 900)
        exit_at = notice_card.ENTRANCE_MS + 1000
        self.assertEqual(motion.frame(exit_at).alpha, 1.0)
        self.assertEqual(motion.phase, "exit")
        half = motion.frame(exit_at + notice_card.EXIT_MS / 2)
        self.assertTrue(0 < half.alpha < 1)
        self.assertEqual((half.offset, half.scale), (0.0, 1.0), "leaving does not move")
        motion.frame(exit_at + notice_card.EXIT_MS)
        self.assertTrue(motion.gone)

    def test_pointing_at_the_stack_holds_it_and_leaving_gives_it_a_little_more(self):
        motion = notice_card.CardMotion(0, hold_ms=1000)
        settled = notice_card.ENTRANCE_MS
        motion.frame(settled + 500)
        motion.pause(settled + 500, True)
        motion.frame(settled + 60_000)
        self.assertEqual(motion.phase, "hold", "held for as long as somebody points at it")
        motion.pause(settled + 60_000, False)
        self.assertGreaterEqual(motion.wait_ms(settled + 60_000), notice_card.HOVER_GRACE_MS)

    def test_a_pointer_brings_back_a_card_that_was_fading_on_its_own(self):
        motion = notice_card.CardMotion(0, hold_ms=0)
        fading_at = notice_card.ENTRANCE_MS + notice_card.EXIT_MS / 2
        fading = motion.frame(fading_at).alpha
        self.assertLess(fading, 1.0)
        motion.pause(fading_at, True)
        self.assertEqual(motion.phase, "return")
        self.assertAlmostEqual(motion.frame(fading_at).alpha, fading, places=5)
        self.assertEqual(motion.frame(fading_at + notice_card.EXIT_MS).alpha, 1.0)
        self.assertEqual(motion.phase, "hold")

    def test_a_retired_card_goes_for_good(self):
        motion = notice_card.CardMotion(0, hold_ms=5000)
        motion.frame(1000)
        motion.retire(1000)
        motion.pause(1010, True)
        self.assertEqual(motion.phase, "exit", "a pointer cannot keep a card that was replaced or clicked")
        motion.frame(1000 + notice_card.EXIT_MS)
        self.assertTrue(motion.gone)
        quick = notice_card.CardMotion(0, hold_ms=5000)
        quick.frame(1000)
        quick.retire(1000, quick=True)
        quick.frame(1000 + notice_card.SWAP_MS)
        self.assertTrue(quick.gone)

    def test_a_delayed_entrance_stays_invisible_until_its_time(self):
        motion = notice_card.CardMotion(0)
        motion.delay(100)
        self.assertEqual(motion.frame(50).alpha, 0.0)
        self.assertTrue(motion.moving(50))
        self.assertGreater(motion.frame(150).alpha, 0.0)

    def test_a_card_glides_to_its_new_place_and_can_wait_before_it_does(self):
        motion = notice_card.CardMotion(0)
        motion.move_to(0, (100, 500))
        self.assertEqual(motion.place(0), (100, 500), "a first place is taken at once")
        motion.move_to(1000, (100, 300), delay=100)
        self.assertEqual(motion.place(1050), (100, 500))
        middle = motion.place(1100 + notice_card.SLIDE_MS / 2)
        self.assertTrue(300 < middle[1] < 500)
        self.assertEqual(motion.place(1100 + notice_card.SLIDE_MS), (100, 300))

    def test_the_rise_comes_out_of_the_taskbar(self):
        self.assertEqual(notice_card.rise_vector("bottom"), (0, 1))
        self.assertEqual(notice_card.rise_vector("top"), (0, -1))
        self.assertEqual(notice_card.rise_vector("left"), (-1, 0))
        self.assertEqual(notice_card.rise_vector("right"), (1, 0))


class StackTests(unittest.TestCase):
    MONITOR = (0, 0, 1920, 1080)
    WORKS = {"bottom": (0, 0, 1920, 1032), "top": (0, 48, 1920, 1080),
             "left": (48, 0, 1920, 1080), "right": (0, 0, 1872, 1080)}
    CORNERS = {"bottom": (1918, 1032, 1919, 1080), "top": (1918, 0, 1919, 48),
               "left": (0, 1078, 48, 1079), "right": (1872, 1078, 1920, 1079)}

    def positions(self, edge, scale, anchor="corner", count=3, offset=(0, 0)):
        work = tuple(value * scale + offset[index % 2] for index, value in enumerate(self.WORKS[edge]))
        monitor = tuple(value * scale + offset[index % 2] for index, value in enumerate(self.MONITOR))
        icon = None
        if anchor == "corner":
            icon = tuple(value * scale + offset[index % 2] for index, value in enumerate(self.CORNERS[edge]))
        sizes = [(int(336 * scale), int(h * scale)) for h in (190, 150, 170)][:count]
        found, got_edge = notice_card.stack_positions(sizes, work, monitor, icon, gap=int(12 * scale),
                                                      spacing=int(12 * scale))
        return found, got_edge, sizes, work

    def test_every_edge_and_scale_keeps_the_stack_inside_the_work_area_newest_in_the_corner(self):
        for edge, scale, anchor, offset in itertools.product(("bottom", "top", "left", "right"), (1.0, 1.5, 2.0),
                                                             ("corner", None), ((0, 0), (-2560, 0))):
            if anchor is None and edge != "bottom":
                continue                            # no anchor: the work area's inset says the edge
            with self.subTest(edge=edge, scale=scale, anchor=anchor, offset=offset):
                found, got_edge, sizes, work = self.positions(edge, scale, anchor, offset=offset)
                self.assertEqual(got_edge, edge)
                for (x, y), (w, h) in zip(found, sizes):
                    self.assertGreaterEqual(x, work[0])
                    self.assertGreaterEqual(y, work[1])
                    self.assertLessEqual(x + w, work[2])
                    self.assertLessEqual(y + h, work[3])
                rects = [(x, y, x + w, y + h) for (x, y), (w, h) in zip(found, sizes)]
                for one, two in itertools.combinations(rects, 2):
                    self.assertTrue(one[3] <= two[1] or two[3] <= one[1], "cards never overlap")
                first = rects[0]
                if edge == "top":
                    self.assertLess(first[1], rects[1][1], "the newest nearest the taskbar")
                else:
                    self.assertGreater(first[1], rects[1][1], "the newest nearest the corner, older above")

    def test_the_newest_card_is_where_the_popup_would_open(self):
        found, edge, sizes, work = self.positions("bottom", 1.0)
        x, y, _ = tray_popup.place(sizes[0], work, self.MONITOR, self.CORNERS["bottom"], None, gap=12)
        self.assertEqual(found[0], (x, y))

    def test_a_single_card_and_no_card(self):
        found, _, _, _ = self.positions("bottom", 1.0, count=1)
        self.assertEqual(len(found), 1)
        self.assertEqual(notice_card.stack_positions([], self.WORKS["bottom"], self.MONITOR, None, gap=12,
                                                     spacing=12)[0], [])

    def assert_apart_and_inside(self, found, sizes, work, gap):
        """The newest card is `place()`'s answer; every older one stands wholly inside the work
        area, and no two cards share a pixel row."""
        rects = [(x, y, x + w, y + h) for (x, y), (w, h) in zip(found, sizes)]
        for rect in rects[1:]:
            self.assertGreaterEqual(rect[1], work[1] + gap)
            self.assertLessEqual(rect[3], work[3] - gap)
            self.assertGreaterEqual(rect[0], work[0] + gap)
            self.assertLessEqual(rect[2], work[2] - gap)
        for one, two in itertools.combinations(rects, 2):
            self.assertTrue(one[3] <= two[1] or two[3] <= one[1], "cards never overlap: %r %r" % (one, two))

    def test_a_short_work_area_holds_only_the_cards_that_fit(self):
        """Three interruption cards on a 1920x1080 laptop at 150% (work area 1008 px) in French:
        the renderer measured them 256 dip tall. Two fit; the oldest is not squeezed in on top of
        the middle one, where the newer card would cover its buttons."""
        cases = (
            # work area, scale, card height in dip (fr 256, en 216), cards that fit:
            # n cards need n*h + (n-1)*spacing <= work height - 2*gap
            ((0, 0, 1920, 1008), 1.5, 256, 2),
            ((0, 0, 1920, 1008), 1.5, 216, 2),
            ((0, 0, 2560, 1392), 1.5, 216, 3),
            ((0, 0, 1366, 728), 1.0, 256, 2),
            ((0, 0, 1366, 728), 1.0, 216, 3),
            ((0, 0, 1280, 680), 1.25, 256, 1),
            ((0, 0, 1024, 400), 1.0, 256, 1),
        )
        for work, scale, dip, fits in cases:
            monitor = (work[0], work[1], work[2], work[3] + int(48 * scale))
            icon = (work[2] - 40, work[3] + 4, work[2] - 20, monitor[3] - 4)
            sizes = [(int(round(336 * scale)), int(round(dip * scale)))] * 3
            gap = spacing = int(round(12 * scale))
            with self.subTest(work=work, scale=scale, dip=dip):
                found, edge = notice_card.stack_positions(sizes, work, monitor, icon, gap=gap, spacing=spacing)
                self.assertEqual(edge, "bottom")
                self.assertEqual(len(found), fits)
                self.assertEqual(found[0], tray_popup.place(sizes[0], work, monitor, icon, None, gap=gap)[:2])
                self.assert_apart_and_inside(found, sizes, work, gap)

    def test_no_work_area_and_no_edge_ever_gets_overlapping_cards(self):
        for edge, height, dip in itertools.product(("bottom", "top", "left", "right"), range(260, 1400, 37),
                                                   (150, 216, 256, 330)):
            monitor = (0, 0, 1600, height + 48)
            work = {"bottom": (0, 0, 1600, height), "top": (0, 48, 1600, height + 48),
                    "left": (48, 0, 1600, height + 48), "right": (0, 0, 1552, height + 48)}[edge]
            corner = {"bottom": (1590, height, 1591, height + 48), "top": (1590, 0, 1591, 48),
                      "left": (0, height + 40, 48, height + 41), "right": (1552, height + 40, 1600, height + 41)}[edge]
            sizes = [(336, dip), (336, dip - 20), (336, dip + 10)]
            with self.subTest(edge=edge, height=height, dip=dip):
                found, _ = notice_card.stack_positions(sizes, work, monitor, corner, gap=12, spacing=12)
                self.assertGreaterEqual(len(found), 1, "the newest card always has a place")
                self.assert_apart_and_inside(found, sizes, work, 12)
                if len(found) < len(sizes):
                    # It stopped because the next one would not fit, not for any other reason.
                    _x, y = found[-1]
                    upward = notice_card.stack_direction(tray_popup.taskbar_edge(work, monitor, corner), found[0][1],
                                                         sizes[0][1], work) < 0
                    need = sizes[len(found)][1] + 12
                    self.assertTrue(y - need < work[1] + 12 if upward
                                    else y + sizes[len(found) - 1][1] + need > work[3] - 12)

    def test_the_stack_grows_away_from_the_corner(self):
        self.assertEqual(notice_card.stack_direction("bottom", 900, 100, (0, 0, 1920, 1032)), -1)
        self.assertEqual(notice_card.stack_direction("top", 60, 100, (0, 48, 1920, 1080)), 1)
        self.assertEqual(notice_card.stack_direction("left", 900, 100, (48, 0, 1920, 1080)), -1)
        self.assertEqual(notice_card.stack_direction("right", 30, 100, (0, 0, 1872, 1080)), 1)


# ============================================================================ layout
def fake_measure(scale):
    def measure(role, text, width, wrap):
        size = tray_popup.ROLES[role][0] * scale
        advance = size * 0.55
        text = text or " "
        if not wrap:
            return int(len(text) * advance), int(size * 1.35)
        per_line = max(1, int(width // advance))
        lines = 0
        for paragraph in text.split("\n"):
            lines += max(1, -(-len(paragraph) // per_line))
        return int(min(width, len(text) * advance)), int(lines * size * 1.35)
    return measure


class LayoutTests(unittest.TestCase):
    LONG = {"de": "Überarbeitung der Wiederholungslogik für unterbrochene Unterhaltungen im Hintergrunddienst",
            "fr": "Réécriture complète de la logique de reprise des conversations interrompues par une limite"}

    def notices(self, locale):
        name = self.LONG.get(locale, "Refactor the retry ladder")
        with in_locale(locale):
            for event, detail, _identity in EVENTS:
                yield build(event, detail, dict(FULL, name=name))

    def check(self, plan, scale):
        width, height = plan["size"]
        self.assertEqual(width, int(round(notice_card.CARD_WIDTH * scale)))
        self.assertEqual(plan["card"], (0, 0, width, height))
        pad = int(round(brand.SPACING["l"] * scale))
        for item in plan["items"]:
            rect = item.get("rect")
            if rect is None or item["kind"] == "card":
                continue
            self.assertGreaterEqual(rect[0], pad - 1, item)
            self.assertLessEqual(rect[2], width - pad + 1, item)
            self.assertGreaterEqual(rect[1], pad - 1, item)
            self.assertLessEqual(rect[3], height - pad + 1, item)
        buttons = [item["rect"] for item in plan["items"] if item["kind"] == "button"]
        for one, two in itertools.combinations(buttons, 2):
            self.assertTrue(one[2] <= two[0] or two[2] <= one[0] or one[3] <= two[1] or two[3] <= one[1])
        self.assertEqual([rect for _, rect in plan["targets"]], buttons)
        kinds = [item["kind"] for item in plan["items"]]
        self.assertEqual(kinds[0], "card")
        self.assertEqual(kinds.count("halo"), 1)
        self.assertEqual(kinds.count("panel"), 1)

    def test_every_notice_fits_in_every_language_at_every_scale(self):
        for locale in l10n.LOCALES:
            for notice in self.notices(locale):
                for scale in (1.0, 1.5, 2.0):
                    with self.subTest(locale=locale, kind=notice.kind, scale=scale):
                        vm = notice_card.view(notice)
                        self.check(notice_card.layout(vm, scale, fake_measure(scale)), scale)

    def test_the_card_is_the_popups_card(self):
        vm = notice_card.view(build("interruption", EVENTS[0][1]))
        plan = notice_card.layout(vm, 1.0, fake_measure(1.0))
        self.assertEqual(notice_card.CARD_WIDTH, tray_popup.WIDTH - 2 * brand.SPACING["m"])
        self.assertEqual(plan["items"][0]["radius"], brand.RADII["card"])
        halo = next(item for item in plan["items"] if item["kind"] == "halo")
        self.assertEqual(halo["state"], "waiting")
        self.assertEqual(halo["radius"], brand.glow_extent(brand.STATUS_DOT["popup"]))
        chips = [item for item in plan["items"] if item["kind"] == "chip"]
        self.assertEqual([chip["tone"] for chip in chips], ["waiting"])

    @unittest.skipUnless(os.name == "nt", "the popup's renderer measures with GDI")
    def test_with_the_real_fonts_nothing_leaves_the_card(self):
        renderer = tray_popup.Renderer()
        try:
            for locale in l10n.LOCALES:
                for scale in (1.0, 2.0):
                    renderer.use(locale, scale)
                    for notice in self.notices(locale):
                        with self.subTest(locale=locale, kind=notice.kind, scale=scale):
                            self.check(notice_card.layout(notice_card.view(notice), scale, renderer.measure), scale)
        finally:
            renderer.close()


# ============================================================================ materials
class ShadowTests(unittest.TestCase):
    def test_over_the_wallpaper_a_shadow_only_darkens(self):
        for theme in brand.THEMES:
            shadows = notice_card.float_shadows(theme)
            with self.subTest(theme=theme):
                self.assertTrue(shadows)
                for shadow in shadows:
                    self.assertLessEqual(brand.luminance(shadow.colour), notice_card.DARK_ENOUGH)
                    self.assertIn(shadow.colour, set(brand.LIGHT.values()) | set(brand.DARK.values()),
                                  "a brand token's colour")
                    self.assertTrue(0 < shadow.alpha <= 1)

    def test_light_keeps_its_drop_and_loses_its_highlight(self):
        light = brand.shadows("card", "light")
        drops = [shadow for shadow in light if not shadow.inset and shadow.token == "shadow_dark"]
        floating = notice_card.float_shadows("light")
        self.assertEqual([(s.dx, s.dy, s.blur) for s in floating], [(s.dx, s.dy, s.blur) for s in drops])
        # As dark on a white ground as the recipe's own drop is.
        for shadow, drop in zip(floating, drops):
            recipe = 1 - drop.alpha * (1 - brand.luminance(brand.LIGHT[drop.token]))
            ours = 1 - shadow.alpha * (1 - brand.luminance(shadow.colour))
            self.assertAlmostEqual(ours, recipe, places=3)

    def test_dark_keeps_its_recipe(self):
        dark = [(s.dx, s.dy, s.blur, brand.DARK[s.token], s.alpha) for s in brand.shadows("card", "dark")
                if not s.inset]
        self.assertEqual([tuple(s) for s in notice_card.float_shadows("dark")], dark)

    def test_the_shadow_deepens_as_the_card_settles(self):
        shadows = notice_card.float_shadows("light")
        previous = None
        for level in range(notice_card.DEPTH_LEVELS):
            now = notice_card.shadow_at(shadows, level / (notice_card.DEPTH_LEVELS - 1))
            if previous is not None:
                for before, after in zip(previous, now):
                    self.assertGreaterEqual(after.alpha, before.alpha)
                    self.assertGreaterEqual(after.blur, before.blur)
            previous = now
        self.assertEqual(notice_card.shadow_at(shadows, 1.0), shadows)
        self.assertEqual({notice_card.depth_level(d / 20.0) for d in range(21)}, set(range(notice_card.DEPTH_LEVELS)))

    def test_the_margin_holds_the_whole_shadow(self):
        for theme in brand.THEMES:
            shadows = notice_card.float_shadows(theme)
            for scale in (1.0, 2.0):
                margin = notice_card.shadow_margin(shadows, scale)
                for shadow in shadows:
                    self.assertGreaterEqual(margin, (max(abs(shadow.dx), abs(shadow.dy)) + 1.5 * shadow.blur) * scale)

    def test_the_cards_corners_are_cut_and_its_pixels_premultiplied(self):
        width, height, radius = 60, 40, 12.0
        pixels = bytes([200, 150, 100, 0]) * (width * height)
        out = notice_card.premultiply(pixels, width, height, radius)
        self.assertEqual(out[3], 0, "the very corner is not the card")
        self.assertEqual(out[((height // 2) * width + width // 2) * 4 + 3], 255)
        for index in range(0, len(out), 4):
            alpha = out[index + 3]
            self.assertTrue(all(out[index + channel] <= alpha for channel in range(3)), index)
        # Symmetric: the four corners are one square turned round.
        corner = lambda x, y: out[(y * width + x) * 4 + 3]
        for x, y in ((0, 3), (3, 0), (2, 2), (5, 1)):
            self.assertEqual(corner(x, y), corner(width - 1 - x, y))
            self.assertEqual(corner(x, y), corner(x, height - 1 - y))


# ============================================================================ safety
class SafetyTests(unittest.TestCase):
    """The envelope of the card's two modules (B-D11), modelled on the popup's."""

    CARD = ("notice_card.py", "notice_window.py")
    ALLOWED = {"brand", "l10n", "machine", "reasons", "tray", "tray_popup", "notice_card", "notice_presence"}
    STDLIB = {"__future__", "collections", "ctypes", "ctypes.wintypes", "math", "os", "threading", "time"}

    def tree(self, name):
        return ast.parse((SRC / name).read_text(encoding="utf-8"))

    def imports(self, name):
        package, stdlib = set(), set()
        for node in ast.walk(self.tree(name)):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    package.update([node.module] if node.module else [alias.name for alias in node.names])
                else:
                    stdlib.add(node.module)
            elif isinstance(node, ast.Import):
                stdlib.update(alias.name for alias in node.names)
        return package, stdlib

    def test_the_card_imports_nothing_that_can_act(self):
        for name in self.CARD:
            package, stdlib = self.imports(name)
            with self.subTest(name):
                self.assertLessEqual(package, self.ALLOWED)
                for forbidden in ("engine", "windows", "store", "source", "app", "continuation", "notify",
                                  "notifier", "control", "controlcli", "mcpserver", "cli", "startup"):
                    self.assertNotIn(forbidden, package)
                self.assertLessEqual(stdlib, self.STDLIB)

    def test_no_name_in_the_card_sends_submits_or_queues(self):
        for module in self.CARD:
            names = set()
            for node in ast.walk(self.tree(module)):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.alias):
                    names.add(node.asname or node.name)
            with self.subTest(module):
                self.assertEqual(sorted(name for name in names
                                        if re.search(r"send|submit|queue|dispatch|backend|engine", name, re.I)), [])

    def test_the_card_asks_the_control_layer_for_nothing(self):
        for module in self.CARD:
            for node in ast.walk(self.tree(module)):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    self.assertNotEqual(node.value.id, "control", module)

    def test_nothing_here_drives_another_window_or_opens_a_connection(self):
        forbidden = re.compile(r"\bSendInput\b|\bkeybd_event\b|\bmouse_event\b|\bSetCursorPos\b|"
                               r"\bPrintWindow\b|\bBitBlt\b|\bFindWindow\w*\b|\bsubprocess\b|\bsocket\b|"
                               r"\burllib\b|\bAccessibleObjectFromWindow\b|\bUIAutomation\w*\b|"
                               r"\bSetForegroundWindow\b|\bSetFocus\b|\bSetActiveWindow\b")
        for name in self.CARD + ("notifier.py", "notice_presence.py"):
            with self.subTest(name):
                self.assertEqual(forbidden.findall((SRC / name).read_text(encoding="utf-8")), [])

    def test_every_colour_in_the_card_is_a_brand_token(self):
        for name in self.CARD:
            with self.subTest(name):
                self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", (SRC / name).read_text(encoding="utf-8")), [])

    def test_the_probes_only_read(self):
        package, stdlib = self.imports("notice_presence.py")
        self.assertEqual(package, set())
        self.assertLessEqual(stdlib, {"__future__", "ctypes", "os"})
        text = (SRC / "notice_presence.py").read_text(encoding="utf-8")
        for writer in ("RegSetValue", "RegCreateKey", "SPI_SET", "SystemParametersInfoW(SPI_SET", "WriteFile"):
            self.assertNotIn(writer, text)

    def test_the_notifier_draws_nothing(self):
        package, _ = self.imports("notifier.py")
        self.assertLessEqual(package, {"l10n", "messages", "notice_presence", "notify", "reasons"})

    def test_no_new_module_raises_powershell_itself(self):
        for name in self.CARD + ("notifier.py", "notice_presence.py"):
            self.assertNotIn("pwsh", (SRC / name).read_text(encoding="utf-8"), name)


class SettingTests(unittest.TestCase):
    def test_a_model_cannot_turn_the_card_off(self):
        from codex_auto_resume import mcpserver
        self.assertNotIn(notifier.CARD_SETTING, mcpserver.settings_schema()["properties"])
        self.assertNotIn(notifier.CARD_SETTING, mcpserver.PANEL_APPEARANCE)
        # Nor once the switch is offered: it is offered in "windows", which Codex never gets.
        with patch.object(settings, "NOT_YET_OFFERED", frozenset()):
            entry = next(entry for entry in settings.describe() if entry["name"] == notifier.CARD_SETTING)
            self.assertEqual(entry["group"], "windows")
            self.assertNotIn(entry["group"], mcpserver.USER_GROUPS)
            self.assertNotIn(notifier.CARD_SETTING, mcpserver.settings_schema()["properties"])

    def test_the_switch_is_offered_exactly_when_something_draws_the_card(self):
        """A switch that changes nothing must not be on the Dashboard. The card is drawn once the
        watcher hands notices to the notifier (app.py) and the icon's thread hosts the stack
        (tray.py) - both, or the card never shows. Until then `notification_card` exists, with
        its default, but no surface offers it; wiring the card fails this test until the name
        leaves settings.NOT_YET_OFFERED, and taking the wiring out fails it the other way."""
        app_source = (SRC / "app.py").read_text(encoding="utf-8")
        tray_source = (SRC / "tray.py").read_text(encoding="utf-8")
        wired = "notifier.deliver(" in app_source and "notice_window.CardStack(" in tray_source
        offered = [entry for entry in settings.describe() if entry["name"] == notifier.CARD_SETTING]
        self.assertEqual(bool(offered), wired)
        self.assertEqual(notifier.CARD_SETTING not in settings.NOT_YET_OFFERED, wired)
        # Either way the value is there to be read, on by default, and only ever a boolean.
        self.assertIs(settings.defaults()[notifier.CARD_SETTING], True)
        self.assertEqual(settings.validate_update({notifier.CARD_SETTING: False}), {notifier.CARD_SETTING: False})


try:
    import test_mcp
except ImportError:                                   # pragma: no cover - run from another directory
    test_mcp = None


if test_mcp is not None:
    class McpRefusalTests(test_mcp.McpTestCase):
        def test_update_settings_refuses_the_card_even_if_the_schema_is_ignored(self):
            response = self.call("update_settings", {notifier.CARD_SETTING: False})
            self.assertIs(response["result"]["isError"], True)
            self.assertIs(self.control.get_settings()[notifier.CARD_SETTING], True)


# ============================================================================ Windows
@unittest.skipUnless(os.name == "nt", "the card is a Windows window")
class WindowsTests(unittest.TestCase):
    # Far outside any monitor, so no test ever puts a card where somebody can see it.
    WHERE = {"work": (-24000, -24000, -22000, -22800), "monitor": (-24000, -24000, -22000, -22752),
             "anchor": None, "dpi": 96}
    LIGHT = {"theme": "light", "contrast": False, "reduced": False}

    @classmethod
    def setUpClass(cls):
        from codex_auto_resume import notice_window
        cls.window = notice_window

    def setUp(self):
        self.now = 0.0
        tray_popup._gdiplus_acquire()
        self.addCleanup(tray_popup._gdiplus_release)

    def stack(self, **kwargs):
        options = dict(clock=lambda: self.now, locate=lambda: dict(self.WHERE),
                       appearance=lambda: dict(self.LIGHT))
        options.update(kwargs)
        return self.window.CardStack(**options)

    def ending(self, **kwargs):
        """A stack whose notices' endings are written down as they happen, in order."""
        outcomes = []
        stack = self.stack(on_complete=lambda notice, shown: outcomes.append((notice, shown)),
                           worker=lambda target, *args: target(*args), **kwargs).create()
        self.addCleanup(stack.destroy)
        return stack, outcomes

    def recording_user32(self):
        """user32 as notice_window reaches it, with every call that can show, raise or activate a
        window written down. Only ShowWindow(SW_SHOWNOACTIVATE) and SetWindowPos with
        SWP_NOACTIVATE are let through; anything else is recorded and not made at all."""
        window, real = self.window, self.window._dll("user32")
        calls = []
        watched = ("ShowWindow", "SetWindowPos", "SetForegroundWindow", "SetActiveWindow", "SetFocus",
                   "BringWindowToTop", "SwitchToThisWindow", "AnimateWindow", "SetWindowLongPtrW",
                   "SetWindowLongW")

        class User32:
            def __getattr__(self, name):
                function = getattr(real, name)
                if name not in watched:
                    return function

                def record(*args):
                    calls.append((name, args))
                    if name == "ShowWindow" and args[1] == 4:                     # SW_SHOWNOACTIVATE
                        return function(*args)
                    if name == "SetWindowPos" and args[-1] & 0x0010:              # SWP_NOACTIVATE
                        return function(*args)
                    return 0
                return record

        proxy, original = User32(), window._dll
        patcher = patch.object(window, "_dll", side_effect=lambda name: proxy if name == "user32" else original(name))
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def offscreen(self, notice, drawn=None, scale=1.0):
        stack = self.window.CardStack()
        where = dict(self.WHERE, dpi=int(96 * scale))
        card = self.window.Card(stack, notice, now_ms=0, where=where, drawn=drawn or self.LIGHT, windows=False)
        self.addCleanup(card.close)
        stack.admit(card, 0, where)
        return card

    def pump(self, seconds=0.05):
        import ctypes
        from codex_auto_resume import tray
        user32 = ctypes.WinDLL("user32")
        user32.PeekMessageW.argtypes = [ctypes.POINTER(tray.MSG), ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_uint, ctypes.c_uint]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(tray.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(tray.MSG)]
        message = tray.MSG()
        deadline = time.monotonic() + seconds
        while True:
            while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            if time.monotonic() >= deadline:
                return
            time.sleep(0.005)

    @staticmethod
    def pixel(layer, x, y):
        data = layer.pixels()
        index = (y * layer.width + x) * 4
        return tuple(data[index:index + 4])                  # B, G, R, A premultiplied

    def test_the_card_is_opaque_inside_its_rounded_corners_and_its_shadow_lies_outside(self):
        card = self.offscreen(build("interruption", EVENTS[0][1]))
        card.paint(10_000)
        body, shadow = card.body, card.shadow
        self.assertEqual(self.pixel(body, 0, 0)[3], 0)
        self.assertEqual(self.pixel(body, body.width // 2, body.height // 2)[3], 255)
        self.assertEqual(self.pixel(body, body.width // 2, 0)[3], 255, "the straight edge is the card's")
        margin = card.margin
        below = self.pixel(shadow, margin + body.width // 2, margin + body.height + 4)
        self.assertGreater(below[3], 0, "the shadow falls below the card")
        self.assertEqual(self.pixel(shadow, margin + body.width // 2, margin + body.height // 2)[3], 0,
                         "and nothing is drawn under it")
        for value in below[:3]:
            self.assertLessEqual(value, below[3])

    def test_high_contrast_has_no_shadow_and_system_colours(self):
        card = self.offscreen(build("interruption", EVENTS[0][1]),
                              drawn={"theme": "light", "contrast": True, "reduced": True})
        self.assertEqual((card.shadows, card.margin), ((), 0))
        card.paint(0)
        self.assertEqual(card.motion.frame(0), notice_card.SETTLED)
        self.assertEqual(self.pixel(card.body, card.body.width // 2, 2)[3], 255)

    def test_a_failure_wears_the_danger_light(self):
        card = self.offscreen(build("result", {"state": "submission_failed"}))
        card.paint(10_000)
        halo = next(item for item in card.plan["items"] if item["kind"] == "halo")
        blue, green, red, alpha = self.pixel(card.body, int(halo["cx"]), int(halo["cy"]))
        self.assertEqual(alpha, 255)
        self.assertEqual((red, green, blue), brand.rgb(brand.LIGHT["danger"]))

    def test_the_cards_light_holds_still_with_no_glow_when_motion_is_reduced(self):
        """Under Reduce motion the card shows brand's still light whatever its state: the dot at its full colour
        and nothing round it, as every surface does when its light holds still - and it never asks to move."""
        for kind, payload, token in (("interruption", EVENTS[0][1], "active"),
                                     ("result", {"state": "submission_failed"}, "danger")):
            with self.subTest(kind):
                card = self.offscreen(build(kind, payload), drawn=dict(self.LIGHT, reduced=True))
                card.paint(10_000)
                self.assertFalse(card.breathe(10_000))
                halo = next(item for item in card.plan["items"] if item["kind"] == "halo")
                cx, cy = int(halo["cx"]), int(halo["cy"])
                blue, green, red, _ = self.pixel(card.body, cx, cy)
                self.assertEqual((red, green, blue), brand.rgb(brand.LIGHT[token]))
                ground = self.pixel(card.body, cx + 10, cy)
                for distance in (6, 7, 8):
                    self.assertEqual(self.pixel(card.body, cx + distance, cy), ground, distance)

    def test_the_cards_light_breathes_on_the_popups_table(self):
        """v0.6.7: the card's light is the popup's - one breath on brand.GLOW for a breathing state, drawn again
        at most every 80 ms; a problem pulses once and then holds lit; High Contrast never moves it."""
        # A continuation being sent, or delivered and running again: the two states that breathe. An
        # interruption waiting for its reset holds lit and still, on the card as in the popup.
        notices = [build(event, detail, identity) for event, detail, identity in EVENTS]
        breathing = [notice for notice in notices if notice is not None and notice.status in brand.GLOW_BREATHES]
        self.assertTrue(breathing, "some card must breathe")
        card = self.offscreen(breathing[0])
        state = card.vm["status"]
        self.assertIn(state, brand.GLOW_BREATHES)
        halo = next(item for item in card.plan["items"] if item["kind"] == "halo")
        cx, cy = int(halo["cx"]), int(halo["cy"])
        rest = self.pixel(card.body, cx, cy)
        low = brand.GLOW[state + "_ms"] // 2                    # the bottom of the breath
        self.assertTrue(card.breathe(low))
        card.paint(low)
        self.assertNotEqual(self.pixel(card.body, cx, cy), rest, "the dot dims at the bottom of the breath")
        self.assertTrue(card.breathe(low + 10))                 # still moving, not drawn again yet
        failed = self.offscreen(build("result", {"state": "submission_failed"}))
        self.assertIn(failed.vm["status"], brand.GLOW_PULSES)
        self.assertTrue(failed.breathe(100))
        self.assertFalse(failed.breathe(brand.GLOW["attention_ms"] + 1), "one pulse, then lit and still")
        contrast = self.offscreen(build("interruption", EVENTS[0][1]), drawn=dict(self.LIGHT, contrast=True))
        self.assertFalse(contrast.breathe(low))

    def test_every_scale_and_theme_draws(self):
        for theme, scale in itertools.product(brand.THEMES, (1.0, 1.5, 2.0)):
            with self.subTest(theme=theme, scale=scale):
                card = self.offscreen(build("interruption", EVENTS[3][1]),
                                      drawn={"theme": theme, "contrast": False, "reduced": False}, scale=scale)
                for elapsed in (0, 40, 120, notice_card.ENTRANCE_MS, 5000):
                    drawn = card.paint(elapsed)
                    self.assertEqual((card.body.width, card.body.height), card.size)
                self.assertEqual(drawn["frame"], notice_card.SETTLED)
                self.assertEqual(card.size[0], int(round(notice_card.CARD_WIDTH * scale)))

    def test_a_posted_notice_becomes_two_windows_that_never_take_the_focus(self):
        import ctypes
        user32 = ctypes.WinDLL("user32")
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindow.restype = ctypes.c_void_p
        user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        calls = self.recording_user32()
        inbox = notifier.Inbox()
        stack = self.stack(inbox=inbox).create()
        self.addCleanup(stack.destroy)
        self.assertTrue(inbox.attached)
        poster = threading.Thread(target=lambda: inbox.post(build("interruption", EVENTS[0][1])))
        poster.start()
        poster.join(10)
        self.pump(0.2)
        self.assertEqual(len(stack.cards), 1)
        card = stack.cards[0]
        self.assertTrue(card.body.shown and card.shadow.shown, "UpdateLayeredWindow took both layers")
        body, shadow = card.body.hwnd, card.shadow.hwnd
        for hwnd, transparent in ((body, False), (shadow, True)):
            styles = user32.GetWindowLongPtrW(hwnd, -20)             # GWL_EXSTYLE
            for flag in (self.window.WS_EX_NOACTIVATE, self.window.WS_EX_LAYERED, self.window.WS_EX_TOOLWINDOW,
                         self.window.WS_EX_TOPMOST):
                self.assertTrue(styles & flag, hex(flag))
            self.assertEqual(bool(styles & self.window.WS_EX_TRANSPARENT), transparent)
        self.assertEqual(user32.GetWindow(body, 4), shadow, "the card is owned by its shadow, so it stays above it")
        # How they were shown, which the styles alone do not say: the foreground lock would hide
        # a SW_SHOW from any test run from a terminal, so the calls themselves are the evidence.
        shows = [args for name, args in calls if name == "ShowWindow"]
        places = [args for name, args in calls if name == "SetWindowPos"]
        self.assertEqual(sorted(name for name, _ in calls if name not in ("ShowWindow", "SetWindowPos")), [],
                         "nothing asked to raise, focus or restyle a window")
        self.assertEqual([args[1] for args in shows], [4, 4], "each layer shown once, SW_SHOWNOACTIVATE")
        self.assertEqual({args[0] for args in shows}, {body, shadow})
        self.assertEqual(len(places), 2)
        for args in places:
            self.assertTrue(args[-1] & 0x0010, "SWP_NOACTIVATE")
            self.assertEqual(args[-1] & ~(0x0010 | 0x0002 | 0x0001), 0, "no other SetWindowPos behaviour")
        self.assertEqual(stack._handle(body, self.window.WM_MOUSEACTIVATE, 0, 0), self.window.MA_NOACTIVATE)
        # Its whole life, on the stack's clock.
        for self.now in range(0, int(notice_card.ENTRANCE_MS + stack.hold() + notice_card.EXIT_MS) + 50, 40):
            stack._tick()
        self.assertEqual(stack.cards, [])
        self.assertFalse(user32.IsWindow(body))
        self.assertFalse(user32.IsWindow(shadow))
        stack.destroy()
        self.assertFalse(inbox.attached)

    def test_three_at_most_and_one_card_per_conversation(self):
        stack = self.stack().create()
        self.addCleanup(stack.destroy)
        for index in range(5):
            self.now = index * 10.0
            stack.show(build("starting", {}, thread="%08d-0000-7000-8000-000000000000" % index))
        living = [card for card in stack.cards if card.motion.phase not in ("exit", "gone")]
        self.assertEqual(len(living), notice_card.MAX_CARDS)
        self.assertEqual([card.notice.key[:8] for card in living], ["00000004", "00000003", "00000002"])
        self.now = 100.0
        stack.show(build("result", {"state": "resumed"}, thread="%08d-0000-7000-8000-000000000000" % 3))
        living = [card for card in stack.cards if card.motion.phase not in ("exit", "gone")]
        self.assertEqual([card.notice.kind for card in living], ["starting", "resumed", "starting"],
                         "the newer notice took the older card's place")
        self.now = 100_000.0
        stack._tick()
        self.assertEqual(stack.cards, [])

    def test_a_button_hands_its_uri_over_and_the_card_goes(self):
        clicked = []
        done = threading.Event()
        stack = self.stack(on_action=lambda uri: (clicked.append(uri), done.set())).create()
        self.addCleanup(stack.destroy)
        card = stack.show(build("interruption", EVENTS[0][1]))
        target, rect = card.plan["targets"][1]
        point = ((rect[1] + rect[3]) // 2 << 16) | ((rect[0] + rect[2]) // 2)
        stack._handle(card.body.hwnd, self.window.WM_LBUTTONDOWN, 0, point)
        stack._handle(card.body.hwnd, self.window.WM_LBUTTONUP, 0, point)
        self.assertTrue(done.wait(5))
        self.assertEqual(clicked, [notify.open_uri("pending")])
        self.assertEqual(card.motion.phase, "exit")

    def test_pointing_at_one_card_holds_them_all_until_the_pointer_is_gone(self):
        stack = self.stack().create()
        self.addCleanup(stack.destroy)
        older = stack.show(build("starting", {}, thread="t1"))
        self.now = 10.0
        newer = stack.show(build("starting", {}, thread="t2"))
        self.now = 1000.0
        stack._tick()
        middle = ((newer.size[1] // 2) << 16) | 4                     # on the card, not on a button
        stack._handle(newer.body.hwnd, self.window.WM_MOUSEMOVE, 0, middle)
        self.assertTrue(older.motion.paused and newer.motion.paused)
        self.now = 60_000.0
        stack._tick()
        self.assertEqual(len(stack.cards), 2, "nothing leaves while somebody is looking")
        # Clicked away: it goes, and the pointer it was under can no longer hold the other one.
        stack._handle(newer.body.hwnd, self.window.WM_LBUTTONDOWN, 0, middle)
        stack._handle(newer.body.hwnd, self.window.WM_LBUTTONUP, 0, middle)
        self.now += notice_card.EXIT_MS + 1
        stack._tick()
        self.assertEqual(stack.cards, [older])
        self.assertFalse(older.motion.paused)
        self.now += stack.hold() + 50
        stack._tick()
        self.now += notice_card.EXIT_MS + 1
        stack._tick()
        self.assertEqual(stack.cards, [])

    def test_a_notice_that_cannot_be_drawn_goes_back_to_the_toast(self):
        returned = []
        done = threading.Event()
        stack = self.stack(on_complete=lambda notice, shown: (returned.append((notice, shown)), done.set()),
                           locate=MagicMock(side_effect=OSError("no screen"))).create()
        self.addCleanup(stack.destroy)
        notice = build("starting", {})
        self.assertIsNone(stack.show(notice))
        self.assertTrue(done.wait(5))
        self.assertEqual(returned, [(notice, False)])

    # ---- exactly once, by exactly one route, however a card ends (PLAN v2, 7.7)
    def test_the_history_copy_follows_only_once_the_card_has_been_seen_whole(self):
        stack, outcomes = self.ending()
        notice = build("interruption", EVENTS[0][1])
        card = stack.show(notice)
        self.assertIsNotNone(card)
        self.assertEqual(outcomes, [], "on screen but not yet visible: nothing is decided")
        self.now = notice_card.ENTRANCE_MS * notice_card.ALPHA_SHARE * 0.5
        stack._tick()
        self.assertEqual(outcomes, [], "half faded in is not seen")
        self.now = notice_card.ENTRANCE_MS
        stack._tick()
        self.assertEqual(outcomes, [(notice, True)], "seen at full strength: the silent copy, once")
        for self.now in range(int(notice_card.ENTRANCE_MS), 100_000, 500):
            stack._tick()
        self.assertEqual(stack.cards, [])
        self.assertEqual(outcomes, [(notice, True)])

    def test_reduced_motion_is_seen_with_its_first_frame(self):
        stack, outcomes = self.ending(appearance=lambda: dict(self.LIGHT, reduced=True))
        notice = build("starting", {})
        stack.show(notice)
        self.assertEqual(outcomes, [(notice, True)])

    def test_a_card_whose_frames_fail_before_it_was_seen_becomes_the_toast(self):
        """UpdateLayeredWindow saying no, or a frame raising, before the card was ever whole on
        screen: no silent copy was raised yet, so today's toast is - once - and the card goes."""
        for how in ("refused", "raised"):
            with self.subTest(how=how):
                stack, outcomes = self.ending()
                notice = build("interruption", EVENTS[0][1])
                if how == "refused":
                    breaking = patch.object(self.window._Layer, "push", return_value=False)
                else:
                    breaking = patch.object(self.window.Card, "paint", side_effect=OSError("GDI+"))
                with breaking:
                    stack.show(notice)
                    self.now = notice_card.ENTRANCE_MS
                    stack._tick()
                self.assertEqual(outcomes, [(notice, False)])
                self.assertEqual(stack.cards, [])
                self.assertEqual(stack.windows, {}, "both windows went with it")

    def test_a_card_that_breaks_after_it_was_seen_is_not_announced_again(self):
        stack, outcomes = self.ending()
        notice = build("interruption", EVENTS[0][1])
        stack.show(notice)
        self.now = notice_card.ENTRANCE_MS
        stack._tick()
        self.assertEqual(outcomes, [(notice, True)])
        with patch.object(self.window._Layer, "push", return_value=False):
            self.now = notice_card.ENTRANCE_MS + stack.hold() + notice_card.EXIT_MS / 2
            stack._tick()                                    # a fading frame fails
        self.assertEqual(stack.cards, [])
        self.assertEqual(outcomes, [(notice, True)], "seen and in the history: no second toast")

    def test_every_notice_the_stack_had_ends_once_when_it_goes_away(self):
        """Tray shutdown: a card already seen stays seen; a card still arriving, and a notice the
        inbox accepted but the stack never took, are raised as today's toast instead."""
        inbox = notifier.Inbox()
        stack, outcomes = self.ending(inbox=inbox)
        seen, arriving, waiting = (build("starting", {}, thread="t%d" % index) for index in range(3))
        stack.show(seen)
        self.now = 1_000.0                                   # whole on screen, holding
        stack._tick()
        self.assertEqual(outcomes, [(seen, True)])
        stack.show(arriving)
        self.assertTrue(inbox.post(waiting))                 # posted; the stack's message not pumped
        stack.destroy()
        self.assertEqual(sorted(((notice.key, shown) for notice, shown in outcomes)),
                         [("t0", True), ("t1", False), ("t2", False)])
        self.assertFalse(inbox.attached)
        stack.destroy()
        self.assertEqual(len(outcomes), 3, "and never twice")

    def test_a_card_replaced_or_clicked_before_it_was_whole_is_in_the_history(self):
        """Replaced by a newer notice about the same conversation (whose card now speaks for it),
        or clicked while it arrived (somebody saw it): its silent copy goes, no toast."""
        stack, outcomes = self.ending()
        first = build("starting", {}, thread="same")
        second = build("result", {"state": "resumed"}, thread="same")
        stack.show(first)
        self.now = 20.0
        stack.show(second)
        for self.now in range(20, 2000, 16):
            stack._tick()
        self.assertEqual([(notice.kind, shown) for notice, shown in outcomes],
                         [("starting", True), ("resumed", True)])
        clicked = build("starting", {}, thread="clicked")
        self.now = 3000.0
        card = stack.show(clicked)
        self.now = 3040.0
        stack._tick()
        middle = ((card.size[1] // 2) << 16) | 4
        stack._handle(card.body.hwnd, self.window.WM_LBUTTONDOWN, 0, middle)
        stack._handle(card.body.hwnd, self.window.WM_LBUTTONUP, 0, middle)
        self.now = 4000.0
        stack._tick()
        self.assertEqual(outcomes[-1], (clicked, True))
        self.assertEqual(len(outcomes), 3)

    def test_a_short_screen_keeps_only_the_cards_that_fit(self):
        """Three interruptions at once on a screen with room for two: the oldest retires as the
        third arrives, rather than being squeezed in under the middle card's buttons."""
        where = dict(self.WHERE, work=(-24000, -24000, -22000, -23500), monitor=(-24000, -24000, -22000, -23452))
        stack, outcomes = self.ending(locate=lambda: dict(where))
        cards = []
        for index in range(3):
            self.now = index * 10.0
            cards.append(stack.show(build("interruption", EVENTS[index][1], thread="t%d" % index)))
        height = cards[0].size[1]
        fits = (500 - 2 * 12 + 12) // (height + 12)
        self.assertEqual(fits, 2, "the screen was chosen to hold two of these cards")
        living = [card for card in stack.cards if card.motion.phase not in ("exit", "gone")]
        self.assertEqual([card.notice.key for card in living], ["t2", "t1"])
        self.assertEqual(cards[0].motion.phase, "exit", "the oldest is on its way out")
        rects = [(x, y, x + card.size[0], y + card.size[1])
                 for card in living for x, y in [card.motion.position]]      # where each is going
        self.assertTrue(rects[0][1] >= rects[1][3] or rects[1][1] >= rects[0][3], rects)
        for rect in rects:
            self.assertGreaterEqual(rect[1], where["work"][1] + 12)
            self.assertLessEqual(rect[3], where["work"][3] - 12)
        # The oldest had not been seen whole when it had to make room: it reaches the person as
        # today's toast. The two that stayed were the cards' to show.
        for self.now in range(30, 1000, 16):
            stack._tick()
        # Which ends first depends only on how long a fade takes; each ends once, one way.
        self.assertEqual(sorted((notice.key, shown) for notice, shown in outcomes),
                         [("t0", False), ("t1", True), ("t2", True)])

    def test_cards_leave_nothing_behind(self):
        from codex_auto_resume import notice_window
        stack = self.stack().create()
        self.addCleanup(stack.destroy)
        warm = stack.show(build("starting", {}))
        self.now = 100_000.0
        stack._tick()
        del warm
        before = (tray_popup.gui_resources(), tray_popup.gdiplus_objects(), notice_window.gdiplus_objects())
        for round_ in range(25):
            self.now = round_ * 1_000_000.0
            for index in range(3):
                stack.show(build("interruption", EVENTS[index % 4][1], thread="t%d" % index))
            for step in range(0, 400, 40):
                self.now += step
                stack._tick()
            self.now += 1_000_000.0
            stack._tick()
            self.assertEqual(stack.cards, [])
        after = (tray_popup.gui_resources(), tray_popup.gdiplus_objects(), notice_window.gdiplus_objects())
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()

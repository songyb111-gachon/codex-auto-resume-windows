"""The popup's waiting-task menu offers what the Dashboard's Pending menu offers (v0.6.23; the owner, 2026-11-11:
"팝업에서 대기중인 거 우클릭 할 때 뜨는거랑 앱 내 대기에서 우클릭 할때 뜨는 기능 양이 같으면 편할 거 같아", and for how:
"대시보드 창 띄우기").

After Hold this project for me, after a line, as gui/DashboardActions.cs FillRowMenu has them: Message for this
conversation..., Add words for this time... (Change words for this time... when the task has some; offered while it
waits, as Postpone is) and, only when it has some, Remove words for this time. The two that write OPEN THE DASHBOARD on
Pending with that row and its own dialog - one dialog, none in the popup: the popup closes and asks the watcher's
opener (`on_dashboard(row=...)`, ui/tray/dashboard.py), which hands the request to a window that is open or starts one
with `--dialog=` (tests/test_gui_row_dialog.py holds the window's side). Remove takes the words away at once through the
control layer, as the Dashboard's item does - the same command with no words, and no question, as the Dashboard asks
none.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import types
import unittest
import unittest.mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.ui import popup, tray  # noqa: E402
from codex_auto_resume.ui.popup import model as popup_model  # noqa: E402
from codex_auto_resume.ui.popup import window as popup_window  # noqa: E402
from codex_auto_resume.ui.tray import dashboard  # noqa: E402
from codex_auto_resume.win import handover  # noqa: E402

import guiscan  # noqa: E402
from test_popup_row_menu_drawn import FakeDrawn, FakeUser32, KEY, THREAD, shown_popup  # noqa: E402

EN = l10n.catalog("en")
NOW = 1000.0
# A row of the shapes the product makes, for the opener, which checks them.
REAL_KEY = "ab" * 32
REAL_THREAD = "01234567-89ab-7cde-8f01-23456789abcd"


def row(**extra):
    return dict({"interruption_id": KEY, "thread_id": THREAD, "state": "waiting_reset", "code": "waiting_reset",
                 "category": "usage_limit", "eligible_at": 2000.0, "overlays": [], "thread_enabled": True,
                 "hold": None, "tier": None}, **extra)


def menu(**extra):
    return popup_model.row_menu(popup.task_item(row(**extra), EN, NOW), EN, "automatic")


def keys(entries):
    """Each top-level item by its catalog key (its text looked up in English), None for a line."""
    by_text = {}
    for key, text in EN.items():
        if key.startswith("menu.") or key == "action.continue":
            by_text.setdefault(text, key)
    return [None if entry is None else by_text.get(entry["text"], entry["text"]) for entry in entries]


def dashboard_order(worded):
    """FillRowMenu's top-level items, by key and in its order, for a row with words for this time or without."""
    body = guiscan.member_body("SettingsForm", "FillRowMenu")
    order = []
    for found in re.finditer(r'pendingMenu\.Items\.Add\(new ToolStripSeparator\(\)\)|S\("((?:menu|action)\.[a-z_]+)"', body):
        key = found.group(1)
        if key is None:
            order.append(None)
        elif key == "menu.unpostpone":
            continue                                              # inside Postpone's submenu
        elif key in ("menu.once_words_change", "menu.once_words_add"):
            if key == ("menu.once_words_change" if worded else "menu.once_words_add"):
                order.append(key)
        elif key == "menu.once_words_remove":
            if worded:
                order.append(key)
        else:
            order.append(key)
    return order


class OfferedTests(unittest.TestCase):
    def test_the_popup_offers_the_dashboards_items_in_its_order(self):
        """Fails with the change reverted: the popup's menu ends at Hold this project for me."""
        for worded in (False, True):
            with self.subTest(worded=worded):
                offered = keys(menu(once_words=worded))
                self.assertEqual(offered, dashboard_order(worded))
        self.assertEqual(keys(menu())[-3:], [None, "menu.conversation_message", "menu.once_words_add"])
        self.assertEqual(keys(menu(once_words=True))[-3:], ["menu.conversation_message", "menu.once_words_change",
                                                            "menu.once_words_remove"])

    def test_the_dashboards_rules_add_or_change_while_it_waits_remove_only_when_there_are_some(self):
        *_, message, add = menu()
        self.assertTrue(message["enabled"])
        self.assertTrue(add["enabled"], "a waiting task can be given words")
        *_, message, add = menu(state="submitted", code="submitted")
        self.assertTrue(message["enabled"], "Message for this conversation... is offered on every row, as Pending's")
        self.assertFalse(add["enabled"], "not while it is no longer waiting (CanAddOnceWords)")
        *_, message, add = menu(cancel_requested=True)
        self.assertFalse(add["enabled"], "nor once it is cancelled")
        *_, change, remove = menu(once_words=True)
        self.assertEqual((change["text"], remove["text"]), (EN["menu.once_words_change"], EN["menu.once_words_remove"]))
        self.assertTrue(remove["enabled"])
        self.assertNotIn("menu.once_words_remove", keys(menu(once_words=False)))
        self.assertNotIn("menu.once_words_remove", keys(menu(once_words="yes")), "only the listing's own true")

    def test_each_is_bound_to_the_rows_identities(self):
        *_, message, add = menu()
        self.assertEqual(message["action"], ("dashboard_row", "message", KEY, THREAD))
        self.assertEqual(add["action"], ("dashboard_row", "once_words", KEY, THREAD))
        *_, change, remove = menu(once_words=True)
        self.assertEqual(change["action"], ("dashboard_row", "once_words", KEY, THREAD))
        self.assertEqual(remove["action"], ("unsay", KEY, THREAD))

    def test_the_dialogs_are_the_ones_the_opener_and_the_window_take(self):
        self.assertEqual(popup_model.ROW_DIALOGS, dashboard.ROW_DIALOGS)
        self.assertIn('RowDialogs = { "message", "once_words" };', guiscan.type_body("SettingsForm", "gui/WindowReopen.cs"))


def dashboard_enabled(case, now=NOW):
    """What FillRowMenu enables for `case` while nothing is on its way (idle), by its rules (CanPostpone, CanUnpostpone,
    CanRelease, CanAddOnceWords, the tiers' `!terminal`), as EnablementTests pins their bodies - by top-level key, and
    Don't postpone's."""
    waiting = case.get("code") in ("waiting_reset", "waiting_usage", "waiting_thread", "scheduled", "failed_retryable")
    postpone = waiting and case.get("cancel_requested") is not True
    released = bool(case.get("hold")) and case.get("terminal") is not True and case.get("cancel_requested") is not True
    tiers = case.get("terminal") is not True
    enabled = {"menu.postpone": postpone, "action.continue": released, "menu.tier": tiers,
               "menu.project_always": tiers, "menu.project_never": tiers, "menu.conversation_message": True,
               "menu.once_words_change" if case.get("once_words") is True else "menu.once_words_add": postpone}
    if case.get("once_words") is True:
        enabled["menu.once_words_remove"] = True
    return enabled, postpone and (case.get("postponed_until") or 0) > now


# Rows as Pending lists them: one waiting for its reset and one already sent, each held, cancelled, ended, postponed or
# with words, alone and together.
WAITS = {"state": "waiting_reset", "code": "waiting_reset"}
SENT = {"state": "submitted", "code": "submitted"}
CASES = [dict(base, **flags) for base in (WAITS, SENT) for flags in (
    {}, {"hold": "person"}, {"hold": "person", "cancel_requested": True}, {"cancel_requested": True},
    {"hold": "person", "terminal": True}, {"postponed_until": NOW + 600}, {"postponed_until": NOW - 600},
    {"postponed_until": NOW + 600, "cancel_requested": True}, {"once_words": True},
    {"once_words": True, "cancel_requested": True})]


class EnablementTests(unittest.TestCase):
    """Not only the items and their order: which of them can be chosen, row by row, as the Dashboard's (the
    reachability audit's M3). Two differences are the popup's on purpose: an action on its way greys the Dashboard's
    whole menu (idle) where the popup holds that action alone (its own busy set), and a row that has ended is not
    offered a tier there while the popup's tiers do not look at it - so an ended row's tiers are not compared."""

    def test_each_item_is_enabled_by_the_dashboards_rules(self):
        """Fails with the popup's Let it continue reverted: a held row whose cancel is pending is offered it."""
        for case in CASES:
            with self.subTest(case=case):
                entries = menu(**case)
                offered = {key: entry["enabled"] for key, entry in zip(keys(entries), entries) if entry is not None}
                expected, unpostpone = dashboard_enabled(case)
                if case.get("terminal") is True:
                    for tier in ("menu.tier", "menu.project_always", "menu.project_never"):
                        expected.pop(tier)
                        offered.pop(tier)
                self.assertEqual(offered, expected)
                postponing = next(entry for entry in entries if entry and entry["text"] == EN["menu.postpone"])["items"]
                undo = next(entry for entry in postponing if entry and entry["text"] == EN["menu.unpostpone"])
                self.assertEqual(undo["enabled"], unpostpone, "Don't postpone, as CanUnpostpone")

    def test_a_held_row_whose_cancel_is_pending_is_not_let_go(self):
        def release(**extra):
            return next(entry for entry in menu(**extra) if entry and entry["text"] == EN["action.continue"])
        self.assertFalse(release(hold="person", cancel_requested=True)["enabled"])
        self.assertTrue(release(hold="person")["enabled"])

    def test_the_rules_compared_are_the_dashboards(self):
        """The rules dashboard_enabled mirrors, as the window writes them: a change there fails here first."""
        def code(name):
            return re.sub(r"\s+", " ", guiscan.member_body("SettingsForm", name))
        self.assertIn('bool waiting = code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" || '
                      'code == "scheduled" || code == "failed_retryable"; '
                      'return waiting && !Equals(Get(row, "cancel_requested"), true);', code("CanPostpone"))
        self.assertIn('if (string.IsNullOrEmpty(Str(row, "hold"))) return false; '
                      'return !Equals(Get(row, "terminal"), true) && !Equals(Get(row, "cancel_requested"), true);',
                      code("CanRelease"))
        self.assertIn('return CanPostpone(row, idle) && !IsDemo(row) && Number(row, "postponed_until") > now;',
                      code("CanUnpostpone"))
        self.assertIn("return CanPostpone(row, idle) && !IsDemo(row);", code("CanAddOnceWords"))
        fill = code("FillRowMenu")
        for rule in ("postpone.Enabled = CanPostpone(row, idle);", "release.Enabled = CanRelease(row, idle);",
                     'tiers.Enabled = idle && !Equals(Get(row, "terminal"), true);', "always.Enabled = tiers.Enabled;",
                     "never.Enabled = tiers.Enabled;", "message.Enabled = idle;",
                     "once.Enabled = CanAddOnceWords(row, idle);", "unsay.Enabled = idle;",
                     "unpostpone.Enabled = CanUnpostpone(row, idle, Now());"):
            with self.subTest(rule=rule):
                self.assertIn(rule, fill)


class RemoveTests(unittest.TestCase):
    def test_remove_is_the_dashboards_command_with_no_words_bound_to_the_row(self):
        calls = []
        control = types.SimpleNamespace(set_once_words=lambda *args: calls.append(args) or {"set": False})
        self.assertEqual(popup.perform(("unsay", KEY, THREAD), control), ("ok", {"set": False}))
        self.assertEqual(calls, [(KEY, THREAD, None)])
        self.assertEqual(popup.busy_key(("unsay", KEY, THREAD)), ("row", KEY))
        self.assertIn("set_once_words", popup.CONTROL_CALLS)
        body = guiscan.member_body("SettingsForm", "FillRowMenu")
        self.assertIn("delegate { SaveOnceWords(null, row, null); }", body, "the Dashboard's: no question asked")

    def test_a_row_that_changed_says_so_as_every_row_action_does(self):
        model = popup.PopupModel(EN)
        model.apply_outcome(("unsay", KEY, THREAD), ("refused", "no_such_interruption"), NOW)
        self.assertEqual(model.notice_key, "popup.stale")
        self.assertTrue(model.wants_read)

    def test_chosen_in_the_drawn_menu_it_runs_and_the_popup_stays(self):
        made = []
        shown = shown_popup(make_menu=lambda: made.append(FakeDrawn()) or made[-1], once_words=True)
        hidden = []
        shown.hide = lambda: hidden.append(True)
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: FakeUser32()):
            shown._context_menu((30 << 16) | 40)
        numbered, actions = popup.menu_numbered(shown.model.menu_for(KEY))
        command = next(number for number, action in actions.items() if action and action[0] == "unsay")
        made[0].opened[0]["on_choose"](command)
        self.assertEqual(shown.ran, [("unsay", KEY, THREAD)])
        self.assertEqual(hidden, [])


class OpensTheDashboardTests(unittest.TestCase):
    def test_a_writing_item_closes_the_popup_and_asks_for_the_dashboards_dialog(self):
        """Fails with the change reverted: there is no such item, and no request for the window."""
        for dialog in ("message", "once_words"):
            with self.subTest(dialog=dialog):
                made = []
                shown = shown_popup(make_menu=lambda: made.append(FakeDrawn()) or made[-1])
                hidden = []
                shown.hide = lambda: hidden.append(True)
                with unittest.mock.patch.object(popup_window, "_dll", lambda name: FakeUser32()):
                    shown._context_menu((30 << 16) | 40)
                _, actions = popup.menu_numbered(shown.model.menu_for(KEY))
                command = next(number for number, action in actions.items()
                               if action and action[:2] == ("dashboard_row", dialog))
                made[0].opened[0]["on_choose"](command)
                self.assertEqual(shown.ran, [("dashboard_row", dialog, KEY, THREAD)])
                self.assertEqual(hidden, [True], "the popup closes, as its Open Dashboard closes it")

    def test_the_action_hands_the_row_to_the_opener_and_nothing_to_the_control_layer(self):
        asked = []
        control = types.SimpleNamespace()                      # any call on it would fail
        outcome = popup.perform(("dashboard_row", "once_words", KEY, THREAD), control,
                                dashboard=lambda row=None: asked.append(row) or True)
        self.assertEqual(outcome, ("ok", {"opened": True}))
        self.assertEqual(asked, [("once_words", KEY, THREAD)])
        self.assertEqual(popup.perform(("dashboard_row", "settings", KEY, THREAD), control,
                                       dashboard=lambda row=None: self.fail("asked")), ("failed", "unknown_action"))
        model = popup.PopupModel(EN)
        model.apply_outcome(("dashboard_row", "message", KEY, THREAD), ("ok", {"opened": False}), NOW)
        self.assertIsNone(model.notice_key)
        self.assertIsNone(popup.busy_key(("dashboard_row", "message", KEY, THREAD)))

    def test_the_watcher_wires_the_popup_to_the_opener_with_its_row(self):
        source = (Path(_HERE).parent / "src/codex_auto_resume/runtime/app.py").read_text(encoding="utf-8")
        self.assertIn('on_dashboard=lambda row=None: tray.open_dashboard(home, "pending", row=row),', source)


class Started:
    def __init__(self):
        self.calls = []

    def __call__(self, arguments, **kwargs):
        self.calls.append(list(arguments))
        return types.SimpleNamespace(pid=0)


class OpenerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        (self.home / "CodexAutoResumeSettings.exe").write_bytes(b"MZ")      # a file to find; never run
        self.started = Started()
        patcher = unittest.mock.patch.object(dashboard.subprocess, "Popen", self.started)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_open_window_is_handed_the_row_on_a_second_line(self):
        asked = []
        with unittest.mock.patch.object(handover, "hand_over",
                                        lambda exe, page=None, row=None: asked.append((page, row)) or True):
            self.assertTrue(tray.open_dashboard(self.home, "pending", row=("once_words", REAL_KEY, REAL_THREAD)))
        self.assertEqual(asked, [("pending", "once_words:%s:%s" % (REAL_KEY, REAL_THREAD))])
        self.assertEqual(self.started.calls, [])
        self.assertEqual(handover.request_text("pending", "message:%s:%s" % (REAL_KEY, REAL_THREAD)),
                         "pending\nmessage:%s:%s" % (REAL_KEY, REAL_THREAD))
        self.assertEqual(handover.request_text("history"), "history")

    def test_with_no_window_one_is_started_on_pending_with_the_dialog(self):
        with unittest.mock.patch.object(handover, "hand_over", lambda exe, page=None, row=None: False):
            self.assertTrue(tray.open_dashboard(self.home, "pending", row=("message", REAL_KEY, REAL_THREAD)))
            self.assertTrue(tray.open_dashboard(self.home, row=("once_words", REAL_KEY, REAL_THREAD)))
        exe = str(self.home / "CodexAutoResumeSettings.exe")
        self.assertEqual(self.started.calls, [
            [exe, "--page=pending", "--dialog=message:%s:%s" % (REAL_KEY, REAL_THREAD)],
            [exe, "--page=pending", "--dialog=once_words:%s:%s" % (REAL_KEY, REAL_THREAD)]])

    def test_without_a_row_the_open_is_what_it_was(self):
        asked = []
        with unittest.mock.patch.object(handover, "hand_over", lambda exe, page=None: asked.append(page) or False):
            self.assertTrue(tray.open_dashboard(self.home, "pending"))
        self.assertEqual(asked, ["pending"])
        self.assertEqual(self.started.calls, [[str(self.home / "CodexAutoResumeSettings.exe"), "--page=pending"]])

    def test_a_malformed_row_is_refused_before_anything_is_asked_or_started(self):
        bad = [("settings", REAL_KEY, REAL_THREAD), ("message", REAL_KEY.upper(), REAL_THREAD),
               ("message", REAL_KEY[:-1], REAL_THREAD), ("message", REAL_KEY + "0", REAL_THREAD),
               ("message", "interruption-example", REAL_THREAD), ("message", REAL_KEY, REAL_THREAD.upper()),
               ("message", REAL_KEY, "{%s}" % REAL_THREAD), ("message", REAL_KEY, REAL_THREAD + " --page=x"),
               ("message", REAL_KEY + ":x", REAL_THREAD), ("message", REAL_KEY), None, "message", 7]
        with unittest.mock.patch.object(handover, "hand_over", lambda *args: self.fail("asked")):
            for row in bad:
                if row is None:
                    continue
                with self.subTest(row=row):
                    with self.assertRaises(ValueError):
                        tray.open_dashboard(self.home, "pending", row=row)
            with self.assertRaises(ValueError):
                tray.open_dashboard(self.home, "history", row=("message", REAL_KEY, REAL_THREAD))
        self.assertEqual(self.started.calls, [])


if __name__ == "__main__":
    unittest.main()

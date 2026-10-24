"""A click on a notice itself (v0.6.16): the card's face and the toast's body go where the notice is about.

The owner, 2026-10-15: "팝업을 클릭하면 무언가가 이미 있나? 없다면 만들어줘". Until then a click on a card's face only put it
away, and a toast's body had no launch of its own; the Open button was the only way to the Dashboard. Now:

* `notifier.click_uri` is the one place that says where a click goes (`DestinationTests`): the notice's own Dashboard
  page - its Open button's page, else the page its kind is about - by default and whenever the in-app chat is off;
  Codex at that conversation (`codex://threads/<id>`, measured 2026-10-16 on Codex app 26.1007) when the setting says
  so while the chat is on, a notice about no conversation falling back to its page; the conversation's chat here
  (v0.6.19's chat, in that same function - tests/test_notice_click_chat.py);
* the Codex link holds a UUID's canonical text and nothing else (`LinkTests`), and is opened through Windows' URL
  handler with no shell and no command string (`OpenerTests`);
* the toast's body carries the same destination as its `launch` (`ToastTests`); the card's face hands it to the same
  in-process handler its buttons reach, and still goes (`ActivateTests`, `CardTests`);
* the setting is stored and validated, and written in the advanced edition's chat card alone (`SettingTests`);
* the watcher builds every notice with the destination its settings give (`AppTests`).

Nothing here opens Codex, the Dashboard or a real toast: the opener, PowerShell and the process start are stubbed,
and a card is only ever placed where no screen shows it.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ElementTree

from codex_auto_resume import config, notifier, notify, settings
from test_notice_card import EVENTS, FULL, THREAD, build, captured_xml

LINK = notify.CODEX_THREAD_LINK + THREAD
# The page a notice of each kind with no Open button is about.
NO_BUTTON = {"starting": "pending", "resumed": "history", "failed": "history", "unknown": "history",
             "stopped": "history", "cancelled": "history"}


def open_page(notice):
    """The page a notice's Open button opens, or None."""
    for _label, uri in notice.actions:
        if notify.parse_open_uri(uri) is not None:
            return notify.parse_open_uri(uri)
    return None


# ------------------------------------------------------------------------------ where it goes
class DestinationTests(unittest.TestCase):
    def test_a_notice_with_an_open_button_is_about_that_button_s_page(self):
        seen = set()
        for event, detail, identity in EVENTS + (("needs_you", {"category": "stalled"}, FULL),
                                                 ("memory_warning", {"used": 2, "limit": 1}, None),
                                                 ("after_sleep", {"slept": 7200, "count": 2}, None)):
            notice = build(event, detail, identity)
            page = open_page(notice)
            if page is None:
                continue
            with self.subTest(event=event, kind=notice.kind):
                seen.add(notice.kind)
                self.assertEqual(notice.click, notify.open_uri(page))
        self.assertLessEqual({"interruption", "needs_you", "memory_warning", "after_sleep"}, seen)

    def test_a_notice_with_no_open_button_is_about_the_page_its_kind_is_on(self):
        seen = set()
        for event, detail, identity in EVENTS:
            notice = build(event, detail, identity)
            if open_page(notice) is not None:
                continue
            with self.subTest(event=event, kind=notice.kind):
                seen.add(notice.kind)
                self.assertEqual(notice.click, notify.open_uri(NO_BUTTON[notice.kind]))
        self.assertEqual(seen, {"starting", "resumed", "failed", "unknown", "stopped"})
        self.assertEqual(notifier.build_cancelled(THREAD).click, notify.open_uri("history"))
        self.assertEqual(notifier.click_uri("a kind nobody raises", (), THREAD), notify.open_uri("overview"))
        for page in set(notifier.BODY_PAGES.values()):
            self.assertIsNotNone(notify.parse_open_uri(notify.open_uri(page)), page)

    def test_codex_opens_the_conversation_and_a_notice_about_none_its_page(self):
        for event, detail, identity in EVENTS:
            notice = build(event, detail, identity)
            with self.subTest(event=event):
                self.assertEqual(notifier.click_uri(notice.kind, notice.actions, notice.key, "codex"), LINK)
        for key in (None, "", "not-a-uuid", THREAD.upper(), "{%s}" % THREAD, THREAD + "/x", 7):
            with self.subTest(key=key):
                self.assertEqual(notifier.click_uri("starting", (), key, "codex"), notify.open_uri("pending"))
        memory = notifier.build("memory_warning", {"used": 2, "limit": 1}, destination="codex")
        self.assertIsNone(memory.key)
        self.assertEqual(memory.click, notify.open_uri(open_page(memory)), "about no conversation: its page")

    def test_the_chat_opens_the_conversation_s_chat_and_anything_else_is_the_page(self):
        self.assertEqual(notifier.click_uri("resumed", (), THREAD, "chat"), notify.chat_uri(THREAD))
        self.assertEqual(notifier.click_uri("resumed", (), None, "chat"), notify.open_uri("history"),
                         "about no conversation: its page")
        for destination in ("page", None, "", "somewhere"):
            with self.subTest(destination=destination):
                self.assertEqual(notifier.click_uri("resumed", (), THREAD, destination), notify.open_uri("history"))

    def test_build_takes_the_destination_and_a_demo_opens_nothing(self):
        self.assertEqual(notifier.build("starting", {"thread_id": THREAD}, destination="codex").click, LINK)
        self.assertEqual(notifier.build("starting", {"thread_id": THREAD}).click, notify.open_uri("pending"))
        demo = notifier.build_demo(0.0)
        self.assertEqual((demo.click, demo.content), ("", ()))

    def test_the_setting_is_read_only_while_the_chat_is_on(self):
        stored = {notifier.CLICK_SETTING: "codex"}
        self.assertEqual(notifier.click_destination(stored), "page", "the chat off: the page")
        self.assertEqual(notifier.click_destination(stored, chat=1), "page", "only True is on")
        for value in notifier.CLICK_DESTINATIONS:
            with self.subTest(value=value):
                self.assertEqual(notifier.click_destination({notifier.CLICK_SETTING: value}, chat=True), value)
        for value in (None, "", "Codex", 3):
            with self.subTest(value=value):
                self.assertEqual(notifier.click_destination({notifier.CLICK_SETTING: value}, chat=True), "page")
        self.assertEqual(notifier.click_destination(None, chat=True), "page")


# ------------------------------------------------------------------------------ the link
class LinkTests(unittest.TestCase):
    def test_the_link_is_codex_s_own_with_the_conversation_s_canonical_id(self):
        self.assertEqual(notify.CODEX_THREAD_LINK, "codex://threads/")
        self.assertEqual(notify.codex_thread_uri(THREAD), "codex://threads/" + THREAD)
        self.assertEqual(notify.parse_codex_thread_uri(LINK), THREAD)

    def test_nothing_but_a_canonical_uuid_is_ever_put_in_it_or_read_from_it(self):
        for value in (None, "", "x", THREAD.upper(), "{%s}" % THREAD, THREAD.replace("-", ""), " " + THREAD,
                      THREAD + "&x=1", "../" + THREAD, b"bytes", 1):
            with self.subTest(value=value):
                self.assertIsNone(notify.codex_thread_uri(value))
        for uri in ("codex://threads/", "codex://threads/" + THREAD.upper(), LINK + "?ephemeral=1", LINK + "#x",
                    LINK + "/more", "CODEX://threads/" + THREAD, "codex://launch", "codex://threads//" + THREAD,
                    notify.open_uri("pending"), None, 7):
            with self.subTest(uri=uri):
                self.assertIsNone(notify.parse_codex_thread_uri(uri))


class OpenerTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.windows = Path(folder.name)
        self.started = []

    def open(self, link, *, explorer=True):
        if explorer:
            (self.windows / "explorer.exe").write_bytes(b"")
        with patch.dict(os.environ, {"SystemRoot": str(self.windows)}), \
                patch.object(notify.subprocess, "Popen", lambda *args, **kwargs: self.started.append((args, kwargs))):
            return notify.open_in_codex(link)

    def test_explorer_is_given_the_link_as_its_one_argument_with_no_console_and_no_shell(self):
        self.assertTrue(self.open(LINK))
        self.assertEqual(len(self.started), 1)
        (argv,), options = self.started[0]
        self.assertEqual(argv, [str(self.windows / "explorer.exe"), LINK])
        self.assertEqual(options["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertNotIn("shell", options)

    def test_anything_but_a_conversation_link_starts_nothing(self):
        for link in (LINK + "?x", "codex://launch", notify.open_uri("pending"), "https://example.com", None):
            with self.subTest(link=link):
                with self.assertRaises(ValueError):
                    self.open(link)
        self.assertEqual(self.started, [])

    def test_without_explorer_it_says_so_and_starts_nothing(self):
        self.assertFalse(self.open(LINK, explorer=False))
        self.assertEqual(self.started, [])


# ------------------------------------------------------------------------------ the toast
class ToastTests(unittest.TestCase):
    def raised(self, notice):
        documents = captured_xml(lambda: notifier.deliver(notice, inbox=None))
        self.assertEqual(len(documents), 1)
        return ElementTree.fromstring(documents[0]["XML"])

    def test_the_toast_s_body_goes_where_the_card_s_face_goes(self):
        for event, detail, identity in EVENTS:
            for destination in ("page", "codex"):
                notice = notifier.build(event, dict(detail, thread_id=THREAD), identity, destination=destination)
                with self.subTest(event=event, destination=destination):
                    root = self.raised(notice)
                    self.assertEqual(root.tag, "toast")
                    self.assertEqual(root.get("launch"), notice.click)
                    self.assertEqual(root.get("activationType"), "protocol")
                    # Its buttons are what they were: the body's destination is the toast's own attribute.
                    self.assertEqual([action.get("arguments") for action in root.iter("action")],
                                     [uri for _label, uri in notice.actions])

    def test_the_history_copy_carries_it_too(self):
        notice = build("starting", {})
        shown = []
        notifier.complete(notice, True, show=lambda content, silent=False: shown.append((content, silent)) or True)
        self.assertEqual(shown[0][0]["launch"], notice.click)
        self.assertTrue(shown[0][1])

    def test_a_toast_nothing_gave_a_launch_is_what_it_always_was(self):
        document = notify._toast_xml("t", "b")
        self.assertTrue(document.startswith('<toast duration="long"><visual>'), document)
        self.assertNotIn("launch", document)
        self.assertIn('launch="a&amp;b"', notify._toast_xml("t", "b", launch="a&b"), "an attribute, escaped")


# ------------------------------------------------------------------------------ the press
class ActivateTests(unittest.TestCase):
    def test_a_conversation_link_is_opened_by_the_opener_it_is_given(self):
        opened, lines = [], []
        result = notifier.activate(LINK, open_link=lambda link: opened.append(link) or True, log=lines.append)
        self.assertEqual(result, "opened")
        self.assertEqual(opened, [LINK])
        self.assertEqual(lines, ["thread %s: Codex opened from a notification card" % THREAD])

    def test_without_an_opener_or_when_it_fails_nothing_else_happens(self):
        self.assertEqual(notifier.activate(LINK), "not_opened")
        self.assertEqual(notifier.activate(LINK, open_link=lambda link: False), "not_opened")

        def broken(link):
            raise OSError("no")
        lines = []
        self.assertEqual(notifier.activate(LINK, open_link=broken, log=lines.append), "failed")
        self.assertEqual(lines, ["notification card: opening Codex failed (OSError)"])

    def test_a_link_that_is_not_exactly_a_conversation_s_is_ignored_and_opens_nothing(self):
        opened = []
        for uri in (LINK + "?x=1", "codex://threads/" + THREAD.upper(), "codex://launch", "codex://threads/"):
            with self.subTest(uri=uri):
                self.assertEqual(notifier.activate(uri, open_link=opened.append), "ignored")
        self.assertEqual(opened, [])

    def test_the_page_a_face_opens_is_the_one_its_open_button_opens(self):
        pages = []
        notice = build("interruption", EVENTS[0][1])
        self.assertEqual(notifier.activate(notice.click, open_dashboard=lambda page: pages.append(page) or True),
                         "opened")
        self.assertEqual(pages, [open_page(notice)])


# ------------------------------------------------------------------------------ the setting
class SettingTests(unittest.TestCase):
    def test_it_is_stored_and_validated_with_the_page_by_default(self):
        self.assertEqual(notifier.CLICK_DESTINATIONS, settings.NOTICE_CLICKS)
        self.assertEqual(settings.NOTICE_CLICKS, ("page", "chat", "codex"))
        self.assertEqual(settings.defaults()[notifier.CLICK_SETTING], "page")
        default, coerce = settings.FIELDS[notifier.CLICK_SETTING]
        self.assertEqual(notifier.DEFAULT_CLICK, default)
        for value, kept in (("codex", "codex"), ("chat", "chat"), ("Codex", "page"), (None, "page"), (1, "page")):
            with self.subTest(value=value):
                self.assertEqual(coerce(value, default), kept)

    def test_it_is_written_in_the_dashboard_alone(self):
        self.assertIn(notifier.CLICK_SETTING, settings.DASHBOARD_ONLY)
        self.assertNotIn(notifier.CLICK_SETTING, settings.NOT_YET_OFFERED)
        self.assertNotIn(notifier.CLICK_SETTING, {entry["name"] for entry in settings.describe()})
        from codex_auto_resume import mcpserver
        self.assertNotIn(notifier.CLICK_SETTING, mcpserver.settings_schema()["properties"])


# ------------------------------------------------------------------------------ the watcher
class AppTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.codex = Path(folder.name) / "codex"
        self.codex.mkdir()
        self.paths = config.Paths(Path(folder.name) / "home")

    def app(self):
        from codex_auto_resume import app
        return app.App(self.paths, codex_home=self.codex, enable_logging=False)

    def test_every_notice_is_built_with_the_destination_its_settings_give(self):
        instance = self.app()
        built = []
        real = notifier.build

        def recording(*args, **kwargs):
            built.append(kwargs.get("destination"))
            return real(*args, **kwargs)
        with patch.object(notifier, "build", recording), \
                patch.object(notifier, "click_destination", lambda values, chat=False: "codex"), \
                patch.object(notifier, "deliver", lambda notice, **kwargs: ("toast", True)):
            source = types.SimpleNamespace(identity=lambda thread: FULL)
            instance._notifier(source)("starting", {"thread_id": THREAD})
            instance._show_watcher_notice("memory_warning", {"used": 2, "limit": 1})
        self.assertEqual(built, ["codex", "codex"])

    def test_a_card_s_face_reaches_the_codex_opener(self):
        instance = self.app()
        seen = {}
        with patch.object(notifier, "activate", lambda uri, **kwargs: seen.update(kwargs, uri=uri) or "opened"):
            self.assertEqual(instance._notice_action(LINK), "opened")
        self.assertEqual(seen["uri"], LINK)
        self.assertIs(seen["open_link"], notify.open_in_codex)


# ------------------------------------------------------------------------------ the card, on Windows
@unittest.skipUnless(os.name == "nt", "the card is a Windows window")
class CardTests(unittest.TestCase):
    # Far outside any monitor, as test_notice_card's WindowsTests place theirs.
    WHERE = {"work": (-24000, -24000, -22000, -22800), "monitor": (-24000, -24000, -22000, -22752),
             "anchor": None, "dpi": 96}
    LIGHT = {"theme": "light", "contrast": False, "reduced": False}

    def setUp(self):
        from codex_auto_resume import notice_window
        from codex_auto_resume.ui import popup as tray_popup
        self.window = notice_window
        self.now = 0.0
        tray_popup._gdiplus_acquire()
        self.addCleanup(tray_popup._gdiplus_release)

    def stack(self, on_action):
        stack = self.window.CardStack(clock=lambda: self.now, locate=lambda: dict(self.WHERE),
                                      appearance=lambda: dict(self.LIGHT), on_action=on_action,
                                      worker=lambda target, *args: target(*args)).create()
        self.addCleanup(stack.destroy)
        return stack

    def press(self, stack, card, message_down, message_up):
        middle = ((card.size[1] // 2) << 16) | 4                      # on the card, not on a button
        stack._handle(card.body.hwnd, message_down, 0, middle)
        stack._handle(card.body.hwnd, message_up, 0, middle)

    def test_a_click_on_the_face_opens_where_the_notice_is_about_and_the_card_goes(self):
        for destination in ("page", "codex"):
            with self.subTest(destination=destination):
                clicked = []
                stack = self.stack(clicked.append)
                notice = notifier.build("starting", {"thread_id": THREAD}, FULL, destination=destination)
                card = stack.show(notice)
                self.assertEqual(card.vm["click"], notice.click)
                self.press(stack, card, self.window.WM_LBUTTONDOWN, self.window.WM_LBUTTONUP)
                self.assertEqual(clicked, [notice.click])
                self.assertEqual(card.motion.phase, "exit")

    def test_a_button_still_does_only_what_it_says(self):
        clicked = []
        stack = self.stack(clicked.append)
        card = stack.show(build("interruption", EVENTS[0][1]))
        target, rect = card.plan["targets"][0]
        point = ((rect[1] + rect[3]) // 2 << 16) | ((rect[0] + rect[2]) // 2)
        stack._handle(card.body.hwnd, self.window.WM_LBUTTONDOWN, 0, point)
        stack._handle(card.body.hwnd, self.window.WM_LBUTTONUP, 0, point)
        self.assertEqual(clicked, [card.vm["actions"][target[1]]["uri"]])

    def test_a_right_click_and_a_demo_s_face_open_nothing(self):
        clicked = []
        stack = self.stack(clicked.append)
        card = stack.show(build("starting", {}))
        middle = ((card.size[1] // 2) << 16) | 4
        stack._handle(card.body.hwnd, self.window.WM_RBUTTONUP, 0, middle)
        self.assertEqual(card.motion.phase, "exit")
        demo = stack.show(notifier.build_demo(0.0))
        self.press(stack, demo, self.window.WM_LBUTTONDOWN, self.window.WM_LBUTTONUP)
        self.assertEqual(clicked, [])
        self.assertEqual(demo.motion.phase, "exit")


if __name__ == "__main__":
    unittest.main()

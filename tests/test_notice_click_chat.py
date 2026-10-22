"""Where a click on a notice goes while the in-app chat is on (v0.6.19, the roadmap's "the person picks that
conversation's chat here, or Codex at that conversation").

* the chat's link names one conversation's canonical id and nothing else, and only exactly that shape is read back
  (`LinkTests`);
* a card's face with that link opens the window at the chat with that conversation, and a toast's body reaches the
  same through the activation command (`OpenTests`) - the window started with no console, the id the only thing
  put on its command line;
* the watcher reads `notice_click` only while the edition's plug says the chat is on (`WatcherTests`): the standard
  edition's plug never says so, and every click opens the page there.

Nothing here opens a window: the process start is stubbed.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from codex_auto_resume import config, notifier, notify
from codex_auto_resume.ui import tray
from codex_auto_resume.ui.tray import dashboard

from test_notice_card import THREAD  # noqa: E402  (a fixture conversation)


class LinkTests(unittest.TestCase):
    def test_the_chat_link_holds_the_conversation_and_reads_back_exactly(self):
        link = notify.chat_uri(THREAD)
        self.assertEqual(link, "codex-auto-resume:chat?thread=" + THREAD)
        self.assertEqual(notify.parse_chat_uri(link), THREAD)
        self.assertIsNone(notify.parse_open_uri(link), "never read as a page")
        for bad in (None, "", "x", THREAD.upper(), "{%s}" % THREAD, THREAD + "&a=1", 7):
            with self.subTest(bad=bad):
                self.assertIsNone(notify.chat_uri(bad))
        for bad in (link + "&page=settings", link.upper(), "codex-auto-resume:chat?thread=" + THREAD + "/x",
                    "other:chat?thread=" + THREAD, None, 3):
            with self.subTest(bad=bad):
                self.assertIsNone(notify.parse_chat_uri(bad))


class OpenTests(unittest.TestCase):
    def test_a_card_s_face_opens_the_chat_with_that_conversation(self):
        """Fails with activate's chat branch reverted: the link would be ignored."""
        opened = []
        said = notifier.activate(notify.chat_uri(THREAD), open_chat=lambda thread: opened.append(thread) or True)
        self.assertEqual((said, opened), ("opened", [THREAD]))
        self.assertEqual(notifier.activate(notify.chat_uri(THREAD)), "not_opened", "no opener, nothing opened")

    def test_the_window_is_started_at_the_chat_with_no_console(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.assertFalse(dashboard.open_chat(home, THREAD), "no window installed")
            (home / "CodexAutoResumeSettings.exe").write_bytes(b"")
            with patch.object(subprocess, "Popen") as started:
                self.assertTrue(dashboard.open_chat(home, THREAD))
            arguments, options = started.call_args
            self.assertEqual(arguments[0][1:], ["--page=advanced", "--capability=codex_chat", "--chat=" + THREAD])
            self.assertEqual(options["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self.assertRaises(ValueError):
                dashboard.open_chat(home, "not a conversation")

    def test_a_toast_s_body_reaches_the_chat_through_the_activation_command(self):
        from codex_auto_resume.commands import watcher
        opened = []
        app = types.SimpleNamespace(paths=types.SimpleNamespace(home=Path(".")), logger=types.SimpleNamespace(
            info=lambda *args: None), settings={})
        with patch.object(watcher, "_app", lambda args: app), \
                patch.object(tray, "open_chat", lambda home, thread: opened.append(thread) or True):
            code = watcher.cmd_activate(types.SimpleNamespace(uri=notify.chat_uri(THREAD)))
        self.assertEqual((code, opened), (watcher.EXIT_OK, [THREAD]))


class WatcherTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.codex = Path(folder.name) / "codex"
        self.codex.mkdir()
        self.paths = config.Paths(Path(folder.name) / "home")

    def test_the_setting_is_read_only_while_the_plug_says_the_chat_is_on(self):
        """Fails with the watcher's `_chat` flag reverted: a click would always open the page."""
        from codex_auto_resume import app
        instance = app.App(self.paths, codex_home=self.codex, enable_logging=False)
        instance.settings = dict(instance.settings, notice_click="chat")
        built = []
        real = notifier.build

        def recording(*args, **kwargs):
            built.append(kwargs.get("destination"))
            return real(*args, **kwargs)
        source = types.SimpleNamespace(identity=lambda thread: None)
        with patch.object(notifier, "build", recording), \
                patch.object(notifier, "deliver", lambda notice, **kwargs: ("toast", True)):
            instance._edition_notices({})
            instance._notifier(source)("starting", {"thread_id": THREAD})
            instance._edition_notices({"notice": {"chat": True}})
            instance._notifier(source)("starting", {"thread_id": THREAD})
            instance._edition_notices({"notice": {"chat": "yes"}})
            instance._notifier(source)("starting", {"thread_id": THREAD})
        self.assertEqual(built, ["page", "chat", "page"])


if __name__ == "__main__":
    unittest.main()

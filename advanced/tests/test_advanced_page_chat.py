# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The Chat tab opens a Chat page of its own (v0.6.19; the owner's decision of 2026-10-24), in the window itself.

Until then the tab jumped to the Advanced features page's chat card and never marked itself. Now: the tab shows only
while chat is on, opens the Chat page and is drawn as the chosen tab there (and not on any other page); the chat - the
conversation, its turns, the box, Send... - is on that page and nowhere on the Advanced features page, whose card for the
capability keeps its switch, limits and statement and holds a button that opens the chat; and a notice's click that
starts the window with `--chat=<conversation>` opens the Chat page at that conversation. Driven through the page's own
hooks with the real bridge's answers, made in a home of its own; the conversation's reading is a test's own.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_chat.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402

CHAT = "codex_chat"
SAID = "Carry on with the release notes."


def reading():
    """What advanced-chat-read answers for a conversation: one finished turn, its words both ways and its counts."""
    turn = {"messages": [{"from": "you", "words": SAID}, {"from": "codex", "words": "Done: the notes are written."}],
            "counts": {"commands": 2, "files": 1}, "status": "completed"}
    return {"ok": True, "result": {"done": True, "refusal": None, "turns": [turn], "messages": [], "words_limit": 4000,
                                   "limit": {"full": False}}}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def scenario_tab(cls, bridge):
        cls.watched(bridge, CHAT, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-chat-read"] = [reading()] * 4
        steps = [{"do": "snapshot", "reply": snapshot(on=1)}, {"do": "page", "name": "overview"}, {"do": "look"},
                 {"do": "chat_tab"}, {"do": "look"},
                 {"do": "show"}, {"do": "choose", "id": CHAT}, {"do": "look"},
                 {"do": "chat_open"}, {"do": "look"},
                 {"do": "page", "name": "pending"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_notice(cls, bridge):
        """The window started as a notice's click starts it: `--chat=<conversation>`."""
        cls.watched(bridge, CHAT, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-chat-read"] = [reading()] * 4
        reply = snapshot(on=1)
        thread = reply["pending"][0]["thread_id"]
        steps = [{"do": "snapshot", "reply": reply}, {"do": "chat_argument", "argument": "--chat=" + thread},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"thread": thread}

    @classmethod
    def scenario_off(cls, bridge):
        """Chat off: no tab."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot(on=0)}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    # ---------------------------------------------------------------- tests
    def test_the_tab_opens_its_own_page_and_is_the_chosen_tab_there(self):
        """Fails with the tab reverted to the Advanced features page's card: the page is "advanced" and the tab plain."""
        result, _expected = self.of("scenario_tab")
        overview, chat, _advanced, opened, pending = result["looks"]
        self.assertTrue(overview["chat"]["tab_shown"])
        self.assertFalse(overview["chat"]["tab_current"])
        for look in (chat, opened):
            self.assertEqual(look["page"], "chat")
            self.assertTrue(look["chat"]["tab_current"], "the Chat tab is drawn as the chosen one on its page")
            self.assertTrue(look["chat"]["on_page"], "the chat is on the Chat page")
        self.assertFalse(pending["chat"]["tab_current"], "and plain on any other page")

    def test_the_advanced_card_no_longer_hosts_the_chat_and_its_button_opens_the_page(self):
        result, _expected = self.of("scenario_tab")
        _overview, _chat, advanced, opened, _pending = result["looks"]
        self.assertEqual(advanced["page"], "advanced")
        self.assertFalse(advanced["chat"]["on_advanced"], "no chat on the Advanced features page")
        self.assertTrue(advanced["chat"]["link"], "its card holds the button that opens the chat")
        self.assertEqual(opened["page"], "chat")

    def test_a_notice_click_opens_the_page_at_that_conversation(self):
        result, expected = self.of("scenario_notice")
        (look,) = result["looks"]
        self.assertEqual(look["page"], "chat")
        self.assertTrue(look["chat"]["tab_current"])
        self.assertEqual(look["chat"]["thread"], expected["thread"])
        self.assertIn({"thread_id": expected["thread"]}, sent(result, "advanced-chat-read"))

    def test_off_there_is_no_tab(self):
        result, _expected = self.of("scenario_off")
        (look,) = result["looks"]
        self.assertFalse(look["chat"]["tab_shown"])


if __name__ == "__main__":
    unittest.main()

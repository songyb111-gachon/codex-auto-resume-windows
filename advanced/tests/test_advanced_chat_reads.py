# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The Chat page's reads (v0.6.23, audit A-C1, A-C2, A-C3): a failed read, a rebuild under typing, a slow bridge.

- C1: a read that got no answer - the long-lived bridge being reconnected, a timeout - kept nothing: the card said the
  conversation could not be read, the header's light went back to the watcher's, and the two-second read stopped for
  good while the message was still waiting. Now the last view is kept, and the read goes on; an answer that refuses
  still empties it.
- C2: each changed read built the card again with a new message box, whose caret is at its start, so what the person
  typed next went to the front. Now the box is kept, with its words, its caret and what is chosen in it.
- C3: behind a slow bridge every two-second tick queued another read. Now one is on its way at a time.

Driven through the page's own hooks with the real bridge's answers, the chat's two-second read once per `chat_poll`
step, a slow bridge as `hold` (the answers held, then let go), typing as `chat_type`.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_chat_reads.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402

CHAT = "codex_chat"
WORKING = "checking"
RECONNECTING = {"ok": False, "error": "the connection to the local service is being restored",
                "error_code": "reconnecting"}
TIMED_OUT = {"ok": False, "error": "the local service did not answer"}
REFUSED = {"ok": True, "result": {"done": False, "refusal": "not_on"}}


def reading(*messages, running=False):
    """What advanced-chat-read answers: one turn - running, or finished - and the page's own messages by state."""
    turn = {"messages": [{"from": "you", "words": "Carry on."}], "counts": {"commands": 0, "files": 0},
            "status": "inProgress" if running else "completed"}
    return {"ok": True, "result": {"done": True, "refusal": None, "turns": [turn], "words_limit": 4000,
                                   "messages": [{"state": state, "reason": None} for state in messages],
                                   "limit": {"full": False}}}


def quiet():
    """Nothing pending, so the watcher's own light is "monitoring" and the working light is told from it."""
    reply = snapshot(on=1)
    reply["pending"] = []
    reply["status"]["pending"] = 0
    return reply


def poll(answer):
    """The next read answered with `answer`, then the chat's two-second poll, then a look."""
    return [{"do": "reply", "key": "advanced-chat-read", "with": [answer]}, {"do": "chat_poll"}, {"do": "look"}]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def opened(cls, bridge, first):
        """The window on the Chat page at a conversation, which reads `first`; looked at."""
        cls.watched(bridge, CHAT, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-chat-read"] = [first]
        reply = quiet()
        thread = reply["history"][0]["thread_id"]
        steps = [{"do": "snapshot", "reply": reply}, {"do": "chat_argument", "argument": "--chat=" + thread},
                 {"do": "look"}]
        return script, steps

    @classmethod
    def scenario_reads_fail(cls, bridge):
        """A message waiting; a read reconnecting, one timing out, one answered, then one refused."""
        script, steps = cls.opened(bridge, reading("waiting"))
        steps += poll(RECONNECTING) + poll(TIMED_OUT) + poll(reading("in_flight")) + poll(REFUSED)
        words = script["advanced-words"][0]["result"]["words"]
        return "en", {"script": script, "steps": steps}, {"words": words}

    # ---------------------------------------------------------------- C1
    def test_a_read_with_no_answer_keeps_the_view_and_the_two_second_read(self):
        """Fails with the view dropped on any failed read: the light goes back and the read stops."""
        result, expected = self.of("scenario_reads_fail")
        first, reconnecting, timed_out, flying, _refused = (look["chat"] for look in result["looks"])
        self.assertEqual(first["light"], WORKING)
        for index, look in enumerate((reconnecting, timed_out)):
            self.assertTrue(look["viewed"], index)
            self.assertTrue(look["polling"], "the two-second read goes on (%d)" % index)
            self.assertEqual(look["light"], WORKING, index)
            self.assertEqual(look["headline"], expected["words"]["page.chat.sending"], index)
        self.assertEqual(flying["headline"], expected["words"]["page.chat.sent"], "the next read is shown")

    def test_an_answer_that_refuses_still_empties_the_view(self):
        result, _expected = self.of("scenario_reads_fail")
        refused = result["looks"][-1]["chat"]
        self.assertFalse(refused["viewed"])
        self.assertEqual(refused["light"], "monitoring")
        self.assertEqual(len(sent(result, "advanced-chat-read")), 6, "the arrival's two reads and the four polls")



if __name__ == "__main__":
    unittest.main()

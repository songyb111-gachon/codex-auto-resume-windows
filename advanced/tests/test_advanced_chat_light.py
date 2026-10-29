# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The Dashboard's status light moves while a chat message is on its way (v0.6.20; the owner's report of 2026-10-26).

A light that does not move while work runs reads as broken or idle. While a message written on the Chat page waits to be
delivered ("waiting") or is on its way ("in_flight"), the header shows the window's working light - "checking", the arc
the installer's progress shows - and the card's own words beside it ("Sending...", "Sent"); once it is delivered, taken
back, failed or cancelled the header goes back to what the watcher's state says. A watcher not known to be running keeps
its grey light (the message is not going anywhere), and a message waiting for a full usage limit is no work in progress.
Driven through the page's own hooks, the chat's two-second read once per `chat_poll` step, with the real bridge's words.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_chat_light.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pagecase import CSC, POWERSHELL, PageCase, sent, snapshot  # noqa: E402

CHAT = "codex_chat"
WORKING = "checking"
WATCHING = "Watching for interruptions"


def reading(*messages, full=False):
    """What advanced-chat-read answers: a finished turn and the page's own messages, each as (state, reason)."""
    turn = {"messages": [{"from": "you", "words": "Carry on."}], "counts": {"commands": 0, "files": 0},
            "status": "completed"}
    return {"ok": True, "result": {"done": True, "refusal": None, "turns": [turn], "words_limit": 4000,
                                   "messages": [{"state": state, "reason": reason} for state, reason in messages],
                                   "limit": {"full": full}}}


def quiet(running=True):
    """The fullest snapshot with nothing pending, so the watcher's own light is "monitoring" - or, with the watcher not
    running, "idle" - and the working light is told from it."""
    reply = snapshot(on=1)
    reply["pending"] = []
    reply["status"]["pending"] = 0
    reply["status"]["watcher_running"] = running
    reply["status"]["watcher"]["running"] = running
    return reply


def view(*messages, **more):
    """The next read, then the chat's two-second poll, then a look."""
    return [{"do": "reply", "key": "advanced-chat-read", "with": [reading(*messages, **more)]}, {"do": "chat_poll"},
            {"do": "look"}]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class LightTests(PageCase):
    @classmethod
    def opened(cls, bridge, reply, first):
        """The window on the Chat page at a conversation, which reads `first`; looked at."""
        cls.watched(bridge, CHAT, state="armed")
        script = cls.opening(bridge, "en")
        script["advanced-chat-read"] = [first]
        thread = reply["history"][0]["thread_id"]
        steps = [{"do": "snapshot", "reply": reply}, {"do": "chat_argument", "argument": "--chat=" + thread},
                 {"do": "look"}]
        return script, steps

    @classmethod
    def scenario_the_message_goes(cls, bridge):
        """Waiting, in flight, delivered; then one not taken, one that fails, one cancelled."""
        script, steps = cls.opened(bridge, quiet(), reading(("waiting", None)))
        for messages in ([("in_flight", None)], [("done", "delivered")],
                         [("waiting", None)], [("cancelled", "not_taken")],
                         [("waiting", None)], [("done", "unknown")],
                         [("waiting", None)], [("cancelled", "cancelled")]):
            steps += view(*messages)
        words = script["advanced-words"][0]["result"]["words"]
        return "en", {"script": script, "steps": steps}, {"words": words}

    @classmethod
    def scenario_off_the_page(cls, bridge):
        """Leaving the Chat page with a message on its way: the read goes on there, and the light goes back at the end."""
        script, steps = cls.opened(bridge, quiet(), reading(("waiting", None)))
        steps += [{"do": "page", "name": "overview"}, {"do": "look"}]
        steps += view(("in_flight", None))
        steps += view(("done", "delivered"))
        # Nothing left to watch: this poll asks for nothing, so the "waiting" it would have read is never seen.
        steps += view(("waiting", None))
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_watcher_not_running(cls, bridge):
        """A message waits and nothing takes it: the grey light of a watcher that is not running stays."""
        script, steps = cls.opened(bridge, quiet(running=False), reading(("waiting", None)))
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_limit_full(cls, bridge):
        """Waiting for the usage limit to reset is not work that is running."""
        script, steps = cls.opened(bridge, quiet(), reading(("waiting", None), full=True))
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_sent_from_the_page(cls, bridge):
        """Send... answered: the message is waiting at once, with no read between."""
        script, steps = cls.opened(bridge, quiet(), reading())
        script["advanced-chat-send"] = [reading(("waiting", None))]
        steps += [{"do": "answer", "with": [True]}, {"do": "chat_send", "text": "Carry on."}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    # ---------------------------------------------------------------- tests
    def test_a_message_waiting_to_be_taken_lights_the_working_light_and_says_sending(self):
        """Fails with the header untold (HeroTold gone): the light stays the watcher's own, "monitoring"."""
        result, expected = self.of("scenario_the_message_goes")
        waiting = result["looks"][0]["chat"]
        self.assertEqual(waiting["light"], WORKING)
        self.assertEqual(waiting["headline"], expected["words"]["page.chat.sending"])

    def test_a_message_on_its_way_keeps_it_lit_and_says_sent(self):
        result, expected = self.of("scenario_the_message_goes")
        flying = result["looks"][1]["chat"]
        self.assertEqual(flying["light"], WORKING)
        self.assertEqual(flying["headline"], expected["words"]["page.chat.sent"])

    def test_delivered_not_taken_failed_and_cancelled_go_back_to_the_watchers_light(self):
        result, _expected = self.of("scenario_the_message_goes")
        looks = result["looks"]
        # The look after each read: 0 waiting, 1 in flight, 2 delivered, 3 waiting, 4 not taken, 5 waiting, 6 failed,
        # 7 waiting, 8 cancelled.
        for index in (3, 5, 7):
            self.assertEqual(looks[index]["chat"]["light"], WORKING, index)
        for index in (2, 4, 6, 8):
            self.assertEqual(looks[index]["chat"]["light"], "monitoring", index)
            self.assertEqual(looks[index]["chat"]["headline"], WATCHING, index)

    def test_the_light_follows_the_message_after_the_page_is_left(self):
        result, _expected = self.of("scenario_off_the_page")
        on_page, away, flying, delivered, stale = result["looks"]
        self.assertEqual(on_page["chat"]["light"], WORKING)
        self.assertNotEqual(away["page"], "chat")
        self.assertEqual(away["chat"]["light"], WORKING, "the other pages' header is lit too")
        self.assertEqual(flying["chat"]["light"], WORKING, "and the read goes on there")
        self.assertEqual(delivered["chat"]["light"], "monitoring", "back once it is delivered")
        self.assertEqual(delivered["chat"]["headline"], WATCHING)
        self.assertEqual(stale["chat"]["light"], "monitoring", "a read away from the page with nothing to watch is not made")
        self.assertEqual(len(sent(result, "advanced-chat-read")), 4, "the arrival's two reads and the two polls that had a message")

    def test_a_watcher_that_is_not_running_keeps_its_grey_light_beside_a_waiting_message(self):
        (look,) = self.of("scenario_watcher_not_running")[0]["looks"]
        self.assertEqual(look["chat"]["light"], "idle")
        self.assertEqual(look["chat"]["headline"], "Watcher not running")

    def test_a_message_waiting_for_a_full_usage_limit_is_no_work_in_progress(self):
        (look,) = self.of("scenario_limit_full")[0]["looks"]
        self.assertEqual(look["chat"]["light"], "monitoring")

    def test_a_message_sent_from_the_page_lights_the_header_at_once(self):
        result, _expected = self.of("scenario_sent_from_the_page")
        before, after = result["looks"]
        self.assertEqual(before["chat"]["light"], "monitoring")
        self.assertEqual(after["chat"]["light"], WORKING)
        self.assertEqual(len(sent(result, "advanced-chat-send")), 1)


if __name__ == "__main__":
    unittest.main()

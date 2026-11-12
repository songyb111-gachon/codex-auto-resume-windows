"""A Pause never takes back a chat message Codex already holds (v0.6.23, finding B1 of the second round's audit): the
chat's statement says "a Pause or Cancel does not take back one Codex already holds", and since its records are marked
`pause_keeps` (engine/chat.handed) core's paused take-back passes them over (engine/plugrecords._take_back). Every
route that pauses reaches the engine as recovery switched off - the Dashboard, the tray, Telegram /pause and the
loopback API's POST /pause all write that one setting - or as an administrator's DisableAutoResume; both are held here.
The chat's own three-minute take-back still works, and the prompt queue and reset messages keep the take-back their
statements state: a Pause takes back what Codex holds - the queue's held for the person with its words kept, a reset
message cancelled.

Held against the shipped definitions and core's own engine, store and simulated Codex home (takingcase.py).
"""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_chat as chat_case  # noqa: E402
import test_advanced_prompt_queue as queue_case  # noqa: E402
import test_advanced_reset_message as reset_case  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.engine import chat as chat_engine  # noqa: E402
from codex_auto_resume_advanced.registry import PROMPT_QUEUE  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (ChatReason, ChatState, PromptState, RecordState,  # noqa: E402
                                                   RuleReason, RuleState)
from test_engine import T1, T2  # noqa: E402


def by_settings(h):
    h.store.set_enabled(False, h.now)


def by_policy(h):
    h.engine.managed = SimpleNamespace(disable_auto_resume=True)


PAUSES = {"recovery switched off": by_settings, "DisableAutoResume": by_policy}


class ChatPauseTests(chat_case.ChatCase):
    def held_in_codex(self, h=None):
        """A chat message sent and held in Codex's queue (its turn not yet dispatched): its record id."""
        plug = self.armed(h)
        key = self.waiting(plug)
        self.h.tick()
        self.assertEqual(len(self.h.home.queued(T1)), 1)
        self.assertEqual(plug.runtime.state.chat_by_record(key)["state"], ChatState.IN_FLIGHT)
        return plug, key

    def record_row(self, plug, key):
        with plug.runtime.state._read() as connection:
            return connection.execute("SELECT state FROM records WHERE record_id=?", (key,)).fetchone()[0]

    def test_a_pause_by_each_route_leaves_it_in_codexs_queue_and_withdraws_nothing(self):
        """Fails with `pause_keeps` taken out of chat.handed: the paused tick would delete the queue item and end the
        message withdrawn, its words already gone."""
        for how, pause in PAUSES.items():
            with self.subTest(how):
                self.setUp()
                plug, key = self.held_in_codex()
                queued = list(self.h.home.queued(T1))
                pause(self.h)
                for _ in range(2):
                    self.h.tick(advance=60)              # within the chat's own three minutes
                self.assertEqual(self.h.home.queued(T1), queued, "still in Codex's queue")
                self.assertEqual(self.h.backend.deleted, [], "nothing deleted")
                row = plug.runtime.state.chat_by_record(key)
                self.assertEqual((row["state"], row["reason"]), (ChatState.IN_FLIGHT, None), "not withdrawn")
                self.assertEqual(self.record_row(plug, key), RecordState.IN_FLIGHT)
                self.assertEqual(len(self.calls), 1, "sent once")

    def test_held_through_a_pause_it_is_delivered_when_codex_takes_it(self):
        plug, key = self.held_in_codex()
        by_settings(self.h)
        self.h.tick(advance=30)
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        row = plug.runtime.state.chat_by_record(key)
        self.assertEqual((row["state"], row["reason"]), (ChatState.DONE, ChatReason.DELIVERED))

    def test_its_own_three_minute_take_back_still_works_after_a_pause(self):
        plug, key = self.held_in_codex()
        by_settings(self.h)
        for _ in range(4):
            self.h.tick(advance=60)
        self.assertEqual(plug.runtime.state.chat_by_record(key)["state"], ChatState.IN_FLIGHT, "kept while paused")
        self.h.store.set_enabled(True, self.h.now)
        self.h.tick(advance=5)
        row = plug.runtime.state.chat_by_record(key)
        self.assertEqual((row["state"], row["reason"]), (ChatState.CANCELLED, ChatReason.NOT_TAKEN))
        self.assertEqual(self.h.home.queued(T1), [])
        self.assertEqual(len(self.calls), 1, "never sent again")

    def test_every_record_it_hands_is_marked(self):
        plug = self.armed()
        key = self.waiting(plug)
        self.assertIs(chat_engine.handed(plug.runtime.state.chat_by_record(key))["pause_keeps"], True)
        self.h.tick()
        flying = chat_engine.watched(plug.runtime.state.chat_by_record(key), self.h.now + 600)
        self.assertEqual((flying["state"], flying["pause_keeps"], flying["withdraw"]), ("in_flight", True, True))


class ChatBesideQueueAtAPauseTests(chat_case.ChatCase):
    """The chat and the prompt queue on together, each holding one in Codex's queue (two conversations): a Pause takes
    back the queue's and holds it with its words, and leaves the chat's."""
    BESIDE = (PROMPT_QUEUE,)

    def test_a_pause_takes_back_the_prompt_and_leaves_the_chat_message(self):
        """Fails with the mark taken out of chat.handed: the Pause would take the chat message back as well."""
        self.h.home.add_turn(T2)
        self.h.backend.loaded_map[T2] = "loaded"
        plug = self.armed()
        self.h.backend.after_accept = "queue"
        key = self.waiting(plug)
        added = surfaces.bridge(plug.runtime, "advanced-prompt-add",
                                dict(thread_id=T2, words=queue_case.SENTINEL, trigger="after_turn",
                                     generation=plug.runtime.state.meta()["generation"]))
        self.assertTrue(added["done"], added)
        for _ in range(2):
            self.h.tick(advance=1)
        self.assertEqual((len(self.h.home.queued(T1)), len(self.h.home.queued(T2))), (1, 1))
        prompt = plug.runtime.state.prompts(pending=None)[0]["prompt_id"]
        by_settings(self.h)
        for _ in range(2):
            self.h.tick(advance=1)
        self.assertEqual(self.h.home.queued(T2), [], "the prompt taken back")
        row = plug.runtime.state.prompt(prompt)
        self.assertEqual((row["state"], row["words"]), (PromptState.HELD, queue_case.SENTINEL), "held, words kept")
        self.assertEqual(len(self.h.home.queued(T1)), 1, "the chat message left with Codex")
        self.assertEqual(plug.runtime.state.chat_by_record(key)["state"], ChatState.IN_FLIGHT)


class QueuePauseTests(queue_case.QueueCase):
    def held_in_codex(self):
        plug = self.on()
        self.h.backend.after_accept = "queue"
        self.add(plug)
        self.h.tick(advance=1)
        self.assertEqual(len(self.h.home.queued(T1)), 1)
        return plug, self.prompts(plug)[0]["prompt_id"]

    def test_a_pause_by_each_route_takes_back_a_prompt_and_holds_it_with_its_words(self):
        for how, pause in PAUSES.items():
            with self.subTest(how):
                self.setUp()
                plug, prompt = self.held_in_codex()
                pause(self.h)
                for _ in range(2):
                    self.h.tick(advance=1)
                self.assertEqual(self.h.home.queued(T1), [])
                row = plug.runtime.state.prompt(prompt)
                self.assertEqual((row["state"], row["words"]), (PromptState.HELD, queue_case.SENTINEL))


class ResetMessagePauseTests(reset_case.MessageCase):
    def test_a_pause_by_each_route_takes_back_a_reset_message_codex_holds_and_cancels_it(self):
        for how, pause in PAUSES.items():
            with self.subTest(how):
                self.setUp()
                plug = self.armed()
                rule, _key = self.message(plug)
                self.h.tick()
                self.h.backend.after_accept = "queue"
                self.h.now = reset_case.RESET + reset_case.CLOSE_AFTER
                self.h.tick()
                self.assertEqual(len(self.h.home.queued(T1)), 1)
                pause(self.h)
                for _ in range(2):
                    self.h.tick(advance=5)
                self.assertEqual(self.h.home.queued(T1), [])
                gone = self.found(plug, rule)
                self.assertEqual((gone["state"], gone["reason"], gone["record_state"]),
                                 (RuleState.CANCELLED, RuleReason.WITHDRAWN, RecordState.CANCELLED))


if __name__ == "__main__":
    unittest.main()

"""Chat with a conversation in the Dashboard (v0.6.19): a message waits until core takes it, goes into the
conversation exactly as typed with no marker, under the client id core derives, through chat's own channel; its words
leave the disk when its send begins; the page reads the conversation's last turns; nothing of either reaches a log,
the journal, the status or MCP; turned off, a waiting message is cancelled with its words.

Held against the shipped definition and core's own engine, store and simulated Codex home (takingcase.py).
"""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from codexsim import CodexHome  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import Point  # noqa: E402
from codex_auto_resume_advanced import registry, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex.conversation import Conversation  # noqa: E402
from codex_auto_resume_advanced.control import chat as control  # noqa: E402
from codex_auto_resume_advanced.registry import CODEX_CHAT  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning, BridgeCommand,  # noqa: E402
                                                   ChatReason, ChatState, Measurement, Refusal, Verdict)
from test_engine import T1  # noqa: E402

SECRET = "SENTINEL-ask-about-the-blue-heron"


class FakeSession:
    """The app server as thread/queue/add meets it: the item added to codexsim's queue under the id it was given."""

    def __init__(self, h, calls):
        self.h, self.calls = h, calls

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def call(self, method, params):
        self.calls.append((method, params))
        text = params["input"][0]["text"]
        queue_id = self.h.home.enqueue(params["threadId"], text, client_id=params.get("clientUserMessageId"))
        return {"queuedSubmissionId": queue_id}


class ChatCase(TakingCase):
    DEFINITION = CODEX_CHAT

    def setUp(self):
        super().setUp()
        self.h.home.add_turn(T1)
        self.h.backend.loaded_map[T1] = "loaded"
        self.calls = []

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def armed(self, h=None, state="armed"):
        plug = super().armed(h, state=state)
        code = plug.runtime._code_of(self.DEFINITION)
        code.channel._open = lambda: FakeSession(self.h, self.calls)
        return plug

    def waiting(self, plug, words="Please run the tests again."):
        key = secrets.token_hex(32)
        plug.runtime.state.add_chat(T1, words, key, at=self.h.now)
        return key


class SendTests(ChatCase):
    def test_a_message_goes_exactly_as_typed_under_its_id_and_its_words_leave_the_disk(self):
        """Fails with chat's channel reverted: the message would wait, held, and nothing would be sent."""
        plug = self.armed()
        key = self.waiting(plug)
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [], "never core's codex queue, never with a marker")
        (method, params), = self.calls
        self.assertEqual(method, "thread/queue/add")
        self.assertEqual(params["input"][0]["text"], "Please run the tests again.")
        self.assertEqual(params["clientUserMessageId"], ids.continuation_client_id(key))
        row = plug.runtime.state.chat_by_record(key)
        self.assertEqual((row["state"], row["words"]), (ChatState.IN_FLIGHT, None))
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        row = plug.runtime.state.chat_by_record(key)
        self.assertEqual((row["state"], row["reason"]), (ChatState.DONE, ChatReason.DELIVERED))

    def test_off_nothing_is_sent_and_a_waiting_message_ends_with_its_words(self):
        plug = self.armed()
        key = self.waiting(plug)
        self.assertTrue(plug.runtime.arming.disarm(self.cap, actor=Actor.DASHBOARD)["done"])
        plug.runtime.states(fresh=True)
        self.h.tick()
        self.assertEqual((self.calls, self.h.backend.send_calls), ([], []))
        row = plug.runtime.state.chat_by_record(key)
        self.assertEqual((row["state"], row["reason"], row["words"]),
                         (ChatState.CANCELLED, ChatReason.TURNED_OFF, None))

    def test_not_taken_in_three_minutes_it_is_taken_back_and_never_sent_again(self):
        plug = self.armed()
        key = self.waiting(plug)
        self.h.tick()
        for _ in range(4):
            self.h.tick(advance=60)
        row = plug.runtime.state.chat_by_record(key)
        self.assertEqual((row["state"], row["reason"]), (ChatState.CANCELLED, ChatReason.NOT_TAKEN))
        self.assertEqual(len(self.calls), 1)

    def test_its_pace_is_its_own_not_cores_five_or_fifteen_minutes(self):
        """Fails with the A20 exemption reverted: the second message would wait fifteen minutes."""
        plug = self.armed()
        for _ in range(2):
            self.waiting(plug)
            self.h.tick()
            self.h.home.dispatch(T1)
            self.h.tick(advance=2)
        self.assertEqual(len(self.calls), 2)

    def test_nothing_of_a_message_reaches_a_log_the_journal_the_status_or_mcp(self):
        plug = self.armed()
        self.waiting(plug, words=SECRET)
        self.h.tick()
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        seen = [repr(self.h.logs), repr(plug.runtime.state.journal()), json.dumps(surfaces.status(plug.runtime)),
                json.dumps(surfaces.mcp(plug.runtime, {}), default=str)]
        for text in seen:
            self.assertNotIn("heron", text)


class PageTests(ChatCase):
    def bridge(self, plug, command, argument):
        with patch.object(control, "switched_off", lambda runtime, thread: False):
            return surfaces.bridge(plug.runtime, command, argument)

    def test_send_is_refused_off_and_one_at_a_time_and_cancel_takes_the_words(self):
        plug = self.advanced()
        generation = plug.runtime.state.meta()["generation"]
        refused = self.bridge(plug, BridgeCommand.ADVANCED_CHAT_SEND, {"thread_id": T1, "words": "hello",
                                                                       "generation": generation})
        self.assertEqual(refused["refusal"], Refusal.NOT_ON)
        self.arm(plug)
        generation = plug.runtime.state.meta()["generation"]
        with patch.object(Conversation, "view", lambda self, thread: []):
            sent = self.bridge(plug, BridgeCommand.ADVANCED_CHAT_SEND, {"thread_id": T1, "words": "hello",
                                                                        "generation": generation})
            self.assertTrue(sent["done"], sent)
            again = self.bridge(plug, BridgeCommand.ADVANCED_CHAT_SEND, {"thread_id": T1, "words": "hello again",
                                                                         "generation": sent["generation"]})
            self.assertEqual(again["refusal"], Refusal.BEING_SENT)
            cancelled = self.bridge(plug, BridgeCommand.ADVANCED_CHAT_CANCEL, {"thread_id": T1,
                                                                               "generation": sent["generation"]})
        self.assertTrue(cancelled["done"], cancelled)
        (row,) = plug.runtime.state.chats(thread_id=T1)
        self.assertEqual((row["state"], row["words"]), (ChatState.CANCELLED, None))

    def test_no_mcp_tool_reaches_the_chat(self):
        self.assertNotIn("chat", json.dumps(sorted(str(name) for name in surfaces.MCP_TOOLS))
                         if hasattr(surfaces, "MCP_TOOLS") else "")
        for command in (BridgeCommand.ADVANCED_CHAT_READ, BridgeCommand.ADVANCED_CHAT_SEND,
                        BridgeCommand.ADVANCED_CHAT_CANCEL):
            self.assertIn(command, surfaces.ARGUMENTS)


class ReaderTests(unittest.TestCase):
    def test_the_last_turns_messages_and_replies_with_counts_and_no_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            home = CodexHome(Path(folder))
            turn = home.add_turn(T1, None, "completed", user_text="Run it again [codex-auto-resume:0123456789abcdef]")
            home.add_item(T1, turn, "commandExecution")
            running = home.add_turn(T1, None, "inProgress", user_text="And now?", progress=False)
            shown = Conversation(home.root).view(T1)
        self.assertEqual([turn["status"] for turn in shown], ["completed", "inProgress"])
        self.assertEqual(shown[0]["messages"][0], {"from": "you", "words": "Run it again"})
        self.assertEqual(shown[0]["messages"][1]["from"], "codex")
        self.assertEqual(shown[0]["counts"]["commands"], 1)
        self.assertEqual(shown[1]["turn_id"], running)

    def test_only_the_two_kinds_words_are_read(self):
        from codex_auto_resume_advanced.codex import conversation
        for statement in conversation.STATEMENTS:
            if "item_json" in statement:
                self.assertIn("item_type IN (?, ?)", statement)
        self.assertEqual(conversation.TEXT_KINDS, ("userMessage", "agentMessage"))


class RegistryTests(ChatCase):
    def test_it_is_shown_after_the_prompt_queue_and_rests_on_mc1_and_mc2(self):
        shown = registry.SHOWN_ORDER
        self.assertEqual(shown.index(self.cap), shown.index("prompt_queue") + 1)
        self.assertEqual(tuple(d.id for d in registry.REGISTRY.at(Point.SENDER))[-1], self.cap)
        plug = self.advanced()
        definition = plug.runtime.registry.get(self.cap)
        self.assertIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))
        self.measured = {Measurement.M7: (Verdict.PASS, ENGINE), Measurement.MC1: (Verdict.PASS, ENGINE),
                         Measurement.MC2: (Verdict.PASS, ENGINE)}
        self.assertNotIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))


if __name__ == "__main__":
    unittest.main()

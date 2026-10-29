"""A scheduled message with pictures is sent (v0.6.20, #50 item 1, MIMG): only by the watcher, through the prompt queue's
own channel - thread/queue/add with exactly its words and then a localImage item for each of the product's copies, in
the person's order, under the client id core derives, with no marker - and proven by that id; its copies go once it is
delivered. A message with no pictures goes exactly as before, through core's backend with its marker. One whose copy is
gone, or any while MIMG failed, is not sent.

Held against the shipped definition and core's own engine, store and simulated Codex home (takingcase.py), with a fake
app-server session: no real Codex is asked anything.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p "test_advanced_prompt_images*.py"
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_prompt_images import GIF, JPEG, PNG, ImagesCase  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.engine import promptqueue  # noqa: E402
from codex_auto_resume_advanced.registry import PROMPT_QUEUE  # noqa: E402
from codex_auto_resume_advanced.vocabulary import PromptReason, PromptState  # noqa: E402
from test_engine import T1  # noqa: E402

WORDS = "Look at these two screenshots and tell me which layout reads better."


class SendTests(ImagesCase):
    def queued(self, plug, pictures, words=WORDS, **argument):
        return super().queued(plug, pictures, words=words, **argument)

    def test_the_queue_add_carries_exactly_the_words_then_each_picture_in_order(self):
        """Fails with the picture channel reverted: the words go through core's backend alone, with a marker."""
        plug = self.on()
        prompt = self.queued(plug, [self.picture(), self.picture(JPEG, "b.jpg"), self.picture(GIF, "c.gif")])
        copies = [image["path"] for image in self.listed(plug, prompt)["images"]]
        self.h.tick(advance=1)
        self.assertEqual(self.sends(), [], "never core's codex queue, never with a marker")
        (method, params), = self.calls
        self.assertEqual(method, "thread/queue/add")
        self.assertEqual(params["input"], [{"type": "text", "text": WORDS}]
                         + [{"type": "localImage", "path": path} for path in copies])
        self.assertEqual(params["threadId"], T1)
        record = plug.runtime.state.prompt(prompt)["record_id"]
        self.assertEqual(params["clientUserMessageId"], ids.continuation_client_id(record))
        for path in copies:
            self.assertTrue(path.startswith(str(plug.runtime.paths.advanced_dir)), "the product's own copy")

    def test_delivered_by_its_id_it_is_done_and_its_copies_go(self):
        plug = self.on()
        prompt = self.queued(plug, [self.picture()])
        self.h.tick(advance=1)
        self.assertEqual(len(self.copies(plug)), 1, "kept while Codex holds it")
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        self.h.tick(advance=2)
        row = plug.runtime.state.prompt(prompt)
        self.assertEqual((row["state"], row["reason"], row["words"]), (PromptState.DONE, PromptReason.DELIVERED, None))
        self.assertEqual(self.copies(plug), [], "delivered: its copies are removed")

    def test_a_message_with_no_pictures_goes_as_before(self):
        plug = self.on()
        self.add(plug, words=WORDS)
        self.h.tick(advance=1)
        self.assertEqual(self.calls, [])
        (sent,) = self.sends()
        self.assertTrue(sent.startswith(WORDS + "\n\n"), "as typed, its marker after a blank line")

    def test_a_copy_gone_holds_it_and_nothing_is_sent(self):
        """Fails with the copies' check reverted: the words would go with the one picture left."""
        plug = self.on()
        prompt = self.queued(plug, [self.picture(), self.picture(PNG, "b.png")])
        Path(self.listed(plug, prompt)["images"][1]["path"]).unlink()
        self.h.tick(advance=1)
        self.assertEqual((self.calls, self.sends()), ([], []), "never sent without the picture the person added")
        self.assertIn(plug.runtime.state.prompt(prompt)["state"], (PromptState.WAITING, PromptState.READY))

    def test_where_mimg_failed_a_message_with_pictures_is_not_sent(self):
        plug = self.on()
        self.queued(plug, [self.picture()])
        with self.mimg_failed(plug):
            self.h.tick(advance=1)
        self.assertEqual((self.calls, self.sends()), ([], []))


class AnswerTests(ImagesCase):
    def test_a_recovery_of_cores_and_a_message_with_no_pictures_are_never_its_channels(self):
        plug = self.on()
        code = plug.runtime._code_of(plug.runtime.registry.get(self.cap))
        recovery = {"interruption_id": "ab" * 32, "thread_id": T1, "marker": "[codex-auto-resume:0123456789abcdef]"}
        self.assertIs(code.sender(recovery, object()), DEFER)
        self.assertIs(code.delivery(recovery), DEFER)
        backend = object()
        self.assertIs(plug.runtime.ask(Point.SENDER, recovery, backend), backend)
        stranger = {"record_id": "cd" * 32, "thread_id": T1}
        self.assertIs(code.sender(stranger, object()), DEFER)

    def test_a_message_with_pictures_is_proven_by_its_id(self):
        plug = self.on()
        self.queued(plug, [self.picture()])
        self.h.tick(advance=1)
        (row,) = plug.runtime.state.prompts_in_flight()
        record = promptqueue.handed(row)
        self.assertIs(plug.runtime.ask(Point.DELIVERY, record), Alternative.CLIENT_ID)
        channel = plug.runtime._code_of(plug.runtime.registry.get(self.cap)).sender(record, object())
        self.assertIsInstance(channel, promptqueue.ImageChannel)

    def test_it_may_ask_codex_for_one_method_and_its_statement_names_the_new_departures(self):
        self.assertEqual(protocol.CAPABILITY_METHODS["prompt_queue"], ("thread/queue/add",))
        self.assertEqual(PROMPT_QUEUE.revision, 3)
        for standard in ("A2", "A4", "B3", "B4"):
            self.assertIn(standard, PROMPT_QUEUE.departs_from)
        from codex_auto_resume_advanced import statement
        does = statement.CATALOGS.own("en")[statement.key(PROMPT_QUEUE.id, "does")]
        self.assertIn("copy", does)
        self.assertIn("until the message is delivered", does)


if __name__ == "__main__":
    unittest.main()

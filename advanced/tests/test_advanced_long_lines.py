"""The advanced edition's app-server session reads past a line over a megabyte (v0.6.22).

MIMG on codex-cli 0.167.0-alpha.3.2 (2026-11-08) sent ten pictures, the last just under 20 MB: Codex queued, showed and
ran the message, but its answer never reached the session - the reader ended at the first line over 1 MB, the pictures
echoed inline - so the probe recorded add_answer_uncertain twice, and the prompt queue's picture channel would end such
a send as "may have been sent". Held here over real pipes to an app server played in this process (core's
test_appserver_long_lines.PipeServer): the session, the picture channel's send proven delivered by its client id, and
MIMG's record. No real Codex is started.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest test_advanced_long_lines
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advancedcase  # noqa: E402,F401  (puts src, advanced/src and tests on the path)
from codex_auto_resume.codex.appserver import OVERSIZE  # noqa: E402
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume_advanced import measure  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.engine import promptqueue  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, PromptReason, PromptState  # noqa: E402
from test_advanced_measure_stage4 import THREAD, VERSIONS, Backend as MeasureBackend  # noqa: E402
from test_advanced_prompt_images import ImagesCase  # noqa: E402
from test_appserver_long_lines import MB, PipeServer, big_error, big_result, notification  # noqa: E402
from test_engine import T1  # noqa: E402

CLIENT = "00000000-0000-7000-8000-0000000000c1"


class Backend:
    """Core's Backend as a Session uses it: a home of its own and no real Codex."""

    def __init__(self, home):
        self.codex_home = home

    def _compatible(self):
        return {}

    def _argv(self):
        return ["codex"]

    def _environment(self):
        return {}


def piped(case, home, answer):
    """Popen patched for the rest of `case`: each session gets a new PipeServer answering with `answer`."""
    servers = []

    def popen(*unused, **ignored):
        servers.append(PipeServer(home, answer))
        return servers[-1]
    patcher = patch.object(protocol.S, "Popen", popen)
    patcher.start()
    case.addCleanup(patcher.stop)
    return servers


class HomeCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="car-longline-adv-")).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)


class SessionTests(HomeCase):
    """Each fails with the reader reverted: the long line ends it, and the answer after it never comes."""

    def session(self, answer):
        piped(self, self.home, answer)
        return protocol.Session(Backend(self.home), capability=promptqueue.CAPABILITY)

    def test_an_oversize_add_answer_is_an_answer_for_its_id_and_the_next_one_still_arrives(self):
        sizes = iter([30 * MB, 0])

        def answers(method, ident, params):
            size = next(sizes)
            return [notification(3 * MB),
                    big_result(ident, size) if size else json.dumps({"id": ident, "result": {"queuedSubmissionId": "q"}})]
        params = {"threadId": THREAD, "clientUserMessageId": CLIENT, "input": [{"type": "text", "text": "ok"}]}
        with self.session(answers) as session:
            self.assertEqual(session.call("thread/queue/add", params), {OVERSIZE: True})
            self.assertEqual(session.call("thread/queue/add", params), {"queuedSubmissionId": "q"})
            self.assertEqual(session.drain_events(), [], "an oversize notification is dropped, never queued")

    def test_an_oversize_error_is_codexs_refusal_with_its_code(self):
        sizes = iter([2 * MB, 0])

        def answers(method, ident, params):
            size = next(sizes)
            return [big_error(ident, size, -32602) if size else json.dumps({"id": ident, "result": {}})]
        params = {"threadId": THREAD, "clientUserMessageId": CLIENT, "input": [{"type": "text", "text": "ok"}]}
        with self.session(answers) as session:
            with self.assertRaises(AdapterError) as raised:
                session.call("thread/queue/add", params)
            self.assertEqual((raised.exception.method, raised.exception.code), ("thread/queue/add", -32602))
            self.assertEqual(session.call("thread/queue/add", params), {})

    def test_an_oversize_request_from_codex_is_still_answered_with_its_refusal(self):
        def answers(method, ident, params):
            return ['{"id":"srv-1","method":"item/tool/requestUserInput","params":{"q":"%s"}}' % ("A" * 2 * MB),
                    json.dumps({"id": ident, "result": {}})]
        params = {"threadId": THREAD, "clientUserMessageId": CLIENT, "input": [{"type": "text", "text": "ok"}]}
        with self.session(answers) as session:
            self.assertEqual(session.call("thread/queue/add", params), {})
            self.assertEqual(session.declined_count() + sum(session.refused.values()), 1)


class PictureSendTests(ImagesCase):
    """The prompt queue's picture channel over a real session: Codex queues the message and answers with the pictures
    inline, 30 MB. Fails with the reader reverted: the send ends as unknown ("may have been sent")."""

    def test_an_oversize_add_answer_is_accepted_and_the_message_is_delivered_by_its_client_id(self):
        home = Path(tempfile.mkdtemp(prefix="car-longline-send-")).resolve()
        self.addCleanup(shutil.rmtree, home, True)

        def answers(method, ident, params):
            self.calls.append((method, params))
            self.h.home.enqueue(params["threadId"], params["input"][0]["text"],
                                client_id=params.get("clientUserMessageId"))
            return [notification(3 * MB), big_result(ident, 30 * MB)]
        piped(self, home, answers)
        outcomes, send = [], promptqueue.ImageChannel.send

        def spied(channel, *arguments, **named):
            outcomes.append(send(channel, *arguments, **named))
            return outcomes[-1]
        patcher = patch.object(promptqueue.ImageChannel, "send", spied)
        patcher.start()
        self.addCleanup(patcher.stop)
        plug = self.on()
        code = plug.runtime._code_of(plug.runtime.registry.get(self.cap))
        code._session = lambda: protocol.Session(Backend(home), capability=promptqueue.CAPABILITY)
        prompt = self.queued(plug, [self.picture()])
        self.h.tick(advance=1)
        self.assertEqual([method for method, _params in self.calls], ["thread/queue/add"], "sent once, never again")
        self.assertEqual(outcomes, [{"outcome": "accepted", "queue_id": None}],
                         "accepted, never 'may have been sent'; the client id proves the rest")
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        self.h.tick(advance=2)
        row = plug.runtime.state.prompt(prompt)
        self.assertEqual((row["state"], row["reason"]), (PromptState.DONE, PromptReason.DELIVERED))
        self.assertEqual(len(self.calls), 1, "never added again")


class MimgTests(HomeCase):
    """MIMG over a real session whose add answer is 30 MB: the add was accepted, not uncertain. Fails with the reader
    reverted: add_answer_uncertain true, local_image_accepted false - the 2026-11-08 record."""

    def setUp(self):
        super().setUp()
        for name, value in (("_MC1_QUEUE_SECONDS", 0.05), ("_MC1_START_SECONDS", 0.05), ("_M2B_POLL_SECONDS", 0.01)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_an_oversize_add_answer_is_recorded_as_accepted(self):
        adds, looked_for = [], []

        def answers(method, ident, params):
            if method == "thread/queue/add":
                adds.append(params["clientUserMessageId"])
                return [notification(3 * MB), big_result(ident, 30 * MB)]
            return [json.dumps({"id": ident, "result": {"data": []}})]
        piped(self, self.home, answers)

        def history(ctx, client_id):
            looked_for.append(client_id)
            return True
        with patch.object(measure, "_client_recorded", history), \
                patch.object(measure, "_latest_kinds", lambda ctx: ("inProgress", False, True)):
            summary = measure.run(Measurement.MIMG,
                                  session_factory=lambda measured_one: protocol.Session(Backend(self.home), measured_one),
                                  backend=MeasureBackend(self.home), versions=VERSIONS, thread=THREAD,
                                  clock=lambda: 1_800_000_000.0, directory=self.home)
        record = json.loads(Path(summary["recorded"]).read_text(encoding="utf-8"))
        observed = record["observed"]
        self.assertEqual((observed["add_calls"], observed["local_image_accepted"], observed["add_answer_oversize"]),
                         (1, True, True))
        self.assertNotIn("add_answer_uncertain", observed)
        self.assertNotIn("queued_images", observed, "what the submission holds is not known: no count is made up")
        self.assertEqual(len(adds), 1, "never added again")
        self.assertEqual(looked_for, adds, "proven by its client id in the history")
        self.assertEqual((observed["taken"], observed["client_id_on_user_item"]), (True, True))


if __name__ == "__main__":
    unittest.main()

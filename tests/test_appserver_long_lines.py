"""A line over a megabyte on the App Server's stdout never ends the reader (v0.6.22).

Codex echoes a queued message's pictures inline, so one answer or notification can be tens of megabytes; the reader used
to stop for good at a line over 1 MB, and every later answer was lost (MIMG, 2026-11-08: add_answer_uncertain twice).
Held here against core's finite helper (codex/appserver.Protocol) over real pipes to an app server played in this
process (PipeServer): a 3 MB notification, a 30 MB result, an oversize error and a long line that is no JSON, each
followed by an answer that must still arrive. No real Codex is started.

    PYTHONPATH="src;tests" python -m unittest test_appserver_long_lines
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from codex_auto_resume.codex import appserver
from codex_auto_resume.codex.errors import AdapterError

MB = 1024 * 1024
THREAD = "00000000-0000-7000-8000-000000000001"
QUEUED = "00000000-0000-7000-8000-000000000002"


def notification(size):
    """A thread/queue/changed of about `size` characters, its picture inline as Codex echoes one."""
    return json.dumps({"method": "thread/queue/changed",
                       "params": {"threadId": THREAD, "image": "A" * size}}, separators=(",", ":"))


def big_result(ident, size):
    """An answer {"id": n, "result": ...} of about `size` characters, the id first as Codex writes it."""
    return '{"id":%s,"result":{"queuedSubmission":{"input":[{"type":"image","url":"data:image/png;base64,%s"}]}}}' % (
        json.dumps(ident), "A" * size)


def big_error(ident, size, code=-32600):
    """An error of about `size` characters, {"error": {...}, "id": n} - its id last, as Codex writes it."""
    return '{"error":{"code":%d,"message":"%s"},"id":%s}' % (code, "A" * size, json.dumps(ident))


class PipeServer:
    """`codex app-server --stdio` played in this process over two real pipes, standing in for the Popen a session
    makes: it answers initialize itself and every other request with the lines `answer(method, id, params)` gives,
    written in pieces so the client's reads meet a line split across many."""

    pid = None

    def __init__(self, home, answer):
        self.home, self.answer, self.requests = home, answer, []
        to_server, from_client = os.pipe()
        to_client, from_server = os.pipe()
        self.stdin = io.open(from_client, "w", encoding="utf-8", newline="")
        self._incoming = io.open(to_server, "r", encoding="utf-8")
        self.stdout = io.open(to_client, "r", encoding="utf-8", errors="replace")
        self._outgoing = io.open(from_server, "w", encoding="utf-8", newline="")
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _write(self, line):
        for start in range(0, len(line), 256 * 1024):
            self._outgoing.write(line[start:start + 256 * 1024])
        self._outgoing.write("\n")
        self._outgoing.flush()

    def _serve(self):
        try:
            for line in self._incoming:
                message = json.loads(line)
                method, ident = message.get("method"), message.get("id")
                if method is None or ident is None:
                    continue
                self.requests.append(method)
                if method == "initialize":
                    self._write(json.dumps({"id": ident, "result": {"codexHome": str(self.home),
                                                                    "platformOs": "windows"}}))
                    continue
                for answer in self.answer(method, ident, message.get("params")):
                    self._write(answer)
        except (OSError, ValueError):
            pass
        finally:
            for stream in (self._outgoing, self._incoming):
                try:
                    stream.close()
                except OSError:
                    pass

    def wait(self, timeout=None):
        self.thread.join(timeout)
        return 0

    def terminate(self):
        pass


class Backend:
    """Core's Backend as Protocol uses it: a home of its own and no real Codex."""

    def __init__(self, home):
        self.codex_home = home

    def _compatible(self):
        return {}

    def _argv(self):
        return ["codex"]

    def _environment(self):
        return {}


class LongLineCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="car-longline-")).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)

    def protocol(self, answer):
        servers = []

        def popen(*unused, **ignored):
            servers.append(PipeServer(self.home, answer))
            return servers[0]
        patcher = patch.object(appserver.S, "Popen", popen)
        patcher.start()
        self.addCleanup(patcher.stop)
        return appserver.Protocol(Backend(self.home))


class ReaderTests(LongLineCase):
    """Each fails with the reader reverted: the long line ends it, and the answer after it times out."""

    def test_a_3_mb_notification_is_dropped_and_the_answer_after_it_arrives(self):
        usage = {"rateLimits": {"primary": {"usedPercent": 12}}}
        answers = lambda method, ident, params: [notification(3 * MB), json.dumps({"id": ident, "result": usage})]
        with self.protocol(answers) as client:
            self.assertEqual(client.call("account/rateLimits/read"), usage)

    def test_a_30_mb_result_comes_as_its_id_marked_oversize_and_the_next_answer_still_arrives(self):
        sizes = iter([30 * MB, 0])

        def answers(method, ident, params):
            size = next(sizes)
            return [big_result(ident, size) if size else json.dumps({"id": ident, "result": {"deleted": True}})]
        with self.protocol(answers) as client:
            started = time.monotonic()
            first = client.call("thread/queue/delete", {"threadId": THREAD, "queuedSubmissionId": QUEUED})
            self.assertEqual(first, {appserver.OVERSIZE: True}, "only the mark, never the payload")
            self.assertEqual(client.call("thread/queue/delete", {"threadId": THREAD, "queuedSubmissionId": QUEUED}),
                             {"deleted": True})
            self.assertLess(time.monotonic() - started, 20, "drained in bounded chunks, not quadratic")

    def test_an_oversize_error_is_an_error_for_its_id_and_the_next_answer_still_arrives(self):
        sizes = iter([2 * MB, 0])

        def answers(method, ident, params):
            size = next(sizes)
            return [big_error(ident, size) if size else json.dumps({"id": ident, "result": {"deleted": True}})]
        with self.protocol(answers) as client:
            with self.assertRaises(AdapterError) as raised:
                client.call("thread/queue/delete", {"threadId": THREAD, "queuedSubmissionId": QUEUED})
            self.assertEqual(str(raised.exception), "protocol_request_failed", "Codex's no, not a lost answer")
            self.assertEqual(client.call("thread/queue/delete", {"threadId": THREAD, "queuedSubmissionId": QUEUED}),
                             {"deleted": True})

    def test_a_long_line_that_is_no_json_is_skipped_and_the_reader_goes_on(self):
        answers = lambda method, ident, params: ["x" * (3 * MB), json.dumps({"id": ident, "result": {"deleted": True}})]
        with self.protocol(answers) as client:
            self.assertEqual(client.call("thread/queue/delete", {"threadId": THREAD, "queuedSubmissionId": QUEUED}),
                             {"deleted": True})


class NextMessageTests(unittest.TestCase):
    """The bounded read alone, over an in-memory stream."""

    def read(self, *lines):
        stream = io.TextIOWrapper(io.BytesIO("".join(line + "\n" for line in lines).encode("utf-8")),
                                  encoding="utf-8")
        found = []
        while True:
            value = appserver.next_message(stream)
            if value is None:
                return found
            found.append("skipped" if value is appserver.SKIPPED else value)

    def test_each_kind_of_long_line(self):
        found = self.read(notification(2 * MB), big_result(7, 2 * MB), big_error("s8", 2 * MB, -32602),
                          '{"id":9,"method":"item/tool/requestUserInput","params":{"q":"%s"}}' % ("A" * 2 * MB),
                          "{" * (2 * MB), '{"id":10,"result":{}}')
        self.assertEqual(found, ["skipped", {"id": 7, "result": {appserver.OVERSIZE: True}},
                                 {"id": "s8", "error": {appserver.OVERSIZE: True, "code": -32602}},
                                 {"id": 9, "method": "item/tool/requestUserInput"}, "skipped",
                                 {"id": 10, "result": {}}])

    def test_a_line_up_to_the_limit_is_read_whole_and_short_lines_as_before(self):
        whole = {"id": 1, "result": {"text": "A" * (appserver.LINE_LIMIT - 40)}}
        self.assertEqual(self.read(json.dumps(whole), "[1]", "not json", '{"id":2,"result":3}'),
                         [whole, "skipped", "skipped", {"id": 2, "result": 3}])

    def test_an_id_inside_the_error_is_never_taken_for_the_answers_own(self):
        line = '{"error":{"code":-1,"data":{"id":5},"message":"%s"}}' % ("A" * 2 * MB)
        self.assertEqual(self.read(line, '{"id":3,"result":{}}'), ["skipped", {"id": 3, "result": {}}])

    def test_nothing_of_the_payload_is_logged(self):
        with self.assertLogs(appserver.__name__, "INFO") as logged:
            self.read(notification(2 * MB), "x" * (2 * MB))
        self.assertEqual(logged.output, ["INFO:%s:a notification of 3 MB was not read: thread/queue/changed"
                                         % appserver.__name__,
                                         "INFO:%s:a line of 3 MB was not read: unknown" % appserver.__name__])


if __name__ == "__main__":
    unittest.main()

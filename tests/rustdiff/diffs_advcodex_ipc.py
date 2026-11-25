"""S7.2c remainder: `codex/ipc.py` as the v0.6.26 final has it, held equal to car-adv's `codex::ipc` over car-platform's
`ipc_pipe`.

Never the Codex Desktop's own pipe: every case connects to a scratch pipe of the test's own name, served in this test
process by the advanced tests' own stand-in (`advanced/tests/fakeipc.py`'s FakeApp, which answers as the app does, its
replies changed per case), extended here to send frames of its own before a reply: a client-discovery request (which
the client must answer), another client's response, a frame of no JSON, not an object, not UTF-8, of size 0 or past
FRAME_LIMIT. CAR_NO_REAL_IPC is set, so car-platform refuses the Desktop's name too, and both sides' request ids count
up from 1. One fresh FakeApp per case and side; compared are the word each call ends in, the guard's enter/exit, and
every request the fake saw (method, version, params, target, request id), in order.

Cases: stop (v3, v4 with the running turn and another), start, steer (with and without a message id); the owner
missing or refusing, initialize without a client id or with no object, version mismatch, any other error; the
guard refusing, raising, its exit raising; silence (no_answer, and unconfirmed after the 30 s stop wait); no pipe.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_ipc`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys
import uuid

from rustdiff import advcodex
from rustdiff.advcodexd import AdvCodexRestDiff, ask_reference

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "advanced" / "tests"))
import fakeipc  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-00000000000a"
TURN = "0a1b2c3d-0001-7000-8000-0000000000bb"


class Served(fakeipc.FakeApp):
    """FakeApp with frames of its own before a method's reply (`extras`), each a JSON value or {"raw": hex} written as
    it is, and every request kept whole."""

    def __init__(self, script=None, extras=None, running=None, broadcast_first=True):
        self.extras = dict(extras or {})
        self.requests = []
        super().__init__(script)
        self.running = running
        self.broadcast_first = broadcast_first

    def _frame(self, value):
        if isinstance(value, dict) and "raw" in value:
            data = bytes.fromhex(value["raw"])
        else:
            body = json.dumps(value).encode("utf-8")
            data = struct.pack("<I", len(body)) + body
        count = fakeipc.wintypes.DWORD(0)
        fakeipc._K32.WriteFile(self._handle, data, len(data), fakeipc.ctypes.byref(count), None)

    def _serve(self):
        fakeipc._K32.ConnectNamedPipe(self._handle, None)
        try:
            while True:
                size = struct.unpack("<I", self._read(4))[0]
                request = json.loads(self._read(size).decode("utf-8"))
                method = request.get("method")
                self.requests.append(request)
                if self.broadcast_first:
                    self._write({"type": "broadcast", "method": "thread-stream-state-changed", "params": {}})
                for extra in self.extras.get(method or "", []):
                    self._frame(extra)
                reply = self.script.get(method, self._default(method, request.get("params") or {}))
                if reply is None:
                    continue
                self._write(dict({"type": "response", "requestId": request.get("requestId")}, **reply))
        except Exception:
            return


def raw(body: bytes, size=None) -> dict:
    return {"raw": (struct.pack("<I", len(body) if size is None else size) + body).hex()}


CASES = [
    # (kind, thread, extra, message, gate, script, extras, running)
    ("stop", THREAD, None, None, None, {}, {}, None),
    ("stop", THREAD, TURN, None, None, {}, {}, None),
    ("stop", THREAD, TURN, None, None, {}, {}, "another-turn"),
    ("stop", THREAD, TURN, None, None, {}, {}, TURN),
    ("stop", THREAD, "", None, {"enter": [True]}, {}, {}, None),
    ("stop", THREAD, None, None, {"enter": [False]}, {}, {}, None),
    ("stop", THREAD, None, None, {"enter": ["raise"]}, {}, {}, None),
    ("stop", THREAD, None, None, {"enter": [True], "exit": ["raise"]}, {}, {}, None),
    ("stop", THREAD, None, None, {"enter": [1]}, {}, {}, None),
    ("stop", THREAD, None, None, None, {"thread-owner-discovery": {"resultType": "error", "error": "no-client-found"}}, {}, None),
    ("stop", THREAD, None, None, None, {"thread-owner-discovery": {"resultType": "success"}}, {}, None),
    ("stop", THREAD, None, None, None, {"thread-owner-discovery": {"resultType": "success", "handledByClientId": ""}}, {}, None),
    ("stop", THREAD, None, None, None, {"initialize": {"resultType": "success", "result": {}}}, {}, None),
    ("stop", THREAD, None, None, None, {"initialize": {"resultType": "success", "result": [1]}}, {}, None),
    ("stop", THREAD, None, None, None, {"initialize": {"resultType": "success", "result": {"clientId": 7}}}, {}, None),
    ("stop", THREAD, None, None, None, {"thread-follower-interrupt-turn": {"resultType": "error", "error": "request-version-mismatch"}}, {}, None),
    ("stop", THREAD, None, None, None, {"thread-follower-interrupt-turn": {"resultType": "error", "error": "busy"}}, {}, None),
    ("stop", THREAD, None, None, None, {"thread-follower-interrupt-turn": {"resultType": "success", "result": {"interruptedTurnId": 5}}}, {}, None),
    ("stop", THREAD, None, None, None, {}, {"initialize": [{"type": "client-discovery-request", "requestId": "d1"},
                                                          {"type": "response", "requestId": "other", "resultType": "success"},
                                                          {"type": "response"}]}, None),
    ("stop", THREAD, None, None, None, {}, {"initialize": [raw(b"[1, 2]")]}, None),
    ("stop", THREAD, None, None, None, {}, {"initialize": [raw(b"{not json")]}, None),
    ("stop", THREAD, None, None, None, {}, {"thread-owner-discovery": [raw(b"\xff\xfe{}")]}, None),
    ("stop", THREAD, None, None, None, {}, {"initialize": [raw(b"", 0)]}, None),
    ("stop", THREAD, None, None, None, {}, {"initialize": [raw(b"{}", 8 * 1024 * 1024 + 1)]}, None),
    ("start", THREAD, "go on \u00e9\u4e2d", None, None, {}, {}, None),
    ("start", THREAD, 5, None, {"enter": [True]}, {}, {}, None),
    ("start", THREAD, "x", None, {"enter": ["raise"]}, {}, {}, None),
    ("start", THREAD, "x", None, None, {"thread-follower-start-turn": {"resultType": "error", "error": "no-client-found"}}, {}, None),
    ("start", THREAD, "x", None, None, {}, {"thread-follower-start-turn": [raw(b"{bad")]}, None),
    ("steer", THREAD, "one more line", None, None, {}, {}, None),
    ("steer", THREAD, "one more line", "car-msg-1", {"enter": [True]}, {}, {}, None),
    ("steer", THREAD, "x", None, {"enter": ["raise"]}, {}, {}, None),
    ("steer", THREAD, "x", None, {"enter": [False]}, {}, {}, None),
    ("steer", THREAD, "x", None, None, {}, {"thread-follower-steer-turn": [raw(b"{bad")]}, None),
    ("steer", THREAD, "x", None, None, {"thread-follower-steer-turn": {"resultType": "error", "error": "x"}}, {}, None),
    ("stop", THREAD, None, None, None, {"initialize": None}, {}, None),
    ("steer", THREAD, "x", None, None, {"thread-follower-steer-turn": None}, {}, None),
    ("stop", THREAD, TURN, None, None, {"thread-follower-interrupt-turn": None}, {}, None),
]


class IpcDiff(AdvCodexRestDiff):
    def setUp(self):
        self.held = os.environ.get("CAR_NO_REAL_IPC")
        os.environ["CAR_NO_REAL_IPC"] = "1"

    def tearDown(self):
        if self.held is None:
            os.environ.pop("CAR_NO_REAL_IPC", None)

    def test_shapes(self):
        fields = {"thread": THREAD, "turn": None, "message": "m", "text": {"x": [1]}, "other": 5}
        cases = []
        for method in ("initialize", "thread-owner-discovery", "thread-follower-interrupt-turn",
                       "thread-follower-start-turn", "thread-follower-steer-turn"):
            cases += [["ip.filled", method, False, fields], ["ip.filled", method, False, {}],
                      ["ip.version", method, False]]
        cases += [["ip.filled", "thread-follower-interrupt-turn", True, fields],
                  ["ip.version", "thread-follower-interrupt-turn", True]]
        self.same("shapes", cases)

    def test_calls(self):
        profile = self.fresh("ipc")
        seen = []
        for ask in (ask_reference, advcodex.ask_rust):
            apps, cases = [], []
            for kind, thread, extra, message, gate, script, extras, running in CASES:
                app = Served(script, extras, running)
                apps.append(app)
                cases.append(["ip.run", kind, app.name, thread, extra, message, gate])
            cases.append(["ip.run", "stop", r"\\.\pipe\car-test-ipc-missing-%s" % uuid.uuid4().hex, THREAD, None, None,
                          None])
            answers = ask({"world": {}, "cases": cases}, profile)
            seen.append((answers, [[{key: value for key, value in request.items()} for request in app.requests]
                                   for app in apps]))
            for app in apps:
                app.close()
        (want, want_seen), (got, got_seen) = seen
        self.compare("calls", [case[:2] + case[3:] for case in cases], want, got)
        for index, (one, other) in enumerate(zip(want_seen, got_seen)):
            self.assertEqual(one, other, "case %d: the app was asked otherwise" % index)
        words = [one["ok"]["word"] for one in want]
        for word in ("stopped", "not_stopped", "no_client", "version_mismatch", "no_pipe", "no_answer", "unconfirmed",
                     "refused", "broken", "held", "started", "steered"):
            self.assertIn(word, words)

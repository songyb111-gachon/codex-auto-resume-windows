"""S7.2c remainder: `codex/protocol.py`'s `Session` and `submitted` as the v0.6.26 final has them, held equal to
car-adv's `codex::session`.

Each case opens one session (for a measurement or a capability, with and without `-c` settings) on its own fake engine:
car-fake-codex (car-harness's dev-only stand-in) copied into the scratch LOCALAPPDATA's Codex bin folder, answering
`--version`, `queue --help` and the app server from its script. Codex's side is scripted per method: results, errors
(with an int, a bool, a missing code), answers with a float id or after another call's id, requests Codex makes of the
client (every approval, input and elicitation kind, auth and attestation, one unknown) and notifications before an
answer, lines that are no JSON; and `initialize` answering another home, no home, a home of no text, no object, an error.
Steps: call, submit/receive (a short wait that runs out), submitted and its answer later, events drained, the declined
count; a method the session may not call; thread/resume subscribing so the exit unsubscribes. Compared: every answer
and refusal, the counts by method, and every byte the engine was sent (CRLF and the refusals the reader wrote
included) with its arguments.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_session` (the fake from
`cargo build -p car-harness --bin car-fake-codex`; CODEX_AR_FAKE_CODEX names another build).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from rustdiff import advcodex
from rustdiff.advcodexd import AdvCodexRestDiff, ask_reference

ROOT = Path(__file__).resolve().parents[2]
THREAD = "0a1b2c3d-0001-7000-8000-00000000000a"
TURN = "0a1b2c3d-0001-7000-8000-0000000000bb"
HELP = "Usage: codex queue [OPTIONS]\n\n  --thread <ID>     the conversation\n  --message <TEXT>  what to send\n"
INIT = [{"result": {"codexHome": "{home}", "platformOs": "windows", "userAgent": "codex_cli_rs/0.171.0"}}]
OK = [{"result": {}}]
REQUESTS = ["item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval",
            "execCommandApproval", "applyPatchApproval", "item/tool/requestUserInput", "mcpServer/elicitation/request",
            "account/chatgptAuthTokens/refresh", "attestation/generate", "item/tool/call", "made/up"]


def fake_binary() -> Path:
    named = os.environ.get("CODEX_AR_FAKE_CODEX")
    if named:
        return Path(named)
    for kind in ("release", "debug"):
        found = ROOT / "rust" / "target" / kind / "car-fake-codex.exe"
        if found.is_file():
            return found
    raise AssertionError("build car-fake-codex first: cargo build -p car-harness --bin car-fake-codex")


def raw_request(number: int, method: str, params=None) -> str:
    return json.dumps({"id": number, "method": method, "params": params if params is not None else {}}) + "\n"


def server(**answers) -> dict:
    found = {"initialize": [INIT], "thread/unsubscribe": [OK]}
    found.update({key.replace("__", "/"): value for key, value in answers.items()})
    return {"version": {"stdout": "codex-cli 0.171.0\n", "code": 0}, "help": {"stdout": HELP, "code": 0},
            "server": {"answers": found}}


def with_lines(lines: str, result) -> list:
    return [[{"raw": lines + json.dumps({"id": 0, "result": result}).replace('"id": 0', '"id": {id}') + "\n"}]]


# The home with a part that resolves away: `{home}\sub\..` as JSON text.
SUBHOME = '{"id": {id}, "result": {"codexHome": "{home}' + r'\\sub\\..' + '"}}' + "\n"

CASES = [
    # (measurement, capability, config, script, steps)
    ("m1", None, [], server(thread__loaded__list=[[{"result": {"data": [THREAD]}}]]),
     [["call", "thread/loaded/list", None], ["call", "turn/start", {}], ["declined"], ["events"]]),
    (None, "headless_run", [["windows.sandbox", '"mxc"'], ["features.prefer_mxc", "true"]],
     server(thread__resume=[[{"result": {"thread": {"id": THREAD}, "model": "gpt-5"}}]],
            turn__start=[[{"result": {"turn": {"id": TURN, "status": "inProgress"}}}]]),
     [["call", "thread/resume", {"threadId": THREAD, "excludeTurns": True}],
      ["call", "turn/start", {"threadId": THREAD, "input": [{"type": "text", "text": "go on \u00e9\u4e2d"}]}],
      ["call", "account/login", {}], ["call", "model/list", {}]]),
    (None, "headless_run", [],
     server(thread__resume=with_lines("".join(raw_request(900 + i, m, {"threadId": THREAD}) for i, m in enumerate(REQUESTS))
                                      + '{"method": "turn/started", "params": {"threadId": "%s"}}\n' % THREAD
                                      + "not json at all\n[1, 2]\n", {"model": "m"})),
     [["call", "thread/resume", {"threadId": THREAD}], ["declined"], ["events"], ["events"]]),
    (None, "headless_run", [],
     server(turn__start=[[{"error": {"code": -32600, "message": "empty"}}], [{"error": {"code": True}}],
                         [{"error": "flat"}], [{"error": {"message": "no code"}}],
                         [{"raw": '{"id": {id}.0, "result": {"turn": {"id": "x"}}}\n'}]]),
     [["call", "turn/start", {"threadId": THREAD, "input": []}], ["call", "turn/start", None],
      ["call", "turn/start", None], ["call", "turn/start", None], ["call", "turn/start", None]]),
    (None, "headless_run", [],
     server(turn__interrupt=[[{"raw": '{"id": 999, "result": "stale"}\n{"id": {id}, "result": null}\n'}]],
            thread__resume=[OK]),
     [["submitted", "turn/interrupt", {"threadId": THREAD, "turnId": TURN}], ["submitted", "account/logout", None],
      ["answer", 1], ["answer", 0], ["submit", "thread/resume", {"threadId": THREAD}], ["receive", "thread/resume", 2, None, 5]]),
    (None, "headless_run", [],
     server(turn__interrupt=[[{"sleep": 0.05}]], thread__resume=[OK]),
     [["submit", "turn/interrupt", {"threadId": THREAD}], ["receive", "turn/interrupt", 1, None, 0.4],
      ["call", "thread/resume", {"threadId": THREAD}], ["call", "thread/resume", {"threadId": ""}],
      ["call", "thread/resume", {"threadId": 0}], ["call", "thread/unsubscribe", {"threadId": THREAD}]]),
    (None, "marker_free_continuation", [], server(thread__queue__add=[[{"result": {"id": "q1"}}]]),
     [["call", "thread/queue/add", {"threadId": THREAD, "message": "x"}], ["call", "thread/resume", {"threadId": THREAD}]]),
    (None, "nothing", [], server(), [["call", "thread/resume", {"threadId": THREAD}], ["call", "initialize", {}]]),
    ("m6b", "headless_run", [], server(), []),
    (None, None, [], server(), []),
    ("not-a-measurement", None, [], server(), []),
    (None, "headless_run", [], dict(server(), server={"answers": {"initialize": [[{"result": {"codexHome": "C:\\elsewhere"}}]]}}), []),
    (None, "headless_run", [], dict(server(), server={"answers": {"initialize": [[{"result": {"platformOs": "windows"}}]]}}), []),
    (None, "headless_run", [], dict(server(), server={"answers": {"initialize": [[{"result": {"codexHome": 5}}]]}}), []),
    (None, "headless_run", [], dict(server(), server={"answers": {"initialize": [[{"result": [1]}]]}}), []),
    (None, "headless_run", [], dict(server(), server={"answers": {"initialize": [[{"error": {"code": -1}}]]}}), []),
    (None, "headless_run", [], dict(server(), version={"stdout": "", "code": 3}), []),
    (None, "headless_run", [], dict(server(), help={"stdout": "nothing here\n", "code": 0}), []),
    (None, "headless_run", [],
     dict(server(), server={"answers": {"initialize": [[{"raw": SUBHOME}]]}}), []),
    ("m3", None, [], server(thread__queue__add=[[{"result": {"id": "q"}}]], thread__resume=[OK]),
     [["call", "thread/resume", {"threadId": THREAD}], ["call", "thread/resume", {"threadId": THREAD.upper()}],
      ["call", "thread/queue/add", {"threadId": THREAD, "message": "x"}], ["call", "turn/start", {}]]),
]


class SessionDiff(AdvCodexRestDiff):
    def test_sessions(self):
        profile = self.fresh("session")
        engines, cases = [], []
        for index, (measurement, capability, config, script, steps) in enumerate(CASES):
            folder = profile / "OpenAI" / "Codex" / "bin" / ("a%03x" % index)
            folder.mkdir(parents=True)
            shutil.copy2(fake_binary(), folder / "codex.exe")
            (folder / "fake.json").write_text(json.dumps(script), encoding="utf-8")
            engines.append(folder)
            cases.append(["ss.run", str(folder / "codex.exe"), measurement, capability, config, steps])

        def taken():
            found = []
            for folder in engines:
                log, stdin = folder / "fake.log.jsonl", folder / "stdin.bin"
                found.append({"log": log.read_text(encoding="utf-8").splitlines() if log.exists() else [],
                              "stdin": stdin.read_bytes().hex() if stdin.exists() else ""})
                log.unlink(missing_ok=True)
                stdin.unlink(missing_ok=True)
            return found

        request = {"world": {}, "cases": cases}
        want = ask_reference(request, profile)
        want_sent = taken()
        got = advcodex.ask_rust(request, profile)
        got_sent = taken()
        self.compare("sessions", cases, want, got)
        for index, (one, other) in enumerate(zip(want_sent, got_sent)):
            self.assertEqual(one, other, "case %d: the engine was sent otherwise" % index)
        self.assertTrue(any(sent["stdin"] for sent in want_sent))

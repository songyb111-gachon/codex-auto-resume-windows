"""S3.3: car-codex's transport and App Server helper held to the reference (`codex/transport.py`, `codex/appserver.py`)
over real processes - `car-fake-codex` copies in a scratch bin folder, started by both sides with no window.

Every request either side writes to the helper is compared byte for byte (the bytes the fake engine kept, CRLF
included), with every argument list it was started with, its working folder and the two variables the backend sets.
The engine checks (`--version` and `queue --help` answering, failing, missing a flag, offering `--remote`, timing
out), the usage read and the queue delete through the helper (good answers, an answer this version cannot read,
Codex's method-not-found and serde's "unknown variant", a refusal, another home, another system, a home that is no
text, server requests, notifications, junk, other calls' ids, an oversize answer, a helper that exits or never answers
or will not end), the sends (every receipt, exit codes, the launch guard's answers, the daemon route, every preflight
refusal), and the pairing's use (app_identity, loaded, holder) on stand-in rows. The time a call takes is compared as
the wait it is (none, the 4 s end, the 25 s call), not to the millisecond.
"""
from __future__ import annotations

import json
from pathlib import Path

from rustdiff.appserverdiff import AppBase, Fake, facts, op

RECORD: list[str] = []
THREAD = "0a1b2c3d-0001-7000-8000-00000000000a"
QUEUED = "0a1b2c3d-0001-7000-8000-0000000000ff"
HELP = "Usage: codex queue [OPTIONS]\n\n  --thread <ID>     the conversation\n  --message <TEXT>  what to send\n"
HELP_REMOTE = HELP + "  --remote <ADDR>   a daemon\n"
VERSION = {"stdout": "codex-cli 0.171.0\n", "code": 0}
INIT = [{"result": {"codexHome": "{home}", "platformOs": "windows", "userAgent": "codex_cli_rs/0.171.0"}}]
USAGE = {"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 40, "windowDurationMins": 300,
                                                       "resetsAt": 1764000000}, "rateLimitReachedType": None}}}
NATIVE = r"C:\Program Files"
APP = NATIVE + r"\WindowsApps\OpenAI.Codex_26.1117.4957.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"
FAMILY = "OpenAI.Codex_2p2nqsd0c76g0"


def script(**parts):
    base = {"version": VERSION, "help": {"stdout": HELP, "code": 0},
            "queue": {"stdout": "Queued message %s for thread {thread}.\n" % QUEUED, "code": 0},
            "server": {"answers": {"initialize": [INIT]}}}
    for key, value in parts.items():
        base[key] = value
    return base


def server(**answers):
    found = {"initialize": [INIT]}
    found.update({key.replace("__", "/"): value for key, value in answers.items()})
    return found


def bucket(seconds: float) -> str:
    return "none" if seconds < 2 else "end wait" if seconds < 15 else "call wait" if seconds < 40 else "longer"


def timed(operation, answer):
    if operation["op"] == "backend.usage" and isinstance(answer.get("ok"), dict):
        return {"ok": dict(answer["ok"], seconds=bucket(answer["ok"]["seconds"]))}
    return answer


class TransportDiff(AppBase):
    def setUp(self):
        super().setUp()
        self.facts = facts()
        self.number = 0

    def case(self, fake_script, ops, *, world=None, hexname="c0de", place="bin"):
        """A case of its own: a LOCALAPPDATA with the fake engine, a Codex home, and `backend.new` first."""
        self.number += 1
        root = self.scratch / ("case-%d" % self.number)
        root.mkdir(parents=True)
        root = root.resolve()
        local, home = root / "local", root / "codex-home"
        home.mkdir(parents=True)
        fake = Fake(local, fake_script, hexname)
        if place != "bin":
            moved = root / "elsewhere" / "codex.exe"
            moved.parent.mkdir(parents=True)
            fake.exe.replace(moved)
            (fake.folder / "fake.json").replace(moved.parent / "fake.json")
            fake.folder, fake.exe = moved.parent, moved
        env = {"LOCALAPPDATA": str(local), "ProgramW6432": NATIVE, "USERPROFILE": str(root / "profile")}
        state = {"env": env, "pid": 4242, "clock": 2000.0}
        state.update(world(fake, home) if callable(world) else world or {})
        head = [op("backend.new", str(home), str(fake.exe), False, self.facts["version"], self.facts["bundled"])]
        return {"world": state, "ops": head + ops(fake, home) if callable(ops) else head + ops}, fake

    def run_cases(self, made, label):
        cases = [case for case, _ in made]
        fakes = [fake for _, fake in made]
        return self.script(cases, label, chunk=12, fakes=fakes, compare=timed)

    def test_engine_checks(self):
        tail = [op("backend.engine_checks"), op("backend.engine_checks"), op("backend.compatible"), op("backend.state")]
        variants = [
            script(), script(version={"stdout": "codex-cli 0.171.0\n", "code": 1}),
            script(help={"stdout": HELP, "code": 2}), script(help={"stdout": "Usage: --thread only\n", "code": 0}),
            script(help={"stdout": HELP_REMOTE, "code": 0}),
            script(help={"stdout": HELP.replace("--message", "--messages"), "code": 0}),
            script(version={"stdout": "  codex-cli 0.171.0-alpha.3\r\n\r\n", "code": 0}),
            script(version={"stdout_hex": "636f6465782d636c6920ff302e3137310d0a", "code": 0}),
            script(version={"stdout": "", "code": 0}), script(version={"stdout": "x" * 200, "code": 0}),
            script(help={"stdout_hex": "2d2d7468726561640d0a2d2d6d657373616765ff", "code": 0}),
            script(help={"stdout": HELP, "code": 0, "sleep": 0.2}),
        ]
        made = [self.case(each, tail) for each in variants]
        made.append(self.case(script(), tail, place="elsewhere"))
        made.append(self.case(script(), tail, place="elsewhere",
                              world=lambda fake, home: {"signers": {str(fake.exe).lower(): "OpenAI OpCo, LLC"}}))
        made.append(self.case(script(), tail, place="elsewhere",
                              world=lambda fake, home: {"signers": {str(fake.exe).lower(): {"raise": "signature_untrusted"}}}))
        made.append(self.case(script(version={"stdout": "codex-cli 0.171.0\n", "code": 0, "sleep": 11}), tail))
        count, calls = self.run_cases(made, "engine checks")
        RECORD.append("transport: engine checks over %d fake engines (%d calls), every argument list equal" % (count, calls))

    def test_usage_and_delete(self):
        later = [op("backend.state"), op("results"), op("said")]
        usage = [op("backend.usage")] + later
        delete = [op("backend.delete_queue", THREAD, QUEUED)] + later
        big = {"big": {"head": '{"id": {id}, "result": {"x": "', "fill": "Z", "count": 1024 * 1024 * 2,
                       "tail": '"}}'}}
        variants = [
            (server(account__rateLimits__read=[[{"result": USAGE}]]), usage),
            (server(account__rateLimits__read=[[{"result": {"rateLimits": {"primary": {"usedPercent": 12}}}}]]), usage),
            (server(account__rateLimits__read=[[{"result": {"unknown": True}}]]), usage),
            (server(account__rateLimits__read=[[{"result": None}]]), usage),
            (server(account__rateLimits__read=[[{"error": {"code": -32601, "message": "Method not found"}}]]), usage),
            (server(account__rateLimits__read=[[{"error": {"code": -32600, "message":
                "Invalid request: unknown variant `account/rateLimits/read`, expected one of `initialize`"}}]]), usage),
            (server(account__rateLimits__read=[[{"error": {"code": -32600, "message": "unknown variant `other`"}}]]), usage),
            (server(account__rateLimits__read=[[{"error": {"code": -32000, "message": "not signed in"}}]]), usage),
            ({"initialize": [[{"result": {"codexHome": "C:\\elsewhere", "platformOs": "windows"}}]]}, usage),
            ({"initialize": [[{"result": {"codexHome": 5, "platformOs": "windows"}}]]}, usage),
            ({"initialize": [[{"result": {"platformOs": "windows"}}]]}, usage),
            ({"initialize": [[{"result": {"codexHome": "{home}", "platformOs": "linux"}}]]}, usage),
            ({"initialize": [[{"result": ["{home}"]}]]}, usage),
            ({"initialize": [[{"error": {"code": -32601, "message": "no"}}]]}, usage),
            (server(account__rateLimits__read=[[
                {"raw": '{"id": 77, "method": "item/tool/call", "params": {}}\n'},
                {"raw": '{"method": "thread/started", "params": {}}\n'}, {"raw": "not json at all\n"},
                {"raw": '{"id": 99, "result": {}}\n'}, {"raw": '{"id": "2", "result": {}}\n'},
                {"raw": '{"id": 2.0, "result": %s}\n' % json.dumps(USAGE)}]]), usage),
            (server(account__rateLimits__read=[[big, {"result": USAGE}]]), usage),
            (server(account__rateLimits__read=[[{"raw": "{\"id\": {id}, \"result\": " + json.dumps(USAGE)
                                                 + "}\r\n"}]]), usage),
            (server(thread__queue__delete=[[{"result": {"deleted": True}}]]), delete),
            (server(thread__queue__delete=[[{"result": {"deleted": 1}}]]), delete),
            (server(thread__queue__delete=[[{"result": {"deleted": False}}]]), delete),
            (server(thread__queue__delete=[[{"result": []}]]), delete),
            (server(thread__queue__delete=[[{"error": {"code": -32601, "message": "gone"}}]]), delete),
            (server(), [op("backend.delete_queue", "not-a-uuid", QUEUED)] + later),
            (server(), [op("backend.delete_queue", THREAD, THREAD.upper())] + later),
            (server(account__rateLimits__read=[[{"result": USAGE}]]),
             [op("backend.usage"), op("backend.usage"), op("backend.delete_queue", THREAD, QUEUED)] + later),
        ]
        made = [self.case(script(server={"answers": answers}), ops) for answers, ops in variants]
        # the slow ones: a helper that exits at once, one that never answers, one that will not end when told
        made.append(self.case(script(server={"answers": server(account__rateLimits__read=[[{"exit": 3}]])}), usage))
        made.append(self.case(script(server={"answers": server(account__rateLimits__read=[[]])}), usage))
        made.append(self.case(script(server={"answers": server(account__rateLimits__read=[[{"result": USAGE}]]),
                                             "on_close": "hang"}), usage))
        made.append(self.case(script(server={"answers": {"initialize": [[{"raw": '{"id": 1, "result": "' +
                                                                         "[" * 10 + '"}\n'}]]}}), usage))
        count, calls = self.run_cases(made, "usage and delete")
        RECORD.append("appserver: usage and queue delete through %d fake helpers (%d calls), every request byte equal"
                      % (count, calls))

    def test_sends(self):
        later = [op("backend.state"), op("results")]
        prompts = ["keep going", "- keep going", "---", 'say "hi" \\ there\\', "é 日本 \U0001f600", "a b\tc",
                   "x" * 30000, "x" * 30001, "", "nul\0here", 5, None, '"' * 20000, "\\" * 100 + '"']
        made = []
        for prompt in prompts:
            made.append(self.case(script(), [op("backend.send", THREAD, prompt, None)] + later))
        receipts = [
            ("Queued message %s for thread {thread}.\n" % QUEUED, 0), ("Queued message %s for thread {thread}." % QUEUED, 1),
            ("Queued message %s for thread {thread}.\n" % QUEUED, 300), ("", 0), ("  \r\n", 0), ("something else\n", 0),
            ("Queued message %s for thread {thread}.\n" % QUEUED.upper(), 0),
            ("Queued message %s for thread {thread}.\n" % ("-" * 36), 0),
            ("\r\n  Queued message %s for thread {thread}.  \r\n" % QUEUED, 0),
            ("Queued message %s for thread %s.\n" % (QUEUED, QUEUED), 0), ("", 255), ("", 4294967295),
        ]
        for stdout, code in receipts:
            made.append(self.case(script(queue={"stdout": stdout, "code": code}),
                                  [op("backend.send", THREAD, "keep going", None)] + later))
        for guard in ({"enter": True}, {"enter": False}, {"enter": 1}, {"enter": "raise"}, {"enter": True, "exit": "raise"},
                      {"enter": False, "exit": "raise"}):
            made.append(self.case(script(), [op("backend.send", THREAD, "keep going", guard)] + later))
        made.append(self.case(script(), [op("backend.send", "not-a-uuid", "keep going", None)] + later))
        # the daemon route: --remote offered, and a daemon of this home in the process list (or none, or no list)
        def daemon(fake, home, *, raised=False, pid=31):
            path = str(home / "packages" / "app-server-daemon" / "releases" / "1.2.3" / "bin" / "codex.exe")
            rows = {"raise": "process_inventory_unavailable"} if raised else [
                {"pid": pid, "parent": 5, "path": path, "created": 3, "family": None},
                {"pid": 32, "parent": 5, "path": path.upper().replace("CODEX.EXE", "x\\codex.exe"), "created": 3}]
            return {"processes": rows}
        for world in (lambda f, h: daemon(f, h), lambda f, h: daemon(f, h, raised=True), lambda f, h: daemon(f, h, pid=0),
                      lambda f, h: {"processes": []}):
            made.append(self.case(script(help={"stdout": HELP_REMOTE, "code": 0}),
                                  [op("backend.queue_daemon_remote"), op("backend.send", THREAD, "keep going", None)]
                                  + later, world=world))
        made.append(self.case(script(queue={"stdout": "x", "code": 0}, help={"stdout": HELP, "code": 3}),
                              [op("backend.send", THREAD, "keep going", None)] + later))
        count, calls = self.run_cases(made, "sends")
        RECORD.append("transport: %d sends (receipts, exit codes, guards, the daemon route, preflight), every "
                      "argument list equal" % count)

    def test_pairing_in_use(self):
        """app_identity, loaded and holder on stand-in rows around the fake engine: the app's server paired or not,
        another session, our own, a named engine, the lock folder there or gone."""
        made = []

        def rows_for(fake, home, layout):
            engine = str(fake.exe)
            main = {"pid": 10, "parent": 1, "path": APP, "created": 100, "family": FAMILY}
            helper = {"pid": 11, "parent": 10, "path": APP, "created": 110, "family": FAMILY}
            server_row = {"pid": 20, "parent": 11 if layout == "helper" else 10, "path": engine, "created": 200}
            tui = {"pid": 31, "parent": 30, "path": engine, "created": 310}
            other = {"pid": 21, "parent": 10, "path": engine.replace("c0de", "beef"), "created": 210}
            rows = {"single": [main, server_row], "helper": [main, helper, server_row],
                    "tui": [main, server_row, tui], "closed": [tui], "other": [main, other],
                    "none": [main]}[layout]
            listed = [{"pid": row["pid"], "path": row["path"].lower(), "created": row["created"]} for row in rows]
            return {"processes": rows, "identities": listed}

        identity = {"pid": 10, "path": APP.lower(), "created": 100,
                    "server": {"pid": 20, "path": None, "created": 200}}
        for layout in ("single", "helper", "tui", "closed", "other", "none"):
            for lock in ("holder", "tui", "ours", "none", "two", "gone"):
                def world(fake, home, layout=layout, lock=lock):
                    found = rows_for(fake, home, layout)
                    users = {"holder": [{"pid": 20, "created": 200}], "tui": [{"pid": 31, "created": 310}],
                             "ours": [{"pid": 20, "created": 999}], "none": [],
                             "two": [{"pid": 20, "created": 200}, {"pid": 31, "created": 310}], "gone": []}[lock]
                    if lock != "gone":
                        (home / "thread-writer-locks").mkdir(exist_ok=True)
                        (home / "thread-writer-locks" / (THREAD + ".lock")).write_bytes(b"")
                    for name in ("state_5.sqlite", "queue_1.sqlite"):
                        (home / name).write_bytes(b"")
                    found["holders"] = {(THREAD + ".lock"): users, "state_5.sqlite": [{"pid": 20, "created": 200}]}
                    return found

                def ops(fake, home):
                    server = dict(identity["server"], path=str(fake.exe).lower())
                    good = dict(identity, server=server)
                    return [op("backend.app_identity"), op("backend.state"), op("backend.loaded", THREAD, good),
                            op("backend.loaded", THREAD, dict(good, created=101)), op("backend.loaded", THREAD, None),
                            op("backend.loaded", "bad", good), op("backend.holder", THREAD),
                            op("own_server", 20), op("backend.holder", THREAD), op("backend.set", {"named_engine": True}),
                            op("backend.app_identity"), op("backend.state"),
                            op("registry.engine_from_backend"), op("registry.server_check")]
                made.append(self.case(script(), ops, world=world))
        count, calls = self.run_cases(made, "pairing in use")
        RECORD.append("transport: app_identity, loaded and holder over %d layouts and locks, %d calls equal" % (count, calls))

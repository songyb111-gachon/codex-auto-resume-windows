"""S7.2e2: window_anchor's code (`engine/anchor.py` `WindowAnchor`, P8) and config.toml's reader, as the v0.6.26 final
has them, held equal to car-adv's `engine::anchor`.

`declared_servers` and `config_unreadable` over generated config.toml files (tables, dotted keys, inline tables, arrays
of tables, every string form and escape, numbers, dates and times valid and not, redefinitions, BOMs, bytes that are
not UTF-8, CRLF and a bare CR) - tomllib's every acceptance and refusal. Then the capability over a scratch home's real
state: its stamps (a reset seen gone by, a time picked now, a start an hour ago, an account changed), its ceiling of
starts a day, the view's settings (on, paused, observe only), a scripted usage session (account/read and
account/rateLimits/read: idle windows whose reset moves with the clock, running, weekly full, no answer), the guard
(permitted or not) and the request itself - a child the test starts, a Python one-liner printing what the case says
(`thread.started`, `turn.completed` with token counts, a refusal of the switch on stderr, an exit code), its argument
list written down by the child and compared. A walk ticks, runs the errand and moves the clock through the two reads,
the start, the settling and the verifying reads; held occasions, their retries and their spans' ends. Compared: every
answer, call, log line, row and file.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_anchor_code`.
"""
from __future__ import annotations

import json
import random
import sys
import time
import unittest

from rustdiff import advtime

CAPABILITY = "window_anchor"
NOW = advtime.NOW
CHILD = ("import json,os,sys;open(os.environ['ADVTIME_ARGV'],'a',encoding='utf-8').write(json.dumps(sys.argv[1:])+chr(10));"
         "sys.stdout.write(open(os.environ['ADVTIME_OUT'],encoding='utf-8').read());"
         "sys.stderr.write(open(os.environ['ADVTIME_ERR'],encoding='utf-8').read());sys.exit(int(os.environ['ADVTIME_CODE']))")

TOML_PARTS = [
    '[mcp_servers.alpha]\ncommand = "npx"\n', '[mcp_servers.beta]\nurl = "http://x"\n', '[mcp_servers.gamma]\nenv = {}\n',
    '[mcp_servers."a.b"]\ncommand = "x"\n', 'mcp_servers.delta.command = "y"\n', 'mcp_servers = { e = { url = "u" } }\n',
    '[[mcp_servers]]\ncommand = "z"\n', 'model = "gpt"\n', '# comment\n', 'x = 1_000\ny = 0x1F\nz = 1e3\nw = inf\n',
    'd = 1979-05-27T07:32:00Z\n', 'd2 = 1979-02-30\n', 't = 07:32:00\n', "s = 'lit'\nm = '''\nmulti'''\n",
    's2 = "esc \\u00e9 \\t"\n', 's3 = "bad \\q"\n', 'a = [1, 2, [3], ]\n', 'a2 = [\n # c\n 1,\n]\n', 'b = true\nb2 = false\n',
    '[t1]\n[t1]\n', 'k = 1\nk = 2\n', 'inl = {a = 1, b = 2}\ninl.c = 3\n', '[x.y]\n[x]\nz = 1\n', 'q = "unterminated\n',
    'p = """\nml \\\n  cont"""\n', '[tbl]\nsub.k = 1\n[tbl.sub]\n', 'n = -0.0\nn2 = +inf\nn3 = nan\n', 'bad key = 1\n',
    "'quoted key' = 1\n", 'e = ""\n', 'num = 01\n', 'off = 1979-05-27T00:32:00-07:00\n', 'ld = 1979-05-27 07:32:00\n',
    'u = "\\U0001F600"\n', 'sur = "\\uD800"\n', '[mcp_servers]\nalpha = 1\n', 'mcp_servers.zeta = { command = "c" }\n',
]


def toml_text(rng: random.Random):
    text = "".join(rng.choice(TOML_PARTS) for _ in range(rng.randint(0, 5)))
    pick = rng.random()
    if pick < 0.1:
        return {"hex": ("\ufeff" + text).encode("utf-8").hex()}
    if pick < 0.15:
        return {"hex": (text.encode("utf-8") + b"\xff").hex()}
    if pick < 0.25:
        return {"hex": text.replace("\n", "\r\n").encode("utf-8").hex()}
    if pick < 0.28:
        return {"hex": text.replace("\n", "\r").encode("utf-8").hex()}
    return text


def limits(used: float, reset: int, week: float = 40.0, week_reset: int | None = None) -> dict:
    return {"rateLimitsByLimitId": {"codex": {
        "primary": {"usedPercent": used, "windowDurationMins": 300, "resetsAt": reset},
        "secondary": {"usedPercent": week, "windowDurationMins": 10080,
                      "resetsAt": week_reset if week_reset is not None else int(NOW) + 500000}}}}


def child_out(rng: random.Random) -> tuple:
    lines = []
    if rng.random() < 0.85:
        lines.append(json.dumps({"type": "thread.started", "thread_id": "t"}))
    if rng.random() < 0.8:
        lines.append(json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": rng.choice([24000, 0, 5]), "cached_input_tokens": 12000, "output_tokens": rng.choice([5, 0])}}))
    err = rng.choice(["", "", "Error: Unknown feature flag apps", "Error loading config.toml: invalid transport", "x"])
    return "\n".join(lines), err


class AnchorTomlDiff(unittest.TestCase):
    def test_toml(self):
        rng = random.Random(7271)
        cases = [{"op": "an.toml", "files": {"codex/config.toml": toml_text(rng)}, "dump": False} for _ in range(900)]
        cases += [{"op": "an.toml", "files": {"codex/config.toml": part}, "dump": False} for part in TOML_PARTS]
        cases.append({"op": "an.toml", "dump": False})
        cases.append({"op": "an.toml", "files": {"codex/config.toml": {"dir": True}}, "dump": False})
        found = advtime.Scene(self, "toml").run(cases)
        unreadable = sum(1 for each in found if (each["result"].get("ok") or {}).get("unreadable"))
        servers = sum(1 for each in found if (each["result"].get("ok") or {}).get("servers"))
        self.assertGreater(unreadable, 50)
        self.assertGreater(servers, 50)


class AnchorCodeDiff(unittest.TestCase):
    def slot_value(self) -> int:
        moment = time.localtime(int(NOW))
        return moment.tm_hour * 60 + moment.tm_min + 2

    def walk(self, rng: random.Random) -> dict:
        setup = []
        generation = 0
        if rng.random() < 0.4:
            setup.append(["set_option", [CAPABILITY, "anchor_at_1", self.slot_value() - rng.choice([0, 0, 10, 40])],
                          {"generation": generation, "actor": "dashboard"}])
            generation += 1
        if rng.random() < 0.15:
            setup.append(["set_option", [CAPABILITY, "anchor_after_reset", 2], {"generation": generation,
                                                                                 "actor": "dashboard"}])
        if rng.random() < 0.7:
            setup.append(["stamp", [CAPABILITY, "anchor_seen_reset", int(NOW) - rng.choice([30, 120, 3000, 20000])], {}])
        if rng.random() < 0.15:
            setup.append(["stamp", [CAPABILITY, "anchor_started_at", int(NOW) - rng.choice([600, 20000])], {}])
        for _ in range(rng.choice([0, 0, 0, 5])):
            setup.append(["counted", [CAPABILITY, "started"], {}])
        if rng.random() < 0.1:
            setup.append(["stamp", ["account_switch", "account_changed_at", int(NOW) - 50], {}])
        steps, now = [], NOW
        reads = []
        for _ in range(rng.randint(3, 14)):
            pick = rng.random()
            if pick < 0.55:
                steps += [["tick"], ["run"]]
            elif pick < 0.8:
                now += rng.choice([5, 20, 25, 30, 300, 301, 1801, 18001])
                steps.append(["clock", now])
            elif pick < 0.86:
                steps.append(["on", rng.random() < 0.8])
            elif pick < 0.9:
                steps.append(["armed", rng.choice([[CAPABILITY], [CAPABILITY, "account_switch"]])])
            else:
                steps.append(["tick"])
        at = NOW
        for _ in range(rng.randint(1, 8)):
            kind = rng.random()
            if kind < 0.5:
                reads.append(limits(0.0, int(at) + 18000))
                at += 25
            elif kind < 0.7:
                reads.append(limits(3.0, int(NOW) + 9000))
            elif kind < 0.78:
                reads.append(limits(0.0, int(NOW) + 18000, week=100.0, week_reset=int(NOW) + rng.choice([600, 90000])))
            elif kind < 0.86:
                reads.append({"raise": "RuntimeError"})
            else:
                reads.append(rng.choice([{}, {"rateLimitsByLimitId": {}}, None]))
        account = [rng.choice([{"account": {"type": "chatgpt"}}, {"account": {"type": "chatgpt"}}, {"account": None},
                               {}, {"raise": "RuntimeError"}])]
        out, err = child_out(rng)
        return {"op": "an", "capability": CAPABILITY, "now": NOW, "setup": setup, "steps": steps,
                "script": {"call:account/rateLimits/read": reads, "call:account/read": account},
                "view": {"settings": [rng.choice([{"enabled": True}] * 6 + [{"enabled": False}, {"enabled": True,
                                                                                                 "observe_only": True},
                                                                              None, {"raise": "RuntimeError"}])]},
                "permitted": [rng.choice([True, True, True, False, 1])],
                "files": {"out.txt": out, "err.txt": err,
                          "codex/config.toml": rng.choice(["", '[mcp_servers.alpha]\ncommand = "x"\n', "bad = ",
                                                           '[mcp_servers."a.b"]\nurl = "u"\n'])},
                "code": rng.choice([0, 0, 0, 1, 2]), "python": sys.executable, "child": CHILD,
                "told": rng.random() < 0.93, "session_raise": rng.random() < 0.04, "backend_raise": rng.random() < 0.04,
                "begin_runs": rng.random() < 0.92, "on": rng.random() < 0.95, "bind": rng.random() < 0.97,
                "armed": [CAPABILITY], "left": ["argv.txt"]}

    def full(self, **changes) -> dict:
        """The whole path: a reset seen gone by, two idle reads, the start, the request, two running reads."""
        steps = [["tick"], ["run"], ["clock", NOW + 25], ["tick"], ["run"], ["tick"], ["run"], ["clock", NOW + 50],
                 ["tick"], ["run"], ["tick"], ["run"]]
        case = {"op": "an", "capability": CAPABILITY, "now": NOW, "steps": steps,
                "setup": [["stamp", [CAPABILITY, "anchor_seen_reset", int(NOW) - 120], {}]],
                "script": {"call:account/read": [{"account": {"type": "chatgpt"}}],
                           "call:account/rateLimits/read": [limits(0.0, int(NOW) + 18000),
                                                            limits(0.0, int(NOW) + 18025),
                                                            limits(1.0, int(NOW) + 18025),
                                                            limits(1.0, int(NOW) + 18025)]},
                "files": {"out.txt": json.dumps({"type": "thread.started"}) + "\n" + json.dumps(
                    {"type": "turn.completed", "usage": {"input_tokens": 24000, "cached_input_tokens": 12000,
                                                         "output_tokens": 5}}), "err.txt": "",
                          "codex/config.toml": '[mcp_servers.alpha]\ncommand = "x"\n'},
                "python": sys.executable, "child": CHILD, "armed": [CAPABILITY], "left": ["argv.txt"]}
        case.update(changes)
        return case

    def test_walks(self):
        rng = random.Random(7272)
        cases = [self.walk(rng) for _ in range(220)]
        cases += [self.full(), self.full(code=1), self.full(permitted=[False]),
                  self.full(files={"out.txt": "", "err.txt": "Error: Unknown feature flag apps"}, code=2),
                  self.full(view={"settings": [{"enabled": True, "observe_only": True}]})]
        quiet = '[mcp_servers."a.b"]\nurl = "u"\n[mcp_servers.c]\ncommand = "x"\n'
        for config in ("", quiet, "broken = ", "﻿" + quiet):
            cases.append(self.full(files={"out.txt": json.dumps({"type": "thread.started"}), "err.txt": "",
                                          "codex/config.toml": config}))
        cases.append(self.full(files={"out.txt": "", "err.txt": "Error loading config.toml: invalid transport",
                                      "codex/config.toml": quiet}, code=1))
        cases.append(self.full(begin_runs=False))
        found = advtime.Scene(self, "anchor code").run(cases)
        fixed = sum(1 for each in found for row in (each["dump"] or {}).get("journal", ()) if "anchor.fixed" in row)
        started = sum(1 for each in found if each["left"].get("argv.txt"))
        self.assertGreater(fixed, 0)
        self.assertGreater(started, 5)

    def test_view(self):
        cases = []
        for state in ("armed", "shadow", None):
            for stamps in ([], [["anchor_started_at", int(NOW) - 10], ["anchor_fixed_at", int(NOW) + 100],
                                ["anchor_retry_until", int(NOW) - 5], ["anchor_stopped_at", int(NOW) - 3]]):
                cases.append({"op": "an.view", "capability": CAPABILITY, "state": state,
                              "setup": [["stamp", [CAPABILITY, key, value], {}] for key, value in stamps]})
        advtime.Scene(self, "anchor view").run(cases)


if __name__ == "__main__":
    unittest.main()

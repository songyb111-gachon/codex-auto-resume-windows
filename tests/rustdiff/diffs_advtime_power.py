"""S7.2e2: `engine/powertasks.py` (power_after_tasks, P21) as the v0.6.26 final has it, held equal to car-adv's
`engine::powertasks`.

`valid` over the list's shape and its mutants; `read` over files on a scratch home (missing, too large, damaged, a BOM,
not UTF-8, every key wrong); `write` (the bytes it leaves, under its named lock) and `remove`; `end_of` over generated
interruption chains (waiting, recovered with and without a recovery turn, continued by the person, loops, unhashable
states, keys that cannot be ordered) with a scripted turn history; `judge` over every list of ends; and P21 itself
over a list file, the facts' nonce, core's records (or their raise) and the history.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_power`.
"""
from __future__ import annotations

import json
import random
import unittest

from rustdiff import advtime

NONCE = "0123456789abcdef"
THREADS = [advtime.THREAD % n for n in range(1, 6)]
TURNS = [advtime.TURN % n for n in range(1, 10)]
STATES = ["waiting_reset", "waiting_poll", "recovered", "resumed", "superseded_by_user", "superseded", "failed",
          "cancelled", "submitting", "queued", "terminal_failure", "stopped_by_user", "nonsense", None, 3, ["x"]]
STATUSES = ["inProgress", "completed", "failed", "interrupted", "other", None, 5, {"raise": "RuntimeError"}]


def nonce() -> str:
    return NONCE


def document(rng: random.Random, tasks: int | None = None) -> dict:
    count = tasks if tasks is not None else rng.randint(1, 4)
    return {"format": "codex-auto-resume/power-tasks/1", "nonce": nonce(), "armed_at": rng.choice([1, 1.5, 1800000000]),
            "failed": rng.random() < 0.5, "interrupted": rng.random() < 0.5,
            "tasks": [{"thread_id": THREADS[n], "turn_id": TURNS[n]} for n in range(count)]}


def mutants(base: dict) -> list:
    found = [base, None, [], "x", {}]
    for key in list(base):
        cut = dict(base)
        del cut[key]
        found.append(cut)
        for value in (None, True, 1, 1.5, "x", [], {}, "fedcba9876543210", "0123456789ABCDEF"):
            changed = dict(base)
            changed[key] = value
            found.append(changed)
    extra = dict(base, more=1)
    found.append(extra)
    found.append(dict(base, tasks=[]))
    found.append(dict(base, tasks=[base["tasks"][0]] * 2))
    found.append(dict(base, tasks=[{"thread_id": THREADS[n], "turn_id": TURNS[0]} for n in range(5)] * 4))
    found.append(dict(base, tasks=[{"thread_id": THREADS[0]}]))
    found.append(dict(base, tasks=[{"thread_id": THREADS[0], "turn_id": "nope"}]))
    found.append(dict(base, tasks=[{"thread_id": THREADS[0], "turn_id": TURNS[0], "x": 1}]))
    found.append(dict(base, tasks=[{"thread_id": THREADS[0].upper(), "turn_id": TURNS[0]}]))
    return found


def record(rng: random.Random, thread: str, turn: str, index: int) -> dict:
    found = {"interruption_id": "i%02d" % index if rng.random() < 0.95 else rng.choice([None, 7, ["l"]]),
             "thread_id": thread, "turn_id": turn, "state": rng.choice(STATES),
             "detected_at": rng.choice([None, 0, 5, 10, 10.5, 20]) if rng.random() < 0.97 else "late"}
    if rng.random() < 0.6:
        found["recovery_turn_id"] = rng.choice(TURNS + [None, "nope"])
    if rng.random() < 0.3:
        found["parent_interruption_id"] = "i%02d" % rng.randint(0, index + 1)
    return found


def history(rng: random.Random, thread: str) -> dict:
    turns = {"status": {"%s|%s" % (thread, turn): rng.choice(STATUSES) for turn in TURNS if rng.random() < 0.8}}
    if rng.random() < 0.7:
        turns["latest"] = {thread: rng.choice(TURNS + [None, "nope", {"raise": "RuntimeError"}])}
    return turns


class PowerTasksDiff(unittest.TestCase):
    def test_valid(self):
        rng = random.Random(1)
        cases = []
        for _ in range(12):
            for each in mutants(document(rng)):
                cases.append({"op": "pt.valid", "document": each, "dump": False})
        advtime.Scene(self, "valid").run(cases)

    def test_read_write(self):
        rng = random.Random(2)
        name = "config/advanced/power-tasks.json"
        cases = []
        for each in mutants(document(rng))[:40]:
            text = json.dumps(each)
            cases.append({"op": "pt.read", "files": {name: text}, "dump": False})
            cases.append({"op": "pt.write", "document": each, "left": [name], "dump": False})
        good = json.dumps(document(rng, 2))
        for body in (good, " " + good + "\n", good + "x", "﻿" + good, {"hex": "ff" + good.encode().hex()},
                     good.replace('"failed": ', '"failed":  '), "[" * 5000, good + " " * 20000, "",
                     good.replace("\"tasks\"", "\"tasks\"", 1).replace("}", "}", 1)):
            cases.append({"op": "pt.read", "files": {name: body}, "dump": False})
        cases.append({"op": "pt.read", "dump": False})
        cases.append({"op": "pt.read", "files": {name: {"dir": True}}, "dump": False})
        cases.append({"op": "pt.write", "document": document(rng, 3), "remove": True, "left": [name], "dump": False})
        cases.append({"op": "pt.write", "document": document(rng, 1), "files": {name: "old"}, "left": [name],
                      "dump": False})
        cases.append({"op": "pt.write", "document": document(rng, 1), "files": {"config/advanced": "a file"},
                      "left": [name], "dump": False})
        advtime.Scene(self, "read/write").run(cases)

    def test_end_of(self):
        rng = random.Random(3)
        cases = []
        for _ in range(900):
            thread = THREADS[0]
            records = [record(rng, thread, rng.choice(TURNS[:4]), index) for index in range(rng.randint(0, 6))]
            cases.append({"op": "pt.end_of", "task": {"thread_id": thread, "turn_id": rng.choice(TURNS[:3])},
                          "records": records, "turns": history(rng, thread), "dump": False})
        found = advtime.Scene(self, "end_of").run(cases)
        ends = {each["result"]["ok"]["end"] for each in found if "ok" in each["result"]}
        self.assertEqual(ends, {"running", "completed", "failed", "interrupted", "unknown"})

    def test_judge(self):
        words = ["running", "completed", "failed", "interrupted", "unknown", "x", None]
        rng = random.Random(4)
        cases = [{"op": "pt.judge", "ends": [], "dump": False}]
        for _ in range(400):
            cases.append({"op": "pt.judge", "ends": [rng.choice(words[:4] if rng.random() < 0.7 else words)
                                                    for _ in range(rng.randint(1, 4))],
                          "failed": rng.random() < 0.5, "interrupted": rng.random() < 0.5, "dump": False})
        advtime.Scene(self, "judge").run(cases)

    def test_power(self):
        rng = random.Random(5)
        name = "config/advanced/power-tasks.json"
        cases = []
        for index in range(300):
            listed = document(rng)
            files = {name: json.dumps(listed)} if rng.random() < 0.9 else {}
            facts = rng.choice([{"nonce": NONCE}, {"nonce": NONCE}, {"nonce": "fedcba9876543210"}, {}, None, [],
                                {"nonce": 5}])
            records = "raise" if rng.random() < 0.1 else [
                record(rng, rng.choice(THREADS[:3]), rng.choice(TURNS[:4]), n) for n in range(rng.randint(0, 6))]
            turns = history(rng, THREADS[0])
            for thread in THREADS[1:3]:
                more = history(rng, thread)
                turns["status"].update(more["status"])
                if "latest" in turns and "latest" in more:
                    turns["latest"].update(more["latest"])
            cases.append({"op": "pt.power", "files": files, "facts": facts, "records": records, "turns": turns,
                          "dump": False})
        found = advtime.Scene(self, "power").run(cases)
        words = {each["result"]["ok"]["answer"].get("tasks") for each in found
                 if isinstance(each["result"].get("ok", {}).get("answer"), dict)}
        self.assertTrue({"met", "not_met", "running", "unknown"} <= words, words)


if __name__ == "__main__":
    unittest.main()

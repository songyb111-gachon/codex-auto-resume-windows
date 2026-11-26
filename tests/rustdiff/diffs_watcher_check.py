"""S6.1, car-watcher: the Diagnostics check's words and verdicts (checkup.py) and Rescan's judge (rescan.py).

* CheckDiff - `lines` over generated results in all 22 languages (every summary, conversations brought and not,
  reasons with and without their kind, left out and unchecked counts, records, the watcher stopped, split ids, homes
  read and not, the current one, cloud tasks, a usage reading with and without its windows, the notices' route and
  switches unknown, Codex found or not, skip lines), `_summary` (the FIRST order, ties, taken, ready, cloud), `_usage`
  over heartbeats of every shape, `_ago`, `_within` and `_reason` at their boundaries.
* RescanDiff - `proofs` over a conversation's records (markers, a marker-free client id, a client id of another
  record, a marker that is no proof), and `judge` over a scripted engine: retired on a person's later turn, a turn this
  product's continuation started or joined, a message not yet in the history, exactly current and still the latest or
  not, marker-free, every word of the rollout's evidence, an engine call that raises at each step, the anchor not
  found or at another ordinal, out of time.
"""
from __future__ import annotations

import json

from rustdiff import core, diffs, reference

SCRIPT = r'''
import json, random, sys, types
from codex_auto_resume import checkup, l10n, rescan
from codex_auto_resume.domain import ids
l10n._windows_preferred = lambda: ["en-US"]
rng = random.Random(6261)
LOCALES = list(l10n.LOCALES) if hasattr(l10n, "LOCALES") else ["en"]
NOW = 1_800_000_000.0
cases = []

SUMMARIES = ["nothing", "cloud", "ready", "taken", "recovery_off", "watcher_stopped", "newer_turn", "made_up_reason"]
REASONS = [None, "", "not_failed", "before_window", "other_kind", "newer_turn", "continued_elsewhere", "no_such_code"]

def conversation(n):
    brought = rng.random() < 0.5
    return {"thread": "conv-%d" % n, "home": rng.choice([None, 2]), "status": rng.choice(["failed", "completed", None, ""]),
            "category": rng.choice([None, "usage_limit", "", "server_5xx"]),
            "completed_at": rng.choice([None, NOW - 30, NOW - 4000, NOW - 200000, NOW + 50, 0]),
            "reason": rng.choice(REASONS), "kind": rng.choice([None, "", "network_transient"]),
            "turns_under": rng.choice([None, "conv-x"]), "brought": brought,
            "remaining": rng.sample(["recovery_off", "category_off", "conversation_off"], rng.randint(0, 2)) if brought else [],
            "records": rng.choice([[], ["waiting_reset"], ["recovered", "cancelled"]]) if brought else []}

def result():
    rows = [conversation(n) for n in range(rng.randint(0, 5))]
    usage = rng.choice([{"read": False, "read_at": None, "five_hour": None, "weekly": None, "reset_at": None},
                        {"read": True, "read_at": NOW - 600, "five_hour": 12.5, "weekly": None, "reset_at": NOW + 7200},
                        {"read": True, "read_at": None, "five_hour": 100, "weekly": 0.000012345, "reset_at": None},
                        {"read": True, "read_at": NOW - 10, "five_hour": 1234567, "weekly": True, "reset_at": NOW + 30}])
    return {"summary": rng.choice(SUMMARIES), "watcher_running": rng.random() < 0.5, "conversations": rows,
            "left_out": {"conversations": rng.choice([0, 3]), "unchecked": rng.choice([0, 1])},
            "split": [{"thread": "conv-1", "turns_under": "conv-9"}] if rng.random() < 0.3 else [],
            "homes": [{"home": None, "state_written": rng.choice([None, NOW - 100]), "history_written": NOW - 50,
                       "current": True, "readable": True, "cloud_tasks": None},
                      {"home": 2, "state_written": None, "history_written": None, "current": False,
                       "readable": rng.random() < 0.5, "cloud_tasks": 3}][:rng.randint(1, 2)],
            "cloud_tasks": rng.choice([None, 0, 4]), "usage": usage,
            "notices": rng.choice([{"route": "card", "do_not_disturb": False, "app_allowed": True},
                                   {"route": None, "do_not_disturb": None, "app_allowed": None},
                                   {"route": "toast", "do_not_disturb": True, "app_allowed": False}]),
            "codex": rng.choice([{"version": "0.140.0", "tier": "verified", "engine_found": True},
                                 {"version": None, "tier": None, "engine_found": False}]),
            "skips": rng.choice([[], ["2026-11-26 10:00:00 thread x: not taken up (newer_turn)"]])}

for locale in LOCALES:
    for _ in range(12):
        cases.append(["check_lines", result(), NOW, locale])
    for seconds in [None, -5, 0, 59.9, 60, 3599, 3600, 7199, 172799, 172800, 10 ** 7]:
        cases.append(["check_ago", seconds, locale])
    for seconds in [-1, 0, 61, 3599, 3600, 90000]:
        cases.append(["check_within", seconds, locale])
    for code in ["before_window", "other_kind", "nope", "not_failed"]:
        for kind in [None, "", "timeout"]:
            cases.append(["check_reason", code, kind, locale])
for _ in range(200):
    cases.append(["check_summary", [conversation(n) for n in range(rng.randint(0, 4))], rng.random() < 0.5,
                  rng.choice([0, 2, None])])
windows = [{"window_minutes": 300, "used_percent": 10, "reset_at": NOW + 100},
           {"window_minutes": 10080, "used_percent": 55.5, "reset_at": NOW + 50},
           {"window_minutes": 300.0, "used_percent": True, "reset_at": NOW - 1},
           {"window_minutes": 60, "used_percent": 1, "reset_at": "soon"}, "not a dict", None,
           {"window_minutes": 10080, "used_percent": "x", "reset_at": NOW + 10}]
for status in [None, {}, {"watcher": None}, {"watcher": {"usage": None}}, {"watcher": {"usage": {"windows": "x"}}},
               {"watcher": {"usage": {"read_at": NOW - 5, "windows": []}}}]:
    cases.append(["check_usage", status, NOW])
for _ in range(60):
    cases.append(["check_usage", {"watcher": {"usage": {"read_at": NOW - 5, "windows": rng.sample(windows, rng.randint(0, 5))}}},
                  NOW])

KEY = "a" * 64
OTHER = "b" * 64
def kin_rows():
    rows = [{"interruption_id": KEY, "marker": rng.choice([None, "", ids.marker(KEY), "not-a-marker"]),
             "recovery_client_id": rng.choice([None, ids.continuation_client_id(KEY), ids.continuation_client_id(OTHER)])}]
    if rng.random() < 0.5:
        rows.append({"interruption_id": OTHER, "marker": None, "recovery_client_id": ids.continuation_client_id(OTHER)})
    return rows
for _ in range(40):
    cases.append(["rescan_proofs", kin_rows()])

ROW = {"interruption_id": KEY, "thread_id": "11111111-1111-7111-8111-000000000001", "turn_id": "turn-1", "ordinal": 3}
def raising():
    return {"raise": "OSError"}
def turn(n, reason="later_turn_exists"):
    return {"turn_id": "turn-%d" % n, "reason": reason}
SCRIPTS = [
    {"turn_observation": {"each": [{"found": True, "ordinal": 3}, {"branded_user_messages": 0, "foreign_user_messages": 1}]},
     "later_turns": [turn(4)]},
    {"turn_observation": {"each": [{"found": True, "ordinal": 3}, {"branded_user_messages": 1}]}, "later_turns": [turn(4)],
     "fresh_throughout": True, "valid_interruption": True},
    {"turn_observation": {"each": [{"found": True, "ordinal": 3}, {"branded_user_messages": 0}]}, "later_turns": [turn(4)]},
    {"turn_observation": {"each": [{"found": True, "ordinal": 3}, {}]}, "later_turns": [turn(4)]},
    {"turn_observation": {"found": True, "ordinal": 3}, "later_turns": [turn(4)], "turn_markers": True,
     "fresh_throughout": True, "valid_interruption": False},
    {"turn_observation": {"found": True, "ordinal": 3}, "later_turns": [turn(4), turn(5, "other"), {"turn_id": None}],
     "foreign": False, "rescan_evidence": "later_message"},
    {"turn_observation": {"found": True, "ordinal": 2}, "rescan_evidence": "too_large"},
    {"turn_observation": {"found": False}, "rescan_evidence": "rolled_back"},
    {"turn_observation": {"found": False}, "rescan_evidence": "nothing_later"},
    {"turn_observation": {"found": False}, "rescan_evidence": raising()},
    {"turn_observation": {"found": False}, "fresh_throughout": raising(), "rescan_evidence": "unreadable"},
    {"turn_observation": {"found": False}, "fresh_throughout": True, "valid_interruption": raising()},
    {"proof": raising()},
    {"turn_observation": None},
    {"turn_observation": {"found": True, "ordinal": 3}, "later_turns": raising()},
    {"turn_observation": {"found": True, "ordinal": 3}, "later_turns": ["not a turn"]},
    {"turn_observation": {"found": True, "ordinal": 3}, "later_turns": [{"reason": "x"}]},
    {"turn_observation": {"each": [{"found": True, "ordinal": 3}, None]}, "later_turns": [turn(4)]},
    {"turn_observation": {"found": False}, "rescan_evidence": ["a", "list"]},
    {"turn_observation": {"found": False}, "rescan_evidence": {"a": "dict"}},
]
for script in SCRIPTS:
    for kin in ([], kin_rows(), [{"interruption_id": KEY, "marker": None, "recovery_client_id": ids.continuation_client_id(KEY)}]):
        cases.append(["rescan_judge", ROW, kin, dict(script, clock=NOW), None, 5.0])
cases.append(["rescan_judge", ROW, [], {"clock": NOW}, 4.0, 5.0])
cases.append(["rescan_judge", ROW, [], {"clock": NOW, "turn_observation": {"found": False}}, 6.0, 5.0])

class Engine:
    def __init__(self, script):
        self.script, self.calls = json.loads(json.dumps(script)), []
        self.source = self
    def answer(self, name, *args):
        self.calls.append([name] + list(args))
        found = self.script.get(name)
        if isinstance(found, dict) and "each" in found:
            items = found["each"]
            found = items.pop(0) if len(items) > 1 else (items[0] if items else None)
        if isinstance(found, dict) and "raise" in found:
            raise OSError("scripted")
        return found
    def proof(self, row):
        return self.answer("proof", row["interruption_id"])
    def turn_observation(self, thread, turn_id, proof):
        return self.answer("turn_observation", thread, turn_id, proof)
    def later_turns(self, thread, ordinal, proof):
        return self.answer("later_turns", thread, ordinal, proof)
    def persons_turns(self, thread, turns):
        found = self.answer("persons_turns", thread, turns)
        return turns if found is None else found
    def foreign(self, row, turn):
        return self.answer("foreign", turn["turn_id"]) is not False
    def turn_markers(self, thread, turn_id, ours):
        return bool(self.answer("turn_markers", thread, turn_id, list(ours)))
    def clock(self):
        return self.script.get("clock", 0.0)
    def fresh_throughout(self, thread, now):
        return bool(self.answer("fresh_throughout", thread, now))
    def valid_interruption(self, row):
        return bool(self.answer("valid_interruption", row["interruption_id"]))
    def rescan_evidence(self, thread, turn_id):
        return self.answer("rescan_evidence", thread, turn_id)

def judge(row, kin, script, deadline, monotonic):
    rescan.time = types.SimpleNamespace(monotonic=lambda: monotonic)
    engine = Engine(script)
    outcome, reason = rescan.judge(engine, row, kin, deadline)
    return [outcome, reason, engine.calls]

def proofs(kin):
    found, free = rescan.proofs(kin)
    return [list(found), free]

ops = {"check_lines": checkup.lines, "check_summary": checkup._summary, "check_usage": checkup._usage,
       "check_ago": checkup._ago, "check_within": checkup._within, "check_reason": checkup._reason,
       "rescan_proofs": proofs, "rescan_judge": judge}
results = []
for case in cases:
    try:
        results.append({"ok": ops[case[0]](*case[1:])})
    except Exception as error:
        results.append({"error": type(error).__name__})
sys.stdout.write(json.dumps({"cases": cases, "results": results}, ensure_ascii=False))
'''


class CheckRescanDiff(diffs.Base):
    def test_check_and_rescan(self):
        made = reference.run(SCRIPT, profile=self.profile("reference"))
        self.assertEqual(made.returncode, 0, made.stderr[-4000:].decode("utf-8", "replace"))
        done = json.loads(made.stdout.decode("utf-8"))
        cases, expected = done["cases"], done["results"]
        self.assertGreater(len(cases), 500)
        actual = []
        with core.Harness(reference.scratch_environment(self.profile("rust"))) as harness:
            for start in range(0, len(cases), 500):
                _id, line = harness.call("watcher.batch", cases=cases[start:start + 500])
                reply = json.loads(line.decode("utf-8"))
                self.assertTrue(reply["reply"].get("ok"), line[:600])
                actual += reply["reply"]["value"]
        self.assertEqual(len(actual), len(expected))
        for index, (want, got) in enumerate(zip(expected, actual)):
            if diffs.encode(want) != diffs.encode(got):
                self.fail("case %d differs\n  case      %s\n  reference %s\n  rust      %s" % (
                    index, json.dumps(cases[index], ensure_ascii=False)[:900],
                    json.dumps(want, ensure_ascii=False)[:1500], json.dumps(got, ensure_ascii=False)[:1500]))

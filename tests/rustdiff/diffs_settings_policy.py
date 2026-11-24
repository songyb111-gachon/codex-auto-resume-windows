"""S2.2, the administrator's policy keys, the status file's content, the power action's rules, the demo and the
self-check, held to the tag.

The policy keys two ways: `managed.parse` over generated places (every switch, ceiling and QuietHours form, each
registry type, a value there and unreadable, a malformed entry), with `fields`, `ceilings`, `clamp`, `admit` and
`quiet_sources`; and end to end through a registry stand-in - the reference's `policykeys.read()` with `winreg`
replaced by platform_registry_diffs' recording `Winreg`, Rust's `registry_reads::read_policies` on car-platform's
`FakeRegistry` - never the machine's HKCU Policies (brief rule 3).
"""
from __future__ import annotations

from rustdiff.platform_registry_diffs import FAKE
from rustdiff.settingsdiff import Family

RECORD: list[str] = []

MANAGED = r'''
from codex_auto_resume import managed
from codex_auto_resume.win import policykeys
rng = random.Random(11)
NAMES = list(managed.VALUES) + ["Other"]
DATA = [0, 1, 2, 5, 19, 20, 21, -1, 2 ** 31, 2 ** 70, True, False, None, "1", 1.0, "22:00-07:00", "22:00-07:00 weekdays",
        "22:00-22:00", " 22:00 - 07:00  weekends ", "22:15-07:00", "٢٢:00-07:00", "22:00-07:00 Weekdays",
        "22:00-07:00weekdays", "22:00-07:00 every_day\n", "22:00　-　07:00", "22:00-07:00 sometimes", "", "7:00-8:00",
        "23:30-00:00", "00:00-23:30 weekends  x", "22:00-07:00 _", ["x"], {"a": 1}]
KINDS = [1, 2, 3, 4, 11, -1, 4.0, True, "4", None, 7]
def entry():
    roll = rng.random()
    if roll < 0.08:
        return rng.choice([[1, 4, 5], "x", None, 5, [4]])
    if roll < 0.2:
        return [None, -1]
    return [rng.choice(DATA), rng.choice(KINDS)]
def place():
    return {name: entry() for name in rng.sample(NAMES, rng.randrange(0, len(NAMES) + 1))}
def tuples(places):
    if not isinstance(places, list):
        return places
    return [{name: tuple(value) if isinstance(value, list) and len(value) == 2 else value for name, value in each.items()}
            if isinstance(each, dict) else each for each in places]
def managed_value(held):
    return {"disable_auto_resume": held.disable_auto_resume, "force_observe_only": held.force_observe_only,
            "disable_update_check": held.disable_update_check, "disable_status_file": held.disable_status_file,
            "max_recovery_attempts": held.max_recovery_attempts, "quiet_hours": list(held.quiet_hours),
            "disable_power_action": held.disable_power_action, "codes": held.codes(), "active": held.active,
            "fields": sorted(managed.fields(held)), "ceilings": managed.ceilings(held)}
cases = []
placeses = [None, [], "x", [5, "x"], [{}], [{}, {}]] + [[place() for _ in range(rng.randrange(1, 4))] for _ in range(1200)]
for places in placeses:
    cases.append(["managed.parse", places])
settings_values = [{}, {"observe_only": False, "max_recovery_attempts": 12, "quiet_hours_start": "off", "status_file": True},
                   {"max_recovery_attempts": 1}, {"max_recovery_attempts": True}, {"max_recovery_attempts": 2 ** 70},
                   {"max_recovery_attempts": 3.5}]
changes = [{"observe_only": True}, {"observe_only": False}, {"observe_only": 1}, {"max_recovery_attempts": 2},
           {"max_recovery_attempts": 20}, {"max_recovery_attempts": True}, {"quiet_hours_start": "22:00"},
           {"theme": "dark", "status_file": True}, {"status_file": False}, {"status_file": 0}, {"theme": "dark"},
           {"max_recovery_attempts": 3, "observe_only": False, "theme": "x"}]
for places in placeses[:300]:
    for values in settings_values:
        cases.append(["managed.clamp", places, values])
        cases.append(["managed.quiet_sources", places, values])
    for change in changes:
        effective = managed.clamp({"observe_only": False, "max_recovery_attempts": 4, "status_file": False,
                                   "quiet_hours_start": "off", "quiet_hours_end": "07:00", "quiet_hours_days": "every_day"},
                                  managed.parse(tuples(places)) if isinstance(places, list) else managed.NONE)
        cases.append(["managed.admit", places, change, effective])
for text in DATA:
    cases.append(["managed.quiet_window", text])
dword, sz = 4, 1
for seed, deny_keys, deny_values in [
        ([], [], []),
        ([["HKCU", policykeys.KEY, {"DisableAutoResume": [1, dword]}]], [], []),
        ([["HKLM", policykeys.KEY, {"MaxRecoveryAttempts": [3, dword], "QuietHours": ["22:00-07:00 weekdays", sz]}],
          ["HKCU", policykeys.KEY, {"MaxRecoveryAttempts": [2, dword], "QuietHours": ["21:00-06:30", 2]}]], [], []),
        ([["HKCU", policykeys.KEY, {"ForceObserveOnly": [0, dword], "DisableStatusFile": [7, dword], "Other": [1, dword]}]], [], []),
        ([["HKCU", policykeys.KEY, {"DisablePowerAction": ["1", sz], "DisableUpdateCheck": [1, 3]}]], [], []),
        ([["HKCU", policykeys.KEY, {"DisableAutoResume": [1, dword]}]], [["HKCU", policykeys.KEY]], []),
        ([["HKLM", policykeys.KEY, {"QuietHours": ["22:00-07:00", sz], "MaxRecoveryAttempts": [9, dword]}]], [],
         [["HKLM", policykeys.KEY, "QuietHours"], ["HKLM", policykeys.KEY, "MaxRecoveryAttempts"]]),
        ([["HKCU", "Software\\Policies", {}]], [], []),
        ([["HKCU", policykeys.KEY, {"MaxRecoveryAttempts": [21, dword], "QuietHours": ["22:00-22:00", sz]}]], [], []),
        ([["HKCU", policykeys.KEY, {"DisableAutoResume": [1, 11], "MaxRecoveryAttempts": [2, 11]}]], [], [])]:
    cases.append(["managed.registry", {"seed": seed, "deny_keys": deny_keys, "deny_values": deny_values}])
def registry(request):
    fake = Winreg(request)
    policykeys._winreg = lambda: fake
    places = policykeys.read()
    return {"places": [{name: list(value) for name, value in each.items()} for each in places],
            "managed": managed_value(managed.parse(places))}
ops = {"managed.parse": lambda places: managed_value(managed.parse(tuples(places))),
       "managed.clamp": lambda places, values: managed.clamp(values, managed.parse(tuples(places))),
       "managed.quiet_sources": lambda places, own: managed.quiet_sources(own, managed.parse(tuples(places))),
       "managed.admit": lambda places, change, effective: list(managed.admit(change, effective, managed.parse(tuples(places)))),
       "managed.quiet_window": managed.quiet_window, "managed.registry": registry}
finish(cases, ops)
'''


class ManagedDiff(Family):
    def test_policy_keys(self):
        done = self.family(FAKE + MANAGED, label="managed", expect=3000)
        registry = sum(1 for case in done["cases"] if case[0] == "managed.registry")
        RECORD.append("policy keys: %d parse/clamp/admit cases and %d registry stand-in scenarios equal (HKCU Policies "
                      "never opened)" % (len(done["cases"]) - registry, registry))


POWER = r'''
from codex_auto_resume import poweraction, statusfile, demo
from codex_auto_resume.domain import public
rng = random.Random(5)
NONCE = "0123456789abcdef"
KEY = "%064x"
NOW = 1_700_000_000.0
STATES = ["waiting_reset", "waiting_poll", "waiting_retry", "submitting", "queued", "turn_started", "recovered",
          "handed_over", "superseded", "superseded_by_user", "stopped_by_user", "cancelled", "failed", "submission_unknown",
          "retry_budget_exhausted", "no_progress_exhausted", "terminal_failure", "x", None, ["recovered"]]
def number():
    return rng.choice([NOW - 7200, NOW - 100, NOW, NOW + 10, NOW + 4000, 0, -1, 2 ** 70, 253402300800, True, None, "1",
                       float("nan"), NOW - 90000, int(NOW) - 30])
def row():
    made = {"interruption_id": rng.choice([KEY % rng.randrange(6), KEY % 99, 5, None]), "state": rng.choice(STATES),
            "category": rng.choice(["usage_limit", "timeout", None, 5]), "detected_at": number()}
    for key in ("outcome_at", "submitted_at", "queue_id", "last_error", "reset_at", "next_retry_at", "hold", "not_before"):
        if rng.random() < 0.4:
            made[key] = rng.choice([number(), "latest_turn_changed", "parent_handed_over", "x", None,
                                    "0a1b2c3d-0001-7000-8000-000000000001"])
    return made
def armed():
    made = {"nonce": NONCE, "action": rng.choice(["sleep", "hibernate", "shut_down"]),
            "after": rng.choice(["all_recovered", "handed_over_too", "any_end"]), "repeat": rng.choice(["once", "always"]),
            "grace_seconds": rng.choice([120, 300, 600, 900, 1800]), "armed_at": NOW - rng.choice([10, 4000, 90000]),
            "since": NOW - 5, "carried": [KEY % n for n in range(rng.randrange(0, 4))], "stop_at": None}
    if rng.random() < 0.15:
        made["stop_at"] = NOW
    if rng.random() < 0.15:
        made.update(tasks=True, repeat="once", carried=[])
    if rng.random() < 0.3:
        key = rng.choice(list(made))
        made[key] = rng.choice([None, True, "x", -5, 2 ** 70, [], NOW + 1000, "ABCDEF0123456789", [KEY % 1, KEY % 1], 121])
    return made
def document():
    made = {"format": "codex-auto-resume/power-action/1", "armed": armed() if rng.random() < 0.85 else None,
            "shown": None, "last": None}
    if made["armed"] is not None and rng.random() < 0.4:
        made["shown"] = {"nonce": NONCE, "phase": rng.choice(["waiting", "grace", "x"]),
                         "waiting_for": rng.choice([None, "no_batch", "paused", "nope"]),
                         "grace_until": rng.choice([None, NOW + 60, "x"])}
    if rng.random() < 0.3:
        made["last"] = {"action": "sleep", "result": rng.choice(["done", "not_met", "x"]), "at": number()}
    if rng.random() < 0.1:
        made[rng.choice(["extra", "format"])] = "x"
    return made
cases = [["power.blank"]]
for _ in range(1500):
    value = document()
    now = rng.choice([NOW, NOW - 400, 2 ** 70])
    cases.append(["power.read_document", value, now])
for value in [None, 5, [], {}, {"format": "codex-auto-resume/power-action/1"}]:
    cases.append(["power.read_document", value, NOW])
documents = []
for _ in range(600):
    found = poweraction.read_document(document(), NOW)
    if found is not None:
        documents.append(found)
for found in documents[:200] + [None, {}, {"armed": None}]:
    cases += [["power.view", found], ["power.for_tasks", (found or {}).get("armed")]]
for choice in [{"action": "sleep", "after": "any_end", "repeat": "once", "grace_minutes": 5}, {"action": "nap"}, None,
               {"action": "sleep", "after": "x", "repeat": "once", "grace_minutes": 5},
               {"action": "sleep", "after": "any_end", "repeat": "x", "grace_minutes": 5},
               {"action": "sleep", "after": "any_end", "repeat": "once", "grace_minutes": 7},
               {"action": "sleep", "after": "any_end", "repeat": "once", "grace_minutes": True},
               {"action": "sleep", "after": "any_end", "repeat": "once", "grace_minutes": 5, "x": 1}]:
    cases.append(["power.choice_problem", choice])
rows = [row() for _ in range(400)]
for each in rows:
    cases += [["power.is_open", each], ["power.classify", each]]
    for found in documents[:3]:
        cases.append(["power.is_member", each, found["armed"]])
for _ in range(200):
    cases.append(["power.newest", rng.sample(rows, rng.randrange(0, 5))])
for after in ["all_recovered", "handed_over_too", "any_end", "x"]:
    for classes in [[], ["success"], ["success", "person"], ["person"], ["other"], ["success", None], ["success", "success"]]:
        cases.append(["power.met", after, classes])
for _ in range(1200):
    found = rng.choice(documents) if documents else None
    facts = {"now": NOW, "read": rng.choice(["ok", "ok", "ok", "missing", "invalid", "unreadable"]), "document": found,
             "managed": rng.random() < 0.1, "ok": rng.random() > 0.1, "paused": rng.random() < 0.1,
             "rows": rng.sample(rows, rng.randrange(0, 6)), "saw_open": rng.random() < 0.3,
             "tasks": rng.choice([None, "running", "met", "not_met", "unknown", "x"])}
    cases.append(["power.decide", facts])
for found in [None, {}, {"history": True, "running": 0, "queued": 0}, {"history": False}, {"history": 1},
              {"history": True, "running": 1, "queued": 0}, {"history": True, "running": 0, "queued": 2},
              {"history": True, "running": True, "queued": 0}, {"history": True, "running": -1, "queued": 0}, 5]:
    cases.append(["power.judge_activity", found])
for action in ["sleep", "shut_down"]:
    for others in [0, 1, None, True, -1]:
        for idle in [0, 119, 120, 120.5, None, True, -1, float("nan"), "300"]:
            cases.append(["power.judge_presence", action, others, idle])
for started, last, now, idle in [(NOW, NOW, NOW + 10, 30), (NOW, NOW, NOW + 10, 5), (NOW, NOW - 100, NOW, 1000),
                                 (NOW, NOW + 100, NOW, 1000), (NOW, NOW, NOW, None), (NOW, NOW, NOW, float("nan")),
                                 (NOW, NOW, NOW + 90, 90), (NOW, NOW, NOW + 91, 91), (NOW, NOW, NOW, True)]:
    cases.append(["power.countdown_holds", started, last, now, idle])
WINDOW = {"bucket": "codex", "window": "primary", "used_percent": 12.5, "window_minutes": 300, "reset_at": 1700003600}
for _ in range(600):
    kwargs = {"now": rng.choice([NOW, int(NOW), 2 ** 70, "x"]), "version": rng.choice(["0.6.26", "0.6.26-beta.2", "", "é", 5, "a" * 33]),
              "running": rng.random() < 0.5, "enabled": rng.choice([True, False, 0, None]), "observe_only": rng.random() < 0.3,
              "engine": rng.choice(["verified", "checked", "x", None]), "rows": rng.sample(rows, rng.randrange(0, 6)),
              "reading": rng.choice([None, {}, {"read_at": NOW, "windows": [WINDOW]}, {"read_at": 2 ** 70, "windows": [WINDOW]},
                                     {"read_at": NOW, "windows": []}, {"read_at": True, "windows": [WINDOW]}, "x"])}
    cases.append(["status.content", kwargs])
base = {"format": "codex-auto-resume/status/1", "written_at": NOW, "version": "0.6.26", "watcher": "running",
        "recovery": "on", "engine": "verified", "pending": 2, "states": {"waiting_reset": 2}, "next_check_at": None,
        "usage": {"read_at": NOW, "windows": [WINDOW]}}
for change in [{}, {"pending": 3}, {"pending": True}, {"states": {"x": 2}}, {"states": {"waiting_reset": 0}, "pending": 0},
               {"version": "0.6+x"}, {"version": "0.6 x"}, {"version": "٣.6"}, {"watcher": "x"}, {"written_at": 2 ** 70},
               {"next_check_at": "x"}, {"usage": {"windows": [WINDOW], "read_at": NOW}}, {"usage": {"read_at": NOW, "windows": [5]}},
               {"engine": "unknown", "recovery": "observe_only"}]:
    cases.append(["status.clean", dict(base, **change)])
cases.append(["status.clean", {key: base[key] for key in reversed(list(base))}])
for values in [None, {}, {"status_file": True}, {"status_file": 1}, {"status_file": "true"}, []]:
    cases.append(["status.wanted", values])
for now in [NOW, int(NOW), 0, 2 ** 70, "x", None, True]:
    cases += [["demo.detail", now], ["demo.rows", now]]
note = {"format": "codex-auto-resume/selfcheck/1", "started_at": NOW, "blocked": "recovery_blocked:held_elsewhere",
        "unknown_error": {"code": "SomethingNew", "count": 3}, "layout_untested": "0.163.0", "updated_from": "0.6.25"}
for change in [{}, {"started_at": int(NOW)}, {"started_at": NOW + 1}, {"started_at": True}, {"format": "x"},
               {"blocked": "x"}, {"unknown_error": {"code": "1bad", "count": 3}}, {"unknown_error": {"code": "a" * 65, "count": 3}},
               {"unknown_error": {"code": "ok", "count": 0}}, {"unknown_error": {"code": "ok", "count": 10 ** 6}},
               {"unknown_error": {"code": "ok", "count": True}}, {"layout_untested": "-1"}, {"layout_untested": "a" * 33},
               {"updated_from": "0.6.25\n"}, {"blocked": None, "unknown_error": None, "layout_untested": None, "updated_from": None}]:
    for started in [NOW, int(NOW), True, "x", 2 ** 70, NOW + 1]:
        cases.append(["selfcheck", dict(note, **change), started])
cases += [["selfcheck", None, NOW], ["selfcheck", [], NOW]]
def decide(facts):
    found = poweraction.decide(poweraction.Facts(**dict(facts, rows=tuple(facts["rows"]))))
    return [found.verdict, found.word, found.saw_open]
ops = {"power.blank": poweraction.blank, "power.read_document": poweraction.read_document, "power.view": poweraction.view,
       "power.for_tasks": poweraction.for_tasks, "power.choice_problem": poweraction.choice_problem,
       "power.is_open": poweraction.is_open, "power.classify": poweraction.classify, "power.is_member": poweraction.is_member,
       "power.newest": poweraction.newest, "power.met": poweraction.met, "power.decide": decide,
       "power.judge_activity": poweraction.judge_activity, "power.judge_presence": poweraction.judge_presence,
       "power.countdown_holds": poweraction.countdown_holds, "status.content": lambda kwargs: statusfile.content(**kwargs),
       "status.clean": statusfile.clean, "status.wanted": statusfile.wanted, "demo.detail": demo.detail,
       "demo.rows": demo.rows, "selfcheck": public.self_check}
finish(cases, ops)
'''


class PowerStatusDiff(Family):
    def test_power_status_demo_selfcheck(self):
        done = self.family(POWER, label="power", expect=5000)
        count = lambda prefix: sum(1 for case in done["cases"] if case[0].startswith(prefix))
        RECORD.append("power action %d, status file content %d, demo %d, self-check %d cases equal" % (
            count("power."), count("status."), count("demo."), count("selfcheck")))

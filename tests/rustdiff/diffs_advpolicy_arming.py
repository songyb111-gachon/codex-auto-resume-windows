"""S7.1b, arming: every decision `Arming` makes, over scenarios made in the reference process.

A scenario (arming_scenarios.py says its shape) is a registry, an environment (the Compatibility Registry's view, the policy,
the table of measurements, the automatic check's record), the advanced state as it stands and a list of steps - arm with every
kind of request, disarm, all off, Keep on, the ceiling, a choice, a wording, a rule, a read, a sweep over core's records, a
send that went unknown, the listing, a statement. The tag's own `Arming` runs it over a Python stand-in for `AdvancedState` and
stubs for what arming imports lazily; car-adv's `Arming` runs the same scenario over a Rust stand-in with the same semantics
and the same stubs (advprobe's `ops_arming.rs`). What must be equal is everything: each step's answer, every call made of
the state and the edges in order with its arguments, and the state left.

| Class | Holds equal to the tag |
|---|---|
| ArmingPureDiff | `engine_version`, `compat_warning`, `warnings_for`, `standing`, `departs`, `offers_send_again`, `kept_words`, `held_word`, `_rises`, `_confirmed`, `_claimed_at`, `_carried`, and autocheck's `settled` and `grade`, over generated views, rows, policies and tables |
| ArmingScenarioDiff | about 700 scenarios, 12,000 steps, over the shipped registry and four test-made ones that need each other |
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from rustdiff import advref
from rustdiff.advdiff import AdvDiff
from rustdiff.arming_scenarios import SCENARIO_RUNNER

RECORD: list[str] = []

GENERATE = r'''
import copy, json, random, shutil, sys
from pathlib import Path
from codex_auto_resume import l10n
from codex_auto_resume_advanced import arming, registry, measured, statement, autocheck
from codex_auto_resume_advanced.vocabulary import ArmingWarning, OffReason, Measurement, Verdict, AutoResult
real, scratch = Path(sys.argv[1]), Path(sys.argv[2])
seed, count = int(sys.argv[3]), int(sys.argv[4])
real_count = int(sys.argv[5]) if len(sys.argv) > 5 else 0
rng = random.Random(seed)
exec(SCENARIO_RUNNER_SOURCE)

shipped = [dump_def(each) for each in registry.DEFINITIONS]
made_defs = made_definitions(shipped)
def statements_into(directory, ids):
    for locale in l10n.LOCALES:
        path = directory / ("%s.json" % locale)
        table = json.loads(path.read_text(encoding="utf-8"))
        for cap in ids:
            for field in statement.FIELDS:
                table[statement.key(cap, field)] = "%s %s %s" % (cap, field, locale)
        path.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
made_dir, incomplete_dir = scratch / "made", scratch / "incomplete"
shutil.copytree(real, made_dir); statements_into(made_dir, MADE)
undecodable_dir = scratch / "undecodable"
shutil.copytree(real, undecodable_dir)
(undecodable_dir / "ru.json").write_bytes(b"\xff\xfe not text")
shutil.copytree(real, incomplete_dir)
table = json.loads((incomplete_dir / "en.json").read_text(encoding="utf-8"))
table.pop(statement.key(shipped[0]["id"], "does"), None); table.pop(statement.key(shipped[5]["id"], "stop"), None)
(incomplete_dir / "en.json").write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")

from codex_auto_resume_advanced.runtime import SENDING
SENDING_POINTS = sorted(str(point) for point in SENDING)
ENGINE, OTHER = "codex-cli 0.167.0-alpha.3.2", "codex-cli 0.168.0"
MEASURED_ROWS = [[str(k), str(v), e] for k, (v, e) in measured.MEASURED.items()]
ALL_PASS = [[str(m), "pass", ENGINE] for m in Measurement]
STATES = ["COMPATIBLE", "COMPATIBLE", "COMPATIBLE", "VERIFIED", "CHECKED", "FAILED_HERE", "INCOMPATIBLE", "UNKNOWN", "WEIRD", 5]

def a_view(ids, engine=ENGINE):
    kind = rng.random()
    if kind < 0.04: return "raises"
    if kind < 0.07: return "notdict"
    if kind < 0.10: return {}
    caps = {}
    for cid in ids:
        entry = rng.choices(["good", "bad", "plain", "nodict", "missing"], [70, 8, 6, 3, 13])[0]
        if entry == "good": caps[cid] = {"state": "COMPATIBLE", "reason": "local_checks_passed"}
        elif entry == "bad": caps[cid] = {"state": rng.choice(STATES), "reason": rng.choice(["local_check_failed", "x", None])}
        elif entry == "plain": caps[cid] = {"state": "VERIFIED"}
        elif entry == "nodict": caps[cid] = "COMPATIBLE"
    view = {"status": rng.choice(["ok", "ok", "ok", "stale"]), "capabilities": caps if rng.random() > 0.05 else rng.choice([None, [], "x"])}
    shape = rng.random()
    view["engine"] = ({"found": True, "version": engine} if shape < 0.85 else {"found": False} if shape < 0.9
                      else {"version": 5} if shape < 0.93 else None if shape < 0.96 else "x")
    return view

def a_table():
    kind = rng.random()
    if kind < 0.35: return copy.deepcopy(MEASURED_ROWS)
    if kind < 0.45: return []
    if kind < 0.6: return copy.deepcopy(ALL_PASS)
    rows = []
    for m in Measurement:
        if rng.random() < 0.5:
            rows.append([str(m), rng.choice(["pass", "pass", "fail", "blocked"]), rng.choice([ENGINE, ENGINE, OTHER, ""])])
    return rows

def a_checked():
    if rng.random() < 0.6: return []
    return [[str(m), rng.choice(["pass", "fail", "unknown"])] for m in Measurement if rng.random() < 0.4]

def a_policy():
    kind = rng.random()
    if kind < 0.6: return {"forbid": False, "force_shadow": False, "allowed": None}
    if kind < 0.65: return "raises"
    return {"forbid": rng.random() < 0.15, "force_shadow": rng.random() < 0.2,
            "allowed": None if rng.random() < 0.5 else rng.sample([d["id"] for d in shipped], rng.randint(0, 40)) + MADE[: rng.randint(0, 4)]}

def a_row(defs, view, table, checked, cap):
    d = next(each for each in defs if each["id"] == cap)
    state = rng.choices(["armed", "shadow", "off"], [55, 25, 20])[0]
    plain = view if isinstance(view, dict) else {}
    now = [str(w) for w in arming.warnings_for(build_def(d), plain, table_of(table), checked=results_of(checked))]
    warnings = now if rng.random() < 0.6 else [w.value for w in ArmingWarning if rng.random() < 0.25]
    version = arming.engine_version(plain)
    keep = state != "off" and rng.random() < 0.18
    return {"state": state, "since": 1799990000.0 + rng.randint(0, 9000) if state != "off" else None,
            "actor": rng.choice(["dashboard", "dashboard", "tripwire", None]),
            "reason": rng.choice([None, None, None] + [o.value for o in OffReason]) if state == "off" or keep else None,
            "statement_revision": d["revision"] if rng.random() < 0.88 else rng.choice([d["revision"] + 1, 0, None]),
            "engine_version": version if rng.random() < 0.75 else rng.choice([OTHER, None]),
            "warnings": warnings, "keep_on": keep, "send_again": keep and rng.random() < 0.4}

def scenario():
    kind = "shipped" if rng.random() < 0.45 else "made"
    shipped_table = [] if rng.random() < 0.6 else (copy.deepcopy(ALL_PASS) if rng.random() < 0.5 else copy.deepcopy(MEASURED_ROWS))
    if kind == "shipped":
        reg = registry.Registry(registry.DEFINITIONS + registry.offered(table_of(shipped_table)))
        ids = [d.id for d in reg]
        defs = [dump_def(d) for d in reg]
    else:
        reg = registry.Registry([build_def(each) for each in made_defs])
        defs = made_defs
        ids = MADE
    compat = sorted({d["compat"] for d in defs if d["compat"]})
    view = a_view(compat)
    table, checked = a_table(), a_checked()
    default_view = a_view(compat)
    env = {"view": view, "live": a_view(compat), "default_view": default_view, "default_live": a_view(compat), "policy": a_policy(),
           "measured": table if rng.random() < 0.9 else "raises", "table_for": table if rng.random() < 0.93 else "raises",
           "checked": checked if rng.random() < 0.95 else "raises", "order": rng.choice(["ok", "ok", "order", "warn"]),
           "clock": 1800000000.0 + rng.randint(0, 100000), "sending": SENDING_POINTS, "wording_limit": wrapwords.continuation.MAX_CUSTOM_LENGTH, "placeholders": list(wrapwords.PLACEHOLDERS)}
    view_given, live_given, measured_given = rng.random() < 0.8, rng.random() < 0.35, rng.random() < 0.3
    rows = []
    for cap in rng.sample(ids, min(len(ids), rng.choice([0, 1, 2, 3, 5, 8]))):
        rows.append([cap, a_row(defs, view if view_given else default_view, table if (measured_given or True) else table, checked, cap)])
    on = [cap for cap, row in rows if row["state"] != "off"]
    records = ["a" * 63 + str(i) for i in range(4)]
    state = {"rows": rows, "generation": rng.randint(1, 9), "global_hourly": rng.choice([24, 12, 1]),
             "spends": [[cap, rng.choice(records), 1799990000.0 + rng.randint(0, 9000)] for cap in on for _ in range(rng.randint(0, 2))],
             "overrides": [{"kind": rng.choice(["force_once", "resend_once"]), "interruption_id": rng.choice(records), "capability": rng.choice(ids),
                            "created_at": 1799990000.0 + rng.randint(0, 100000)} for _ in range(rng.randint(0, 3))],
             "resent": [r for r in records if rng.random() < 0.2],
             "payers": {r: [[rng.choice(ids), 1799990000.0 + rng.randint(0, 9000)] for _ in range(rng.randint(0, 3))] for r in records},
             "reset_rules": [{"rule_id": i, "capability": rng.choice(ids), "launching_at": rng.choice([None, None, 5.0]),
                              "record_state": rng.choice([None, "waiting", "in_flight"])} for i in range(rng.randint(0, 3))],
             "credits": rng.random() < 0.4,
             "continuations": [{"capability": rng.choice(ids), "record_state": rng.choice(["waiting", "in_flight", None])} for _ in range(rng.randint(0, 3))],
             "options": {}, "wordings": {}, "rules": [{"rule_id": i, "tag": "T%d" % i, "status_from": 500, "status_to": 599, "category": "server_5xx", "known": rng.random() < 0.3} for i in range(rng.randint(0, 3))],
             "hits": {"0": 3, "1": 1}, "samples": [{"tag": rng.choice(["Abc", "x y", None, "Q9", ""]), "n": 1} for _ in range(rng.randint(0, 4))],
             "ever": [d["id"] for d in defs if rng.random() < 0.3] + ["stop_hook_continuation"] * rng.randint(0, 1)}
    methods = ["arming", "meta", "move", "move_set", "all_off", "set_keep_on", "note_kept", "spends_since", "open_overrides", "use_override",
               "resent", "payers", "reset_rules", "end_rule", "reading", "set_reading", "end_prompts", "end_requested_steers", "continuations",
               "end_continuations", "options", "wordings", "set_option", "set_wording", "add_rule", "remove_rule", "rules", "rule_hits",
               "failure_samples", "set_global_hourly", "send_again_off", "ever_moved"]
    if rng.random() < 0.18:
        state["faults"] = {rng.choice(methods): rng.choice(["state", "stale", "refused:option_invalid", "refused:rules_full"])}
    capabilities = ids if rng.random() < 0.8 else ids + ["no_such_capability", None, 5]
    pick = lambda: rng.choice(capabilities)
    def valid_cap():
        return rng.choice(ids)
    def arm_step():
        cap = pick()
        d = next((each for each in defs if each["id"] == cap), None)
        body = {"capability": cap, "state": rng.choices(["armed", "shadow", "other", None, 3], [62, 28, 4, 3, 3])[0],
                "revision": "@rev:%s" % cap if d and rng.random() < 0.85 else rng.choice([0, 1, 2, "1", None, True]),
                "generation": rng.choices(["@gen", "@gen-1", "@gen+1", None, "x", 7], [70, 7, 3, 4, 4, 12])[0],
                "warnings": "@warn:%s" % cap if d and rng.random() < 0.8 else rng.choice([[], ["bogus"], None, "x", ["measurement_failed"], [5]]),
                "acknowledged_version": "@ver" if rng.random() < 0.8 else rng.choice([None, "other", 5]),
                "keep_on": rng.choices([False, True, "yes", None], [60, 30, 5, 5])[0],
                "actor": rng.choices(["dashboard", "mcp", "model", None, "tray"], [85, 5, 4, 3, 3])[0]}
        if d and rng.random() < 0.5:
            needed = [r for r in reg.requires(cap)]
            also = []
            for r in needed:
                if rng.random() < 0.9:
                    also.append({"capability": r, "revision": "@rev:%s" % r if rng.random() < 0.92 else 9, "warnings": "@warn:%s" % r if rng.random() < 0.92 else ["x"],
                                 "engine_version": "@ver" if rng.random() < 0.92 else "other"})
            if rng.random() < 0.05: also.append("not a dict")
            if rng.random() < 0.05: also.append({"capability": "ghost_cap"})
            if rng.random() < 0.04: also.append({"capability": r if needed else "x", "revision": "@rev:%s" % cap})
            body["also"] = also if rng.random() > 0.05 else rng.choice([None, "x", ()])
        elif rng.random() < 0.1:
            body["also"] = rng.choice([[], None, "x", [{"capability": "x"}]])
        return ["arm", body]
    def actor():
        return rng.choices(["dashboard", "mcp", "tray", "card", "tripwire", "model", None], [40, 15, 10, 10, 5, 5, 5])[0]
    def gen():
        return rng.choices(["@gen", "@gen-1", None, "x", 3], [75, 6, 6, 6, 7])[0]
    def step():
        kind = rng.choices(["arm", "disarm", "all_off", "keep", "hourly", "option", "wordings_view", "wording", "add_rule", "remove_rule", "rules_view",
                            "samples_view", "listing", "statement", "check", "warnings", "verdict", "current", "read", "sweep", "moved", "resender",
                            "trip", "kept", "set_env", "policy", "measured", "checked", "view", "live_view", "why", "edition_entered"],
                           [30, 9, 3, 7, 3, 7, 2, 4, 3, 2, 2, 2, 3, 3, 2, 2, 2, 6, 4, 6, 4, 3, 3, 2, 8, 1, 1, 1, 1, 1, 1, 1])[0]
        if kind == "arm": return arm_step()
        if kind == "disarm": return ["disarm", pick(), actor()]
        if kind == "all_off": return ["all_off", actor()]
        if kind == "edition_entered": return ["edition_entered"]
        if kind == "keep":
            on = rng.random() < 0.8
            again = rng.random() < 0.3
            words = (["keep_on"] if on else []) + (["send_again"] if again and on else [])
            return ["keep", {"capability": pick(), "keep_on": on if rng.random() < 0.96 else "x", "send_again": again if rng.random() < 0.96 else 1,
                             "generation": gen(), "confirmed": words if rng.random() < 0.85 else rng.choice([None, ["x"], "keep_on"]), "actor": actor()}]
        if kind == "hourly": return ["hourly", rng.choice([1, 12, 24, 25, 0, -1, "x", None, True]), gen(), actor()]
        if kind == "option":
            cap = rng.choice(ids + ["usage_meter", "usage_wrap_up", "usage_pause"]) if kind == "option" and rng.random() < 0.5 else pick()
            d = next((each for each in defs if each["id"] == cap), None)
            options = d["options"] if d else []
            key, value = (rng.choice(options)["key"], rng.choice([1, 2, 3, 5, 85, 90, 97, 100, 0, "x", 10000])) if options and rng.random() < 0.9 else (rng.choice(["days", "bogus", None, 5]), rng.choice([1, 2, "x"]))
            return ["option", cap, key, value, gen(), actor()]
        if kind == "wordings_view": return ["wordings_view", rng.choice(["usage_wrap_up", pick()])]
        if kind == "wording": return ["wording", rng.choice(["usage_wrap_up", pick()]), rng.choice(["wrap_custom_five_hour", "wrap_custom_weekly", "fleet_alias", "fleet_folder", "x", None]),
                                     rng.choice([None, "hello", "", "  ", "bad words", "x" * 40, 5]), gen(), actor()]
        if kind == "add_rule": return ["add_rule", rng.choice(["Abc", "", None, "x y", 5]), rng.choice([None, 500]), rng.choice([None, 599]), rng.choice(["server_5xx", "x"]), gen(), actor()]
        if kind == "remove_rule": return ["remove_rule", rng.choice([0, 1, 2, 101, 7, "x"]), gen(), actor()]
        if kind in ("rules_view", "samples_view", "listing", "current", "kept_", "policy", "measured", "checked", "view", "live_view", "why"): return [kind]
        if kind == "statement": return ["statement", valid_cap(), rng.choice([None, "en", "ko", "xx", "ja"])]
        if kind in ("check", "warnings"): return [kind, valid_cap()]
        if kind == "verdict": return ["verdict", rng.choice([str(m) for m in Measurement] + ["nope", ""])]
        if kind == "read":
            return ["read", {"live": rng.sample(ids, rng.randint(0, 2)), "view": rng.choice([None, None, a_view(compat)]) if rng.random() < 0.3 else None}]
        if kind == "sweep":
            core = {}
            for r in records:
                found = rng.random()
                core[r] = ("raises" if found < 0.08 else None if found < 0.25 else
                           {"interruption_id": r, "state": rng.choice(["submission_unknown", "queued", None]),
                            "last_claim_at": rng.choice([1799990000.0 + rng.randint(0, 9000), None, "x", True, 5.5]),
                            "last_error": rng.choice([None, "duplicate_marker", "x"])})
            return ["sweep", core]
        if kind == "moved":
            return ["moved", rng.choice([{"interruption_id": rng.choice(records), "last_claim_at": 1799990000.0 + rng.randint(0, 9000)}, {"interruption_id": 5}, "x", {}]),
                    rng.choice(["submission_unknown", "submission_unknown", "queued"])]
        if kind == "resender":
            return ["resender", {"interruption_id": rng.choice(records), "state": rng.choice(["submission_unknown", "queued"]), "last_claim_at": 1799990000.0 + rng.randint(0, 9000)}]
        if kind == "trip": return ["trip", rng.choice(ids + ["no_such_capability"]), rng.choice([o.value for o in OffReason] + ["nope"])]
        if kind == "kept": return ["kept", rng.choice(ids + ["no_such_capability"])]
        if kind == "set_env":
            change = {"view": a_view(compat, engine=rng.choice([ENGINE, OTHER])), "table_for": a_table(), "checked": a_checked(), "policy": a_policy()}
            return ["set_env", {key: change[key] for key in rng.sample(list(change), rng.randint(1, 3))}]
        raise AssertionError(kind)
    steps = [step() for _ in range(rng.randint(5, 22))]
    if rng.random() < 0.1:
        steps.insert(rng.randint(0, len(steps)), ["constants"])
    return {"registry": kind, "shipped_table": shipped_table, "catalogs": "made" if kind == "made" else rng.choices(["real", "incomplete", "undecodable"], [88, 7, 5])[0],
            "directory": None, "locale": rng.choice(["en", "ko", "ja"]), "view_given": view_given, "live_given": live_given, "measured_given": measured_given,
            "env": env, "state": state, "steps": steps}
'''

RUN = r'''
scratch_dirs = {"real": str(real), "made": str(made_dir), "incomplete": str(incomplete_dir), "undecodable": str(undecodable_dir)}
cases, ops = [], {}
for _ in range(count):
    sc = scenario()
    sc["directory"] = scratch_dirs[sc["catalogs"]]
    cases.append(["arming.scenario", sc])
for index in range(real_count):
    # Integration 5: the same steps over the real AdvancedState (the tag's and car-adv's), each on a home of its own.
    sc = scenario()
    sc["directory"] = scratch_dirs[sc["catalogs"]]
    sc.update({"real": True, "home": str(scratch / "real-homes" / ("%d" % index)), "state": {}})
    cases.append(["arming.scenario", sc])
ops["arming.scenario"] = run_scenario
finish(cases, ops)
'''


def source() -> str:
    return "SCENARIO_RUNNER_SOURCE = %r\n%s\n%s\n%s" % (SCENARIO_RUNNER, GENERATE, "", RUN)


class ArmingScenarioDiff(AdvDiff):
    def run_one(self, label: str, seed: int, count: int, minimum: int, real: int = 0):
        scratch = Path(self.reference_scratch) / ("arming-%s" % label)
        scratch.mkdir()
        # the generator needs `made_registry` (a module-level name its arm_step reads), and the runner is exec'd into it
        done = self.family(source(), str(advref.locales()), str(scratch), str(seed), str(count), str(real),
                           label="arming-" + label, expect_ops=minimum, chunk=100)
        shutil.rmtree(scratch, ignore_errors=True)
        return done

    def test_scenarios(self):
        scale = int(os.environ.get("CODEX_AR_ARMING_SCENARIOS", "360"))
        done = self.run_one("a", 20261125, scale, min(300, scale))
        steps = sum(len(case[1]["steps"]) for case in done["cases"])
        refusals = {}
        for case, result in zip(done["cases"], done["results"]):
            for step, answer in zip(case[1]["steps"], result["ok"]["results"]):
                if step[0] == "arm" and "ok" in answer and isinstance(answer["ok"], dict):
                    key = "done" if answer["ok"]["done"] else answer["ok"]["refusal"]
                    refusals[key] = refusals.get(key, 0) + 1
        RECORD.append("advpolicy arming: %d scenarios, %d steps, every answer, every call of the state and the edges (%d) and the state "
                      "left equal; arm answered %s" % (len(done["cases"]), steps,
                                                       sum(len(result["ok"]["log"]) for result in done["results"]),
                                                       ", ".join("%s %d" % item for item in sorted(refusals.items()))))

    def test_over_the_real_state(self):
        """Arming over `AdvancedState` itself, the tag's and car-adv's (Integration 5): each side on a home of its own, begun
        empty, every step's answer and the state's own readers after them (arming, meta, options, wordings, rules, the
        journal, the last reading) equal; the edges' calls too (the state's calls are not logged, they are the state's)."""
        scale = int(os.environ.get("CODEX_AR_ARMING_REAL", "240"))
        done = self.run_one("real", 20261201, 0, scale, real=scale)
        steps = sum(len(case[1]["steps"]) for case in done["cases"])
        moved = sum(1 for result in done["results"]
                    if any(row for row in result["ok"]["state"]["journal"]))
        RECORD.append("advpolicy arming over the real state: %d scenarios, %d steps, every answer and the state left (arming, "
                      "meta, options, wordings, rules, journal, reading) equal; %d scenarios wrote the journal"
                      % (len(done["cases"]), steps, moved))

    def test_more_scenarios(self):
        scale = int(os.environ.get("CODEX_AR_ARMING_SCENARIOS", "360"))
        self.run_one("b", 5150, scale, min(300, scale))

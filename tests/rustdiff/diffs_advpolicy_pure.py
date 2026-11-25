"""S7.1b, arming's pure functions: the decisions arming makes of a view, a row, a policy and a table, one case each.

`engine_version`, `compat_warning`, `warnings_for`, `standing` (the order of what overrides what), `departs`, `held_word`,
`offers_send_again`, `kept_words`, `_rises`, `_confirmed`, `_claimed_at`, `_carried`, and autocheck's `settled` and `grade`
(which arming reads: car-adv's `seam_autocheck` holds them until S7.2's autocheck port replaces it), over generated views of the
Compatibility Registry (every state, a state of the wrong type, a missing engine), rows (every state, keep on, send again,
the revision a person read or not), policies and tables of measurements, for every capability the edition has - the shipped
ones, the hidden ones and the installation's.
"""
from __future__ import annotations

from rustdiff.advdiff import AdvDiff

RECORD: list[str] = []

PURE = r'''
import itertools, random
from codex_auto_resume_advanced import arming, autocheck, registry, policy as policy_module
from codex_auto_resume_advanced.runtime import SENDING
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning, AutoResult, Measurement, OffReason, Verdict, KEPT_NOTICES)
rng = random.Random(77)
shipped = ([dump_def(each) for each in registry.DEFINITIONS] + [dump_def(each) for each, _need in registry.WAITING]
           + [dump_def(each) for each in registry.INSTALLED_ONLY])
ENGINE, OTHER = "codex-cli 0.167.0-alpha.3.2", "codex-cli 0.168.0"
STATES = ["COMPATIBLE", "VERIFIED", "CHECKED", "FAILED_HERE", "INCOMPATIBLE", "UNKNOWN", "WEIRD", "", 5, None]

def table_rows():
    rows = []
    for m in Measurement:
        if rng.random() < 0.55:
            rows.append([str(m), rng.choice(["pass", "pass", "fail", "blocked"]),
                         rng.choice([ENGINE, ENGINE, OTHER, "codex-cli 0.9.0-alpha.2", "codex-cli 0.167.0-alpha.3.1"])])
    return rows

def result_rows():
    return [[str(m), rng.choice(["pass", "fail", "unknown"])] for m in Measurement if rng.random() < 0.35]

def a_view(compat):
    if rng.random() < 0.05:
        return rng.choice([None, [], "x", 5, {}])
    caps = {}
    for cid in compat:
        kind = rng.random()
        if kind < 0.5:
            caps[cid] = {"state": rng.choice(STATES), "reason": rng.choice(["local_check_failed", "x", None])}
        elif kind < 0.6:
            caps[cid] = rng.choice([None, "COMPATIBLE", 5, []])
        elif kind < 0.7:
            caps[cid] = {"reason": "local_check_failed"}
    view = {"capabilities": caps if rng.random() > 0.08 else rng.choice([None, [], "x"])}
    view["engine"] = rng.choice([{"found": True, "version": ENGINE}, {"found": True, "version": OTHER}, {"version": 5},
                                 {"found": False}, None, "x", {"version": ""}])
    return view

def a_policy():
    return {"forbid": rng.random() < 0.15, "force_shadow": rng.random() < 0.2,
            "allowed": None if rng.random() < 0.6 else rng.sample([d["id"] for d in shipped], rng.randint(0, 50))}

def table_of(rows):
    return {Measurement(m): (Verdict(v), e) for m, v, e in rows}

def results_of(rows):
    return {Measurement(m): AutoResult(r) for m, r in rows}

def row_of(d, view, table, checked):
    if rng.random() < 0.08:
        return None
    state = rng.choice(["armed", "armed", "shadow", "off"])
    now = [str(w) for w in arming.warnings_for(build_def(d), view if isinstance(view, dict) else {}, table_of(table), checked=results_of(checked))]
    return {"state": state, "since": rng.choice([None, 1799990000.5]), "actor": rng.choice([None, "dashboard", "tripwire"]),
            "reason": rng.choice([None] + [o.value for o in OffReason]),
            "statement_revision": rng.choice([d["revision"], d["revision"], d["revision"] + 1, None]),
            "engine_version": rng.choice([ENGINE, OTHER, None, ENGINE]),
            "warnings": now if rng.random() < 0.6 else [w.value for w in ArmingWarning if rng.random() < 0.3],
            "keep_on": rng.random() < 0.2, "send_again": rng.random() < 0.1}

def typed_row(row):
    if row is None:
        return None
    return {"state": ArmingState(row["state"]), "since": row["since"], "actor": None if row["actor"] is None else Actor(row["actor"]),
            "reason": None if row["reason"] is None else OffReason(row["reason"]), "statement_revision": row["statement_revision"],
            "engine_version": row["engine_version"], "warnings": tuple(ArmingWarning(w) for w in row["warnings"]),
            "keep_on": row["keep_on"], "send_again": row["send_again"]}

def pol(shape):
    return policy_module.Policy(forbid=shape["forbid"], force_shadow=shape["force_shadow"],
                                allowed=None if shape["allowed"] is None else frozenset(shape["allowed"]))

cases, ops = [], {}
sending = sorted(str(p) for p in SENDING)
for d in shipped:
    compat = [d["compat"]] if d["compat"] else []
    for _ in range(40):
        view, table, checked = a_view(compat), table_rows(), result_rows()
        policy_shape = a_policy()
        row = row_of(d, view, table, checked)
        cases.append(["arming.pure.engine_version", view])
        cases.append(["arming.pure.compat_warning", view, d])
        cases.append(["arming.pure.warnings_for", d, view, table, rng.random() < 0.7, checked])
        cases.append(["arming.pure.standing", d, row, policy_shape, view, table, checked])
        cases.append(["arming.pure.departs", d, row])
        cases.append(["arming.pure.held_word", d, row, rng.choice(["off", "shadow", "armed"]), rng.choice([None, "failed_here", "engine_changed"]),
                      rng.choice([None, "engine_unknown", "compat_unknown"]), policy_shape])
        ms = [str(m) for m in rng.sample(list(Measurement), rng.randint(0, 5))]
        version = rng.choice([ENGINE, OTHER, None, "codex-cli 0.167.0-alpha.3.1", "x"])
        cases.append(["arming.pure.settled", ms[0] if ms else "m1", version, table, checked])
        cases.append(["arming.pure.grade", ms, version, table, checked])
    cases.append(["arming.pure.offers_send_again", d, sending])
for keep, again in itertools.product([False, True], repeat=2):
    cases.append(["arming.pure.kept_words", keep, again])
for held in [None] + [o.value for o in OffReason]:
    for notice in [str(n) for n in KEPT_NOTICES]:
        cases.append(["arming.pure.rises", held, notice])
for each in [None, [], ["measurement_failed"], ["x"], "x", 5, ["unmeasured", "unmeasured"], [5], ["engine_unknown", "failed_here"], {}, True]:
    cases.append(["arming.pure.confirmed", each])
for record in [None, {}, {"last_claim_at": 5.5}, {"last_claim_at": True}, {"last_claim_at": "x"}, {"last_claim_at": None},
               [], "x", {"last_claim_at": 1799990000.25}, {"last_claim_at": -1.0}, {"last_claim_at": 1e308}]:
    cases.append(["arming.pure.claimed_at", record])
for spent, key, claimed in [({"a": [1.0]}, "a", 1.0), ({"a": [1.0]}, "a", 1.0005), ({"a": [1.0]}, "a", 1.002), ({"a": [1.0]}, "a", None),
                            ({"a": []}, "a", 1.0), ({"a": [1.0]}, "b", 1.0), ({}, "a", None), ({"a": [5.0, 1.0]}, "a", 1.001),
                            ({"a": [5.0, 1.0]}, "a", 1.0011)]:
    cases.append(["arming.pure.carried", spent, key, claimed])
ops["arming.pure.engine_version"] = lambda view: arming.engine_version(view)
ops["arming.pure.compat_warning"] = lambda view, d: arming.compat_warning(view, build_def(d))
ops["arming.pure.warnings_for"] = lambda d, view, table, parts, checked: arming.warnings_for(
    build_def(d), view, table_of(table), parts=parts, checked=results_of(checked))
ops["arming.pure.standing"] = lambda d, row, policy_shape, view, table, checked: list(arming.standing(
    build_def(d), typed_row(row), pol(policy_shape), view, table_of(table), results_of(checked)))
ops["arming.pure.departs"] = lambda d, row: arming.departs(build_def(d), typed_row(row))
ops["arming.pure.offers_send_again"] = lambda d, sending_: arming.offers_send_again(build_def(d))
ops["arming.pure.kept_words"] = lambda keep, again: arming.kept_words(keep, again)
ops["arming.pure.held_word"] = lambda d, row, state, change, held, policy_shape: arming.held_word(
    build_def(d), typed_row(row), ArmingState(state), None if change is None else OffReason(change),
    None if held is None else ArmingWarning(held), pol(policy_shape))
ops["arming.pure.rises"] = lambda held, notice: arming._rises(None if held is None else OffReason(held), OffReason(notice))
ops["arming.pure.confirmed"] = lambda value: (lambda found: None if found is None else sorted(str(w) for w in found))(arming._confirmed(value))
ops["arming.pure.claimed_at"] = lambda record: arming._claimed_at(record)
ops["arming.pure.carried"] = lambda spent, key, claimed: arming._carried(spent, key, claimed)
ops["arming.pure.settled"] = lambda m, version, table, checked: autocheck.settled(Measurement(m), version, table_of(table), results_of(checked))
ops["arming.pure.grade"] = lambda ms, version, table, checked: (lambda found: [str(found[0]), found[1]])(
    autocheck.grade([Measurement(m) for m in ms], version, table_of(table), results_of(checked)))
finish(cases, ops)
'''


class ArmingPureDiff(AdvDiff):
    def test_pure_functions(self):
        done = self.family(PURE, label="arming-pure", expect_ops=8000)
        standing = [result["ok"] for case, result in zip(done["cases"], done["results"]) if case[0] == "arming.pure.standing"]
        words: dict = {}
        for found in standing:
            words[found[0]] = words.get(found[0], 0) + 1
        RECORD.append("advpolicy arming pure: %d cases equal - engine_version, compat_warning, warnings_for, standing (%s), departs, held_word, "
                      "offers_send_again, kept_words, rises, confirmed, claimed_at, carried, and autocheck's settled and grade"
                      % (len(done["cases"]), ", ".join("%s %d" % item for item in sorted(words.items()))))

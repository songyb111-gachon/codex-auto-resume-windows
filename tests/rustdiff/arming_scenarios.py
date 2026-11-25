"""The reference side of S7.1b's arming diff: a scenario is run through the tag's own `Arming` over an in-memory stand-in for
`AdvancedState` and stubs for what arming imports lazily, and what it answered - every step's result, every call it made of the
state and the edges, in order, and the state it left - is the answer the Rust `Arming` must give over the same stand-ins.

This file is a Python source that `diffs_advpolicy_arming.py` hands to the reference process (`advref.run`) after
`advdiff.PRELUDE`; it is not imported by the harness. The stand-ins' semantics are written twice, here and in
car-adv's example `advprobe` (ops_arming.rs), and kept deliberately small: what is under test is `Arming`, not the state
(S7.1a's) or the engine (S7.2's).

A scenario (JSON):

    {"registry": "shipped" | "made",           which registry (the shipped one, or four test-made ones that need each other)
     "catalogs": "real" | "incomplete",        where the statements are read from
     "locale": "en",                           l10n.current()
     "view_given": bool, "live_given": bool, "measured_given": bool,
     "env": {"view": view | "raises" | "notdict", "live": ..., "default_view": ..., "default_live": ...,
             "policy": {"forbid", "force_shadow", "allowed"} | "raises", "measured": [[m, v, e]] | "raises",
             "table_for": [[m, v, e]] | "raises", "checked": [[m, "pass"|"fail"|"unknown"]] | "raises",
             "order": "ok" | "order" | "warn", "clock": float, "sending": [points], "wording_limit": int, "placeholders": [..]},
     "state": {"rows": [[id, row]], "generation": n, "global_hourly": n, "faults": {method: "state"|"stale"|"refused:<word>"},
               "spends": [[cap, record, time]], "overrides": [...], "resent": [...], "payers": {...}, "reset_rules": [...],
               "credits": bool, "continuations": [...], "options": {...}, "wordings": {...}, "rules": [...], "hits": {...},
               "samples": [...], "ever": [...]},
     "steps": [[name, arg, ...], ...]}

A real-state scenario (`"real": true`, `"home": folder`) runs the same steps over the tag's own `AdvancedState` on a
home of its own (`<home>/py`; car-adv's probe uses `<home>/rs`), the state begins empty, and the state left is what the
state's own readers say (`arming`, `meta`, the options and wordings of every capability, `rules`, `journal`, `reading`).

A step's argument `"@gen"` is the generation the state holds now, `"@rev:<id>"` a capability's revision, `"@warn:<id>"` the
warnings that hold now (the pure `warnings_for` over the environment), `"@ver"` the engine version of the view, `"@now"` the
clock's next reading; a list or dict of them is resolved inside.
"""

SCENARIO_RUNNER = r'''
import copy
import json
import time
from unittest.mock import patch
from codex_auto_resume.domain.plug import Point
from codex_auto_resume import l10n
from codex_auto_resume_advanced import arming, autocheck, compatdata, policy, registry, statement
from codex_auto_resume_advanced.control import hookplugin, powertasks
from codex_auto_resume_advanced.engine import account, usage, wrapwords
from codex_auto_resume_advanced.state import Refused, StaleGeneration, StateError
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning, AutoResult, Measurement, OffReason,
                                                   OptionKey, OverrideKind, Refusal, Verdict, WordingKey)

MADE = ["alpha_cap", "beta_cap", "gamma_cap", "delta_cap"]

def made_definitions(shipped):
    def lone(i, **changes):
        d = copy.deepcopy(shipped[i])
        d.update(changes)
        return d
    return [lone(0, id="alpha_cap", journal_prefix="alp", requires=[]), lone(1, id="beta_cap", journal_prefix="bet", requires=["alpha_cap"]),
            lone(2, id="gamma_cap", journal_prefix="gam", requires=["beta_cap", "alpha_cap"]),
            lone(3, id="delta_cap", journal_prefix="del", requires=[], resends=False)]

def table_of(rows):
    return {Measurement(m): (Verdict(v), e) for m, v, e in rows}

def results_of(rows):
    return {Measurement(m): AutoResult(r) for m, r in rows}

class Fault(Exception):
    pass

class FakeState:
    def __init__(self, sc, registry_, log):
        spec = sc["state"]
        self.registry, self.paths, self.log = registry_, "paths", log
        self.rows = [[cap, copy.deepcopy(row)] for cap, row in spec["rows"]]
        self.generation, self.hourly = spec.get("generation", 1), spec.get("global_hourly", 24)
        self.faults = spec.get("faults", {})
        self.spends, self.overrides = spec.get("spends", []), copy.deepcopy(spec.get("overrides", []))
        self.resent_keys, self.payer_table = set(spec.get("resent", [])), spec.get("payers", {})
        self.reset_rules_, self.credits = copy.deepcopy(spec.get("reset_rules", [])), spec.get("credits", False)
        self.conts, self.options_ = copy.deepcopy(spec.get("continuations", [])), copy.deepcopy(spec.get("options", {}))
        self.wordings_, self.rules_ = copy.deepcopy(spec.get("wordings", {})), copy.deepcopy(spec.get("rules", []))
        self.hits, self.samples = spec.get("hits", {}), spec.get("samples", [])
        self.ever, self.next_rule = set(spec.get("ever", [])), 100

    def call(self, name, *args):
        self.log.append([name, *args])
        fault = self.faults.get(name)
        if fault == "state":
            raise StateError("down")
        if fault == "stale":
            raise StaleGeneration("stale")
        if fault and fault.startswith("refused:"):
            raise Refused(Refusal(fault[8:]))

    def row(self, cap):
        for held, row in self.rows:
            if held == cap:
                return row
        return None

    def put(self, cap, row):
        for pair in self.rows:
            if pair[0] == cap:
                pair[1] = row
                return
        self.rows.append([cap, row])

    def stale(self, generation):
        if generation is not None and generation != self.generation:
            raise StaleGeneration("stale")

    def arming(self):
        self.call("arming")
        found = {}
        for cap, row in self.rows:
            if self.registry.get(cap) is None:
                continue
            found[cap] = {"state": ArmingState(row["state"]), "since": row["since"],
                          "actor": None if row["actor"] is None else Actor(row["actor"]),
                          "reason": None if row["reason"] is None else OffReason(row["reason"]),
                          "statement_revision": row["statement_revision"], "engine_version": row["engine_version"],
                          "warnings": tuple(ArmingWarning(w) for w in row["warnings"]),
                          "keep_on": row["keep_on"], "send_again": row["send_again"]}
        return found

    def meta(self):
        self.call("meta")
        return {"generation": self.generation, "global_hourly": self.hourly}

    def ever_moved(self, capability):
        self.call("ever_moved", capability)
        return capability in self.ever

    def write(self, cap, state, actor, reason, revision, engine_version, warnings, at, keep=False):
        self.put(cap, {"state": state, "since": at if state != "off" else None, "actor": actor, "reason": reason,
                       "statement_revision": revision if state != "off" else None,
                       "engine_version": engine_version if state != "off" else None,
                       "warnings": [w for w in (warnings or [])] if state != "off" else [], "keep_on": keep, "send_again": False})
        self.ever.add(cap)

    def move(self, capability, state, *, actor, reason=None, revision=None, engine_version=None, warnings=None,
             generation=None, at=None):
        self.call("move", capability, str(state), str(actor), None if reason is None else str(reason), revision, engine_version,
                  None if warnings is None else [str(w) for w in warnings], generation, at)
        self.stale(generation)
        row = self.row(capability)
        if state == ArmingState.OFF:
            if row is None or row["state"] == "off":
                return False, self.generation
            self.write(capability, "off", str(actor), None if reason is None else str(reason), None, None, None, at)
        else:
            self.write(capability, str(state), str(actor), None, revision, engine_version, [str(w) for w in warnings or []], at)
        self.generation += 1
        return True, self.generation

    def move_set(self, moves, *, actor, generation, at=None, keep=()):
        self.call("move_set", [[c, str(s), r, e, [str(w) for w in ws]] for c, s, r, e, ws in moves], str(actor), generation, at, list(keep))
        self.stale(generation)
        for cap, state, revision, engine_version, warnings in moves:
            self.write(cap, str(state), str(actor), None, revision, engine_version, [str(w) for w in warnings], at, keep=cap in keep)
        self.generation += 1
        return len(moves), self.generation

    def all_off(self, *, actor, reason, at=None):
        self.call("all_off", str(actor), str(reason), at)
        count = 0
        for cap, row in self.rows:
            if row["state"] != "off":
                count += 1
                self.write(cap, "off", str(actor), str(reason), None, None, None, at)
        if count:
            self.generation += 1
        return count, self.generation

    def set_keep_on(self, capability, on, *, send_again=False, actor, generation=None, at=None):
        self.call("set_keep_on", capability, on, send_again, str(actor), generation, at)
        self.stale(generation)
        row = self.row(capability)
        if row is None or row["state"] == "off":
            raise Refused(Refusal.NOT_ON)
        row["keep_on"], row["send_again"] = on, bool(on and send_again)
        self.generation += 1
        return self.generation

    def send_again_off(self, capability, *, reason, at=None):
        self.call("send_again_off", capability, str(reason), at)
        row = self.row(capability)
        if row is None or not row["send_again"]:
            return False
        row["send_again"], row["reason"] = False, str(reason)
        return True

    def note_kept(self, capability, reason, *, at=None):
        self.call("note_kept", capability, str(reason), at)
        row = self.row(capability)
        if row is None or row["state"] == "off":
            return False
        row["reason"] = str(reason)
        return True

    def set_global_hourly(self, value, *, generation, actor, at=None):
        self.call("set_global_hourly", value, generation, str(actor), at)
        self.stale(generation)
        self.hourly = value
        self.generation += 1
        return self.generation

    def spends_since(self, capability, since):
        self.call("spends_since", capability, since)
        found = {}
        for cap, record, time_ in self.spends:
            if cap == capability and time_ >= since:
                found.setdefault(record, []).append(time_)
        return found

    def open_overrides(self, kind):
        self.call("open_overrides", str(kind))
        return [{"interruption_id": o["interruption_id"], "capability": o["capability"], "created_at": o["created_at"]}
                for o in self.overrides if o["kind"] == str(kind) and not o.get("used")]

    def use_override(self, key, capability, *, at=None):
        self.call("use_override", key, capability, at)
        for o in self.overrides:
            if o["interruption_id"] == key and o["capability"] == capability and not o.get("used"):
                o["used"] = True
                return

    def resent(self, key):
        self.call("resent", key)
        return key in self.resent_keys

    def payers(self, key, claimed_at):
        self.call("payers", key, claimed_at)
        found = {}
        for cap, time_ in self.payer_table.get(key, []):
            found.setdefault(cap, []).append(time_)
        return found

    def reset_rules(self):
        self.call("reset_rules")
        return copy.deepcopy(self.reset_rules_)

    def end_rule(self, rule_id, state, reason, *, at=None):
        self.call("end_rule", rule_id, str(state), str(reason), at)

    def reading(self):
        self.call("reading")
        return {"credits": 5 if self.credits else None}

    def set_reading(self, **fields):
        self.call("set_reading", sorted(fields.items()))
        self.credits = False

    def end_prompts(self, reason, *, at=None):
        self.call("end_prompts", str(reason), at)

    def end_requested_steers(self, reason, *, at=None):
        self.call("end_requested_steers", str(reason), at)

    def continuations(self, pending=False):
        self.call("continuations", pending)
        return copy.deepcopy(self.conts)

    def end_continuations(self, reason, *, capability=None, at=None):
        self.call("end_continuations", str(reason), capability, at)

    def options(self, capability):
        self.call("options", capability)
        return {OptionKey(key): value for key, value in self.options_.get(capability, {}).items()}

    def wordings(self, capability):
        self.call("wordings", capability)
        return {WordingKey(key): value for key, value in self.wordings_.get(capability, {}).items()}

    def set_option(self, capability, key, value, *, generation, actor, at):
        self.call("set_option", capability, key, value, generation, str(actor), at)
        self.stale(generation)
        option = self.registry.get(capability).option(key) if isinstance(key, str) else None
        if option is None or not option.takes(value):
            raise Refused(Refusal.OPTION_INVALID)
        self.options_.setdefault(capability, {})[str(option.key)] = value
        self.generation += 1
        return self.generation

    def set_wording(self, capability, key, words, *, generation, actor, at):
        self.call("set_wording", capability, key, words, generation, str(actor), at)
        self.stale(generation)
        if key not in [str(each) for each in self.registry.get(capability).wordings]:
            raise Refused(Refusal.OPTION_INVALID)
        self.wordings_.setdefault(capability, {})[key] = words
        self.generation += 1
        return self.generation

    def add_rule(self, tag, status_from, status_to, category, *, generation, actor, at):
        self.call("add_rule", tag, status_from, status_to, category, generation, str(actor), at)
        self.stale(generation)
        if not isinstance(tag, str) or not tag:
            raise Refused(Refusal.RULE_SHAPE)
        if len(self.rules_) >= 10:
            raise Refused(Refusal.RULES_FULL)
        self.next_rule += 1
        rule = {"rule_id": self.next_rule, "tag": tag, "status_from": status_from, "status_to": status_to,
                "category": category, "known": False}
        self.rules_.append(rule)
        self.generation += 1
        return dict(rule), self.generation

    def remove_rule(self, rule, *, generation, actor, at):
        self.call("remove_rule", rule, generation, str(actor), at)
        self.stale(generation)
        kept = [each for each in self.rules_ if each["rule_id"] != rule]
        if len(kept) == len(self.rules_):
            raise Refused(Refusal.UNKNOWN_RULE)
        self.rules_ = kept
        self.generation += 1
        return self.generation

    def rules(self):
        self.call("rules")
        return copy.deepcopy(self.rules_)

    def rule_hits(self, since):
        self.call("rule_hits", since)
        return {int(key): value for key, value in self.hits.items()}

    def failure_samples(self, since):
        self.call("failure_samples", since)
        return copy.deepcopy(self.samples)

    def dump(self):
        return {"rows": [[cap, row] for cap, row in self.rows], "generation": self.generation, "global_hourly": self.hourly,
                "overrides": self.overrides, "credits": self.credits, "options": self.options_, "wordings": self.wordings_,
                "rules": self.rules_, "ever": sorted(self.ever)}

class CoreView:
    def __init__(self, table, log):
        self.table, self.log = table, log
    def get(self, key):
        self.log.append(["core_get", key])
        found = self.table.get(key)
        if found == "raises":
            raise RuntimeError("cannot answer")
        return found

def tag_ok(tag):
    return isinstance(tag, str) and 0 < len(tag) <= 64 and tag[0].isascii() and tag[0].isalpha() and all(c.isascii() and c.isalnum() for c in tag)

def run_scenario(sc):
    sc = json.loads(json.dumps(sc))
    log = []
    env = copy.deepcopy(sc["env"])
    shipped = [dump_def(each) for each in registry.DEFINITIONS]
    clock_now = [env.get("clock", 1800000000.0)]
    def clock():
        clock_now[0] += 1.0
        return clock_now[0]
    if sc["registry"] == "shipped":
        made_registry = registry.Registry(registry.DEFINITIONS + registry.offered(table_of(sc.get("shipped_table", []))))
    else:
        made_registry = registry.Registry([build_def(each) for each in made_definitions(shipped)])
    real = bool(sc.get("real"))
    if real:
        # Integration 5: the same Arming over the tag's own AdvancedState on a home of its own (never this machine's).
        from pathlib import Path
        from codex_auto_resume import config
        from codex_auto_resume_advanced.state import AdvancedState
        home = Path(sc["home"]) / "py"
        home.mkdir(parents=True, exist_ok=True)
        fixed = env.get("clock", 1800000000.0)
        state = AdvancedState(config.Paths(str(home)), registry=made_registry, clock=lambda: fixed)
    else:
        state = FakeState(sc, made_registry, log)
    def generation_now():
        return state.meta()["generation"] if real else state.generation
    def real_dump():
        ids = [d.id for d in made_registry]
        return {"arming": state.arming(), "meta": state.meta(), "options": {c: dict(state.options(c)) for c in ids},
                "wordings": {c: dict(state.wordings(c)) for c in ids}, "rules": state.rules(),
                "journal": state.journal(limit=500),
                # READING is a frozenset: with no file its keys come in the interpreter's hash order, which no run repeats.
                "reading": dict(sorted(state.reading().items()))}

    def view_fn():
        log.append(["view"])
        found = env["view"]
        if found == "raises":
            raise RuntimeError("view")
        return ["not", "a", "dict"] if found == "notdict" else found
    def live_fn():
        log.append(["live"])
        found = env["live"]
        if found == "raises":
            raise RuntimeError("live")
        return ["not", "a", "dict"] if found == "notdict" else found
    def policy_fn():
        log.append(["policy"])
        found = env["policy"]
        if found == "raises":
            raise RuntimeError("policy")
        return policy.Policy(forbid=found["forbid"], force_shadow=found["force_shadow"],
                             allowed=None if found["allowed"] is None else frozenset(found["allowed"]))
    def measured_fn():
        log.append(["measured"])
        found = env["measured"]
        if found == "raises":
            raise RuntimeError("measured")
        return table_of(found)

    def table_for(paths, engine):
        log.append(["table_for", engine])
        found = env["table_for"]
        if found == "raises":
            raise RuntimeError("table_for")
        return table_of(found)
    def results_for(paths, engine):
        log.append(["checked_for", engine])
        found = env["checked"]
        if found == "raises":
            raise RuntimeError("checked")
        return results_of(found)
    def default_view(paths):
        log.append(["default_view"])
        found = env["default_view"]
        if found == "raises":
            raise RuntimeError("default view")
        return found
    def default_live(paths):
        log.append(["default_live_view"])
        found = env["default_live"]
        if found == "raises":
            raise RuntimeError("default live")
        return found
    def hook_follow(paths, home, armed, *rest):
        log.append(["hook_follow", armed])
    def power_follow(paths, armed):
        log.append(["power_tasks_follow", armed])
    def forget(state_, secrets=None):
        log.append(["account_forget"])
        return True
    def touched(key):
        log.append(["usage_touched", str(key)])
        return [300] if "five" in str(key) else [10080] if "weekly" in str(key) else []
    def order_problem(values, windows_=None):
        log.append(["usage_order_problem", sorted([cap, sorted([str(k), v] for k, v in options.items())] for cap, options in values.items()), list(windows_)])
        return ("order", None) if env["order"] == "order" else (None, "stop_before_words" if env["order"] == "warn" else None)
    def previews(state_, now):
        log.append(["usage_previews", now])
        return {300: "five words", 10080: None}
    def check_custom(words):
        log.append(["wording_problem", words])
        if not isinstance(words, str) or not words.strip():
            raise wrapwords.WordingError("empty")
        if len(words) > 30:
            raise wrapwords.WordingError("too_long")
        if "bad" in words:
            raise wrapwords.WordingError("marker")
        return words
    def aggregated(samples):
        log.append(["aggregated", copy.deepcopy(samples)])
        return {"count": len(samples), "tags": sorted({s["tag"] for s in samples if s.get("tag") is not None})}
    def tag_problem(tag):
        return None if tag_ok(tag) else "bad"

    directory = sc["directory"]
    os_env = __import__("os").environ
    os_env[l10n.ENV_LANG] = sc["locale"]
    l10n._preference = l10n.SYSTEM
    catalogs = statement.Catalogs(directory)

    with patch.object(compatdata, "table_for", table_for), patch.object(autocheck, "results_for", results_for), \
            patch.object(arming, "_view_of", default_view), patch.object(arming, "_live_view_of", default_live), \
            patch.object(hookplugin, "follow", hook_follow), patch("codex_auto_resume_advanced.codex.inuse.home", lambda paths=None: "home"), \
            patch.object(powertasks, "follow", power_follow), patch.object(account, "forget", forget), \
            patch.object(usage, "touched", touched), patch.object(usage, "order_problem", order_problem), \
            patch.object(usage, "previews", previews), patch.object(wrapwords, "check_custom", check_custom), \
            patch.object(arming, "aggregated", arming.aggregated if real else aggregated), \
            patch.object(arming, "tag_problem", arming.tag_problem if real else tag_problem):
        engine = arming.Arming(state, catalogs=catalogs, policy=policy_fn,
                               view=view_fn if sc["view_given"] else None,
                               measured=measured_fn if sc["measured_given"] else None, clock=clock,
                               live=live_fn if sc["live_given"] else None)
        results = []
        def plain_view():
            held = env["view"] if sc["view_given"] else env["default_view"]
            return held if isinstance(held, dict) else {}
        def table_now():
            if sc["measured_given"]:
                return table_of(env["measured"]) if env["measured"] != "raises" else {}
            return table_of(env["table_for"]) if env["table_for"] != "raises" else {}
        def checked_now():
            return results_of(env["checked"]) if env["checked"] != "raises" else {}
        def resolve(value):
            if isinstance(value, str) and value.startswith("@"):
                if value == "@gen":
                    return generation_now()
                if value == "@gen+1":
                    return generation_now() + 1
                if value == "@gen-1":
                    return generation_now() - 1
                if value == "@ver":
                    return arming.engine_version(plain_view())
                if value == "@now":
                    return clock()
                if value.startswith("@rev:"):
                    return made_registry.get(value[5:]).revision
                if value.startswith("@warn:"):
                    return [str(w) for w in arming.warnings_for(made_registry.get(value[6:]), plain_view(), table_now(), checked=checked_now())]
                return value
            if isinstance(value, list):
                return [resolve(each) for each in value]
            if isinstance(value, dict):
                return {key: resolve(each) for key, each in value.items()}
            return value
        def definition(cap):
            return made_registry.get(cap)
        def step(name, args):
            args = [resolve(each) for each in args]
            if name == "arm":
                a = args[0]
                return engine.arm(a.get("capability"), state=a.get("state"), revision=a.get("revision"), generation=a.get("generation"),
                                  acknowledged_version=a.get("acknowledged_version"), warnings=a.get("warnings"), also=a.get("also"),
                                  keep_on=a.get("keep_on", False), actor=a.get("actor", "dashboard"))
            if name == "disarm":
                return engine.disarm(args[0], actor=args[1])
            if name == "all_off":
                return engine.all_off(actor=args[0])
            if name == "edition_entered":
                return engine.edition_entered()
            if name == "keep":
                a = args[0]
                return engine.set_keep_on(a.get("capability"), a.get("keep_on"), send_again=a.get("send_again", False),
                                          generation=a.get("generation"), confirmed=a.get("confirmed"), actor=a.get("actor", "dashboard"))
            if name == "hourly":
                return engine.set_global_hourly(args[0], generation=args[1], actor=args[2])
            if name == "option":
                return engine.set_option(args[0], args[1], args[2], generation=args[3], actor=args[4])
            if name == "wordings_view":
                return engine.wordings_view(args[0])
            if name == "wording":
                return engine.set_wording(args[0], args[1], args[2], generation=args[3], actor=args[4])
            if name == "add_rule":
                return engine.add_rule(args[0], args[1], args[2], args[3], generation=args[4], actor=args[5])
            if name == "remove_rule":
                return engine.remove_rule(args[0], generation=args[1], actor=args[2])
            if name == "rules_view":
                return engine.rules_view()
            if name == "samples_view":
                return engine.samples_view()
            if name == "listing":
                return engine.listing()
            if name == "statement":
                return engine.statement(definition(args[0]), args[1])
            if name == "check":
                return engine.check(definition(args[0]))
            if name == "warnings":
                return [str(w) for w in engine.warnings(definition(args[0]))]
            if name == "verdict":
                return engine.verdict(args[0])
            if name == "current":
                return engine.current()
            if name == "read":
                a = args[0]
                view = None
                if a.get("view") is not None:
                    view = a["view"]
                states, since, failed = engine.read(view=view, policy=None, live=tuple(a.get("live", [])))
                return {"states": states, "since": since, "failed": failed}
            if name == "sweep":
                engine.sweep(CoreView(args[0], log))
                return None
            if name == "moved":
                return engine.moved(args[0], args[1])
            if name == "resender":
                states = engine.current()
                found = engine.resender(args[0], states)
                return None if found is None else [found[0].id, str(found[1])]
            if name == "trip":
                return engine.trip(args[0], OffReason(args[1]))
            if name == "kept":
                return engine.kept(args[0])
            if name == "view":
                return engine.view()
            if name == "live_view":
                return engine.live_view()
            if name == "measured":
                return sorted([str(k), str(v), e] for k, (v, e) in engine.measured().items())
            if name == "checked":
                return sorted([str(k), str(v)] for k, v in engine.checked().items())
            if name == "policy":
                return engine.policy().as_json()
            if name == "why":
                return dict(engine.why)
            if name == "set_env":
                env.update(args[0])
                return None
            if name == "constants":
                return {"SURFACES": sorted(str(a) for a in arming.SURFACES), "TRIPPING": [[str(w), str(r)] for w, r in arming.TRIPPING.items()],
                        "SUBMISSION_UNKNOWN": arming.SUBMISSION_UNKNOWN, "SAME_CLAIM": arming.SAME_CLAIM, "DUPLICATE": arming.DUPLICATE,
                        "RESEND_WATCH": arming.RESEND_WATCH, "CREDIT": arming.CREDIT, "ACCOUNT": account.CAPABILITY,
                        "HOOK": hookplugin.CAPABILITY, "POWER": powertasks.CAPABILITY if hasattr(powertasks, "CAPABILITY") else "power_after_tasks",
                        "RULES_LIMIT": arming.RULES_LIMIT, "RECENT_DAYS": arming.RECENT_DAYS, "DAY": arming.DAY,
                        "METER": usage.METER, "WRAP_UP": usage.WRAP_UP, "PAUSE": usage.PAUSE, "ONCE_MORE": arming.ONCE_MORE.id,
                        "GLOBAL_HOURLY": arming.GLOBAL_HOURLY}
            raise AssertionError("no such step " + name)
        for name, *args in sc["steps"]:
            try:
                results.append({"ok": norm(step(name, args))})
            except Exception as error:
                results.append({"error": type(error).__name__})
    return {"results": results, "log": norm(log), "state": norm(real_dump() if real else state.dump())}
'''

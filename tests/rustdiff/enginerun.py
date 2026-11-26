"""Engine traces (S4.1): one scenario run step by step on one side - the reference's Engine, or car-engine's through
car-harness - and everything the product would use recorded after each step.

This file is run in two interpreters, so it imports nothing of the product and nothing of this checkout's tests: the
reference's side runs in the tag's own Python (PYTHONPATH the tag's src, `enginediff.SCRIPT`), the Rust side in the
test process. Both load the tag's own `tests/codexsim.py` (`codexsim` is handed in), so the two worlds are built by
the same code, call for call, with the same ids: `new_id` is a counter here, so a turn, a queue item and a client id
are the same on both sides.

A scenario is a list of steps (`run`). After each step the trace holds: the step's own answer (or the class of what
it raised), the engine's log lines and notifications since the last step, every backend call it made (in order, with
its arguments), and the whole state store, dumped table by table, row by row, each value with its type - so any
decision, state write, journal entry, notice, announcement and launch request that differs, differs in the trace.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
T1 = "11111111-1111-7111-8111-111111111111"
T2 = "22222222-2222-7222-8222-222222222222"
T3 = "33333333-3333-7333-8333-333333333333"
LANG = "CODEX_AUTO_RESUME_LANG"


class Ids:
    """codexsim's `new_id`, made a counter: the n-th id of a side is the n-th id of the other."""

    def __init__(self):
        self.count = 0

    def __call__(self) -> str:
        self.count += 1
        return "00000000-0000-4000-8000-%012x" % self.count


def plain(value):
    """A value as JSON carries it: tuples become lists, so both sides' traces read the same."""
    return json.loads(json.dumps(value))


def dump(state_dir: Path):
    """The store, every table and every row in rowid order, each value with its type; and the other files kept."""
    path = state_dir / "state.sqlite"
    found = {"files": sorted(str(p.relative_to(state_dir)).replace("\\", "/") for p in state_dir.rglob("*")
                             if p.is_file() and not p.name.startswith("state.sqlite"))}
    if not path.exists():
        found["tables"] = None
        return found
    with closing(sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)) as db:
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            try:
                rows = db.execute('SELECT * FROM "%s" ORDER BY rowid' % name).fetchall()
            except sqlite3.OperationalError:
                rows = db.execute('SELECT * FROM "%s"' % name).fetchall()
            tables[name] = [[[type(v).__name__, repr(v) if isinstance(v, float) else v] for v in row] for row in rows]
        found["tables"] = tables
        found["user_version"] = db.execute("PRAGMA user_version").fetchone()[0]
    return found


# ------------------------------------------------------------------ the Codex side (test_engine's own helpers)
def fail_turn(sim, home, thread_id, turn_id, *, usage=False, code="serverOverloaded", reset=None, error_json=None,
              completed=None):
    completed = int(home.clock()) if completed is None else completed
    columns = {"status": "failed", "completed_at": completed}
    if usage:
        events = []
        if reset is not None:
            events.append({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
                "limit_id": "codex", "primary": {"used_percent": 100, "resets_at": reset}}}})
        events.append({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn_id,
                                                        "error": {"codex_error_info": "usage_limit_exceeded"}}})
        columns["rollout_end_byte_offset"] = home._append(thread_id, events)
        columns["error_json"] = sim.USAGE_ERROR
    else:
        columns["error_json"] = error_json or sim.transient_error(code)
    home.set_turn(thread_id, turn_id, **columns)
    home.catch_up(thread_id)
    return turn_id


def dispatch_and_fail(sim, home, thread_id, *, usage=False, progress=False, reset=None, code="serverOverloaded"):
    turn = home.dispatch(thread_id, status="inProgress", progress=progress)
    if turn is None:
        return None
    return fail_turn(sim, home, thread_id, turn, usage=usage, reset=reset, code=code)


def archive(sim, home, thread_id):
    with home._db("state_5.sqlite") as db:
        db.execute("UPDATE threads SET archived=1 WHERE id=?", (thread_id,))


def drop_projection_table(sim, home):
    with home._db("thread_history_1.sqlite") as db:
        db.execute("DROP TABLE thread_history_projection_state")


def raw_turn(sim, home, **values):
    row = {"thread_id": T1, "turn_id": "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa", "rollout_ordinal": 1,
           "status": "failed", "error_json": sim.USAGE_ERROR, "started_at": sim.BASE, "completed_at": sim.BASE}
    row.update(values)
    with home._db("thread_history_1.sqlite") as db:
        db.execute("DELETE FROM thread_turns")
        db.execute("INSERT INTO thread_turns (%s) VALUES (%s)"
                   % (",".join(row), ",".join("?" for _ in row)), tuple(row.values()))


def set_project(sim, home, thread_id, project_id=None, cwd=None):
    with home._db("state_5.sqlite") as db:
        db.execute("UPDATE threads SET project_id=?, cwd=? WHERE id=?", (project_id, cwd, thread_id))


def history_aside(sim, home, aside=True):
    """Codex's history database cannot be opened for a while (moved aside), or is back."""
    path, moved = home.root / "thread_history_1.sqlite", home.root / "thread_history_1.sqlite.aside"
    os.replace(path, moved) if aside else os.replace(moved, path)


def edit_head(sim, home, thread_id, text="edited by the person"):
    """A person edits the item at the head of a conversation's queue in Codex."""
    queued = home.queued(thread_id)
    if queued:
        home.edit_queued(queued[0], text)
    return bool(queued)


def remove_head(sim, home, thread_id):
    """The item at the head of a conversation's queue is removed in Codex."""
    queued = home.queued(thread_id)
    return home.remove_queued(queued[0]) if queued else False


def duplicate_head(sim, home, thread_id):
    """Codex's history holds the text of the queue's head twice: two turns each starting with it."""
    with home._db("queue_1.sqlite") as db:
        row = db.execute("SELECT payload_json FROM queued_items WHERE thread_id=? ORDER BY queue_order LIMIT 1",
                         (thread_id,)).fetchone()
    if row is None:
        return False
    text = json.loads(row[0])["UserInput"]["content"][0]["text"]
    home.add_turn(thread_id, None, "completed", user_text=text)
    home.add_turn(thread_id, None, "completed", user_text=text)
    return True


HELPERS = {"edit_head": edit_head, "remove_head": remove_head, "duplicate_head": duplicate_head,
           "fail_turn": fail_turn, "dispatch_and_fail": dispatch_and_fail, "archive": archive,
           "drop_projection_table": drop_projection_table, "raw_turn": raw_turn, "set_project": set_project,
           "history_aside": history_aside}


class Recorder:
    """codexsim.SimBackend with every call written down, in order, with its arguments."""

    def __init__(self, sim, calls):
        self.sim, self.calls = sim, calls
        # The attributes the engine reads with getattr(backend, name, default) (review 6, S4): absent until a scenario
        # names one (`backend` step, `attrs`); `holder` is a conversation -> answer map, called as backend.holder(t).
        self.attrs = {}

    def __getattr__(self, name):
        attrs = self.__dict__.get("attrs") or {}
        if name not in attrs:
            raise AttributeError(name)
        value = attrs[name]
        if name == "holder":
            return lambda thread_id: value.get(thread_id)
        if name == "protocol_results" and isinstance(value, dict):
            # The transport's own shape: method -> (result, time).
            return {method: tuple(found) if isinstance(found, list) else found for method, found in value.items()}
        return value

    def app_identity(self):
        self.calls.append(["app_identity"])
        return self.sim.app_identity()

    def loaded(self, thread_id, app_identity):
        self.calls.append(["loaded", thread_id, app_identity])
        return self.sim.loaded(thread_id, app_identity)

    def usage(self):
        self.calls.append(["usage"])
        return self.sim.usage()

    def send(self, thread_id, prompt, *, launch_guard=None, permitted=None, noted=False):
        if not noted:                       # car-engine's side writes it down before its guard (backend.send_noted)
            self.calls.append(["send", thread_id, prompt])
        if permitted is False:
            return {"outcome": "not_started", "error_code": "queue_consent_refused"}
        return self.sim.send(thread_id, prompt, launch_guard=launch_guard)

    def delete_queue(self, thread_id, queue_id):
        self.calls.append(["delete_queue", thread_id, queue_id])
        return self.sim.delete_queue(thread_id, queue_id)


class ScriptRaise(Exception):
    """A scripted hook that fails: the reference's `consult` and car-policy's `Guarded` both give NULL's answer in its
    place."""


class ScriptPanic(Exception):
    """A scripted hook that panics (D15): on the reference's side it is an exception like any other."""


def norm(value):
    """What a hook was handed, as the trace holds it: sets as sorted lists, enums as their words, tuples as lists."""
    if isinstance(value, dict):
        return {str(key): norm(each) for key, each in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(norm(each) for each in value)
    if isinstance(value, (list, tuple)):
        return [norm(each) for each in value]
    if isinstance(value, str) and type(value) is not str:
        return str(getattr(value, "value", value))          # a str enum's word
    return value


class Script:
    """The scripted plug's answers (review 6, S3), one object for both sides: the reference's Engine is handed a
    `domain.plug.Plug` that asks it, and car-engine's plug asks it back over the pipe (`plug.<hook>`).

    `spec` = {"wants": [point words the plug wants], "rules": {hook: [rule, ...]}}; a hook is one of gate, text, outcome,
    schedule, moved, delivery, unloaded, admission, sessions, eligibility, notice, sender. A rule is
    {"when": {fact: value, ...}, "answer": A, "skip": k, "times": n}: the first rule whose `when` all hold - the facts
    are the record's fields beside `name` (gate), `to` (moved), `outcome` (outcome) and `due_at` (schedule) - and whose
    `times` is not used up answers; no rule is DEFER (null). A is a word, a text, a list, null, "raise" (the hook fails)
    or "panic" (it panics). Every question is written down in `calls`, with its answer, so the two sides' questions are
    compared as the backend's calls are."""

    def __init__(self, spec, calls):
        self.calls, self.wants_, self.rules = calls, set(), {}
        self.set(spec)

    def set(self, spec):
        if "wants" in spec:
            self.wants_ = set(spec["wants"])
        if "rules" in spec:
            self.rules = {hook: [dict(rule, seen=0) for rule in rules] for hook, rules in spec["rules"].items()}

    @staticmethod
    def facts(hook, args):
        record = args[1] if hook == "gate" else args[0] if args else None
        found = dict(record) if isinstance(record, dict) else {}
        if hook == "gate":
            found["name"] = args[0]
        elif hook == "moved":
            found["to"] = args[1]
        elif hook == "outcome":
            found["outcome"] = args[1]
        elif hook == "schedule":
            found["due_at"] = args[1]
        return found

    def wants(self, point):
        return str(getattr(point, "value", point)) in self.wants_

    def answer(self, hook, args):
        args = norm(list(args))
        if hook == "admission" and isinstance(args[0], dict) and isinstance(args[0].get("takes"), list):
            args[0]["takes"] = sorted(args[0]["takes"])
        found, given = self.facts(hook, args), None
        for rule in self.rules.get(hook, ()):
            if any(found.get(name, "<absent>") != wanted for name, wanted in rule.get("when", {}).items()):
                continue
            rule["seen"] += 1
            used = rule["seen"] - 1 - rule.get("skip", 0)
            if used < 0 or (rule.get("times") is not None and used >= rule["times"]):
                continue
            given = rule["answer"]
            break
        self.calls.append(["plug", hook, *args, given])
        if given == "raise":
            raise ScriptRaise(hook)
        if given == "panic":
            raise ScriptPanic(hook)
        return given


def scripted_plug(script):
    """The reference's side of the script: a `domain.plug.Plug` whose every hook asks `script`."""
    from codex_auto_resume.domain.plug import DEFER, Plug

    def said(value):
        return DEFER if value is None else value

    class Scripted(Plug):
        def gate(self, name, record, facts):
            return said(script.answer("gate", [name, record, facts]))

        def text(self, record, text):
            return said(script.answer("text", [record, text]))

        def sender(self, record, backend):
            script.answer("sender", [record])
            return backend

        def outcome(self, record, outcome):
            return said(script.answer("outcome", [record, outcome]))

        def schedule(self, record, due):
            return said(script.answer("schedule", [record, due]))

        def moved(self, record, state):
            script.answer("moved", [record, state])
            return DEFER

        def delivery(self, record):
            return said(script.answer("delivery", [record]))

        def unloaded(self, record):
            return said(script.answer("unloaded", [record]))

        def admission(self, failure):
            return said(script.answer("admission", [failure]))

        def sessions(self):
            return said(self.words("sessions"))

        def eligibility(self):
            return said(self.words("eligibility"))

        @staticmethod
        def words(hook):
            found = script.answer(hook, [])
            return tuple(found) if isinstance(found, list) else found       # the reference takes a tuple, not a list

        def notice(self, facts):
            script.answer("notice", [facts])
            return DEFER

        def records(self, view):                    # P2 (seat S7.2a2): handed over by the script
            return said(script.answer("records", []))

        def claim_ledger(self, connection, record, now, carried):     # P11 (seat S7.2a2)
            return said(script.answer("claim_ledger", [record, now, carried]))

        def wants(self, point):
            return script.wants(point)

    return Scripted()


def judge(step) -> dict:
    """engine/impossible.py, pure (review 6, S4): a fresh Judge run through `script` - ["look", now, app_runs, facts],
    ["tick", app_runs, facts], ["word", now] - and `usage_reason` / `recovery_facts` over their cases."""
    from codex_auto_resume.engine import impossible
    found, words = impossible.Judge(), []
    for each in step.get("script", []):
        if each[0] == "look":
            found.look(each[1], each[2], each[3])
        elif each[0] == "tick":
            found.tick(each[1], each[2])
        else:
            words.append(found.word(each[1]))
    usage = []
    for limits, results in step.get("usage", []):
        if isinstance(results, dict):
            results = {method: tuple(value) if isinstance(value, list) else value for method, value in results.items()}
        usage.append(impossible.usage_reason(limits, results))
    facts = []
    for case in step.get("facts", []):
        case = dict(case, reasons=set(case["reasons"]))
        facts.append(impossible.recovery_facts(**case))
    return {"words": words, "usage": usage, "facts": facts}


def raised(error) -> dict:
    return {"raised": type(error).__name__}


# ------------------------------------------------------------------ the two sides
class ReferenceSide:
    """The tag's own Engine, Store and LocalSource, in this process (the tag's Python)."""

    def __init__(self, spec, state_dir, home, backend, now, notes, logs, *, plug=None):
        from codex_auto_resume.codex import LocalSource
        from codex_auto_resume.engine import Engine
        from codex_auto_resume.store import Store
        self.store = Store(state_dir, clock=lambda: now[0])

        def notify(event, payload):
            notes.append([event, payload])
            if spec.get("notify_raises"):
                raise RuntimeError("the notifier failed")
        engine_state, home_lock = spec.get("engine_state", "verified"), spec.get("home_lock", True)
        connectivity = spec.get("connectivity")
        self.engine = Engine(self.store, LocalSource(home.root), backend, clock=lambda: now[0],
                             log=lambda *args: logs.append(list(args)), options=spec.get("options") or {},
                             notify=notify, home_key=spec.get("home_key", ""),
                             engine_state=lambda: engine_state, home_lock=lambda: home_lock,
                             connectivity=lambda: connectivity, plug=None if plug is None else scripted_plug(plug))
        self.scripted = plug is not None
        if self.scripted:
            # What the claim is told of the plug's answers (`carried`, `relaxed`, `resend`, `forced`, `caps`) is what
            # P11's ledger would pay for, and nothing else shows it: written down as a call, so both sides' are compared.
            reserve = self.store.reserve_detailed

            def noting(interruption_id, now, **options):
                number = lambda found: None if found is None else float(found)
                pair = lambda found: None if found is None else [float(each) for each in found]
                backend.calls.append(["claim", sorted(str(getattr(point, "value", point))
                                                      for point in options.get("carried", ())),
                                      options.get("relaxed"), pair(options.get("resend")), bool(options.get("forced")),
                                      pair(options.get("caps")), number(options.get("quiet_until")),
                                      not options["ledger"].null if options.get("ledger") is not None else False])
                return reserve(interruption_id, now, **options)
            self.store.reserve_detailed = noting
        self.engine._random = random.Random(spec.get("seed", 7))

    def clock(self, now):
        pass

    def call(self, step):
        op = step["op"]
        try:
            if op == "tick":
                self.engine.tick()
            elif op == "watch":
                self.engine.watch()
            elif op == "policy":
                managed = step.get("managed")
                if managed is not None:
                    from codex_auto_resume import managed as admin
                    managed = admin.Managed(**dict(managed, quiet_hours=tuple(managed.get("quiet_hours") or ())))
                self.engine.apply_policy(step.get("values"), managed)
            elif op == "store":
                return plain(getattr(self.store, step["method"])(*step.get("args", []), **step.get("kwargs", {})))
            elif op == "after_sleep":
                return self.engine.after_sleep(step["since"], step["slept"])
            elif op == "retiring":
                self.engine.retiring = bool(step["value"])
            elif op == "facts":
                found = {"detection_failed": self.engine.detection_failed,
                         "watch_needed": self.engine.watch_needed(),
                         "activity": self.engine.activity(step.get("threads") or ()),
                         "last_usage": self.engine.last_usage()}
                if self.scripted:
                    found["plug_failures"] = self.engine.plug.failures
                return found
            elif op == "judge":
                return judge(step)
            return None
        except Exception as error:      # what raised, by class: the Rust side answers the same
            return raised(error)

    def take(self):
        return None

    def close(self):
        self.store.close()


class RustSide:
    """car-engine through `car-harness serve`, its backend and jitter's draw asked back to this side's stand-ins."""

    def __init__(self, spec, state_dir, home, backend, now, notes, logs, *, harness, session=1, plug=None):
        self.backend, self.notes, self.logs, self.session, self.script = backend, notes, logs, session, plug
        self.rng = random.Random(spec.get("seed", 7))
        self.process = harness
        environ = {LANG: os.environ.get(LANG, "")} if os.environ.get(LANG) else {}
        self.request("engine.open", state=str(state_dir), codex=str(home.root), clock=now[0],
                     options=spec.get("options") or {}, home_key=spec.get("home_key", ""), environ=environ,
                     notify_raises=bool(spec.get("notify_raises")), engine_state=spec.get("engine_state", "verified"),
                     home_lock=spec.get("home_lock", True), connectivity=spec.get("connectivity"),
                     plug=plug is not None)

    def request(self, call, **fields):
        line = json.dumps(dict(fields, id=self.session, call=call, session=self.session), ensure_ascii=False)
        self.process.stdin.write((line + "\n").encode("utf-8"))
        self.process.stdin.flush()
        while True:
            answer = self.process.stdout.readline()
            if not answer:
                raise RuntimeError("car-harness ended: " + self.process.stderr.read().decode("utf-8", "replace"))
            found = json.loads(answer)
            if "ask" not in found:
                reply = found["reply"]
                if not reply.get("ok"):
                    raise RuntimeError("car-harness refused %s: %r" % (call, reply))
                return reply["value"]
            self.process.stdin.write((json.dumps(self.answer(found["ask"], found["args"]), ensure_ascii=False)
                                      + "\n").encode("utf-8"))
            self.process.stdin.flush()

    def answer(self, name, args):
        try:
            if name == "draw":
                return {"value": self.rng.random()}
            if name == "note.claim":
                self.backend.calls.append(["claim", sorted(args[0]), *args[1:]])
                return {"value": None}
            if name.startswith("plug."):
                hook = name.split(".", 1)[1]
                if hook == "wants":
                    return {"value": self.script.wants(args[0])}
                return {"value": plain(self.script.answer(hook, args))}
            if name == "backend.send_noted":
                self.backend.calls.append(["send", args[0], args[1]])
                return {"value": None}
            if name == "backend.send":
                return {"value": plain(self.backend.send(args[0], args[1], permitted=args[2],
                                                         noted=len(args) > 3 and args[3] is True))}
            if name == "backend.getattr":
                return {"value": plain(getattr(self.backend, args[0], None))}
            if name == "backend.holder":
                holder = getattr(self.backend, "holder", None)
                return {"value": [False, None] if holder is None else [True, plain(holder(args[0]))]}
            method = getattr(self.backend, name.split(".", 1)[1])
            return {"value": plain(method(*args))}
        except Exception as error:
            return {"raise": type(error).__name__}

    def clock(self, now):
        self.request("engine.step", op="clock", value=now)

    def call(self, step):
        answer = self.request("engine.step", **step)
        self.logs.extend(answer["log"])
        self.notes.extend(answer["notify"])
        result = answer["result"]
        if isinstance(result, dict) and set(result) == {"raised", "message"}:
            result = {"raised": result["raised"]}       # a store call's refusal, by class, as the reference's is kept
        return result

    def close(self):
        self.request("engine.close")


def resolved(value, state_dir: Path):
    """`{"$key": thread}` - the newest record of that conversation's id - read from the side's own store, which holds
    the same ids on both sides (they are derived from the failure)."""
    if isinstance(value, list):
        return [resolved(each, state_dir) for each in value]
    if isinstance(value, dict) and set(value) == {"$key"}:
        path = state_dir / "state.sqlite"
        with closing(sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)) as db:
            found = db.execute("SELECT interruption_id FROM interruptions WHERE thread_id=? "
                               "ORDER BY detected_at DESC, interruption_id LIMIT 1", (value["$key"],)).fetchone()
        return found[0] if found else "0" * 32
    if isinstance(value, dict):
        return {key: resolved(each, state_dir) for key, each in value.items()}
    return value


def run(spec, codexsim, root: Path, side, **side_options):
    """One scenario on one side: the trace, a list of {step, result, log, notify, calls, state}."""
    ids = Ids()
    codexsim.new_id = ids
    root = Path(root)
    now = [float(spec.get("clock", codexsim.BASE + 10.0))]
    home = codexsim.CodexHome(root / "codex-home")
    home.clock = lambda: now[0]
    sim = codexsim.SimBackend(home)
    calls, notes, logs = [], [], []
    backend = Recorder(sim, calls)
    script = Script(spec["plug"], calls) if spec.get("plug") is not None else None
    state_dir = root / "state"
    # The language a continuation is written in, named, so neither side reads this PC's Windows languages.
    os.environ[LANG] = spec.get("lang") or "en"
    engine = side(spec, state_dir, home, backend, now, notes, logs, plug=script, **side_options)
    trace = []
    try:
        for index, step in enumerate(spec["steps"]):
            op = step["op"]
            if op in ("advance", "clock"):
                now[0] = (now[0] + float(step["by"])) if op == "advance" else float(step["at"])
                engine.clock(now[0])
                result = now[0]
            elif op == "home":
                result = getattr(home, step["method"])(*step.get("args", []), **step.get("kwargs", {}))
            elif op == "helper":
                result = HELPERS[step["name"]](codexsim, home, *step.get("args", []), **step.get("kwargs", {}))
            elif op == "backend":
                for name, value in step.get("set", {}).items():
                    if name == "app":
                        sim.app = dict(codexsim.APP) if value == "APP" else value
                    else:
                        setattr(sim, name, value)
                for thread, value in step.get("loaded", {}).items():
                    sim.loaded_map[thread] = value
                for thread, value in step.get("outcomes", {}).items():
                    sim.outcomes[thread] = value
                backend.attrs.update(step.get("attrs", {}))
                result = None
            elif op == "plug":
                script.set(step)
                result = None
            else:
                result = engine.call(resolved(step, state_dir))
            trace.append({"step": index, "op": op, "result": plain(result), "log": plain(logs), "notify": plain(notes),
                          "calls": plain(calls), "state": dump(state_dir)})
            logs.clear(), notes.clear(), calls.clear()
    finally:
        engine.close()
    return trace


def reference_main(request_path, out_path):
    """The reference's entry: the request names the tag's codexsim, the scenarios and a scratch folder."""
    import importlib.util
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    loaded = importlib.util.spec_from_file_location("codexsim", request["codexsim"])
    codexsim = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(codexsim)
    from codex_auto_resume.codex import rollout
    traces = {}
    for name, spec in request["scenarios"].items():
        # The reader's module state is cleared before each scenario, as a fresh process (and a fresh Rust session)
        # starts with none.
        for kept in ("_SPLITS", "_ASKED", "_RELISTED", "_META", "_TRIGGERS"):
            if hasattr(rollout, kept):
                getattr(rollout, kept).clear()
        try:
            traces[name] = run(spec, codexsim, Path(request["root"]) / ("ref-" + name), ReferenceSide)
        except Exception as error:      # a scenario the reference cannot run at all is said, not hidden
            traces[name] = {"failed": "%s: %s" % (type(error).__name__, error)}
    Path(out_path).write_text(json.dumps(traces, ensure_ascii=False), encoding="utf-8")

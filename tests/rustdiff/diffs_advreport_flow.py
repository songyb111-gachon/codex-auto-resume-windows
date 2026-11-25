"""The compatibility report's flow (car-adv `report/flow.rs`) held to the tag's `report/flow.py`, command by command.

A case is a program of the Dashboard's commands - build, save, check, send, job - put to the tag's `Flow` and to car-adv's, each
over a home of its own made twice by the tag's own fixtures (the records of `reportfixtures.BASE`, a watcher's report), with the
seams the flow reaches the rest of the edition through answering from the case: the runtime (the policy, where the capability
stands, what the state stores, and what changes between the questions of a send), the home's report mutex (free, abandoned,
busy, one that cannot be made), gh (the recorded script of the tag's `FakeGh`), the clock (one step a call) and the tokens.

Both answer every step, and write down what the flow did that can be seen: the journal's lines, the capability's trips, gh's
calls, its sleeps, the mutex's life and how many times each seam was asked. Jobs run on threads in both; the programs wait for
a job before they ask the next thing, except where the case holds one with a gate to ask what answers while it runs.

Not here: `Flow`'s default `find_gh` and `inuse.home` (the process's own PATH and Codex home; the case names the gh and the
Codex home), and the real home mutex (`ReportMutex`, a Windows object the tag's own tests start a process to hold).
"""
from __future__ import annotations

import unittest

from rustdiff import advreport

RECORD = []

SCRIPT = r'''
import itertools, secrets, shutil, sqlite3, threading, types
import reportfixtures as fixtures
from ghfake import FakeGh, pull, LOGIN
from codex_auto_resume_advanced import policy as policymod, registry
from codex_auto_resume_advanced.report import flow as flowmod, github
from codex_auto_resume_advanced.vocabulary import ArmingState, BridgeCommand

counter = [0]
def token_hex(nbytes=32):
    counter[0] += 1
    return format(counter[0], "0%dx" % (2 * nbytes))
secrets.token_hex = token_hex

DEFINITION = registry.COMPAT_REPORT
EXE = r"C:\Tools\gh\gh.exe"
BUILD, SAVE, CHECK, SEND, JOB = (str(BridgeCommand.ADVANCED_REPORT_BUILD), str(BridgeCommand.ADVANCED_REPORT_SAVE),
                                 str(BridgeCommand.ADVANCED_REPORT_CHECK), str(BridgeCommand.ADVANCED_REPORT_SEND),
                                 str(BridgeCommand.ADVANCED_REPORT_JOB))

def digest(env):
    return hashlib.sha256(json.dumps(sorted(env.items())).encode("utf-8")).hexdigest()
import hashlib

class Recorder:
    def __init__(self, fake, raises=None, gate=None):
        self.fake, self.script, self.raises, self.gate = fake, [], dict(raises or {}), gate
    def __call__(self, argv, *, env, cwd, stdin, timeout, creationflags):
        if self.gate is not None:
            self.gate.wait(60)
        call = {"argv": list(argv), "env": digest(env), "cwd": cwd, "stdin": None if stdin is None else stdin.decode("ascii"),
                "timeout": timeout, "flags": creationflags}
        index = len(self.script)
        try:
            if index in self.raises:
                raise self.raises[index]("boom")
            answer = self.fake(argv, env=env, cwd=cwd, stdin=stdin, timeout=timeout, creationflags=creationflags)
        except github.GhTimeout:
            self.script.append({"call": call, "answer": {"raise": "GhTimeout"}})
            raise
        except Exception as error:
            self.script.append({"call": call, "answer": {"raise": type(error).__name__}})
            raise
        self.script.append({"call": call, "answer": [answer[0], answer[1], answer[2]]})
        return answer

class Stub:
    """The runtime of a case."""
    def __init__(self, script, home):
        self.script, self.home = script or {}, home
        self.policy_calls = self.state_calls = self.stored_calls = 0
        self.journal, self.trips = [], []
        self.arming = types.SimpleNamespace(policy=self._policy, trip=self._trip)
        self.state = types.SimpleNamespace(arming=self._stored, note=self._note)
    def _pick(self, key, call):
        items = self.script.get(key) or [None]
        return items[min(call, len(items) - 1)]
    @staticmethod
    def _raise(item):
        if isinstance(item, dict) and "raise" in item:
            raise {"RuntimeError": RuntimeError, "OSError": OSError, "KeyError": KeyError}[item["raise"]]("boom")
    def _policy(self):
        call = self.policy_calls
        self.policy_calls += 1
        statement = (self.script.get("sql") or {}).get(str(call))
        if statement:
            db = sqlite3.connect(self.home / "config" / "state.sqlite")
            db.executescript(statement)
            db.commit()
            db.close()
        item = self._pick("policy", call)
        self._raise(item)
        if not isinstance(item, dict):
            return policymod.NONE
        return policymod.Policy(forbid=item.get("forbid") is True, force_shadow=item.get("force_shadow") is True,
                                allowed=None if item.get("allowed") is None else frozenset(item["allowed"]))
    def states(self, fresh=False):
        call = self.state_calls
        self.state_calls += 1
        item = self._pick("state", call)
        self._raise(item)
        return {} if item is None else {DEFINITION.id: ArmingState(item)}
    def _stored(self):
        call = self.stored_calls
        self.stored_calls += 1
        item = self._pick("stored", call)
        self._raise(item)
        return {} if item is None else {DEFINITION.id: {"state": item}}
    def _trip(self, capability, reason):
        self.trips.append([capability, str(reason)])
    def _note(self, code, capability=None, at=None):
        self.journal.append([code, capability, at])
        if self.script.get("note_raises"):
            raise OSError("boom")

class StubMutex:
    def __init__(self, script, log):
        self.script, self.log, self.calls = script or ["free"], log, 0
    def take(self):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        self.log.append(["take", item])
        if item == "free":
            return False
        if item == "abandoned":
            return True
        if item == "raise":
            raise RuntimeError("the mutex could not be made")
        raise flowmod.Busy()
    def give(self):
        self.log.append(["give"])

def error_of(error):
    found = {"error": type(error).__name__}
    code = getattr(error, "code", None)
    if code is not None and not isinstance(code, int):
        found["code"] = str(code)
    return found

def resolve(value, state, home_dir):
    """`value` with `$sha`, `$writes` and `$dir` (this side's own folder) put in."""
    if isinstance(value, str):
        if value == "$sha":
            return state["sha"]
        if value == "$sha0":
            return state["shas"][0]
        if value == "$writes":
            return state["writes"]
        return value.replace("$dir", home_dir)
    if isinstance(value, dict):
        return {key: resolve(each, state, home_dir) for key, each in value.items()}
    if isinstance(value, list):
        return [resolve(each, state, home_dir) for each in value]
    return value

def flow_case(program, runtime=None, mutex=None, gate=False, gh=None, exe=EXE, home_options=None, clock=(1790000000.0, 1.0), raises=None):
    runtime = dict({"state": ["armed"]}, **(runtime or {}))
    options = {"state": 4, "watcher_report": fixtures.watcher()}
    options.update(home_options or {})
    mine, theirs = fixtures.Home(fixtures.BASE, **options), fixtures.Home(fixtures.BASE, **options)
    counter[0] = 0
    stub = Stub(runtime, mine.paths.home)
    stub.script = dict(runtime or {})
    stub.home = Path(mine.paths.home)
    fake = FakeGh(**(gh or {}))
    event = threading.Event() if gate else None
    recorder = Recorder(fake, raises, event)
    sleeps, log, ticks = [], [], [0]
    def clock_now():
        index = ticks[0]
        ticks[0] += 1
        return clock[0] + clock[1] * index
    def make_mutex(paths):
        log.append(["made"])
        return StubMutex(mutex, log)
    flow = flowmod.Flow(mine.paths, runner=recorder, find_gh=lambda: exe, mutex=make_mutex, sleep=sleeps.append, clock=clock_now,
                        product_version="0.6.14-beta", windows="10.0.26200", codex_home=mine.codex, view=mine.raw_view)
    state, last, steps, kept = {"sha": None, "writes": None, "shas": []}, [None], [], []
    for step in program:
        kind = step[0]
        if kind == "answer":
            argument = resolve(step[2], state, str(mine.root))
            for_rust = ["answer", step[1], resolve(step[2], state, "$dir")]
            try:
                shown = flow.answer(stub, DEFINITION, step[1], argument)
            except Exception as error:
                shown = error_of(error)
            if isinstance(shown, dict) and shown.get("done") is True and isinstance(shown.get("job"), str):
                last[0] = shown["job"]
        elif kind == "wait":
            for_rust = step
            shown = flow.wait(last[0], 30.0)
        elif kind == "job":
            for_rust = step
            shown = flow.job(last[0] if step[1] == "last" else step[1])
        elif kind == "release":
            for_rust = step
            event.set()
            kept.append(for_rust)
            continue
        elif kind == "sql":
            for_rust = step
            db = sqlite3.connect(mine.paths.state_dir / "state.sqlite")
            db.executescript(step[1])
            db.commit()
            db.close()
            kept.append(for_rust)
            continue
        else:
            for_rust = step
            target = Path(str(step[1]).replace("$dir", str(mine.root)))
            shown = {"exists": target.is_file(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None}
        if isinstance(shown, dict):
            if shown.get("status") == "built":
                state["sha"] = shown["sha256"]
                state["shas"].append(shown["sha256"])
            if shown.get("status") == "checked":
                state["writes"] = shown["writes"]
        steps.append(shown)
        kept.append(for_rust)
    # the program Rust is given has what the reference resolved, and `$dir` left for each side's own folder
    case_data = {"home": str(theirs.paths.home), "codex": str(theirs.codex), "view": theirs.raw_view(), "product_version": "0.6.14-beta",
                 "windows": "10.0.26200", "clock": {"start": clock[0], "step": clock[1]}, "tokens": 0, "find": exe, "runtime": runtime or {},
                 "mutex": mutex or ["free"], "gate": bool(gate), "script": [{"answer": entry["answer"]} for entry in recorder.script]}
    case_data["root"] = str(theirs.root)
    def homeless(value):
        if isinstance(value, str):
            return value.replace(str(mine.root), "<root>")
        if isinstance(value, list):
            return [homeless(each) for each in value]
        if isinstance(value, dict):
            return {key: homeless(each) for key, each in value.items()}
        return value
    CASES.append(["flow.run", case_data, kept])
    RESULTS.append({"ok": homeless({"steps": steps, "journal": json.loads(json.dumps(stub.journal)), "trips": stub.trips,
                           "calls": [entry["call"] for entry in recorder.script], "sleeps": [float(each) for each in sleeps],
                           "mutex": log, "asked": {"policy": stub.policy_calls, "state": stub.state_calls, "stored": stub.stored_calls, "clock": ticks[0]}})})

def ask(command, **argument):
    return ["answer", command, argument]

BUILT = [ask(BUILD, login="ExampleUser"), ["wait"]]
CHECKED = BUILT + [ask(CHECK, sha256="$sha"), ["wait"]]
SENT = CHECKED + [ask(SEND, sha256="$sha", word="send", writes="$writes"), ["wait"]]

# building
flow_case(BUILT)
flow_case([ask(BUILD, login=login) for login in ("-bad-", "nul", "songyb111-gachon", None, 7, "")])
flow_case(BUILT, runtime={"state": [None]})
flow_case(BUILT, runtime={"state": ["off"]})
flow_case(BUILT, runtime={"state": ["shadow"]})
flow_case(BUILT, runtime={"policy": [{"forbid": True}]})
flow_case(BUILT, runtime={"policy": [{"allowed": ["other"]}]})
flow_case(BUILT, runtime={"policy": [{"allowed": ["compat_report"]}]})
flow_case(BUILT, home_options={"state": None})
flow_case(BUILT, home_options={"state": 2})
flow_case(BUILT, runtime={"note_raises": True})
flow_case(BUILT, clock=(1790000000.0, 0.0))
flow_case([step for number in range(6) for step in (ask(BUILD, login="a%d" % number), ["wait"])] + [ask(CHECK, sha256="$sha"), ["wait"]])
flow_case([step for number in range(20) for step in (ask(BUILD, login="ExampleUser"), ["wait"])] + [["job", "last"]])
for builds in (4, 5):
    flow_case([step for number in range(builds) for step in (ask(BUILD, login="b%d" % number), ["wait"])] + [ask(CHECK, sha256="$sha0"), ["wait"]])
# saving
dest = "$dir\\saved.json"
flow_case([ask(SAVE, sha256="x" * 64, path=dest)])
flow_case(BUILT + [ask(SAVE, sha256="$sha", path=path) for path in (dest, dest, "relative.json", "", None, 7, "$dir\\nowhere\\saved.json", "C:saved.json", "\\\\?\\NUL\\x")] + [["file", dest]])
flow_case(BUILT + [ask(SAVE, sha256="$sha", path=dest)], runtime={"state": ["shadow"]})
flow_case(BUILT + [ask(SAVE, sha256="$sha", path=dest)], runtime={"state": [None]})
# checking
flow_case(CHECKED)
flow_case(CHECKED, gh={"fork": "fork", "branch": True})
flow_case(CHECKED, exe=None)
flow_case(CHECKED, gh={"signed_in": False})
flow_case(CHECKED, gh={"who": "SomeoneElse"})
flow_case(CHECKED, gh={"who": "exampleuser"})
flow_case(CHECKED, gh={"open_door": False})
flow_case(CHECKED, gh={"hang": ("user",)})
flow_case(CHECKED, raises={2: OSError})
flow_case(CHECKED, raises={2: RuntimeError})
flow_case(CHECKED, runtime={"state": ["armed", "shadow"]})
flow_case(BUILT + [ask(CHECK, sha256="$sha")], runtime={"state": ["shadow"]})
flow_case(BUILT + [ask(CHECK, sha256="$sha")], runtime={"state": ["shadow"], "stored": ["armed"], "policy": [{"force_shadow": True}]})
flow_case(BUILT + [ask(CHECK, sha256="$sha")], runtime={"state": ["shadow"], "stored": [{"raise": "OSError"}]})
flow_case(BUILT + [ask(CHECK, sha256="$sha")], runtime={"state": ["off"]})
flow_case(BUILT + [ask(CHECK, sha256="$sha")], runtime={"policy": [{"forbid": True}]})
flow_case(BUILT + [ask(CHECK, sha256="$sha")], runtime={"policy": [{"allowed": []}]})
flow_case(BUILT + [["sql", "UPDATE settings SET enabled = 0;"], ask(CHECK, sha256="$sha")])
flow_case(BUILT + [["sql", "DELETE FROM settings;"], ask(CHECK, sha256="$sha")])
flow_case(BUILT + [ask(CHECK, sha256="x" * 64), ask(CHECK, sha256=None), ask(CHECK)])
flow_case(CHECKED, mutex=["abandoned"])
flow_case(CHECKED, mutex=["busy"])
flow_case(CHECKED, mutex=["raise"])
flow_case(CHECKED + [ask(CHECK, sha256="$sha"), ["wait"]], mutex=["free", "busy", "abandoned", "free"])
# sending
flow_case(SENT)
flow_case(SENT, gh={"fork": "fork", "branch": True})
flow_case(BUILT + [ask(SEND, sha256="$sha", word="send", writes=[])])
flow_case(CHECKED + [ask(SEND, sha256="$sha", word="Send", writes="$writes"), ask(SEND, sha256="$sha", word="send ", writes="$writes"),
                     ask(SEND, sha256="$sha", word=None, writes="$writes"), ask(SEND, sha256="$sha", word="send", writes=[]),
                     ask(SEND, sha256="$sha", word="send", writes=None), ask(SEND, sha256="$sha", word="send", writes="x"),
                     ask(SEND, sha256="x" * 64, word="send", writes="$writes")])
flow_case(CHECKED, gh={"fork": "fork", "branch": True, "pulls": [pull(ref="compat-report/codex-cli-0.158.0")]})
flow_case(SENT, gh={"made_fork": "ExampleUser/other"})
flow_case(SENT, gh={"fork_ready_after": 4})
flow_case(SENT, gh={"fork_ready_after": 25})
flow_case(SENT, gh={"pr_answer": (1, "", "failed")})
flow_case(SENT, gh={"hang": ("forks",)})
flow_case(SENT, gh={"hang": ("git/refs",)})
flow_case(SENT, raises={7: RuntimeError})
flow_case(SENT, raises={9: OSError})
flow_case(SENT, raises={5: RuntimeError})
for states in (["armed", "armed", "off"], ["armed", "armed", "armed", "shadow"], ["armed", "armed", "armed", "armed", "off"], ["armed", "armed", "armed", "armed", "armed", "off"]):
    flow_case(SENT, runtime={"state": states})
flow_case(SENT, runtime={"policy": [None, None, {"forbid": True}]})
flow_case(SENT, runtime={"policy": [None, None, None, {"allowed": []}]})
flow_case(SENT, runtime={"policy": [None, None, None, {"force_shadow": True}], "state": ["armed", "armed", "armed", "shadow"], "stored": ["armed"]})
flow_case(SENT, runtime={"sql": {"3": "UPDATE settings SET enabled = 0;"}})
flow_case(SENT, runtime={"sql": {"4": "UPDATE settings SET enabled = 0;"}})
flow_case(SENT, runtime={"state": ["armed", "armed", {"raise": "RuntimeError"}]})
flow_case(SENT, runtime={"policy": [None, None, {"raise": "KeyError"}]})
flow_case(SENT, runtime={"note_raises": True})
flow_case(SENT, mutex=["free", "abandoned"])
# jobs
flow_case([ask(JOB, job="nope"), ask(JOB, job=None), ask(JOB, job=7), ask(JOB), ["job", "x"]])
flow_case(BUILT + [["job", "last"], ["job", "last"]])
flow_case([["answer", BUILD, "not a dict"], ["answer", JOB, "x"], ["answer", CHECK, None], ["answer", SAVE, []]])
flow_case([["answer", BUILD, "not a dict"]], runtime={"state": ["off"]})
flow_case([["answer", "advanced-list", {}], ["answer", "x", {"sha256": "y"}]])
# one at a time: a check held at its first call to gh answers busy to everything else, then goes on
flow_case(BUILT + [ask(CHECK, sha256="$sha"), ask(CHECK, sha256="$sha"), ask(SEND, sha256="$sha", word="send", writes=[]), ask(BUILD, login="ExampleUser"),
                   ["job", "last"], ["release"], ["wait"]], gate=True)
finish()
'''


class FlowDiff(advreport.ReportDiff):
    def test_the_commands_in_the_tags_order(self):
        found = self.family(SCRIPT, label="flow", expect_cases=70, chunk=20)
        statuses = {step.get("status") for result in found["results"] for step in result["ok"]["steps"] if isinstance(step, dict)}
        for status in ("built", "checked", "sent", "partial", "refused", "web", "saved", "lost", "running"):
            self.assertIn(status, statuses, status)
        refusals = {step.get("refusal") for result in found["results"] for step in result["ok"]["steps"] if isinstance(step, dict)}
        for word in ("busy", "word", "changed", "unknown_build", "not_on", "watched", "paused", "state_unreadable", "forbidden_by_policy",
                     "login_invalid", "file_exists", "save_failed"):
            self.assertIn(word, refusals, word)
        RECORD.append("flow: %d programs - build, save, check, send and job over every policy, state, pause, mutex and gh answer, a "
                      "stop between any two writes, a fault after a write, one job at a time; journal, trips, gh's calls, "
                      "sleeps and the seams' questions equal" % len(found["cases"]))


if __name__ == "__main__":
    unittest.main()

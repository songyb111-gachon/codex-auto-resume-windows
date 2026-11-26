"""What seat S7.2d's diffs (diffs_advusage_*.py) share: the usage meter, the wrap-up, the forced stop, the reset credit and
message, the early reset, the capacity retry and their words, run by the v0.6.26 final's own advanced edition and by
car-adv's `advusage` probe on the same inputs, held equal.

A request is `{"home", "clock", "tokens", "catalogs", "world", "ops"}`. Both sides run every op in order on one scratch
home (the reference first, then the probe on the home made again) and answer one line per op, `{"ok": value}` or
`{"raised": class}`; the advanced state file each left is compared by its dump. The world stands in for everything the
codes read of the outside, the same on both sides and logged in order (the `{"log": true}` op reads it back): Codex's
files (`turns`, `source`), core's view, the backend the meter looks through, the capability's own session, the app's
IPC channel, core's errand guard, the saved accounts' switch, the continuation language and the Codex home. Nothing is
started and nothing is sent: no real Codex, no real usage limit, no real app.

The reference's test seams are the tag's own (`session=`, `stop=`, `start=`, `home=`); the rest are module attributes
replaced for the run (`inuse.backend`, `inuse.home`, `usage._switched_at`, `Turns`, `booted_of`, core's `LocalSource`,
`settings.load`, `continuation.resolve_locale`, `credits.uuid`, `l10n.current`). An errand that raises is answered
`{"raised": "Exception"}` on both sides (the runtime takes any raise the same: the capability trips).

D17: the reference is the v0.6.26 final (`usage.py` is the final's: SKIP_WAIT, `_held`, `inuse.saw`). Not a test module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rustdiff import advdiff, advref, advstore, diffs

TAG = os.environ.get("CODEX_AR_REFERENCE") or "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CLOCK = 1_764_000_000.0
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0001-7000-8000-000000000002"

REFERENCE = r'''
import contextlib, enum, json, sqlite3, sys, types
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
counter = [request.get("tokens", 0)]
import secrets
def token_hex(nbytes=32):
    counter[0] += 1
    return format(counter[0], "0%dx" % (2 * nbytes))
secrets.token_hex = token_hex
from codex_auto_resume import config, continuation, l10n, settings
from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume.codex.errors import AdapterError
import codex_auto_resume.codex as core_codex
from codex_auto_resume_advanced import state as state_package, statement
from codex_auto_resume_advanced.registry import REGISTRY
from codex_auto_resume_advanced.codex import inuse
from codex_auto_resume_advanced.engine import (capacity, continued, credits, earlyreset, resetmessage, resetwatch,
                                               usage, usagestop, wrapwords)

clock = [request.get("clock", 0.0)]
paths = config.Paths(str(Path(request["home"])))
state = state_package.AdvancedState(paths, registry=REGISTRY, clock=lambda: clock[0])
WORLD = dict(request.get("world") or {})
LOG, CURSORS, SWITCHES, MADE, PENDING = [], {}, {}, {}, {}


def at(value, name):
    return value.get(name) if isinstance(value, dict) else None


def raise_of(value):
    found = at(value, "raise")
    return found if isinstance(found, str) else None


def raising(name):
    raise type(name, (Exception,), {})(name)


def nxt(part, name):
    items = at(WORLD.get(part), name)
    if not isinstance(items, list):
        return None
    key = "%s.%s" % (part, name)
    index = CURSORS.get(key, 0)
    CURSORS[key] = index + 1
    return items[index] if index < len(items) else None


def note(*entry):
    LOG.append(list(entry))


# ---------------------------------------------------------------- the world
l10n.current = lambda environ=None: "en"
statement.CATALOGS = statement.Catalogs(request["catalogs"])
settings.load = lambda *arguments, **keywords: {}


def resolve(values, environ=None):
    found = WORLD.get("locale")
    if not isinstance(found, str):
        raise RuntimeError("no locale")
    return found


continuation.resolve_locale = resolve


def home_of(paths_):
    found = WORLD.get("home")
    if raise_of(found):
        raising(raise_of(found))
    return str(found)


inuse.home = home_of
usage._switched_at = lambda paths_: WORLD.get("switched")


class Backend:
    def __init__(self, spec):
        self.spec = spec
        self.codex_exe = str(spec.get("codex_exe"))
        self.served_elsewhere = list(spec.get("served_elsewhere") or [])
        self.app_look = spec.get("app_look")

    def app_identity(self):
        note("backend.identity")
        found = self.spec.get("identity")
        if found == "raise":
            raise AdapterError("app_identity")
        return found

    def _compatible(self):
        found = nxt("backend", "compatible")
        found = "ok" if found is None else found
        note("backend.compatible", found)
        if found == "raise":
            raise AdapterError("engine_check")


def backend_of(paths_):
    spec = WORLD.get("backend")
    if spec is None:
        raise AdapterError("no_backend")
    if raise_of(spec):
        raising(raise_of(spec))
    note("backend.made")
    return Backend(spec)


inuse.backend = backend_of


class Turn(types.SimpleNamespace):
    pass


class ScriptTurns:
    def __init__(self, home):
        self.home = home

    def running(self, booted=None):
        note("turns.running")
        found = at(WORLD.get("turns"), "running")
        if raise_of(found):
            raising(raise_of(found))
        return [str(item) for item in found] if isinstance(found, list) else []

    def latest(self, thread):
        note("turns.latest", thread)
        found = at(at(WORLD.get("turns"), "latest"), thread)
        if raise_of(found):
            raising(raise_of(found))
        if not isinstance(found, dict):
            return None
        return Turn(status=str(found.get("status")), ordinal=found.get("ordinal"), turn_id=found.get("turn_id"))

    def between(self, thread, after, before):
        note("turns.between", thread, after, before)
        found = at(at(WORLD.get("turns"), "between"), thread)
        if raise_of(found):
            raising(raise_of(found))
        return int(found or 0)


usage.Turns = usagestop.Turns = ScriptTurns
usage.booted_of = usagestop.booted_of = lambda paths_: None


class ScriptSource:
    def __init__(self, home, *arguments, **keywords):
        made = at(WORLD.get("source"), "make")
        if raise_of(made):
            raising(raise_of(made))
        self.widened = frozenset()

    def latest(self, thread):
        note("source.latest", thread, bool(self.widened))
        found = at(at(WORLD.get("source"), "latest"), thread)
        if raise_of(found):
            raising(raise_of(found))
        return dict(found) if isinstance(found, dict) else None


core_codex.LocalSource = ScriptSource


class ScriptSession:
    sequence = 0

    def __enter__(self):
        note("session.enter")
        if raise_of(at(WORLD.get("session"), "enter")):
            raise AdapterError("app_server_failed")
        return self

    def __exit__(self, *unused):
        note("session.exit")
        return False

    def _reply(self):
        found = nxt("session", "replies")
        kind = raise_of(found)
        if kind == "adapter":
            raise AdapterError(str(found.get("code")))
        if kind == "bycodex":
            error = AdapterError("protocol_request_failed")
            error.code = found.get("code")
            raise error
        if kind:
            raise RuntimeError("scripted")
        return at(found, "reply")

    def call(self, method, params=None):
        note("session.call", method, params)
        return self._reply()

    def submit(self, method, params=None):
        note("session.submit", method, params)
        kind = raise_of(at(WORLD.get("session"), "submit"))
        if kind == "adapter":
            raise AdapterError("protocol_write_failed")
        if kind:
            raise RuntimeError("scripted")
        self.sequence += 1                      # each session numbers its own requests
        return self.sequence

    def receive(self, method, sequence, params=None):
        note("session.receive", method, sequence)
        return self._reply()


def opener(capability):
    def open_():
        note("session.open", capability)
        if raise_of(at(WORLD.get("session"), "open")):
            raise AdapterError("backend_unavailable")
        return ScriptSession()
    return open_


def ask(which):
    def call(thread, what, gate=None):
        word = nxt("ipc", which)
        word = "stopped" if word is None else str(word)
        if which == "start" and word == "stopped":
            word = "started"
        name = "ipc.%s" % which
        if word == "raise":
            note(name, thread, what, "raise")
            raise RuntimeError("scripted")
        if word.startswith("!"):
            note(name, thread, what, word)
            return word[1:]
        with gate() as permitted:
            note(name, thread, what, permitted)
            if permitted is not True:
                return "held"
        return word
    return call


class Keys:
    count = 0

    @staticmethod
    def uuid4():
        Keys.count += 1
        return "00000000-0000-4000-8000-%012d" % Keys.count


credits.uuid = types.SimpleNamespace(uuid4=Keys.uuid4)


@contextlib.contextmanager
def guard_scope():
    yield WORLD.get("guard") is not False


def guard():
    return guard_scope()


class ScriptView:
    def records_in(self, states):
        found = at(WORLD.get("view"), "records")
        if isinstance(found, str):
            raise RuntimeError("records")
        return [dict(row) for row in found] if isinstance(found, list) else []

    def thread_enabled(self, thread):
        found = at(at(WORLD.get("view"), "enabled"), thread)
        if isinstance(found, str):
            raise RuntimeError("enabled")
        return found if isinstance(found, bool) else True

    def last_usage(self):
        found = at(WORLD.get("view"), "last_usage")
        return tuple(found) if isinstance(found, list) else found


VIEW = ScriptView()


def canon(value):
    if value is DEFER:
        return "DEFER"
    if isinstance(value, enum.Enum):
        value = value.value
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, sqlite3.Row):
        value = dict(value)
    if isinstance(value, dict):
        if all(isinstance(name, str) for name in value):
            return {str(name): canon(item) for name, item in value.items()}
        return {"__pairs__": [[canon(name), canon(item)] for name, item in value.items()]}
    if isinstance(value, (list, tuple)):
        return [canon(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(canon(item) for item in value)
    if hasattr(value, "run"):
        return "ERRAND"
    return "OBJECT"


def keyed(rows):
    return {(row["bucket"], row["minutes"]): row for row in rows or []}


def pure(name, args, kwargs):
    if name == "continued.answer_key":
        return continued.answer_key(*args)
    if name == "continued.handed":
        return continued.handed(args[0])
    if name == "continued.words_pass":
        return continued.words_pass(args[0])
    if name == "wrapwords.check_custom":
        try:
            return wrapwords.check_custom(args[0])
        except wrapwords.WordingError as error:
            return {"error": error.code}
    if name == "wrapwords.window_words":
        return wrapwords.window_words(*args)
    if name == "wrapwords.reset_words":
        return wrapwords.reset_words(*args)
    if name == "wrapwords.render":
        return wrapwords.render(**kwargs)
    if name == "resetwatch.blank":
        return resetwatch.blank(*args)
    if name == "resetwatch.by_time":
        return list(resetwatch.by_time(*args))
    if name == "resetwatch.closed":
        return resetwatch.closed(*args)
    if name == "resetwatch.advance":
        row, events = resetwatch.advance(args[0], args[1], args[2], early=args[3] is not False)
        return [row, list(events)]
    if name == "resetwatch.family_window":
        return resetwatch.family_window(args[0], tuple(args[1]))
    if name == "resetwatch.count":
        return resetwatch.count(*args)
    if name == "resetwatch.due":
        return resetwatch.due(*args)
    if name == "usage.percent":
        return usage.percent(*args)
    if name == "usage.reached":
        return usage.reached(*args)
    if name == "usage.acting":
        return sorted(usage.acting(args[0]))
    if name == "usage.touched":
        return list(usage.touched(args[0]))
    if name == "usage.order_problem":
        return list(usage.order_problem(args[0], tuple(args[1]) if args[1] is not None else usage.WINDOWS))
    if name == "usage.stale":
        return usage.stale(args[0], {(b, m): a for b, m, a in args[1]})
    if name == "usage.reset_since":
        return usage._reset_since(keyed(args[0]), args[1], args[2], args[3])
    if name == "usage.previews":
        return {str(minutes): words for minutes, words in usage.previews(state, args[0]).items()}
    if name == "resetmessage.carried_by_stop":
        return resetmessage.carried_by_stop(args[0], args[1])
    if name == "resetmessage.same_reset":
        return resetmessage.ResetMessage._same_reset(*args)
    if name == "usagestop.counts_here":
        return usagestop._counts_here(args[0], args[1], args[2], keyed(args[3]), args[4])
    raise LookupError(name)


def make(op):
    capability = op["make"]
    scoped = state.scoped(
        capability,
        on=lambda: (SWITCHES.get("on") or {}).get(capability) is not False,
        verdict=lambda measurement: (SWITCHES.get("verdict") or {}).get(str(getattr(measurement, "value", measurement))),
        armed=lambda other: (SWITCHES.get("armed") or {}).get(str(other)) is True)
    if capability == "usage_meter":
        code = usage.UsageMeter(paths, session=opener(capability))
    elif capability == "usage_wrap_up":
        code = usage.UsageWrapUp(paths, home=op.get("home"))
    elif capability == "usage_pause" and op.get("plain") is True:
        code = usage.UsagePause(paths)
    elif capability == "usage_pause":
        code = usagestop.UsageStop(paths, stop=ask("stop"), start=ask("start"), home=op.get("home"))
    elif capability == "reset_credit":
        code = credits.ResetCredit(paths, session=opener(capability))
    elif capability == "reset_message":
        code = resetmessage.ResetMessage(paths, session=opener(capability))
    elif capability == "early_reset":
        code = earlyreset.EarlyReset(paths)
    elif capability == "capacity_retry":
        code = capacity.CapacityRetry(paths)
    else:
        raise LookupError(capability)
    if not (capability == "capacity_retry" and op.get("unbound") is True):
        code.bind(scoped)
    MADE[op["as"]] = code
    return None


def lower(told):
    return None if told is None else [str(part).lower() for part in told]


def kept(code):
    now = clock[0]
    if isinstance(code, usage.UsageMeter):
        return {"looked": code._looked, "why": code._why, "said": code._said, "skipped_at": code._skipped_at,
                "held": None if code._held is None else [str(code._held[0][0]), str(code._held[0][1])]}
    if isinstance(code, usage.UsageWrapUp):
        return {"looked": code._looked, "turn": code._turn}
    if isinstance(code, earlyreset.EarlyReset):
        return {"probe_at": code.probe_at, "reached": code.reached, "first_available_at": code.first_available_at,
                "lifted_at": code.lifted_at, "released": sorted(code.released, key=str)}
    if isinstance(code, credits.ResetCredit):
        return [[rule, at_] for rule, at_ in code._tried.items()]
    if isinstance(code, usagestop.UsageStop):
        return {"notices": code.notices(now),
                "backoff": [[key, value[0], value[1]] for key, value in code._backoff.items()],
                "stopped": [list(key) for key in code._stopped],
                "unsure": [[key, said] for key, said in code._unsure.items()],
                "missing": [[key, since] for key, since in code._missing.items()]}
    return None


def operate(op):
    args, kwargs = op.get("args", []), op.get("kwargs", {})
    if "clock" in op:
        clock[0] = op["clock"]
        return None
    if "world" in op:
        for key, value in op["world"].items():
            WORLD[key] = value
            for name in [name for name in CURSORS if name.startswith(key)]:
                del CURSORS[name]
        return None
    if "switches" in op:
        SWITCHES.update(op["switches"])
        return None
    if op.get("log") is True:
        found = list(LOG)
        LOG.clear()
        return found
    if "method" in op:
        return getattr(state, op["method"])(*args, **kwargs)
    if "fn" in op:
        return pure(op["fn"], args, kwargs)
    if "inuse" in op:
        what = op["inuse"]
        if what == "tell":
            try:
                return inuse.tell(paths, args[0], args[1])
            except OSError:
                return {"raised": "OSError"}
        if what == "forget":
            return inuse.forget(paths)
        if what == "told":
            return lower(inuse.told(paths))
        if what == "elsewhere":
            return sorted(inuse.elsewhere(paths))
    if "make" in op:
        return make(op)
    if "hook" in op:
        code = MADE[op["code"]]
        hook = op["hook"]
        a = list(args) + [None] * 3
        if hook in ("tick", "records", "watched_due"):
            found = getattr(code, hook)(VIEW)
        elif hook == "gate":
            found = code.gate(a[0], a[1], a[2])
        elif hook == "schedule":
            found = code.schedule(a[0], a[1])
        else:
            found = getattr(code, hook)(a[0])
        if hasattr(found, "run"):
            PENDING[op["code"]] = found
        return found
    if "run" in op:
        if op["run"] not in PENDING:
            return {"__raised__": "NoErrand"}
        errand = PENDING.pop(op["run"])
        try:
            return errand.run(guard)
        except Exception:
            return {"__raised__": "Exception"}
    if "kept" in op:
        return kept(MADE[op["kept"]])
    raise LookupError("op")


lines = []
for op in request.get("ops", []):
    try:
        found = operate(op)
        if isinstance(found, dict) and "__raised__" in found:
            lines.append({"raised": found["__raised__"]})
        else:
            lines.append({"ok": canon(found)})
    except Exception as exc:
        lines.append({"raised": type(exc).__name__})
state.close()
sys.stdout.write("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))
'''


def binary() -> Path:
    named = os.environ.get("CODEX_AR_ADVUSAGE_EXE")
    return Path(named) if named else advref.target_dir() / "release" / "examples" / "advusage.exe"


def build() -> None:
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advusage",
                    "--manifest-path", str(advref.ADVANCED / "Cargo.toml")], env=environment, check=True,
                   creationflags=NO_WINDOW, timeout=3600)


def ensure() -> None:
    if not binary().is_file():
        build()


def lines_of(done: subprocess.CompletedProcess, who: str) -> list:
    if done.returncode != 0:
        raise AssertionError("%s failed (%d): %s" % (who, done.returncode, done.stderr[-3000:].decode("utf-8", "replace")))
    return [json.loads(line) for line in done.stdout.decode("utf-8").splitlines() if line.strip()]


def normal(answer):
    """The meter's held engine and inuse's paths, compared case-folded (pathlib's Windows paths compare so)."""
    if isinstance(answer, dict):
        return {key: (normal_paths(value) if key == "held" else normal(value)) for key, value in answer.items()}
    if isinstance(answer, list):
        return [normal(item) for item in answer]
    return answer


def normal_paths(value):
    return [str(part).lower() for part in value] if isinstance(value, list) else value


class AdvUsageDiff(unittest.TestCase):
    """A diff of S7.2d's modules: `same(...)` runs one request through both sides on one scratch home and holds every
    answer, the world's log and the advanced state left equal."""

    @classmethod
    def setUpClass(cls):
        ensure()
        advref.package(TAG)
        cls.catalogs = str(advref.locales(TAG))
        cls.root = Path(tempfile.mkdtemp(prefix="advusage-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)

    def same(self, label: str, ops: list, *, world: dict | None = None, clock: float = CLOCK, setup=None) -> list:
        folder = self.root / ("case-%d" % len(list(self.root.iterdir())))
        home, profile = folder / "home", folder / "profile"
        request_path = folder / "request.json"
        left = []
        for side in ("reference", "rust"):
            shutil.rmtree(home, ignore_errors=True)
            home.mkdir(parents=True)
            profile.mkdir(parents=True, exist_ok=True)
            if setup is not None:
                setup(home)
            request = {"home": str(home), "clock": clock, "tokens": 0, "catalogs": self.catalogs,
                       "world": world or {}, "ops": ops}
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            if side == "reference":
                done = advref.run(REFERENCE, str(request_path), profile=profile, tag=TAG, timeout=1800)
            else:
                done = subprocess.run([str(binary()), str(request_path)], capture_output=True,
                                      env=advref.environment(profile, TAG), cwd=str(profile),
                                      creationflags=NO_WINDOW, timeout=1800)
            answers = [normal(line) for line in lines_of(done, side)]
            state = home / "config" / "advanced" / "advanced.sqlite"
            left.append((answers, advstore.dump(state) if state.is_file() else None))
        (want, want_state), (got, got_state) = left
        self.assertEqual(len(want), len(got), label)
        for index, (one, other) in enumerate(zip(want, got)):
            if diffs.encode(one) != diffs.encode(other):
                self.fail("%s: op %d differs at %s\n  op        %s\n  reference %s\n  rust      %s" % (
                    label, index, advdiff.first_difference(one, other), json.dumps(ops[index], ensure_ascii=False)[:700],
                    json.dumps(one, ensure_ascii=False)[:900], json.dumps(other, ensure_ascii=False)[:900]))
        self.assertEqual(want_state, got_state, "%s: the advanced state left differs" % label)
        return want

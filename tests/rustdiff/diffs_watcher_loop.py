"""S6.1, car-watcher: the watch loop (runtime/loop.py) over one scripted world, traced on both sides.

`LOOP` runs under the reference tag's Python: the tag's own `App` on a scratch home, every collaborator the loop asks
of `self` answered from the scenario (the named objects entered, busy, abandoned or refused; every wait - stop, wake,
or the time running out - on a clock of the script's own; the store's opens; the engine's builds, ticks, watches and
readings; the process's memory; the self-check's looks), the tag's own Health, Waking, store, status file and
self-check writer doing their real work. The same scenario goes to `car-harness serve` as `watcher.loop`
(rust/crates/car-harness/src/watcher.rs), whose world answers the same way over car-watcher's `watchloop::run`.

Equal for every scenario: the exit code; every log line, in order (the home's path written `<HOME>`); every call the
loop made of its world, in order, with its arguments (each wait's seconds among them); and the files the run wrote -
the heartbeat row of state.sqlite, status.json and selfcheck.json, byte for byte.

The scenarios: each exit code (0 stop, 0 once, 1 a refused mutex, a refused stop event and a once with no engine, 3
the double look and a busy Codex home, 4 a newer state at the open and mid-tick, 5 the memory guard), a status probe
lost to and won on the second look, an abandoned mutex, no wake event, the store's open retried with its backoff and
stopped while it waits, a tick that fails and one that cannot build its engine (a settings file that cannot be read,
an engine that will not start), Retry now's wake and its coalescing, the one-second watch while something may be
queued, the memory guard's warning, the status file on, the usage reading kept once, the self-check's detection rules
over three ticks, an error code this version does not know, and the poll interval from the settings and the argument.
No named object of the product's, no timer, no window, no Codex: nothing of the machine is asked.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from rustdiff import core, diffs, reference

MIB = 1024 * 1024
T0 = 1_700_000_000.0 + 86_400.0 * 400

LOOP = r'''
import builtins, json, os, sys, types, time as real_time
from pathlib import Path
from codex_auto_resume import config, settings as policy, store as store_mod
from codex_auto_resume.runtime import app as app_mod, loop as loop_mod
from codex_auto_resume.runtime.health import Health
from codex_auto_resume.runtime.waking import Waking
from codex_auto_resume.windows import AdapterError

MONO = 1_700_000_000.0
scenarios = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
base = Path(sys.argv[2])
os.getpid = lambda: 4242
RealStore = store_mod.Store
out = []

def exc(name):
    if name == "Unreadable":
        return policy.Unreadable("x", True)
    if hasattr(store_mod, name):
        return getattr(store_mod, name)("x")
    found = getattr(builtins, name, None)
    return found("x") if isinstance(found, type) else type(name, (Exception,), {})("x")

for number, sc in enumerate(scenarios):
    home = base / ("py-%d" % number)
    home.mkdir(parents=True)
    paths = config.Paths(home)
    paths.ensure()
    if sc.get("settings"):
        values = policy.defaults()
        values.update(sc["settings"])
        policy.save(paths.settings_file, values)
    calls, lines = [], []
    lists = {key: list(sc.get(key, [])) for key in ("mutex", "stop", "wake", "home_lock", "waits", "opens", "builds",
                                                     "ticks", "watches", "watch_needed", "usage", "memory")}

    def nxt(key, otherwise):
        found = lists[key]
        return found.pop(0) if found else otherwise

    def raised(value):
        if isinstance(value, dict) and "raise" in value:
            raise exc(value["raise"])
        return value

    class Clock:
        t = float(sc.get("clock", 0.0))
    clock = Clock()
    fake_time = types.SimpleNamespace(time=lambda: clock.t, monotonic=lambda: clock.t - MONO,
                                      strftime=real_time.strftime, localtime=real_time.localtime)

    def sleep(seconds):
        calls.append(["sleep", float(seconds)])
        clock.t += max(0.0, seconds)
    fake_time.sleep = sleep
    loop_mod.time = fake_time
    loop_mod.uuid = types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex="0123456789ab" + "0" * 20))

    def store_open(*args, **kwargs):
        if kwargs.get("migrate"):
            calls.append(["open"])
            raised(nxt("opens", None))
        return RealStore(*args, **kwargs)
    loop_mod.Store = store_open
    loop_mod.sweep_set_aside = lambda paths, log: calls.append(["sweep"])
    loop_mod._app_runs = lambda: (calls.append(["app_runs"]), sc.get("app_runs"))[1]

    class NoPower:
        @staticmethod
        def awake_seconds():
            return None

        class WakeListener:
            def __init__(self, heard):
                calls.append(["listener"])

            def start(self):
                return False

            def stop(self):
                pass

        @staticmethod
        def keep_awake(on):
            calls.append(["keep_awake", on])
            return False

        @staticmethod
        def on_mains():
            return None
    loop_mod.Waking = lambda signal, log: Waking(signal=signal, log=log, port=NoPower, clock=fake_time.time)

    def no_afterwork(**kwargs):
        raise OSError("no power action here")
    loop_mod.AfterWork = no_afterwork

    app = app_mod.App(paths)
    home_text = str(paths.home)

    class Rec:
        def info(self, text, *args):
            lines.append((text % args if args else text).replace(home_text, "<HOME>"))
    app.logger = Rec()

    def record_failure(label):
        cls = sys.exc_info()[0]
        name = cls.__name__ if cls else "error"
        calls.append(["failure", label, name])
        app.logger.info("%s failed (%s); no submission was made", label, name)
    app._record_failure = record_failure

    class Obj:
        def __init__(self, what):
            self.what, self.abandoned, self.handle, self.held, self.identity = what, False, None, True, None

        def __exit__(self, *rest):
            calls.append(["exit", self.what])

    def named(what):
        def make(*args, **kwargs):
            made = Obj(what)

            def enter():
                answer = nxt(what, "ok")
                calls.append(["enter", what])
                if answer in ("ok", "abandoned"):
                    made.abandoned = answer == "abandoned"
                    return made
                raise AdapterError(answer)
            made.__enter__ = enter
            return made
        return make
    app.mutex, app.stop_event, app.wake_event, app.home_lock = (named("mutex"), named("stop"), named("wake"),
                                                                named("home_lock"))

    def wait_for(stop, wake, seconds):
        calls.append(["wait", wake is not None, float(seconds)])
        answer = nxt("waits", "stop")
        fired, after = (answer.get("fired"), answer.get("after")) if isinstance(answer, dict) else (answer, None)
        fired = fired if fired in ("stop", "wake") else None
        clock.t += max(0.0, after if after is not None else (seconds if fired is None else 0.5))
        return fired
    app._wait_for = wait_for

    class Source:
        def latest_failures(self, since, admissible=False, shapes=False):
            calls.append(["latest_failures", float(since)])
            return list(sc.get("failures", []))

    class Engine:
        def __init__(self):
            self.detection_failed = sc.get("detection_failed")
            self.handed_waits, self.options, self.source = {}, {}, Source()

        def tick(self):
            calls.append(["tick"])
            raised(nxt("ticks", "ok"))

        def watch_needed(self):
            return bool(raised(nxt("watch_needed", False)))

        def watch(self):
            calls.append(["watch"])
            raised(nxt("watches", None))

        def last_usage(self):
            found = nxt("usage", None)
            return tuple(found) if isinstance(found, list) and len(found) == 2 else None

        def after_sleep(self, since, slept):
            calls.append(["after_sleep", since, slept])

        def apply_policy(self, values, managed):
            pass

    def build(store, **kwargs):
        calls.append(["build"])
        raised(nxt("builds", None))
        return Engine()
    app.engine = build
    app.engine_moved = lambda: (calls.append(["moved"]), False)[1]
    app._compatibility_tick = lambda: calls.append(["compat"])
    app.refresh_settings = lambda engine: calls.append(["refresh"])
    app._failure_baseline = lambda: calls.append(["baseline"])
    app._start_tray = lambda stop: None
    app._edition_surface = lambda store: None
    app._recovery_facts = lambda store, engine: (calls.append(["facts"]),
                                                 (sc.get("facts_runs"), dict(sc.get("facts") or {})))[1]

    def no_backend():
        raise OSError("no Codex here")
    app.backend = no_backend
    app._watcher_notice = lambda event, detail, final=False: calls.append(["notice", event, detail, final])

    class Memory:
        @staticmethod
        def memory():
            found = nxt("memory", None)
            return tuple(found) if isinstance(found, list) and len(found) == 2 else None

        @staticmethod
        def sign_in():
            return "S-1-5-21-0-0-0-1001:7"

        @staticmethod
        def booted_at():
            return 1_700_000_000.0
    app._new_health = lambda: Health(paths=app.paths, log=app.logger.info, notice=app._watcher_notice, port=Memory,
                                     clock=fake_time.time)
    code = app.run(once=bool(sc.get("once")), poll=sc.get("poll"))
    out.append({"home": home_text, "values": json.loads(json.dumps(app.settings)), "version": config.version(),
                "code": code, "lines": lines, "calls": calls})
sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''


def wait(fired=None, after=None):
    found = {"fired": fired}
    if after is not None:
        found["after"] = after
    return found


TIMEOUT = wait(None)
STOP = wait("stop")
FAILURE = {"category": "unknown", "completed_at": T0 - 100.0, "shape": {"form": "tagged", "code": "brandNewTrouble"}}
WINDOWS = [{"window_minutes": 300, "used_percent": 12.5, "reset_at": T0 + 3600}]

SCENARIOS = [
    {"name": "stop after two ticks", "waits": [TIMEOUT, STOP]},
    {"name": "once", "once": True},
    {"name": "once with no engine", "once": True, "builds": [{"raise": "OSError"}]},
    {"name": "mutex refused", "mutex": ["windows_required"]},
    {"name": "a probe lost to once", "mutex": ["mutex_busy", "ok"], "waits": [STOP]},
    {"name": "another watcher", "mutex": ["mutex_busy", "mutex_busy"]},
    {"name": "abandoned", "mutex": ["abandoned"], "waits": [STOP]},
    {"name": "stop event refused", "stop": ["stop_event_squatted"]},
    {"name": "no wake event", "wake": ["wake_event_squatted"], "waits": [TIMEOUT, STOP]},
    {"name": "codex home busy", "home_lock": ["home_lock_busy"]},
    {"name": "open retried", "opens": [{"raise": "StoreError"}, {"raise": "OSError"}, {"raise": "StoreError"}],
     "waits": [TIMEOUT, TIMEOUT, TIMEOUT, STOP]},
    {"name": "stopped while the open waits", "opens": [{"raise": "StoreError"}], "waits": [STOP]},
    {"name": "newer state at the open", "opens": [{"raise": "StateFromNewerVersion"}]},
    {"name": "newer state mid-tick", "ticks": ["ok", {"raise": "StateFromNewerVersion"}], "waits": [TIMEOUT]},
    {"name": "newer rows mid-tick", "ticks": [{"raise": "RecordSchemaMismatch"}]},
    {"name": "a tick that fails", "ticks": [{"raise": "OSError"}, {"raise": "StoreError"}, "ok"],
     "waits": [TIMEOUT, TIMEOUT, STOP]},
    {"name": "no engine yet", "builds": [{"raise": "Unreadable"}, {"raise": "RuntimeError"}],
     "waits": [TIMEOUT, TIMEOUT, STOP]},
    {"name": "retry now", "waits": [wait("wake", 1.0), wait("wake", 10.0), TIMEOUT, STOP]},
    {"name": "stopped while a wake coalesces", "waits": [wait("wake", 0.5), STOP]},
    {"name": "watching", "watch_needed": [True, True, True, False], "watches": [None, {"raise": "OSError"}],
     "waits": [TIMEOUT, TIMEOUT, TIMEOUT, STOP]},
    {"name": "memory guard stops", "settings": {"memory_guard": "stop", "memory_guard_limit": "mb256"},
     "memory": [[300 * MIB, 310 * MIB]]},
    {"name": "memory guard warns", "settings": {"memory_guard": "warn", "memory_guard_limit": "mb256"},
     "memory": [[100 * MIB, 120 * MIB], [300 * MIB, 305 * MIB], [301 * MIB, 302 * MIB]], "waits": [TIMEOUT, TIMEOUT, STOP]},
    {"name": "status file", "settings": {"status_file": True}, "memory": [[50 * MIB, 60 * MIB]],
     "waits": [TIMEOUT, STOP]},
    {"name": "usage kept once", "usage": [[T0 - 10, WINDOWS], [T0 - 10, WINDOWS], [T0 + 50, WINDOWS]],
     "waits": [TIMEOUT, TIMEOUT, STOP]},
    {"name": "history unreadable", "detection_failed": True, "app_runs": True,
     "waits": [TIMEOUT, TIMEOUT, TIMEOUT, STOP]},
    {"name": "engine missing", "builds": [{"raise": "OSError"}] * 4, "app_runs": True,
     "waits": [TIMEOUT, TIMEOUT, TIMEOUT, STOP]},
    {"name": "an unknown error code", "failures": [FAILURE, dict(FAILURE, completed_at=T0 - 50.0)],
     "waits": [wait(None, 61.0), STOP]},
    {"name": "recovery facts", "facts_runs": True, "facts": {"held_elsewhere": True},
     "waits": [wait(None, 61.0), wait(None, 61.0), STOP]},
    {"name": "poll from the settings", "settings": {"poll_seconds": 7}, "waits": [TIMEOUT, STOP]},
    {"name": "poll argument clamped", "poll": 2, "waits": [TIMEOUT, STOP]},
]


def heartbeat(home: Path):
    database = home / "config" / "state.sqlite"
    if not database.is_file():
        return None
    with sqlite3.connect(str(database)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM watcher_status")]


def files(home: Path) -> dict:
    found = {}
    for name in ("status.json", "selfcheck.json"):
        path = home / "config" / name
        found[name] = path.read_bytes().decode("utf-8", "replace") if path.is_file() else None
    found["heartbeat"] = heartbeat(home)
    return found


class WatchLoopDiff(diffs.Base):
    def test_loop_traces(self):
        scenarios = [dict(each, clock=T0) for each in SCENARIOS]
        base = self.profile("homes").resolve()
        listing = base / "scenarios.json"
        listing.write_text(json.dumps(scenarios), encoding="utf-8")
        made = reference.run(LOOP, str(listing), str(base), profile=self.profile("reference"))
        self.assertEqual(made.returncode, 0, made.stderr[-4000:].decode("utf-8", "replace"))
        expected = json.loads(made.stdout.decode("utf-8"))
        dump = os.environ.get("CAR_WATCHER_DUMP")
        if dump:
            Path(dump).write_text(json.dumps(expected, ensure_ascii=False, indent=1), encoding="utf-8")
        self.assertEqual(len(expected), len(scenarios))
        with core.Harness(reference.scratch_environment(self.profile("rust"))) as harness:
            for number, (scenario, want) in enumerate(zip(scenarios, expected)):
                home = base / ("rs-%d" % number)
                home.mkdir()
                script = dict(scenario, values=want["values"], version=want["version"])
                _id, line = harness.call("watcher.loop", home=str(home), script=script)
                reply = json.loads(line.decode("utf-8"))
                self.assertTrue(reply["reply"].get("ok"), line[:600])
                got = reply["reply"]["value"]
                label = scenario["name"]
                self.assertEqual(want["code"], got["code"], label)
                self.assertEqual(want["lines"], got["lines"], label)
                self.assertEqual(diffs.encode(want["calls"]), diffs.encode(got["calls"]), label)
                py_files, rs_files = files(Path(want["home"])), files(home)
                self.assertEqual(py_files, rs_files, label)
        if os.environ.get("CAR_WATCHER_SAY"):
            print("watch loop: %d scenarios equal" % len(scenarios))

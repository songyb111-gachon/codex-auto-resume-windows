"""car-control's acting bridge commands (seat S5.1b): the same requests through the reference tag's `controlcli` and
through car-control, over the same scratch installation and the same world (bridgeworld's, with actworld's acting
stand-ins), held equal byte for byte: the replies and the exit code, every file the commands wrote (settings,
power-action.json, once-words.json, the usage checks, a diagnostics bundle, codex-start.log), every row of the state
afterwards, and the calls each side made through its Host seam - in order, with their arguments.

* GoldenActsDiff   - every case the wire goldens ask of the S5.1b commands (`wiregolden.BRIDGE_CASES`), their
                     stand-ins (`using`) given as the world or as files made before the stream.
* WatcherDiff      - start-watcher and stop-watcher over the mutex's answers in turn, the launch refused or ended,
                     the launcher missing, the install lock, a chosen Python; startup over the Run key's answers.
* ActionsDiff      - the record actions over every waiting state, the administrator's keys, a legacy state, a
                     state that cannot be opened, ids of every kind; Retry now and Rescan's usage reading under each
                     thing that stops it; Rescan's judge answering every outcome, raising, or refused.
* PowerDiff        - power-action, power-arm and power-disarm over the port's answers and every kind of file.
* RegistryDiff     - compatibility, compat-import, compat-refresh, detection-check and demo over the stand-ins.
* OwnReportDiff    - own-report over damaged, empty, old, newer and huge states, logs of every kind, the watcher's
                     report in force or not.
* DiagnosticsDiff  - the bundle's bytes over the golden, empty and damaged homes; names refused and taken.
* ControlCallDiff  - the methods no bridge command reaches: the start with Codex, the watcher's and a notice's
                     power-action writers, Retry now and Rescan as another actor.
* PowerGuardDiff   - the harness runs with CAR_NO_POWER_ACTION set, and no answer here ever acts.

Run by run.py; never by the lanes' discovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

from rustdiff import actworld as aw
from rustdiff import bridgeworld as bw
from rustdiff import core, reference
from rustdiff.diffs import RECORD
from rustdiff.diffs_bridge import TEMPLATES, BridgeBase, lines, request

ROOT = core.ROOT
for entry in (ROOT / "tests", ROOT / "build", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import wiregolden as wg  # noqa: E402

T1, T2, T3, T4, T5 = wg.T1, wg.T2, wg.T3, wg.T4, wg.T5
RESET, BACKOFF, RECOVERED, EXHAUSTED, NO_SUCH = (wg.WAITING_RESET, wg.WAITING_BACKOFF, wg.RECOVERED, wg.EXHAUSTED,
                                                 wg.NO_SUCH)
ACTING = ("start-watcher", "stop-watcher", "clear-history", "cancel-all", "rescan", "demo", "power-action",
          "detection-check", "own-report", "enabled", "startup", "cancel", "reset-budget", "retry-now",
          "thread-enabled", "cancel-thread", "diagnostics", "interruption-recovery", "compatibility",
          "compat-import", "compat-refresh", "postpone", "unpostpone", "release-hold", "thread-tier",
          "project-rule", "power-arm", "power-disarm", "once-words")
COUNTS = {"streams": 0, "requests": 0, "calls": 0}


def golden_now() -> float:
    import make_screenshots

    return float(make_screenshots.ENVELOPE_NOW)


NOW = None


def now() -> float:
    global NOW
    if NOW is None:
        NOW = golden_now()
    return NOW


def power_file(document) -> "callable":
    """A power-action.json of these bytes (or this document) in the home before the stream."""
    def tune(workspace: Path):
        path = workspace / "home" / "config" / "power-action.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = document if isinstance(document, bytes) else json.dumps(document, sort_keys=True).encode("utf-8")
        path.write_bytes(data)
    return tune


def armed(**changes) -> dict:
    """A power-action.json armed as the Dashboard arms it, under a fixed nonce."""
    at = now() - 600
    arming = {"nonce": "0123456789abcdef", "action": "shut_down", "after": "any_end", "repeat": "always",
              "grace_seconds": 1800, "armed_at": at, "since": at, "carried": [], "stop_at": None}
    arming.update(changes.pop("armed", {}))
    document = {"format": "codex-auto-resume-power-action/1", "armed": arming, "shown": None, "last": None}
    document.update(changes)
    return document


def chained(*tunes):
    def tune(workspace):
        for each in tunes:
            if each is not None:
                each(workspace)
    return tune


def with_store(action):
    """`action(store)` on the home's own state, through the worktree's store (as wiregolden's stand-ins do)."""
    def tune(workspace: Path):
        from codex_auto_resume import config
        from codex_auto_resume.store import Store

        with Store(config.Paths(workspace / "home").state_dir) as store:
            action(store)
    return tune


def filed(thread, folder):
    def tune(workspace: Path):
        connection = sqlite3.connect(workspace / "codex" / "state_5.sqlite")
        try:
            with connection:
                connection.execute("UPDATE threads SET cwd=? WHERE id=?", (folder, thread))
        finally:
            connection.close()
    return tune


def write_file(relative, data):
    def tune(workspace: Path):
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return tune


class ActingBase(BridgeBase):
    @classmethod
    def setUpClass(cls):
        super(BridgeBase, cls).setUpClass()
        profile = Path(tempfile.mkdtemp(prefix="car-v0627-bridge6-profile-"))
        cls.addClassCleanup(shutil.rmtree, profile, True)
        # S5.1b: the power guard is set for the harness as every test runner sets it (fix4 S3).
        cls.harness = core.Harness(reference.scratch_environment(profile, CAR_NO_POWER_ACTION="1")).__enter__()
        cls.addClassCleanup(cls.harness.__exit__, None, None, None)

    def template(self, kind: str) -> Path:
        if kind == "acts" and kind not in TEMPLATES:
            golden = super().template("golden")
            folder = Path(tempfile.mkdtemp(prefix="car-v0627-bridge6-template-"))
            shutil.copytree(golden, folder, dirs_exist_ok=True)
            from codex_auto_resume import config

            wg._seed_exhausted(config.Paths(folder / "home"))
            TEMPLATES[kind] = folder
        return super().template(kind)

    def run_both(self, kind, *, requests=None, world=None, tune=None, label="", mode="serve", argv=(),
                 method=None, args=(), stdin=None):
        """Both sides on fresh copies at one path; everything compared. Returns the reference's output."""
        ran = []
        for side in ("reference", "rust"):
            workspace = self.workspace(kind, tune)
            made = world(workspace) if callable(world) else dict(world or {})
            if kind in ("golden", "acts"):
                made.setdefault("now", now())
            asked_world = aw.world_for(workspace, **made)
            asked = requests(workspace) if callable(requests) else requests
            stream = stdin(workspace) if callable(stdin) else (stdin if stdin is not None else
                                                              (lines(*asked) if asked else b""))
            home = workspace / "home"
            if side == "reference":
                code, out, err, calls, result = aw.ask_reference(home, asked_world, mode="call" if method else mode,
                                                                 stdin=stream, argv=argv, method=method, args=args)
            else:
                err = b""
                if method:
                    result, calls = aw.call_rust(self.harness, home, asked_world, method, args)
                    code, out = 0, b""
                else:
                    code, out, calls, guard = aw.ask_rust(self.harness, home, asked_world, mode=mode, stdin=stream,
                                                          argv=argv)
                    self.assertTrue(guard, "the harness must run with CAR_NO_POWER_ACTION set")
                    result = None
            files = {name: data for name, data in bw.files_of(workspace).items() if not name.startswith("profile/")}
            ran.append((code, out, err, files, aw.state_dump(home), calls, result))
        (code, expected, err, files, state, calls, result), (code2, actual, _, files2, state2, calls2, result2) = ran
        label = label or "a stream"
        if actual != expected:
            at = next((index for index, (a, b) in enumerate(zip(actual, expected)) if a != b),
                      min(len(actual), len(expected)))
            self.fail("%s: the output differs at byte %d (reference exit %d, rust exit %d; reference stderr %r)\n"
                      "reference: ...%s\nrust:      ...%s" % (
                          label, at, code, code2, err[-600:],
                          expected[max(0, at - 300):at + 300].decode("utf-8", "replace"),
                          actual[max(0, at - 300):at + 300].decode("utf-8", "replace")))
        self.assertEqual(code2, code, "%s: the exit code differs (reference stderr %r)" % (label, err[-600:]))
        # Compared without unittest's difflib, which takes hours over a list of a thousand calls.
        for what, mine, theirs in (("the method's answer", result2, result), ("the files written", files2, files),
                                   ("the state written", state2, state), ("the Host calls", calls2, calls)):
            if mine != theirs:
                self.fail("%s: %s differ at %s (reference stderr %r)" % (label, what, first_difference(theirs, mine),
                                                                       err[-600:]))
        COUNTS["streams"] += 1
        COUNTS["requests"] += len(requests) if isinstance(requests, list) else 0
        COUNTS["calls"] += len(calls or [])
        return expected, result


MISSING = object()


def first_difference(theirs, mine, path="") -> str:
    """Where two answers first differ, and how: the reference's value, then car-control's."""
    if type(theirs) is not type(mine):
        return ("%s: reference %r, rust %r" % (path or "the whole", theirs, mine))[:3000]
    if isinstance(theirs, dict):
        for key in sorted(set(theirs) | set(mine), key=str):
            a, b = theirs.get(key, MISSING), mine.get(key, MISSING)
            if a is MISSING or b is MISSING:
                return "%s[%r]: present on %s only" % (path, key, "the reference" if b is MISSING else "rust")
            if a != b:
                return first_difference(a, b, "%s[%r]" % (path, key))
    if isinstance(theirs, list):
        for index, (a, b) in enumerate(zip(theirs, mine)):
            if a != b:
                return first_difference(a, b, "%s[%d]" % (path, index))
        return "%s: %d items on the reference, %d on rust; next %r" % (
            path, len(theirs), len(mine), (theirs[len(mine):] or mine[len(theirs):])[:3])
    return ("%s: reference %r, rust %r" % (path or "the whole", theirs, mine))[:3000]


def stream(command, *arguments, start=1):
    """One request per argument (None for none), ids from `start`."""
    return [request(command, argument, ident=start + index) for index, argument in enumerate(arguments)]


# ------------------------------------------------------------------------------ the goldens' own cases
SLEEP_ONCE = wg.SLEEP_ONCE
SHUT_DOWN_ALWAYS = wg.SHUT_DOWN_ALWAYS


def golden_streams() -> list:
    """(label, kind, world, tune, requests) for every case wiregolden asks of an S5.1b command, the cases of a command
    that share a world in one stream (in the goldens' order), a stand-in's own case in a stream of its own after the
    ones before it."""
    out = []

    def add(label, requests, world=None, tune=None, kind="acts"):
        out.append((label, kind, world or {}, tune, requests))

    add("start-watcher: a watcher already holds the mutex", stream("start-watcher", None),
        {"watcher_running": True})
    add("start-watcher: launched, and it stopped again straight away", stream("start-watcher", None),
        {"watcher_running": False, "launch": {"pid": 4242, "polls": [1]}})
    add("start-watcher: refused while an installation holds the install lock", stream("start-watcher", None),
        {"watcher_running": False, "install_in_progress": True})
    add("stop-watcher: no watcher is running", stream("stop-watcher", None), {"watcher_running": False})
    add("stop-watcher: the watcher does not let go before the wait is over", stream("stop-watcher", None),
        {"watcher_running": True, "signals": {"stop": True}})
    add("clear-history, twice", stream("clear-history", None, None))
    add("cancel-all, twice", stream("cancel-all", None, None))
    add("rescan, twice", stream("rescan", None, None))
    add("demo", stream("demo", None), {"watcher_running": False})
    add("own-report: no Codex version is named yet", stream("own-report", None))
    add("own-report: the watcher's report names the pictures' Codex", stream("own-report", None),
        {"compat_view": {"status": "ok", "engine": {"version": "0.130.0", "found": True},
                         "capabilities": {"engine_present": {"state": "VERIFIED", "reason": "local_checks_passed"},
                                          "usage_probe": {"state": "CHECKED", "reason": "registry_checked"},
                                          "queue_withdraw": {"state": "CHECKED", "reason": "local_checks_passed"}}},
         "version": "0.0.0", "windows_version": "10.0.26100"})
    add("detection-check", stream("detection-check", None))
    add("enabled: paused, on again, refusals", stream("enabled", {"enabled": False}, {"enabled": True},
                                                       {"enabled": "false"}, {}))
    add("enabled: an administrator's pause", stream("enabled", {"enabled": False}, {"enabled": True}),
        {"managed": {"disable_auto_resume": True}})
    add("startup: registered, unregistered, refused", stream("startup", {"enabled": True}, {"enabled": False},
                                                             {"enabled": "true"}))
    add("cancel", stream("cancel", {"interruption_id": BACKOFF}, {"interruption_id": BACKOFF},
                         {"interruption_id": "not-an-id"}, {"interruption_id": NO_SUCH}))
    add("reset-budget", stream("reset-budget", {"interruption_id": EXHAUSTED}, {"interruption_id": RESET},
                               {"interruption_id": RECOVERED}, {"interruption_id": 7}))
    add("retry-now, the watcher running", stream("retry-now", {"interruption_id": RESET}, {"interruption_id": BACKOFF},
                                                 {"interruption_id": RECOVERED}, {"interruption_id": NO_SUCH}),
        {"watcher_running": True, "signals": {"wake": True}})
    add("retry-now, no watcher", stream("retry-now", {"interruption_id": RESET}, {"interruption_id": BACKOFF}),
        {"watcher_running": False})
    add("thread-enabled", stream("thread-enabled", {"thread_id": T1, "enabled": False},
                                 {"thread_id": T1, "enabled": True}, {"thread_id": T1.upper(), "enabled": True},
                                 {"thread_id": T1}))
    add("cancel-thread", stream("cancel-thread", {"thread_id": T2}, {"thread_id": "not-a-uuid"}))
    add("diagnostics", lambda ws: stream("diagnostics", {"path": str(ws / "diagnostics.json")},
                                         {"path": str(ws / "diagnostics.json")},
                                         {"path": str(ws / "diagnostics.txt")}))
    add("interruption-recovery", stream("interruption-recovery",
                                        {"interruption_id": RESET, "thread_id": T1, "enabled": False},
                                        {"interruption_id": RESET, "thread_id": T2, "enabled": True},
                                        {"interruption_id": RECOVERED, "thread_id": T3, "enabled": True},
                                        {"interruption_id": RESET, "thread_id": T1, "enabled": "on"}))
    add("compatibility", stream("compatibility", {}, {"live": True}, {"live": "yes"}))
    add("compat-import", lambda ws: stream(
        "compat-import", {"path": str(ws / "downloads" / "codex_compat.json"), "origin": "file"},
        {"path": str(ws / "downloads" / "older.json")}, {"path": str(ws / "downloads" / "broken.json")},
        {"path": str(ws / "downloads" / "registry.txt")}, {},
        {"path": str(ws / "downloads" / "codex_compat.json"), "origin": "web"}),
        {"compat_import": {"value": {"imported": True, "reason": None, "sequence": 4, "cache": "ok"}},
         "signals": {"wake": True}})
    add("compat-refresh", stream("compat-refresh", {}, {}))
    add("postpone", stream("postpone", {"interruption_id": RESET, "thread_id": T1, "preset": "1_hour"},
                           {"interruption_id": RESET, "thread_id": T1, "preset": "30_minutes"},
                           {"interruption_id": RESET, "thread_id": T1, "minutes": 180},
                           {"interruption_id": RESET, "thread_id": T1, "preset": "3_hours", "minutes": 240},
                           {"interruption_id": RESET, "thread_id": T1, "minutes": 10081},
                           {"interruption_id": RESET, "thread_id": T2, "preset": "3_hours"},
                           {"interruption_id": RECOVERED, "thread_id": T3, "preset": "3_hours"}))
    add("unpostpone", stream("unpostpone", {"interruption_id": RESET, "thread_id": T1},
                             {"interruption_id": RESET, "thread_id": T1},
                             {"interruption_id": RESET, "thread_id": T2},
                             {"interruption_id": RECOVERED, "thread_id": T3}),
        tune=with_store(lambda store: store.postpone(RESET, T1, now() + 3600, now(), actor="gui")))
    add("release-hold", stream("release-hold", {"interruption_id": RESET, "thread_id": T1},
                               {"interruption_id": RESET, "thread_id": T1},
                               {"interruption_id": RESET, "thread_id": T2},
                               {"interruption_id": NO_SUCH, "thread_id": T1}),
        tune=with_store(lambda store: store.set_thread_tier(T1, "ask_first", now(), actor="gui")))
    add("thread-tier", stream("thread-tier", {"thread_id": T1, "tier": "ask_first", "interruption_id": RESET},
                              {"thread_id": T1, "tier": None}, {"thread_id": T1, "tier": "sometimes"},
                              {"thread_id": T2, "tier": "ask_first", "interruption_id": RESET},
                              {"thread_id": T1}))
    add("project-rule", stream("project-rule", {"interruption_id": RESET, "thread_id": T1, "always": False},
                               {"interruption_id": RESET, "thread_id": T1, "always": True},
                               {"interruption_id": BACKOFF, "thread_id": T2, "always": False},
                               {"interruption_id": RESET, "thread_id": T1, "always": "yes"},
                               {"interruption_id": RESET, "thread_id": T2, "always": False},
                               {"interruption_id": RECOVERED, "thread_id": T3, "always": False}),
        tune=filed(T1, r"C:\work\alpha"))
    add("power-action: nothing armed", stream("power-action", None))
    add("power-action: hibernation off", stream("power-action", None), {"power": wg.NO_HIBERNATION})
    add("power-action: none for this account", stream("power-action", None), {"power": wg.NONE_FOR_THIS_ACCOUNT})
    add("power-action: an administrator's key", stream("power-action", None),
        {"managed": {"disable_power_action": True}})
    add("power-action: armed to shut down every time", stream("power-action", None), tune=power_file(armed()))
    add("power-action: armed for tasks a person picked", stream("power-action", None),
        tune=power_file(armed(armed={"action": "sleep", "after": "all_recovered", "repeat": "once",
                                     "grace_seconds": 300, "tasks": True})))
    add("power-arm", stream("power-arm", SLEEP_ONCE, SHUT_DOWN_ALWAYS, dict(SLEEP_ONCE, action="restart"),
                            dict(SLEEP_ONCE, grace_minutes="5"), dict(SLEEP_ONCE, grace_minutes=7),
                            dict(SLEEP_ONCE, nonce="0123456789abcdef")))
    add("power-arm: Windows does not offer it", stream("power-arm", dict(SLEEP_ONCE, action="hibernate")),
        {"power": wg.NO_HIBERNATION})
    add("power-arm: an administrator's key", stream("power-arm", SLEEP_ONCE),
        {"managed": {"disable_power_action": True}})
    add("power-disarm", stream("power-disarm", {}, None, {}, {"actor": "mcp"}), tune=power_file(armed()))
    add("once-words", stream("once-words", {"interruption_id": RESET},
                             {"interruption_id": RESET, "thread_id": T1, "text": "Then run the tests, please."},
                             {"interruption_id": RESET},
                             {"interruption_id": RESET, "thread_id": T1, "text": "{prompt}"},
                             {"interruption_id": RESET, "thread_id": T2, "text": "go"},
                             {"interruption_id": RECOVERED, "thread_id": T3, "text": "go"},
                             {"interruption_id": RESET, "thread_id": T1, "text": None},
                             {"interruption_id": "latest", "thread_id": T1, "text": "go"}))
    return out


class GoldenActsDiff(ActingBase):
    def test_every_golden_case(self):
        streams = golden_streams()
        covered = set()
        for label, kind, world, tune, requests in streams:
            with self.subTest(label):
                self.run_both(kind, requests=requests, world=world, tune=tune, label=label)
            made = requests(Path(".")) if callable(requests) else requests
            covered.update(each["command"] for each in made)
        self.assertEqual(sorted(set(ACTING) - covered), [], "an S5.1b command no golden stream asks")
        cases = sum(len(wg.BRIDGE_CASES.get(command, ())) for command in ACTING)
        RECORD.append("bridge acting: %d golden streams over %d commands (%d golden cases) equal - replies, files, the "
                      "state and the Host calls" % (len(streams), len(ACTING), cases))


# ------------------------------------------------------------------------------ the watcher's life
class WatcherDiff(ActingBase):
    def test_start(self):
        launcher = write_file("home/watcher-launcher.py", "# the stable launcher\n")
        chosen = write_file("home/runtimes/chosen.json", "{}")
        worlds = [
            ("comes up at the third look", {"probes": [False, False, False, True]}, launcher),
            ("comes up at the third look, entry script only", {"probes": [False, False, False, True]},
             write_file("home/app/src/auto_resume.py", "")),
            ("exits after two polls", {"probes": [False], "launch": {"pid": 5, "polls": [None, None, 3]}}, launcher),
            ("never seen: the whole wait", {"watcher_running": False, "launch": {"pid": 5, "polls": [None]}},
             launcher),
            ("never seen with a chosen Python", {"watcher_running": False, "launch": {"polls": [None]}},
             chained(launcher, chosen)),
            ("the probe cannot tell", {"watcher_running": None, "launch": {"polls": [None]}}, launcher),
            ("Windows refuses the launch", {"watcher_running": False,
                                            "launch": {"raise": ["FileNotFoundError", "[WinError 2] gone"]}},
             launcher),
            ("a launch fails another way", {"watcher_running": False, "launch": {"raise": ["ValueError", "x"]}},
             launcher),
            ("no windowless interpreter", {"watcher_running": False,
                                           "launcher": {"raise": ["StartupError", "no pythonw.exe beside x.exe"]}},
             launcher),
            ("nothing installed", {"watcher_running": False}, None),
            ("the install lock cannot be looked at", {"watcher_running": False, "install_in_progress": None},
             launcher),
            ("already running", {"watcher_running": True}, launcher),
        ]
        for label, world, tune in worlds:
            with self.subTest(label):
                self.run_both("acts", requests=stream("start-watcher", None, None), world=world, tune=tune,
                              label="start: " + label)
        for kind in ("fresh", "empty"):
            with self.subTest(kind):
                self.run_both(kind, requests=stream("start-watcher", None), world={"watcher_running": False},
                              label="start on a %s home" % kind)

    def test_stop(self):
        worlds = [
            ("lets go at the fourth look", {"probes": [True, True, True, True, False], "signals": {"stop": True}}),
            ("unknown throughout", {"watcher_running": None}),
            ("unknown, then gone", {"probes": [None, None, False]}),
            ("the event cannot be signalled", {"watcher_running": True, "signals": {"stop": {"raise": "OSError"}}}),
            ("held to the end", {"watcher_running": True, "signals": {"stop": False}}),
        ]
        for label, world in worlds:
            with self.subTest(label):
                self.run_both("acts", requests=stream("stop-watcher", None), world=world, label="stop: " + label)

    def test_startup(self):
        launcher = write_file("home/watcher-launcher.py", "")
        bundled = write_file("home/runtime/pythonw.exe", "")
        def ours(ws):
            return {"startup_value": "\"C:\\x\\pythonw.exe\" \"%s\" run" % (ws / "home" / "watcher-launcher.py")}
        cases = [
            ("nothing registered", {}, None),
            ("with the stable launcher", {}, launcher),
            ("with the bundled runtime", {}, chained(launcher, bundled)),
            ("a foreign value is left alone", {"startup_value": "pythonw.exe C:\\elsewhere\\watcher.py run"}, None),
            ("our own value", ours, launcher),
            ("the Run key cannot be read", {"startup_raise": {"read": "Cannot read the current user's Run key"}},
             None),
            ("the Run key cannot be written", {"startup_raise": {"install": "Cannot write the current user's Run key"}},
             launcher),
            ("the value cannot be removed", lambda ws: dict(ours(ws), startup_raise={
                "uninstall": "Cannot remove the current user's Run value"}), launcher),
            ("no windowless interpreter", {"launcher": {"raise": ["StartupError", "no pythonw.exe beside x"]}},
             launcher),
        ]
        for label, world, tune in cases:
            with self.subTest(label):
                self.run_both("acts", requests=stream("startup", {"enabled": True}, {"enabled": False},
                                                      {"enabled": True}, {"enabled": 1}, {}) + [
                    request("status", ident=9)], world=world, tune=tune, label="startup: " + label)


# ------------------------------------------------------------------------------ the record actions
EVERY_KEY = [RESET, BACKOFF, RECOVERED, EXHAUSTED, NO_SUCH, wg.key(1), wg.key(2), wg.key(3), wg.key(4), wg.key(5),
             "", None, 5, True, [RESET], "  " + RESET, RESET.upper(), "f" * 63, "f" * 65]


class ActionsDiff(ActingBase):
    def test_every_action_over_every_key(self):
        def build(_ws):
            made, ident = [], 1
            for key in EVERY_KEY:
                for command, extra in (("timeline", {}), ("reset-budget", {}), ("retry-now", {}),
                                       ("postpone", {"thread_id": T1, "minutes": 30}),
                                       ("unpostpone", {"thread_id": T1}), ("release-hold", {"thread_id": T1}),
                                       ("interruption-recovery", {"thread_id": T1, "enabled": False}),
                                       ("thread-tier", {"thread_id": T1, "tier": "notify_only"}),
                                       ("project-rule", {"thread_id": T1, "always": False}),
                                       ("once-words", {"thread_id": T1, "text": "Run the tests."}),
                                       ("cancel", {})):
                    made.append(request(command, dict(extra, interruption_id=key), ident=ident))
                    ident += 1
            return made
        for running in (True, False):
            with self.subTest(running=running):
                self.run_both("acts", requests=build, world={"watcher_running": running, "signals": {"wake": running}},
                              tune=filed(T1, r"C:\work\alpha"), label="every action, watcher %s" % running)

    def test_threads_of_every_kind(self):
        threads = [T1, T2, T3, T4, T5, T1.upper(), "not-a-uuid", "", None, 5, "11111111-1111-1111-1111-111111111111",
                   "{%s}" % T1, T1 + " "]
        requests = []
        for index, thread in enumerate(threads):
            requests += [request("thread-enabled", {"thread_id": thread, "enabled": index % 2 == 0},
                                 ident=3 * index + 1),
                         request("cancel-thread", {"thread_id": thread}, ident=3 * index + 2),
                         request("thread-tier", {"thread_id": thread, "tier": "ask_first"}, ident=3 * index + 3)]
        self.run_both("acts", requests=requests + [request("pending-all", ident=99)], label="threads")

    def test_postpone_every_way(self):
        ways = [{"preset": p} for p in ("10_minutes", "30_minutes", "1_hour", "3_hours", "tomorrow_morning",
                                        "tonight", "nope", 5, None)]
        ways += [{"minutes": m} for m in (1, 0, -1, 59.5, True, "30", 10080, 10081, 10 ** 20, 10 ** 400)]
        ways += [{"until": u} for u in (now() + 60, now() - 60, now() + 8 * 86400, "soon", None, float("inf")
                                        if False else 1e308)]
        ways += [{"preset": "1_hour", "until": now() + 60}, {}]
        requests = [request("postpone", dict(way, interruption_id=RESET, thread_id=T1), ident=index + 1)
                    for index, way in enumerate(ways)]
        requests += [request("unpostpone", {"interruption_id": RESET, "thread_id": T1}, ident=90),
                     request("pending", ident=91)]
        self.run_both("acts", requests=requests, label="postpone")

    def test_retry_now_and_what_stops_reading_usage(self):
        night = {"quiet_hours": True, "quiet_hours_start": "00:00", "quiet_hours_end": "23:59",
                 "quiet_hours_days": "every_day"}
        worlds = [
            ("running", {"watcher_running": True, "signals": {"wake": True}}, []),
            ("not running", {"watcher_running": False}, []),
            ("paused", {"watcher_running": True, "signals": {"wake": True}}, [request("enabled", {"enabled": False})]),
            ("paused by an administrator", {"managed": {"disable_auto_resume": True}, "signals": {"wake": True}}, []),
            ("observe only", {"signals": {"wake": True}}, [request("update", {"observe_only": True})]),
            ("quiet hours", {"signals": {"wake": True}}, [request("update", night)]),
            ("offline", {"signals": {"wake": True}, "internet": False},
             [request("update", {"wait_for_network": True})]),
            ("offline unknown", {"signals": {"wake": True}, "internet": None},
             [request("update", {"wait_for_network": True})]),
            ("the network cannot be asked", {"signals": {"wake": True}, "internet": {"raise": "OSError"}},
             [request("update", {"wait_for_network": True})]),
            ("the conversation off", {"signals": {"wake": True}},
             [request("thread-enabled", {"thread_id": T1, "enabled": False})]),
            ("the wake raises", {"signals": {"wake": {"raise": "OSError"}}}, []),
        ]
        for label, world, before in worlds:
            with self.subTest(label):
                requests = [dict(each, id=index + 1) for index, each in enumerate(before)] + [
                    request("retry-now", {"interruption_id": key}, ident=20 + index)
                    for index, key in enumerate((RESET, BACKOFF, EXHAUSTED, RESET))] + [
                    request("rescan", ident=30), request("rescan", ident=31), request("pending", ident=32)]
                self.run_both("acts", requests=requests, world=world, label="retry-now: " + label)

    def test_rescan_judges(self):
        judges = [
            ("every one retired", {"*": ["retired", "superseded_by_person"]}),
            ("every one rechecked", {"*": ["rechecked", None]}),
            ("a judge that raises", {"*": {"raise": "ValueError"}}),
            ("words a judge may not answer", {"*": ["send", 5]}),
            ("mixed", {RESET: ["retired", "newer_turn"], BACKOFF: ["rechecked", "ok"]}),
        ]
        for label, table in judges:
            for running in (True, False):
                with self.subTest(label=label, running=running):
                    self.run_both("acts", requests=stream("rescan", None, None) + [request("history", ident=9)],
                                  world={"judge": table, "watcher_running": running, "signals": {"wake": running}},
                                  label="rescan: %s, watcher %s" % (label, running))
        with self.subTest("the judge cannot be made"):
            self.run_both("acts", requests=stream("rescan", None), world={"judge_for": {"raise": "OSError"}},
                          label="rescan: no judge")

    def test_a_legacy_state_and_states_that_cannot_be_opened(self):
        requests = []
        ident = 1
        for command, argument in (("enabled", {"enabled": False}), ("enabled", {"enabled": True}),
                                  ("thread-enabled", {"thread_id": T1, "enabled": False}),
                                  ("cancel-thread", {"thread_id": T2}), ("cancel", {"interruption_id": RESET}),
                                  ("clear-history", None), ("cancel-all", None), ("rescan", None),
                                  ("power-action", None), ("power-arm", SLEEP_ONCE), ("power-disarm", None),
                                  ("retry-now", {"interruption_id": RESET}), ("own-report", None)):
            requests.append(request(command, argument, ident=ident))
            ident += 1

        def legacy(workspace):
            path = workspace / "home" / "config" / "state.sqlite"
            connection = sqlite3.connect(path)
            try:
                connection.execute("PRAGMA user_version=2")
                connection.commit()
            finally:
                connection.close()
        cases = [("garbage", write_file("home/config/state.sqlite", b"not a database" * 40)),
                 ("an empty file", write_file("home/config/state.sqlite", b"")),
                 ("an older schema", legacy)]
        for label, tune in cases:
            with self.subTest(label):
                self.run_both("acts", requests=requests, tune=tune, label="state: " + label)
        for kind in ("empty", "fresh"):
            with self.subTest(kind):
                self.run_both(kind, requests=requests, label="state: a %s home" % kind)


# ------------------------------------------------------------------------------ the power action
class PowerDiff(ActingBase):
    def test_files_of_every_kind(self):
        files = [
            ("missing", None),
            ("armed", power_file(armed())),
            ("armed and stopped", power_file(armed(armed={"stop_at": now() - 60}))),
            ("shown", power_file(armed(shown={"phase": "grace", "waiting_for": None, "grace_until": now() + 60,
                                              "nonce": "0123456789abcdef"}))),
            ("a last batch", power_file(armed(last={"action": "sleep", "result": "done", "at": now() - 100}))),
            ("garbage", power_file(b"{not json")),
            ("not UTF-8", power_file(b"\xff\xfe{}")),
            ("too large", power_file(b"{" + b" " * (33 * 1024) + b"}")),
            ("a list", power_file(b"[]")),
            ("another format", power_file({"format": "other/1", "armed": None})),
            ("deep", power_file(b"[" * 5000 + b"]" * 5000)),
            ("a folder", lambda ws: (ws / "home" / "config" / "power-action.json").mkdir(parents=True)),
        ]
        requests = [request("power-action", ident=1), request("status", ident=2),
                    request("power-arm", SLEEP_ONCE, ident=3), request("power-action", ident=4),
                    request("power-arm", dict(SHUT_DOWN_ALWAYS, grace_minutes=30), ident=5),
                    request("power-disarm", ident=6), request("power-disarm", {}, ident=7),
                    request("power-disarm", {"x": 1}, ident=8), request("status", ident=9),
                    request("power-arm", [1], ident=10), request("power-arm", "not json", ident=11)]
        for label, tune in files:
            with self.subTest(label):
                self.run_both("acts", requests=requests, tune=tune, label="power file: " + label)

    def test_the_port_and_the_keys(self):
        worlds = [("a port that raises", {"power": {"raise": "OSError"}}),
                  ("one action that raises", {"power": {"sleep": {"raise": "OSError"}}}),
                  ("a reason the card has no word for", {"power": {"sleep": "on_battery"}}),
                  ("every reason", {"power": {"sleep": "no_sleep_state", "hibernate": "hibernate_off",
                                              "shut_down": "no_privilege"}}),
                  ("an administrator's key", {"managed": {"disable_power_action": True}})]
        choices = [SLEEP_ONCE, SHUT_DOWN_ALWAYS, dict(SLEEP_ONCE, action="hibernate"),
                   dict(SLEEP_ONCE, after="handed_over_too"), dict(SLEEP_ONCE, repeat="sometimes"),
                   dict(SLEEP_ONCE, grace_minutes=True), {k: v for k, v in SLEEP_ONCE.items() if k != "after"}, {}]
        for label, world in worlds:
            with self.subTest(label):
                requests = [request("power-arm", choice, ident=index + 1) for index, choice in enumerate(choices)]
                self.run_both("acts", requests=[request("power-action", ident=99)] + requests + [
                    request("power-action", ident=100)], world=world, label="power: " + label)


# ------------------------------------------------------------------------------ the registry, the check, the demo
class RegistryDiff(ActingBase):
    def test_stand_ins_of_every_kind(self):
        answers = [
            ("values", {}),
            ("raising", {"compat_live": {"raise": "OSError"}, "compat_import": {"raise": "ValueError"},
                         "compat_refresh": {"raise": "TimeoutError"}, "checkup": {"raise": "KeyError"}}),
            ("not objects", {"compat_import": {"value": 5}, "compat_refresh": {"value": [1]}, "compat_live": 7,
                             "checkup": {"value": None}}),
            ("an import that names no import", {"compat_import": {"value": {"reason": "ok"}}}),
            ("an import made, the watcher woken", {"compat_import": {"value": {"imported": 1, "cache": "ok"}},
                                                   "signals": {"wake": True}}),
        ]
        for label, world in answers:
            with self.subTest(label):
                def build(ws):
                    target = str(ws / "doc.json")
                    return [request("compatibility", ident=1), request("compatibility", {"live": True}, ident=2),
                            request("compatibility", {"live": None}, ident=3),
                            request("compat-import", {"path": target}, ident=4),
                            request("compat-import", {"path": target, "origin": "main"}, ident=5),
                            request("compat-import", {"path": ""}, ident=6),
                            request("compat-import", {"path": 5}, ident=7),
                            request("compat-import", {"path": target, "origin": None}, ident=8),
                            request("compat-refresh", ident=9), request("detection-check", ident=10),
                            request("demo", ident=11)]
                self.run_both("acts", requests=build, world=world, label="registry: " + label)
        for word in (True, False, {"raise": "OSError"}):
            with self.subTest(demo=word):
                self.run_both("acts", requests=stream("demo", None), world={"signals": {"demo": word}},
                              label="demo %r" % (word,))

    def test_the_one_shot_form(self):
        cases = [("compat-import", "--file", "C:\\scratch\\doc.json", "--origin", "main"),
                 ("compat-import", "--file", "C:\\scratch\\doc.json"),
                 ("compat-import", "{\"path\": \"C:\\\\x.json\", \"origin\": \"file\"}"),
                 ("power-disarm", "{}"), ("power-disarm", "{\"a\": 1}"), ("start-watcher",), ("demo",),
                 ("rescan",), ("enabled", "{\"enabled\": false}"), ("startup", "-")]
        for argv in cases:
            with self.subTest(argv=argv):
                self.run_both("acts", mode="main", argv=argv, stdin=b"{\"enabled\": true}",
                              label="one shot %r" % (argv,))


# ------------------------------------------------------------------------------ this PC's own report
ENGINE_LINES = [
    "[2026-09-01 10:00:00] engine codex-cli 0.120.0 is verified: its local checks pass, and the registry data in force "
    "verifies this build.",
    "[2026-09-10 10:00:00] engine codex-cli 0.125.0 passes its local checks (`codex queue` still offers "
    "--thread/--message).",
    "[2026-09-20 10:00:00] engine codex-cli 0.130.0 is compatible: its local checks pass (`codex queue` still offers "
    "--thread/--message), and the registry data in force does not verify this build.",
]


def log_file(*texts, name="auto-resume.log", raw=None):
    return write_file("home/logs/" + name, raw if raw is not None else "\n".join(texts) + "\n")


def state_sql(*statements):
    def tune(workspace):
        connection = sqlite3.connect(workspace / "home" / "config" / "state.sqlite")
        try:
            for each in statements:
                connection.execute(each)
            connection.commit()
        finally:
            connection.close()
    return tune


class OwnReportDiff(ActingBase):
    def report(self, tune, label, world=None, kind="acts"):
        self.run_both(kind, requests=[request("own-report", ident=1), request("diagnostics",
                                                                              {"path": "C:\\nowhere\\x.txt"},
                                                                              ident=2)],
                      tune=tune, world=world, label="own report: " + label)

    def test_logs_of_every_kind(self):
        cases = [
            ("no log", None),
            ("the engine lines", log_file(*ENGINE_LINES)),
            ("an alpha and a sub-alpha", log_file(
                "[2026-09-01 10:00:00] engine codex-cli 0.130.0-alpha.2 passes its local checks (`codex queue` still "
                "offers --thread/--message).",
                "[2026-09-02 10:00:00] engine codex-cli 0.130.0-alpha.2.1 passes its local checks.",
                "[2026-09-03 10:00:00] engine codex-cli 00.130.0 passes its local checks.",
                "[2026-09-04 10:00:00] engine codex-cli 0.130.0-alpha.0 accepted because `codex queue` still offers")),
            ("dates that are not dates", log_file(
                "[2026-02-30 10:00:00] engine codex-cli 0.1.0 passes its local checks.",
                "[2026-13-01 10:00:00] engine codex-cli 0.2.0 passes",
                "[0000-01-01 10:00:00] engine codex-cli 0.3.0 passes",
                "[2026-01-01 24:00:00] engine codex-cli 0.4.0 passes",
                "[2026-01-01 23:59:61] engine codex-cli 0.5.0 passes its local checks (`codex queue` still offers "
                "--thread/--message).",
                "[2024-02-29 00:00:00] engine codex-cli 0.6.0;",
                "[２０２６-01-01 10:00:00] engine codex-cli ٠.7.0 passes")),
            ("lines it never writes", log_file("engine codex-cli 0.1.0 passes", "[2026-09-01 10:00:00]engine x",
                                               "[2026-09-01 10:00:00] engine codex-cli 0.9.0x passes",
                                               "[2026-09-01 10:00:00] xengine codex-cli 0.9.1)")),
            ("not UTF-8 and line breaks of every kind", log_file(
                raw=b"[2026-09-01 10:00:00] engine codex-cli 0.120.0 is verified\xff\r\n"
                    b"[2026-09-02 10:00:00] engine codex-cli 0.121.0 passes\r"
                    b"[2026-09-03 10:00:00] engine codex-cli 0.122.0 passes\x0b"
                    b"[2026-09-04 10:00:00] engine codex-cli 0.123.0 passes\xe2\x80\xa8")),
            ("rotated copies", chained(log_file(ENGINE_LINES[0], name="auto-resume.log.5"),
                                       log_file(ENGINE_LINES[1], name="auto-resume.log.2"),
                                       log_file(ENGINE_LINES[2]))),
            ("a log far too large", log_file(raw=b"x" * (8 * 1024 * 1024 + 1))),
        ]
        for label, tune in cases:
            with self.subTest(label):
                self.report(tune, label)

    def test_states_of_every_kind(self):
        logged = log_file(*ENGINE_LINES)
        cases = [
            ("no state", chained(logged, lambda ws: (ws / "home" / "config" / "state.sqlite").unlink()), "acts"),
            ("garbage", chained(logged, write_file("home/config/state.sqlite", b"x" * 4096)), "acts"),
            ("a newer schema", chained(logged, state_sql("PRAGMA user_version=6")), "acts"),
            ("an older schema", chained(logged, state_sql("PRAGMA user_version=2")), "acts"),
            ("schema 3", chained(logged, state_sql("PRAGMA user_version=3")), "acts"),
            ("a column gone", chained(logged, state_sql("ALTER TABLE interruptions DROP COLUMN limit_type")), "acts"),
            ("paused", chained(logged, state_sql("UPDATE settings SET enabled=0")), "acts"),
            ("records of odd values", chained(logged, state_sql(
                "UPDATE interruptions SET gate_eval='[1,2]' WHERE rowid=1",
                "UPDATE interruptions SET gate_eval='{\"engine_compatible\": [\"PASS\", \"ok\"], \"usage\": "
                "[\"PASS\", \"plugged\"]}' WHERE rowid=2",
                "UPDATE interruptions SET category='made_up', state=5, last_error=x'00ff' WHERE rowid=3",
                "UPDATE interruptions SET resumed_at=detected_at+60, outcome_at=detected_at+120, state='recovered' "
                "WHERE rowid=4",
                "UPDATE interruptions SET detected_at=1e20 WHERE rowid=5")), "acts"),
            ("hidden records", chained(logged, state_sql("UPDATE interruptions SET history_hidden_at=1 WHERE "
                                                         "rowid % 2 = 0")), "acts"),
            ("an empty home", logged, "empty"),
        ]
        for label, tune, kind in cases:
            with self.subTest(label):
                self.report(tune, label, kind=kind)

    def test_the_watchers_report(self):
        logged = log_file(*ENGINE_LINES)
        views = [None, {"status": "ok", "engine": {"version": "codex-cli 0.130.0"}},
                 {"status": "ok", "engine": {"version": "  0.125.0 "}, "capabilities": [1]},
                 {"status": "stale", "engine": {"version": "0.130.0"}},
                 {"status": "ok", "engine": {"version": ""}}, {"status": "ok", "engine": 5},
                 {"status": "ok", "engine": {"version": "9.9.9"},
                  "capabilities": {"engine_present": {"reason": "local_checks_passed"},
                                   "usage_reset_hint": {"reason": "registry_verified"},
                                   "goal_continuation": {"reason": "local_checks_passed"}}}]
        for view in views:
            with self.subTest(view=view):
                self.report(logged, "view %r" % (view,), world={"compat_view": view})
        for version in ("0.6.26", "unknown", "0.6.27-alpha", "weird"):
            with self.subTest(version=version):
                self.report(logged, "version %s" % version, world={"version": version, "windows_version": None})

    def test_many_records(self):
        def many(count):
            def tune(ws):
                connection = sqlite3.connect(ws / "home" / "config" / "state.sqlite")
                try:
                    columns = [row[1] for row in connection.execute("PRAGMA table_info(interruptions)")]
                    base = connection.execute("SELECT * FROM interruptions LIMIT 1").fetchone()
                    # Exactly `count` records, so the report's bound (500 on one version) is met and passed by one.
                    connection.execute("DELETE FROM interruptions")
                    rows = []
                    for index in range(count):
                        row = dict(zip(columns, base))
                        row.update(interruption_id="%064x" % (10 ** 6 + index), detected_at=1790000000.0 - index,
                                   chain_origin_id="%064x" % (10 ** 6 + index), recovery_turn_id=None,
                                   recovery_client_id=None, queue_id=None)
                        rows.append(row)
                    connection.executemany("INSERT INTO interruptions (%s) VALUES (%s)" % (
                        ", ".join(columns), ", ".join("?" * len(columns))),
                        [tuple(row[c] for c in columns) for row in rows])
                    connection.commit()
                finally:
                    connection.close()
            return tune
        logged = log_file("[2026-01-01 00:00:00] engine codex-cli 0.130.0 passes its local checks (`codex queue` "
                          "still offers --thread/--message).")
        for count in (500, 501):
            with self.subTest(count=count):
                self.report(chained(logged, many(count)), "%d records on one version" % count)


# ------------------------------------------------------------------------------ the diagnostics bundle
class DiagnosticsDiff(ActingBase):
    def test_bundles(self):
        logged = chained(
            log_file(*ENGINE_LINES, "[2026-09-21 10:00:00] thread %s at C:\\Users\\ExampleUser\\x for ExampleUser "
                     "mail someone@example.com record %s" % (T1, RESET)),
            log_file("Traceback: \\\\server\\share\\file 0123456789abcdef0123 EXAMPLEUSER", name="errors.log"),
            log_file("pid 1; job unknown; off", name="codex-start.log"))
        cases = [("golden", None, {}), ("with logs", logged, {}),
                 ("a short user name", logged, {"environ": {"USERNAME": "ab"}}),
                 ("a plug-free bundle under an administrator", None, {"managed": {"max_recovery_attempts": 2}}),
                 ("the check and the registry raise", None, {"checkup_bundle": {"raise": "KeyError"}}),
                 ("garbage state", write_file("home/config/state.sqlite", b"x" * 100), {}),
                 ("the Run key and the protocol", None, {"startup_value": "pythonw.exe C:\\else\\a.py run",
                                                         "protocol_value": "x", "notification_owner": True})]
        for label, tune, world in cases:
            with self.subTest(label):
                def build(ws):
                    return [request("diagnostics", {"path": str(ws / "out" / "bundle.json")}, ident=1),
                            request("diagnostics", {"path": str(ws / "out" / "bundle.json")}, ident=2),
                            request("diagnostics", {"path": str(ws / "out" / "B.JSON")}, ident=3),
                            request("diagnostics", {"path": str(ws / "out//x/./y.json")}, ident=4),
                            request("diagnostics", {"path": str(ws / "home" / "logs" / "auto-resume.log" / "z.json")},
                                    ident=5),
                            request("diagnostics", {"path": 5}, ident=6), request("diagnostics", {}, ident=7),
                            request("diagnostics", {"path": "x.jsonx"}, ident=8)]
                self.run_both("acts", requests=build, world=world, tune=tune, label="bundle: " + label)
        for kind in ("empty", "fresh"):
            with self.subTest(kind):
                self.run_both(kind, requests=lambda ws: [request("diagnostics", {"path": str(ws / "b.json")})],
                              label="bundle: a %s home" % kind)


# ------------------------------------------------------------------------------ what no bridge command reaches
JOBS = [{"in_job": True, "kill_on_close": True, "breakaway_ok": False, "silent_breakaway_ok": False, "packaged": False},
        {"in_job": True, "kill_on_close": True, "breakaway_ok": True, "silent_breakaway_ok": False, "packaged": True},
        {"in_job": True, "kill_on_close": None, "breakaway_ok": None, "silent_breakaway_ok": None, "packaged": None},
        {"in_job": False, "kill_on_close": False, "breakaway_ok": False, "silent_breakaway_ok": False,
         "packaged": False},
        {"in_job": None}, {}]


class ControlCallDiff(ActingBase):
    def call(self, method, args=(), *, world=None, tune=None, label=""):
        return self.run_both("acts", method=method, args=args, world=world, tune=tune,
                             label=label or "%s%r" % (method, tuple(args)))

    def test_start_for_codex(self):
        launcher = write_file("home/watcher-launcher.py", "")
        on = state_sql("SELECT 1")

        def setting(value):
            def tune(ws):
                path = ws / "home" / "config" / "settings.json"
                data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                data["start_with_codex"] = value
                path.write_text(json.dumps(data), encoding="utf-8")
            return tune
        for context in JOBS:
            for setting_on in (True, False):
                for alive in ([], [4242]):
                    world = {"process_context": context, "watcher_running": False, "alive": alive,
                             "launch": {"pid": 4242, "polls": [None]}}
                    with self.subTest(context=context, setting=setting_on, alive=alive):
                        self.call("start_for_codex", [8], world=world,
                                  tune=chained(launcher, setting(setting_on), on))
        others = [("paused", {}, state_sql("UPDATE settings SET enabled=0")),
                  ("running", {"watcher_running": True}, None),
                  ("cannot be asked", {"watcher_running": None}, None),
                  ("installing", {"install_in_progress": True}, None),
                  ("not installed", {}, lambda ws: (ws / "home" / "watcher-launcher.py").unlink()),
                  ("context raises", {"process_context": {"raise": "OSError"}}, None),
                  ("launch refused", {"launch": {"raise": ["PermissionError", "[WinError 5] no"]},
                                      "process_context": JOBS[1]}, None),
                  ("no turn at the log", {"note_turn": False}, None)]
        for label, world, tune in others:
            with self.subTest(label):
                made = dict({"process_context": JOBS[3], "watcher_running": False}, **world)
                self.call("start_for_codex", [0], world=made, tune=chained(launcher, setting(True), tune),
                          label="start for Codex: " + label)
        # Integration 12: a plug's start route is told what core made of it (`_tell`): the first word at the note, and
        # "ended" when the watcher it started is gone; a route the plug named before a refusal is told the refusal.
        routes = [("started, then gone", {"route": {"pid": 4242}}, {"process_context": JOBS[0], "alive": []}, None, 8),
                  ("started, still there", {"route": {"pid": 4242}}, {"process_context": JOBS[0], "alive": [4242]},
                   None, 8),
                  ("refused", {"route": {"code": 5}}, {"process_context": JOBS[0]}, None, 0),
                  ("uncertain", {"route": {"uncertain": "timeout"}}, {"process_context": JOBS[0]}, None, 0),
                  ("no pid", {"route": {}}, {"process_context": JOBS[0]}, None, 0),
                  ("an answer that is no dict", {"route": [1]}, {"process_context": JOBS[0]}, None, 0),
                  ("paused after it was named", {"route": {"pid": 4242}}, {"process_context": JOBS[0]},
                   state_sql("UPDATE settings SET enabled=0"), 0),
                  ("running", {"route": {"pid": 4242}}, {"process_context": JOBS[0], "watcher_running": True}, None, 0),
                  ("cannot be asked", {"route": {"pid": 4242}}, {"process_context": JOBS[0], "watcher_running": None},
                   None, 0),
                  ("installing", {"route": {"pid": 4242}}, {"process_context": JOBS[0], "install_in_progress": True},
                   None, 0),
                  ("not installed", {"route": {"pid": 4242}}, {"process_context": JOBS[0]},
                   lambda ws: (ws / "home" / "watcher-launcher.py").unlink(), 0),
                  ("not in a job: core starts it", {"route": {"pid": 4242}},
                   {"process_context": JOBS[3], "alive": []}, None, 8),
                  ("a route with no told", {"route": {"pid": 4242}, "told": False},
                   {"process_context": JOBS[0], "alive": []}, None, 8),
                  ("a told that raises", {"route": {"pid": 4242}, "told_raises": True},
                   {"process_context": JOBS[0], "alive": []}, None, 8),
                  ("no route, held", {"held": "armed_later"}, {"process_context": JOBS[0]}, None, 0),
                  ("no route, a held that is no word", {"held": "Not A Word"}, {"process_context": JOBS[0]}, None, 0),
                  ("the context raises", {"route": {"pid": 4242}}, {"process_context": {"raise": "OSError"}}, None, 0)]
        for label, plug, world, tune, seconds in routes:
            with self.subTest(route=label):
                made = dict({"watcher_running": False, "launch": {"pid": 4242, "polls": [None]}, "start_plug": plug},
                            **world)
                self.call("start_for_codex", [seconds], world=made, tune=chained(launcher, setting(False), on, tune),
                          label="start for Codex through a plug's route: " + label)
        full = write_file("home/logs/codex-start.log", "".join("[2026-01-01 00:00:%02d] old %d\n" % (i, i)
                                                                for i in range(60)))
        self.call("start_for_codex", [0], world={"process_context": JOBS[3]}, tune=chained(launcher, full),
                  label="start for Codex: the log cut to 50")
        for context in JOBS:
            with self.subTest(job=context):
                self.call("launch_ends_with_job", [], world={"process_context": context})

    def test_power_writers(self):
        nonce = "0123456789abcdef"
        calls = [("stop_power_countdown", [nonce, "toast"]), ("stop_power_countdown", [nonce, "card"]),
                 ("stop_power_countdown", ["ffffffffffffffff", "toast"]), ("stop_power_countdown", [nonce, "mcp"]),
                 ("stop_power_countdown", [5, "toast"]), ("power_batch_end", [nonce, "done", None]),
                 ("power_batch_end", [nonce, "skipped", now()]), ("power_batch_end", [nonce, "nope", None]),
                 ("power_batch_finish", [nonce, None]), ("power_batch_finish", ["x", None]),
                 ("power_refused", [None]), ("power_show", [nonce, {"phase": "grace", "waiting_for": None,
                                                                   "grace_until": now() + 5}, None]),
                 ("power_show", [nonce, {"phase": "grace"}, None]), ("disarm_power_action", ["tray"]),
                 ("disarm_power_action", ["model"]), ("arm_power_action", [SLEEP_ONCE, "mcp", False]),
                 ("arm_power_action", [SLEEP_ONCE, "dashboard", True])]
        files = [("armed always", armed()), ("armed once", armed(armed={"repeat": "once"})),
                 ("stopped", armed(armed={"stop_at": now() - 5})),
                 ("done last", armed(last={"action": "sleep", "result": "done", "at": now() - 5})),
                 ("shown already", armed(shown={"phase": "grace", "waiting_for": None, "grace_until": now() + 5,
                                                "nonce": nonce}))]
        for label, document in files:
            for method, args in calls:
                with self.subTest(file=label, method=method, args=args):
                    self.call(method, args, tune=power_file(document), label="%s on %s %r" % (method, label, args))

    def test_other_actors(self):
        for actor in ("gui", "mcp", "tray"):
            with self.subTest(actor=actor):
                self.call("request_retry_now", [RESET, actor], world={"signals": {"wake": True}})
                self.call("rescan", [actor, True], world={"judge": {"*": ["rechecked", None]}})
                self.call("cancel_interruption", [BACKOFF, actor])
                self.call("cancel_all_pending", [actor])
                self.call("clear_history", [actor])
        self.call("own_report", [], tune=log_file(*ENGINE_LINES))


class PowerGuardDiff(ActingBase):
    def test_the_harness_runs_with_the_power_guard(self):
        # run_both asserts the harness saw CAR_NO_POWER_ACTION on every stream; here the guard is asked alone.
        _, _, _, guard = aw.ask_rust(self.harness, self.workspace("acts") / "home",
                                     aw.world_for(self.workspace("acts")), stdin=lines(request("power-action")))
        self.assertTrue(guard)
        RECORD.append("bridge acting: %(streams)d streams, %(requests)d requests and %(calls)d Host calls equal" % COUNTS)

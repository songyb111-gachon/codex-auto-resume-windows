"""The acting half of the bridge's diffs' world (seat S5.1b, car-control): the stand-ins the tag's modules are
patched to for every call car-control makes through its Host seam beyond the quiet commands' - signals, the Run key,
the launch and its poll, the clock's waits, the power port, the network, the tokens, the process context, the
registry's live check, import and refresh, the watcher's check and its Rescan judge - and the record of those calls,
in order, with their arguments, which car-harness's `acting.rs` writes the same way.

Nothing the reference does here starts a process, signals an event, writes the registry, reads the network or acts
on the power: `subprocess.Popen` is a stand-in whose `poll` answers the world's list, the Run key is a value in
memory, `time.sleep` only moves a stand-in clock, and the power port's `act` raises.

`HOOK` runs inside bridgeworld.SCRIPT after the world is in (its `hooks`); with `mode` "call" it also runs one
Control method and writes its answer (control.call's counterpart).
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from rustdiff import bridgeworld as bw
from rustdiff import core, reference

HOOK = r'''
import atexit, builtins, calendar, hashlib, json as _json, secrets as _secrets, subprocess as _subprocess, types
import time as _time
from pathlib import Path as _Path

CALLS = []
def _log(*entry):
    CALLS.append(list(entry))
atexit.register(lambda: _Path(spec["calls_path"]).write_text(_json.dumps(CALLS), encoding="utf-8"))

def _exception(said):
    name, message = (said[0], said[1] if len(said) > 1 else "") if isinstance(said, list) else (said, "")
    kind = getattr(builtins, name, None)
    if not (isinstance(kind, type) and issubclass(kind, BaseException)):
        if name == "StartupError":
            kind = startup.StartupError
        else:
            kind = type(name, (Exception,), {})
    return kind(message) if message else kind()

def _answer(name):
    found = world.get(name)
    if isinstance(found, dict) and "raise" in found:
        raise _exception(found["raise"])
    if isinstance(found, dict) and "value" in found:
        return found["value"]
    return found

# The entry script is the code's own (config.PROJECT_ROOT); car-harness builds its Paths with the home as the project
# root, so the reference's is put where car-harness's is.
_paths_init = config.Paths.__init__
def _paths(self, *args, **kwargs):
    _paths_init(self, *args, **kwargs)
    self.entry_script = _Path(spec["home"]) / "src" / "auto_resume.py"
config.Paths.__init__ = _paths

# The clock's waits: a stand-in monotonic clock that only a sleep moves; and the local zone the world's (UTC).
_clock = [1000.0]
_time.monotonic = lambda: _clock[0]
def _sleep(seconds):
    _log("sleep", float(seconds))
    _clock[0] += seconds
_time.sleep = _sleep
_real_mktime = _time.mktime
_time.mktime = lambda t: float(calendar.timegm(tuple(t)))
# quiet.py and its kin took time.mktime as a default argument when they were imported: give them the world's too.
for _module in list(sys.modules.values()):
    if not getattr(_module, "__name__", "").startswith("codex_auto_resume"):
        continue
    for _function in list(vars(_module).values()):
        _defaults = getattr(_function, "__kwdefaults__", None)
        if isinstance(_defaults, dict):
            for _name, _value in list(_defaults.items()):
                if _value is _real_mktime:
                    _defaults[_name] = _time.mktime
_real_strftime = _time.strftime
_time.strftime = lambda fmt, t=None: _real_strftime(fmt, _time.gmtime(world["now"]) if t is None else t)

# The watcher's mutex: the world's probes in turn, then watcher_running.
_probes = list(world.get("probes") or [])
def _running(self):
    _log("watcher_running")
    if _probes:
        return _probes.pop(0)
    return world["watcher_running"]
control_watcher.WatcherMixin.watcher_running = _running

# The three named events.
def _event(word):
    class Event:
        def __init__(self, _state_dir):
            pass
        def signal(self):
            _log("signal", word)
            found = (world.get("signals") or {}).get(word, False)
            if isinstance(found, bool):
                return found
            raise _exception((found or {}).get("raise", "AdapterError") if isinstance(found, dict) else "AdapterError")
    return Event
from codex_auto_resume.control import actions as _actions, codexstart as _codexstart, poweraction as _pa
from codex_auto_resume.control import tools as _tools
_actions.WakeEvent = _event("wake")
controlcli.WakeEvent = _event("wake")
control_watcher.StopEvent = _event("stop")
_tools.DemoEvent = _event("demo")

# The Run key, in memory.
_run = [world.get("startup_value")]
_raise = world.get("startup_raise") or {}
def _read():
    _log("startup_read")
    if "read" in _raise:
        raise startup.StartupError(_raise["read"])
    return _run[0]
def _install(command):
    _log("startup_install", command)
    if "install" in _raise:
        raise startup.StartupError(_raise["install"])
    changed = _run[0] != command
    _run[0] = command
    return changed
def _uninstall():
    _log("startup_uninstall")
    if "uninstall" in _raise:
        raise startup.StartupError(_raise["uninstall"])
    had = _run[0] is not None
    _run[0] = None
    return had
startup.current_value = _read
startup.install = _install
startup.uninstall = _uninstall
def _protocol():
    _log("protocol_value")
    return _answer("protocol_value")
startup.protocol_value = _protocol
def _owner(home):
    _log("notification_identity_owner", str(home))
    return _answer("notification_owner")
startup.notification_identity_owner = _owner
def _launcher():
    _log("python_launcher")
    found = world.get("launcher")
    if isinstance(found, str):
        return _Path(found)
    said = found.get("raise") if isinstance(found, dict) else None
    raise startup.StartupError(said[1] if isinstance(said, list) else "no pythonw.exe beside python.exe")
startup.python_launcher = _launcher

# The one launch, answered by a stand-in that starts nothing.
class _Popen:
    def __init__(self, args, cwd=None, creationflags=0, **_kwargs):
        _log("launch", [str(each) for each in args], str(cwd), int(creationflags))
        launch = world.get("launch") or {}
        if "raise" in launch:
            raise _exception(launch["raise"])
        self.pid = launch.get("pid", 4242)
        self._polls = list(launch.get("polls") or [])
    def poll(self):
        _log("poll")
        if len(self._polls) > 1:
            return self._polls.pop(0)
        return self._polls[0] if self._polls else None
_subprocess.Popen = _Popen

# The power port: whether each action is offered, and never an action.
class _Port:
    def available(self, action):
        _log("power_available", action)
        power = world.get("power")
        if isinstance(power, dict) and "raise" in power:
            raise _exception(power["raise"])
        reason = power.get(action) if isinstance(power, dict) else None
        if reason is None:
            return True, None
        if isinstance(reason, str):
            return False, reason
        raise _exception(reason.get("raise", "OSError") if isinstance(reason, dict) else "OSError")
    def act(self, action):
        raise SystemExit("a diff never puts its machine to sleep")
_pa.PowerActionMixin.power_port = _Port()

from codex_auto_resume.win import network as _network
def _internet():
    _log("internet")
    return _answer("internet")
_network.internet = _internet

# Tokens: SHA-256 of "token-<n>-<round>", the n-th asked, cut to length.
_tokens = [0]
def _token(count):
    _tokens[0] += 1
    out, round_ = b"", 0
    while len(out) < count:
        out += hashlib.sha256(("token-%d-%d" % (_tokens[0], round_)).encode()).digest()
        round_ += 1
    return out[:count]
def _token_hex(count=32):
    _log("token_hex", count)
    return _token(count).hex()
def _token_bytes(count=32):
    _log("token_bytes", count)
    return _token(count)
_secrets.token_hex = _token_hex
_secrets.token_bytes = _token_bytes

# The process this is, for the start with Codex.
def _context():
    _log("process_context")
    return dict(_answer("process_context"))
windows.process_context = _context
def _identity(pid):
    _log("process_there", pid)
    if pid in (world.get("alive") or []):
        return {"pid": pid}
    raise windows.AdapterError("process_gone")
windows.process_identity = _identity
_codexstart.os = types.SimpleNamespace(getpid=lambda: world.get("pid", 7777))
def _turn(stream):
    _log("note_turn")
    return world.get("note_turn", True) is not False
_codexstart._note_turn = _turn

# What Windows reports of itself, for the own report and the bundle.
from codex_auto_resume import diagnostics as _diagnostics
from codex_auto_resume.ownreport import document as _document
def _windows_version():
    _log("windows_version")
    return world.get("windows_version")
_document.windows_version = _windows_version
def _system():
    _log("system")
    return world.get("system")
_diagnostics._system = _system

# The registry (S3.3's), the watcher's check and its Rescan judge (car-watcher's).
def _reader(paths, settings=None, now=None):
    _log("compat_view", (settings or {}).get("codex_exe"))
    return world["compat_view"]
compatio.reader_view = _reader
def _live(paths, codex_home, explicit=None):
    _log("compat_live_view", str(codex_home), explicit)
    return _answer("compat_live")
compatio.live_view = _live
def _import(paths, target, origin="file"):
    _log("compat_import", target, origin)
    return _answer("compat_import")
compatio.import_document = _import
def _refresh(home, **_kwargs):
    _log("compat_refresh", str(home))
    return _answer("compat_refresh")
compatio.run_refresh = _refresh
from codex_auto_resume import checkup as _checkup, rescan as _rescan
def _check(control, *_args, **_kwargs):
    _log("checkup")
    return _answer("checkup")
_checkup.run = _check
def _for_bundle(control):
    def check(redact):
        _log("checkup_for_bundle", redact._key.hex())
        return _answer("checkup_bundle")
    return check
_checkup.for_bundle = _for_bundle
def _judge_for(control, *_args, **_kwargs):
    _log("rescan_judge_for")
    refused = world.get("judge_for")
    if isinstance(refused, dict) and "raise" in refused:
        raise _exception(refused["raise"])
    table = world.get("judge") or {}
    def judged(row, kin):
        key = row.get("interruption_id") or ""
        _log("judge", key)
        found = table.get(key, table.get("*"))
        if isinstance(found, dict) and "raise" in found:
            raise _exception(found["raise"])
        if isinstance(found, list) and len(found) == 2:
            return found[0], found[1]
        return "unresolved", "no_proof"
    return judged
_rescan.judge_for = _judge_for

if world.get("status_plug") is not None:
    # test_status_newest_usage's MeterPlug: an advanced edition's plug whose STATUS surface adds the world's value.
    from codex_auto_resume import edition as _edition
    from codex_auto_resume.domain.plug import Edition as _Edition, Plug as _Plug, Surface as _Surface

    class _StatusPlug(_Plug):
        __slots__ = ()
        edition = _Edition.ADVANCED
        badge = "Advanced"

        def surface(self, name, facts):
            return world["status_plug"] if name == _Surface.STATUS else {}
    _edition.plug = lambda paths: _StatusPlug()

if mode == "call":
    from codex_auto_resume import ownreport as _ownreport
    _layer = control.Control(Path(home))
    _methods = {
        "start_for_codex": lambda c, seconds=0: c.start_for_codex(seconds),
        "launch_ends_with_job": lambda c: c.launch_ends_with_job(),
        "stop_power_countdown": lambda c, nonce, actor: c.stop_power_countdown(nonce, actor),
        "power_batch_end": lambda c, nonce, result, now=None: c.power_batch_end(nonce, result, now),
        "power_batch_finish": lambda c, nonce, now=None: c.power_batch_finish(nonce, now),
        "power_refused": lambda c, now=None: c.power_refused(now),
        "power_show": lambda c, nonce, shown, now=None: c.power_show(nonce, shown, now),
        "disarm_power_action": lambda c, actor: c.disarm_power_action(actor),
        "arm_power_action": lambda c, choice, actor, tasks=False: c.arm_power_action(choice, actor, tasks),
        "request_retry_now": lambda c, key, actor: c.request_retry_now(key, actor=actor),
        "rescan": lambda c, actor, read_usage=False: c.rescan_pending(_rescan.judge_for(c), actor=actor,
                                                                     read_usage=read_usage),
        "cancel_interruption": lambda c, key, actor: c.cancel_interruption(key, actor=actor),
        "cancel_all_pending": lambda c, actor: c.cancel_all_pending(actor=actor),
        "clear_history": lambda c, actor: c.clear_history(actor=actor),
        "own_report": lambda c: _ownreport.write(c.paths),
        # The final-port seat (FINAL-DELTA #15): the status a plug's meter adds to (STATUS_PLUG below).
        "get_status": lambda c: c.get_status(),
    }
    try:
        _result = {"value": _methods[spec["method"]](_layer, *spec["args"])}
    except control.ControlError as exc:
        _result = {"refusal": [str(exc), exc.code]}
    except Exception as exc:
        _result = {"raised": type(exc).__name__}
    _Path(spec["result_path"]).write_text(_json.dumps(_result), encoding="utf-8")
    sys.exit(0)
'''

# What the acting calls answer unless a case says otherwise (laid over bridgeworld.DEFAULT_WORLD).
ACTING_WORLD = {
    "environ": {"USERNAME": "ExampleUser"},
    "probes": [],
    "signals": {"wake": False, "stop": False, "demo": False},
    "launcher": "C:\\Program Files\\Example\\pythonw.exe",
    "launch": {"pid": 4242, "polls": [None]},
    "power": {},
    "internet": True,
    "process_context": {"in_job": False, "kill_on_close": False, "breakaway_ok": False,
                        "silent_breakaway_ok": False, "packaged": False},
    "pid": 7777,
    "alive": [],
    "windows_version": "10.0.26100",
    "system": {"windows": "10.0.26100", "python": "3.14.10", "machine": "AMD64"},
    "compat_live": {"value": {"status": "ok", "live": True}},
    "compat_import": {"value": {"imported": False, "reason": "invalid", "sequence": None, "cache": "absent"}},
    "compat_refresh": {"value": {"outcome": "refreshed", "code": 0}},
    "checkup": {"value": {"summary": "ok", "lines": ["ok"]}},
    "checkup_bundle": {"value": {"summary": "ok"}},
    "judge": {},
    "protocol_value": None,
    "notification_owner": None,
}


def world_for(workspace: Path, **changes) -> dict:
    """bridgeworld's world with the acting calls' answers, `changes` laid over both."""
    made = bw.world_for(workspace)
    for key, value in json.loads(json.dumps(ACTING_WORLD)).items():
        made[key] = value
    environ = dict(made.get("environ") or {})
    environ.update(changes.pop("environ", {}) or {})
    made["environ"] = environ
    made.update(changes)
    return made


def ask_reference(home: Path, world: dict, *, mode="serve", stdin: bytes = b"", argv=(), method=None, args=()):
    """The tag's bridge (or one Control method, mode "call") on `home`: (code, stdout, stderr, calls, result)."""
    folder = Path(tempfile.mkdtemp(prefix="car-v0627-bridge6-spec-"))
    try:
        spec = {"world": world, "mode": mode, "home": str(home), "argv": list(argv), "hooks": [HOOK],
                "calls_path": str(folder / "calls.json"), "result_path": str(folder / "result.json"),
                "method": method, "args": list(args)}
        (folder / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        done = reference.run(bw.SCRIPT, folder / "spec.json", profile=home.parent / "profile", stdin=stdin)
        calls = (json.loads((folder / "calls.json").read_text(encoding="utf-8"))
                 if (folder / "calls.json").is_file() else None)
        result = (json.loads((folder / "result.json").read_text(encoding="utf-8"))
                  if (folder / "result.json").is_file() else None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return done.returncode, done.stdout, done.stderr, calls, result


def ask_rust(harness: core.Harness, home: Path, world: dict, *, mode="serve", stdin: bytes = b"", argv=()):
    """car-control's bridge on `home`: (code, output, calls, power_guard)."""
    _, line = harness.call("bridge.run", home=str(home), world=world, mode=mode, input=stdin.hex(), argv=list(argv))
    reply = json.loads(line.decode("utf-8"))["reply"]
    if not reply.get("ok"):
        raise AssertionError("car-harness refused bridge.run: %r" % (reply,))
    value = reply["value"]
    return value["code"], value["output"].encode("utf-8"), value["calls"], value["power_guard"]


def call_rust(harness: core.Harness, home: Path, world: dict, method: str, args=()):
    """One Control method through car-harness's control.call: (result, calls)."""
    _, line = harness.call("control.call", home=str(home), world=world, method=method, args=list(args))
    reply = json.loads(line.decode("utf-8"))["reply"]
    if not reply.get("ok"):
        raise AssertionError("car-harness refused control.call: %r" % (reply,))
    return reply["value"]["result"], reply["value"]["calls"]


def state_dump(home: Path) -> dict:
    """Every table of the home's state, every row in rowid order: what the commands wrote to the store."""
    found = {}
    for path in sorted(home.rglob("state.sqlite")):
        if not path.is_file():
            continue
        try:
            found[path.relative_to(home).as_posix()] = _dump(path)
        except sqlite3.Error:
            # Not a database the commands could have written: its bytes, as they are.
            found[path.relative_to(home).as_posix()] = {"bytes": path.read_bytes().hex()}
    return found


def _dump(path: Path) -> dict:
    connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        dump = {"user_version": connection.execute("PRAGMA user_version").fetchone()[0]}
        for table in tables:
            try:
                dump[table] = [list(row) for row in connection.execute(
                    "SELECT * FROM \"%s\" ORDER BY rowid" % table)]
            except sqlite3.Error:
                dump[table] = [list(row) for row in connection.execute("SELECT * FROM \"%s\"" % table)]
        return dump
    finally:
        connection.close()

"""What the S7.2b diffs (diffs_advaccount_*.py) share: the saved accounts' acts - `codex/authfile`, `codex/account`,
`codex/restart`, `codex/swap`, `win/appclose`, `engine/account`, `engine/autoswitch` - run by the v0.6.26 final's own
advanced edition and by car-adv's `advaccount` probe on the same inputs, held equal.

A request is `{"world": {...}, "cases": [[op, arg, ...], ...]}`; both sides answer `{"results": [{"ok": value, "log":
[...]} | {"error": class, "log": [...]}]}` - `log` is every call a stand-in was asked, in order. The reference is this
module's `REFERENCE`, started on the reference Python (`refpython`: the bundled 3.14.10 unless told otherwise) with the
tag's `src` and `advanced/src` first on its path and every home a scratch folder (`advref.environment`); the probe is
car-adv's example `advaccount`, started with the same environment, in a scratch folder of its own.

Nothing real is asked of anyone: the sign-in files are synthetic ones the test writes in a scratch folder; the seal is
S7.1a's stand-in (`SEALED:` and the bytes), never DPAPI; the saved accounts' lock, Credential Manager, the private
access list, the process list, the Restart Manager, TerminateProcess, Codex's sessions, the runner of `codex
login`/`logout`, the restart's hands and the clocks are scripted stand-ins on both sides that log what they are asked.
`secrets.token_hex` is one counter both sides use. Each side runs on its own copy of the folders the test made
(`setup(root)`), and what is left there afterwards is compared as bytes.

Not a test module (no `test` in its name, and not `diffs_*`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from rustdiff import advdiff, advref, diffs, refpython

TAG = os.environ.get("CODEX_AR_REFERENCE") or "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXAMPLE = "advaccount"
PUBLISHER = "2p2nqsd0c76g0"
NATIVE = r"C:\Program Files"
APP = NATIVE + r"\WindowsApps\OpenAI.Codex_26.1.0_x64__" + PUBLISHER + r"\app\ChatGPT.exe"
ENGINE = NATIVE + r"\WindowsApps\OpenAI.Codex_26.1.0_x64__" + PUBLISHER + r"\app\resources\codex.exe"
TUI = r"C:\Tools\codex\codex.exe"

REFERENCE = r'''
import base64, contextlib, ctypes, json, os, secrets, sys, time, types
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
WORLD = dict(request.get("world") or {})
ROOT = Path.cwd()
COUNTER = [int(WORLD.get("tokens", 0))]


def token_hex(nbytes=32):
    COUNTER[0] += 1
    return format(COUNTER[0], "0%dx" % (2 * nbytes))


secrets.token_hex = token_hex
from codex_auto_resume import config
from codex_auto_resume.codex import pairing
from codex_auto_resume.domain.errors import AdapterError
from codex_auto_resume_advanced import profiles as profiles_
from codex_auto_resume_advanced.codex import account, authfile, restart, swap
from codex_auto_resume_advanced.win import appclose
from codex_auto_resume_advanced.report.github import GhTimeout
from codex_auto_resume_advanced.codex import inuse as inuse_


def no_real_codex(*unused, **ignored):
    """Nothing in a diff may find, start or ask the Codex installed on this PC: core's discovery, its process list
    and a process's identity all refuse."""
    raise AdapterError("a diff never finds a real Codex")


inuse_.backend = no_real_codex
pairing.processes_named = no_real_codex
pairing.resource_users = no_real_codex
pairing.process_identity = no_real_codex

LOG = []
CLASSES = {"AdapterError": AdapterError, "OSError": OSError, "ValueError": ValueError, "KeyError": KeyError,
           "TypeError": TypeError, "RuntimeError": RuntimeError, "ProfileError": profiles_.ProfileError,
           "AuthFileError": authfile.AuthFileError, "AttributeError": AttributeError}


def unhex(value):
    if isinstance(value, dict) and set(value) == {"hex"}:
        return bytes.fromhex(value["hex"])
    if isinstance(value, list):
        return [unhex(each) for each in value]
    if isinstance(value, dict):
        return {key: unhex(each) for key, each in value.items()}
    return value


def norm(value):
    if isinstance(value, (bytes, bytearray)):
        return {"hex": bytes(value).hex()}
    if isinstance(value, (set, frozenset)):
        return sorted(norm(each) for each in value)
    if isinstance(value, (tuple, list)):
        return [norm(each) for each in value]
    if isinstance(value, dict):
        return {str(key): norm(each) for key, each in value.items()}
    if isinstance(value, Path):
        try:
            return value.relative_to(ROOT).as_posix()
        except ValueError:
            return str(value)
    return value


def raise_for(word):
    name = word.split(":", 1)[1] if ":" in word else "RuntimeError"
    raise CLASSES[name]("stand-in")


class Script:
    """Answers per call kind, taken in order (the last one repeated); "raise" or "raise:Class" raises."""

    def __init__(self, script):
        self.script = {key: list(value) for key, value in (script or {}).items()}

    def take(self, kind, default=None):
        found = self.script.get(kind)
        if not found:
            return default
        value = found.pop(0) if len(found) > 1 else found[0]
        if isinstance(value, str) and value.startswith("raise"):
            raise_for(value)
        return unhex(value)


class Clock:
    def __init__(self, start=0.0):
        self.at = float(start)

    def now(self):
        return self.at

    def sleep(self, seconds):
        LOG.append(["sleep", float(seconds)])
        self.at += float(seconds)


def private(directory):
    LOG.append(["private", norm(Path(directory))])
    return True


authfile._PRIVATE = private
authfile.time = types.SimpleNamespace(time=time.time, sleep=lambda seconds: LOG.append(["pause", float(seconds)]))
CLOCK = float(WORLD.get("clock", 1767225600.0))


class Held:
    def __enter__(self):
        LOG.append(["lock"])
        return self

    def __exit__(self, *unused):
        LOG.append(["unlock"])
        return False


def store_of(spec):
    lock = spec.get("lock") or ["free"]
    locks = list(lock)

    def locker(directory, seconds):
        word = locks.pop(0) if len(locks) > 1 else locks[0]
        LOG.append(["lock?", float(seconds)])
        if word == "held":
            raise TimeoutError("held")
        return Held()

    store = profiles_.Profiles(ROOT / spec["home"], seal=lambda data: b"SEALED:" + data,
                               open_=lambda blob: blob[len(b"SEALED:"):] if blob.startswith(b"SEALED:")
                               else (_ for _ in ()).throw(OSError("not sealed")),
                               clock=lambda: CLOCK, lock=locker)
    if spec.get("raw") is not None:
        store.directory.mkdir(parents=True, exist_ok=True)
        for name, data in unhex(spec["raw"]).items():
            (store.directory / name).write_bytes(data)
    ids = []
    for email, plan, data in spec.get("saved") or ():
        ids.append(store.save(unhex(data), email, plan))
    for field in spec.get("updates") or ():
        store.update(ids[field[0]], **unhex(field[1]))
    if spec.get("intent") is not None:
        args = dict(unhex(spec["intent"]))
        source = ids[args.pop("from")] if isinstance(args.get("from"), int) else args.pop("from", None)
        target = ids[args.pop("to")] if isinstance(args.get("to"), int) else args.pop("to", None)
        store.begin(source, target, **args)
    LOG.clear()
    return store, ids


def target_of(value, ids):
    return ids[value["saved"]] if isinstance(value, dict) and "saved" in value else value


class Session:
    """A session's stand-in: entering it may raise, each call answers from the script by its method, and a call may
    first write a newer sign-in file into the home it runs on (Codex refreshing its tokens there)."""

    def __init__(self, script, home=None):
        self.script, self.home = script, home

    def __enter__(self):
        LOG.append(["enter", norm(self.home) if self.home is not None else None])
        self.script.take("open")
        return self

    def call(self, method, params):
        LOG.append(["call", method, params])
        fresh = self.script.take("refresh:" + method)
        if fresh is not None and self.home is not None:
            (Path(self.home) / "auth.json").write_bytes(fresh)
        return self.script.take(method)

    def __exit__(self, *unused):
        LOG.append(["exit"])
        return False


class Backend:
    def __init__(self, script, home=None):
        self.script, self.home = script, home

    def _argv(self):
        return self.script.take("argv", ["codex.exe"])

    def _environment(self):
        found = self.script.take("env", [["CODEX_HOME", "h"]])
        return {key: value for key, value in found}

    @property
    def codex_home(self):
        return self.home if self.home is not None else self.script.take("home", "h")


def runner_of(script):
    def run(argv, *, env, cwd, stdin, timeout):
        LOG.append(["run", list(argv), sorted([key, value] for key, value in env.items()), norm(Path(cwd)) if
                    Path(cwd).is_absolute() else cwd, stdin, float(timeout)])
        found = script.take("run", [0, "", ""])
        if found == "timeout":
            raise GhTimeout()
        return tuple(found) if isinstance(found, list) else found
    return run


def reads(script, kind="read"):
    def read(*unused):
        LOG.append([kind])
        return script.take(kind, {"present": None, "plan_word": None, "email": None, "kind": None})
    return read


OPS = {}


def op(name):
    def keep(function):
        OPS[name] = function
        return function
    return keep


# ------------------------------------------------------------------------------------------------ account
OPS["ac.plan_word"] = account.plan_word
OPS["ac.parse"] = account.parse
OPS["ac.identity"] = account.identity
OPS["ac.digest"] = account.digest
OPS["ac.mask"] = account.mask


@op("ac.read")
def ac_read(script):
    return account.read(None, session=Session(Script(script)))


@op("ac.switch")
def ac_switch(backend, runner, reader, login_seconds):
    script = Script(reader)
    made = None if backend == "raise" else Backend(Script(backend))
    if made is None:
        account.inuse = None
    return account.switch(None, backend=made, runner=runner_of(Script(runner)), reader=reads(script),
                          login_seconds=login_seconds)


# ------------------------------------------------------------------------------------------------ authfile
OPS["af.check"] = lambda data: authfile.check(unhex(data))
OPS["af.names"] = lambda name: [bool(authfile._SCRATCH.match(name)), bool(authfile._TEMPORARY.match(name)),
                                bool(authfile._BESIDE.match(name))]
OPS["af.store_mode"] = lambda folder: authfile.store_mode(ROOT / folder)
OPS["af.usable"] = lambda folder: authfile.usable(ROOT / folder)
OPS["af.read"] = lambda folder: authfile.read(ROOT / folder)
OPS["af.replace"] = lambda folder, data: authfile.replace(ROOT / folder, unhex(data))
OPS["af.own_folder"] = lambda folder: authfile.own_folder(ROOT / folder)
OPS["af.confined"] = lambda folder: authfile.confined(ROOT / folder)
OPS["af.remove_tree"] = lambda folder: authfile.remove_tree(ROOT / folder)
OPS["af.sweep"] = lambda folder, home, now, stale: authfile.sweep(
    ROOT / folder, None if home is None else ROOT / home, now=now, stale=stale)


@op("af.scratch")
def af_scratch(root, data, action):
    scratch = authfile.Scratch(ROOT / root, unhex(data))
    try:
        with scratch as home:
            LOG.append(["inside", norm(home)])
            if action == "raise":
                raise RuntimeError("stand-in")
            if isinstance(action, dict) and "write" in action:
                (home / "auth.json").write_bytes(unhex(action["write"]))
            if action == "unlink":
                (home / "auth.json").unlink()
    except RuntimeError:
        LOG.append(["raised"])
    return [norm(scratch.path), scratch.after, scratch.removed]


# ------------------------------------------------------------------------------------------------ appclose
class Fn:
    def __init__(self, name, script, act=None):
        self.name, self.script, self.act = name, script, act
        self.argtypes = self.restype = None

    def __call__(self, *arguments):
        found = self.script.take(self.name, 0)
        if self.act is not None:
            return self.act(found, *arguments)
        return found


class Library:
    def __init__(self, script, acts):
        self.script, self.acts = script, acts

    def __getattr__(self, name):
        return Fn(name, self.script, self.acts.get(name))


def rm_library(script):
    def start(found, session, flags, key):
        LOG.append(["RmStartSession", flags])
        code, handle = found if isinstance(found, list) else (found, 1)
        session._obj.value = handle
        return code

    def register(found, session, files, names, count, process, services, more):
        process = process._obj
        LOG.append(["RmRegisterResources", session.value if hasattr(session, "value") else session, count,
                    process.pid, (process.created.dwHighDateTime << 32) | process.created.dwLowDateTime])
        return found

    def shutdown(found, session, flags, callback):
        LOG.append(["RmShutdown", session.value if hasattr(session, "value") else session, flags])
        return found

    def end(found, session):
        LOG.append(["RmEndSession", session.value if hasattr(session, "value") else session])
        return found
    return Library(script, {"RmStartSession": start, "RmRegisterResources": register, "RmShutdown": shutdown,
                            "RmEndSession": end})


def kernel_library(script):
    def open_(found, access, inherit, pid):
        LOG.append(["OpenProcess", access, pid & 0xFFFFFFFF])
        return found or None

    def wait(found, handle, millis):
        LOG.append(["WaitForSingleObject", handle, millis])
        return found

    def times(found, handle, *refs):
        LOG.append(["GetProcessTimes", handle])
        if found is None or found is False or found == 0:
            return 0
        refs[0]._obj.dwLowDateTime = found & 0xFFFFFFFF
        refs[0]._obj.dwHighDateTime = (found >> 32) & 0xFFFFFFFF
        return 1

    def terminate(found, handle, code):
        LOG.append(["TerminateProcess", handle, code])
        return found

    def close(found, handle):
        LOG.append(["CloseHandle", handle])
        return found
    return Library(script, {"OpenProcess": open_, "WaitForSingleObject": wait, "GetProcessTimes": times,
                            "TerminateProcess": terminate, "CloseHandle": close})


@op("ap.ask_close")
def ap_ask_close(pid, created, script):
    real = ctypes.WinDLL
    ctypes.WinDLL = lambda name, use_last_error=False: rm_library(Script(script))
    try:
        return appclose.ask_close(pid, created)
    finally:
        ctypes.WinDLL = real


@op("ap.end_process")
def ap_end_process(pid, created, script):
    real = ctypes.WinDLL
    ctypes.WinDLL = lambda name, use_last_error=False: kernel_library(Script(script))
    try:
        return appclose.end_process(pid, created)
    finally:
        ctypes.WinDLL = real


# ------------------------------------------------------------------------------------------------ restart
class Hands:
    def __init__(self, script):
        self.script, self.clock = Script(script), Clock()

    def inventory(self):
        LOG.append(["inventory"])
        return self.script.take("inventory", [])

    def created(self, pid):
        LOG.append(["created", pid])
        return self.script.take("created")

    def ask_close(self, pid, created):
        LOG.append(["ask_close", pid, created])
        return self.script.take("ask_close", False)

    def end_process(self, pid, created):
        LOG.append(["end_process", pid, created])
        return self.script.take("end_process", False)

    def newest_conversation(self):
        LOG.append(["newest"])
        return self.script.take("newest")

    def open(self, link):
        LOG.append(["open", link])
        return self.script.take("open", True)

    def read(self):
        LOG.append(["read"])
        return self.script.take("read", {"present": True})

    def now(self):
        return self.clock.now()

    def sleep(self, seconds):
        self.clock.sleep(seconds)


def between_of(script):
    if script is None:
        return None
    made = Script(script)

    def between():
        LOG.append(["between"])
        made.take("between")
    return between


@op("rs.restart")
def rs_restart(hands, between):
    return restart.restart(None, hands=Hands(hands), between=between_of(between))


class BusyStore:
    def __init__(self, script):
        self.script = Script(script)

    def pending(self):
        LOG.append(["pending"])
        return self.script.take("pending", [])

    def watcher_status(self):
        LOG.append(["status"])
        return self.script.take("status")


class Source:
    def __init__(self, script):
        self.script = Script(script)

    def activity(self, threads, now, booted=None):
        LOG.append(["activity", list(threads), now, booted])
        return self.script.take("activity")


OPS["rs.busy"] = lambda store, source, now, ok: restart.busy(None, source=Source(source), store=BusyStore(store),
                                                             now=now, usage_waiting_ok=ok)

# ------------------------------------------------------------------------------------------------ swap
OPS["sw.meters"] = swap.meters
OPS["sw.usage_of"] = swap.usage_of
OPS["sw.has_room"] = swap.has_room
OPS["sw.known"] = swap.known


def world_of(world):
    script = Script(world)
    clock = Clock(0.0)

    def inventory():
        LOG.append(["inventory"])
        try:
            found = script.take("inventory", [])
        except Exception:
            return None
        return found

    def running():
        LOG.append(["app_running"])
        return script.take("app_running", False)
    swap._inventory = inventory
    swap._clock = clock.now
    swap._sleep = clock.sleep
    pairing.app_running_now = running
    with pairing._OWN_LOCK:
        pairing._OWN.clear()
        pairing._OWN.update((pid, 1) for pid in script.take("own", []) or [])
    return script


@op("sw.other_engines")
def sw_other_engines(rows, app_open, own):
    world_of({"own": [own]})
    return swap.other_engines(rows, app_open=app_open)


@op("sw.engines_gone")
def sw_engines_gone(world, seconds):
    world_of(world)
    return swap.engines_gone(seconds)


@op("sw.read_answer")
def sw_read_answer(world, reader, tries):
    world_of(world)
    return swap.read_answer(reads(Script(reader)), tries)


def restart_of(script):
    if script is None:
        return None
    made = Script(script)

    def restart_(between):
        LOG.append(["restart"])
        step = made.take("restart", {"between": True, "answer": ["restarted", "closed"]})
        if step.get("write"):
            place, data = step["write"]
            (ROOT / place / "auth.json").write_bytes(data)
        if step.get("between"):
            try:
                between()
            except Exception as error:
                LOG.append(["between raised", name_of(error)])
        found = step.get("answer")
        return tuple(found) if isinstance(found, list) else found
    return restart_


def files(spec):
    return {"store": spec}


@op("sw.read_profile")
def sw_read_profile(spec, target, session, now, world):
    store, ids = store_of(spec)
    world_of(world)
    script = Script(session)
    return swap.read_profile(None, store, target_of(target, ids), session_for=lambda home: Session(script, home),
                             now=now)


@op("sw.switch")
def sw_switch(spec, target, restart_script, reader, now, world):
    store, ids = store_of(spec)
    world_of(world)
    return swap.switch(None, store, ROOT / spec["codex"], target_of(target, ids), restart=restart_of(restart_script),
                       read_real=reads(Script(reader)), now=now)


@op("sw.recover")
def sw_recover(spec, reader, restart_script, world):
    store, ids = store_of(spec)
    world_of(world)
    return swap.recover(None, store, ROOT / spec["codex"], read_real=reads(Script(reader)),
                        restart=restart_of(restart_script))


@op("sw.unwind")
def sw_unwind(spec, world):
    store, ids = store_of(spec)
    world_of(world)
    return swap.unwind(store, None if spec.get("codex") is None else ROOT / spec["codex"])


@op("sw.save_current")
def sw_save_current(spec, reader):
    store, ids = store_of(spec)
    return swap.save_current(None, store, ROOT / spec["codex"], read_real=reads(Script(reader)))


@op("sw.add_by_login")
def sw_add_by_login(spec, backend, runner, session, seconds):
    store, ids = store_of(spec)
    made, script = Script(backend), Script(session)

    def backend_for(home):
        LOG.append(["backend", norm(home)])
        made.take("make")
        return Backend(made, home)
    return swap.add_by_login(None, store, backend_for=backend_for, session_for=lambda home: Session(script, home),
                             runner=runner_of(Script(runner)), seconds=seconds)


# ------------------------------------------------------------------------------------------------ engines
import enum, sqlite3  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume_advanced import state as state_package  # noqa: E402
from codex_auto_resume_advanced.registry import REGISTRY  # noqa: E402
from codex_auto_resume_advanced.engine import account as eaccount, autoswitch  # noqa: E402

STATE_CLOCK = [0.0]


def canon(value):
    if value is DEFER:
        return "DEFER"
    if isinstance(value, enum.Enum):
        value = value.value
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return list(value)
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
    return repr(value)


def state_of(home):
    STATE_CLOCK[0] = 0.0
    paths = config.Paths(str(ROOT / home))
    return state_package.AdvancedState(paths, registry=REGISTRY, clock=lambda: STATE_CLOCK[0]), paths


def seed(state, seeds):
    for name, args, kwargs in seeds or ():
        getattr(state, name)(*args, **kwargs)


def state_reads(state, entries):
    return [canon(getattr(state, name)(*args, **kwargs)) for name, args, kwargs in entries or ()]


class View:
    def __init__(self, script):
        self.script = Script(script)

    def records_in(self, states):
        LOG.append(["records_in"])
        return self.script.take("records", [])

    def settings(self):
        LOG.append(["settings"])
        return self.script.take("settings")


class Secrets:
    def __init__(self, script):
        self.script = Script(script)

    def read(self, capability, name):
        LOG.append(["secret.read", capability, name])
        found = self.script.take("read")
        return found if isinstance(found, str) else None

    def write(self, capability, name, secret):
        LOG.append(["secret.write", capability, name, secret])
        self.script.take("write")

    def delete(self, capability, name):
        LOG.append(["secret.delete", capability, name])
        return bool(self.script.take("delete", True))


@op("ea.look")
def ea_look(home, seeds, seams, view, steps, wanted):
    state, paths = state_of(home)
    seed(state, seeds)
    script = Script(seams)

    def read(paths):
        LOG.append(["read"])
        return script.take("read", {"present": None, "plan_word": None, "email": None, "kind": None})

    def hold(paths, keys, now):
        LOG.append(["hold", list(keys), float(now)])
        found = script.take("hold", 0)
        return found if isinstance(found, int) else 0

    def ours(paths, text, after):
        LOG.append(["ours", text, after])
        return bool(script.take("ours", False))
    code = eaccount.AccountWatch(paths, read=read, secrets=Secrets((seams or {}).get("secrets")), hold=hold, ours=ours)
    code.bind(state.scoped(eaccount.CAPABILITY, on=lambda: True))
    seen = View(view)
    for at in steps:
        STATE_CLOCK[0] = float(at)
        try:
            code.look(seen, float(at))
        except Exception as error:
            LOG.append(["raised", name_of(error)])
    return {"notice": code.notice(), "reads": state_reads(state, wanted)}


@op("ea.forget")
def ea_forget(home, seeds, secrets, wanted):
    state, paths = state_of(home)
    seed(state, seeds)
    done = eaccount.forget(state, Secrets(secrets))
    return {"done": done, "reads": state_reads(state, wanted)}


@op("ec.look")
def ec_look(home, seeds, spec, seams, view, steps, wanted):
    state, paths = state_of(home)
    seed(state, seeds)
    store, ids = store_of(spec)
    seams = seams or {}
    world_of(seams.get("world"))
    reader, idle, busy = Script(seams.get("reader")), Script(seams.get("idle")), Script(seams.get("busy"))
    session = Script(seams.get("session"))

    def idle_now():
        LOG.append(["idle"])
        return idle.take("idle", 1000.0)

    def busy_now():
        LOG.append(["busy"])
        return busy.take("busy", [])
    code = autoswitch.AutoSwitch(paths, store=store, session_for=lambda home: Session(session, home),
                                 restart=restart_of(seams.get("restart")), read_real=reads(reader),
                                 idle=idle_now, busy=busy_now, home=ROOT / spec["codex"])
    code.bind(state.scoped(autoswitch.CAPABILITY, on=lambda: True))
    seen = View(view)
    answers = []
    for step in steps:
        kind, at = (step[0], float(step[1])) if isinstance(step, list) else ("look", float(step))
        STATE_CLOCK[0] = at
        try:
            if kind == "settle":
                code.settle()
            elif kind in ("put_in", "manual"):
                outcome, closed = code.put_in(target_of(step[2], ids), at, manual=kind == "manual")
                answers.append([outcome, list(closed)])
            elif kind == "schedule":
                try:
                    found = code.schedule(step[2], step[3])
                    answers.append("DEFER" if found is DEFER else str(found))
                except Exception as error:
                    answers.append({"raised": type(error).__name__})
            else:
                code.look(seen, at)
        except Exception as error:
            LOG.append(["raised", name_of(error)])
    memory = {"episode": sorted(code._episode, key=str) if code._episode is not None else None,
              "switched_at": float(code._switched_at) if code._switched_at is not None else None,
              "notice": code.notice(), "others": code._others, "told": [list(each) for each in code._told],
              "looked": float(code._looked) if code._looked is not None else None}
    return {"memory": memory, "answers": answers, "reads": state_reads(state, wanted)}


# The later families add themselves below this line (EXTRA).
#EXTRA#


def name_of(error):
    name = type(error).__name__
    if name in ("AuthFileError", "ProfileError", "Locked", "PutBackWaits"):
        return name
    if isinstance(error, OSError):
        return "OSError"
    return name


results = []
for case in request["cases"]:
    LOG.clear()
    COUNTER[0] = int(WORLD.get("tokens", 0))
    try:
        results.append({"ok": norm(OPS[case[0]](*case[1:])), "log": norm(LOG)})
    except Exception as error:
        results.append({"error": name_of(error), "log": norm(LOG)})
sys.stdout.write(json.dumps({"results": results}))
'''

EXTRA: list = []


def script() -> str:
    return REFERENCE.replace("#EXTRA#", "\n".join(EXTRA))


def example(name: str = EXAMPLE) -> Path:
    named = os.environ.get("CODEX_AR_ADVACCOUNT_DIR")
    folder = Path(named) if named else advref.target_dir() / "release" / "examples"
    return folder / ("%s.exe" % name)


_BUILT: list = []


def build() -> None:
    """`cargo build --release --locked -p car-adv --example advaccount` once per run (cargo leaves an up-to-date one
    alone), so a stale probe never answers."""
    if _BUILT or os.environ.get("CODEX_AR_ADVACCOUNT_DIR"):
        return
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", EXAMPLE,
                    "--manifest-path", str(advref.ADVANCED / "Cargo.toml")], env=environment, check=True,
                   creationflags=NO_WINDOW, timeout=3600)
    _BUILT.append(True)


BOOT = ("import sys\n_path = sys.argv.pop(1)\n"
        "exec(compile(open(_path, encoding='utf-8').read(), _path, 'exec'))\n")


def ask_reference(request: dict, profile: Path) -> list:
    scratch = Path(tempfile.mkdtemp(prefix="advaccount-req-"))
    try:
        (scratch / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (scratch / "reference.py").write_text(script(), encoding="utf-8")
        command = refpython.command(BOOT, str(scratch / "reference.py"), str(scratch / "request.json"),
                                    paths=[str(each) for each in advref.trees(TAG)])
        done = subprocess.run(command, capture_output=True, env=advref.environment(profile, TAG), cwd=str(profile),
                              creationflags=NO_WINDOW, timeout=1800)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if done.returncode != 0:
        raise AssertionError("the reference failed: %s" % done.stderr[-3000:].decode("utf-8", "replace"))
    return json.loads(done.stdout.decode("utf-8"))["results"]


def ask_rust(request: dict, profile: Path) -> list:
    done = subprocess.run([str(example())], input=json.dumps(request).encode("utf-8"),
                          capture_output=True, env=advref.environment(profile, TAG), cwd=str(profile),
                          creationflags=NO_WINDOW, timeout=1800)
    if done.returncode != 0:
        raise AssertionError("advaccount failed (%d): %s" % (done.returncode,
                                                              done.stderr[-3000:].decode("utf-8", "replace")))
    return json.loads(done.stdout.decode("utf-8"))["results"]


def snapshot(root: Path) -> dict:
    """Every file and folder under `root`: a file's bytes as hex, a folder as None, a junction as such - and a SQLite
    database (the advanced state) as its dump, since two engines' pages differ in bytes the state never reads; its
    journal files are left out."""
    import sqlite3
    found = {}
    for path in sorted(root.rglob("*"), key=lambda each: each.as_posix().lower()):
        key = path.relative_to(root).as_posix()
        if path.is_junction() if hasattr(path, "is_junction") else False:
            found[key] = "junction"
        elif path.is_dir():
            found[key] = None
        elif path.name.endswith(("-wal", "-shm", "-journal")):
            continue
        elif path.suffix == ".sqlite":
            connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
            try:
                found[key] = {"dump": list(connection.iterdump())}
            finally:
                connection.close()
        elif path.is_file():
            found[key] = path.read_bytes().hex()
    return found


def junction(link: Path, target: Path) -> None:
    import _winapi
    target.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def sign_in(email: str, refresh: str = "r0") -> str:
    """A synthetic sign-in file's bytes, as hex: never a real token."""
    return json.dumps({"OPENAI_API_KEY": None, "tokens": {"id_token": "synthetic-" + email, "refresh_token": refresh},
                       "last_refresh": "2026-01-01T00:00:00Z"}).encode("utf-8").hex()


class AdvAccountDiff(unittest.TestCase):
    """A diff of S7.2b's modules: `same(label, cases, setup=)` runs one request through both sides, each on its own copy
    of what `setup(root)` makes, and holds every answer, every stand-in call and every file left equal."""

    @classmethod
    def setUpClass(cls):
        build()
        advref.package(TAG)
        cls.root = Path(tempfile.mkdtemp(prefix="advaccount-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)

    def fresh(self, label: str) -> Path:
        short = re.sub(r"[^A-Za-z0-9]+", "-", label)[:40]
        return Path(tempfile.mkdtemp(prefix="%s-" % short, dir=self.root))

    def compare(self, label, cases, want, got):
        self.assertEqual(len(want), len(got), label)
        for index, (one, other) in enumerate(zip(want, got)):
            if diffs.encode(one) != diffs.encode(other):
                self.fail("%s: case %d differs at %s\n  case      %s\n  reference %s\n  rust      %s" % (
                    label, index, advdiff.first_difference(one, other),
                    json.dumps(cases[index], ensure_ascii=False)[:700], json.dumps(one, ensure_ascii=False)[:900],
                    json.dumps(other, ensure_ascii=False)[:900]))

    def same(self, label: str, cases: list, *, setup=None, world: dict | None = None, one_by_one: bool = False) -> list:
        """Both sides on the same cases. `one_by_one`: each case on its own fresh copy of `setup`'s folders (a case
        that changes files), the files left compared case by case."""
        batches = [[case] for case in cases] if one_by_one else [cases]
        answers = []
        for number, batch in enumerate(batches):
            left = []
            for ask in (ask_reference, ask_rust):
                profile = self.fresh("%s-%d" % (label, number))
                if setup is not None:
                    setup(profile)
                found = ask({"world": world or {}, "cases": batch}, profile)
                left.append((found, snapshot(profile)))
            (want, want_files), (got, got_files) = left
            self.compare(label, batch, want, got)
            self.assertEqual(sorted(want_files), sorted(got_files),
                             "%s: the files left differ (case %s)" % (label, json.dumps(batch[0])[:300]))
            for name in want_files:
                self.assertEqual(want_files[name], got_files[name], "%s: %s differs (case %s)" % (
                    label, name, json.dumps(batch[0])[:300]))
            answers += want
        # A family whose every case raised (a seed or a store that cannot be made) would be equal and prove nothing.
        self.assertTrue(any("ok" in each for each in answers), "%s: every case raised" % label)
        return answers

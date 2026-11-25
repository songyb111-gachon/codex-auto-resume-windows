"""The installer proofs' test double (seat S8.2): the Rust core the stub cannot be yet, v0.6.26's engine, and both
watchers, on scratch homes only.

Three roles, one file:

* `core` - the Rust core. The stub `codex-auto-resume.exe` hands every command here where CODEX_AUTO_RESUME_TEST_CORE
  names an interpreter and CODEX_AUTO_RESUME_TEST_CORE_SCRIPT this file (car-bin `core_stub`); the stub sets
  CODEX_AUTO_RESUME_TEST_CORE_EXE, which is how this role is told. It answers the commands install.ps1, the bootstrap
  and car-legacy hand on with plugin_setup.py's codes and lines (the contract the real core keeps, P5/P6): `claim-home`,
  `verify-home`, `setup [--keep-state] [--no-startup] [--watcher-was-stopped] [--edition-from E]` (0, 2 unconfirmed,
  4 left stopped, 5 started again), `stop`, `watcher-running` (0 running, else 2), `doctor`, `uninstall [--purge]`,
  `remove-entry`, `downgrade-state --to N --stop-watcher`, `desktop-shortcut make|remove`, `engine-trusted` (1).
  Its registrations are the Rust ones PLAN 6.4 names: the Run value `"<home>\\app\\bin\\CodexAutoResume.exe" --home
  "<home>" run` - with --home, which is how v0.6.26's startup.belongs_to knows it as this installation's - and the
  link handler `"<home>\\app\\bin\\codex-auto-resume.exe" --home "<home>" activate "%1"`.
* `engine` - v0.6.26's plugin_setup.py, run by a real Python at runtime\\python.exe of a v0.6.26-shaped home (the
  test's app\\scripts\\plugin_setup.py is a shim to this role). The same commands, registering v0.6.26's own shapes
  (its startup.command_line and notification_command) and writing watcher-launcher.py and runtime.json as its
  install_launcher does.
* `watch --flavour python|rust` - a watcher: it takes the home's watcher mutex - one name for both flavours, so the
  two exclude each other as PLAN 6.2's handover needs - and ends when the home's stop event is set. The Python one
  runs as runtime\\pythonw.exe <home>\\watcher-launcher.py run (a shim), the Rust one as app\\bin\\CodexAutoResume.exe
  (a copy of pythonw.exe the test puts there for P6's host), so install.ps1 finds each by what it is.

Every decision about ownership is v0.6.26's own: config.Paths' owns_home and claim_home and startup.belongs_to, from
the tag (CAR_DOUBLE_REFERENCE, tests/released.py's package). Nothing real is touched:

* a home outside CAR_DOUBLE_SCRATCH is refused (exit 1) before anything is read;
* the registry is a JSON file (CAR_DOUBLE_REGISTRY): {"run", "protocol", "entries": {name: {InstallLocation,
  UninstallString}}} - never HKCU;
* the mutex and the stop event are named after CAR_DOUBLE_NAMES, a test-only prefix, never the product's
  `Local\\codex-auto-resume-<digest>`; a watcher ends by itself after CAR_DOUBLE_LIFETIME seconds (600);
* every child is started with CREATE_NO_WINDOW and no inherited handle.

CAR_DOUBLE_FAIL lists `role:command` pairs that end with 1 (a setup that does not complete). CAR_DOUBLE_RUN_NO_HOME=1
makes the core register its Run value without --home: the shape the downgrade proof shows v0.6.26 would not know.
Each call is one JSON line in CAR_DOUBLE_LOG.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

NO_WINDOW = 0x08000000
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0, 0x80, 0x102
SYNCHRONIZE, EVENT_MODIFY_STATE = 0x00100000, 0x0002
OWNER_TEXT = "Created by codex-auto-resume. Deleting this file makes `uninstall` skip this directory.\n"
OCCUPIED_NAMES = ("app", "runtime", "config", "logs")
ENTRY_NAMES = {"standard": "CodexAutoResume", "advanced": "CodexAutoResumeAdvanced"}

_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel.CreateMutexW.restype = wintypes.HANDLE
_kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel.OpenMutexW.restype = wintypes.HANDLE
_kernel.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_kernel.CreateEventW.restype = wintypes.HANDLE
_kernel.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
_kernel.OpenEventW.restype = wintypes.HANDLE
_kernel.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_kernel.WaitForSingleObject.restype = wintypes.DWORD
_kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel.OpenProcess.restype = wintypes.HANDLE
_kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel.SetEvent.argtypes = (wintypes.HANDLE,)
_kernel.ResetEvent.argtypes = (wintypes.HANDLE,)
_kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
_kernel.CloseHandle.argtypes = (wintypes.HANDLE,)


class Refused(Exception):
    pass


def environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise Refused("%s is not set: the double runs only for a test" % name)
    return value


def inside(child: Path, parent: Path) -> bool:
    child_text, parent_text = os.path.normcase(str(child)), os.path.normcase(str(parent))
    return child_text == parent_text or child_text.startswith(parent_text.rstrip("\\") + "\\")


def home_path() -> Path:
    """The installation home - CODEX_AUTO_RESUME_PLUGIN_HOME, as install.ps1 and plugin_setup.py read it - and only one
    inside the test's scratch folder."""
    scratch = Path(environment("CAR_DOUBLE_SCRATCH")).resolve()
    home = Path(environment("CODEX_AUTO_RESUME_PLUGIN_HOME")).resolve()
    if not inside(home, scratch) or home == scratch:
        raise Refused("%s is outside the test's scratch folder %s" % (home, scratch))
    return home


def reference():
    """v0.6.26's config and startup modules, from the tag (tests/released.py's package)."""
    source = environment("CAR_DOUBLE_REFERENCE")
    if source not in sys.path:
        sys.path.insert(0, source)
    from codex_auto_resume import config, startup  # noqa: E402  (the tag's)
    return config, startup


def log(role: str, words: list, **said) -> None:
    path = os.environ.get("CAR_DOUBLE_LOG")
    if not path:
        return
    record = {"role": role, "words": words, "pid": os.getpid(), "at": time.time()}
    record.update(said)
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")


def names(home: Path) -> tuple:
    digest = hashlib.sha256(os.path.normcase(str(home)).encode("utf-8")).hexdigest()[:16]
    prefix = environment("CAR_DOUBLE_NAMES")
    if not prefix.startswith("Local\\car-double-"):
        raise Refused("CAR_DOUBLE_NAMES must be a test-only name")
    return prefix + "-watcher-" + digest, prefix + "-stop-" + digest


def held(mutex_name: str) -> bool:
    handle = _kernel.OpenMutexW(SYNCHRONIZE, False, mutex_name)
    if not handle:
        return False
    try:
        answer = _kernel.WaitForSingleObject(handle, 0)
        if answer in (WAIT_OBJECT_0, WAIT_ABANDONED):
            _kernel.ReleaseMutex(handle)
            return False
        return answer == WAIT_TIMEOUT
    finally:
        _kernel.CloseHandle(handle)


def wait_ended(pid: int, seconds: float) -> bool:
    """Whether the process `pid` has ended, waiting up to `seconds`. Only waits: nothing is ever ended here."""
    handle = _kernel.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return True
    try:
        return _kernel.WaitForSingleObject(handle, int(seconds * 1000)) == WAIT_OBJECT_0
    finally:
        _kernel.CloseHandle(handle)


def signal_stop(event_name: str) -> bool:
    handle = _kernel.OpenEventW(EVENT_MODIFY_STATE, False, event_name)
    if not handle:
        return False
    try:
        return bool(_kernel.SetEvent(handle))
    finally:
        _kernel.CloseHandle(handle)


# ------------------------------------------------------------------------------------------------ the registry
def registry_path() -> Path:
    path = Path(environment("CAR_DOUBLE_REGISTRY")).resolve()
    if not inside(path, Path(environment("CAR_DOUBLE_SCRATCH")).resolve()):
        raise Refused("the registry stand-in must be in the scratch folder")
    return path


def load_registry() -> dict:
    path = registry_path()
    if not path.is_file():
        return {"run": None, "protocol": None, "entries": {}}
    data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    data.setdefault("run", None)
    data.setdefault("protocol", None)
    if not isinstance(data.get("entries"), dict):
        data["entries"] = {}
    return data


def save_registry(data: dict) -> None:
    registry_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


# ------------------------------------------------------------------------------------------------ shapes
def edition_of(home: Path) -> str:
    package = home / "app" / "src" / "codex_auto_resume_advanced" / "__init__.py"
    return "advanced" if package.is_file() else "standard"


def run_value(role: str, home: Path, startup) -> str:
    if role == "engine":
        return startup.command_line(home / "watcher-launcher.py", None, launcher=home / "runtime" / "pythonw.exe")
    host = home / "app" / "bin" / "CodexAutoResume.exe"
    words = [str(host)] + ([] if os.environ.get("CAR_DOUBLE_RUN_NO_HOME") == "1" else ["--home", str(home)]) + ["run"]
    return " ".join(startup.quote_argument(word) for word in words)


def protocol_value(role: str, home: Path, startup) -> str:
    if role == "engine":
        argv = [str(home / "runtime" / "pythonw.exe"), *startup.NO_REMOTE_DEBUG, str(home / "watcher-launcher.py"),
                "activate"]
    else:
        argv = [str(home / "app" / "bin" / "codex-auto-resume.exe"), "--home", str(home), "activate"]
    return " ".join(startup.quote_argument(argument) for argument in argv) + ' "%1"'


def shim(target: Path, *role: str) -> None:
    """A Python file that runs this double in `role`, with the words it was started with."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import runpy, sys\nsys.argv = [%r, '--role', %s] + sys.argv[1:]\nrunpy.run_path(%r, "
                      "run_name='__main__')\n" % (__file__, ", ".join(repr(word) for word in role), __file__),
                      encoding="utf-8")


# ------------------------------------------------------------------------------------------------ the watcher
def start_watcher(role: str, home: Path) -> str:
    """'already-running', 'running', 'failed' or 'no-host'."""
    mutex, _ = names(home)
    if held(mutex):
        return "already-running"
    if role == "engine":
        program, words = home / "runtime" / "pythonw.exe", [str(home / "watcher-launcher.py"), "run"]
        words = ["-X", "disable-remote-debug"] + words
    else:
        program = home / "app" / "bin" / "CodexAutoResume.exe"
        words = [__file__, "--role", "watch", "--flavour", "rust", "--home", str(home)]
    if not program.is_file():
        return "no-host"
    subprocess.Popen([str(program)] + words, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, creationflags=NO_WINDOW, cwd=str(home))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if held(mutex):
            return "running"
        time.sleep(0.1)
    return "failed"


def stop_watcher(home: Path, seconds: float = 30) -> bool:
    mutex, stop = names(home)
    if not held(mutex):
        return True
    signal_stop(stop)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not held(mutex):
            return True
        time.sleep(0.1)
    return False


def watch(words: list) -> int:
    flavour = words[words.index("--flavour") + 1] if "--flavour" in words else "python"
    home = Path(words[words.index("--home") + 1]).resolve() if "--home" in words else home_path()
    scratch = Path(environment("CAR_DOUBLE_SCRATCH")).resolve()
    if not inside(home, scratch):
        raise Refused("%s is outside the scratch folder" % home)
    mutex_name, stop_name = names(home)
    mutex = _kernel.CreateMutexW(None, False, mutex_name)
    if not mutex:
        return 1
    if _kernel.WaitForSingleObject(mutex, 0) not in (WAIT_OBJECT_0, WAIT_ABANDONED):
        log("watch", words, flavour=flavour, home=str(home), outcome="mutex held by another")
        return 4
    stop = _kernel.CreateEventW(None, True, False, stop_name)
    _kernel.ResetEvent(stop)
    log("watch", words, flavour=flavour, home=str(home), outcome="started", executable=sys.executable)
    lifetime = float(os.environ.get("CAR_DOUBLE_LIFETIME", "600"))
    deadline = time.monotonic() + lifetime
    outcome = "lifetime"
    while time.monotonic() < deadline:
        if _kernel.WaitForSingleObject(stop, 200) == WAIT_OBJECT_0:
            outcome = "stopped"
            break
    _kernel.ReleaseMutex(mutex)
    _kernel.CloseHandle(mutex)
    _kernel.CloseHandle(stop)
    log("watch", words, flavour=flavour, home=str(home), outcome=outcome)
    return 0


# ------------------------------------------------------------------------------------------------ the commands
def fails(role: str, command: str) -> bool:
    listed = [item.strip() for item in os.environ.get("CAR_DOUBLE_FAIL", "").split(",") if item.strip()]
    return ("%s:%s" % (role, command)) in listed


def value_after(words: list, name: str):
    return words[words.index(name) + 1] if name in words and words.index(name) + 1 < len(words) else None


def command(role: str, words: list) -> int:
    if not words:
        print("usage: a command", file=sys.stderr)
        return 2
    name, rest = words[0], words[1:]
    home = home_path()
    config, startup = reference()
    log(role, words, home=str(home))
    if fails(role, name):
        print("error: %s failed (the test asked for it)" % name)
        return 1
    paths = config.Paths(home)
    if name == "verify-home":
        if not paths.owns_home():
            print("not-owned")
            print(str(home))
            return 1
        print("owned")
        print(str(paths.home))
        return 0
    if name == "claim-home":
        if paths.owns_home():
            print("owned")
            print(str(paths.home))
            return 0
        try:
            occupied = sorted(entry.name for entry in home.iterdir()
                              if entry.name in OCCUPIED_NAMES or ".old-" in entry.name)
        except OSError:
            occupied = []
        if occupied or not paths.claim_home():
            print("not-owned")
            print(str(home))
            for entry in occupied:
                print(entry)
            return 1
        print("claimed")
        print(str(paths.home))
        return 0
    if name == "setup":
        return setup(role, home, rest, paths, startup)
    if name == "stop":
        stopped = stop_watcher(home, 60)
        print("watcher: stopped" if stopped else "watcher: still running")
        return 0
    if name == "watcher-running":
        running = held(names(home)[0])
        print("watcher: running" if running else "watcher: stopped")
        return 0 if running else 2
    if name == "doctor":
        print("health check     : ok")
        return 0
    if name == "uninstall":
        return uninstall(role, home, rest, startup)
    if name == "remove-entry":
        registry = load_registry()
        entry = ENTRY_NAMES[edition_of(home)]
        removed = registry["entries"].pop(entry, None) is not None
        save_registry(registry)
        print("entry: removed" if removed else "entry: none")
        return 0
    if name == "downgrade-state":
        if "--stop-watcher" in rest and not stop_watcher(home, 60):
            print("downgrade: watcher-running")
            return 3
        print("downgrade: nothing")
        return 0
    if name == "desktop-shortcut" and rest[:1] in (["make"], ["remove"]):
        return 0
    if name == "engine-trusted":
        return 1
    if name in ("enable", "disable", "status", "pending", "logs", "cancel"):
        print("%s: done" % name)
        return 0
    print("error: unrecognized command %r" % name, file=sys.stderr)
    return 2


def setup(role: str, home: Path, words: list, paths, startup) -> int:
    keep = "--keep-state" in words
    no_startup = "--no-startup" in words
    was_stopped = keep and "--watcher-was-stopped" in words
    paths.ensure()
    if role == "engine":
        # v0.6.26's install_launcher: the stable launcher at the root, runtime.json, and the root claimed.
        shim(home / "watcher-launcher.py", "watch", "--flavour", "python")
        (home / "runtime.json").write_text(json.dumps({"mode": "local", "plugin_name": "codex-auto-resume",
                                                       "plugin_root": str(home / "app"), "home": str(home)},
                                                      indent=2), encoding="utf-8")
        paths.claim_home()
    registry = load_registry()
    current = registry.get("run")
    enabled = bool(current) and startup.belongs_to(current, home)
    if not no_startup and (not keep or enabled):
        registry["run"] = run_value(role, home, startup)
    registry["protocol"] = protocol_value(role, home, startup)
    kept = home / "uninstall" / "install.ps1"
    if kept.is_file():
        registry["entries"][ENTRY_NAMES[edition_of(home)]] = {
            "InstallLocation": str(home),
            "UninstallString": '"%s" "--uninstall" "%s"' % (home / "CodexAutoResumeSettings.exe", kept)}
    save_registry(registry)
    startup_on = bool(registry.get("run")) and startup.belongs_to(registry["run"], home)
    if was_stopped and not startup_on:
        print("The watcher was not running before, and it does not start at sign-in, so it was left stopped.")
        print("state: %s" % home)
        return 4 if os.environ.get("CODEX_AUTO_RESUME_SETUP_SAYS_LEFT_STOPPED") == "1" else 0
    started = start_watcher(role, home)
    log(role, ["setup:watcher"], home=str(home), started=started)
    print("watcher: %s" % started)
    print("state: %s" % home)
    return 0 if started in ("running", "already-running") else 2


def uninstall(role: str, home: Path, words: list, startup) -> int:
    if not stop_watcher(home, 60):
        print("error: the watcher could not be stopped")
        return 1
    registry = load_registry()
    if registry.get("run") and startup.belongs_to(registry["run"], home):
        registry["run"] = None
    if registry.get("protocol") and str(home).lower() in registry["protocol"].lower():
        registry["protocol"] = None
    if os.environ.get("CODEX_AUTO_RESUME_KEEP_ENTRY") != "1":
        registry["entries"].pop(ENTRY_NAMES[edition_of(home)], None)
    save_registry(registry)
    for name in ("watcher-launcher.py", "runtime.json"):
        path = home / name
        if path.is_file():
            path.unlink()
    print("uninstalled")
    return 0


def main(argv: list) -> int:
    try:
        if argv[:1] == ["--role"] and len(argv) >= 2:
            role, words = argv[1], argv[2:]
        elif os.environ.get("CODEX_AUTO_RESUME_TEST_CORE_EXE"):
            role, words = "core", argv
        else:
            raise Refused("no role: started by neither the stub core nor a shim")
        if role == "watch":
            return watch(words)
        if role not in ("core", "engine"):
            raise Refused("no such role %r" % role)
        return command(role, words)
    except Refused as refusal:
        print("install_double: refused: %s" % refusal, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

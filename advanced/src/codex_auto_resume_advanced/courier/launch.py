# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Starting the courier: from the watcher at P8 (engine/push.py, engine/feed.py) and from the Dashboard's service for
a test notice, a pairing or a feed read now (control/courier.py). No network here.

The courier is this product's own code, so it runs under pythonw.exe beside the interpreter running this one
(startup.python_launcher, rule 12), `-c <BOOTSTRAP> <import roots> --home <home>`, and no console: CREATE_NO_WINDOW, and
CREATE_SUSPENDED so it is in this process's one job object - made
KILL_ON_JOB_CLOSE, its one handle never closed here - before it runs an instruction; then resumed. That is the chain
codex/wmi_escape.py and report/github.py use, and it means the courier ends with the process that started it, however
that process ends. One that cannot be put in the job is ended before it runs.

The import roots are on the command line, not in PYTHONPATH: an installed copy runs the embeddable runtime, whose
python3XX._pth makes it ignore the environment (sys.flags.ignore_environment), so a PYTHONPATH reached nothing there and
every courier start from an installation failed on its first import (v0.6.22's live acceptance, F7). BOOTSTRAP is the
two-line dispatcher codex/wmi_escape.py's helper runs: the roots onto sys.path, then the courier's own main. A constant;
what follows it is paths and this module's own words, never a person's text.

`start` never waits: the watcher's tick goes on at once, whatever the courier does (E11). From the watcher it starts
at most once in EVERY seconds for one home (`start_due`), and the courier's own mutex refuses a second for the same
home anyway. `run` waits, for the Dashboard's test notice, at most a given time.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import threading
import time

from codex_auto_resume.win.kernel import JOB_KILL_ON_CLOSE, NO_WINDOW

MODULE = "codex_auto_resume_advanced.courier"
# The courier's start, whatever the interpreter makes of the environment: sys.argv[1] is roots(), the rest the courier's.
BOOTSTRAP = ("import os, sys; sys.path[:0] = sys.argv[1].split(os.pathsep); "
             "from %s.__main__ import main; sys.exit(main(sys.argv[2:]))" % MODULE)
EVERY = 60                                   # seconds between two starts from the watcher, for one home
CREATE_SUSPENDED = 0x00000004
FLAGS = NO_WINDOW | CREATE_SUSPENDED
_JOB_EXTENDED_LIMIT_INFORMATION = 9

_LOCK = threading.Lock()
_JOB = None
_STARTED = {}                                # {home: when the watcher last started a courier for it}
_CHILDREN = []                               # started and not yet reaped, so no handle is left behind


def roots() -> str:
    """The import roots the courier needs: this edition's package and the core beside it."""
    import codex_auto_resume
    advanced_src = Path(__file__).resolve().parents[2]
    core_src = Path(codex_auto_resume.__file__).resolve().parents[1]
    return os.pathsep.join(dict.fromkeys((str(advanced_src), str(core_src))))


def argv(paths, *extra) -> list:
    """The courier's command line: pythonw.exe, the bootstrap and the import roots it puts on sys.path, the home, and
    `extra` (`--pair`, `--test <channel>`, `--feed`, `--serve`, `--check`)."""
    from codex_auto_resume import startup
    interpreter = startup.python_launcher()
    return [str(interpreter), *startup.NO_REMOTE_DEBUG, "-c", BOOTSTRAP, roots(), "--home", str(Path(paths.home)),
            *extra]


def _kernel():
    from ..codex.wmi_escape import _kernel as kernel        # the job object's calls, declared once
    return kernel()


def _job(k):
    """This process's one job object for the courier: KILL_ON_JOB_CLOSE, never closed here."""
    global _JOB
    with _LOCK:
        if _JOB is None:
            from ..codex.wmi_escape import _ExtendedLimits
            handle = k.CreateJobObjectW(None, None)
            if not handle:
                raise OSError("no job object")
            info = _ExtendedLimits()
            info.basic.flags = JOB_KILL_ON_CLOSE
            if not k.SetInformationJobObject(handle, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                             ctypes.sizeof(info)):
                k.CloseHandle(handle)
                raise OSError("the job object refused its limits")
            _JOB = handle
        return _JOB


def adopt(process) -> None:
    """`process`, started suspended, put in the job and resumed - or ended, and OSError."""
    try:
        k = _kernel()
        job = _job(k)
        handle = k.OpenProcess(0x0001 | 0x0100 | 0x0800, False, process.pid)   # TERMINATE | SET_QUOTA | SUSPEND_RESUME
        if not handle:
            raise OSError("the courier could not be opened")
        try:
            if not k.AssignProcessToJobObject(job, handle):
                raise OSError("the courier could not be put in the job")
            if ctypes.WinDLL("ntdll").NtResumeProcess(ctypes.c_void_p(handle)) != 0:
                raise OSError("the courier could not be resumed")
        finally:
            k.CloseHandle(handle)
    except BaseException:
        process.kill()
        raise


def spawn(paths, *extra, popen=None, adopt_it=None):
    """The courier started, in the job and running - its Popen - or None where it could not be: no pythonw.exe, a
    refused start, or a job that would not take it (then it was ended before it ran)."""
    popen = popen or subprocess.Popen
    adopt_it = adopt_it or adopt
    try:
        command = argv(paths, *extra)
    except Exception:
        return None
    # The roots travel on the command line; a PYTHONPATH of the caller's would only stand before the standard library.
    environment = {name: value for name, value in os.environ.items() if name.upper() != "PYTHONPATH"}
    try:
        process = popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        env=environment, creationflags=NO_WINDOW | CREATE_SUSPENDED, close_fds=True, shell=False)
    except OSError:
        return None
    try:
        adopt_it(process)
    except BaseException:
        try:
            process.wait(5)
        except Exception:
            pass
        return None
    with _LOCK:
        _CHILDREN[:] = [child for child in _CHILDREN if child.poll() is None]
        _CHILDREN.append(process)
    return process


def start(paths, *extra, **seams) -> bool:
    """Start the courier and return at once: whether it started."""
    return spawn(paths, *extra, **seams) is not None


def start_due(paths, now=None, *extra, **seams) -> bool:
    """From the watcher: start the courier, with `extra`, unless one was started for this home in the last EVERY
    seconds. Whether it was started now."""
    now = time.time() if now is None else now
    home = str(Path(paths.home))
    with _LOCK:
        last = _STARTED.get(home)
        if last is not None and 0 <= now - last < EVERY:
            return False
        _STARTED[home] = now
    return start(paths, *extra, **seams)


def run(paths, *extra, timeout=30, **seams):
    """Start the courier and wait for it at most `timeout` seconds: its exit code, or None where it did not start or
    has not finished (it is then left to finish, in the job)."""
    process = spawn(paths, *extra, **seams)
    if process is None:
        return None
    try:
        return process.wait(timeout)
    except subprocess.TimeoutExpired:
        return None

# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""MW's real launcher: re-prove that a process can leave Codex's kind of job through WMI.

Measured on 2026-09-25, Codex runs each plugin's MCP server inside a job object with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE and no breakaway, so a watcher a plugin starts plainly dies
when that server closes. The one way out that was measured to work is WMI: a process inside such
a job asks WMI Win32_Process.Create to start the watcher, whose parent becomes WmiPrvSE - outside
the job - so closing the job does not kill it. This module re-proves that chain on demand, as
measurement MW, and records only the heartbeat's job words.

The chain, from the harness (this process, under pythonw - the watcher's own host):

    1. Create a job object with KILL_ON_JOB_CLOSE and no breakaway - the shape Codex gives its
       MCP servers.
    2. Start a helper, suspended so it is assigned to the job before it does anything, then
       resume it. The helper stands inside the job.
    3. The helper asks WMI Win32_Process.Create to start pythonw.exe on the heartbeat, with
       Win32_ProcessStartup ShowWindow = 0. The heartbeat lands outside the job.
    4. The heartbeat writes its job words - IsProcessInJob, and the job's limit flags if it is in
       one - to a temp file, then waits.
    5. The harness closes the job. Its still-inside helper dies (KILL_ON_JOB_CLOSE); the heartbeat,
       outside it, does not.
    6. The harness checks the heartbeat is still alive and stood outside any job, then cleans up
       everything it started.

Every process it starts is windowless (v0611_no_console_rules.md): the helper is pythonw.exe from
`startup.python_launcher()`, started with CREATE_NO_WINDOW (and CREATE_SUSPENDED, which does not
void it); the WMI create goes through `pwsh.run` (CREATE_NO_WINDOW) with ShowWindow = 0 and never
a CreateFlags argument (which returns 21); the heartbeat is pythonw.exe too. Nothing here touches
Codex, the installed product, the registry or any scheduled task: it is a self-contained loop of
throwaway processes in a temporary directory, and the tests drive it with a fake launcher. The
one real live run is opt-in, under CODEX_AR_LIVE_WMI=1.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from codex_auto_resume.win.kernel import JOB_KILL_ON_CLOSE, NO_WINDOW

# Started suspended so the helper is in the job before it fires WMI; this bit does not void
# CREATE_NO_WINDOW the way DETACHED_PROCESS or CREATE_NEW_CONSOLE would (test_no_console_windows).
CREATE_SUSPENDED = 0x00000004
_JOB_EXTENDED_LIMIT_INFORMATION = 9
# How long each hand of the chain is given. The heartbeat outlives the harness's own check so it
# is provably alive after the job closes; the harness kills it in cleanup regardless.
_HEARTBEAT_SECONDS = 30.0
_HELPER_SECONDS = 12.0
_WMI_TIMEOUT = 30.0
_SETTLE_SECONDS = 3.0

# The WMI create, as a constant `pwsh.run` script. The command line arrives as an environment
# variable (pwsh passes values that way, so nothing derived from a path is ever formatted into
# the script). ShowWindow = 0 is the second guard the console rules ask for; CreateFlags is never
# passed, because WMI returns 21 when it is. A non-zero ReturnValue is turned into a non-zero exit
# so the harness sees the create failed without reading any output.
_WMI_SCRIPT = r"""
$cmd = $env:CODEX_AUTO_RESUME_ARG_HEARTBEAT_CMD
$startup = New-CimInstance -Namespace root/cimv2 -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
$r = Invoke-CimMethod -Namespace root/cimv2 -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; ProcessStartupInformation = $startup }
if ($null -eq $r -or $r.ReturnValue -ne 0) { exit 3 }
exit 0
"""


# --------------------------------------------------------------------------- kernel handles
class _BasicLimits(ctypes.Structure):
    _fields_ = [("per_process_user_time", ctypes.c_longlong),
                ("per_job_user_time", ctypes.c_longlong), ("flags", wintypes.DWORD),
                ("minimum_working_set", ctypes.c_size_t), ("maximum_working_set", ctypes.c_size_t),
                ("active_process_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                ("priority_class", wintypes.DWORD), ("scheduling_class", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = ([("basic", _BasicLimits)]
                + [(name, ctypes.c_ulonglong) for name in ("read_operations", "write_operations",
                   "other_operations", "read_bytes", "write_bytes", "other_bytes")]
                + [(name, ctypes.c_size_t) for name in ("process_memory_limit", "job_memory_limit",
                   "peak_process_memory", "peak_job_memory")])


def _kernel():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.TerminateProcess.restype = wintypes.BOOL
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


def _alive(k, pid) -> bool:
    handle = k.OpenProcess(0x00100000 | 0x1000, False, pid)   # SYNCHRONIZE | QUERY_LIMITED
    if not handle:
        return False
    try:
        return k.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT: still running
    finally:
        k.CloseHandle(handle)


def _terminate(k, pid) -> None:
    handle = k.OpenProcess(0x0001, False, pid)                # PROCESS_TERMINATE
    if handle:
        try:
            k.TerminateProcess(handle, 1)
        finally:
            k.CloseHandle(handle)


# --------------------------------------------------------------------------- the harness
def _src_paths() -> str:
    """The import roots the helper and the heartbeat need on sys.path: this edition's package and
    the core beside it, so a WMI-started pythonw with no PYTHONPATH can reach them."""
    import codex_auto_resume

    advanced_src = Path(__file__).resolve().parents[2]        # advanced/src
    core_src = Path(codex_auto_resume.__file__).resolve().parents[1]
    return os.pathsep.join(dict.fromkeys((str(advanced_src), str(core_src))))


# The bootstrap the helper and the heartbeat both run: it puts the import roots on the path and
# hands off to this module's own role. Written to the throwaway directory and started by name, so
# a WMI command line quotes four plain tokens, never a multi-line -c argument. All of the logic
# stays in this reviewed module; the file is a two-line dispatcher.
_BOOTSTRAP = (
    "import os, sys\n"
    "sys.path[:0] = sys.argv[2].split(os.pathsep)\n"
    "from codex_auto_resume_advanced.codex import wmi_escape\n"
    "wmi_escape._role(sys.argv[1], sys.argv[2], sys.argv[3:])\n"
)


def probe(paths=None) -> dict:
    """Run the whole chain once and report the heartbeat's job words. Content-free: booleans only.

    Returns {started, in_job, kill_on_close, survived}, where `started` is that the heartbeat ran,
    `in_job` is its own IsProcessInJob, `kill_on_close` is that the job we built killed its in-job
    helper (the shape held), and `survived` is that the heartbeat outlived the job's close. MW is
    a pass only when the heartbeat started, stood outside a job, and survived (measure._mw)."""
    facts = {"started": False, "in_job": None, "job_kills_on_close": None, "kill_on_close": False,
             "survived": False}
    if os.name != "nt":
        return facts
    from codex_auto_resume import startup
    try:
        pythonw = startup.python_launcher()
    except Exception:
        return facts                                          # no windowless interpreter: not started

    workdir = Path(tempfile.mkdtemp(prefix="car-mw-"))
    bootstrap = workdir / "bootstrap.py"
    bootstrap.write_text(_BOOTSTRAP, encoding="utf-8")
    heartbeat_out = workdir / "heartbeat.json"
    src_paths = _src_paths()

    k = _kernel()
    job = k.CreateJobObjectW(None, None)
    helper = None
    helper_handle = None
    heartbeat_pid = None
    try:
        info = _ExtendedLimits()
        info.basic.flags = JOB_KILL_ON_CLOSE                  # and no breakaway, as Codex does
        if not job or not k.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT_INFORMATION,
                                                    ctypes.byref(info), ctypes.sizeof(info)):
            return facts
        argv = [str(pythonw), str(bootstrap), "helper", src_paths, str(workdir),
                str(pythonw), str(bootstrap)]
        helper = subprocess.Popen(argv, creationflags=NO_WINDOW | CREATE_SUSPENDED,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, close_fds=True, shell=False)
        helper_handle = k.OpenProcess(0x1F0FFF, False, helper.pid)   # PROCESS_ALL_ACCESS
        if not helper_handle or not k.AssignProcessToJobObject(job, helper_handle):
            return facts
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtResumeProcess(wintypes.HANDLE(helper_handle))

        heartbeat = _await_json(heartbeat_out, _WMI_TIMEOUT)
        if heartbeat is None:
            return facts                                      # WMI never produced the heartbeat
        facts["started"] = True
        heartbeat_pid = heartbeat.get("pid")
        facts["in_job"] = bool(heartbeat.get("in_job"))
        # The job the heartbeat is in now, if any, and whether it would end it: Windows keeps a
        # WMI-started process in a job of its own, which is harmless only while that job does not.
        facts["job_kills_on_close"] = bool(heartbeat.get("kill_on_close"))
        helper_alive_before = _alive(k, helper.pid)
        k.CloseHandle(job)                                    # the job closes: its members die
        job = None
        time.sleep(_SETTLE_SECONDS)
        facts["kill_on_close"] = helper_alive_before and not _alive(k, helper.pid)
        facts["survived"] = _alive(k, heartbeat_pid) if isinstance(heartbeat_pid, int) else False
        return facts
    finally:
        if isinstance(heartbeat_pid, int):
            _terminate(k, heartbeat_pid)
        if helper is not None:
            try:
                helper.wait(timeout=1)
            except Exception:
                _terminate(k, helper.pid)
        if helper_handle:
            k.CloseHandle(helper_handle)
        if job:
            k.CloseHandle(job)
        _remove(workdir)


def _await_json(path: Path, timeout: float):
    """The heartbeat's record once it is whole, or None if it never appears. It is written to a
    temp name and renamed, so a partial read is impossible."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.2)
    return None


def _remove(directory: Path) -> None:
    import shutil

    shutil.rmtree(directory, ignore_errors=True)


# --------------------------------------------------------------------------- the started roles
def _role(role, src_paths, rest) -> None:
    """The entry the bootstrap hands to, inside the helper or the heartbeat."""
    if role == "helper":
        _helper_main(src_paths, rest[0], rest[1], rest[2])
    elif role == "heartbeat":
        _heartbeat_main(rest[0])


def _helper_main(src_paths, workdir, pythonw, bootstrap) -> None:
    """Inside the job: ask WMI to start the heartbeat outside it, through pwsh.run so the create
    is windowless and carries ShowWindow = 0, then wait so the job still holds a live member when
    the harness closes it."""
    from codex_auto_resume import pwsh, startup

    heartbeat_out = os.path.join(workdir, "heartbeat.json")
    tokens = [pythonw, bootstrap, "heartbeat", src_paths, heartbeat_out]
    command_line = " ".join(startup.quote_argument(token) for token in tokens)
    try:
        pwsh.run(_WMI_SCRIPT, {"HEARTBEAT_CMD": command_line}, timeout=_WMI_TIMEOUT)
    except Exception:
        return
    time.sleep(_HELPER_SECONDS)


def _heartbeat_main(out_path) -> None:
    """Outside the job (WMI started it): write this process's own job words, then wait so the
    harness can see it is still alive after the job closes."""
    from codex_auto_resume.win import kernel

    context = kernel.process_context()
    data = {"pid": os.getpid(), "in_job": context.get("in_job"),
            "kill_on_close": context.get("kill_on_close")}
    temporary = str(out_path) + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(temporary, out_path)
    time.sleep(_HEARTBEAT_SECONDS)


if __name__ == "__main__":                                    # pragma: no cover - reached only as a role
    _role(sys.argv[1], sys.argv[2], sys.argv[3:])

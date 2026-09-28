# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Start-with-Codex through WMI: the advanced edition's route at P9.

Codex runs each plugin's MCP server inside a job object with KILL_ON_JOB_CLOSE and no breakaway
(measured, MW), so a watcher the server starts plainly dies when Codex cancels the server, a few
seconds later. Core refuses to start one there (control/codexstart.py). This capability is the
one way out that was measured to work: a process inside such a job asks WMI Win32_Process.Create
to start the watcher, whose parent becomes WmiPrvSE - outside the job - so closing the job does
not end it. It is decision C9's route, and it departs from C4 ("nothing at start") and F6 (a
process-creation route beyond the listed ones), which is why it is advanced and off until armed.

What is here is the route alone. Core reaches P9 only after every existing refusal, and only
where the job would end the watcher; it asks this capability for a route, builds the command
line itself - from the windowless interpreter and this installation's stable launcher, the same
two pieces `_launch_watcher` uses - and calls `start` with it, once, under the install lock it
re-checks. This code never builds that command line, never sends, never claims, and touches no
setting: it runs one constant PowerShell script through core's `pwsh` (values in environment
variables, PowerShell by its System32 path) that calls Win32_Process.Create with ShowWindow = 0,
and reads back the created watcher's pid. Every process in the chain is windowless: `pwsh` runs
under CREATE_NO_WINDOW, the create carries ShowWindow = 0, and the launcher is pythonw.exe.

The live proof - that the created watcher shows the same pid, stands outside any job and is at
Medium integrity after Codex closes - is measurement MW (measure.py), which the owner runs by
hand on a real machine. Nothing here runs in a test: the tests give the capability a fake `pwsh`
runner, so no test starts a real process or reaches WMI.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

# The WMI create, as a constant `pwsh.run` script. The watcher's command line and the path the
# created pid is written to both arrive as environment variables - `pwsh` passes values that way,
# so nothing derived from a path is ever formatted into the script. ShowWindow = 0 keeps the
# created process windowless (the console rules); CreateFlags is never passed, because WMI returns
# 21 when it is. A missing or non-zero ReturnValue becomes a distinct non-zero exit, so the caller
# learns the create failed, and its code, without any output being read.
_WMI_CREATE = r"""
$cmd = $env:CODEX_AUTO_RESUME_ARG_WMI_COMMAND
$pidfile = $env:CODEX_AUTO_RESUME_ARG_WMI_PIDFILE
$startup = New-CimInstance -Namespace root/cimv2 -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
$r = Invoke-CimMethod -Namespace root/cimv2 -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; ProcessStartupInformation = $startup }
if ($null -eq $r) { exit 4 }
if ($r.ReturnValue -ne 0) { exit (100 + [int]$r.ReturnValue) }
[System.IO.File]::WriteAllText($pidfile, [string]$r.ProcessId)
exit 0
"""
_TIMEOUT_SECONDS = 30.0


class StartWithCodex:
    """The start-with-Codex capability's code: a route core carries out at P9.

    `start_route` is the hook. Core asks it only in the job-ends branch, so there is nothing
    left to decide: the capability's whole purpose is to offer the escape, and the hook hands
    core this object as the route. `start` is what core then calls, with the command line it
    built, to run the WMI create and hand back the created watcher's pid or a refusal code."""
    __slots__ = ("paths",)

    def __init__(self, paths):
        self.paths = paths

    def start_route(self, request):
        """P9: the route that starts the watcher outside Codex's job. `request` is core's copy
        of the process context, which this does not read: the decision to escape the job was
        core's, at the point it asks. Handing back this object is naming a route with a
        `start`; core validates that and calls it (domain/plug.Guarded.start_route)."""
        return self

    def start(self, command):
        """Run the WMI create for `command` and report the created pid, or why it failed.

        `command` is the watcher's command line, built by core from the windowless interpreter
        and the stable launcher. Content-free: the return is `{"pid": int}` on success or
        `{"code": <int or word>}` on a refusal - never a path, a name or any output. Never
        raises: a failure of the runner, or a create WMI would not make, is a code."""
        from codex_auto_resume import pwsh
        if pwsh.executable() is None:
            return {"code": "no_powershell"}
        handle, pidfile = tempfile.mkstemp(prefix="car-swc-")
        os.close(handle)
        try:
            code = pwsh.run(_WMI_CREATE, {"WMI_COMMAND": command, "WMI_PIDFILE": pidfile},
                            timeout=_TIMEOUT_SECONDS)
            if code != 0:
                return {"code": code}
            try:
                pid = int(Path(pidfile).read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                return {"code": "no_pid"}
            return {"pid": pid}
        except (OSError, subprocess.SubprocessError, pwsh.PowerShellError) as exc:
            return {"code": type(exc).__name__}
        finally:
            try:
                os.unlink(pidfile)
            except OSError:
                pass


def make(paths) -> StartWithCodex:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return StartWithCodex(paths)

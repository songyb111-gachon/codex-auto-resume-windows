"""The C# host's render mode, asked one case at a time from a test (S6.4, P6-DESIGN 3.4 "drawn" and "window").

`run(case)` writes a one-case job (`car-surface-job/1`, the format tests/test_surface_parity.py and test_surface_windows.py
build), runs the host's render mode on it with CREATE_NO_WINDOW - which loads no DLL, makes no window anybody sees and draws
nothing on the screen - and answers the case's `plan` as the plain JSON the C# wrote. `call(name, ...)` asks a question of
the surfaces' own code the render mode has no case for (HostProbe.cs beside this file answers it). The surfaces are compiled
once into `%TEMP%\\car-surface-host\\<digest of the sources>` (or `CODEX_AR_SURFACE_EXE` names a built host, which has the
render mode's cases only).

Self-contained: stdlib at import.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FORMAT = "car-surface-job/1"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
DRIVER = Path(__file__).resolve().with_name("HostProbe.cs")
GROUPS = ("contract", "surface", "generated")
_EXE = None
CALLS: dict = {}


def sources() -> list:
    """The [contract], [surface] and [generated] files of gui/host.sources in order, then this folder's driver."""
    groups, group = {}, None
    for line in (ROOT / "gui" / "host.sources").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
        else:
            groups.setdefault(group, []).append(ROOT / line)
    return [path for name in GROUPS for path in groups.get(name, [])] + [DRIVER]


def executable() -> Path:
    """The surfaces and the driver compiled once per digest of their sources."""
    global _EXE
    if _EXE is not None:
        return _EXE
    named = os.environ.get("CODEX_AR_SURFACE_EXE")
    if named:
        _EXE = Path(named)
        return _EXE
    files = sources()
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes())
    folder = Path(tempfile.gettempdir()) / "car-surface-host" / digest.hexdigest()[:16]
    exe = folder / "host-probe.exe"
    if not exe.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        building = folder / ("building-%d.exe" % os.getpid())
        done = subprocess.run([str(CSC), "-nologo", "-target:exe", "-platform:x64", "-warnaserror", "-optimize+",
                               "-out:%s" % building, "-r:System.dll", "-r:System.Drawing.dll"] + [str(p) for p in files],
                              capture_output=True, timeout=600, creationflags=NO_WINDOW)
        if done.returncode != 0:
            raise RuntimeError("the surfaces do not compile:\n%s" % done.stdout.decode("utf-8", "replace"))
        os.replace(building, exe)
    _EXE = exe
    return _EXE


def _start(environment: dict):
    environment = dict(os.environ, **environment)
    environment.pop("CODEX_AR_CORE", None)
    environment["CODEX_AUTO_RESUME_CODEX_EXE"] = os.path.join(tempfile.gettempdir(), "car-no-codex", "codex.exe")
    return subprocess.run([str(executable())], env=environment, capture_output=True, timeout=300, creationflags=NO_WINDOW)


def run(case: dict, tables: dict | None = None):
    """The plan the host's render mode makes of `case` (its `surface` and the fields that surface reads)."""
    CALLS[case["surface"]] = CALLS.get(case["surface"], 0) + 1
    with tempfile.TemporaryDirectory(prefix="car-surface-host-") as folder:
        job, out = Path(folder, "job.json"), Path(folder, "out.json")
        job.write_text(json.dumps({"format": FORMAT, "tables": tables or {}, "cases": [dict(case, id="case")]},
                                  ensure_ascii=False), encoding="utf-8")
        ran = _start({"CODEX_AR_RENDER_PLAN": str(job), "CODEX_AR_RENDER_OUT": str(out)})
        if not out.is_file():
            raise RuntimeError("the render mode wrote nothing (exit %d): %s" % (ran.returncode, ran.stdout[-400:]))
        found = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
    if "error" in found:
        raise RuntimeError("the render mode refused the case: %s" % found["error"])
    return found["plan"]


def call(name: str, **fields):
    """One question of the surfaces' own code the render mode has no case for."""
    CALLS[name] = CALLS.get(name, 0) + 1
    with tempfile.TemporaryDirectory(prefix="car-surface-host-") as folder:
        asked, out = Path(folder, "call.json"), Path(folder, "out.json")
        asked.write_text(json.dumps(dict(fields, call=name), ensure_ascii=False), encoding="utf-8")
        ran = _start({"CODEX_AR_HOST_CALL": str(asked), "CODEX_AR_HOST_OUT": str(out)})
        if not out.is_file():
            raise RuntimeError("the host probe wrote nothing (exit %d): %s" % (ran.returncode, ran.stdout[-400:]))
        found = json.loads(out.read_text(encoding="utf-8"))
    if "error" in found:
        raise RuntimeError("the host probe refused %s: %s" % (name, found["error"]))
    return found["ok"]


class Serve:
    """The probe as one process the run shares: `ask(name, **fields)` writes a line and reads the answer's. Ended with the run."""

    def __init__(self):
        self.process = None

    def ask(self, name: str, **fields):
        import atexit
        CALLS[name] = CALLS.get(name, 0) + 1
        if self.process is None:
            environment = dict(os.environ, CODEX_AR_HOST_SERVE="1",
                               CODEX_AUTO_RESUME_CODEX_EXE=os.path.join(tempfile.gettempdir(), "car-no-codex", "codex.exe"))
            environment.pop("CODEX_AR_CORE", None)
            self.process = subprocess.Popen([str(executable())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            env=environment, creationflags=NO_WINDOW)
            atexit.register(self.stop)
        self.process.stdin.write((json.dumps(dict(fields, call=name), ensure_ascii=True) + "\n").encode("utf-8"))
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("the host probe ended")
        found = json.loads(line.decode("utf-8"))
        if "error" in found:
            raise RuntimeError("the host probe refused %s: %s" % (name, found["error"]))
        return found["ok"]

    def stop(self):
        process, self.process = self.process, None
        if process is not None:
            try:
                process.stdin.close()
                process.wait(timeout=20)
            except Exception:
                process.kill()


SERVE = Serve()

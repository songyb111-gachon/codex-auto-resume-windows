r"""Smoke-test an archive's own bytes, without installing anything on this machine.

Run it on a release candidate before tagging, and on the published archive afterwards -
the second is the one that matters, because "the build works" and "what people download
works" are different sentences and only the second is a promise to anybody.

    python build/smoke_archive.py build\dist\CodexAutoResume-v0.6.0-win-x64.zip 0.6.0

It extracts the archive and drives the engine inside it with the interpreter inside it,
against a state directory and a Codex home that exist only for this run. Nothing outside
that directory is touched: no registry value, no Start Menu entry, no watcher started, and
`scripts/plugin_setup.py` - which is what writes the user-wide registrations - is never
run. That is deliberate. A smoke test that repoints the sign-in entry and the notification
handler at a temporary folder, and then deletes the folder, has broken the installation it
was checking.

What it therefore does not prove: that installing works. `Install.cmd`, the installer's
move-aside and journal, the registrations and the watcher handover are what
`docs/LIVE_ACCEPTANCE.md` is for, on a machine somebody is willing to install on.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def run(command, **kwargs):
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300, **kwargs)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def main():
    archive, expected = Path(sys.argv[1]), sys.argv[2]
    workspace = Path(tempfile.mkdtemp(prefix="car-smoke-"))
    failures = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(workspace / "unpacked")
        payload = workspace / "unpacked" / "payload"
        python = payload / "runtime" / "python.exe"
        entry = payload / "app" / "src" / "auto_resume.py"
        home = workspace / "home"
        codex = workspace / "codex"
        codex.mkdir(parents=True)
        environment = dict(os.environ, CODEX_HOME=str(codex), PYTHONPATH=str(payload / "app" / "src"))

        def check(name, ok, detail=""):
            print("%-46s %s" % (name, "ok" if ok else "FAILED"))
            if not ok:
                failures.append("%s: %s" % (name, detail[-600:]))

        check("the bundled interpreter is there", python.is_file())
        code, out = run([str(python), "-c", "import sys;print(sys.version.split()[0])"])
        check("the bundled interpreter runs", code == 0, out)
        bundled_python = out.strip()

        manifest = json.loads((payload / "app" / ".codex-plugin" / "plugin.json")
                              .read_text(encoding="utf-8-sig"))
        check("the manifest declares the expected version", manifest["version"] == expected,
              "manifest says %s" % manifest["version"])

        code, out = run([str(python), str(entry), "--home", str(home), "--quiet", "install"],
                        env=environment)
        check("install into a temporary home", code == 0, out)

        code, out = run([str(python), str(entry), "--home", str(home), "--quiet", "status"],
                        env=environment)
        check("status reads that home", code == 0, out)

        code, again = run([str(python), str(entry), "--home", str(home), "--quiet", "install"],
                          env=environment)
        check("installing twice is not an error", code == 0, again)

        code, out = run([str(python), str(entry), "--home", str(home), "pending"], env=environment)
        check("pending answers", code == 0, out)

        code, out = run([str(python), str(entry), "--home", str(home), "--quiet", "uninstall"],
                        env=environment)
        check("uninstall", code == 0, out)
        code, out = run([str(python), str(entry), "--home", str(home), "--quiet", "uninstall"],
                        env=environment)
        check("uninstalling twice is not an error", code == 0, out)

        window = payload / "CodexAutoResumeSettings.exe"
        launcher = payload / "app" / "mcp" / "codex-auto-resume-mcp.exe"
        check("the window is in the payload root", window.is_file())
        check("the MCP launcher is in the payload", launcher.is_file())

        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        powershell = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        probe = workspace / "version.ps1"
        probe.write_text(
            "$ErrorActionPreference='Stop'\n"
            "foreach ($p in @($env:CAR_WINDOW, $env:CAR_LAUNCHER)) {\n"
            "  $i = [Diagnostics.FileVersionInfo]::GetVersionInfo($p)\n"
            "  Write-Output ($i.FileVersion + '|' + $i.ProductVersion + '|' + $i.ProductName)\n"
            "}\n", encoding="utf-8")
        code, out = run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                         "Bypass", "-File", str(probe)],
                        env=dict(os.environ, CAR_WINDOW=str(window), CAR_LAUNCHER=str(launcher)))
        reported = [line.strip() for line in out.splitlines() if "|" in line]
        check("both executables report the expected version",
              code == 0 and len(reported) == 2
              and all(line.startswith(expected + ".0|" + expected + "|") for line in reported),
              out)

        print()
        print("bundled python : %s" % bundled_python)
        for line in reported:
            print("version resource: %s" % line)
        print("state left behind on this machine: none (%s is removed)" % workspace)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    if failures:
        print()
        for failure in failures:
            print("FAILED " + failure)
        return 1
    print("\nall smoke checks passed")
    return 0


sys.exit(main())

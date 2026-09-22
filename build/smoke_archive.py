r"""Smoke-test an archive's own bytes, without installing anything on this machine.

Run it on a release candidate before tagging, and on the published archive afterwards -
the second is the one that matters, because "the build works" and "what people download
works" are different sentences and only the second is a promise to anybody.

    python build/smoke_archive.py build\dist\CodexAutoResume-v0.6.0-win-x64.zip 0.6.0

It extracts the archive and drives the engine inside it with the interpreter inside it,
against a state directory and a Codex home that exist only for this run. `install` runs
the way a person's does, with notifications on, so it calls the writers of the user-wide
registrations: the notification identity, the Start Menu entry and the handler for the
notification's button - and, given --startup, the sign-in entry. Each of those is a
per-user singleton at a fixed location. Up to v0.6.4 this run wrote them for real:
`install` repointed this machine's Start Menu entry and button handler at the temporary
folder, and `uninstall` then deleted the handler - a smoke test that broke the
installation it was run beside. Now nothing the archive runs can reach them:

* every command goes through a bootstrap (this file, run with ISOLATED by the archive's
  own interpreter) that loads a registry hive private to this run - RegLoadAppKey, a file
  in the workspace, no administrator rights - and remaps HKEY_CURRENT_USER onto it for
  that one process with RegOverridePredefKey. Before a single module of the archive is
  imported it proves the remap: a random marker it has just written into the hive must be
  what HKEY_CURRENT_USER shows, and `Control Panel`, which every real profile has, must
  not be there. When it cannot prove both, the command is refused, never run unprotected;
* the per-user folders - the profile, APPDATA (where the Start Menu entry is written) and
  LOCALAPPDATA - and CODEX_HOME point into the workspace, the bootstrap refuses to run a
  command when one of them does not, and every CODEX_AUTO_RESUME_* variable of the calling
  shell is dropped;
* and the run checks itself: this machine's own registrations are read, read only, before
  and after - after however the run ended, a timeout or an interruption included - and
  any difference fails it.

So the writers still run - against the private hive and folders - and the run inspects
what they wrote: `install` registers the identity, the Start Menu entry and the button's
handler for this home and leaves sign-in autostart alone; `uninstall` removes all three
again. The mechanism lives here, outside the product, on purpose: it protects this machine
from any archive, including one published before it existed, and the product carries no
switch that turns its registrations off.

What it still does not prove: that installing works. `Install.cmd`, the installer's
move-aside and journal, the watcher handover and the registrations in the real hive are
what `docs/LIVE_ACCEPTANCE.md` is for, on a machine somebody is willing to install on.
"""
import contextlib
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

SELF = Path(__file__).resolve()

# The user-wide registrations `install` and `uninstall` write, at their fixed locations
# (codex_auto_resume/startup.py and shortcut.py; tests/test_smoke_archive.py keeps the two
# in step). Spelled out rather than imported: this script checks an archive, and must not
# lean on the code it is checking.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "CodexAutoResume"
AUMID_KEY = r"Software\Classes\AppUserModelId\CodexAutoResume.Watcher"
AUMID_DISPLAY_NAME = "Codex Auto Resume"
PROTOCOL_KEY = r"Software\Classes\codex-auto-resume"
PROTOCOL_COMMAND_KEY = PROTOCOL_KEY + r"\shell\open\command"
START_MENU_ENTRY = Path("Microsoft", "Windows", "Start Menu", "Programs", "Codex Auto Resume.lnk")

# The bootstrap's first argument, and the exit code of a refusal: distinct from every code
# the command line uses, so a refusal is never read as the product failing.
ISOLATED = "--isolated-command"
REFUSED = 86
# Written into the private hive through its own handle, read back through HKEY_CURRENT_USER.
MARKER = "CodexAutoResumeSmokeIsolation"
# In every real user hive, never in the private one: the second, independent proof.
EVERY_PROFILE_HAS = "Control Panel"
# The per-user folders a command may write to. All of them must lie inside the workspace.
REDIRECTED = ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "CODEX_HOME")
HIVE_NAME = "user.dat"
KEY_READ = 0x20019
KEY_ALL_ACCESS = 0xF003F


def run(command, **kwargs):
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300, **kwargs)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


# ------------------------------------------------------------------ the private hive
def _advapi32():
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32")
    advapi.RegLoadAppKeyW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.HKEY),
                                      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    advapi.RegLoadAppKeyW.restype = wintypes.LONG
    advapi.RegOverridePredefKey.argtypes = [wintypes.HKEY, wintypes.HKEY]
    advapi.RegOverridePredefKey.restype = wintypes.LONG
    advapi.RegCloseKey.argtypes = [wintypes.HKEY]
    advapi.RegCloseKey.restype = wintypes.LONG
    return advapi


def load_hive(path, access=KEY_READ) -> int:
    """The root of a registry hive private to the caller, created when the file is missing.

    RegLoadAppKey needs no administrator rights and attaches the hive under no visible
    root: only a holder of the returned handle can reach it.
    """
    from ctypes import wintypes
    root = wintypes.HKEY()
    status = _advapi32().RegLoadAppKeyW(str(path), ctypes.byref(root), access, 0, 0)
    if status or not root.value:
        raise OSError(status, "cannot load the private registry hive")
    return root.value


@contextlib.contextmanager
def private_hive(path):
    """A read-only look into the run's hive, from this process, which is never remapped."""
    from ctypes import wintypes
    root = load_hive(path, KEY_READ)
    try:
        yield root
    finally:
        _advapi32().RegCloseKey(wintypes.HKEY(root))


def registrations(root) -> dict:
    """The user-wide registrations under ``root``, read only; None where a key is absent.

    ``root`` is HKEY_CURRENT_USER for this machine's own, or a private hive's handle.
    """
    import winreg

    def values(path, names):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
                found = {}
                for name in names:
                    try:
                        found[name or "(default)"] = winreg.QueryValueEx(key, name)[0]
                    except FileNotFoundError:
                        pass
                return found
        except FileNotFoundError:
            return None

    return {
        "sign-in autostart": (values(RUN_KEY, [RUN_VALUE]) or {}).get(RUN_VALUE),
        "notification identity": values(AUMID_KEY, ["DisplayName", "IconUri"]),
        "notification button handler": values(PROTOCOL_KEY, ["", "URL Protocol"]),
        "notification button command": (values(PROTOCOL_COMMAND_KEY, [""]) or {}).get("(default)"),
    }


def start_menu_entry(appdata):
    """[size, mtime_ns, sha256] of the Start Menu entry under ``appdata``, or None."""
    path = Path(appdata) / START_MENU_ENTRY
    try:
        data = path.read_bytes()
        stat = path.stat()
    except FileNotFoundError:
        return None
    return [stat.st_size, stat.st_mtime_ns, hashlib.sha256(data).hexdigest()]


def machine_state() -> dict:
    """This machine's own registrations, read only: the run's tripwire."""
    import winreg
    state = registrations(winreg.HKEY_CURRENT_USER)
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    state["Start Menu entry"] = start_menu_entry(appdata)
    return state


def child_environment(workspace, base) -> dict:
    """The environment every command of the archive runs in.

    Every per-user folder the product writes to points into the workspace, and anything
    the calling shell set for Codex Auto Resume itself - a home, an engine path - is left
    behind, so the run is the same on a developer's machine as on a clean runner.
    """
    workspace = Path(workspace)
    kept = {name: value for name, value in base.items()
            if not name.upper().startswith("CODEX_AUTO_RESUME")}
    # No engine directory exists under this LOCALAPPDATA, so no Codex process is ever
    # started - not the machine's own Codex either, whatever it has installed.
    return dict(kept, USERPROFILE=str(workspace / "profile"), APPDATA=str(workspace / "appdata"),
                LOCALAPPDATA=str(workspace / "no-engines"), CODEX_HOME=str(workspace / "codex"))


def archive_command(python, hive, entry, arguments) -> list:
    """The argv of one command of the archive: its own interpreter, through the bootstrap."""
    return [str(python), str(SELF), ISOLATED, str(hive), str(entry)] + [str(a) for a in arguments]


# ------------------------------------------------------------------ the bootstrap
def _canonical(path) -> str:
    # resolve(), not abspath(): TEMP is often spelled in 8.3 form (RUNNER~1 on a CI runner)
    # while the hive's path comes back long, and the two must still compare equal.
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except (OSError, ValueError, RuntimeError):
        return os.path.normcase(os.path.abspath(path))


def _inside(child, parent) -> bool:
    child, parent = _canonical(child), _canonical(parent).rstrip("\\/")
    return child == parent or child.startswith(parent + os.sep)


def _refuse(reason) -> int:
    sys.stderr.write("isolation refused: %s; nothing from the archive was run\n" % reason)
    return REFUSED


def isolated(argv) -> int:
    """Run one command with HKEY_CURRENT_USER remapped onto the private hive, or refuse.

    Runs in the archive's interpreter, as `python smoke_archive.py ISOLATED <hive> <entry>
    [arguments]`. Nothing here writes through HKEY_CURRENT_USER, not even when the remap
    fails: the marker goes in through the hive's own handle, and the proof only reads.
    """
    if len(argv) < 2:
        return _refuse("usage: %s <hive> <entry> [arguments]" % ISOLATED)
    if os.name != "nt":
        return _refuse("the registry remap is Windows-only")
    import runpy
    import uuid
    import winreg
    from ctypes import wintypes
    hive, entry, arguments = Path(argv[0]).resolve(), Path(argv[1]).resolve(), argv[2:]
    workspace = hive.parent
    for name in REDIRECTED:
        value = os.environ.get(name)
        if not value or not _inside(value, workspace):
            return _refuse("%s is not inside %s" % (name, workspace))
    try:
        root = load_hive(hive, KEY_ALL_ACCESS)
    except OSError as exc:
        return _refuse("the private hive could not be loaded (%s)" % exc)
    nonce = uuid.uuid4().hex
    try:
        with winreg.CreateKeyEx(root, MARKER, 0, winreg.KEY_ALL_ACCESS) as key:
            winreg.SetValueEx(key, "nonce", 0, winreg.REG_SZ, nonce)
    except OSError as exc:
        return _refuse("the private hive is not writable (%s)" % exc)
    if _advapi32().RegOverridePredefKey(wintypes.HKEY(winreg.HKEY_CURRENT_USER), wintypes.HKEY(root)):
        return _refuse("HKEY_CURRENT_USER could not be remapped")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MARKER, 0, winreg.KEY_READ) as key:
            seen = winreg.QueryValueEx(key, "nonce")[0]
    except OSError:
        seen = None
    if seen != nonce:
        return _refuse("HKEY_CURRENT_USER does not show the private hive's marker")
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, EVERY_PROFILE_HAS, 0, winreg.KEY_READ).Close()
        return _refuse("HKEY_CURRENT_USER still shows the real profile")
    except FileNotFoundError:
        pass
    except OSError:
        return _refuse("HKEY_CURRENT_USER could not be checked")
    winreg.DeleteKey(root, MARKER)
    # The archive's command, as `python <entry> <arguments>` would run it. This script's
    # directory comes off the path first: the bundled interpreter never puts it there, and
    # the entry point adds its own.
    if sys.path and _canonical(sys.path[0] or os.curdir) == _canonical(SELF.parent):
        del sys.path[0]
    sys.argv = [str(entry)] + list(arguments)
    try:
        runpy.run_path(str(entry), run_name="__main__")
    except SystemExit as exit_:
        code = exit_.code
        if code is None or isinstance(code, int):
            return code or 0
        sys.stderr.write("%s\n" % code)
        return 1
    return 0


# ------------------------------------------------------------------ the smoke run
class Refused(Exception):
    """The bootstrap would not run a command. The run stops; it never goes on unprotected."""


def conclude(before, failures, workspace):
    """Reads this machine's registrations again, removes the workspace and prints the verdict.

    Called from main()'s `finally`, so it speaks however the run ended - a command past its
    time limit, a hive that would not open, an interruption: a change to this machine's
    registrations is never hidden behind a traceback.
    """
    try:
        after = machine_state()
    except Exception as exc:  # the tripwire cannot vouch for anything it could not read
        after = None
        failures.append("this machine's registrations could not be read again after the run, "
                        "so nothing says they are unchanged: %r" % (exc,))
    changed = [] if after is None else sorted(name for name in before
                                              if before[name] != after.get(name))
    for name in changed:
        failures.append("this machine's %s changed during the run: was %s, now %s"
                        % (name, json.dumps(before[name]), json.dumps(after.get(name))))
    shutil.rmtree(workspace, ignore_errors=True)
    print("this machine's registrations: %s" % (
        "CHANGED - see below" if changed else "UNKNOWN - see below" if after is None
        else "unchanged (%s)" % ", ".join(sorted(before))))
    print("state left behind on this machine: %s" % (
        "%s could not be removed completely" % workspace if workspace.exists()
        else "none (%s is removed)" % workspace))
    if failures:
        print()
        for failure in failures:
            print("FAILED " + failure)
    else:
        print("\nall smoke checks passed")
    sys.stdout.flush()


def main():
    archive, expected = Path(sys.argv[1]), sys.argv[2]
    # Read first: when even this fails, nothing has been created or run yet.
    before = machine_state()
    workspace = Path(tempfile.mkdtemp(prefix="car-smoke-"))
    failures = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(workspace / "unpacked")
        payload = workspace / "unpacked" / "payload"
        python = payload / "runtime" / "python.exe"
        entry = payload / "app" / "src" / "auto_resume.py"
        home = workspace / "home"
        hive = workspace / HIVE_NAME
        environment = dict(child_environment(workspace, os.environ),
                           PYTHONPATH=str(payload / "app" / "src"))
        for name in REDIRECTED:
            Path(environment[name]).mkdir(parents=True, exist_ok=True)
        appdata = Path(environment["APPDATA"])

        def check(name, ok, detail=""):
            print("%-64s %s" % (name, "ok" if ok else "FAILED"))
            if not ok:
                failures.append("%s: %s" % (name, detail[-600:]))

        def cli(*arguments):
            code, out = run(archive_command(python, hive, entry, ("--home", home) + arguments),
                            env=environment)
            if code == REFUSED and "isolation refused" in out:
                raise Refused(out.strip())
            return code, out

        def private():
            with private_hive(hive) as root:
                return registrations(root)

        check("the bundled interpreter is there", python.is_file())
        code, out = run([str(python), "-c", "import sys;print(sys.version.split()[0])"])
        check("the bundled interpreter runs", code == 0, out)
        bundled_python = out.strip()

        manifest = json.loads((payload / "app" / ".codex-plugin" / "plugin.json")
                              .read_text(encoding="utf-8-sig"))
        check("the manifest declares the expected version", manifest["version"] == expected,
              "manifest says %s" % manifest["version"])

        # The two files `install` reads from the home, where the installer puts them: the
        # icon is what names the notification identity's owner, and the window is what the
        # Start Menu entry opens.
        home.mkdir(parents=True)
        for name in ("codex-auto-resume.ico", "CodexAutoResumeSettings.exe"):
            if (payload / name).is_file():
                shutil.copyfile(payload / name, home / name)

        code, out = cli("--quiet", "install")
        check("install into a temporary home", code == 0, out)
        seen = private()
        identity = seen["notification identity"] or {}
        command = seen["notification button command"] or ""
        check("install registers the notification identity for it",
              identity.get("DisplayName") == AUMID_DISPLAY_NAME
              and _inside(identity.get("IconUri") or "?", home.resolve()), json.dumps(seen))
        check("install registers the notification button for it",
              os.path.normcase(str(home.resolve())) in os.path.normcase(command), json.dumps(seen))
        check("install writes the Start Menu entry", start_menu_entry(appdata) is not None)
        check("install leaves sign-in autostart alone unasked",
              seen["sign-in autostart"] is None, json.dumps(seen))

        code, out = cli("--quiet", "status")
        check("status reads that home", code == 0, out)

        code, again = cli("--quiet", "install")
        check("installing twice is not an error", code == 0, again)

        code, out = cli("pending")
        check("pending answers", code == 0, out)

        # The Compatibility Registry's bundled baseline, read by the bundled interpreter the
        # way the product reads it. No engine directory exists here, so no Codex process is
        # started: this proves the data shipped and validates, not what any engine is.
        registry = payload / "app" / "src" / "codex_auto_resume" / "data" / "codex_compat.json"
        check("the bundled compatibility data is in the payload", registry.is_file())
        code, out = cli("--quiet", "compat", "--live", "--json")
        try:
            view = json.loads(out[out.index("{"):])
        except ValueError:
            view = {}
        capabilities = view.get("capabilities") or {}
        check("the bundled interpreter accepts the bundled compatibility data",
              code == 0 and (view.get("data") or {}).get("bundled") == "ok", out)
        check("the bundled compatibility data verifies nothing without evidence",
              bool(capabilities) and all(capability.get("state") != "VERIFIED"
                                         for capability in capabilities.values()), out)

        code, out = cli("--quiet", "uninstall")
        check("uninstall", code == 0, out)
        seen = private()
        check("uninstall removes what install registered",
              seen["notification identity"] is None
              and seen["notification button handler"] is None
              and seen["notification button command"] is None
              and start_menu_entry(appdata) is None, json.dumps(seen))
        code, out = cli("--quiet", "uninstall")
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
              and all(line.startswith(expected.split("-")[0] + ".0|" + expected + "|") for line in reported),
              out)

        print()
        print("bundled python : %s" % bundled_python)
        for line in reported:
            print("version resource: %s" % line)
    except Refused as refusal:
        failures.append("a command of the archive could not be isolated, so the run stopped "
                        "before running it unprotected: %s" % refusal)
    except Exception:
        # A command past run()'s time limit, a private hive that will not open, a probe that
        # cannot start: the run stops there, and says so next to the tripwire's verdict.
        failures.append("the run stopped on an unexpected error, before its remaining checks:\n%s"
                        % traceback.format_exc().rstrip())
    except BaseException as interruption:
        failures.append("the run was interrupted (%s) before its remaining checks"
                        % type(interruption).__name__)
        raise
    finally:
        conclude(before, failures, workspace)
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == ISOLATED:
        sys.exit(isolated(sys.argv[2:]))
    sys.exit(main())

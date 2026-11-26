"""The Rust payload's installer (seat S8.2): install, update from v0.6.26, repair, uninstall, purge, and back to v0.6.26.

Each proof runs the installers whole - build/rust_install/install.ps1 as rust_release.py ships it, v0.6.26's own
build/install/install.ps1 from the tag, and the bootstrap's PLAN 6.10 step from scripts/bootstrap.ps1 - on a scratch
home, in Windows PowerShell 5.1 under Set-StrictMode 2.0 as the bootstrap runs an installer, with the real
car-legacy, the real stub core and the real setup program from `rust/target/release` (and `advanced/rust/target/release`
for the advanced edition). What cannot be real yet, or must never be, is stood in:

* the core's answers: the stub core hands every command to tests/install_double.py (CODEX_AUTO_RESUME_TEST_CORE), which
  answers plugin_setup.py's codes and lines, decides ownership with v0.6.26's own config.Paths and startup.belongs_to,
  and registers the Rust programs as PLAN 6.4 says; v0.6.26's engine is the same double in its `engine` role, run by a
  real Python copied into the scratch runtime\\ (PYTHONHOME pointing at this Python's own library);
* the watchers: the double's `watch` role, as runtime\\pythonw.exe <home>\\watcher-launcher.py run (Python) and as
  app\\bin\\CodexAutoResume.exe (a copy of pythonw.exe in place of P6's host), each holding one test-only mutex name;
* the registry: a JSON file the double and the installers' two registry functions (Read-UninstallEntry,
  Remove-UninstallEntry) read and write - never HKCU;
* everything else an installer would reach outside the home: the outside gate (Resolve-OutsideRun), Codex
  (Get-CodexCli, Invoke-Codex: recorded, answered), v0.6.26's precompile, and the install lock's name
  (`Local\\CodexAutoResume.Install` -> a test-only name). The profile, LOCALAPPDATA, APPDATA, TEMP and CODEX_HOME are
  folders of the scratch; the windows are stand-ins (car-legacy's pythonw.exe, which ends at once with no window).

Nothing here shows a window, touches the real install, its registry values or its watcher, or reaches the network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)
_TESTS = str(ROOT / "tests")
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import install_double  # noqa: E402
import released  # noqa: E402
import rust_release  # noqa: E402

REFERENCE = "v0.6.26"
VERSION = "0.6.27-alpha"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RELEASE = {"standard": ROOT / "rust" / "target" / "release", "advanced": ROOT / "advanced" / "rust" / "target" / "release"}
DOUBLE = ROOT / "tests" / "install_double.py"
# car-platform's probe (a dev-only example, never shipped): the Rust watcher's object names, by car-platform's own rule.
PROBE = RELEASE["standard"] / "examples" / "probe.exe"
BASE = Path(sys.base_prefix)
PYTHON_FILES = ("python.exe", "pythonw.exe", "python3.dll", "python%d%d.dll" % sys.version_info[:2], "vcruntime140.dll",
                "vcruntime140_1.dll")
ENTRY = {"standard": "CodexAutoResume", "advanced": "CodexAutoResumeAdvanced"}
INSTALL_LOCK = "'Local\\CodexAutoResume.Install'"

# The installers' reach outside the home, stood in (see the module's docstring). Functions with no param block take
# whatever they are called with.
STAND_INS = {
    "Resolve-OutsideRun": "function Resolve-OutsideRun { return $null }\n",
    "Get-CodexCli": "function Get-CodexCli { return 'C:\\car-double\\codex.exe' }\n",
    "Invoke-Codex": r"""function Invoke-Codex {
    param([string]$Exe, [string[]]$Arguments)
    $said = (@($Arguments) -join ' ')
    Add-Content -LiteralPath $env:CAR_DOUBLE_CODEX_LOG -Value $said -Encoding UTF8
    $app = Join-Path $env:CODEX_AUTO_RESUME_PLUGIN_HOME 'app'
    $out = ''
    if ($said -ceq 'plugin list --json') {
        $out = ConvertTo-Json -Compress -Depth 6 @{ installed = @(@{ name = 'codex-auto-resume'; marketplaceName = 'codex-auto-resume-windows'; source = @{ path = $app } }) }
    } elseif ($said -ceq 'plugin marketplace list --json') {
        $out = ConvertTo-Json -Compress -Depth 6 @{ marketplaces = @(@{ name = 'codex-auto-resume-windows'; root = $app }) }
    }
    return @{ Code = 0; Out = $out; Err = '' }
}
""",
    "Read-UninstallEntry": r"""function Read-UninstallEntry {
    param([string]$Name)
    if (-not (Test-Path -LiteralPath $env:CAR_DOUBLE_REGISTRY)) { return $null }
    $registry = [IO.File]::ReadAllText($env:CAR_DOUBLE_REGISTRY) | ConvertFrom-Json
    $entry = $registry.entries.PSObject.Properties[$Name]
    if ($null -eq $entry) { return $null }
    return @{ InstallLocation = [string]$entry.Value.InstallLocation; UninstallString = [string]$entry.Value.UninstallString }
}
""",
    "Remove-UninstallEntry": r"""function Remove-UninstallEntry {
    param([string]$Name)
    $registry = [IO.File]::ReadAllText($env:CAR_DOUBLE_REGISTRY) | ConvertFrom-Json
    $registry.entries.PSObject.Properties.Remove($Name)
    [IO.File]::WriteAllText($env:CAR_DOUBLE_REGISTRY, (ConvertTo-Json -Depth 6 $registry), (New-Object System.Text.UTF8Encoding $false))
}
""",
    "Invoke-Precompile": "function Invoke-Precompile { }\n",
}


def compose(text: str, lock: str) -> str:
    """An installer's text with STAND_INS in place of those of its functions it has, and the install lock renamed."""
    text = text.replace("\r\n", "\n")
    for name, body in STAND_INS.items():
        pattern = re.compile(r"^function %s \{\n.*?^\}\n" % re.escape(name), re.M | re.S)
        text, count = pattern.subn(lambda _: body, text, count=1)
        if count == 0 and name != "Invoke-Precompile":
            raise AssertionError("the installer has no function %s to stand in for" % name)
    if text.count(INSTALL_LOCK) != 1:
        raise AssertionError("the installer names the install lock %d times" % text.count(INSTALL_LOCK))
    return text.replace(INSTALL_LOCK, "'" + lock + "'").replace("\n", "\r\n")


def function_text(text: str, name: str) -> str:
    found = re.search(r"^function %s \{.*?^\}\r?$" % re.escape(name), text, re.M | re.S)
    if found is None:
        raise AssertionError("no function %s" % name)
    return found.group(0)


def missing_build() -> str | None:
    for edition, folder in RELEASE.items():
        names = ["codex-auto-resume.exe", "codex-auto-resume-setup.exe", "car_core.dll"]
        if edition == "standard":
            names += ["python.exe", "pythonw.exe"]
        for name in names:
            if not (folder / name).is_file():
                return "not built: %s (cargo build --release in both workspaces)" % (folder / name)
    if not PROBE.is_file():
        return "not built: %s (cargo build --release --locked -p car-platform --example probe in rust/)" % PROBE
    for name in PYTHON_FILES:
        if not (BASE / name).is_file():
            return "this Python has no %s to copy into a scratch runtime" % name
    if not POWERSHELL.is_file():
        return "no Windows PowerShell"
    return None


def copy_python(folder: Path, host: bool = False) -> None:
    """This Python's interpreter files into `folder` (a scratch runtime\\), or as P6's host stand-in."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in PYTHON_FILES:
        if host and name == "python.exe":
            continue
        target = folder / ("CodexAutoResume.exe" if host and name == "pythonw.exe" else name)
        shutil.copyfile(BASE / name, target)


def window(tag: bytes) -> bytes:
    """A window stand-in: car-legacy's pythonw.exe, a Windows program that ends at once and shows nothing, marked."""
    return (RELEASE["standard"] / "pythonw.exe").read_bytes() + b"\0stand-in window " + tag


class Scratch:
    """One scratch PC: a profile with the home in it, the other folders, the registry stand-in, test-only names."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.profile = folder / "profile"
        self.home = self.profile / ".codex-auto-resume"
        for name in ("profile", "local", "temp", "codex"):
            (folder / name).mkdir(parents=True, exist_ok=True)
        self.registry = folder / "registry.json"
        self.log = folder / "double.log"
        self.codex_log = folder / "codex.log"
        tag = uuid.uuid4().hex[:12]
        self.names = "Local\\car-double-" + tag
        self.lock = "Local\\car-double-" + tag + "-Install"
        self.reference = released.package(REFERENCE)

    def env(self, **extra) -> dict:
        environment = {name: value for name, value in os.environ.items()
                       if not name.upper().startswith(("PYTHON", "CODEX_", "CAR_DOUBLE"))}
        environment.update({
            "USERPROFILE": str(self.profile), "LOCALAPPDATA": str(self.folder / "local"),
            "APPDATA": str(self.folder / "local"), "TEMP": str(self.folder / "temp"), "TMP": str(self.folder / "temp"),
            "CODEX_HOME": str(self.folder / "codex"), "CODEX_AUTO_RESUME_PLUGIN_HOME": str(self.home),
            "PYTHONHOME": str(BASE), "PYTHONDONTWRITEBYTECODE": "1", "CAR_NO_POWER_ACTION": "1",
            "CODEX_AUTO_RESUME_TEST_CORE": sys.executable, "CODEX_AUTO_RESUME_TEST_CORE_SCRIPT": str(DOUBLE),
            "CAR_DOUBLE_SCRATCH": str(self.folder), "CAR_DOUBLE_REGISTRY": str(self.registry),
            "CAR_DOUBLE_NAMES": self.names, "CAR_DOUBLE_REFERENCE": str(self.reference),
            "CAR_DOUBLE_LOG": str(self.log), "CAR_DOUBLE_CODEX_LOG": str(self.codex_log),
            "CAR_DOUBLE_LIFETIME": "900", "CAR_DOUBLE_PROBE": str(PROBE)})
        environment.update(extra)
        return environment

    def powershell(self, command: str, **extra) -> subprocess.CompletedProcess:
        return subprocess.run([str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", command], cwd=str(self.folder), env=self.env(**extra), capture_output=True,
                              encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW,
                              stdin=subprocess.DEVNULL)

    def install(self, stage: Path, *switches: str, **extra) -> subprocess.CompletedProcess:
        """The stage's install\\install.ps1, under Set-StrictMode 2.0 as the bootstrap runs it."""
        script = str(stage / "install" / "install.ps1").replace("'", "''")
        return self.powershell("Set-StrictMode -Version 2.0; & '%s' %s; exit $LASTEXITCODE"
                               % (script, " ".join(switches)), **extra)

    def records(self) -> list:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def calls(self, role: str) -> list:
        return [" ".join(record["words"]) for record in self.records()
                if record["role"] == role and "started" not in record]

    def watches(self) -> list:
        return [record for record in self.records() if record["role"] == "watch"]

    def object_names(self) -> dict:
        """Both watchers' mutex and stop event for this home, each by its own rule (the double's `--role names`):
        {"python": [mutex, stop], "rust": [mutex, stop]}."""
        if not hasattr(self, "_object_names"):
            done = subprocess.run([sys.executable, str(DOUBLE), "--role", "names"], env=self.env(),
                                  cwd=str(self.folder), capture_output=True, encoding="utf-8", timeout=120,
                                  creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
            if done.returncode != 0:
                raise AssertionError("the double could not name the objects: %s" % done.stderr)
            self._object_names = json.loads(done.stdout)
        return self._object_names

    def mutex(self) -> str:
        return self.object_names()["python"][0]

    def running(self) -> bool:
        return install_double.held(self.mutex())

    def running_as(self) -> str | None:
        """The flavour of the watcher that runs now, by the last start no stop followed."""
        state = {}
        for record in self.watches():
            state[record["pid"]] = record
        alive = [record for record in state.values() if record["outcome"] == "started"]
        return alive[-1]["flavour"] if alive and self.running() else None

    def registered(self) -> dict:
        return json.loads(self.registry.read_text(encoding="utf-8-sig")) if self.registry.is_file() else {}

    def stop(self) -> None:
        install_double.signal_stop(self.object_names()["python"][1])
        for _ in range(150):
            if not self.running():
                break
            time.sleep(0.2)
        # And each watcher this scratch started has ended, not only let go of the mutex: a process on its way out
        # still holds its program's files, which the scratch folder's removal needs.
        for record in self.watches():
            if record["outcome"] == "started":
                install_double.wait_ended(record["pid"], 10)

    def snapshot(self) -> dict:
        found = {}
        for folder in ("config", "logs", "accounts"):
            base = self.home / folder
            for path in sorted(base.rglob("*")) if base.is_dir() else []:
                if path.is_file():
                    found[path.relative_to(self.home).as_posix()] = path.read_bytes()
        return found


def rust_stage(folder: Path, edition: str, lock: str) -> Path:
    """The Rust archive as rust_release.py stages it from the cargo build, with P6's host stand-in added to app\\bin and
    the installer's reach outside the home stood in."""
    work = folder / ("rust-in-" + edition)
    work.mkdir(parents=True, exist_ok=True)
    (work / "window.exe").write_bytes(window(b"rust " + edition.encode()))
    shutil.copyfile(RELEASE["standard"] / "python.exe", work / "launcher.exe")
    stage = rust_release.stage_edition(folder / ("rust-" + edition), edition, VERSION, bins=RELEASE[edition],
                                       legacy=RELEASE["standard"], window=work / "window.exe",
                                       launcher=work / "launcher.exe", host=RELEASE["standard"] / "pythonw.exe")
    copy_python(stage / "payload" / "app" / "bin", host=True)
    installer = stage / "install" / "install.ps1"
    installer.write_bytes(compose(installer.read_bytes().decode("utf-8"), lock).encode("utf-8"))
    return stage


def python_stage(folder: Path, edition: str, lock: str) -> Path:
    """A v0.6.26-shaped archive: the tag's own install.ps1, a real Python as its runtime, and its engine the double."""
    stage = folder / ("python-" + edition)
    app = stage / "payload" / "app"
    (app / ".codex-plugin").mkdir(parents=True)
    (app / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "codex-auto-resume", "version": "0.6.26"}),
                                                       encoding="utf-8")
    (app / "src" / "codex_auto_resume").mkdir(parents=True)
    (app / "src" / "codex_auto_resume" / "__init__.py").write_text("# v0.6.26\n", encoding="utf-8")
    if edition == "advanced":
        (app / "src" / "codex_auto_resume_advanced").mkdir(parents=True)
        (app / "src" / "codex_auto_resume_advanced" / "__init__.py").write_text("# ADVANCED-EDITION-CODE\n",
                                                                                encoding="utf-8")
    install_double.shim(app / "scripts" / "plugin_setup.py", "engine")
    copy_python(stage / "payload" / "runtime")
    (stage / "payload" / "CodexAutoResumeSettings.exe").write_bytes(window(b"v0.6.26 " + edition.encode()))
    (stage / "payload" / "codex-auto-resume.ico").write_bytes(b"v0.6.26 icon")
    reference = subprocess.run(["git", "-C", str(ROOT), "show", REFERENCE + ":build/install/install.ps1"],
                               capture_output=True, check=True, creationflags=NO_WINDOW).stdout.decode("utf-8")
    (stage / "install").mkdir()
    (stage / "install" / "install.ps1").write_bytes(compose(reference, lock).encode("utf-8"))
    return stage


def write_store(path: Path, schema: int, *statements: str) -> None:
    """A database at `schema`, closed again: an open one would hold the file the uninstall's purge removes."""
    store = sqlite3.connect(path)
    try:
        for statement in statements:
            store.execute(statement)
        store.execute("PRAGMA user_version = %d" % schema)
        store.commit()
    finally:
        store.close()


def add_state(scratch: Scratch, edition: str) -> None:
    """What a person's installation holds: settings, a schema-5 state with a pending row, logs; advanced: its state
    (schema 9), a saved account and a chosen Python (D8)."""
    config = scratch.home / "config"
    (config / "settings.json").write_text(json.dumps({"interface_language": "ko", "max_retries": 7}), encoding="utf-8")
    write_store(config / "state.sqlite", 5, "CREATE TABLE pending (thread TEXT, reason TEXT)",
                "INSERT INTO pending VALUES ('example-thread', 'usage_limit')")
    (scratch.home / "logs" / "auto-resume.log").write_text("2026-11-25 line kept\n", encoding="utf-8")
    if edition == "advanced":
        (config / "advanced").mkdir(exist_ok=True)
        write_store(config / "advanced" / "advanced.sqlite", 9, "CREATE TABLE armed (name TEXT)")
        (scratch.home / "accounts").mkdir(exist_ok=True)
        (scratch.home / "accounts" / "example.sealed").write_bytes(b"sealed")
        chosen = scratch.home / "runtimes" / "3.13.1"
        chosen.mkdir(parents=True)
        (chosen / "python.exe").write_bytes(b"chosen")
        (scratch.home / "runtimes" / "chosen.json").write_text('{"version": "3.13.1"}', encoding="utf-8")


def belongs(value: str, home: Path) -> bool:
    """v0.6.26's own startup.belongs_to, in a process of its own."""
    return released.run(REFERENCE, "import json, sys\nfrom pathlib import Path\nfrom codex_auto_resume import startup\n"
                        "print(json.dumps(startup.belongs_to(sys.argv[1], Path(sys.argv[2]))))", value, str(home))


SKIP = missing_build() if sys.platform == "win32" else "the installers are Windows PowerShell"


@unittest.skipIf(SKIP, SKIP or "")
class InstallerProofs(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="car-rust-install-")
        self.scratch = Scratch(Path(self.work.name))
        self.addCleanup(self.work.cleanup)
        self.addCleanup(self.scratch.stop)

    def said(self, done: subprocess.CompletedProcess) -> str:
        return "exit %s\n--- stdout\n%s\n--- stderr\n%s\n--- double\n%s" % (
            done.returncode, done.stdout[-6000:], done.stderr[-3000:],
            "\n".join(json.dumps(record) for record in self.scratch.records()[-30:]))

    def v0626_installed(self, edition: str) -> Path:
        """v0.6.26 installed by its own installer into the empty scratch home, with a person's state added."""
        stage = python_stage(self.scratch.folder, edition, self.scratch.lock)
        done = self.scratch.install(stage, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertIn("Installed and running.", done.stdout)
        self.assertEqual(self.scratch.running_as(), "python", self.said(done))
        add_state(self.scratch, edition)
        return stage

    def assert_rust_installed(self, edition: str, stage: Path) -> None:
        home = self.scratch.home
        self.assertTrue((home / "app" / "bin" / "codex-auto-resume.exe").is_file())
        self.assertFalse((home / "app" / "src" / "codex_auto_resume" / "__init__.py").exists())
        self.assertEqual(sorted(path.name for path in (home / "runtime").iterdir()), ["python.exe", "pythonw.exe"])
        self.assertEqual((home / "runtime" / "python.exe").read_bytes(), (RELEASE["standard"] / "python.exe").read_bytes())
        self.assertEqual((home / "app" / "scripts" / "plugin_setup.py").read_bytes(),
                         (stage / "payload" / "app" / "scripts" / "plugin_setup.py").read_bytes())
        self.assertEqual((home / "uninstall" / "install.ps1").read_bytes(), (stage / "install" / "install.ps1").read_bytes())
        self.assertEqual((home / "app" / "src" / "codex_auto_resume_advanced" / "__init__.py").is_file(),
                         edition == "advanced")
        leftovers = [path.name for path in home.iterdir() if ".old-" in path.name or path.name.endswith(".migrating")
                     or path.name.endswith("-install-journal.json")]
        self.assertEqual(leftovers, [])
        self.assertFalse((home / "runtimes").exists(), "D8: the chosen Pythons go")
        registry = self.scratch.registered()
        # Every word quoted, as v0.6.26's startup.quote_argument writes a Run value, with the home as v0.6.26's
        # plugin_setup.runtime_home and the core's setup spell it: Path.resolve()'s, so a TEMP given in 8.3 form
        # (a CI runner's) is written long.
        spelled = home.resolve()
        host = '"%s" "--home" "%s" "run"' % (spelled / "app" / "bin" / "CodexAutoResume.exe", spelled)
        self.assertEqual(registry["run"], host)
        self.assertEqual(registry["protocol"], '"%s" "--home" "%s" "activate" "%%1"'
                         % (spelled / "app" / "bin" / "codex-auto-resume.exe", spelled))
        self.assertIn(ENTRY[edition], registry["entries"])
        self.assertEqual(self.scratch.running_as(), "rust")

    def round_trip(self, edition: str) -> None:
        python = self.v0626_installed(edition)
        kept = self.scratch.snapshot()
        rust = rust_stage(self.scratch.folder, edition, self.scratch.lock)

        # The update from v0.6.26 (PLAN 6.2-6.5).
        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertIn("edition: " + edition, done.stdout)
        self.assertIn("Updated. Your settings and pending recoveries were kept.", done.stdout)
        self.assertIn("[ok] The previous watcher stopped", done.stdout)
        self.assertIn("[ok] The Python runtime of the version this replaced was removed", done.stdout)
        self.assertIn("stop", self.scratch.calls("engine"), "the Python version's own engine stops its watcher")
        self.assertIn("setup --keep-state", self.scratch.calls("core"))
        flavours = [(record["flavour"], record["outcome"]) for record in self.scratch.watches()]
        self.assertEqual(flavours, [("python", "started"), ("python", "stopped"), ("rust", "started")])
        self.assertTrue(self.scratch.watches()[-1]["executable"].lower().endswith(r"app\bin\codexautoresume.exe"))
        self.assert_rust_installed(edition, rust)
        self.assertEqual(self.scratch.snapshot(), kept, "D13: state and settings carried unchanged")
        self.assertTrue(belongs(self.scratch.registered()["run"], self.scratch.home),
                        "v0.6.26 knows the Rust Run value as this installation's")

        # Repair: this version over itself.
        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertIn("Repaired. Your settings and pending recoveries were kept.", done.stdout)
        self.assertEqual(self.scratch.calls("core").count("stop"), 1, "the host is found by its image and stopped")
        self.assertEqual([record["flavour"] for record in self.scratch.watches()][-2:], ["rust", "rust"])
        self.assert_rust_installed(edition, rust)
        self.assertEqual(self.scratch.snapshot(), kept)

        # Back to v0.6.26 (PLAN 6.10): the bootstrap's step stops the Rust watcher, then v0.6.26's own installer runs.
        bootstrap = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        step = self.scratch.powershell(
            "$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version 2.0\n"
            + function_text(bootstrap, "Stop-WatcherBeforeOlder") + "\n"
            + "Stop-WatcherBeforeOlder -Home_ '%s' -Unpacked '%s'\n" % (self.scratch.home, python))
        self.assertEqual(step.stdout.strip().splitlines()[-1:], ["stopped"], self.said(step))
        self.assertFalse(self.scratch.running())
        self.assertIn("stop", self.scratch.calls("core"))
        done = self.scratch.install(python, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertIn("Updated. Your settings and pending recoveries were kept.", done.stdout)
        home = self.scratch.home
        self.assertTrue((home / "app" / "src" / "codex_auto_resume" / "__init__.py").is_file())
        self.assertFalse((home / "app" / "bin").exists())
        self.assertEqual((home / "runtime" / "python.exe").read_bytes(), (BASE / "python.exe").read_bytes())
        self.assertEqual(self.scratch.running_as(), "python", self.said(done))
        registry = self.scratch.registered()
        self.assertIn("watcher-launcher.py", registry["run"])
        self.assertIn(r"runtime\pythonw.exe", registry["run"])
        self.assertIn("watcher-launcher.py", registry["protocol"])
        self.assertIn(ENTRY[edition], registry["entries"])
        self.assertEqual(self.scratch.snapshot(), kept, "nothing of the person's is lost on the way back")

    def test_both_watchers_name_their_objects_by_their_own_rules_and_the_names_agree(self):
        """PLAN 6.2's handover (review 9, S5): the Python watcher's mutex and stop event by the tag's win/sync.py, the
        Rust one's by car-platform's names, each made test-only by the prefix alone - the same two names, so the two
        watchers exclude each other. Every handover proof below rests on this."""
        names = self.scratch.object_names()
        self.assertEqual(names["python"], names["rust"])
        self.assertEqual(len(set(names["python"])), 2)
        for name in names["python"]:
            self.assertTrue(name.startswith(self.scratch.names + "-"), name)
            self.assertRegex(name[len(self.scratch.names):], r"^-(stop-)?[0-9a-f]{64}$")

    def test_the_standard_edition_updates_from_v0626_repairs_and_goes_back(self):
        self.round_trip("standard")

    def test_the_advanced_edition_updates_from_v0626_repairs_and_goes_back(self):
        self.round_trip("advanced")

    def test_a_migration_whose_setup_fails_puts_the_python_version_back(self):
        python = self.v0626_installed("standard")
        kept = self.scratch.snapshot()
        before = {name: (self.scratch.home / name).read_bytes()
                  for name in ("CodexAutoResumeSettings.exe", "codex-auto-resume.ico", "uninstall/install.ps1")}
        rust = rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent", CAR_DOUBLE_FAIL="core:setup")
        self.assertEqual(done.returncode, 1, self.said(done))
        self.assertIn("[ok] The Python version that was installed here was put back as it was", done.stdout)
        self.assertIn("[ok] Its watcher was started again", done.stdout)
        self.assertIn("Nothing was changed: the version that was installed is installed again.", done.stdout)
        home = self.scratch.home
        self.assertTrue((home / "app" / "src" / "codex_auto_resume" / "__init__.py").is_file())
        self.assertFalse((home / "app" / "bin").exists())
        self.assertEqual((home / "runtime" / "python.exe").read_bytes(), (BASE / "python.exe").read_bytes())
        for name, data in before.items():
            self.assertEqual((home / name).read_bytes(), data, name)
        self.assertEqual([path.name for path in home.iterdir() if ".old-" in path.name or "migrating" in path.name
                          or "journal" in path.name], [])
        self.assertEqual(self.scratch.running_as(), "python")
        self.assertEqual(self.scratch.calls("engine")[-1], "setup --keep-state")
        self.assertIn("watcher-launcher.py", self.scratch.registered()["run"])
        self.assertEqual(self.scratch.snapshot(), kept)
        del python

    def test_another_edition_is_refused_with_14_and_nothing_changes(self):
        self.v0626_installed("standard")
        kept = self.scratch.snapshot()
        rust = rust_stage(self.scratch.folder, "advanced", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 14, self.said(done))
        self.assertIn("An edition is changed only when that is asked for, so nothing was changed.", done.stdout)
        self.assertTrue((self.scratch.home / "app" / "src" / "codex_auto_resume" / "__init__.py").is_file())
        self.assertEqual(self.scratch.running_as(), "python")
        self.assertEqual(self.scratch.snapshot(), kept)

    def test_the_setup_program_installs_what_it_is_handed_and_refuses_another_edition(self):
        self.v0626_installed("standard")
        kept = self.scratch.snapshot()
        rust = rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        setup = rust / "payload" / "app" / "bin" / "codex-auto-resume-setup.exe"
        self.assertEqual(rust_release.subsystem(setup.read_bytes()), 2)

        def run(*words):
            return subprocess.run([str(setup)] + list(words), cwd=str(setup.parent), env=self.scratch.env(),
                                  timeout=600, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                                  capture_output=True).returncode

        self.assertEqual(run("-Handover", "update", "-Edition", "advanced"), 14)
        self.assertEqual(run("-Edition", "standard"), 2)
        self.assertEqual(self.scratch.running_as(), "python", "nothing was run")
        self.assertEqual(run("-Handover", "update", "-Edition", "standard"), 0)
        log = (self.scratch.folder / "temp" / "CodexAutoResume-Setup.log").read_text(encoding="utf-8")
        self.assertIn("Updated. Your settings and pending recoveries were kept.", log)
        self.assertIn("The installer ended with code 0.", log)
        self.assert_rust_installed("standard", rust)
        self.assertEqual(self.scratch.snapshot(), kept)

    def test_an_uninstall_keeps_the_data_and_a_purge_takes_it(self):
        rust = rust_stage(self.scratch.folder, "standard", self.scratch.lock)
        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertIn("Installed and running.", done.stdout)
        self.assertEqual(self.scratch.calls("core")[:2], ["claim-home", "setup"])
        self.assertEqual(self.scratch.running_as(), "rust")
        add_state(self.scratch, "standard")
        kept = self.scratch.snapshot()

        done = self.scratch.install(rust, "-Uninstall", "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertIn("Removed. Settings and pending recoveries were kept.", done.stdout)
        self.assertIn("uninstall", self.scratch.calls("core"))
        self.assertFalse(self.scratch.running())
        for name in ("app", "runtime", "uninstall", "CodexAutoResumeSettings.exe"):
            self.assertFalse((self.scratch.home / name).exists(), name)
        self.assertEqual(self.scratch.snapshot(), kept)
        registry = self.scratch.registered()
        self.assertEqual((registry["run"], registry["protocol"], registry["entries"]), (None, None, {}))
        codex = self.scratch.codex_log.read_text(encoding="utf-8-sig")
        self.assertIn("plugin remove codex-auto-resume@codex-auto-resume-windows", codex)

        done = self.scratch.install(rust, "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertEqual(self.scratch.snapshot(), kept, "the reinstall picks the kept data up again")
        done = self.scratch.install(rust, "-Uninstall", "-Purge", "-Silent")
        self.assertEqual(done.returncode, 0, self.said(done))
        self.assertIn("Removed, including settings and recovery history.", done.stdout)
        self.assertFalse(self.scratch.home.exists())


@unittest.skipUnless(sys.platform == "win32", "v0.6.26's startup is Windows'")
class RunValueContractTests(unittest.TestCase):
    """PLAN 6.4 as the downgrade needs it: v0.6.26's `setup --keep-state` re-registers the start at sign-in only where
    startup.belongs_to knows the value as this installation's, so the Rust Run value carries `--home <home>`. Without
    it, going back to v0.6.26 would leave the start at sign-in on a host that is gone."""

    def test_v0626_knows_the_rust_run_value_only_with_its_home(self):
        home = Path(r"C:\Users\ExampleUser\.codex-auto-resume")
        host = home / "app" / "bin" / "CodexAutoResume.exe"
        self.assertTrue(belongs('"%s" --home "%s" run' % (host, home), home))
        self.assertTrue(belongs('"%s" "--home" "%s" "run"' % (host, home), home))
        self.assertFalse(belongs('"%s" run' % host, home))
        self.assertFalse(belongs('"%s"' % host, home))
        self.assertFalse(belongs('"%s" --home "%s" run' % (host, home.parent / "other"), home))


class InstallerShapeTests(unittest.TestCase):
    """The Rust installer is v0.6.26's, function by function, but for what S8.2 changed: nothing of v0.6.26's is lost
    unseen, and nothing Python is left in it."""

    @classmethod
    def setUpClass(cls):
        cls.rust = rust_release.INSTALLER.read_bytes().decode("utf-8").replace("\r\n", "\n")
        shown = subprocess.run(["git", "-C", str(ROOT), "show", REFERENCE + ":build/install/install.ps1"],
                               capture_output=True, creationflags=NO_WINDOW)
        if shown.returncode != 0:
            raise unittest.SkipTest("%s is not in this checkout" % REFERENCE)
        cls.reference = shown.stdout.decode("utf-8").replace("\r\n", "\n")

    @staticmethod
    def functions(text: str) -> dict:
        return {match.group(1): match.group(0) for match in
                re.finditer(r"^function ([A-Za-z-]+) \{.*?^\}$", text, re.M | re.S)}

    def test_every_function_of_v0626_is_kept_but_the_compile(self):
        ours, theirs = self.functions(self.rust), self.functions(self.reference)
        self.assertEqual(set(theirs) - set(ours), {"Get-ChosenPython", "Get-CompilePythons", "Invoke-Precompile"})
        self.assertEqual(set(ours) - set(theirs),
                         {"Invoke-InstalledEngine", "Save-MigratedFile", "Undo-Migration", "Complete-Migration",
                          "Test-KnowsWatcherWasStopped", "Wait-WatcherEnded", "Resolve-MigratingCopies"})
        changed = {name for name in theirs if name in ours and ours[name] != theirs[name]}
        self.assertEqual(changed, {"Get-CodexCli", "Get-OwnedWatcherProcess", "Invoke-Setup", "Start-StoppedWatcher"})

    def test_the_outside_gate_is_v0626s_byte_for_byte(self):
        def gate(text):
            return text[text.index("# >>> the outside gate"):text.index("# <<< the outside gate")]
        self.assertEqual(gate(self.rust), gate(self.reference))

    def test_only_the_installed_engine_of_a_python_version_is_run_as_python(self):
        engine = self.functions(self.rust)["Invoke-InstalledEngine"]
        rest = self.rust.replace(engine, "")
        self.assertNotIn("& $Python", rest)
        self.assertNotIn("disable-remote-debug $setup", rest)
        self.assertIn("& $Core @Arguments", self.functions(self.rust)["Invoke-Setup"])
        self.assertIn("& $PayloadCore 'claim-home'", self.rust)
        self.assertIn("& $verifier 'verify-home'", self.rust)


if __name__ == "__main__":
    unittest.main()

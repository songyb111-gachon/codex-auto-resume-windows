"""build/smoke_archive.py cannot reach this machine's user-wide registrations.

Up to v0.6.4 the archive smoke test ran `install` and `uninstall` against the real current
user: with notifications on, `install` writes the notification identity, the Start Menu
entry and the handler for the notification's button, all per-user singletons at fixed
locations, and the run repointed them at a temporary folder and then deleted the handler.
Now every command of the archive runs through a bootstrap that remaps HKEY_CURRENT_USER
onto a registry hive private to the run and refuses to run anything when it cannot prove
the remap, with every per-user folder inside the workspace.

These tests hold it to that. The product's writers are called here for real, but only
under the bootstrap, and only after a second check of their own that HKEY_CURRENT_USER is
not the real profile; every test that runs one reads this machine's registrations before
and after - read only - and fails on any difference.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT = ROOT / "build" / "smoke_archive.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codex_auto_resume import shortcut, startup  # noqa: E402


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_archive_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()

# Stops before writing anything unless HKEY_CURRENT_USER is not the real profile - checked
# here, independently of the bootstrap's own proof, by reading only.
_GUARD = """\
import json, sys, winreg
from pathlib import Path
try:
    winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Control Panel").Close()
    sys.exit(99)
except FileNotFoundError:
    pass
sys.path.insert(0, %r)
from codex_auto_resume import shortcut, startup
home = Path(sys.argv[1])
""" % str(SRC)

_WRITE = _GUARD + """\
startup.install(startup.command_line(home / "src" / "auto_resume.py", home))
startup.register_aumid(home / "codex-auto-resume.ico")
startup.install_protocol(startup.protocol_command_line(home / "src" / "auto_resume.py", home))
shortcut.install(target=sys.executable, description="smoke isolation test")
print(json.dumps({"start menu entry": str(shortcut.shortcut_path())}))
"""

_REMOVE = _GUARD + """\
print(json.dumps([startup.uninstall(), startup.unregister_aumid(),
                  startup.uninstall_protocol(), shortcut.uninstall()]))
"""

_FLAG = """\
import sys
from pathlib import Path
Path(sys.argv[1]).write_text("ran", encoding="utf-8")
"""

# The bootstrap with a fault put into its own process first: the script is loaded as
# `smoke`, the fault is applied, and then isolated() runs as `ISOLATED` would run it. The
# faults below only ever make the bootstrap see less than it should; the entry run behind
# them is _FLAG, which writes one file in the workspace and nothing else.
_FAULTED = """\
import importlib.util, sys, winreg
spec = importlib.util.spec_from_file_location("smoke_archive_faulted", %r)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
%s
sys.exit(smoke.isolated(sys.argv[1:]))
"""

# RegOverridePredefKey answers as it is asked to and leaves HKEY_CURRENT_USER alone: the
# failure the proofs exist for - a changed signature, a Windows that ignores the call.
_OVERRIDE_ANSWERS = """\
_real = smoke._advapi32
class _Advapi:
    def __init__(self):
        self.real = _real()
    def __getattr__(self, name):
        return getattr(self.real, name)
    def RegOverridePredefKey(self, key, target):
        return %d
smoke._advapi32 = _Advapi
"""

# On top of a remap that did nothing, the marker proof is fooled into seeing its nonce, so
# only the second proof is left to notice. HKEY_CURRENT_USER is still only read.
_MARKER_FOOLED = """\
_nonces = []
_set, _open, _query = winreg.SetValueEx, winreg.OpenKey, winreg.QueryValueEx
class _Seen:
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def Close(self):
        pass
def _set_value(key, name, reserved, kind, value):
    if name == "nonce":
        _nonces.append(value)
    return _set(key, name, reserved, kind, value)
def _open_key(key, sub_key, *rest, **named):
    if key == winreg.HKEY_CURRENT_USER and sub_key == smoke.MARKER:
        return _Seen()
    return _open(key, sub_key, *rest, **named)
def _query_value(key, name):
    if isinstance(key, _Seen):
        return _nonces[-1], winreg.REG_SZ
    return _query(key, name)
winreg.SetValueEx, winreg.OpenKey, winreg.QueryValueEx = _set_value, _open_key, _query_value
"""

# The profile proof cannot read HKEY_CURRENT_USER at all.
_PROFILE_UNREADABLE = """\
_open = winreg.OpenKey
def _open_key(key, sub_key, *rest, **named):
    if sub_key == smoke.EVERY_PROFILE_HAS:
        raise PermissionError(5, "Access is denied")
    return _open(key, sub_key, *rest, **named)
winreg.OpenKey = _open_key
"""


class ContractTests(unittest.TestCase):
    def test_it_watches_the_registrations_the_product_writes(self):
        self.assertEqual(smoke.RUN_KEY, startup.RUN_KEY)
        self.assertEqual(smoke.RUN_VALUE, startup.VALUE_NAME)
        self.assertEqual(smoke.AUMID_KEY, startup.AUMID_KEY)
        self.assertEqual(smoke.AUMID_DISPLAY_NAME, startup.AUMID_DISPLAY_NAME)
        self.assertEqual(smoke.PROTOCOL_KEY, startup.PROTOCOL_KEY)
        self.assertEqual(smoke.PROTOCOL_COMMAND_KEY, startup.PROTOCOL_COMMAND_KEY)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"APPDATA": temp}):
            self.assertEqual(shortcut.shortcut_path(), Path(temp) / smoke.START_MENU_ENTRY,
                             "the Start Menu entry follows APPDATA, which the run redirects")

    def test_the_child_environment_stays_in_the_workspace(self):
        base = {"PATH": r"C:\Windows", "SystemRoot": r"C:\Windows", "TEMP": r"C:\t",
                "USERPROFILE": r"C:\Users\someone", "APPDATA": r"C:\Users\someone\AppData\Roaming",
                "LOCALAPPDATA": r"C:\Users\someone\AppData\Local", "CODEX_HOME": r"C:\c",
                "CODEX_AUTO_RESUME_HOME": r"C:\Users\someone\.codex-auto-resume",
                "codex_auto_resume_codex_exe": r"C:\codex.exe"}
        with tempfile.TemporaryDirectory() as workspace:
            child = smoke.child_environment(workspace, base)
            for name in smoke.REDIRECTED:
                self.assertTrue(smoke._inside(child[name], workspace), name)
            self.assertFalse([name for name in child if name.upper().startswith("CODEX_AUTO_RESUME")])
            for name in ("PATH", "SystemRoot", "TEMP"):
                self.assertEqual(child[name], base[name])
        self.assertIn("CODEX_AUTO_RESUME_HOME", base, "the caller's mapping is not changed")

    def test_every_command_of_the_archive_goes_through_the_bootstrap(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        main = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "main")
        wrapped = set()
        for node in ast.walk(main):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "archive_command"):
                wrapped.update(id(inner) for inner in ast.walk(node))
        uses = [node for node in ast.walk(main) if isinstance(node, ast.Name)
                and node.id == "entry" and isinstance(node.ctx, ast.Load)]
        self.assertTrue(uses)
        self.assertEqual([node.lineno for node in uses if id(node) not in wrapped], [],
                         "the archive's entry point is run only through archive_command")
        # The one other use of the bundled interpreter asks it for its version, and runs no
        # code of the archive.
        direct = []
        for node in ast.walk(main):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run"
                    and node.args and isinstance(node.args[0], ast.List)):
                first = node.args[0].elts[0] if node.args[0].elts else None
                if isinstance(first, ast.Call) and ast.unparse(first) == "str(python)":
                    direct.append(ast.unparse(node.args[0]))
        self.assertEqual(direct, ["[str(python), '-c', 'import sys;print(sys.version.split()[0])']"])

    def test_the_command_line_starts_with_the_bootstrap(self):
        argv = smoke.archive_command(Path("C:/p/python.exe"), Path("C:/w/user.dat"),
                                     Path("C:/p/app/src/auto_resume.py"), ("--home", Path("C:/w/home"), "install"))
        self.assertEqual(argv[1:3], [str(SCRIPT.resolve()), smoke.ISOLATED])
        self.assertEqual(argv[3:], [str(Path("C:/w/user.dat")), str(Path("C:/p/app/src/auto_resume.py")),
                                    "--home", str(Path("C:/w/home")), "install"])

    def test_the_bootstrap_refuses_without_its_arguments(self):
        with patch.object(sys, "stderr"):
            self.assertEqual(smoke.isolated([]), smoke.REFUSED)
            self.assertEqual(smoke.isolated(["only-a-hive"]), smoke.REFUSED)

    def test_the_product_never_remaps_the_registry(self):
        """The remap belongs to the smoke run alone: the product, the installer and the
        workflows never set it up, so no installation can end up with its registrations
        going somewhere private."""
        found = []
        for tree in ("src", "scripts", "install", "gui", ".github"):
            for path in sorted((ROOT / tree).rglob("*")):
                if not path.is_file() or path.suffix.lower() not in (".py", ".ps1", ".cmd", ".cs", ".yml", ".json"):
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for word in ("RegOverridePredefKey", "RegLoadAppKey", smoke.ISOLATED):
                    if word in text:
                        found.append("%s: %s" % (path.relative_to(ROOT), word))
        self.assertEqual(found, [])


class VerdictTests(unittest.TestCase):
    """However a run ends, it reads this machine's registrations again and says whether
    they changed. Nothing of the archive runs here: `run` and the tripwire's reads are
    stubbed, and the archive is a stand-in holding one empty file."""

    BEFORE = {"sign-in autostart": "was", "Start Menu entry": [1, 2, "a"]}
    CHANGED = {"sign-in autostart": "now", "Start Menu entry": [1, 2, "a"]}

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="car-smoke-verdict-")
        self.addCleanup(temp.cleanup)
        self.archive = Path(temp.name) / "stand-in.zip"
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.writestr("payload/runtime/python.exe", b"")

    def main(self, archive, states, run):
        out = io.StringIO()
        with patch.object(sys, "argv", ["smoke_archive.py", str(archive), "0.0.0"]), \
                patch.object(smoke, "machine_state", side_effect=states), \
                patch.object(smoke, "run", side_effect=run) as run_, \
                contextlib.redirect_stdout(out):
            try:
                code = smoke.main()
            except BaseException as escaped:  # noqa: B036 - the test inspects what escaped
                code = escaped
        self.assertLessEqual(run_.call_count, 1, "nothing after the first command ran")
        return code, out.getvalue()

    def assertWorkspaceRemoved(self, out):
        left = re.search(r"state left behind on this machine: none \((.+) is removed\)", out)
        self.assertIsNotNone(left, out)
        self.assertFalse(Path(left.group(1)).exists())

    def test_a_command_that_times_out_still_gets_the_tripwire_verdict(self):
        code, out = self.main(self.archive, [self.BEFORE, self.CHANGED],
                              subprocess.TimeoutExpired(cmd="python.exe", timeout=300))
        self.assertEqual(code, 1, out)
        self.assertIn("this machine's registrations: CHANGED", out)
        self.assertIn('FAILED this machine\'s sign-in autostart changed during the run: was "was", now "now"', out)
        self.assertIn("FAILED the run stopped on an unexpected error", out)
        self.assertIn("TimeoutExpired", out)
        self.assertNotIn("all smoke checks passed", out)
        self.assertWorkspaceRemoved(out)

    def test_an_interrupted_run_prints_the_verdict_before_it_stops(self):
        code, out = self.main(self.archive, [self.BEFORE, self.CHANGED], KeyboardInterrupt())
        self.assertIsInstance(code, KeyboardInterrupt, "the interruption is not swallowed")
        self.assertIn("this machine's registrations: CHANGED", out)
        self.assertIn("FAILED this machine's sign-in autostart changed during the run", out)
        self.assertIn("FAILED the run was interrupted (KeyboardInterrupt)", out)
        self.assertNotIn("all smoke checks passed", out)
        self.assertWorkspaceRemoved(out)

    def test_registrations_that_cannot_be_read_again_fail_the_run(self):
        code, out = self.main(self.archive.with_name("missing.zip"),
                              [self.BEFORE, PermissionError(5, "Access is denied")], AssertionError())
        self.assertEqual(code, 1, out)
        self.assertIn("this machine's registrations: UNKNOWN", out)
        self.assertIn("FAILED this machine's registrations could not be read again after the run", out)
        self.assertIn("FAILED the run stopped on an unexpected error", out)
        self.assertIn("FileNotFoundError", out)
        self.assertNotIn("all smoke checks passed", out)
        self.assertWorkspaceRemoved(out)

    def test_an_unchanged_machine_is_reported_as_unchanged(self):
        code, out = self.main(self.archive.with_name("missing.zip"), [self.BEFORE, dict(self.BEFORE)],
                              AssertionError())
        self.assertEqual(code, 1, out)
        self.assertIn("this machine's registrations: unchanged (Start Menu entry, sign-in autostart)", out)
        self.assertNotIn("changed during the run", out)
        self.assertWorkspaceRemoved(out)


@unittest.skipUnless(os.name == "nt", "the registry remap is Windows-only")
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.before = smoke.machine_state()
        temp = tempfile.TemporaryDirectory(prefix="car-smoke-test-")
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.hive = self.workspace / smoke.HIVE_NAME
        self.env = dict(smoke.child_environment(self.workspace, os.environ), PYTHONPATH=str(SRC))
        for name in smoke.REDIRECTED:
            Path(self.env[name]).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.assertEqual(smoke.machine_state(), self.before,
                         "this machine's own registrations changed during the test")

    def bootstrap(self, code, *arguments, env=None, hive=None):
        entry = self.workspace / "entry.py"
        entry.write_text(code, encoding="utf-8")
        done = subprocess.run([sys.executable, str(SCRIPT), smoke.ISOLATED, str(hive or self.hive),
                               str(entry)] + [str(a) for a in arguments],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env or self.env, timeout=180)
        return done.returncode, (done.stdout or "") + (done.stderr or "")

    def test_it_refuses_when_a_per_user_folder_is_outside_the_workspace(self):
        flag = self.workspace / "ran.txt"
        for name in smoke.REDIRECTED:
            env = dict(self.env, **{name: os.environ.get(name) or str(Path.home())})
            code, out = self.bootstrap(_FLAG, flag, env=env)
            self.assertEqual(code, smoke.REFUSED, out)
            self.assertIn("isolation refused: %s is not inside" % name, out)
            self.assertFalse(flag.exists(), "nothing ran")

    def faulted(self, fault):
        """The bootstrap, with `fault` applied in its own process, running _FLAG."""
        flag = self.workspace / "ran.txt"
        entry = self.workspace / "entry.py"
        entry.write_text(_FLAG, encoding="utf-8")
        driver = self.workspace / "faulted.py"
        driver.write_text(_FAULTED % (str(SCRIPT), fault), encoding="utf-8")
        done = subprocess.run([sys.executable, str(driver), str(self.hive), str(entry), str(flag)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=self.env, timeout=180)
        return done.returncode, (done.stdout or "") + (done.stderr or ""), flag

    def assertRefused(self, code, out, flag, reason):
        self.assertEqual(code, smoke.REFUSED, out)
        self.assertIn("isolation refused: %s; nothing from the archive was run" % reason, out)
        self.assertFalse(flag.exists(), "the archive's command must not run: " + out)
        self.assertMarkerNotInTheRealProfile()

    def assertMarkerNotInTheRealProfile(self):
        import winreg
        with self.assertRaises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, smoke.MARKER).Close()

    def test_it_refuses_when_the_remap_silently_does_nothing(self):
        """The case the first proof exists for: RegOverridePredefKey reports success and
        HKEY_CURRENT_USER is still the real profile. The marker is not there, so nothing
        runs - and the marker, written through the hive's own handle, never reaches it."""
        code, out, flag = self.faulted(_OVERRIDE_ANSWERS % 0)
        self.assertRefused(code, out, flag, "HKEY_CURRENT_USER does not show the private hive's marker")

    def test_the_profile_proof_alone_still_refuses_a_remap_that_did_nothing(self):
        """The two proofs are independent: with the marker proof fooled as well, the second
        one still sees the real profile's Control Panel and refuses."""
        code, out, flag = self.faulted(_OVERRIDE_ANSWERS % 0 + _MARKER_FOOLED)
        self.assertRefused(code, out, flag, "HKEY_CURRENT_USER still shows the real profile")

    def test_it_refuses_when_hkcu_shows_a_profile_after_the_remap(self):
        """A real remap onto a hive that has a profile's keys in it is not proof of anything."""
        import winreg
        from ctypes import wintypes
        root = smoke.load_hive(self.hive, smoke.KEY_ALL_ACCESS)
        try:
            winreg.CreateKeyEx(root, smoke.EVERY_PROFILE_HAS, 0, winreg.KEY_ALL_ACCESS).Close()
        finally:
            smoke._advapi32().RegCloseKey(wintypes.HKEY(root))
        flag = self.workspace / "ran.txt"
        code, out = self.bootstrap(_FLAG, flag)
        self.assertRefused(code, out, flag, "HKEY_CURRENT_USER still shows the real profile")

    def test_it_refuses_when_the_remap_reports_failure(self):
        code, out, flag = self.faulted(_OVERRIDE_ANSWERS % 5)
        self.assertRefused(code, out, flag, "HKEY_CURRENT_USER could not be remapped")

    def test_it_refuses_when_the_profile_proof_cannot_read(self):
        code, out, flag = self.faulted(_PROFILE_UNREADABLE)
        self.assertRefused(code, out, flag, "HKEY_CURRENT_USER could not be checked")

    def test_it_refuses_when_the_private_hive_cannot_be_loaded(self):
        flag = self.workspace / "ran.txt"
        missing = self.workspace / "missing"
        env = dict(self.env, **{name: str(missing / name.lower()) for name in smoke.REDIRECTED})
        code, out = self.bootstrap(_FLAG, flag, env=env, hive=missing / smoke.HIVE_NAME)
        self.assertEqual(code, smoke.REFUSED, out)
        self.assertIn("the private hive could not be loaded", out)
        self.assertFalse(flag.exists(), "nothing ran")

    def test_a_workspace_spelled_in_short_form_is_still_the_workspace(self):
        """TEMP is often in 8.3 form - RUNNER~1 on a CI runner - while the hive's path
        resolves long. Compared as spelled, every command there would be refused."""
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(self.workspace), buffer, len(buffer))
        if not length or os.path.normcase(buffer.value) == os.path.normcase(str(self.workspace)):
            self.skipTest("this volume gives the workspace no short name")
        short = Path(buffer.value)
        env = dict(smoke.child_environment(short, os.environ), PYTHONPATH=str(SRC))
        self.writer_cycle(short, env, short / smoke.HIVE_NAME)

    def test_it_runs_the_command_and_passes_its_exit_code_back(self):
        code, out = self.bootstrap("import sys\nprint(sys.argv[1:])\nsys.exit(3)\n", "--home", "x")
        self.assertEqual(code, 3, out)
        self.assertIn("['--home', 'x']", out)

    def test_every_writer_lands_in_the_private_hive_and_folders(self):
        self.writer_cycle(self.workspace, self.env, self.hive)

    def writer_cycle(self, workspace, env, hive):
        """Every writer, then every remover, of the user-wide registrations, under the bootstrap."""
        home = workspace / "home"
        code, out = self.bootstrap(_WRITE, home, env=env, hive=hive)
        self.assertEqual(code, 0, out)
        written = json.loads(out.strip().splitlines()[-1])
        with smoke.private_hive(hive) as root:
            seen = smoke.registrations(root)
        where = os.path.normcase(str(home.resolve()))
        self.assertIn(where, os.path.normcase(seen["sign-in autostart"] or ""))
        self.assertEqual((seen["notification identity"] or {}).get("DisplayName"), startup.AUMID_DISPLAY_NAME)
        self.assertTrue(smoke._inside((seen["notification identity"] or {}).get("IconUri") or "?", home))
        self.assertEqual((seen["notification button handler"] or {}).get("URL Protocol"), "")
        self.assertIn(where, os.path.normcase(seen["notification button command"] or ""))
        self.assertTrue(smoke._inside(written["start menu entry"], workspace))
        self.assertIsNotNone(smoke.start_menu_entry(env["APPDATA"]))

        code, out = self.bootstrap(_REMOVE, home, env=env, hive=hive)
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out.strip().splitlines()[-1]), [True, True, True, True])
        with smoke.private_hive(hive) as root:
            self.assertEqual(smoke.registrations(root),
                             {"sign-in autostart": None, "notification identity": None,
                              "notification button handler": None, "notification button command": None})
        self.assertIsNone(smoke.start_menu_entry(env["APPDATA"]))

    def test_the_marker_never_reaches_the_real_profile(self):
        import winreg
        code, out = self.bootstrap("print('ok')\n")
        self.assertEqual(code, 0, out)
        with self.assertRaises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, smoke.MARKER).Close()
        with smoke.private_hive(self.hive) as root, self.assertRaises(FileNotFoundError):
            winreg.OpenKey(root, smoke.MARKER).Close()


if __name__ == "__main__":
    unittest.main()

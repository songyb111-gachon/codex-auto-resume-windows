"""Nothing the product starts may put a console window on the screen.

Measured on Windows 11 on 2026-09-26: a console program started plainly by a process with no
console of its own - pythonw.exe, the settings window, a DETACHED_PROCESS child, anything WMI
creates - gets a new console window, and a person sees it (a Windows Terminal window, where
that is the default terminal). Started with CREATE_NO_WINDOW - in C#, UseShellExecute=false
and CreateNoWindow=true - it gets a console with no window at all, and everything it starts
plainly shares that console and shows nothing either. The watcher, the tray icon, the cards and
the notification button all run under pythonw.exe, so one plain start of git, PowerShell or
python.exe anywhere beneath them is a window on the owner's screen, and the owner never wants
one.

So, over everything the release ships (build/make_release.py's APP_TREES, the installer, the
window's C#):

* PythonStartTests - every subprocess start passes CREATE_NO_WINDOW, or is one of the three
  DETACHED starts of pythonw.exe (a GUI program: Windows makes no console for it) running the
  product's own launcher, so no Python child runs foreign code under pythonw; no shell; no
  os.system, os.popen, os.startfile, os.spawn*, os.exec* or Win32 CreateProcess/ShellExecute;
  and the interpreter those starts and every registration name is pythonw.exe or nothing.
* StdlibTests - no standard-library module that starts a program by itself: `platform`
  (uname() and all that is built on it fall back to `cmd /c ver`), `multiprocessing`,
  `webbrowser`, `pydoc`.
* WindowStartTests - every ProcessStartInfo in the window's C# sets UseShellExecute=false and
  CreateNoWindow=true, except the two GUI targets named below with their reason.
* PowerShellTests - in the PowerShell the product runs, no Start-Process without -NoNewWindow
  or -WindowStyle Hidden, and none of the other ways to open a console.
* LiveChainTests - under pythonw, two real chains: `pwsh.run` (PowerShell with CREATE_NO_WINDOW
  starting python.exe with `&` and with Start-Process -NoNewWindow, as the bootstrap and the
  installer do), and the Codex adapter's own `codex queue --help`, with a stand-in that starts a
  program plainly, as codex starts its tools. Every leaf must have a console and no window.
  Temporary folders only: nothing is installed or registered, and no real home is read.
"""
from __future__ import annotations

import ast
from collections import namedtuple
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _path in (str(HERE), str(ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import srcscan  # noqa: E402
from codex_auto_resume import config, control, startup  # noqa: E402
from codex_auto_resume.win import kernel  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SPAWNERS = {"Popen", "run", "call", "check_call", "check_output"}
# subprocess functions that always go through a shell.
SHELL_OUTS = {"getoutput", "getstatusoutput"}
OS_STARTERS = re.compile(r"(system|popen|startfile|spawn[lv]p?e?|exec[lv]p?e?|posix_spawnp?)\Z")
OTHER_STARTERS = {"create_subprocess_exec", "create_subprocess_shell", "CreateProcessW", "CreateProcessA",
                  "CreateProcessAsUserW", "ShellExecuteW", "ShellExecuteA", "ShellExecuteExW", "WinExec"}
# Flags that make Windows ignore CREATE_NO_WINDOW when they are given with it.
VOIDING = re.compile(r"DETACHED_PROCESS|CREATE_NEW_CONSOLE")


def _app_trees() -> tuple:
    """build/make_release.py's APP_TREES, read rather than imported: the scan reaches exactly
    what the release copies, and a tree added there is scanned without an edit here."""
    tree = ast.parse((ROOT / "build" / "make_release.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "APP_TREES"
                                                for target in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("build/make_release.py no longer names APP_TREES")


def _tracked(*paths) -> tuple:
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *paths],
                             capture_output=True, timeout=120, creationflags=NO_WINDOW)
    if listing.returncode != 0:
        raise AssertionError("git ls-files failed: %s" % listing.stderr.decode("utf-8", "replace"))
    return tuple(sorted(name for name in listing.stdout.decode("utf-8").split("\0") if name))


# Listed once, at collection, before any test patches subprocess (srcscan does the same).
APP_TREES = _app_trees()
SHIPPED = _tracked(*APP_TREES)
SHIPPED_PY = tuple(name for name in SHIPPED if name.endswith(".py"))
# The installer ships beside the payload (make_release.LAUNCHER_FILES), and bootstrap.ps1 in it.
POWERSHELL = tuple(name for name in SHIPPED + _tracked("build/install") if name.endswith(".ps1"))
CMD = tuple(name for name in _tracked("build/install") if name.endswith((".cmd", ".bat")))
WINDOW_CS = tuple(name for name in guiscan.tracked() if name.endswith(".cs"))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _parse(name: str) -> ast.Module:
    return ast.parse(_read(name), filename=name)


TREES = {name: _parse(name) for name in SHIPPED_PY}


def _bound(tree, module: str):
    """The names `module` is bound to in a file, and the names imported from it."""
    modules, members = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == module)
        elif isinstance(node, ast.ImportFrom) and node.module == module and not node.level:
            members.update({alias.asname or alias.name: alias.name for alias in node.names})
    return modules, members


def _named(node, modules, members):
    """The function of `module` a node names (`subprocess.run`, `S.Popen`, `run`), or None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in modules:
        return node.attr
    if isinstance(node, ast.Name) and node.id in members:
        return members[node.id]
    return None


Start = namedtuple("Start", "file qualname line call function")


def _parents(tree) -> dict:
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing(tree, node, parents):
    """The innermost function holding `node`, or the module."""
    while id(node) in parents:
        node = parents[id(node)]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return tree


def _scan():
    """Every subprocess start in the shipped Python, and every reference to a starter that the
    scan could not follow to its call."""
    starts, unfollowed = [], []
    for name, tree in TREES.items():
        modules, members = _bound(tree, "subprocess")
        if not modules and not members:
            continue
        names, parents = srcscan.qualnames(tree), _parents(tree)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        called = {id(call.func) for call in calls}
        for call in calls:
            if _named(call.func, modules, members) in SPAWNERS | SHELL_OUTS:
                starts.append(Start(name, names[call], call.lineno, call, _enclosing(tree, call, parents)))
        # A starter held in a name and called through it (`runner = runner or subprocess.run`):
        # the calls of that name in the same function are starts too. Anything else - a starter
        # passed along, stored, returned - is a start this scan cannot see, and fails.
        for node in ast.walk(tree):
            if _named(node, modules, members) not in SPAWNERS | SHELL_OUTS or id(node) in called:
                continue
            function = _enclosing(tree, node, parents)
            holders = [assign for assign in ast.walk(function) if isinstance(assign, ast.Assign)
                       and any(inner is node for inner in ast.walk(assign.value))
                       and all(isinstance(target, ast.Name) for target in assign.targets)]
            if not holders:
                unfollowed.append("%s:%d" % (name, node.lineno))
                continue
            held = {target.id for assign in holders for target in assign.targets}
            starts.extend(Start(name, names[call], call.lineno, call, function)
                          for call in ast.walk(function) if isinstance(call, ast.Call)
                          and isinstance(call.func, ast.Name) and call.func.id in held)
    return starts, unfollowed


def _keyword(call, name):
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _assigned(function, name):
    """The values assigned to a local name in a function."""
    return [node.value for node in ast.walk(function) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]


def _argv(start):
    """The argument list a start is given, followed through one local name."""
    argv = start.call.args[0] if start.call.args else _keyword(start.call, "args")
    if isinstance(argv, ast.Name):
        values = _assigned(start.function, argv.id)
        argv = values[0] if len(values) == 1 else argv
    while isinstance(argv, ast.BinOp):                 # [interpreter, script] + list(command)
        argv = argv.left
    return argv


class PythonStartTests(unittest.TestCase):
    # The only starts without CREATE_NO_WINDOW: the watcher, started detached so it outlives
    # whatever started it. Detached is safe only for pythonw.exe, a GUI program, which gets no
    # console at all; a detached python.exe would have none to hand down, and everything it
    # started plainly would open a window. Each must name its interpreter through one of
    # INTERPRETERS, all of which are pythonw.exe or refuse, and must run the product's own
    # launcher or entry point, never code from anywhere else.
    DETACHED = {
        ("src/codex_auto_resume/control/watcher.py", "WatcherMixin._launch_watcher"):
            "Start watcher, from the window, the panel and the command line",
        ("scripts/plugin_setup.py", "start_watcher"): "setup and enable, from the installer and the skill",
        ("scripts/watcher_launcher.py", "_relaunch_once"):
            "the launcher again, once, when the state is newer than its engine",
    }
    INTERPRETERS = {"startup.python_launcher()", "python_for_watcher(home)",
                    "Path(sys.executable).resolve().with_name('pythonw.exe')"}
    OWN_CODE = ("entry", "LAUNCHER_NAME", "__file__")

    @classmethod
    def setUpClass(cls):
        cls.starts, cls.unfollowed = _scan()

    def test_the_scan_reaches_what_the_release_ships(self):
        for name in ("src/codex_auto_resume/pwsh.py", "src/codex_auto_resume/codex/transport.py",
                     "scripts/plugin_setup.py", "scripts/watcher_launcher.py", "scripts/promote.py"):
            self.assertIn(name, SHIPPED_PY)
        found = {(start.file, start.qualname) for start in self.starts}
        for site in (("src/codex_auto_resume/compat/evaluator.py", "run_refresh"),   # through `runner`
                     ("src/codex_auto_resume/ui/tray/dashboard.py", "open_dashboard"),
                     ("src/codex_auto_resume/codex/appserver.py", "Protocol.__enter__"),
                     ("scripts/promote.py", "git")):
            self.assertIn(site, found)
        self.assertGreaterEqual(len(self.starts), 20)

    def test_every_start_can_be_followed(self):
        self.assertEqual(self.unfollowed, [])

    def test_every_start_gets_a_hidden_console_or_is_a_listed_detached_start(self):
        offenders = []
        for start in self.starts:
            flags = _keyword(start.call, "creationflags")
            if flags is None:
                offenders.append("%s:%d passes no creationflags" % (start.file, start.line))
                continue
            text = ast.unparse(flags)
            if "NO_WINDOW" in text:
                if VOIDING.search(text):
                    offenders.append("%s:%d: %s voids CREATE_NO_WINDOW" % (start.file, start.line, text))
            elif (start.file, start.qualname) not in self.DETACHED:
                offenders.append("%s:%d (%s) starts a program without CREATE_NO_WINDOW"
                                 % (start.file, start.line, start.qualname))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_start_goes_through_a_shell(self):
        offenders = ["%s:%d" % (start.file, start.line) for start in self.starts
                     if _keyword(start.call, "shell") is not None
                     and not (isinstance(_keyword(start.call, "shell"), ast.Constant)
                              and _keyword(start.call, "shell").value is False)]
        offenders += ["%s:%d uses subprocess.%s" % (start.file, start.line, start.call.func.attr)
                      for start in self.starts if getattr(start.call.func, "attr", None) in SHELL_OUTS]
        self.assertEqual(offenders, [])

    def test_the_detached_starts_are_pythonw_running_the_products_own_code(self):
        detached = {}
        for start in self.starts:
            flags = _keyword(start.call, "creationflags")
            if flags is not None and "NO_WINDOW" not in ast.unparse(flags):
                detached[(start.file, start.qualname)] = start
        self.assertEqual(set(detached), set(self.DETACHED), "a stale entry, or a new detached start")
        for site, start in detached.items():
            with self.subTest(site=site):
                source = ast.unparse(start.function)
                self.assertIn("DETACHED_PROCESS", source)
                self.assertNotIn("CREATE_NEW_CONSOLE", source)
                argv = _argv(start)
                self.assertIsInstance(argv, ast.List, ast.unparse(argv))
                self.assertEqual(ast.unparse(argv.elts[0]), "str(interpreter)")
                chosen = {ast.unparse(value) for value in _assigned(start.function, "interpreter")}
                self.assertTrue(chosen and chosen <= self.INTERPRETERS, chosen)
                self.assertTrue(any(word in ast.unparse(argv.elts[1]) for word in self.OWN_CODE),
                                ast.unparse(argv.elts[1]))

    def test_the_no_window_constant_is_the_one_windows_defines(self):
        if os.name == "nt":
            self.assertEqual(kernel.NO_WINDOW, 0x08000000)
            self.assertEqual(kernel.NO_WINDOW, subprocess.CREATE_NO_WINDOW)

    def test_nothing_starts_a_program_any_other_way(self):
        offenders = []
        for name, tree in TREES.items():
            modules, members = _bound(tree, "os")
            for node in ast.walk(tree):
                called = _named(node, modules, members)
                if called and OS_STARTERS.match(called):
                    offenders.append("%s:%d os.%s" % (name, node.lineno, called))
                if isinstance(node, ast.Attribute) and node.attr in OTHER_STARTERS:
                    offenders.append("%s:%d %s" % (name, node.lineno, node.attr))
                if isinstance(node, ast.Constant) and node.value in OTHER_STARTERS:
                    offenders.append("%s:%d %r" % (name, node.lineno, node.value))
        self.assertEqual(offenders, [])


class InterpreterTests(unittest.TestCase):
    """What Windows starts on its own - the Run value, the protocol handler, the Start Menu entry
    - and the detached watcher are pythonw.exe or nothing. A Run value cannot carry
    CREATE_NO_WINDOW, and until this release a missing pythonw.exe silently put python.exe there,
    whose console window would have stayed for the whole session."""

    def interpreter_folder(self, *names):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in names:
            (folder / name).write_bytes(b"")
        return folder

    def test_python_launcher_is_pythonw_or_refuses(self):
        folder = self.interpreter_folder("python.exe")
        with mock.patch.object(startup.sys, "executable", str(folder / "python.exe")):
            for build in (startup.python_launcher,
                          lambda: startup.command_line(folder / "entry.py", folder),
                          lambda: startup.protocol_command_line(folder / "entry.py", folder)):
                with self.assertRaises(startup.StartupError):
                    build()
        (folder / "pythonw.exe").write_bytes(b"")
        with mock.patch.object(startup.sys, "executable", str(folder / "python.exe")):
            self.assertEqual(startup.python_launcher(), (folder / "pythonw.exe").resolve())
            for command in (startup.command_line(folder / "entry.py", folder),
                            startup.protocol_command_line(folder / "entry.py", folder)):
                self.assertEqual(Path(startup.parse_command(command)[0]).name.lower(), "pythonw.exe")

    def test_start_watcher_starts_nothing_without_pythonw(self):
        folder = self.interpreter_folder("python.exe")
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (home / "watcher-launcher.py").write_text("# launcher\n", encoding="utf-8")
        panel = control.Control(config.Paths(home))
        with mock.patch.object(startup.sys, "executable", str(folder / "python.exe")), \
                mock.patch.object(control.Control, "watcher_running", return_value=False), \
                mock.patch("subprocess.Popen") as popen:
            with self.assertRaises(control.ControlError) as refused:
                panel.start_watcher()
        self.assertEqual(refused.exception.code, "not_installed")
        popen.assert_not_called()


class StdlibTests(unittest.TestCase):
    # Standard-library modules that start a program by themselves, and why none may be imported
    # by anything the release ships. Every other module the product loads was read for this on
    # 3.13.15 (the bundled runtime) and starts nothing on Windows.
    BANNED = {
        "platform": "uname() - and version(), release(), machine(), system(), node(), platform() and "
                    "win32_ver(), which are built on it - asks WMI and, when that fails, runs `cmd /c "
                    "ver` with shell=True; sys.getwindowsversion() and the environment answer both",
        "multiprocessing": "every worker is sys.executable, started by it: pythonw.exe under the watcher",
        "concurrent.futures.process": "ProcessPoolExecutor is multiprocessing",
        "webbrowser": "runs $BROWSER with Popen and no flags; open a URL with os.startfile, which is "
                      "the shell and needs a listed reason here",
        "pydoc": "its pager is `more`, through os.popen",
    }

    def test_no_shipped_file_imports_a_module_that_starts_programs(self):
        offenders = []
        for name, tree in TREES.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    targets = [node.module] + ["%s.%s" % (node.module, alias.name) for alias in node.names]
                else:
                    continue
                for target in targets:
                    for banned in self.BANNED:
                        if target == banned or target.startswith(banned + "."):
                            offenders.append("%s:%d imports %s: %s" % (name, node.lineno, target,
                                                                      self.BANNED[banned]))
                if any(alias.name == "ProcessPoolExecutor" for alias in node.names):
                    offenders.append("%s:%d ProcessPoolExecutor" % (name, node.lineno))
        self.assertEqual(offenders, [], "\n".join(offenders))

    @unittest.skipUnless(sys.platform == "win32", "Windows versions")
    def test_diagnostics_says_what_platform_would_have_said(self):
        import platform
        from codex_auto_resume import diagnostics
        system = diagnostics._system()
        self.assertEqual(system["windows"], platform.version())
        self.assertEqual(system["machine"], platform.machine())


def _without_comments(text: str) -> str:
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _statements(text: str) -> list:
    """PowerShell lines with their backtick continuations joined."""
    return re.sub(r"`\r?\n", " ", _without_comments(text)).splitlines()


class PowerShellTests(unittest.TestCase):
    """`&` and a plain command line share the console of the PowerShell running them: the
    installer's own window, or the windowless console of a powershell started with
    CREATE_NO_WINDOW (pwsh.run, the window's Update and Repair, the compatibility refresh).
    Start-Process makes a new console unless it is told not to, and the rest below always do."""

    FORBIDDEN = {
        r"\bInvoke-Item\b": "the shell decides what opens",
        r"\bStart-Job\b": "a new powershell.exe",
        r"Diagnostics\.Process\]::Start": "a start with no window rule",
        r"^\s*(start|saps)\s": "Start-Process by its alias",
        r"\bcmd(\.exe)?\s+/[ck]\s+start\b": "a new console, always",
        r"powershell(\.exe)?['\"]?\s[^\n]*-WindowStyle\s+Hidden": "the window opens, then hides",
    }

    # What makes a Python string constant a PowerShell script: the ones pwsh.run and the process
    # inventory hand to powershell.exe all carry one of these.
    POWERSHELL_TEXT = re.compile(r"\$env:|\$ErrorActionPreference|Add-Type|Get-CimInstance|New-Object|"
                                 r"\[Console\]|Start-Process")

    def texts(self):
        found = {name: _read(name) for name in POWERSHELL}
        for name, tree in TREES.items():
            pieces = [value for _, value in srcscan.string_constants(tree) if self.POWERSHELL_TEXT.search(value)]
            if pieces:
                found[name] = "\n".join(pieces)
        return found

    def test_the_scripts_inside_the_package_are_read_too(self):
        texts = self.texts()
        for name in ("src/codex_auto_resume/notify.py", "src/codex_auto_resume/shortcut.py",
                     "src/codex_auto_resume/codex/pairing.py"):
            self.assertIn(name, texts)

    def test_the_scan_reads_the_bootstrap_and_the_installer(self):
        self.assertIn("scripts/bootstrap.ps1", POWERSHELL)
        self.assertIn("build/install/install.ps1", POWERSHELL)
        self.assertIn("build/install/Install.cmd", CMD)

    def test_every_start_process_shares_the_console_or_hides_its_own(self):
        offenders, seen = [], 0
        for name, text in self.texts().items():
            for line in _statements(text):
                if re.search(r"\bStart-Process\b", line, re.I):
                    seen += 1
                    if not re.search(r"-NoNewWindow\b|-WindowStyle\s+['\"]?Hidden\b", line, re.I):
                        offenders.append("%s: %s" % (name, line.strip()))
        self.assertGreaterEqual(seen, 1, "install.ps1 starts codex.exe with Start-Process")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_nothing_else_opens_a_console(self):
        offenders = []
        for name, text in self.texts().items():
            for line in _statements(text):
                for pattern, why in self.FORBIDDEN.items():
                    if re.search(pattern, line, re.I):
                        offenders.append("%s: %s (%s)" % (name, line.strip(), why))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_installer_commands_start_nothing_in_a_console_of_its_own(self):
        # Install.cmd is the person's own console, by design; `start` would open a second one.
        offenders = []
        for name in CMD:
            for line in _read(name).splitlines():
                code = line.strip()
                if code.lower().startswith(("rem ", "::")):
                    continue
                if re.match(r"(start|cmd(\.exe)?\s+/[ck]\s+start)\b", code, re.I) \
                        or re.search(r"-WindowStyle\s+Hidden", code, re.I):
                    offenders.append("%s: %s" % (name, code))
        self.assertEqual(offenders, [])


class WindowStartTests(unittest.TestCase):
    # Starts in the window's C# that set no CreateNoWindow, because the target is a GUI program
    # and Windows makes no console for one: (file, target as written) -> why.
    GUI_TARGETS = {
        ("gui/WindowReopen.cs", "typeof(SettingsForm).Assembly.Location"):
            "the window starting itself again, compiled /target:winexe by build/make_gui.ps1",
        ("gui/DashboardMaintenance.cs", '"explorer.exe"'):
            "File Explorer on the logs folder the person asked to open, through the shell",
    }

    @staticmethod
    def first_argument(text: str, start: int) -> str:
        """The first argument of the call whose `(` ends just before `start`, brackets balanced."""
        depth, index = 0, start
        while index < len(text):
            character = text[index]
            if character in "([{":
                depth += 1
            elif character in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif character == "," and depth == 0:
                break
            index += 1
        return text[start:index].strip()

    def starts(self):
        """(file, variable or None, target, text from the declaration to the start)."""
        found = []
        for name in WINDOW_CS:
            text = _read(name)
            checked = set()
            for made in re.finditer(r"(?:var|ProcessStartInfo)\s+(\w+)\s*=\s*new\s+ProcessStartInfo\s*\(", text):
                variable = made.group(1)
                started = re.compile(r"Process\.Start\(\s*%s\s*\)" % re.escape(variable)).search(text, made.end())
                self.assertIsNotNone(started, "%s: %s is never started" % (name, variable))
                body = text[made.start():started.end()]
                assigned = re.search(r"\b%s\.FileName\s*=\s*([^;]+);" % re.escape(variable), body)
                target = self.first_argument(text, made.end()) or (assigned.group(1).strip() if assigned else None)
                found.append((name, variable, target, body))
                checked.add(variable)
            for call in re.finditer(r"\bProcess\.Start\(", text):
                argument = self.first_argument(text, call.end())
                if argument not in checked:
                    found.append((name, None, argument, text[call.start():call.end()]))
        return found

    def test_the_scan_finds_the_windows_starts(self):
        targets = {(name, target) for name, _, target, _ in self.starts()}
        self.assertIn(("gui/McpLauncher.cs", "python"), targets)
        self.assertIn(("gui/Dashboard.cs", "python"), targets)
        self.assertGreaterEqual(len(targets), 7)

    def test_every_console_program_the_window_starts_gets_a_hidden_console(self):
        offenders, gui = [], set()
        for name, variable, target, body in self.starts():
            if (name, target) in self.GUI_TARGETS:
                gui.add((name, target))
                continue
            if variable is None:
                offenders.append("%s: Process.Start(%s) with no ProcessStartInfo" % (name, target))
                continue
            for setting in (r"UseShellExecute\s*=\s*false", r"CreateNoWindow\s*=\s*true"):
                if not re.search(r"\b%s\.%s\s*;" % (re.escape(variable), setting), body):
                    offenders.append("%s: %s (%s) does not set %s" % (name, variable, target, setting))
        self.assertEqual(offenders, [], "\n".join(offenders))
        self.assertEqual(gui, set(self.GUI_TARGETS), "a GUI target listed here is gone or renamed")

    def test_the_window_reaches_no_other_process_api(self):
        for name in WINDOW_CS:
            with self.subTest(name=name):
                self.assertIsNone(re.search(r"\b(CreateProcess\w*|ShellExecute(Ex)?W?|WinExec)\s*\(",
                                            _read(name)))

    def test_the_window_is_a_gui_program_and_the_mcp_launcher_a_console_one(self):
        # The tray and WindowReopen start the window; a console build of it would open a console.
        # The MCP launcher is a console program on purpose - it speaks to Codex over stdio - and
        # its python.exe child is held above; Codex starts it windowless (measured 2026-09-26).
        script = _read("build/make_gui.ps1")
        self.assertRegex(script, r"Build -Name 'CodexAutoResumeSettings\.exe' -Target 'winexe'")
        self.assertRegex(script, r"Build -Name 'codex-auto-resume-mcp\.exe' -Target 'exe'")


# What a program at the end of a chain asks of its console, written where the test can read it.
LEAF = r'''
import ctypes, json, sys
kernel, user = ctypes.windll.kernel32, ctypes.windll.user32
window = kernel.GetConsoleWindow()
with open(sys.argv[1], "a", encoding="utf-8") as answers:
    answers.write(json.dumps({"chain": sys.argv[2], "console": bool(kernel.GetConsoleCP()),
                              "console_window": bool(window),
                              "visible": bool(window and user.IsWindowVisible(window))}) + "\n")
'''
# A console program as codex.exe is, run as `codex queue --help`: it answers for itself, starts a
# program plainly, as codex starts git and its tools, and prints the flags the adapter looks for.
STAND_IN = r'''
import subprocess, sys
python, leaf, answers = %r, %r, %r
sys.argv = [leaf, answers, "codex queue --help, started by the Codex adapter"]
exec(compile(open(leaf, encoding="utf-8").read(), leaf, "exec"), {"__name__": "__main__"})
subprocess.run([python, leaf, answers, "a program codex starts plainly"])
print("--thread --message")
'''
# Constant, as pwsh.run requires; the values arrive as environment variables.
SCRIPT = r'''
$python = $env:CODEX_AUTO_RESUME_ARG_PYTHON
$leaf = $env:CODEX_AUTO_RESUME_ARG_LEAF
$answers = $env:CODEX_AUTO_RESUME_ARG_ANSWERS
& $python $leaf $answers 'python.exe by the call operator, as bootstrap.ps1 and install.ps1 run it'
$line = '"{0}" "{1}" "python.exe by Start-Process -NoNewWindow, as install.ps1 runs codex.exe"' -f $leaf, $answers
Start-Process -FilePath $python -ArgumentList $line -NoNewWindow -Wait
exit 0
'''
DRIVER = r'''
import ctypes, json, os, pathlib, sys
src, work, script, stand_in = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, src)
from codex_auto_resume import pwsh
from codex_auto_resume.codex.transport import Backend
kernel = ctypes.windll.kernel32
python = str(pathlib.Path(sys.executable).with_name("python.exe"))
values = {"PYTHON": python, "LEAF": str(work / "leaf.py"), "ANSWERS": str(work / "answers.jsonl")}
done = {"host": {"console": bool(kernel.GetConsoleCP()), "console_window": bool(kernel.GetConsoleWindow())}}
try:
    done["pwsh"] = pwsh.run(pathlib.Path(script).read_text(encoding="utf-8"), values, timeout=60)
except Exception as exc:
    done["pwsh"] = repr(exc)
(work / "queue").write_text(pathlib.Path(stand_in).read_text(encoding="utf-8")
                            % (python, values["LEAF"], values["ANSWERS"]), encoding="utf-8")
os.chdir(work)      # `python.exe queue --help` runs work/queue
try:
    done["queue"] = Backend(work / "codex-home", python)._queue_interface_ok()
except Exception as exc:
    done["queue"] = repr(exc)
(work / "driver.json").write_text(json.dumps(done), encoding="utf-8")
'''


@unittest.skipUnless(sys.platform == "win32", "Windows consoles")
class LiveChainTests(unittest.TestCase):
    """The real chains, from a host with no console, as the watcher is."""

    def test_under_pythonw_nothing_down_the_chain_gets_a_window(self):
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file() or not Path(sys.executable).with_name("python.exe").is_file():
            self.skipTest("no pythonw.exe and python.exe beside this interpreter")
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            for file_name, text in (("leaf.py", LEAF), ("script.ps1", SCRIPT), ("stand_in.py", STAND_IN),
                                    ("driver.py", DRIVER)):
                (work / file_name).write_text(text, encoding="utf-8")
            subprocess.run([str(pythonw), str(work / "driver.py"), str(ROOT / "src"), str(work),
                            str(work / "script.ps1"), str(work / "stand_in.py")],
                           timeout=180, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            done = json.loads((work / "driver.json").read_text(encoding="utf-8"))
            answers = [json.loads(line) for line in
                       (work / "answers.jsonl").read_text(encoding="utf-8").splitlines() if line]
        # The host had no console: the case where a plain start would have opened a window.
        self.assertEqual(done["host"], {"console": False, "console_window": False})
        self.assertEqual(done["pwsh"], 0)
        self.assertIs(done["queue"], True, "the adapter read the stand-in's flags")
        self.assertEqual(len(answers), 4, answers)
        for answer in answers:
            with self.subTest(chain=answer["chain"]):
                # A console, so the program ran as a console program does, and no window for it:
                # not a hidden one, none at all.
                self.assertEqual((answer["console"], answer["console_window"], answer["visible"]),
                                 (True, False, False))


if __name__ == "__main__":
    unittest.main()

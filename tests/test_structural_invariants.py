"""Safety properties that used to rest on one file's text, asserted over the whole package.

Each of these was true because of where a line sat - `engine.py` held the only call that hands
a message to the backend, `windows.py` the only argv that runs `codex queue`, `cli.py` the only
mention of `--last` - and nothing would have noticed a second one appearing in another
module. They are asserted here by qualified name across every tracked file (`srcscan`), so a
function that moves keeps its guarantee, and a second site anywhere fails.

The second half pins the names and paths other programs depend on. Some of those programs
are not in this repository at all: a launcher copied into a user's home by an older release
keeps running after this code is upgraded underneath it.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
import re
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

ROOT = srcscan.ROOT
SPAWNERS = {"Popen", "run", "call", "check_call", "check_output"}


def calls(predicate):
    """(file, qualified name, node) for every call in the package the predicate accepts."""
    found = []
    for path, tree in srcscan.package_asts().items():
        names = srcscan.qualnames(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and predicate(node):
                found.append((srcscan.relative(path), names[node], node))
    return found


def constants(node):
    return {value for _, value in srcscan.string_constants(node)}


class OneSenderTests(unittest.TestCase):
    """The watcher is the only sender, and inside it one function sends."""

    def test_only_the_dispatch_hands_a_message_to_the_backend(self):
        # Any call of a method named `send`, on anything: the backend's is the only one the
        # package makes, so an alias (`b = self.backend; b.send(...)`) is caught as well.
        sends = calls(lambda node: isinstance(node.func, ast.Attribute) and node.func.attr == "send")
        self.assertEqual([(where, name) for where, name, _ in sends],
                         [("codex_auto_resume/engine.py", "Engine.dispatch")])
        receiver = sends[0][2].func.value
        self.assertEqual(getattr(receiver, "attr", getattr(receiver, "id", None)), "backend")

    def test_exactly_one_place_spawns_the_queue_process(self):
        """`codex queue` is started with a message in one function. The only other process
        that names `queue` asks it for `--help`, to prove the flags still exist."""
        spawns = calls(lambda node: getattr(node.func, "attr", getattr(node.func, "id", None)) in SPAWNERS
                       and "queue" in constants(node))
        sending = [(where, name, node) for where, name, node in spawns if "--message" in constants(node)]
        self.assertEqual([(where, name) for where, name, _ in sending],
                         [("codex_auto_resume/windows.py", "Backend.send")])
        self.assertEqual(sending[0][2].func.attr, "Popen")
        self.assertLessEqual({"--thread", "--message"}, constants(sending[0][2]))
        for where, name, node in spawns:
            with self.subTest(where=where, name=name):
                self.assertTrue("--message" in constants(node) or "--help" in constants(node),
                                "a process names `queue` without being the send or the help probe")

    def test_last_is_named_only_to_be_refused(self):
        """Exact conversation identity, never `--last`: the only place the package spells it is
        the sentence that refuses anything but a canonical UUID."""
        found = []
        for path, tree in srcscan.package_asts().items():
            names = srcscan.qualnames(tree)
            raised = {id(child) for node in ast.walk(tree) if isinstance(node, ast.Raise)
                      for child in ast.walk(node)}
            found += [(srcscan.relative(path), names[node], id(node) in raised)
                      for node, value in srcscan.string_constants(tree) if "--last" in value]
        self.assertEqual(found, [("codex_auto_resume/cli.py", "canonical_thread_id", True)])


class ProcessTests(unittest.TestCase):
    # Every module that imports subprocess, and why. An adapter that runs something, or a
    # module that only names its exception type. A module leaving this list is a deletion to
    # make here; a module joining it is a new way to start a process, and needs a reason.
    SUBPROCESS = {
        "codex_auto_resume/windows.py": "the Codex adapter: `codex queue`, the App Server, the process inventory",
        "codex_auto_resume/compatio.py": "`codex --version`, `codex queue --help`, and the bootstrap's -Compatibility fetch",
        "codex_auto_resume/pwsh.py": "the one place PowerShell is run",
        "codex_auto_resume/control.py": "starts the watcher, detached (a lazy import in start_watcher)",
        "codex_auto_resume/tray.py": "opens the settings window from the icon",
        "codex_auto_resume/notify.py": "catches SubprocessError from pwsh.run",
        "codex_auto_resume/shortcut.py": "catches SubprocessError from pwsh.run",
        "codex_auto_resume/cli.py": "imported and unused (a dead import; step 2 removes it)",
        "codex_auto_resume/startup.py": "imported and unused (a dead import; step 2 removes it)",
    }

    def test_subprocess_is_imported_only_by_the_adapters_listed(self):
        importers = {srcscan.relative(path) for path in srcscan.package_files()
                     if any(entry.target == "subprocess" or entry.target.startswith("subprocess.")
                            for entry in srcscan.imports(path))}
        self.assertEqual(importers, set(self.SUBPROCESS))


class EntryPointTests(unittest.TestCase):
    """Names another program calls. Moving one is a change to that program too."""

    ENTRY_POINTS = (
        # (module, name, a file that calls it by that name, the text it calls it with)
        ("codex_auto_resume.cli", "main", "src/auto_resume.py", "from codex_auto_resume.cli import main"),
        ("codex_auto_resume.cli", "main", "scripts/plugin_setup.py", "from codex_auto_resume.cli import main"),
        ("codex_auto_resume.controlcli", "main", "gui/SettingsApp.cs", "from codex_auto_resume.controlcli import main;"),
        ("codex_auto_resume.controlcli", "main", "gui/Dashboard.cs", "from codex_auto_resume.controlcli import main;"),
        ("codex_auto_resume.controlcli", "serve", "gui/Dashboard.cs", " serve\";"),
        ("codex_auto_resume.mcpserver", "main", "gui/McpLauncher.cs", "from codex_auto_resume.mcpserver import main;"),
        ("codex_auto_resume.app", "App", "scripts/plugin_setup.py", "from codex_auto_resume.app import App"),
        ("codex_auto_resume.config", "Paths", "scripts/plugin_setup.py", "config.Paths("),
        ("codex_auto_resume.control", "Control", "scripts/plugin_setup.py", "control.Control("),
    )

    def test_every_entry_point_is_where_its_callers_look(self):
        for module, name, caller, spelled in self.ENTRY_POINTS:
            with self.subTest(module=module, name=name, caller=caller):
                self.assertIn(spelled, (ROOT / caller).read_text(encoding="utf-8"),
                              "the caller no longer names it this way; update this table with it")
                self.assertTrue(callable(getattr(importlib.import_module(module), name, None)))

    def test_the_bridge_still_answers_to_serve(self):
        """The window starts the bridge as `... controlcli main serve` and talks to it for as
        long as it is open."""
        from codex_auto_resume import controlcli
        self.assertEqual(controlcli.build_parser().parse_args(["serve"]).command, "serve")


class PinnedPathTests(unittest.TestCase):
    """Paths that are contracts with something outside the package."""

    def test_the_paths_the_launcher_requires_are_files(self):
        """`scripts/watcher_launcher.py` accepts a directory as an installation only if these
        two exist. Its copy is installed into the user's home and is not replaced when the
        application is: an OLDER installed launcher reads these paths from a NEWER
        installation. Turning either into a package, or moving it, makes that launcher refuse
        to start the watcher at the next sign-in - for every existing installation."""
        tree = ast.parse((ROOT / "scripts" / "watcher_launcher.py").read_text(encoding="utf-8"))
        usable = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_usable")
        required = []
        for node in ast.walk(usable):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "is_file":
                parts, value = [], node.func.value
                while isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div):
                    parts.insert(0, value.right.value)
                    value = value.left
                required.append("/".join(parts))
        self.assertEqual(sorted(required), ["src/auto_resume.py", "src/codex_auto_resume/cli.py"])
        tracked = set(srcscan.tracked())
        for relative in required:
            with self.subTest(relative):
                self.assertTrue((ROOT / relative).is_file(), relative)
                self.assertIn(relative, tracked)

    def test_the_entry_script_and_the_cli_stay_files(self):
        """In users' HKCU Run values (the entry script) and in installed launchers (both)."""
        self.assertTrue((ROOT / "src" / "auto_resume.py").is_file())
        self.assertFalse((ROOT / "src" / "auto_resume").exists())
        self.assertEqual(srcscan.files_of("codex_auto_resume.cli"),
                         [srcscan.modules()["codex_auto_resume.cli"]])
        self.assertEqual(srcscan.relative(srcscan.modules()["codex_auto_resume.cli"]), "codex_auto_resume/cli.py")

    def test_files_other_programs_name_are_where_they_look(self):
        """The release and the bootstrap check the archive for mcpserver.py; the bootstrap asks
        whether an installation exists by controlcli.py; the settings window keys its
        strings cache on five files by name, and hashes "-" for one that is missing -
        silently serving a stale language."""
        names = {
            ".github/workflows/release.yml": ["payload/app/src/codex_auto_resume/mcpserver.py"],
            "scripts/bootstrap.ps1": ["payload/app/src/codex_auto_resume/mcpserver.py",
                                      "codex_auto_resume\\controlcli.py"],
        }
        for consumer, spelled in names.items():
            text = (ROOT / consumer).read_text(encoding="utf-8")
            for name in spelled:
                with self.subTest(consumer=consumer, name=name):
                    self.assertIn(name, text)
                    self.assertTrue((ROOT / "src" / name.replace("payload/app/src/", "").replace("\\", "/")).is_file())
        stamp = re.search(r'foreach \(string name in new\[\] \{([^}]*)\}\)',
                          (ROOT / "gui" / "SettingsApp.cs").read_text(encoding="utf-8"))
        stamped = re.findall(r'"([^"]+)"', stamp.group(1))
        self.assertEqual(stamped, ["interface.py", "l10n.py", "settings.py", "config.py", "controlcli.py"])
        for name in stamped:
            self.assertTrue((ROOT / "src" / "codex_auto_resume" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()

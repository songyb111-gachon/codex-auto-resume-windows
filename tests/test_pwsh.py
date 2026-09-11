"""No value can change what PowerShell runs.

v0.5.6 and earlier quoted each value as a PowerShell single-quoted string and doubled any
ASCII apostrophe. PowerShell also accepts U+2018, U+2019, U+201A and U+201B as single
quotes, so a conversation title or project folder containing one of them closed the
string early and the rest of the value ran as PowerShell in the watcher's context. That
was confirmed against the real interpreter before the fix: a title of
`project’; Write-Output INJECTED; ’` printed INJECTED.

The fix passes values as environment variables to a constant script. These tests hold it
to that in two ways: structurally (every script is a constant and contains no value) and
behaviourally (the real Windows PowerShell receives hostile values intact and runs none
of them).
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import notify, pwsh, shortcut  # noqa: E402

# Every character PowerShell treats as a quote or an interpolation start, in payloads
# that would run a command if any of them were interpreted.
HOSTILE = [
    "project\u2019; New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL; \u2019",
    "project\u2018; New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL; \u2018",
    "project\u201a; New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL; \u201a",
    "project\u201b; New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL; \u201b",
    "project'; New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL; '",
    "project\"; New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL; \"",
    "$(New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL)",
    "@(New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL)",
    "`n New-Item -ItemType File -Path $env:CAR_TEST_SENTINEL",
    "Bob\u2019s project",
    "자동 복구 \u2019 🧩",
]

# Writes the received value to a file, byte for byte, and nothing else. Constant.
ECHO = """
$ErrorActionPreference = 'Stop'
[System.IO.File]::WriteAllText($env:CODEX_AUTO_RESUME_ARG_OUT, $env:CODEX_AUTO_RESUME_ARG_VALUE, [System.Text.UTF8Encoding]::new($false))
"""


@unittest.skipUnless(pwsh.executable(), "Windows PowerShell is not available")
class RealInterpreterTests(unittest.TestCase):
    def test_hostile_values_arrive_intact_and_run_nothing(self):
        for value in HOSTILE:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                out = Path(folder) / "received.txt"
                sentinel = Path(folder) / "INJECTED"
                with patch.dict(os.environ, {"CAR_TEST_SENTINEL": str(sentinel)}):
                    code = pwsh.run(ECHO, {"OUT": out, "VALUE": value}, timeout=60)
                self.assertEqual(code, 0)
                self.assertFalse(sentinel.exists(), "a value ran as PowerShell")
                self.assertEqual(out.read_text(encoding="utf-8"), value,
                                 "the value did not survive unchanged")

    def test_the_toast_script_loads_a_hostile_title_as_text(self):
        """The real toast script, as far as parsing the document - no toast is raised."""
        probe = notify._SCRIPT.split("$toast =")[0] + (
            "\n[System.IO.File]::WriteAllText($env:CODEX_AUTO_RESUME_ARG_OUT, "
            "$doc.GetXml(), [System.Text.UTF8Encoding]::new($false))\n")
        title = HOSTILE[0]
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "doc.xml"
            sentinel = Path(folder) / "INJECTED"
            with patch.dict(os.environ, {"CAR_TEST_SENTINEL": str(sentinel)}):
                code = pwsh.run(probe, {"OUT": out, "XML": notify._toast_xml(title, "body"),
                                        "AUMID": "x"}, timeout=60)
            self.assertEqual(code, 0)
            self.assertFalse(sentinel.exists())
            self.assertIn("project\u2019; New-Item", out.read_text(encoding="utf-8"))


class EnvironmentTests(unittest.TestCase):
    def test_values_are_namespaced(self):
        env = pwsh.environment({"XML": "<a/>"})
        self.assertEqual(env[pwsh.PREFIX + "XML"], "<a/>")

    def test_a_stale_argument_from_the_parent_is_not_inherited(self):
        with patch.dict(os.environ, {pwsh.PREFIX + "STALE": "left over"}):
            self.assertNotIn(pwsh.PREFIX + "STALE", pwsh.environment({}))

    def test_values_that_cannot_be_carried_are_refused_not_mangled(self):
        with self.assertRaises(pwsh.PowerShellError):
            pwsh.environment({"X": "a\0b"})
        with self.assertRaises(pwsh.PowerShellError):
            pwsh.environment({"X": "x" * (pwsh.MAX_VALUE + 1)})

    def test_argument_names_are_restricted(self):
        for bad in ("lower", "WITH-DASH", "", "A" * 60, "X;Y"):
            with self.subTest(bad), self.assertRaises(pwsh.PowerShellError):
                pwsh.environment({bad: "v"})


class NoValueInScriptTests(unittest.TestCase):
    """Structural: every PowerShell script this product sends is a constant."""

    def test_the_old_quoting_helpers_are_gone(self):
        for module in (notify, shortcut):
            with self.subTest(module.__name__):
                self.assertFalse(hasattr(module, "_ps_literal"),
                                 "quoting values into script text is the bug this replaced")

    def test_the_scripts_have_no_format_placeholders(self):
        for name, script in (("notify._SCRIPT", notify._SCRIPT), ("shortcut._MAKER", shortcut._MAKER)):
            with self.subTest(name):
                self.assertNotIn("%(", script)
                self.assertNotIn("{0}", script)

    def test_every_pwsh_run_call_passes_a_module_constant(self):
        """Not an f-string, not a %-format, not a concatenation: a name bound once."""
        calls = []
        for path in (ROOT / "src" / "codex_auto_resume").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            constants = {target.id for node in tree.body if isinstance(node, ast.Assign)
                         for target in node.targets if isinstance(target, ast.Name)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "run" and isinstance(node.func.value, ast.Name) \
                        and node.func.value.id == "pwsh":
                    calls.append(path.name)
                    script = node.args[0]
                    with self.subTest(path.name):
                        self.assertIsInstance(script, ast.Name, "the script must be a named constant")
                        self.assertIn(script.id, constants, "the script must be defined at module level")
        self.assertEqual(sorted(set(calls)), ["notify.py", "shortcut.py"])

    def test_nothing_else_builds_an_encoded_powershell_command(self):
        """One place encodes scripts; a second would be a second place to get it wrong."""
        offenders = []
        for path in (ROOT / "src" / "codex_auto_resume").glob("*.py"):
            if path.name == "pwsh.py":
                continue
            if "-EncodedCommand" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_the_shortcut_values_travel_out_of_band(self):
        with patch.object(pwsh, "executable", return_value="powershell.exe"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)) as run, \
             patch.object(shortcut, "shortcut_path", return_value=Path(tempfile.gettempdir()) / "car-test.lnk"), \
             patch.object(Path, "is_file", return_value=True):
            shortcut.install("C:\\Users\\O\u2019Brien\\app\\CodexAutoResumeSettings.exe", description="d")
        env = run.call_args.kwargs["env"]
        self.assertIn("O\u2019Brien", env[pwsh.PREFIX + "TARGET"])
        import base64
        argv = run.call_args.args[0]
        script = base64.b64decode(argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertEqual(script, shortcut._MAKER)


if __name__ == "__main__":
    unittest.main()

"""Every text call says its encoding (PEP 686: from Python 3.15 the default is UTF-8, whatever the machine's locale is).

Before 3.15 a text call with no encoding reads and writes the locale's: cp949 on a Korean Windows, cp1252 on an English one.
From 3.15 the same call means UTF-8, in strict mode: on a Korean PC `subprocess.run(["cmd", ...], text=True)` then dies in
its reader thread on the first Korean word cmd.exe prints (measured on 3.15.2 here). The sources run on 3.13, 3.14 and 3.15,
so a call means one thing on all three only if it names its encoding, and this finds the one that does not.

Which one to name, for what a program prints to a pipe:
  a Windows console program (powershell, cmd, csc, icacls, whoami, a compiled exe): encoding="locale", errors="replace". That
  is what 3.13 and 3.14 read it as, and it stays cp949 here on 3.15 even in UTF-8 mode (measured);
  Python or git: encoding="utf-8", errors="replace";
  a file of ours or of Codex's: encoding="utf-8".
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import unittest

_TESTS = str(Path(__file__).resolve().parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from test_python315_ready import ROOT, dotted, keyword, parsed  # noqa: E402

_PROCESS_CALLS = frozenset(("run", "Popen", "check_output", "check_call", "call"))
_TEMPORARY = frozenset(("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"))
# `x.open()` is many things (a menu, a measurement, a browser): only what is a path by its name is read as a file.
_PATH_LIKE = re.compile(r"(path|file)$", re.IGNORECASE)
_ARCHIVES = frozenset(("tarfile", "zipfile"))


def frozen_modules() -> set:
    """The scenario modules held byte for byte to v0.6.10 (tests/neutral.py MODULES, tests/test_released_calls.py). No edit
    may land in them, so they are the one place an old call stays: what they read from a pipe is ASCII."""
    source = (ROOT / "tests" / "neutral.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MODULES":
            return {"tests/%s.py" % name for name in ast.literal_eval(node.value)}
    raise AssertionError("tests/neutral.py has no MODULES")


def _names_encoding(call, position: int) -> bool:
    return keyword(call, "encoding") is not None or len(call.args) > position


def _opened_as_text(mode) -> bool:
    return mode is None or not isinstance(mode, ast.Constant) or "b" not in str(mode.value)


def text_call_without_encoding(call):
    """What kind of text call `call` is, when it names no encoding; None for anything else."""
    function = call.func
    name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
    whole = dotted(function)
    if name == "open" and (isinstance(function, ast.Name) or whole == "io.open"):
        mode = keyword(call, "mode") or (call.args[1] if len(call.args) > 1 else None)
        return "open" if _opened_as_text(mode) and not _names_encoding(call, 3) else None
    if name == "open" and isinstance(function, ast.Attribute):
        receiver = function.value
        pathish = isinstance(receiver, ast.BinOp) or (dotted(receiver) not in _ARCHIVES and _PATH_LIKE.search(dotted(receiver) or ""))
        mode = keyword(call, "mode") or (call.args[0] if call.args else None)
        known = mode is None or isinstance(mode, ast.Constant)
        return "Path.open" if pathish and known and _opened_as_text(mode) and not _names_encoding(call, 2) else None
    if name == "read_text":
        return "read_text" if not _names_encoding(call, 0) else None
    if name == "write_text":
        return "write_text" if not _names_encoding(call, 1) else None
    if name == "fdopen":
        mode = keyword(call, "mode") or (call.args[1] if len(call.args) > 1 else None)
        return "fdopen" if _opened_as_text(mode) and not _names_encoding(call, 3) else None
    if name == "TextIOWrapper":
        return "TextIOWrapper" if not _names_encoding(call, 1) else None
    if name in _TEMPORARY:
        mode = keyword(call, "mode") or (call.args[0] if call.args else None)
        return name if mode is not None and _opened_as_text(mode) and keyword(call, "encoding") is None else None
    if whole == "os.popen":
        return "os.popen"
    if name in _PROCESS_CALLS and (name not in ("run", "call") or whole.startswith("subprocess.")):
        if any(item.arg is None for item in call.keywords) or keyword(call, "encoding") is not None:
            return None
        for option in ("text", "universal_newlines"):
            value = keyword(call, option)
            if value is not None and not (isinstance(value, ast.Constant) and not value.value):
                return "subprocess %s=" % option
        return "subprocess errors=" if keyword(call, "errors") is not None else None
    return None


def findings(tree) -> list:
    return [(node.lineno, kind) for node in ast.walk(tree) if isinstance(node, ast.Call)
            for kind in [text_call_without_encoding(node)] if kind]


class EncodingTests(unittest.TestCase):
    def test_every_text_call_names_its_encoding(self):
        frozen = frozen_modules()
        found = ["%s:%d %s" % (name, line, kind) for name, tree in parsed() if name not in frozen for line, kind in findings(tree)]
        self.assertEqual(found, [], 'name the encoding; which one: this module\'s first lines')

    def test_the_frozen_modules_are_the_ones_the_scenarios_are(self):
        self.assertIn("tests/test_engine.py", frozen_modules())
        self.assertNotIn("tests/test_python315_encoding.py", frozen_modules())

    def test_the_reading_sees_each_kind_of_call(self):
        for source, kind in (("open(p)\n", "open"), ("open(p, 'w')\n", "open"), ("open(p, mode)\n", "open"), ("io.open(p)\n", "open"),
                             ("path.open()\n", "Path.open"), ("(a / b).open('w')\n", "Path.open"), ("p.read_text()\n", "read_text"),
                             ("p.read_text(errors='replace')\n", "read_text"), ("p.write_text('x')\n", "write_text"),
                             ("os.fdopen(f, 'w')\n", "fdopen"), ("io.TextIOWrapper(b)\n", "TextIOWrapper"),
                             ("tempfile.NamedTemporaryFile('w')\n", "NamedTemporaryFile"), ("os.popen('x')\n", "os.popen"),
                             ("subprocess.run(a, text=True)\n", "subprocess text="),
                             ("subprocess.Popen(a, universal_newlines=True)\n", "subprocess universal_newlines="),
                             ("subprocess.check_output(a, errors='replace')\n", "subprocess errors=")):
            with self.subTest(source=source):
                self.assertEqual([kind_seen for _line, kind_seen in findings(ast.parse(source))], [kind])

    def test_what_says_its_encoding_or_is_bytes_is_not_a_finding(self):
        for source in ("open(p, 'rb')\n", "open(p, encoding='utf-8')\n", "open(p, 'r', -1, 'utf-8')\n", "path.open('rb')\n",
                       "path.open(encoding='utf-8')\n", "menu.open()\n", "self.open(link)\n", "p.read_text(encoding='utf-8')\n",
                       "p.read_text('utf-8')\n", "p.write_text('x', 'utf-8')\n", "p.write_text('x', encoding='utf-8')\n",
                       "os.fdopen(f, 'wb')\n", "tempfile.NamedTemporaryFile()\n", "server.popen(a)\n", "tarfile.open(fileobj=f)\n", "subprocess.run(a)\n",
                       "subprocess.run(a, text=False)\n", "subprocess.run(a, text=True, encoding='locale')\n",
                       "subprocess.run(a, encoding='utf-8', errors='replace')\n", "harness.run(a, text=True)\n"):
            with self.subTest(source=source):
                self.assertEqual(findings(ast.parse(source)), [])


if __name__ == "__main__":
    unittest.main()

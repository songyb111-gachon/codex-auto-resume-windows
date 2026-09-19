"""Everything this product writes as JSON is strict JSON.

The settings file, the registry cache and report, a bridge reply, an MCP message, the
panel's seed, the diagnostics bundle, runtime.json: each is read by something stricter than
Python's own parser - the settings window's C#, an MCP client, serde_json in the Rust core
to come - and none of them accepts the NaN or Infinity `json.dumps` writes by default. And a
value that is not JSON at all used to be written as its str() by the bridge, the MCP server,
the panel and the bundle (`default=str`), so a path or an object reached a front end as
prose instead of failing a test.

So every writer passes allow_nan=False, and none has a `default` that turns a value into
text - except the diagnostics bundle, whose default is a deliberate redactor. The two loops
that answer a front end write a reply they cannot write as the refusal that front end
already reads, and keep answering. What they write for everything else is byte for byte
what they wrote before; tests/golden holds them to it.
"""
from __future__ import annotations

import ast
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

from codex_auto_resume import control, controlcli, diagnostics, mcpserver  # noqa: E402

# Product code outside the package that writes JSON: the installer's runtime record.
SCRIPTS = ("scripts/plugin_setup.py",)


def writers():
    """(file, qualified name, call) for every json.dump and json.dumps the product makes."""
    trees = dict(srcscan.package_asts())
    for relative in SCRIPTS:
        path = srcscan.ROOT / relative
        trees[path] = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for path, tree in trees.items():
        names = srcscan.qualnames(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("dump", "dumps")
                    and getattr(node.func.value, "id", None) in ("json", "_json")):
                where = srcscan.relative(path) if path in srcscan.package_asts() else str(path.relative_to(srcscan.ROOT))
                found.append((where.replace("\\", "/"), names.get(node, ""), node))
    return found


class WriterTests(unittest.TestCase):
    def test_there_are_writers_to_read(self):
        self.assertGreaterEqual(len(writers()), 12, "the scan found fewer writers than there are")

    def test_every_writer_refuses_nan_and_infinity(self):
        for where, name, node in writers():
            with self.subTest(where=where, name=name, line=node.lineno):
                allow = [keyword.value for keyword in node.keywords if keyword.arg == "allow_nan"]
                self.assertEqual(len(allow), 1, "no allow_nan=False")
                self.assertIsInstance(allow[0], ast.Constant)
                self.assertIs(allow[0].value, False)

    def test_only_the_diagnostics_bundle_turns_a_value_into_text_and_it_redacts_it(self):
        found = {}
        for where, name, node in writers():
            for keyword in node.keywords:
                if keyword.arg == "default":
                    found[(where, name)] = ast.unparse(keyword.value)
        self.assertEqual(found, {("codex_auto_resume/diagnostics.py", "write"): "redact.unexpected"})


class BridgeTests(unittest.TestCase):
    def serve(self, lines, reply):
        out = io.StringIO()
        with patch.object(controlcli, "dispatch", side_effect=reply):
            self.assertEqual(controlcli.serve(object(), io.StringIO("".join(line + "\n" for line in lines)), out), 0)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_a_reply_that_is_not_json_is_the_generic_refusal_and_the_loop_answers_on(self):
        replies = iter([{"ok": True, "status": object()}, {"ok": True, "result": {"x": math.nan}},
                        {"ok": True, "result": {"x": math.inf}}, {"ok": True, "status": {"fine": 1}}])
        lines = ['{"id": %d, "command": "status"}' % index for index in range(1, 5)]
        answered = self.serve(lines, lambda *arguments: next(replies))
        refusal = {"ok": False, "error": controlcli.GENERIC_ERROR, "error_code": control.FALLBACK_CODE}
        self.assertEqual(answered, [{"id": 1, "reply": refusal}, {"id": 2, "reply": refusal},
                                    {"id": 3, "reply": refusal}, {"id": 4, "reply": {"ok": True, "status": {"fine": 1}}}])

    def test_an_id_json_has_no_word_for_is_answered_as_null(self):
        answered = self.serve(['{"id": NaN, "command": "status"}', '{"id": [Infinity], "command": "status"}'],
                              lambda *arguments: {"ok": True})
        for reply in answered:
            self.assertEqual(reply, {"id": None, "reply": {"ok": False, "error": "id must be an integer",
                                                           "error_code": control.FALLBACK_CODE}})

    def test_the_one_shot_form_refuses_what_it_cannot_write(self):
        out = io.StringIO()
        with patch.object(controlcli, "dispatch", return_value={"ok": True, "status": object()}), \
                patch.object(controlcli, "Control"), patch.object(sys, "stdout", out), \
                patch.object(sys, "stdin", io.StringIO()):
            code = controlcli.main(["--home", "nowhere", "status"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue()), {"ok": False, "error": controlcli.GENERIC_ERROR,
                                                     "error_code": control.FALLBACK_CODE})


class McpTests(unittest.TestCase):
    def test_a_result_that_is_not_json_is_an_internal_error_and_the_server_answers_on(self):
        server = mcpserver.Server(object(), io.StringIO(
            '{"jsonrpc": "2.0", "id": 7, "method": "ping"}\n{"jsonrpc": "2.0", "id": 8, "method": "ping"}\n'),
            io.StringIO())
        results = iter([{"odd": object()}, {}])
        with patch.object(mcpserver.Server, "_result", staticmethod(lambda request_id, result: {
                "jsonrpc": "2.0", "id": request_id, "result": next(results)})):
            self.assertEqual(server.serve(), 0)
        answered = [json.loads(line) for line in server.stream_out.getvalue().splitlines()]
        self.assertEqual(answered, [
            {"jsonrpc": "2.0", "id": 7, "error": {"code": mcpserver.INTERNAL_ERROR,
                                                   "message": "the request could not be completed"}},
            {"jsonrpc": "2.0", "id": 8, "result": {}}])


class DiagnosticsTests(unittest.TestCase):
    def test_a_value_that_is_not_json_is_written_redacted_and_the_bundle_is_written(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        odd = Path("C:/Users/tester/secret/state.sqlite")

        def collect(control, *, now=None, redact=None):
            return {"format": "codex-auto-resume-diagnostics/1", "odd": odd}

        target = Path(temporary.name) / "d.json"
        with patch.object(diagnostics, "collect", side_effect=collect), \
                patch.dict(os.environ, {"USERNAME": "tester"}):
            diagnostics.write(object(), target)
        text = target.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text)["odd"], "<path>")
        self.assertNotIn("tester", text)

    def test_a_bundle_that_cannot_be_written_leaves_no_file_behind(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name) / "d.json"
        with patch.object(diagnostics, "collect", return_value={"rate": math.nan}):
            with self.assertRaises(ValueError):
                diagnostics.write(object(), target)
        self.assertFalse(target.exists(), "half a bundle would take the name the next attempt needs")


if __name__ == "__main__":
    unittest.main()

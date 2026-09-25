"""Every bridge command and every MCP tool answers exactly what `tests/golden` recorded.

The goldens were made from the code as it was before v0.6.5 moved any of it (`tests/wiregolden.py`
says how), and they are the acceptance test of every move since: a move that leaves the answers
byte for byte where they were has not changed the wire the window and the panel read. This file
regenerates each one and compares it with the file, and checks that there is exactly one for each
command and each tool, that making them is independent of the machine, and that making them never
started a process, wrote the registry, wrote Custom text from Codex or reached the registry
refresh from it.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import wiregolden  # noqa: E402

REGENERATE = ("the wire changed. If that was deliberate, run `python -X utf8 tests/wiregolden.py "
              "--write` and review the diff with whoever reads that field (the window, the panel, a "
              "Codex conversation); if it was not, the change is the bug")


def strings_in(value):
    """Every string in a parsed JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


class GoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.made = wiregolden.generate()

    def test_there_is_one_golden_for_each_command_and_each_tool(self):
        bridge = {name[len("bridge/"):-len(".json")] for name in self.made if name.startswith("bridge/")}
        mcp = {name[len("mcp/"):-len(".json")] for name in self.made if name.startswith("mcp/")}
        self.assertEqual(bridge - {wiregolden.BRIDGE_FRAMING}, set(wiregolden.bridge_commands()))
        self.assertEqual(mcp - {wiregolden.MCP_PROTOCOL, wiregolden.MCP_TOOL_LIST}, set(wiregolden.mcp_tools()))
        on_disk = {str(path.relative_to(wiregolden.GOLDEN)).replace(os.sep, "/")
                   for path in wiregolden.GOLDEN.rglob("*.json")}
        self.assertEqual(sorted(set(self.made) - on_disk), [],
                         "a command or tool has no golden; run python -X utf8 tests/wiregolden.py --write")
        self.assertEqual(sorted(on_disk - set(self.made)), [],
                         "a golden for a command or tool that no longer exists")

    def test_a_command_or_tool_without_cases_is_refused(self):
        for table, name in ((wiregolden.BRIDGE_CASES, "status"), (wiregolden.MCP_CASES, "get_status")):
            with self.subTest(name):
                fewer = {key: value for key, value in table.items() if key != name}
                with patch.dict(table, clear=True), self.assertRaises(LookupError) as caught:
                    table.update(fewer)
                    wiregolden.expected_files()
                self.assertIn(name, str(caught.exception))

    def test_each_answer_is_the_one_recorded(self):
        for name, text in sorted(self.made.items()):
            with self.subTest(name):
                recorded = wiregolden.recorded(name)
                self.assertIsNotNone(recorded, "no golden at tests/golden/" + name)
                if recorded != text:
                    diff = "".join(difflib.unified_diff(recorded.splitlines(True), text.splitlines(True),
                                                        "tests/golden/" + name, "the code now", n=2))
                    self.fail("%s\n%s" % (REGENERATE, diff[:6000]))

    def test_the_answers_are_the_same_from_another_root_temp_profile_and_clock(self):
        """Another scratch installation, under a temporary directory whose name has a space and
        non-ASCII letters, another profile, the product's own overrides and the engine's location
        set to values that would change the answers if anything read them, another time zone, and
        the real clock a year on."""
        names = ["bridge/status.json", "bridge/diagnostics.json", "bridge/compatibility.json",
                 "bridge/compat-refresh.json", "bridge/start-watcher.json", "mcp/get_status.json",
                 "mcp/open_settings.json"]
        with tempfile.TemporaryDirectory() as scratch:
            temp, profile = Path(scratch) / "다른 임시 é", Path(scratch) / "profile ü"
            temp.mkdir()
            profile.mkdir()
            elsewhere = {"TEMP": str(temp), "TMP": str(temp), "USERPROFILE": str(profile),
                         "CODEX_AUTO_RESUME_LANG": "fr", "TZ": "EST5EDT",
                         "CODEX_AUTO_RESUME_HOME": str(Path(scratch) / "another-home"),
                         "CODEX_AUTO_RESUME_CODEX_EXE": str(Path(scratch) / "codex.exe"),
                         "CODEX_HOME": str(Path(scratch) / "another-codex"),
                         "LOCALAPPDATA": str(Path(scratch) / "another-localappdata")}
            with patch.dict(os.environ, elsewhere), patch.object(tempfile, "tempdir", str(temp)), \
                    patch.object(time, "time", return_value=time.time() + 365 * 86400):
                again = wiregolden.generate(names)
        for name in names:
            with self.subTest(name):
                self.assertEqual(again[name], self.made[name])

    def test_the_answers_name_no_path_of_this_machine(self):
        import json
        spellings = set()
        for directory in (wiregolden.ROOT, Path(tempfile.gettempdir()), Path.home()):
            for path in (directory, directory.resolve()):
                spellings.update((str(path).lower(), path.as_posix().lower()))
        for name, text in sorted(self.made.items()):
            texts = [value.lower() for value in strings_in(json.loads(text))]
            for spelling in spellings:
                with self.subTest(name=name, spelling=spelling):
                    self.assertEqual([value for value in texts if spelling in value], [])

    def test_codex_can_neither_write_nor_preview_custom_text(self):
        """Every MCP request that names a Custom text is refused, and the tools say so up front."""
        import json
        named = 0
        for name, text in sorted(self.made.items()):
            if not name.startswith("mcp/") or "/_" in name or name.endswith(wiregolden.MCP_TOOL_LIST + ".json"):
                continue
            for case in json.loads(text)["cases"]:
                arguments = case["arguments"]
                keys = set(arguments) | set(arguments.get("changes") or {})
                if any(key.startswith("custom_message") and key != "custom_message_mode" for key in keys):
                    named += 1
                    with self.subTest(name=name, case=case["case"]):
                        self.assertIs(case["response"]["result"].get("isError"), True)
        self.assertGreaterEqual(named, 3, "the refusals this checks are no longer asked for")
        tools = json.loads(self.made["mcp/%s.json" % wiregolden.MCP_TOOL_LIST])["response"]["result"]["tools"]
        offered = set()
        for tool in tools:
            offered |= set(tool["inputSchema"].get("properties", {}))
            offered |= set(tool["inputSchema"].get("properties", {}).get("changes", {}).get("properties", {}))
        self.assertEqual(sorted(name for name in offered if name.startswith("custom_message")),
                         ["custom_message_mode"])

    def test_the_design_and_reduce_motion_are_not_codexs_to_write(self):
        """v0.6.10: the design decides what moves on every surface, as Reduce motion does, so the tool
        list offers neither (standard H3) - while every reply that carries the settings carries it."""
        import json
        tools = json.loads(self.made["mcp/%s.json" % wiregolden.MCP_TOOL_LIST])["response"]["result"]["tools"]
        update = next(tool for tool in tools if tool["name"] == "update_settings")
        self.assertNotIn("design", update["inputSchema"]["properties"])
        self.assertNotIn("reduce_motion", update["inputSchema"]["properties"])
        self.assertIn('"design": "soft"', self.made["mcp/get_status.json"])
        self.assertIn('"design": "soft"', self.made["bridge/settings.json"])

    def test_nothing_is_started_and_no_refresh_is_reachable_from_codex(self):
        from codex_auto_resume import compatio

        real = subprocess.Popen
        with wiregolden.installation(mcp=True) as (_workspace, _surface, _rewriting):
            self.assertIsNot(subprocess.Popen, real)
            self.assertIs(type(sys.modules["winreg"]), wiregolden.generator._NoRegistration)
            # Harmless even if the guard were not in place; with it, nothing starts at all.
            with self.assertRaises(wiregolden.ProcessRefused):
                subprocess.run([sys.executable, "-c", "pass"])
            for reached in (compatio.run_refresh, compatio.import_document):
                with self.assertRaises(wiregolden.RefreshReached):
                    reached(None)
        self.assertIs(subprocess.Popen, real)
        self.assertIsNot(type(sys.modules.get("winreg")), wiregolden.generator._NoRegistration)


class FramingTests(unittest.TestCase):
    """A reply line is checked as the wire writes it before it is parsed."""

    def test_a_line_written_as_the_wire_writes_it_is_taken(self):
        self.assertEqual(wiregolden._framed('{"ok": true, "text": "한국어"}\n', "t"),
                         [{"ok": True, "text": "한국어"}])
        self.assertEqual(wiregolden._framed("", "t"), [])
        # A line separator inside a value is written as itself and splits nothing on the wire.
        self.assertEqual(wiregolden._framed('{"text": "a\u2028b"}\n{"ok": false}\n', "t"),
                         [{"text": "a\u2028b"}, {"ok": False}])

    def test_any_other_writing_of_the_same_value_is_a_wire_change(self):
        for written in ('{"ok":true}\n',                        # other separators
                        '{"text": "\\ud55c"}\n',                  # escaped instead of UTF-8
                        '{"ok": true}',                           # no line feed
                        '{\n"ok": true}\n'):                      # split over lines
            with self.subTest(written), self.assertRaises((wiregolden.WireChanged, ValueError)):
                wiregolden._framed(written, "t")

    def test_the_version_and_the_directories_are_written_as_placeholders(self):
        from codex_auto_resume import config

        version = config.version()
        with tempfile.TemporaryDirectory() as scratch:
            rewriting = wiregolden._rewriting(Path(scratch))
            answer = {"version": version, "said": "v%s installed" % version,
                      "other": version + "0", "longer": version + ".1",
                      "path": str(Path(scratch) / "home")}
            self.assertEqual(wiregolden.canonical(answer, rewriting),
                             {"version": "<version>", "said": "v<version> installed",
                              "other": version + "0", "longer": version + ".1",
                              "path": "<scratch>" + os.sep + "home"})


if __name__ == "__main__":
    unittest.main()

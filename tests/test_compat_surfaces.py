"""Where the Compatibility Registry shows, and where it must not reach.

The bridge commands the window will call, the command line, MCP, the diagnostics bundle,
the release archive - and the negative rules: no MCP tool refreshes or imports registry
data, no `experimental_*` setting can ever appear in what a model may change, and the
Python side still reaches no network at all.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from test_compat_characterization import FakeCodex, Fixture  # noqa: E402
from codex_auto_resume import (compat, compatio, config, control, controlcli, diagnostics,  # noqa: E402
                               mcpserver, settings, windows)

ROOT = Path(__file__).resolve().parents[1]


def a_document(sequence=5, **extra):
    value = {"format": compat.FORMAT, "sequence": sequence, "published_at": "2026-09-18T00:00:00Z",
             "expires_at": "2027-06-01T00:00:00Z", "min_product": "0.6.4",
             "requires_signature": False, "engines": [], "advisories": []}
    value.update(extra)
    return value


REFRESH_HOST = "raw.githubusercontent.com"


def documentation_gaps(texts) -> list:
    """What the privacy and security documents still owe the compatibility refresh.

    Shape-based, like tests/test_privacy_claims.py: names and nearby qualifiers rather than
    exact sentences, so a rewrite that is still true passes and one that is not fails."""
    privacy, security = texts.get("PRIVACY.md", ""), texts.get("SECURITY.md", "")
    gaps = []
    if REFRESH_HOST not in privacy:
        gaps.append("PRIVACY.md does not name %s" % REFRESH_HOST)
    else:
        near = [privacy[max(0, at - 600):at + 600]
                for at in (m.start() for m in re.finditer(re.escape(REFRESH_HOST), privacy))]
        if not any(re.search(r"(?i)press|button|only when|on request|\bask", window) for window in near):
            gaps.append("PRIVACY.md does not say the refresh happens only when asked")
    for name in ("compat-cache.json", "compatibility.json"):
        if name not in privacy:
            gaps.append("PRIVACY.md does not name config/%s" % name)
    checks = [m.start() for m in re.finditer(r"(?i)check for updates", privacy)]
    if checks and not any(re.search(r"(?i)compatibility", privacy[max(0, at - 800):at + 800])
                          for at in checks):
        gaps.append("PRIVACY.md describes Check for updates without the refresh it now makes")
    if not re.search(r"(?i)compatibility (?:data )?refresh", security):
        gaps.append("SECURITY.md does not name the compatibility refresh")
    for name in ("PRIVACY.ko.md", "SECURITY.ko.md"):
        if REFRESH_HOST not in texts.get(name, ""):
            gaps.append("%s does not name %s" % (name, REFRESH_HOST))
    gaps.extend(status_disclosure_gaps(texts))
    return gaps


def status_item(text):
    """The list item PRIVACY.md (or its Korean pair) gives `get_status`, or None: from its
    bullet to the next bullet or the blank line that ends the list."""
    found = re.search(r"^- [^\n]*`get_status`.*?(?=^- |^[ \t]*$)", text or "", re.M | re.S)
    return found.group(0) if found else None


def status_disclosure_gaps(texts) -> list:
    """What PRIVACY.md and PRIVACY.ko.md owe the compatibility summary `get_status` carries.

    `get_status` (and `open_settings`, which returns the same status) puts compat.mcp_view's
    summary into the Codex conversation, which Codex sends on. The item that says what
    `get_status` returns must name the summary and say it is codes only. Shape-based, and in
    either language, because the generated `ko` branch holds Korean under the English name."""
    gaps = []
    for name in ("PRIVACY.md", "PRIVACY.ko.md"):
        item = status_item(texts.get(name, ""))
        if item is None:
            gaps.append("%s has no item saying what get_status returns" % name)
        elif not re.search(r"(?i)compatibility|호환", item):
            gaps.append("%s: get_status's item does not name the compatibility summary" % name)
        elif not re.search(r"(?i)\bcodes\b|코드", item):
            gaps.append("%s: get_status's item does not say the summary is codes only" % name)
    return gaps


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        self.control = control.Control(self.fixture.paths)
        for name, value in (("watcher_running", False), ("startup_enabled", False)):
            guard = patch.object(control.Control, name, return_value=value)
            guard.start()
            self.addCleanup(guard.stop)

    def dispatch(self, command, payload=None):
        return controlcli.dispatch(self.control, command, payload or {})

    def test_the_report_view_before_any_watcher_ran(self):
        reply = self.dispatch("compatibility")
        self.assertIs(reply["ok"], True)
        view = reply["compatibility"]
        self.assertEqual((view["status"], view["overall"], view["live"]), ("absent", "unknown", False))
        self.assertEqual(set(view["capabilities"]), set(compat.CAPABILITIES))

    def test_the_report_view_after_the_watcher_wrote_one(self):
        self.fixture.backend()
        view = self.dispatch("compatibility")["compatibility"]
        self.assertEqual((view["status"], view["overall"]), ("ok", "structurally_compatible"))
        text = json.dumps(view)
        self.assertNotIn(str(self.fixture.exe), text)
        self.assertNotIn(compatio.path_digest(self.fixture.exe), text)

    def test_a_live_check_on_request(self):
        view = self.dispatch("compatibility", {"live": True})["compatibility"]
        self.assertIs(view["live"], True)
        self.assertEqual(view["overall"], "structurally_compatible")
        for bad in ("true", 1, None, []):
            self.assertIs(self.dispatch("compatibility", {"live": bad})["ok"], False, bad)

    def test_import_through_the_one_shot_form_the_bootstrap_uses(self):
        download = Path(self.fixture.folder.name) / "download" / "codex_compat.json"
        download.parent.mkdir()
        download.write_text(json.dumps(a_document()), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = controlcli.main(["--home", str(self.fixture.paths.home), "compat-import",
                                    "--file", str(download), "--origin", "main"])
        reply = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(reply["result"]["imported"], True)
        self.assertEqual(reply["result"]["sequence"], 5)
        self.assertTrue(self.fixture.paths.compat_cache_file.is_file())

    def test_a_refused_import_is_an_answer_with_a_code(self):
        download = Path(self.fixture.folder.name) / "bad.json"
        download.write_text('{"format": "codex-auto-resume-compat/9"}', encoding="utf-8")
        reply = self.dispatch("compat-import", {"path": str(download)})
        self.assertIs(reply["ok"], True)
        self.assertEqual((reply["result"]["imported"], reply["result"]["reason"]),
                         (False, "unknown_format"))
        self.assertNotIn(str(download), json.dumps(reply), "the answer never echoes the file")
        for payload in ({}, {"path": 7}, {"path": str(download), "origin": "internet"}):
            self.assertIs(self.dispatch("compat-import", payload)["ok"], False, payload)

    def test_the_refresh_reports_the_bootstrap_answer_and_a_fresh_view(self):
        with patch.object(compatio, "run_refresh",
                          return_value={"answer": "refreshed", "sequence": 7, "reason": None}) as run:
            reply = self.dispatch("compat-refresh")
        run.assert_called_once_with(self.fixture.paths.home)
        result = reply["result"]
        self.assertEqual((result["answer"], result["sequence"]), ("refreshed", 7))
        self.assertIs(result["compatibility"]["live"], True)

    def test_every_new_command_is_reachable_the_same_two_ways(self):
        parser = controlcli.build_parser()
        for name in ("compatibility", "compat-import", "compat-refresh"):
            self.assertIn(name, controlcli.WITH_ARGUMENT)
            parser.parse_args([name])


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        self.addCleanup(self._reset_logging)

    @staticmethod
    def _reset_logging():
        import logging
        logger = logging.getLogger("codex_auto_resume")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def cli(self, *argv):
        from codex_auto_resume import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--home", str(self.fixture.paths.home), "--quiet",
                             "--codex-home", str(self.fixture.home.root), *argv])
        return code, out.getvalue()

    def test_compat_reads_the_report(self):
        code, out = self.cli("compat")
        self.assertEqual(code, 0)
        self.assertIn("compatibility    : unknown (no report yet", out)
        self.fixture.backend()
        code, out = self.cli("compat")
        self.assertIn("compatibility    : structurally_compatible (report ok", out)
        self.assertIn("exact_thread_recovery", out)

    def test_compat_live_and_json(self):
        code, out = self.cli("compat", "--live", "--json")
        self.assertEqual(code, 0)
        view = json.loads(out)
        self.assertEqual((view["overall"], view["live"]), ("structurally_compatible", True))

    def test_compat_import(self):
        download = Path(self.fixture.folder.name) / "d.json"
        download.write_text(json.dumps(a_document()), encoding="utf-8")
        code, out = self.cli("compat", "--import", str(download))
        self.assertEqual(code, 0)
        self.assertIn("imported registry data #5", out)
        download.write_text("{}", encoding="utf-8")
        code, out = self.cli("compat", "--import", str(download))
        self.assertEqual(code, 1)
        self.assertIn("refused: unknown_format", out)

    def test_status_and_doctor_say_it(self):
        from codex_auto_resume import startup
        # Nothing about the machine's own registrations is read, and no process inventory runs.
        with patch.object(windows.Backend, "app_identity", return_value=None),              patch.object(startup, "current_value", return_value=None),              patch.object(startup, "protocol_value", return_value=None):
            code, out = self.cli("status")
            self.assertIn("compatibility    :", out)
            code, out = self.cli("doctor")
        self.assertIn("compatibility    : structurally_compatible (checked now)", out)
        self.assertIn("watcher's report :", out)
        self.assertIn("compatible: its local checks pass", out)

    def import_verified(self):
        claim = {"state": "VERIFIED", "evidence": ["docs/evidence/loaded-thread-delivery.json"]}
        download = Path(self.fixture.folder.name) / "verified.json"
        download.write_text(json.dumps(a_document(9, engines=[{
            "version": "codex-cli 0.155.0",
            "capabilities": {"engine_present": claim, "exact_thread_recovery": claim}}])),
            encoding="utf-8")
        self.assertTrue(compatio.import_document(self.fixture.paths, download)["imported"])

    def test_status_doctor_and_the_log_agree_with_the_registry_data_in_force(self):
        """The engine line used to read the bundled baseline alone, so after a refresh that
        verified this build it said 'no registry entry verifies this build' two lines above
        'compatibility: verified'. Every surface now says what the gate reads."""
        from codex_auto_resume import startup
        self.import_verified()
        with patch.object(windows.Backend, "app_identity", return_value=None), \
             patch.object(startup, "current_value", return_value=None), \
             patch.object(startup, "protocol_value", return_value=None):
            _, status = self.cli("status")
            _, doctor = self.cli("doctor")
        for out in (status, doctor):
            self.assertNotIn("not a verified build", out)
            self.assertNotIn("does not verify this build", out)
            self.assertNotIn("no registry entry", out)
        self.assertIn("codex-cli 0.155.0  (verified", status)
        self.assertIn("engine version   : codex-cli 0.155.0 (verified", doctor)
        self.assertIn("compatibility    : verified (checked now)", doctor)

    def test_an_advisory_is_named_on_the_engine_line_too(self):
        from codex_auto_resume import startup
        download = Path(self.fixture.folder.name) / "advisory.json"
        download.write_text(json.dumps(a_document(9, advisories=[{
            "id": "CAR-2026-0100", "match": {"version_gte": "0.0.0"}, "state": "INCOMPATIBLE",
            "capabilities": ["exact_thread_recovery"], "reason": "queue_interface_changed"}])),
            encoding="utf-8")
        self.assertTrue(compatio.import_document(self.fixture.paths, download)["imported"])
        with patch.object(windows.Backend, "app_identity", return_value=None), \
             patch.object(startup, "current_value", return_value=None), \
             patch.object(startup, "protocol_value", return_value=None):
            _, status = self.cli("status")
            _, doctor = self.cli("doctor")
        self.assertIn("marks this build incompatible", status)
        self.assertIn("marks this build incompatible", doctor)
        self.assertIn("compatibility    : incompatible (checked now)", doctor)

    def test_the_start_up_log_says_what_the_registry_data_in_force_says(self):
        said = []
        self.fixture.app.logger = MagicMock(
            info=lambda *args: said.append(args[0] % args[1:] if len(args) > 1 else args[0]))
        self.fixture.app.backend()
        self.assertTrue([line for line in said if line.startswith("engine codex-cli 0.155.0 ")], said)
        self.assertFalse([line for line in said if "no registry entry" in line])
        self.assertTrue([line for line in said if "does not verify this build" in line])
        self.import_verified()
        self.fixture.app._backend = None
        said.clear()
        self.fixture.app.backend()
        engine_lines = [line for line in said if line.startswith("engine codex-cli 0.155.0 ")]
        self.assertEqual(len(engine_lines), 1, said)
        self.assertIn("verifies this build", engine_lines[0])
        self.assertNotIn("does not verify", engine_lines[0])


class McpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        self.control = control.Control(self.fixture.paths)
        for name, value in (("watcher_running", True), ("startup_enabled", False)):
            guard = patch.object(control.Control, name, return_value=value)
            guard.start()
            self.addCleanup(guard.stop)

    def call(self, name):
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": {}}}) + "\n"
        out = io.StringIO()
        mcpserver.Server(self.control, io.StringIO(line), out).serve()
        return json.loads(out.getvalue())["result"]

    def test_get_status_carries_the_summary_codes_only(self):
        self.fixture.backend()
        status = self.call("get_status")["structuredContent"]
        summary = status["watcher"]["compatibility"]
        self.assertEqual(set(summary), {"status", "overall", "acting", "source", "sequence", "cache",
                                        "checked_at", "capabilities"})
        self.assertEqual((summary["status"], summary["overall"]), ("ok", "structurally_compatible"))
        self.assertEqual((summary["source"], summary["sequence"]), ("bundled", 1))
        text = json.dumps(summary)
        for leak in ("codex-cli", str(self.fixture.exe), compatio.path_digest(self.fixture.exe),
                     str(self.fixture.paths.home)):
            self.assertNotIn(leak, text)
        for entry in summary["capabilities"].values():
            self.assertIn(entry["reason"], compat.REASONS)

    def test_no_tool_can_refresh_or_import_registry_data(self):
        names = [tool["name"] for tool in mcpserver.TOOLS]
        self.assertFalse([name for name in names if re.search(r"compat|registry|refresh|import|fetch", name)])
        source = (ROOT / "src" / "codex_auto_resume" / "mcpserver.py").read_text(encoding="utf-8")
        for forbidden in ("compat-import", "compat-refresh", "run_refresh", "import_document",
                          "bootstrap.ps1"):
            self.assertNotIn(forbidden, source)

    def test_no_experimental_setting_can_ever_be_offered_to_a_model(self):
        """M9, for v0.6.6's opt-ins. The schema is generated from the settings module, so a
        field in a user group would be exposed with no further review; this is the rule that
        stops that, written before any such field exists."""
        properties = mcpserver.settings_schema()["properties"]
        self.assertFalse([name for name in properties if name.startswith("experimental")])
        for entry in settings.describe():
            if entry["name"].startswith("experimental"):
                self.assertNotIn(entry.get("group"), mcpserver.USER_GROUPS, entry["name"])
                self.assertNotIn(entry["name"], mcpserver.PANEL_APPEARANCE)
        self.assertNotIn("windows", mcpserver.USER_GROUPS)
        self.assertNotIn("advanced", mcpserver.USER_GROUPS)

    def test_the_negative_rule_would_catch_a_leak(self):
        leaked = list(settings.describe()) + [{"name": "experimental_not_loaded_recovery",
                                               "group": "recovery", "type": "boolean"}]
        with patch.object(settings, "describe", return_value=leaked):
            properties = mcpserver.settings_schema()["properties"]
        self.assertIn("experimental_not_loaded_recovery", properties,
                      "the schema is generated, so the guard has to be the test above")


class DiagnosticsTests(unittest.TestCase):
    def test_the_bundle_carries_the_view_and_no_binding(self):
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        fixture.backend()
        ctl = control.Control(fixture.paths)
        with patch.object(control.Control, "watcher_running", return_value=False), \
             patch.object(control.Control, "startup_enabled", return_value=False), \
             patch.object(diagnostics, "_installation", return_value={}):
            bundle = diagnostics.collect(ctl)
        view = bundle["compatibility"]
        self.assertEqual(view["overall"], "structurally_compatible")
        text = json.dumps(view)
        self.assertNotIn(compatio.path_digest(fixture.exe), text)
        self.assertNotIn(str(fixture.paths.home), text)


class PrivacyTests(unittest.TestCase):
    BOOTSTRAP = ROOT / "scripts" / "bootstrap.ps1"

    def constant(self, name):
        match = re.search(r"^\$" + name + r" = (.+)$", self.BOOTSTRAP.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(match, name)
        return match.group(1).strip()

    def test_the_refresh_url_is_one_constant_with_nothing_about_the_machine_in_it(self):
        url = self.constant("CompatibilityUrl").strip("'")
        release = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(url, "https://raw.githubusercontent.com/%s/%s/main/src/codex_auto_resume/data/"
                              "codex_compat.json" % (release["owner"], release["repo"]))
        for forbidden in ("?", "{", "$", "%", "#"):
            self.assertNotIn(forbidden, url)
        self.assertEqual(self.constant("CompatibilityHosts"), "@('raw.githubusercontent.com')")
        # The archive's own list did not grow.
        self.assertEqual(self.constant("AllowedHosts"),
                         "@('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')")

    def test_the_fetched_path_is_the_bundled_file(self):
        url = self.constant("CompatibilityUrl").strip("'")
        self.assertTrue(url.endswith("/" + str(compatio.BUNDLED.relative_to(ROOT)).replace("\\", "/")))

    def test_the_registry_modules_import_no_networking_module(self):
        pattern = re.compile(r"^\s*(?:import|from)\s+(socket|ssl|http|urllib\.request|requests|"
                             r"httpx|aiohttp|ftplib|webbrowser)\b", re.M)
        for name in ("compat.py", "compatio.py"):
            text = (ROOT / "src" / "codex_auto_resume" / name).read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(text), name)
            self.assertNotIn("Invoke-WebRequest", text)

    def test_the_pure_model_touches_no_file_and_no_process(self):
        text = (ROOT / "src" / "codex_auto_resume" / "compat.py").read_text(encoding="utf-8")
        for forbidden in ("open(", "subprocess", "import os", "Path(", "sqlite3"):
            self.assertNotIn(forbidden, text)

    def test_the_gap_rule_knows_a_documented_refresh_from_an_undocumented_one(self):
        undocumented = {"PRIVACY.md": "Pressing *Check for updates* makes one HTTPS request. "
                                      "It is a HEAD request, so no page is read.",
                        "SECURITY.md": "No update check runs unless you press the button.",
                        "PRIVACY.ko.md": "", "SECURITY.ko.md": ""}
        self.assertEqual(len(documentation_gaps(undocumented)), 9)
        documented = {
            "PRIVACY.md": "Pressing *Check for updates* asks github.com, and then fetches the Codex "
                          "compatibility data from raw.githubusercontent.com - only when you press "
                          "it. The result is kept in config/compat-cache.json, and the watcher "
                          "writes config/compatibility.json.\n\n"
                          "- from `get_status`: the version and, as codes only, the Codex "
                          "compatibility summary;\n",
            "SECURITY.md": "No update check and no compatibility refresh runs unless you press "
                           "the button; the data comes from raw.githubusercontent.com.",
            "PRIVACY.ko.md": "raw.githubusercontent.com compat-cache.json\n\n"
                             "- `get_status`: 버전, 그리고 코드로만 된 Codex 호환성 요약;\n",
            "SECURITY.ko.md": "raw.githubusercontent.com"}
        self.assertEqual(documentation_gaps(documented), [])

    def test_the_status_rule_reads_the_get_status_item_and_nothing_else(self):
        item = ("- from `get_status`: the version, and the Codex compatibility summary as codes;\n"
                "  a second line of the same item;\n")
        text = "Tools: `get_status`, `list_pending` and more.\n\n" + item + "- from `list_pending`: rows.\n"
        self.assertEqual(status_item(text), item)
        self.assertEqual(status_disclosure_gaps({"PRIVACY.md": text, "PRIVACY.ko.md": text}), [])
        # The summary named anywhere but in get_status's own item does not count.
        elsewhere = ("- from `get_status`: the version and your settings;\n"
                     "- from `list_pending`: the compatibility summary, codes only;\n")
        self.assertEqual(status_disclosure_gaps({"PRIVACY.md": elsewhere, "PRIVACY.ko.md": item}),
                         ["PRIVACY.md: get_status's item does not name the compatibility summary"])
        unqualified = "- from `get_status`: the version and the compatibility summary;\n"
        self.assertEqual(status_disclosure_gaps({"PRIVACY.md": unqualified, "PRIVACY.ko.md": item}),
                         ["PRIVACY.md: get_status's item does not say the summary is codes only"])
        self.assertEqual(status_disclosure_gaps({"PRIVACY.md": item}),
                         ["PRIVACY.ko.md has no item saying what get_status returns"])

    def test_privacy_names_the_compatibility_summary_get_status_returns(self):
        """Binding now, not at the version bump: get_status has carried compat.mcp_view's summary
        since it was written (v0.6.5's registry work), and every call puts it into a conversation
        Codex sends to OpenAI, so the document that lists what get_status returns must say so for
        as long as the code does. A Korean pair that exists must say it too."""
        summary = compat.mcp_view(compat.unusable_view("absent"))
        self.assertTrue({"status", "overall", "acting", "source", "sequence", "cache", "checked_at",
                         "capabilities"} >= set(summary))
        texts = {name: (ROOT / name).read_text(encoding="utf-8")
                 for name in ("PRIVACY.md", "PRIVACY.ko.md") if (ROOT / name).is_file()}
        self.assertIn("PRIVACY.md", texts)
        texts.setdefault("PRIVACY.ko.md", texts["PRIVACY.md"])
        self.assertEqual(status_disclosure_gaps(texts), [])

    def test_the_documents_name_the_refresh_before_it_ships(self):
        """The refresh is a request PRIVACY.md does not describe yet: it still says the
        update check is one HEAD request that reads no page. PLAN §5.10 puts the documents
        in the same release as the refresh, and this makes that a rule rather than a memory:
        binding from the version bump past 0.6.4 - the last version without the refresh - so
        a release cannot go out with the old sentence standing. Skipped, saying so, before."""
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
        if compat.product_key(manifest["version"]) <= (0, 6, 4):
            self.skipTest("binding from the version bump past 0.6.4: PRIVACY.md, SECURITY.md and "
                          "their .ko.md pairs must name the compatibility refresh before it ships")
        texts = {name: (ROOT / name).read_text(encoding="utf-8") if (ROOT / name).is_file() else ""
                 for name in ("PRIVACY.md", "SECURITY.md", "PRIVACY.ko.md", "SECURITY.ko.md")}
        self.assertEqual(documentation_gaps(texts), [])


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "build"))
        self.addCleanup(sys.path.remove, str(ROOT / "build"))
        import make_release
        self.builder = make_release

    def test_the_release_carries_the_bundled_data(self):
        self.assertIn("src/codex_auto_resume/data/codex_compat.json", self.builder.REQUIRED_APP_FILES)
        for name in self.builder.REQUIRED_APP_FILES:
            self.assertTrue(self.builder._wanted(Path(name)), name)
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertIn(Path(name).parts[0], self.builder.APP_TREES)

    def test_a_payload_without_valid_data_stops_the_build(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            target = stage / "payload" / "app" / "src" / "codex_auto_resume" / "data" / "codex_compat.json"
            with self.assertRaises(SystemExit):
                self.builder.check_app_files(stage)
            target.parent.mkdir(parents=True)
            target.write_text('{"format": "codex-auto-resume-compat/1"}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.builder.check_app_files(stage)
            target.write_bytes(compatio.BUNDLED.read_bytes())
            self.builder.check_app_files(stage)

    def test_the_smoke_test_checks_the_shipped_data(self):
        text = (ROOT / "build" / "smoke_archive.py").read_text(encoding="utf-8")
        self.assertIn('"codex_compat.json"', text)
        self.assertIn('"compat"', text)
        self.assertIn("LOCALAPPDATA=str(workspace / \"no-engines\")", text,
                      "the smoke test must not start the machine's own Codex")


if __name__ == "__main__":
    unittest.main()

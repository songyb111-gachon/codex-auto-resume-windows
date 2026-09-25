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
import languages  # noqa: E402
import srcscan  # noqa: E402
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

# The documents these rules read, by the name their messages use. The privacy policy moved into
# docs/ with the rest when the front page was tidied; the names stay what a reader recognises.
DOCUMENTS = {"PRIVACY.md": "docs/PRIVACY.md", "PRIVACY.ko.md": "docs/PRIVACY.ko.md"}


def read(name: str) -> str:
    return (ROOT / DOCUMENTS.get(name, name)).read_text(encoding="utf-8")


def generated_ko_branch() -> bool:
    """Whether this checkout is the generated `ko` branch. There, each Korean document has been
    written over its English sibling and removed, so the root PRIVACY.md and SECURITY.md are the
    Korean text and there is no English to hold to English wording. This module did not ask once,
    and it was the one failure that kept ko from syncing. `tests/languages.py` answers it for
    every test, together with the other question - whether this is English-only main."""
    return languages.generated_ko_branch()


def documentation_gaps(texts) -> list:
    """What the privacy and security documents still owe the compatibility refresh.

    Shape-based, like tests/test_privacy_claims.py: names and nearby qualifiers rather than
    exact sentences, so a rewrite that is still true passes and one that is not fails."""
    privacy, security = texts.get("PRIVACY.md", ""), texts.get("docs/SECURITY.md", "")
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
    # The Korean pair, when the texts hold it: dev does; main is English only, and its
    # Korean halves are dev's to answer. A Korean key given as "" is still a Korean text that
    # says nothing, and is a gap.
    for name in ("PRIVACY.ko.md", "docs/SECURITY.ko.md"):
        if name in texts and REFRESH_HOST not in texts[name]:
            gaps.append("%s does not name %s" % (name, REFRESH_HOST))
    gaps.extend(status_disclosure_gaps(texts, korean="PRIVACY.ko.md" in texts))
    return gaps


def status_item(text):
    """The list item PRIVACY.md (or its Korean pair) gives `get_status`, or None: from its
    bullet to the next bullet or the blank line that ends the list."""
    found = re.search(r"^- [^\n]*`get_status`.*?(?=^- |^[ \t]*$)", text or "", re.M | re.S)
    return found.group(0) if found else None


def status_disclosure_gaps(texts, korean: bool = True) -> list:
    """What PRIVACY.md and PRIVACY.ko.md owe the compatibility summary `get_status` carries.

    `get_status` (and `open_settings`, which returns the same status) puts compat.mcp_view's
    summary into the Codex conversation, which Codex sends on. The item that says what
    `get_status` returns must name the summary and say it is codes only. Shape-based, and in
    either language, because the generated `ko` branch holds Korean under the English name.
    `korean=False` on English-only main, where PRIVACY.ko.md does not exist; anywhere else a
    missing Korean item is a gap, never a pass by substitution."""
    gaps = []
    for name in ("PRIVACY.md", "PRIVACY.ko.md") if korean else ("PRIVACY.md",):
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

    def test_doctor_and_compat_say_what_others_report_and_decide_nothing_by_it(self):
        """One line beside the version (v0.6.10), saying it is others' reports and changes nothing - and
        it does not: doctor's answer and every other line are the same whatever the counts claim."""
        from codex_auto_resume import startup
        from codex_auto_resume.compat import reported
        version = "codex-cli 0.155.0"
        folder = Path(self.fixture.folder.name) / "counts"
        folder.mkdir()
        self.fixture.backend()
        said = {}
        for name, entries in (("none_yet", ()), ("worked", ((version, 1000, 0, 0, 0),)),
                              ("failed", ((version, 0, 1000, 0, 0),)), ("both", ((version, 3, 2, 1, 1),))):
            with patch.object(reported, "BUNDLED", counts_file(folder, *entries)), \
                 patch.object(windows.Backend, "app_identity", return_value=None), \
                 patch.object(startup, "protocol_value", return_value=None):
                said[name] = (self.cli("doctor"), self.cli("compat"))
        lines = {name: [line for line in doctor[1].splitlines() + compat_[1].splitlines()
                        if line.startswith("reported ")] for name, (doctor, compat_) in said.items()}
        self.assertEqual(lines["none_yet"], ["reported         : none yet (others' reports; changes nothing)"] * 2)
        self.assertEqual(lines["failed"], ["reported         : worked 0, failed 1000, neither 0 "
                                           "(others' reports; changes nothing)"] * 2)
        self.assertEqual(lines["both"], ["reported         : worked 3, failed 2, neither 1, counted in both 1 "
                                         "(others' reports; changes nothing)"] * 2)
        rest = {name: ([line for line in doctor[1].splitlines() if not line.startswith("reported ")], doctor[0],
                       [line for line in compat_[1].splitlines() if not line.startswith("reported ")], compat_[0])
                for name, (doctor, compat_) in said.items()}
        self.assertEqual(rest["worked"], rest["none_yet"])
        self.assertEqual(rest["failed"], rest["none_yet"])
        self.assertEqual(rest["both"], rest["none_yet"])

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
        self.assertEqual((summary["source"], summary["sequence"]),
                         ("bundled", compatio.load_bundled()[0]["sequence"]))
        text = json.dumps(summary)
        for leak in ("codex-cli", str(self.fixture.exe), compatio.path_digest(self.fixture.exe),
                     str(self.fixture.paths.home)):
            self.assertNotIn(leak, text)
        for entry in summary["capabilities"].values():
            self.assertIn(entry["reason"], compat.REASONS)

    def test_no_tool_can_refresh_or_import_registry_data(self):
        names = [tool["name"] for tool in mcpserver.TOOLS]
        self.assertFalse([name for name in names if re.search(r"compat|registry|refresh|import|fetch", name)])
        # Every file of the MCP server, however it is split...
        for path in srcscan.files_of("codex_auto_resume.mcpserver", "codex_auto_resume.mcp"):
            source = srcscan.read(path)
            for forbidden in ("compat-import", "compat-refresh", "run_refresh", "import_document",
                              "bootstrap.ps1"):
                self.assertNotIn(forbidden, source)
        # ...and the whole package: each of these words lives exactly where it always has, so a
        # tool body moved out of mcpserver.py cannot take one with it unseen. (The panel's
        # `compat-refresh` is the CSS class of a help paragraph, not a command.)
        package = "codex_auto_resume/%s.py"
        # v0.6.10-alpha moved the panel's stylesheet and script out of `mcpui.py` into
        # `mcp/assets/`, and `srcscan.holders` reads those too - so `compat-refresh`, which is
        # the CSS class of a help paragraph, is found where it now lives rather than nowhere.
        for forbidden, holders in (("compat-import", {package % "controlcli"}),
                                   ("compat-refresh", {package % "controlcli",
                                                       "codex_auto_resume/mcp/assets/panel.css",
                                                       "codex_auto_resume/mcp/assets/panel.js"}),
                                   # compat/ holds the registry's io half since v0.6.10-alpha:
                                   # the refresh in evaluator.py, the one writer in cache.py, the
                                   # bootstrap's answers in files.py. compatio.py is their front.
                                   ("run_refresh", {package % "compatio", package % "controlcli",
                                                    "codex_auto_resume/compat/evaluator.py"}),
                                   ("import_document", {"codex_auto_resume/commands/status.py", package % "compatio",
                                                        package % "controlcli",
                                                        "codex_auto_resume/compat/cache.py",
                                                        "codex_auto_resume/compat/evaluator.py"}),
                                   ("bootstrap.ps1", {package % "compatio", package % "controlcli",
                                                      "codex_auto_resume/compat/evaluator.py",
                                                      "codex_auto_resume/compat/files.py"})):
            with self.subTest(forbidden):
                self.assertEqual(srcscan.holders(forbidden), holders)

    def test_no_experimental_setting_can_ever_be_offered_to_a_model(self):
        """M9, for v0.6.11's opt-ins. The schema is generated from the settings module, so a
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


def counts_file(folder, *entries) -> Path:
    """A counts file of Reported's own format, in `folder`, holding `entries` (version, worked,
    failed, neither, both); the reports each adds up to follow from the counting rule."""
    from codex_auto_resume.compat import reported
    versions = [{"version": version, "reports": worked + failed - both + neither, "worked": worked,
                 "failed": failed, "neither": neither, "both": both}
                for version, worked, failed, neither, both in entries]
    path = Path(folder) / ("reported-%d.json" % len(list(Path(folder).glob("reported-*.json"))))
    path.write_text(json.dumps({"format": reported.FORMAT, "versions": versions}), encoding="utf-8")
    return path


def keys_anywhere(value) -> set:
    """Every key of every object in a parsed JSON value."""
    if isinstance(value, dict):
        return set(value).union(*(keys_anywhere(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_anywhere(item) for item in value))
    return set()


class ReportedTests(unittest.TestCase):
    """What others report, beside the version (v0.6.10): on every view a person reads - the bridge's,
    the command line's, the diagnostics bundle's - and never in what a model reads."""

    VERSION = "codex-cli 0.155.0"

    def setUp(self):
        from codex_auto_resume.compat import reported
        self.reported = reported
        self.fixture = Fixture(self, codex=FakeCodex(version=self.VERSION))
        self.control = control.Control(self.fixture.paths)
        for name, value in (("watcher_running", True), ("startup_enabled", False)):
            guard = patch.object(control.Control, name, return_value=value)
            guard.start()
            self.addCleanup(guard.stop)
        self.folder = Path(self.fixture.folder.name) / "counts"
        self.folder.mkdir()

    def counts(self, *entries):
        """Reported's counts are `entries` for as long as the test runs."""
        guard = patch.object(self.reported, "BUNDLED", counts_file(self.folder, *entries))
        guard.start()
        self.addCleanup(guard.stop)

    def view(self, **payload):
        return controlcli.dispatch(self.control, "compatibility", payload)["compatibility"]

    def test_a_usable_view_carries_the_counts_of_its_exact_version(self):
        self.counts((self.VERSION, 2, 1, 0, 1), ("codex-cli 0.153.4", 9, 9, 9, 0))
        self.fixture.backend()
        view = self.view()
        self.assertEqual(view["status"], "ok")
        self.assertEqual(view["reported"], {"state": "reported", "reports": 2, "worked": 2, "failed": 1,
                                            "neither": 0, "both": 1})
        self.assertEqual(self.view(live=True)["reported"], view["reported"], "a live check says the same")

    def test_each_state_it_can_be_in(self):
        self.fixture.backend()
        self.counts(("codex-cli 0.153.4", 1, 0, 0, 0))
        self.assertEqual(self.view()["reported"]["state"], "none_yet", "counts, but none for this version")
        broken = self.folder / "broken.json"
        broken.write_bytes(b'{"format": "codex-auto-resume-reported/1", "versions": [{"version": 7}]}')
        with patch.object(self.reported, "BUNDLED", broken):
            self.assertEqual(self.view()["reported"]["state"], "rejected")
        with patch.object(self.reported, "BUNDLED", self.folder / "absent.json"):
            self.assertEqual(self.view()["reported"]["state"], "unavailable")

    def test_a_view_that_cannot_be_used_vouches_for_no_version(self):
        """No report, one too old, or Codex changed under it: `unavailable`, with no counts - as the
        window says "-" for the version then - however many reports name the version it was about."""
        self.counts((self.VERSION, 5, 5, 0, 5))
        before = self.view()
        self.assertEqual((before["status"], before["reported"]["state"]), ("absent", "unavailable"))
        self.fixture.backend()
        stale = compatio.read_view(self.fixture.paths, now=10 ** 10)
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["engine"]["version"], self.VERSION, "the version it was about is still named")
        self.assertEqual(stale["reported"], dict.fromkeys(stale["reported"], 0) | {"state": "unavailable"})

    def test_no_engine_found_is_unavailable(self):
        self.counts((self.VERSION, 1, 0, 0, 0))
        from codex_auto_resume.compat import views
        view = {"status": "ok", "engine": {"found": False, "version": self.VERSION}}
        self.assertEqual(views.reported_for(view)["state"], "unavailable")

    def test_a_model_is_never_handed_it(self):
        """get_status and open_settings carry the summary, codes only, with the same keys as before;
        no key anywhere in either reply is `reported`, and no count of anyone's reports is in it."""
        self.counts((self.VERSION, 777, 555, 333, 111))
        self.fixture.backend()
        self.assertEqual(self.view()["reported"]["worked"], 777, "the counts are there to leave out")
        for tool in ("get_status", "open_settings"):
            line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": tool, "arguments": {}}}) + "\n"
            out = io.StringIO()
            mcpserver.Server(self.control, io.StringIO(line), out).serve()
            result = json.loads(out.getvalue())["result"]
            with self.subTest(tool):
                self.assertNotIn("reported", keys_anywhere(result))
                content = result["structuredContent"]
                status = content["status"] if tool == "open_settings" else content
                summary = status["watcher"]["compatibility"]
                self.assertEqual(set(summary), {"status", "overall", "acting", "source", "sequence", "cache",
                                                "checked_at", "capabilities"})
                text = json.dumps(summary)
                for leak in ("codex-cli", "777", "555", "333", "111"):
                    self.assertNotIn(leak, text)

    def test_the_popup_and_the_tray_are_given_the_same_whatever_others_report(self):
        """R10: the popup, the notification card and the tray get nothing - Reported has no action and must never
        draw attention. What they are drawn from, and the popup's model and the icon's attention made of it, are
        the same with no counts, with a thousand reports that failed and with a thousand that worked."""
        from codex_auto_resume import l10n
        from codex_auto_resume.ui.popup import model
        self.fixture.backend()
        strings = l10n.catalog("en")
        seen = []
        for entries in ((), ((self.VERSION, 0, 1000, 0, 0),), ((self.VERSION, 1000, 0, 0, 0),)):
            with patch.object(self.reported, "BUNDLED", counts_file(self.folder, *entries)):
                status = self.control.get_status()
                rows = self.control.list_pending()
                seen.append((status, rows, model.view_model(rows, status, strings, 1000.0),
                             model.icon_attention(status, rows), model.light_for(status, status["watcher"]["engine_state"], rows)))
        self.assertNotIn("reported", keys_anywhere(seen[0][:2]))
        self.assertEqual(seen[1], seen[0])
        self.assertEqual(seen[2], seen[0])

    def test_the_diagnostics_bundle_carries_it(self):
        self.counts((self.VERSION, 1, 0, 2, 0))
        self.fixture.backend()
        with patch.object(diagnostics, "_installation", return_value={}):
            bundle = diagnostics.collect(self.control)
        self.assertEqual(bundle["compatibility"]["reported"]["neither"], 2)

    def test_reading_the_view_again_costs_a_stat_not_a_parse(self):
        """The Diagnostics page reads the view on every poll (the v0.6.9 lag work): a thousand reads
        parse the counts once, and a changed file once more."""
        self.counts((self.VERSION, 1, 0, 0, 0))
        self.fixture.backend()
        with patch.object(self.reported, "parse", wraps=self.reported.parse) as parse:
            for _ in range(1000):
                answer = compatio.read_view(self.fixture.paths)["reported"]
            self.assertEqual((answer["worked"], parse.call_count), (1, 1))
            self.counts((self.VERSION, 2, 0, 0, 0))
            self.assertEqual(compatio.read_view(self.fixture.paths)["reported"]["worked"], 2)
            self.assertEqual(parse.call_count, 2)


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
        # The two registry modules and every module of this product they reach, lazily or not:
        # the registry's code is held to it however it is split and whatever it starts to use.
        reached = srcscan.closure("codex_auto_resume.compat", "codex_auto_resume.compatio")
        for module in sorted(reached):
            text = srcscan.read(srcscan.modules()[module])
            with self.subTest(module):
                self.assertIsNone(pattern.search(text), module)
                self.assertNotIn("Invoke-WebRequest", text)

    def test_the_pure_model_touches_no_file_and_no_process(self):
        # The model and everything it reaches: a pure function moved into a helper module, or
        # a package made of the model, is still read.
        reached = srcscan.closure("codex_auto_resume.compat")
        for module in sorted(reached):
            text = srcscan.read(srcscan.modules()[module])
            for forbidden in ("open(", "subprocess", "import os", "Path(", "sqlite3"):
                with self.subTest(module=module, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_the_gap_rule_knows_a_documented_refresh_from_an_undocumented_one(self):
        undocumented = {"PRIVACY.md": "Pressing *Check for updates* makes one HTTPS request. "
                                      "It is a HEAD request, so no page is read.",
                        "docs/SECURITY.md": "No update check runs unless you press the button.",
                        "PRIVACY.ko.md": "", "docs/SECURITY.ko.md": ""}
        self.assertEqual(len(documentation_gaps(undocumented)), 9)
        documented = {
            "PRIVACY.md": "Pressing *Check for updates* asks github.com, and then fetches the Codex "
                          "compatibility data from raw.githubusercontent.com - only when you press "
                          "it. The result is kept in config/compat-cache.json, and the watcher "
                          "writes config/compatibility.json.\n\n"
                          "- from `get_status`: the version and, as codes only, the Codex "
                          "compatibility summary;\n",
            "docs/SECURITY.md": "No update check and no compatibility refresh runs unless you press "
                           "the button; the data comes from raw.githubusercontent.com.",
            "PRIVACY.ko.md": "raw.githubusercontent.com compat-cache.json\n\n"
                             "- `get_status`: 버전, 그리고 코드로만 된 Codex 호환성 요약;\n",
            "docs/SECURITY.ko.md": "raw.githubusercontent.com"}
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
        # dev holds both; main is English only; on ko, PRIVACY.md is the Korean text. The
        # English copy used to stand in for a missing Korean one here, which let a deleted
        # PRIVACY.ko.md pass - now the Korean half is asked only where it must exist.
        korean = languages.both_languages()
        texts = {"PRIVACY.md": read("PRIVACY.md")}
        if korean:
            texts["PRIVACY.ko.md"] = read("PRIVACY.ko.md")
        self.assertEqual(status_disclosure_gaps(texts, korean=korean), [])

    def test_the_documents_name_the_refresh_before_it_ships(self):
        """The refresh is a request PRIVACY.md does not describe yet: it still says the
        update check is one HEAD request that reads no page. PLAN §5.10 puts the documents
        in the same release as the refresh, and this makes that a rule rather than a memory:
        binding from the version bump past 0.6.4 - the last version without the refresh - so
        a release cannot go out with the old sentence standing. Skipped, saying so, before."""
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
        if compat.product_key(manifest["version"].split("-")[0]) <= (0, 6, 4):
            self.skipTest("binding from the version bump past 0.6.4: PRIVACY.md, SECURITY.md and "
                          "their .ko.md pairs must name the compatibility refresh before it ships")
        if generated_ko_branch():
            # The Korean half of the rule, asked of the files that hold the Korean text here. The
            # English half is main's to answer, where the English is.
            for name in ("PRIVACY.md", "docs/SECURITY.md"):
                with self.subTest(name):
                    self.assertIn(REFRESH_HOST, read(name),
                                  "%s holds the Korean text on this branch, and it must still name %s"
                                  % (name, REFRESH_HOST))
            return
        names = ["PRIVACY.md", "docs/SECURITY.md"]
        if languages.both_languages():
            names += ["PRIVACY.ko.md", "docs/SECURITY.ko.md"]
        texts = {name: read(name) for name in names}
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
        data = "src/codex_auto_resume/data/codex_compat.json"
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            app = stage / "payload" / "app"
            target = app / data
            with self.assertRaises(SystemExit):
                self.builder.check_app_files(stage)
            # Every other file the build requires is there; the registry's data is the one
            # under test. Written this way so a file added to REQUIRED_APP_FILES - the panel's
            # stylesheet and script were, in v0.6.10-alpha - does not have to be named again.
            for name in self.builder.REQUIRED_APP_FILES:
                if name == data:
                    continue
                (app / name).parent.mkdir(parents=True, exist_ok=True)
                (app / name).write_bytes((ROOT / name).read_bytes())
            with self.assertRaises(SystemExit):
                self.builder.check_app_files(stage)
            target.parent.mkdir(parents=True)
            target.write_text('{"format": "codex-auto-resume-compat/1"}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.builder.check_app_files(stage)
            target.write_bytes(compatio.BUNDLED.read_bytes())
            self.builder.check_app_files(stage)
            # And a payload that has the data but not the panel's own files is refused too.
            (app / "src/codex_auto_resume/mcp/assets/panel.js").unlink()
            with self.assertRaises(SystemExit):
                self.builder.check_app_files(stage)

    def test_the_smoke_test_checks_the_shipped_data(self):
        text = (ROOT / "build" / "smoke_archive.py").read_text(encoding="utf-8")
        self.assertIn('"codex_compat.json"', text)
        self.assertIn('"compat"', text)
        self.assertIn("LOCALAPPDATA=str(workspace / \"no-engines\")", text,
                      "the smoke test must not start the machine's own Codex")


if __name__ == "__main__":
    unittest.main()

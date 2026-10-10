"""The Dashboard's Advanced features page (advanced/gui/AdvancedPage.cs), in the window itself.

The advanced window is compiled from the standard window's sources and the overlay's, and loaded; the
page is driven through the window's own hooks (AdvancedPageRun, AdvancedLayoutAudit in
advanced/gui/AdvancedPageAudit.cs), the way tests/test_gui_layout.py drives the standard pages through
LayoutAudit. The window is never shown, and its bridge is rooted where nothing is: every reply it reads
is one this test hands it, made by this edition's real bridge (controlcli, surfaces, arming) in a
temporary home with a policy, a compatibility view and measurements of the test's own - so nothing here
reads the real installation, the real Software\\Policies keys or a real Codex.

Held here: the page's rows are every capability in the registry's order, by name and state in the
person's language; the open one shows its statement's five fields, its warnings, what a policy refuses
and its limits; Turn on and Watch first ask in the dialog with the statement and every warning, send
exactly what the page showed - which the real bridge then accepts - and ask again, with what holds now,
when the bridge says something changed, or say why they cannot (it could not be read again, or a policy
now refuses it); a refusal is told; a capability that turned itself off says so and why; Turn off and
Turn every advanced feature off send theirs; the hourly limit is a spin box, and the lowered limit is one
the real bridge takes; a capability's own choices are drop-downs whose choice is sent at once, the rules
for Codex's error codes are listed, added and removed, and the samples are listed, codes and numbers only -
each request one the real bridge takes, and each refusal told; what a watched capability would have done is a card last
in its column, answer words, counts and minutes only, read for every capability but an action; a capability on or watched can be kept on, with Send
again or without, after each warning, and let go - what a kept-on one noted shown in the accent - and Send now, while it
is on, offers each waiting recovery, asking first; the compatibility report - an action - says it sends nothing to
Codex where the others show their limits, and its card writes, shows, saves, checks and sends a report only as its
state allows, sends only on exactly the word send, holds the window's reopen while a check or a send runs, keeps
Turn off live meanwhile, shows a send it cannot account for as lost, and keeps the last ending once it is
off; the list is read again after every action and when the snapshot's badge says it
changed; the reset actions (v0.6.14) - a message at a reset and a reset credit's rules - are added from their
forms, which offer the windows, which reset, and the snapshot's conversations, asking first, and are cancelled, let
go on counting and used now, each request one the real bridge takes, and Pending shows each rule still to act with
Cancel, read when the status's counts change; Longer reset messages says what it lets a message be; a window that
reopens itself on the page comes back to it; the page is audited in every language at every scaling - Pending's
scheduled group too - its tabs on the narrowest screen too; and the standard window holds nothing of it.

GUI test module: compiles real executables, so it runs on its own.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_page.py
"""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ROOT  # noqa: E402

if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

import edition_audit  # noqa: E402
import guiscan  # noqa: E402
from test_gui_layout import fullest_snapshot  # noqa: E402
from codex_auto_resume import config, control, controlcli, l10n  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, policy, registry, statement, surfaces, watchlog  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingWarning, JournalCode, Measurement, Verdict  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
OVERLAY = ROOT / "advanced" / "gui" / "window.sources"
WINDOW = "CodexAutoResumeSettings.exe"
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)
IDS = [definition.id for definition in registry.DEFINITIONS]
# Every measurement the shipped capabilities rest on, passed on the Codex in force: no warning of that kind.
PASSED = {measurement: (Verdict.PASS, ac.ENGINE) for measurement in Measurement}


def overlay_sources() -> list:
    sources = []
    for line in OVERLAY.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("["):
            sources.append(ROOT / line)
    return sources


def compile_window(folder: Path) -> Path:
    """The advanced window, as build/make_gui.ps1 -Edition advanced compiles it (less its version resource)."""
    exe = folder / WINDOW
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                    "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                    *[str(path) for path in guiscan.sources()], *[str(path) for path in overlay_sources()]],
                   check=True, capture_output=True, timeout=300)
    return exe


def strings(locale: str, catalog=None) -> dict:
    """A strings reply, as the window is handed one."""
    return {"ok": True, "language": locale, "strings": catalog or l10n.catalog(locale),
            "endonyms": dict(l10n.ENDONYMS), "preference": locale, "system_language": locale}


def snapshot(on=0) -> dict:
    """A dashboard reply - the fullest the standard pages show (test_gui_layout) - with this edition's badge
    (surfaces.badge) under the status's one key."""
    reply = fullest_snapshot(ac.NOW)
    reply["status"]["advanced"] = {"edition": "advanced", "on": on}
    return reply


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$run = $form.GetMethod('AdvancedPageRun', $static)
$audit = $form.GetMethod('AdvancedLayoutAudit', $static)
$audited = $form.GetField('AdvancedAudited', $static)
if (-not $run -or -not $audit) { throw 'SettingsForm has no AdvancedPageRun or AdvancedLayoutAudit' }
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Text([string]$name) { [IO.File]::ReadAllText((Join-Path $work $name), $utf8) }
$jobs = ConvertFrom-Json ([IO.File]::ReadAllText($env:CAR_JOBS, $utf8))
$out = @{}
foreach ($job in $jobs) {
    try {
        if ($job.kind -eq 'run') {
            $out[$job.name] = [string]$run.Invoke($null, [object[]]@((Text $job.strings), (Text $job.scenario)))
        } else {
            $report = [string]$audit.Invoke($null, [object[]]@((Text $job.strings), (Text $job.words), (Text $job.listing),
                                                              (Text $job.statements), (Text $job.kept), (Text $job.reports),
                                                              [double]$job.scale))
            $out[$job.name] = @{ report = $report; audited = [int]$audited.GetValue($null) }
        }
    } catch {
        # What the window threw, whole, for the one job it threw in; the others still run.
        $thrown = $_.Exception
        while ($thrown.InnerException) { $thrown = $thrown.InnerException }
        $out[$job.name] = @{ error = $thrown.ToString() }
    }
}
[IO.File]::WriteAllText($env:CAR_RESULT, (ConvertTo-Json $out -Depth 6 -Compress), $utf8)
"""


def probe(work: Path, exe: Path, jobs: list, timeout: int, workers: int = 1) -> tuple:
    """Runs `jobs` in the window, in `workers` processes side by side, each an STA PowerShell that loads the window
    once: (the processes, what each job answered). The jobs are independent, so the answers are the same however
    they are shared out; only the time differs."""
    script = work / "probe.ps1"
    script.write_text(PROBE, encoding="utf-8")
    shares = [jobs[index::workers] for index in range(max(1, workers))]
    running = []
    for index, share in enumerate(share for share in shares if share):
        listed, result = work / ("jobs-%d.json" % index), work / ("result-%d.json" % index)
        listed.write_text(json.dumps(share), encoding="utf-8")
        result.unlink(missing_ok=True)
        process = subprocess.Popen([str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                                    "Bypass", "-File", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_JOBS=str(listed),
                                            CAR_RESULT=str(result)))
        running.append((process, result))
    done, found = [], {}
    for process, result in running:
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            out, err = process.communicate()
        done.append(subprocess.CompletedProcess(process.args, process.returncode, out.decode("utf-8", "replace"),
                                                err.decode("utf-8", "replace")))
        if process.returncode == 0 and result.is_file():
            found.update(json.loads(result.read_text(encoding="utf-8-sig")))
    failed = [run for run in done if run.returncode != 0]
    return (failed[0] if failed else done[0]), ({} if failed else found)


class Bridge:
    """This edition's real bridge, as the Dashboard's long-lived one reaches it (controlcli.serve), in a home of
    the test's own: the shipped registry and statements, and a policy, a view and measurements a test sets."""

    def __init__(self, home: Path):
        self.paths = config.Paths(home)
        self.paths.ensure()
        self.policy = policy.NONE
        self.view = ac.view("COMPATIBLE", capability="engine_present")
        for definition in registry.DEFINITIONS:
            if definition.compat is not None:          # an action stands on none
                self.view["capabilities"][definition.compat] = {"state": "COMPATIBLE", "reason": "local_checks_passed"}
        self.measured = dict(PASSED)
        self.plug = advanced.AdvancedPlug(self.paths, clock=lambda: ac.NOW, policy=lambda: self.policy,
                                          view=lambda: self.view, measured=lambda: self.measured)
        self.control = control.Control(self.paths, plug=self.plug)

    def close(self):
        if self.plug._runtime is not None:
            self.plug._runtime.state.close()

    def __call__(self, command, argument=None) -> dict:
        request = {"id": 1, "command": command}
        if argument is not None:
            request["argument"] = argument
        out = io.StringIO()
        controlcli.serve(self.control, io.StringIO(json.dumps(request) + "\n"), out)
        return json.loads(out.getvalue())["reply"]

    def request(self, sent: str) -> dict:
        """A request the page wrote down ("<command> <argument>"), put to this bridge."""
        command, argument = sent.split(" ", 1)
        return self(command, json.loads(argument))

    def statements(self, locale) -> dict:
        return {"advanced-statement " + capability: [self("advanced-statement", {"capability": capability,
                                                                                  "locale": locale})]
                for capability in IDS}


def sent(result, command) -> list:
    return [json.loads(line.split(" ", 1)[1]) for line in result["sent"] if line.split(" ", 1)[0] == command]


REPORT = "compat_report"
SHA = "a" * 64
FILE = '{\n  "format": "codex-auto-resume-compat-evidence/1"\n}\n'
PROJECT = "https://github.com/songyb111-gachon/codex-auto-resume-windows"
BRANCH = "compat-report/codex-cli-0.158.0"
TARGET = "docs/evidence/community/ExampleUser/codex-cli-0.158.0.json"
WRITES = [{"kind": "fork_new", "name": "ExampleUser/codex-auto-resume-windows"}, {"kind": "branch_new", "name": BRANCH},
          {"kind": "file", "name": TARGET}, {"kind": "pr", "name": "songyb111-gachon/codex-auto-resume-windows"}]
# Each status a report job answers with, as report/flow.py writes it, of fixture data: ExampleUser, a fixed SHA-256.
BUILT = {"done": True, "job": "j1", "status": "built", "sha256": SHA, "bytes": len(FILE), "text": FILE,
         "codex_version": "codex-cli 0.158.0", "records": 12, "verdict": "PASS",
         "left_out": {"hidden": 1, "another_route": 0, "beyond_reach": 0, "elsewhere": 3, "unplaced": {}},
         "login": "ExampleUser", "file_name": "codex-cli-0.158.0.json", "branch": BRANCH}
CHECKED = {"done": True, "job": "j2", "status": "checked", "gh": r"C:\Program Files\GitHub CLI\gh.exe", "who": "ExampleUser",
           "writes": WRITES, "interrupted": True}
WEB = {"done": True, "job": "j2", "status": "web", "why": "gh_other_login", "login": "ExampleUser", "who": "SomeoneElse",
       "branch": BRANCH, "target": TARGET, "file_name": "codex-cli-0.158.0.json", "project_page": PROJECT}
SENT = {"done": True, "job": "j3", "status": "sent", "url": PROJECT + "/pull/42", "already": False}
PARTIAL = {"done": True, "job": "j3", "status": "partial", "written": WRITES[:2], "refusal": "paused"}
RUNNING = {"done": True, "status": "running"}


def job(name, answer=None) -> dict:
    """A start's answer: the job's id."""
    return {"ok": True, "result": answer or {"done": True, "job": name}}


def ok(result) -> dict:
    return {"ok": True, "result": result}


def report_states() -> list:
    """The report's card at its fullest, for the layout audit, in two states that between them show every part of it:
    on with a report written and checked, a send running and the last one ended part way; and on the web, with the
    last send's pull request. (Watched and off show fewer of the same parts; every state is driven in PageTests.)"""
    return [{"state": "armed", "built": BUILT, "checked": CHECKED, "last": PARTIAL, "login": "ExampleUser", "word": "send",
             "job": "send"},
            {"state": "armed", "built": BUILT, "checked": WEB, "last": SENT, "job": "check"}]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(unittest.TestCase):
    """The page driven as a person would, every scenario in one window process."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        cls.exe = compile_window(work)
        cls.scenarios, cls.expected, jobs = {}, {}, []
        for name in sorted(dir(cls)):
            if name.startswith("scenario_"):
                bridge = Bridge(work / "homes" / name)
                try:
                    locale, scenario, expected = getattr(cls, name)(bridge)
                finally:
                    bridge.close()
                cls.expected[name] = expected
                (work / (name + ".json")).write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
                strings_name = "strings-%s.json" % locale
                if not (work / strings_name).is_file():
                    (work / strings_name).write_text(json.dumps(strings(locale), ensure_ascii=False), encoding="utf-8")
                jobs.append({"kind": "run", "name": name, "strings": strings_name, "scenario": name + ".json"})
        cls.run_, answers = probe(work, cls.exe, jobs, timeout=600)
        cls.results = {name: json.loads(found) if isinstance(found, str) else found for name, found in answers.items()}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.results:
            self.fail("the probe did not run: " + (self.run_.stderr or self.run_.stdout)[-3000:])

    def of(self, name) -> tuple:
        """What the page did in one scenario, and what the bridge said while it was made."""
        found = self.results.get(name)
        if found is None or "error" in found:
            self.fail("%s did not run: %s" % (name, (found or {}).get("error")))
        return found, self.expected[name]

    # ---------------------------------------------------------------- scenarios
    # Each makes its replies with the real bridge of a home of its own, and returns (locale, scenario, what the test
    # needs to know of what the bridge said). The scenario's own replies are what the window reads.
    @staticmethod
    def opening(bridge, locale):
        return {"advanced-words": [bridge("advanced-words", {"locale": locale})],
                "advanced-list": [bridge("advanced-list", {})], **bridge.statements(locale)}

    @classmethod
    def scenario_reading(cls, bridge):
        """Opened in Korean: the words, the list and the first statement read as a snapshot arrives; then the tab."""
        script = cls.opening(bridge, "ko")
        steps = [{"do": "look"}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"}, {"do": "show"},
                 {"do": "choose", "id": IDS[1]}]
        statements = {capability: script["advanced-statement " + capability][0]["result"] for capability in IDS}
        return "ko", {"script": script, "steps": steps}, {"statements": statements,
                                                          "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_turn_on(cls, bridge):
        """Turn on, answered yes - with a warning the statement carries, which the request confirms."""
        bridge.measured = {}
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": IDS[2]},
                 {"do": "look"}, {"do": "reply", "key": "advanced-arm", "with": [{"ok": True, "result": {"done": True}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True], "script": script, "steps": steps}, {
            "statement": script["advanced-statement " + IDS[2]][0]["result"],
            "generation": script["advanced-list"][0]["result"]["generation"]}

    @classmethod
    def scenario_declined(cls, bridge):
        """Turn on and Watch first, both answered Cancel: nothing is sent."""
        script = cls.opening(bridge, "de")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "press", "button": "on"},
                 {"do": "press", "button": "watch"}]
        return "de", {"answers": [False, False], "script": script, "steps": steps}, {}

    @classmethod
    def scenario_changed(cls, bridge):
        """Turn on, answered yes; meanwhile a local check failed here, so the bridge answers that the confirmation
        is stale. The page reads again, asks again with what holds now, and the second yes sends that."""
        script = cls.opening(bridge, "en")
        capability = IDS[0]
        before = script["advanced-statement " + capability][0]["result"]
        compat = registry.REGISTRY.get(capability).compat
        bridge.view["capabilities"][compat] = {"state": "FAILED_HERE", "reason": "local_check_failed_here"}
        stale = bridge("advanced-arm", {"capability": capability, "state": "armed", "revision": before["revision"],
                                        "generation": 0, "engine_version": before["engine_version"], "warnings": []})
        after = bridge("advanced-statement", {"capability": capability, "locale": "en"})
        listing = bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-list", "with": [listing]},
                 {"do": "reply", "key": "advanced-statement " + capability, "with": [after]},
                 {"do": "reply", "key": "advanced-arm", "with": [stale, {"ok": True, "result": {"done": True}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "stale": stale["result"], "after": after["result"], "listing": listing["result"]}

    @classmethod
    def scenario_refused(cls, bridge):
        """Watch first, answered yes, refused by an administrator's policy that arrived meanwhile: said, in words."""
        script = cls.opening(bridge, "fr")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "forbidden_by_policy", "warnings": []}}]},
                 {"do": "press", "button": "watch"}]
        return "fr", {"answers": [True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_policy(cls, bridge):
        """An administrator allows one capability and forces the rest to be watched: the others say so, and cannot be
        turned on or watched; the allowed one can only be watched."""
        bridge.policy = policy.Policy(force_shadow=True, allowed=frozenset({IDS[1]}))
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "look"},
                 {"do": "choose", "id": IDS[1]}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_off(cls, bridge):
        """One capability watched: Turn off sends advanced-disarm for it, and Turn every advanced feature off sends
        advanced-disarm-all; each is read again after, and says what it did."""
        definition = registry.REGISTRY.get(IDS[1])
        listed = bridge("advanced-statement", {"capability": IDS[1], "locale": "ja"})["result"]
        done = bridge("advanced-arm", {"capability": IDS[1], "state": "shadow", "revision": definition.revision,
                                       "generation": 0, "engine_version": listed["engine_version"],
                                       "warnings": [item["warning"] for item in listed["warnings"]["items"]]})
        assert done["result"]["done"], done
        script = cls.opening(bridge, "ja")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": IDS[1]},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-disarm", "with": [{"ok": True, "result": {"done": True, "changed": True}}]},
                 {"do": "press", "button": "off"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-disarm-all", "with": [{"ok": True, "result": {"done": True, "count": 0}}]},
                 {"do": "press", "button": "all_off"}]
        return "ja", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_hourly(cls, bridge):
        """The hourly limit lowered to 5: sent with the generation the list was read at, never above the registry's."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-ceiling", "with": [{"ok": True, "result": {"done": True}}]},
                 {"do": "hourly", "value": 5}]
        return "en", {"script": script, "steps": steps}, {"listing": script["advanced-list"][0]["result"]}

    @classmethod
    def scenario_followed(cls, bridge):
        """Away from the page, a snapshot whose badge says nothing changed reads nothing, and one whose badge changed -
        a capability turned on or off, here or anywhere - reads the list again; on the page, every snapshot does."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot(on=1)}, {"do": "look"},
                 {"do": "show"}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot(on=1)}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_measured(cls, bridge):
        """On the page, every snapshot reads the list again (scenario_followed): twice the same list, then one where a
        capability is watched. The cells are measured when the rows come, and again only when a state's word changed."""
        script = cls.opening(bridge, "en")
        definition = registry.REGISTRY.get(IDS[1])
        listed = bridge("advanced-statement", {"capability": IDS[1], "locale": "en"})["result"]
        done = bridge("advanced-arm", {"capability": IDS[1], "state": "shadow", "revision": definition.revision,
                                       "generation": 0, "engine_version": listed["engine_version"],
                                       "warnings": [item["warning"] for item in listed["warnings"]["items"]]})
        assert done["result"]["done"], done
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "reply", "key": "advanced-list", "with": [bridge("advanced-list", {})]},
                 {"do": "snapshot", "reply": snapshot(on=1)}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_keys(cls, bridge):
        """Ctrl+Tab goes from Settings to this page and on to the Overview; Ctrl+Shift+Tab back."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "page", "name": "settings"}, {"do": "ctrl-tab"},
                 {"do": "look"}, {"do": "ctrl-tab"}, {"do": "look"}, {"do": "ctrl-tab", "shift": True}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_changed_unreadable(cls, bridge):
        """Turn on, answered yes; the bridge says the confirmation is stale, and the statement read again cannot be
        read. Nothing can be asked again: the person is told so, and the page says why it cannot be turned on."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-statement " + IDS[0], "with": [{"ok": False, "error": "timed out"}]},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_confirmation"}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_changed_unlisted(cls, bridge):
        """As above, but it is the list read again that cannot be read."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-list", "with": [{"ok": False, "error": "timed out"}]},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_generation"}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_changed_to_policy(cls, bridge):
        """Turn on, answered yes; meanwhile an administrator's policy came to forbid every capability. The list read
        again says so: the person is not asked to confirm what the page knows cannot happen, but told why."""
        script = cls.opening(bridge, "en")
        bridge.policy = policy.Policy(forbid=True)
        forbidden = bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"},
                 {"do": "reply", "key": "advanced-list", "with": [forbidden]},
                 {"do": "reply", "key": "advanced-arm",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_generation"}},
                           {"ok": True, "result": {"done": False, "refusal": "forbidden_by_policy"}}]},
                 {"do": "press", "button": "on"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_tripped(cls, bridge):
        """Marker-free continuation turned on with the statement's own confirmation, and then the measurement it rests
        on failed: the real bridge's list says a tripwire turned it off, and why. The page says so; then, for the
        same capability turned off by a person, it says nothing of the kind; and for one Codex's new version turned
        off, it says that."""
        capability = "marker_free_continuation"
        shown = bridge("advanced-statement", {"capability": capability, "locale": "en"})["result"]
        armed = bridge("advanced-arm", {"capability": capability, "state": "armed", "revision": shown["revision"],
                                        "generation": bridge("advanced-list", {})["result"]["generation"],
                                        "engine_version": shown["engine_version"],
                                        "warnings": [item["warning"] for item in shown["warnings"]["items"]]})
        assert armed["result"]["done"], armed
        bridge.measured = dict(bridge.measured, **{Measurement.M7: (Verdict.FAIL, ac.ENGINE)})
        script = cls.opening(bridge, "en")
        listing = script["advanced-list"][0]
        item = next(entry for entry in listing["result"]["capabilities"] if entry["id"] == capability)
        by_person, by_engine = copy.deepcopy(listing), copy.deepcopy(listing)
        for changed, (by, reason) in ((by_person, ("dashboard", "disarmed")), (by_engine, ("engine_change", "engine_changed"))):
            entry = next(entry for entry in changed["result"]["capabilities"] if entry["id"] == capability)
            entry["by"], entry["reason"] = by, reason
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": capability},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-list", "with": [by_person]}, {"do": "snapshot", "reply": snapshot()},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-list", "with": [by_engine]}, {"do": "snapshot", "reply": snapshot()},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "item": item, "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_choices(cls, bridge):
        """Short retries when Codex is at capacity open: its one choice, the hours it keeps trying, a drop-down at the
        default; four hours chosen is sent at once, with the generation the list was read at."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "capacity_retry"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-option", "with": [{"ok": True, "result": {"done": True, "generation": 1}}]},
                 {"do": "set_option", "key": "ceiling_hours", "value": 4},
                 {"do": "reply", "key": "advanced-option",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "stale_generation"}}]},
                 {"do": "set_option", "key": "ceiling_hours", "value": 6}]
        return "en", {"script": script, "steps": steps}, {
            "listing": script["advanced-list"][0]["result"], "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def rules_home(cls, bridge):
        """A rule of the person's, written through the real bridge as the Dashboard writes one."""
        added = bridge("advanced-rule-add", {"tag": "brandNewVariant", "status_from": 500, "status_to": 599,
                                             "category": "server_5xx", "generation": 0})["result"]
        assert added["done"], added
        return added

    @classmethod
    def scenario_rules(cls, bridge):
        """The rules for Codex's error codes open: the person's one rule, with its Remove; a new one taken from the
        samples' codes, with status numbers and a kind, added; the first removed; a code that may name a decision
        refused by the bridge, and one that is not a code at all refused before anything is sent - each told."""
        cls.rules_home(bridge)
        script = cls.opening(bridge, "en")
        rules = bridge("advanced-rules", {})
        rules["result"]["tags"] = ["seenOnlyHere"]
        script["advanced-rules"] = [rules]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "structured_rules"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-rule-add", "with": [{"ok": True, "result": {"done": True, "rule": 2}}]},
                 {"do": "rule", "sampled": "seenOnlyHere", "from": "502", "to": "504", "kind": "timeout"},
                 {"do": "reply", "key": "advanced-rule-remove", "with": [{"ok": True, "result": {"done": True}}]},
                 {"do": "remove", "rule": 1}, {"do": "look"},
                 {"do": "reply", "key": "advanced-rule-add",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "rule_decision"}}]},
                 {"do": "rule", "tag": "policyRefused", "kind": "server_5xx"},
                 {"do": "rule", "tag": "not a code"}]
        return "en", {"script": script, "steps": steps}, {
            "rules": rules["result"], "listing": script["advanced-list"][0]["result"],
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_samples(cls, bridge):
        """Retry failures it cannot name open: its choice of tries, and its samples - a code with a status, and a
        failure with no code - then, read again, none."""
        script = cls.opening(bridge, "en")
        script["advanced-samples"] = [{"ok": True, "result": {"done": True, "samples": [
            {"tag": "brandNewVariant", "status": 503, "form": "tagged", "count": 2, "last": "2027-01-15"},
            {"tag": None, "status": None, "form": "absent", "count": 1, "last": "2027-01-14"}]}}]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "unknown_failure_budget"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-samples", "with": [{"ok": True, "result": {"done": True, "samples": []}}]},
                 {"do": "snapshot", "reply": snapshot()}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_watch_log(cls, bridge):
        """Notice a usage limit that lifts early, watched: its watch log read through the real bridge - off with nothing,
        watched with nothing, then two looks early and one hold counted - and, scripted, one the bound has cut; then the
        compatibility report, an action, opened."""
        def log():
            return bridge("advanced-watch-log", {"capability": "early_reset"})
        off = log()
        cls.watched(bridge, "early_reset")
        none = log()
        state = bridge.plug.runtime.state
        for at in (ac.NOW - 3600, ac.NOW - 60):
            state.note(JournalCode.WOULD_HAVE, capability="early_reset", point=Point.SCHEDULE, answer=Alternative.EARLY,
                       at=at)
        state.note(JournalCode.WOULD_HAVE, capability="early_reset", point=Point.GATES, answer=Alternative.HOLD,
                   at=ac.NOW - 60)
        lines = log()
        full = copy.deepcopy(lines)
        full["result"].update({"full": True, "from": watchlog.minute(ac.NOW - 3600)})
        key = "advanced-watch-log early_reset"
        script = cls.opening(bridge, "en")
        script[key] = [lines]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "early_reset"},
                 {"do": "look"},
                 {"do": "reply", "key": key, "with": [none]}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "reply", "key": key, "with": [off]}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "reply", "key": key, "with": [full]}, {"do": "snapshot", "reply": snapshot()}, {"do": "look"},
                 {"do": "choose", "id": REPORT}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"],
            "replies": {"off": off["result"], "none": none["result"], "lines": lines["result"]}}

    @staticmethod
    def watched(bridge, capability, state="shadow"):
        """`capability` watched - or on - through the real bridge, as the Dashboard asks for it."""
        shown = bridge("advanced-statement", {"capability": capability, "locale": "en"})["result"]
        done = bridge("advanced-arm", {"capability": capability, "state": state, "revision": shown["revision"],
                                       "generation": bridge("advanced-list", {})["result"]["generation"],
                                       "engine_version": shown["engine_version"],
                                       "warnings": [item["warning"] for item in shown["warnings"]["items"]]})
        assert done["result"]["done"], done
        return done["result"]["generation"]

    @classmethod
    def scenario_keep_on(cls, bridge):
        """Short retries when Codex is at capacity watched: Keep it on... asks with its warning and sends it, confirmed;
        then Also send again when unsure... with its own; then Let it turn itself off, asking nothing. Each list read
        after is the real bridge's after that request."""
        cls.watched(bridge, "capacity_retry")
        script = cls.opening(bridge, "en")
        generation = script["advanced-list"][0]["result"]["generation"]
        kept = bridge("advanced-keep-on", {"capability": "capacity_retry", "keep_on": True, "generation": generation,
                                           "confirmed": ["keep_on"]})
        once = bridge("advanced-list", {})
        again = bridge("advanced-keep-on", {"capability": "capacity_retry", "keep_on": True, "send_again": True,
                                            "generation": once["result"]["generation"],
                                            "confirmed": ["keep_on", "send_again"]})
        twice = bridge("advanced-list", {})
        let_go = bridge("advanced-keep-on", {"capability": "capacity_retry", "keep_on": False, "send_again": False})
        after = bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "capacity_retry"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-keep-on", "with": [kept]},
                 {"do": "reply", "key": "advanced-list", "with": [once]},
                 {"do": "press", "button": "keep_on"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-keep-on", "with": [again]},
                 {"do": "reply", "key": "advanced-list", "with": [twice]},
                 {"do": "press", "button": "send_again"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-keep-on", "with": [let_go]},
                 {"do": "reply", "key": "advanced-list", "with": [after]},
                 {"do": "press", "button": "let_go"}, {"do": "look"},
                 {"do": "choose", "id": "send_now"}, {"do": "look"}]
        return "en", {"answers": [True, True], "script": script, "steps": steps}, {
            "generations": [generation, once["result"]["generation"]],
            "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_kept_notice(cls, bridge):
        """Kept on, Short retries when Codex is at capacity noted a new Codex version instead of turning itself off: said
        in the accent under its state; and a once-more capability that a resend found twice turned off: said why."""
        from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, OffReason
        cls.watched(bridge, "capacity_retry")
        generation = bridge("advanced-list", {})["result"]["generation"]
        assert bridge("advanced-keep-on", {"capability": "capacity_retry", "keep_on": True, "generation": generation,
                                           "confirmed": ["keep_on"]})["result"]["done"]
        state = bridge.plug.runtime.state
        assert state.note_kept("capacity_retry", OffReason.ENGINE_CHANGED, at=ac.NOW)
        cls.watched(bridge, "once_more_when_unsure")
        state.move("once_more_when_unsure", ArmingState.OFF, actor=Actor.TRIPWIRE, reason=OffReason.DUPLICATE_SEEN,
                   at=ac.NOW)
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "capacity_retry"},
                 {"do": "look"}, {"do": "choose", "id": "once_more_when_unsure"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_action_kept(cls, bridge):
        """The compatibility report watched and kept on: Let it turn itself off, and no Also send again when unsure... -
        an action sends no continuation to send again, and the bridge refuses Send again for one."""
        cls.watched(bridge, REPORT)
        generation = bridge("advanced-list", {})["result"]["generation"]
        assert bridge("advanced-keep-on", {"capability": REPORT, "keep_on": True, "generation": generation,
                                           "confirmed": ["keep_on"]})["result"]["done"]
        refused = bridge("advanced-keep-on", {"capability": REPORT, "keep_on": True, "send_again": True,
                                              "generation": bridge("advanced-list", {})["result"]["generation"],
                                              "confirmed": ["keep_on", "send_again"]})["result"]
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": REPORT},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"],
                                                          "refused": refused}

    @classmethod
    def scenario_send_now(cls, bridge):
        """Send now on: its card lists the recoveries the snapshot holds waiting - not the one whose turn is running -
        each with its Send now..., which asks first and sends that record's id; declined, nothing is sent."""
        cls.watched(bridge, "send_now", state="armed")
        script = cls.opening(bridge, "en")
        reply = snapshot()
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": "send_now"}, {"do": "look"},
                 {"do": "reply", "key": "advanced-send-now",
                  "with": [{"ok": True, "result": {"done": True, "refusal": None, "expires_at": ac.NOW + 900}}]},
                 {"do": "send_now", "id": reply["pending"][0]["interruption_id"]}, {"do": "look"},
                 {"do": "send_now", "id": reply["pending"][1]["interruption_id"]},
                 {"do": "reply", "key": "advanced-send-now",
                  "with": [{"ok": True, "result": {"done": False, "refusal": "not_on"}}]},
                 {"do": "send_now", "id": reply["pending"][1]["interruption_id"]},
                 {"do": "send_now", "id": reply["pending"][2]["interruption_id"]}]
        return "en", {"answers": [True, False, True], "script": script, "steps": steps}, {
            "pending": reply["pending"], "words": script["advanced-words"][0]["result"]["words"]}

    # ---------------------------------------------------------------- the reset actions (AdvancedResets.cs)
    WORDS = "SENTINEL-reset: carry on with the release notes."

    @staticmethod
    def credit_rules(bridge):
        """Using a reset credit on, through the real bridge: a rule due that waits for a click (1), one held over a
        gap (2), the 5-hour window full now and the credits read - the same ids and generation in every home."""
        from codex_auto_resume_advanced.engine import resetwatch
        PageTests.watched(bridge, "reset_credit", state="armed")
        state = bridge.plug.runtime.state
        rules = []
        for ordinal in (1, 2):
            added = bridge("advanced-reset-add", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": ordinal,
                                                  "ask_first": True,
                                                  "generation": bridge("advanced-list", {})["result"]["generation"]})
            assert added["result"]["done"], added
            rules.append(added["result"]["rule"])
        state.change_rule(rules[0], state="ready", reason="ask_first", due_at=ac.NOW)
        state.change_rule(rules[1], state="held", reason="count_gap")
        state.save_windows([dict(resetwatch.blank("codex", 300), open_reset_at=int(ac.NOW) + 3600, open_full=True,
                                 seen_at=int(ac.NOW))])
        state.set_reading(read_at=int(ac.NOW), credits=3, expiry_known=1, nearest_expiry=int(ac.NOW) + 5 * 86400)
        return rules

    @classmethod
    def scenario_reset_message(cls, bridge):
        """A message at a reset on: the form offers the windows, which reset - only the next for the weekly one - and
        the snapshot's conversations; Add waits for words; added, asked first, the rule is a line with Cancel, which
        sends at once; declined, nothing is sent."""
        cls.watched(bridge, "reset_message", state="armed")
        script = cls.opening(bridge, "en")
        generation = script["advanced-list"][0]["result"]["generation"]
        reply = snapshot()
        thread = reply["pending"][1]["thread_id"]
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        added = bridge("advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 3,
                                              "thread_id": thread, "words": cls.WORDS, "generation": generation})
        after, listed = bridge("advanced-resets", {}), bridge("advanced-list", {})
        rule = added["result"]["rule"]
        cancelled = bridge("advanced-reset-cancel", {"rule": rule, "generation": listed["result"]["generation"]})
        gone, relisted = bridge("advanced-resets", {}), bridge("advanced-list", {})
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": "reset_message"},
                 {"do": "look"},                                                       # 0: no message yet
                 {"do": "reset_add", "family": "codex 10080"}, {"do": "look"},         # 1: weekly, no words: no Add
                 {"do": "reply", "key": "advanced-reset-add", "with": [added]},
                 {"do": "reply", "key": "advanced-resets", "with": [after]},
                 {"do": "reply", "key": "advanced-list", "with": [listed]},
                 {"do": "reset_add", "family": "codex 300", "ordinal": "3", "thread": thread, "words": cls.WORDS},
                 {"do": "look"},                                                       # 2: added
                 {"do": "reply", "key": "advanced-reset-cancel", "with": [cancelled]},
                 {"do": "reply", "key": "advanced-resets", "with": [gone]},
                 {"do": "reply", "key": "advanced-list", "with": [relisted]},
                 {"do": "reset_cancel", "rule": rule}, {"do": "look"},                 # 3: cancelled
                 {"do": "reset_add", "family": "codex 300", "ordinal": "1", "thread": thread, "words": "x"}]
        return "en", {"answers": [True, False], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "thread": thread, "rule": rule,
            "generations": [generation, listed["result"]["generation"]], "pending": reply["pending"]}

    @classmethod
    def scenario_reset_credit(cls, bridge):
        """Using a reset credit on: the reading, each rule a line - Go on counting for the held one, Use a reset credit
        now... for the due one and for the window full now - and a rule added with how often and Ask me first."""
        due, held = cls.credit_rules(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        # As where MU is not measured on the Codex in force: the count past the next one is unproven.
        script["advanced-resets"][0]["result"]["count_unproven"] = True
        done = {"ok": True, "result": {"done": True, "refusal": None, "rule": 9}}
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "reset_credit"},
                 {"do": "look"},
                 {"do": "reply", "key": "advanced-reset-add", "with": [done]},
                 {"do": "reset_add", "family": "codex 10080", "repeat": "every", "ask": "ask"},
                 {"do": "reply", "key": "advanced-credit-now", "with": [done]},
                 {"do": "credit_now", "family": "codex 300"},
                 {"do": "credit_now", "rule": due},
                 {"do": "reply", "key": "advanced-reset-go-on", "with": [done]},
                 {"do": "reset_go_on", "rule": held}, {"do": "look"}]
        return "en", {"answers": [True, True, False], "script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "due": due, "held": held,
            "generation": script["advanced-list"][0]["result"]["generation"]}

    @classmethod
    def scenario_scheduled(cls, bridge):
        """Pending's Scheduled group: hidden while nothing is read; read when the status's counts change, a line with
        Cancel for each rule still to act - and Go on counting for one held over a gap; not read again while they stay;
        let go on, and cancelled, read again and hidden."""
        cls.watched(bridge, "reset_message", state="armed")
        reply = snapshot(on=1)
        thread = reply["pending"][0]["thread_id"]
        added = bridge("advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1,
                                              "thread_id": thread, "words": cls.WORDS,
                                              "generation": bridge("advanced-list", {})["result"]["generation"]})
        rule = added["result"]["rule"]
        bridge.plug.runtime.state.change_rule(rule, state="held", reason="count_gap")
        script = cls.opening(bridge, "en")
        script["advanced-resets"] = [bridge("advanced-resets", {})]
        counted = copy.deepcopy(reply)
        counted["status"]["advanced"].update(surfaces.status(bridge.plug.runtime))
        cancelled = bridge("advanced-reset-cancel", {"rule": rule,
                                                     "generation": script["advanced-list"][0]["result"]["generation"]})
        gone = bridge("advanced-resets", {})
        steps = [{"do": "snapshot", "reply": reply}, {"do": "page", "name": "pending"}, {"do": "look"},
                 {"do": "snapshot", "reply": counted}, {"do": "look"},
                 {"do": "snapshot", "reply": counted}, {"do": "look"},
                 {"do": "reply", "key": "advanced-reset-go-on",
                  "with": [{"ok": True, "result": {"done": True, "refusal": None, "rule": rule}}]},
                 {"do": "scheduled_go_on", "rule": rule},
                 {"do": "reply", "key": "advanced-reset-cancel", "with": [cancelled]},
                 {"do": "reply", "key": "advanced-resets", "with": [gone]},
                 {"do": "scheduled_cancel", "rule": rule}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "rule": rule, "pending": reply["pending"],
            "counts": counted["status"]["advanced"]}

    @classmethod
    def scenario_long_messages(cls, bridge):
        """Longer reset messages, an action with no card of its own: its limits say what it lets a message be."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": "long_reset_message"},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    # What a window on this page passes on when it reopens itself (ReopenArguments): the page, and the keyboard on its tab.
    REOPENED = ("--page=advanced --section=general --bounds=100,100,1000,700 --theme=system --design=soft --reopened=1 "
                "--focus=page.advanced")

    @classmethod
    def scenario_reopen(cls, bridge):
        """On this page, a reopen - a theme, a language, Windows' colours - names it for the window that replaces it."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "reopen"},
                 {"do": "page", "name": "history"}, {"do": "reopen"}]
        return "en", {"script": script, "steps": steps}, {}

    @classmethod
    def scenario_reopened(cls, bridge):
        """The window that replaces it opens on the Overview, as one asked for a page it does not have yet, and comes
        back to this page once this edition has answered."""
        script = cls.opening(bridge, "en")
        steps = [{"do": "open", "arguments": cls.REOPENED}, {"do": "look"}, {"do": "snapshot", "reply": snapshot()},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    @staticmethod
    def report_on(bridge, state="armed"):
        """The compatibility report turned on, or watched, through the real bridge, as the page turns it."""
        shown = bridge("advanced-statement", {"capability": REPORT, "locale": "en"})["result"]
        done = bridge("advanced-arm", {"capability": REPORT, "state": state, "revision": shown["revision"],
                                       "generation": bridge("advanced-list", {})["result"]["generation"],
                                       "engine_version": shown["engine_version"],
                                       "warnings": [item["warning"] for item in shown["warnings"]["items"]]})
        assert done["result"]["done"], done

    @classmethod
    def scenario_report_sent(cls, bridge):
        """On: the login typed, the report written, saved, checked and - on exactly the word send - sent."""
        cls.report_on(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-report-build"] = [job("j1")]
        script["advanced-report-check"] = [job("j2")]
        script["advanced-report-send"] = [job("j3")]
        script["advanced-report-save"] = [ok({"done": True, "status": "saved"})]
        script["advanced-report-job"] = [ok(RUNNING), ok(BUILT), ok(CHECKED), ok(RUNNING), ok(SENT)]
        steps = [{"do": "snapshot", "reply": snapshot(on=1)}, {"do": "show"}, {"do": "choose", "id": REPORT},
                 {"do": "look"},                                                        # 0: nothing written yet
                 {"do": "type", "into": "login", "text": " ExampleUser "}, {"do": "press", "button": "report_write"},
                 {"do": "look"},                                                        # 1: writing
                 {"do": "poll"}, {"do": "poll"}, {"do": "look"},                        # 2: written
                 {"do": "save_to", "path": "C:\\Reports\\codex-cli-0.158.0.json"},
                 {"do": "press", "button": "report_save"}, {"do": "look"},              # 3: saved
                 {"do": "press", "button": "report_check"}, {"do": "look"},             # 4: checking, held
                 {"do": "poll"}, {"do": "look"},                                        # 5: checked
                 {"do": "type", "into": "word", "text": "Send"}, {"do": "look"},        # 6: not the word
                 {"do": "press", "button": "report_send"},
                 {"do": "type", "into": "word", "text": "send"}, {"do": "look"},        # 7: the word
                 {"do": "press", "button": "report_send"}, {"do": "look"},              # 8: sending, held
                 {"do": "poll"}, {"do": "look"},                                        # 9: still sending
                 {"do": "poll"}, {"do": "look"}]                                        # 10: sent
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"],
                                                          "listing": script["advanced-list"][0]["result"]}

    @classmethod
    def scenario_report_watched(cls, bridge):
        """Watched: written and saved, never checked or sent; and an action's limits say it sends nothing to Codex."""
        cls.report_on(bridge, "shadow")
        script = cls.opening(bridge, "ko")
        script["advanced-report-build"] = [job("j1")]
        script["advanced-report-job"] = [ok(BUILT)]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": REPORT},
                 {"do": "type", "into": "login", "text": "ExampleUser"}, {"do": "press", "button": "report_write"},
                 {"do": "poll"}, {"do": "look"}]
        return "ko", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_report_lost(cls, bridge):
        """A send whose start the one-shot bridge answered as an unknown command, and a check whose job the service no
        longer held: both are lost, shown with the way to tell, and neither holds the reopen after."""
        cls.report_on(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-report-build"] = [job("j1")]
        script["advanced-report-check"] = [job("j2")]
        script["advanced-report-send"] = [{"ok": False, "error": "unknown command", "error_code": "request_failed"}]
        script["advanced-report-job"] = [ok(BUILT), ok(CHECKED), ok({"done": True, "status": "lost"})]
        steps = [{"do": "snapshot", "reply": snapshot(on=1)}, {"do": "show"}, {"do": "choose", "id": REPORT},
                 {"do": "type", "into": "login", "text": "ExampleUser"}, {"do": "press", "button": "report_write"},
                 {"do": "poll"}, {"do": "press", "button": "report_check"}, {"do": "poll"},
                 {"do": "type", "into": "word", "text": "send"}, {"do": "press", "button": "report_send"},
                 {"do": "look"},                                                        # 0: the send is lost
                 {"do": "press", "button": "report_check"}, {"do": "poll"}, {"do": "look"}]  # 1: the check is lost
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_report_turned_off(cls, bridge):
        """Turned off while a send runs - Turn off is live then - the send ends part way; the card, off, keeps that."""
        cls.report_on(bridge)
        script = cls.opening(bridge, "en")
        off_listing = bridge("advanced-list", {})
        off_listing = copy.deepcopy(off_listing)
        entry = next(item for item in off_listing["result"]["capabilities"] if item["id"] == REPORT)
        entry["state"], entry["stored"], entry["by"], entry["reason"] = "off", "off", "dashboard", "disarmed"
        script["advanced-report-build"] = [job("j1")]
        script["advanced-report-check"] = [job("j2")]
        script["advanced-report-send"] = [job("j3")]
        script["advanced-report-job"] = [ok(BUILT), ok(CHECKED), ok(RUNNING), ok(PARTIAL)]
        steps = [{"do": "snapshot", "reply": snapshot(on=1)}, {"do": "show"}, {"do": "choose", "id": REPORT},
                 {"do": "type", "into": "login", "text": "ExampleUser"}, {"do": "press", "button": "report_write"},
                 {"do": "poll"}, {"do": "press", "button": "report_check"}, {"do": "poll"},
                 {"do": "type", "into": "word", "text": "send"}, {"do": "press", "button": "report_send"},
                 {"do": "poll"}, {"do": "look"},                                        # 0: sending
                 {"do": "reply", "key": "advanced-disarm", "with": [{"ok": True, "result": {"done": True, "changed": True}}]},
                 {"do": "reply", "key": "advanced-list", "with": [off_listing]},
                 {"do": "press", "button": "off"}, {"do": "look"},                      # 1: off, still sending
                 {"do": "poll"}, {"do": "look"}]                                        # 2: ended part way
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_report_web(cls, bridge):
        """gh signed in as someone else: the web's four steps, the names to type as text that can be selected."""
        cls.report_on(bridge)
        script = cls.opening(bridge, "en")
        script["advanced-report-build"] = [job("j1")]
        script["advanced-report-check"] = [job("j2")]
        script["advanced-report-job"] = [ok(BUILT), ok(WEB)]
        steps = [{"do": "snapshot", "reply": snapshot(on=1)}, {"do": "show"}, {"do": "choose", "id": REPORT},
                 {"do": "type", "into": "login", "text": "ExampleUser"}, {"do": "press", "button": "report_write"},
                 {"do": "poll"}, {"do": "press", "button": "report_check"}, {"do": "poll"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_unloaded(cls, bridge):
        """An installation whose advanced package could not be loaded answers every advanced command as unknown:
        no tab, and nothing but the one question, asked again with each read."""
        refused = {"ok": False, "error": "unknown command", "error_code": "request_failed"}
        script = {"advanced-words": [refused], "advanced-list": [refused]}
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "snapshot", "reply": snapshot()}, {"do": "show"}]
        return "en", {"script": script, "steps": steps}, {}

    # ---------------------------------------------------------------- tests
    def test_the_tab_shows_once_this_edition_has_answered_with_its_words(self):
        result, expected = self.of("scenario_reading")
        before, after = result["looks"][0], result["looks"][1]
        self.assertFalse(before["tab_visible"])
        self.assertTrue(after["tab_visible"])
        self.assertEqual(after["tab"], expected["words"]["page.nav"])
        self.assertEqual(after["tab"], "고급 기능")
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][:3]],
                         ["advanced-words", "advanced-list", "advanced-statement"])
        self.assertEqual(sent(result, "advanced-words")[0], {"locale": "ko"})

    def test_every_capability_is_a_row_in_the_registry_s_order_by_name_and_state(self):
        result, expected = self.of("scenario_reading")
        words = expected["words"]
        self.assertEqual([row[:2] for row in result["rows"]],
                         [[words["name." + capability], words["state.off"]] for capability in IDS])
        self.assertEqual(len(IDS), 15)
        self.assertEqual(result["page"], "advanced")
        # The row chosen is the capability open, and nothing else is.
        self.assertEqual(result["open"], IDS[1])
        self.assertEqual([row[2] for row in result["rows"]], [capability == IDS[1] for capability in IDS])

    def test_the_open_capability_shows_its_statement_in_the_person_s_language(self):
        result, expected = self.of("scenario_reading")
        statement_ = expected["statements"][IDS[1]]
        words = expected["words"]
        head, about, limits = result["cards"]
        self.assertEqual(head[0], words["name." + IDS[1]])
        self.assertEqual(about[0], words["page.about"])
        # The five fields, each under its title - the standards it departs from among them, in words.
        fields = [text for field in statement_["fields"] for text in (field["title"], field["text"])]
        self.assertEqual(about[1:], fields)
        self.assertEqual(len(statement_["fields"]), 5)
        departs = next(field["text"] for field in statement_["fields"] if field["field"] == "departs")
        for standard in registry.REGISTRY.get(IDS[1]).departs_from:
            self.assertIn(standard, departs)
        self.assertGreater(len(departs), 12 * len(registry.REGISTRY.get(IDS[1]).departs_from),
                           "the standards are glossed in words, not listed as ids")
        self.assertEqual(limits[0], words["page.limits"])
        self.assertIn(words["page.hourly"], limits)
        # A number with a ceiling, edited as the Settings page edits every one: a spin box from 1 to the registry's.
        self.assertEqual(result["hourly"], {"minimum": 1, "maximum": registry.GLOBAL_HOURLY,
                                            "value": registry.GLOBAL_HOURLY})
        # It was read in Korean.
        self.assertEqual({json.loads(line.split(" ", 1)[1]).get("locale") for line in result["sent"]
                          if line.startswith("advanced-statement ")}, {"ko"})

    def test_turn_on_asks_with_the_statement_and_every_warning_and_sends_exactly_what_was_shown(self):
        result, expected = self.of("scenario_turn_on")
        shown = expected["statement"]
        self.assertTrue(shown["warnings"]["items"], "the scenario's statement carries a warning")
        head = result["looks"][0]["cards"][0]
        for item in shown["warnings"]["items"]:
            self.assertIn(item["text"], head)
        (question,) = result["asked"]
        for item in shown["warnings"]["items"]:
            self.assertIn(item["text"], question)
        self.assertIn(shown["warnings"]["note"], question)
        for field in shown["fields"]:
            self.assertIn(field["title"], question)
            self.assertIn(field["text"], question)
        self.assertIn(shown["engine_version"], question)
        (arm,) = sent(result, "advanced-arm")
        self.assertEqual(arm, {"capability": IDS[2], "state": "armed", "revision": shown["revision"],
                               "generation": expected["generation"], "engine_version": shown["engine_version"],
                               "warnings": [item["warning"] for item in shown["warnings"]["items"]]})
        self.assertEqual(result["note"], "%s is on." % "Marker-free continuation")
        # Read again after the action: the list, the statement and (v0.6.14) the watch log.
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][-3:]],
                         ["advanced-list", "advanced-statement", "advanced-watch-log"])

    def test_what_the_page_sends_is_what_the_real_bridge_takes(self):
        """The request the page wrote, put to this edition's real bridge in the state the page read: it turns the
        capability on, with the warnings confirmed - it is the person's own, current confirmation."""
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                bridge.measured = {}
                result, _ = self.of("scenario_turn_on")
                arm_line = next(line for line in result["sent"] if line.startswith("advanced-arm "))
                reply = bridge.request(arm_line)["result"]
                self.assertTrue(reply["done"], reply)
                listed = bridge("advanced-list", {})["result"]
                item = next(entry for entry in listed["capabilities"] if entry["id"] == IDS[2])
                self.assertEqual((item["state"], item["by"]), ("armed", "dashboard"))
                self.assertEqual(item["confirmed_warnings"], json.loads(arm_line.split(" ", 1)[1])["warnings"])
            finally:
                bridge.close()

    def test_cancel_sends_nothing(self):
        result, _ = self.of("scenario_declined")
        self.assertEqual(len(result["asked"]), 2)
        self.assertEqual(sent(result, "advanced-arm"), [])
        self.assertTrue(result["asked"][1].startswith("„%s“ erst beobachten?" % "Mit Codex starten"), result["asked"][1])

    def test_a_confirmation_that_went_stale_is_read_again_and_asked_again(self):
        result, expected = self.of("scenario_changed")
        self.assertEqual(expected["stale"]["refusal"], "stale_confirmation")
        first, second = sent(result, "advanced-arm")
        self.assertEqual(first["warnings"], [])
        after = expected["after"]
        self.assertEqual(second, {"capability": IDS[0], "state": "armed", "revision": after["revision"],
                                  "generation": expected["listing"]["generation"],
                                  "engine_version": after["engine_version"],
                                  "warnings": [item["warning"] for item in after["warnings"]["items"]]})
        self.assertIn("failed_here", second["warnings"])
        asked_first, asked_second = result["asked"]
        self.assertNotIn("Something changed", asked_first)
        self.assertTrue(asked_second.startswith("Something changed since this was shown."))
        (failed,) = [item for item in after["warnings"]["items"] if item["warning"] == "failed_here"]
        self.assertIn(failed["text"], asked_second)
        self.assertNotIn(failed["text"], asked_first)
        self.assertEqual(result["told"], [])
        # Between the two: the list and the statement read again.
        lines = [line.split(" ", 1)[0] for line in result["sent"]]
        between = lines[lines.index("advanced-arm") + 1:len(lines) - 1 - lines[::-1].index("advanced-arm")]
        self.assertEqual(between, ["advanced-list", "advanced-statement", "advanced-watch-log"])

    def test_the_second_confirmation_is_one_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                capability = IDS[0]
                compat = registry.REGISTRY.get(capability).compat
                bridge.view["capabilities"][compat] = {"state": "FAILED_HERE", "reason": "local_check_failed_here"}
                arms = [line for line in self.of("scenario_changed")[0]["sent"] if line.startswith("advanced-arm ")]
                self.assertEqual(bridge.request(arms[0])["result"]["refusal"], "stale_confirmation")
                self.assertTrue(bridge.request(arms[1])["result"]["done"])
            finally:
                bridge.close()

    def test_a_refusal_is_told_in_the_person_s_words(self):
        result, expected = self.of("scenario_refused")
        self.assertEqual(len(sent(result, "advanced-arm")), 1)
        self.assertEqual(sent(result, "advanced-arm")[0]["state"], "shadow")
        self.assertEqual(result["told"], [expected["words"]["page.policy.forbid"]])
        self.assertEqual(result["note"], "")

    def test_a_policy_says_what_it_refuses_and_the_buttons_follow_it(self):
        result, expected = self.of("scenario_policy")
        words = expected["words"]
        refused, allowed = result["looks"]
        self.assertEqual(refused["open"], IDS[0])
        self.assertIn(words["page.policy.not_allowed"], refused["cards"][0])
        self.assertEqual(refused["buttons"], {"on": False, "watch": False, "off": False, "all_off": True})
        self.assertEqual(allowed["open"], IDS[1])
        self.assertIn(words["page.policy.shadow_only"], allowed["cards"][0])
        self.assertEqual(allowed["buttons"], {"on": False, "watch": True, "off": False, "all_off": True})

    def test_turn_off_and_every_feature_off_send_theirs(self):
        result, expected = self.of("scenario_off")
        words = expected["words"]
        watched, off = result["looks"]
        self.assertEqual(watched["rows"][1][1], words["state.shadow"])
        self.assertEqual(watched["buttons"], {"on": True, "watch": False, "off": True, "all_off": True})
        self.assertEqual(sent(result, "advanced-disarm"), [{"capability": IDS[1]}])
        self.assertEqual(off["note"], words["page.done.off"].replace("{name}", words["name." + IDS[1]]))
        self.assertEqual(sent(result, "advanced-disarm-all"), [{}])
        self.assertEqual(result["note"], words["page.done.all_off"])
        self.assertEqual(result["asked"], [], "turning off asks nothing")
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][-3:]],
                         ["advanced-list", "advanced-statement", "advanced-watch-log"])

    def test_the_hourly_limit_is_lowered_with_the_generation_read(self):
        result, expected = self.of("scenario_hourly")
        self.assertEqual(result["looks"][0]["hourly"], {"minimum": 1,
                                                        "maximum": expected["listing"]["global_hourly_default"],
                                                        "value": expected["listing"]["global_hourly"]})
        self.assertEqual(sent(result, "advanced-ceiling"),
                         [{"global_hourly": 5, "generation": expected["listing"]["generation"]}])

    def test_the_hourly_request_is_one_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                (line,) = [line for line in self.of("scenario_hourly")[0]["sent"] if line.startswith("advanced-ceiling ")]
                self.assertTrue(bridge.request(line)["result"]["done"])
                self.assertEqual(bridge("advanced-list", {})["result"]["global_hourly"], 5)
            finally:
                bridge.close()

    def test_the_list_is_read_again_when_the_snapshot_says_it_changed(self):
        result, _ = self.of("scenario_followed")
        commands = [line.split(" ", 1)[0] for line in result["sent"]]
        counts = [int(look["requests"]) for look in result["looks"]]
        read = ["advanced-list", "advanced-statement", "advanced-watch-log"]
        # The words, the list, the statement and (v0.6.14) the watch log once this edition answers; then, with the first
        # badge seen, read again.
        self.assertEqual(commands[:counts[0]], ["advanced-words"] + read + read)
        # Away from the page, the same badge: nothing read.
        self.assertEqual(counts[1], counts[0])
        # Away from the page, a badge that changed: the list read again, and the open capability's statement.
        self.assertEqual(commands[counts[1]:counts[2]], read)
        # The tab pressed, and then on the page, each snapshot: read again.
        self.assertEqual(commands[counts[2]:counts[3]], read)
        self.assertEqual(commands[counts[3]:counts[4]], read)
        self.assertEqual(result["page"], "advanced")

    def test_the_cells_are_measured_again_only_when_a_word_changed(self):
        """With the page in front, every snapshot read the list again and measured all its cells (32 measurements every
        few seconds); the same rows in the same words now measure nothing, and a state that changed is measured."""
        result, _ = self.of("scenario_measured")
        first, again, third, changed = result["looks"]
        self.assertEqual(first["page"], "advanced")
        self.assertGreater(int(first["requests"]), 0)
        self.assertLess(int(first["requests"]), int(again["requests"]), "the snapshot read the list again")
        self.assertGreaterEqual(int(first["measures"]), 1, "the rows that came were not measured")
        self.assertEqual([int(look["measures"]) for look in (again, third)], [int(first["measures"])] * 2,
                         "the same list in the same words was measured again")
        self.assertNotEqual(changed["rows"][1][1], third["rows"][1][1])
        self.assertEqual(int(changed["measures"]), int(first["measures"]) + 1, "a state's new word was not measured")

    def test_ctrl_tab_goes_from_settings_to_this_page_and_on(self):
        pages = [look["page"] for look in self.of("scenario_keys")[0]["looks"]]
        self.assertEqual(pages, ["advanced", "overview", "advanced"])

    def test_a_confirmation_that_went_stale_and_cannot_be_read_again_is_told(self):
        """The person said yes and nothing was turned on: they are told, never left with a page that did nothing."""
        result, expected = self.of("scenario_changed_unreadable")
        words = expected["words"]
        self.assertEqual(len(sent(result, "advanced-arm")), 1)
        self.assertEqual(len(result["asked"]), 1)
        self.assertEqual(result["told"], [words["page.refused.unread"]])
        # Where the statement would be, why it cannot be turned on or watched.
        self.assertEqual(result["cards"][1], [words["page.about"], words["page.statement_unavailable"]])
        self.assertEqual((result["buttons"]["on"], result["buttons"]["watch"]), (False, False))
        result, expected = self.of("scenario_changed_unlisted")
        self.assertEqual(len(result["asked"]), 1)
        self.assertEqual(result["told"], [expected["words"]["page.refused.unread"]])
        self.assertEqual(result["cards"], [[expected["words"]["page.nav"], expected["words"]["page.unavailable"]]])

    def test_a_confirmation_that_went_stale_is_not_asked_again_where_a_policy_now_refuses_it(self):
        result, expected = self.of("scenario_changed_to_policy")
        forbid = expected["words"]["page.policy.forbid"]
        self.assertEqual(len(result["asked"]), 1, "nothing a policy refuses is asked for")
        self.assertEqual(len(sent(result, "advanced-arm")), 1)
        self.assertEqual(result["told"], [forbid])
        self.assertIn(forbid, result["cards"][0])
        self.assertEqual((result["buttons"]["on"], result["buttons"]["watch"]), (False, False))

    def test_a_capability_that_turned_itself_off_says_so_and_why(self):
        result, expected = self.of("scenario_tripped")
        words, item = expected["words"], expected["item"]
        self.assertEqual((item["stored"], item["state"], item["by"], item["reason"]),
                         ("off", "off", "tripwire", "measurement_failed"))
        tripped, by_person, by_engine = result["looks"]
        self.assertEqual(tripped["open"], "marker_free_continuation")
        self.assertEqual(tripped["cards"][0][:4], [words["name.marker_free_continuation"], words["page.col_state"],
                                                   words["state.off"], words["page.tripped.measurement_failed"]])
        said = {key: words[key] for key in words if key.startswith("page.tripped")}
        self.assertFalse(set(by_person["cards"][0]) & set(said.values()), "a person's own turning off is not a tripwire")
        self.assertIn(words["page.tripped.engine_changed"], by_engine["cards"][0])

    def test_a_choice_is_a_drop_down_whose_choice_is_sent_at_once(self):
        result, expected = self.of("scenario_choices")
        words = expected["words"]
        (shown,) = result["looks"]
        self.assertEqual(shown["choices"], [{"key": "ceiling_hours", "enabled": True, "value": "2 h",
                                             "items": ["%d h" % hours for hours in (1, 2, 3, 4, 6, 8, 12)]}])
        titles = [card[0] for card in shown["cards"]]
        self.assertEqual(titles[-1], words["page.options"])
        self.assertIn(words["page.option.ceiling_hours"], shown["cards"][-1])
        generation = expected["listing"]["generation"]
        self.assertEqual(sent(result, "advanced-option"),
                         [{"capability": "capacity_retry", "key": "ceiling_hours", "value": 4, "generation": generation},
                          {"capability": "capacity_retry", "key": "ceiling_hours", "value": 6, "generation": generation}])
        self.assertEqual(result["told"], [words["page.refused.choice"]])
        self.assertEqual(result["looks"][0]["note"], "")

    def test_keep_it_on_asks_with_each_warning_sends_what_was_confirmed_and_lets_go_asking_nothing(self):
        result, expected = self.of("scenario_keep_on")
        words = expected["words"]
        name = words["name.capacity_retry"]
        first, once, twice, after, send_now = result["looks"]
        card = next(card for card in first["cards"] if card[0] == words["page.keep_on"])
        self.assertEqual(card[1], words["page.keep_on.off"])
        self.assertEqual(first["kept"], {"keep_on": True, "send_again": None, "let_go": None})
        self.assertEqual(once["kept"], {"keep_on": None, "send_again": True, "let_go": True})
        self.assertIn(words["page.keep_on.on"], next(card for card in once["cards"] if card[0] == words["page.keep_on"]))
        self.assertEqual(twice["kept"], {"keep_on": None, "send_again": None, "let_go": True})
        self.assertIn(words["page.keep_on.again"], next(card for card in twice["cards"] if card[0] == words["page.keep_on"]))
        self.assertEqual(after["kept"], first["kept"])
        self.assertEqual(once["note"], words["page.done.keep_on"].replace("{name}", name))
        self.assertEqual(after["note"], words["page.done.keep_on_off"].replace("{name}", name))
        self.assertEqual(result["asked"], [words["page.confirm.keep_on"].replace("{name}", name),
                                           words["page.confirm.send_again"].replace("{name}", name)])
        first_generation, second_generation = expected["generations"]
        self.assertEqual(sent(result, "advanced-keep-on"), [
            {"capability": "capacity_retry", "keep_on": True, "send_again": False, "generation": first_generation,
             "confirmed": ["keep_on"]},
            {"capability": "capacity_retry", "keep_on": True, "send_again": True, "generation": second_generation,
             "confirmed": ["keep_on", "send_again"]},
            {"capability": "capacity_retry", "keep_on": False, "send_again": False}])
        self.assertEqual(result["told"], [])
        # Send now off: no card of waiting recoveries, and no Keep it on for what is off.
        self.assertEqual(send_now["send_now"], [])
        self.assertEqual(send_now["kept"], {"keep_on": None, "send_again": None, "let_go": None})
        self.assertNotIn(words["page.send_now.title"], [card[0] for card in send_now["cards"]])

    def test_what_keep_it_on_sends_is_what_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                self.watched(bridge, "capacity_retry")
                line = next(line for line in self.of("scenario_keep_on")[0]["sent"] if line.startswith("advanced-keep-on "))
                self.assertTrue(bridge.request(line)["result"]["done"])
                item = next(entry for entry in bridge("advanced-list", {})["result"]["capabilities"]
                            if entry["id"] == "capacity_retry")
                self.assertEqual((item["keep_on"], item["send_again"]), (True, False))
            finally:
                bridge.close()

    def test_a_kept_on_notice_and_a_duplicate_trip_are_said_in_the_accent(self):
        result, expected = self.of("scenario_kept_notice")
        words = expected["words"]
        kept, tripped = result["looks"]
        self.assertIn(words["page.kept.engine_changed"], kept["cards"][0])
        self.assertIn(words["page.tripped.duplicate_seen"], tripped["cards"][0])
        self.assertNotIn(words["page.keep_on"], [card[0] for card in tripped["cards"]], "off: nothing to keep on")

    def test_an_action_kept_on_is_never_offered_send_again(self):
        result, expected = self.of("scenario_action_kept")
        words = expected["words"]
        look, = result["looks"]
        self.assertEqual(look["kept"], {"keep_on": None, "send_again": None, "let_go": True})
        self.assertIn(words["page.keep_on.on"], next(card for card in look["cards"] if card[0] == words["page.keep_on"]))
        self.assertEqual((expected["refused"]["done"], expected["refused"]["refusal"]), (False, "invalid_request"))

    def test_send_now_offers_each_waiting_recovery_asks_first_and_sends_its_id(self):
        result, expected = self.of("scenario_send_now")
        words = expected["words"]
        pending = expected["pending"]
        shown, after = result["looks"]
        waiting = [row["interruption_id"] for row in pending if row["code"] in ("waiting_reset", "scheduled")]
        self.assertEqual(shown["send_now"], waiting)
        card = next(card for card in shown["cards"] if card[0] == words["page.send_now.title"])
        self.assertIn(pending[0]["name"], card[1])
        self.assertEqual(sent(result, "advanced-send-now"),
                         [{"interruption_id": pending[0]["interruption_id"]},
                          {"interruption_id": pending[1]["interruption_id"]}], "declined, nothing is sent")
        self.assertEqual(result["asked"], [words["page.confirm.send_now"]] * 3)
        self.assertEqual(after["note"], words["page.done.send_now"])
        self.assertEqual(result["told"], [words["page.refused.not_on"]])
        self.assertEqual(result["disabled"], ["send_now"], "a recovery whose turn is running is not offered")

    def test_what_send_now_sends_is_what_the_real_bridge_takes(self):
        from codex_auto_resume_advanced.control import sendnow
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                self.watched(bridge, "send_now", state="armed")
                line = next(line for line in self.of("scenario_send_now")[0]["sent"] if line.startswith("advanced-send-now "))
                with patch.object(sendnow, "wake", return_value=True) as woken:
                    self.assertTrue(bridge.request(line)["result"]["done"])
                self.assertEqual(woken.call_count, 1)
            finally:
                bridge.close()

    # ---------------------------------------------------------------- the reset actions
    def test_a_message_at_a_reset_is_added_from_the_form_asking_first_and_cancelled_at_once(self):
        result, expected = self.of("scenario_reset_message")
        words, thread, rule = expected["words"], expected["thread"], expected["rule"]
        empty, weekly, added, cancelled = result["looks"]
        self.assertEqual(empty["open"], "reset_message")
        form = empty["resets"]
        self.assertEqual(form["families"], ["The 5-hour limit", "The weekly limit"])
        self.assertEqual(form["ordinals"], ["The next one"] + ["%d from now" % n for n in range(2, 10)])
        label = "%s (%s)" % (expected["pending"][1]["name"], thread[:8])
        self.assertIn(label, form["conversations"], "a name two conversations share, told apart by the id")
        self.assertEqual(len(form["conversations"]), len(set(form["conversations"])), "two of one name are told apart")
        self.assertEqual((form["most"], form["count"], form["add"]), (2000, "0 of 2000 characters", False))
        card = next(card for card in empty["cards"] if card[0] == words["page.resets.message.title"])
        self.assertIn(words["page.resets.message.none"], card)
        self.assertNotIn(words["page.resets.unproven"], card, "MU passed on this Codex")
        self.assertEqual(weekly["resets"]["ordinals"], ["The next one"], "a weekly window offers only its next reset")
        self.assertIn("reset_add", result["disabled"], "no words, no Add")
        self.assertEqual(sent(result, "advanced-reset-add"),
                         [{"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 3, "thread_id": thread,
                           "words": self.WORDS, "generation": expected["generations"][0]}], "declined, nothing is sent")
        asked = words["page.confirm.reset_message"].replace("{window}", "the 5-hour limit").replace("{which}", "3 from now")
        self.assertEqual(result["asked"][0], asked.replace("{conversation}", label))
        self.assertEqual(len(result["asked"]), 2)
        self.assertEqual(added["note"], words["page.done.reset_added"])
        self.assertEqual(added["resets"]["cancels"], [rule])
        card = next(card for card in added["cards"] if card[0] == words["page.resets.message.title"])
        line = next(text for text in card if text.startswith("A message to "))
        self.assertIn(label, line)
        self.assertIn("(3 from now)", line)
        self.assertIn("\u201c%s\u201d" % self.WORDS, card)
        self.assertEqual(added["resets"]["words"], "", "what was added is not left in the box")
        self.assertEqual(sent(result, "advanced-reset-cancel"), [{"rule": rule, "generation": expected["generations"][1]}])
        self.assertEqual(cancelled["resets"]["cancels"], [])

    def test_a_reset_credit_rule_offers_go_on_and_use_now_and_is_added_with_how_often_and_asking(self):
        result, expected = self.of("scenario_reset_credit")
        words, due, held = expected["words"], expected["due"], expected["held"]
        shown, after = result["looks"]
        form = shown["resets"]
        self.assertEqual(form["repeat"], [words["page.resets.repeat.once"], words["page.resets.repeat.every"]])
        self.assertEqual(form["ask"], [words["page.resets.ask.no"], words["page.resets.ask.yes"]])
        self.assertEqual(form["conversations"], None, "a credit is for no conversation")
        self.assertEqual(form["cancels"], [due, held])
        self.assertEqual(form["go_ons"], [held])
        self.assertEqual(form["now"], [due, "codex 300"])
        card = next(card for card in shown["cards"] if card[0] == words["page.resets.credit.title"])
        self.assertTrue(card[1].startswith("Reset credits: 3 \u00b7 "), card[1])
        self.assertTrue(any(words["page.resets.state.ask_first"] in text for text in card))
        self.assertTrue(any(words["page.resets.state.count_gap"] in text for text in card))
        self.assertIn(words["page.resets.unproven"], card, "MU is not measured on this Codex")
        self.assertEqual(sent(result, "advanced-reset-add"),
                         [{"kind": "credit", "bucket": "codex", "minutes": 10080, "ordinal": 1, "repeat": True,
                           "ask_first": True, "generation": expected["generation"]}])
        self.assertEqual(sent(result, "advanced-credit-now"),
                         [{"bucket": "codex", "minutes": 300, "generation": expected["generation"]}], "declined, nothing")
        self.assertEqual(sent(result, "advanced-reset-go-on"), [{"rule": held, "generation": expected["generation"]}])
        self.assertEqual(result["asked"][1:], [words["page.confirm.credit_now"].replace("{window}", "the 5-hour limit")] * 2)
        self.assertEqual(after["note"], words["page.done.go_on"])

    def test_what_the_reset_forms_send_is_what_the_real_bridge_takes(self):
        from codex_auto_resume_advanced.control import sendnow
        message, _ = self.of("scenario_reset_message")
        credit, _ = self.of("scenario_reset_credit")
        with tempfile.TemporaryDirectory() as home, patch.object(sendnow, "wake", return_value=True):
            bridge = Bridge(Path(home))
            try:
                self.watched(bridge, "reset_message", state="armed")
                lines = [line for line in message["sent"] if line.startswith(("advanced-reset-add ", "advanced-reset-cancel "))]
                self.assertEqual(len(lines), 2, "one added, one cancelled")
                for line in lines:
                    with self.subTest(line):
                        reply = bridge.request(line)["result"]
                        self.assertTrue(reply["done"], reply)
            finally:
                bridge.close()
        with tempfile.TemporaryDirectory() as home, patch.object(sendnow, "wake", return_value=True):
            bridge = Bridge(Path(home))
            try:
                self.credit_rules(bridge)
                lines = [line for line in credit["sent"]
                         if line.startswith(("advanced-reset-add ", "advanced-credit-now ", "advanced-reset-go-on "))]
                self.assertEqual(len(lines), 3, "one added, one used now, one let go on")
                for line in lines:
                    with self.subTest(line):
                        reply = bridge.request(line)["result"]
                        self.assertTrue(reply["done"], reply)
            finally:
                bridge.close()

    def test_pending_shows_each_scheduled_rule_with_cancel_only_while_one_waits(self):
        result, expected = self.of("scenario_scheduled")
        words, rule = expected["words"], expected["rule"]
        before, read, again, cancelled = result["looks"]
        self.assertEqual(expected["counts"]["messages"], 1)
        self.assertEqual(before["page"], "pending")
        self.assertFalse(before["scheduled"]["group_shown"])
        self.assertEqual(len(sent(result, "advanced-resets")), 3,
                         "read when the counts changed, after Go on counting and after Cancel")
        self.assertTrue(read["scheduled"]["group_shown"])
        self.assertEqual(read["scheduled"]["cancels"], [rule])
        self.assertEqual(read["scheduled"]["go_ons"], [rule], "one held over a gap can be let go on from Pending too")
        texts = read["scheduled"]["texts"]
        self.assertEqual(texts[0], words["page.scheduled"])
        self.assertIn(expected["pending"][0]["name"], texts[1])
        self.assertNotIn(self.WORDS, " ".join(texts), "Pending shows no words of a message")
        self.assertEqual(again["requests"], read["requests"], "the same counts read nothing again")
        generation = sent(result, "advanced-reset-cancel")[0]["generation"]
        self.assertEqual(sent(result, "advanced-reset-go-on"), [{"rule": rule, "generation": generation}])
        self.assertEqual(sent(result, "advanced-reset-cancel"), [{"rule": rule, "generation": generation}])
        self.assertFalse(cancelled["scheduled"]["group_shown"])
        self.assertEqual(cancelled["scheduled"]["cancels"], [])

    def test_longer_reset_messages_says_what_it_lets_a_message_be_and_has_no_report_card(self):
        result, expected = self.of("scenario_long_messages")
        words = expected["words"]
        (look,) = result["looks"]
        self.assertEqual(look["open"], "long_reset_message")
        limits = next(card for card in look["cards"] if card[0] == words["page.limits"])
        self.assertIn(words["page.long_limits"].replace("{n}", "2000"), limits)
        self.assertNotIn(words["page.action_limits"], limits)
        self.assertNotIn(words["page.report.title"], [card[0] for card in look["cards"]])

    def test_the_choice_sent_is_one_the_real_bridge_takes(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                line = next(line for line in self.of("scenario_choices")[0]["sent"] if line.startswith("advanced-option "))
                self.assertTrue(bridge.request(line)["result"]["done"])
                item = next(entry for entry in bridge("advanced-list", {})["result"]["capabilities"]
                            if entry["id"] == "capacity_retry")
                self.assertEqual(item["options"][0]["value"], 4)
            finally:
                bridge.close()

    def test_the_rules_are_listed_added_and_removed_and_a_refusal_is_told(self):
        result, expected = self.of("scenario_rules")
        words = expected["words"]
        first, after = result["looks"]
        rules = next(card for card in first["cards"] if card[0] == words["page.rules"])
        self.assertIn("brandNewVariant \u00b7 500\u2013599 \u00b7 Server error \u00b7 %s: 0" % words["page.rule.hits"], rules)
        self.assertEqual(first["rules"], {"removes": [1], "add": True, "sampled": ["seenOnlyHere"],
                                          "kinds": ["Network problem", "Timeout", "Rate limit", "Server error",
                                                    "Interrupted response"]})
        generation = expected["listing"]["generation"]
        add, refused = sent(result, "advanced-rule-add")
        self.assertEqual(add, {"tag": "seenOnlyHere", "status_from": 502, "status_to": 504, "category": "timeout",
                               "generation": generation})
        self.assertEqual(refused["tag"], "policyRefused")
        self.assertEqual(sent(result, "advanced-rule-remove"), [{"rule": 1, "generation": generation}])
        self.assertEqual(after["note"], words["page.done.rule_removed"])
        self.assertEqual(result["told"], [words["page.refused.rule_decision"], words["page.refused.rule_shape"]])
        self.assertEqual(len(sent(result, "advanced-rule-add")), 2, "a code of the wrong shape is never sent")
        # Read again after each action: the list, the statement, the rules and (v0.6.14) the watch log.
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"][-4:]],
                         ["advanced-list", "advanced-statement", "advanced-rules", "advanced-watch-log"])

    def test_the_rules_the_page_sends_are_ones_the_real_bridge_takes_and_refuses(self):
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                self.rules_home(bridge)
                lines = self.of("scenario_rules")[0]["sent"]
                add, refused = [line for line in lines if line.startswith("advanced-rule-add ")]
                self.assertTrue(bridge.request(add)["result"]["done"])
                removed = next(line for line in lines if line.startswith("advanced-rule-remove "))
                stale = bridge.request(removed)["result"]
                self.assertEqual(stale["refusal"], "stale_generation", "the add moved the generation on")
                self.assertTrue(bridge("advanced-rule-remove", dict(json.loads(removed.split(" ", 1)[1]),
                                                                    generation=stale["generation"]))["result"]["done"])
                current = bridge("advanced-list", {})["result"]["generation"]
                self.assertEqual(bridge("advanced-rule-add", dict(json.loads(refused.split(" ", 1)[1]), generation=current))
                                 ["result"]["refusal"], "rule_decision")
                self.assertEqual([rule["tag"] for rule in bridge("advanced-rules", {})["result"]["rules"]],
                                 ["seenOnlyHere"])
            finally:
                bridge.close()

    def test_the_samples_are_listed_codes_and_numbers_only(self):
        result, expected = self.of("scenario_samples")
        words = expected["words"]
        seen, none = result["looks"]
        samples = seen["cards"][-1]
        self.assertEqual(samples, [words["page.samples"],
                                   "%s: brandNewVariant \u00b7 %s: 503 \u00b7 %s: 2" % (
                                       words["page.sample.code"], words["page.sample.status"], words["page.sample.count"]),
                                   "%s: %s \u00b7 %s: - \u00b7 %s: 1" % (
                                       words["page.sample.code"], words["page.sample.no_code"], words["page.sample.status"],
                                       words["page.sample.count"])])
        self.assertEqual(seen["choices"], [{"key": "attempts", "enabled": True, "value": "1", "items": ["1", "2", "3"]}])
        self.assertEqual(none["cards"][-1], [words["page.samples"], words["page.samples.none"]])
        self.assertIsNone(seen["rules"])

    @staticmethod
    def on_the_clock(at) -> str:
        """A minute as the window prints it (gui/DashboardData.cs When): this PC's time."""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))

    def test_the_watch_log_shows_what_it_would_have_done_minutes_and_counts_only(self):
        result, expected = self.of("scenario_watch_log")
        words = expected["words"]
        replies = expected["replies"]
        lines, none, off, _full, report = result["looks"]
        title = words["page.watchlog"]
        since = words["page.watchlog.since"].replace("{time}", self.on_the_clock(replies["lines"]["watched_since"]))
        late = self.on_the_clock(watchlog.minute(ac.NOW - 60))
        self.assertEqual(lines["open"], "early_reset")
        self.assertEqual(lines["cards"][-1], [
            title, since,
            "%s \u00b7 %s: 2 \u00b7 %s: %s" % (words["page.watchlog.answer.early"], words["page.watchlog.times"],
                                              words["page.watchlog.last"], late),
            "%s \u00b7 %s: 1 \u00b7 %s: %s" % (words["page.watchlog.answer.hold"], words["page.watchlog.times"],
                                              words["page.watchlog.last"], late),
            words["page.watchlog.note"]])
        self.assertEqual(none["cards"][-1], [title, since, words["page.watchlog.none"], words["page.watchlog.note"]])
        self.assertEqual((replies["off"]["watched_since"], replies["off"]["entries"]), (None, []))
        self.assertNotIn(title, [card[0] for card in off["cards"]], "off, with nothing counted: no card")
        # Its other cards are where they were: the watch log is the last, and moves none of them.
        self.assertEqual([card[0] for card in lines["cards"][:-1]], [card[0] for card in off["cards"]])
        self.assertEqual(report["open"], REPORT)
        self.assertNotIn(title, [card[0] for card in report["cards"]], "an action is never asked anything")

    def test_a_full_log_says_from_when_it_counts(self):
        result, expected = self.of("scenario_watch_log")
        words = expected["words"]
        card = result["looks"][3]["cards"][-1]
        said = words["page.watchlog.from"].replace("{time}", self.on_the_clock(watchlog.minute(ac.NOW - 3600)))
        self.assertEqual(card[0], words["page.watchlog"])
        self.assertEqual(card[-2:], [said, words["page.watchlog.note"]])
        self.assertNotIn(said, result["looks"][0]["cards"][-1], "a log the bound has not cut says nothing of it")

    def test_what_the_watch_log_asks_is_one_the_real_bridge_takes(self):
        """Every request names one capability, the one whose cards are open - the first one too, before any is chosen -
        and never an action; put to this edition's real bridge, each is answered."""
        result, _ = self.of("scenario_watch_log")
        asked = sent(result, "advanced-watch-log")
        self.assertTrue(asked)
        self.assertIn({"capability": "early_reset"}, asked)
        self.assertIn({"capability": IDS[0]}, asked, "the first capability's cards are open before any is chosen")
        self.assertNotIn({"capability": REPORT}, asked)
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                for line in [line for line in result["sent"] if line.startswith("advanced-watch-log ")]:
                    with self.subTest(line):
                        self.assertEqual(set(json.loads(line.split(" ", 1)[1])), {"capability"})
                        reply = bridge.request(line)["result"]
                        self.assertTrue(reply["done"], reply)
            finally:
                bridge.close()

    def test_a_window_that_reopens_on_this_page_comes_back_to_it(self):
        result, _ = self.of("scenario_reopen")
        here, elsewhere = result["reopened"]
        self.assertEqual(here, self.REOPENED)
        self.assertNotIn("advanced", elsewhere)
        self.assertTrue(elsewhere.startswith("--page=history "), elsewhere)
        result, _ = self.of("scenario_reopened")
        opened, answered = result["looks"]
        self.assertEqual((opened["page"], opened["tab_visible"]), ("overview", False))
        self.assertEqual((answered["page"], answered["tab_visible"], answered["focus"]),
                         ("advanced", True, "page.advanced"))
        self.assertEqual([row[0] for row in answered["rows"]],
                         [statement.CATALOGS.words("en")["name." + capability] for capability in IDS])

    # ---------------------------------------------------------------- the compatibility report
    def report_card(self, look, words) -> list:
        """The report's card among the open capability's cards: under its heading's, which bears the capability's
        name - the same words, "Compatibility report", in English."""
        (card,) = [card for card in look["cards"][1:] if card and card[0] == words["page.report.title"]]
        return card

    def test_an_action_says_it_sends_nothing_to_codex_where_the_others_show_their_limits(self):
        result, expected = self.of("scenario_report_watched")
        words = expected["words"]
        (look,) = result["looks"]
        self.assertEqual(look["open"], REPORT)
        limits = next(card for card in look["cards"] if card[0] == words["page.limits"])
        self.assertIn(words["page.action_limits"], limits)
        self.assertNotIn(words["page.per_day"], limits)
        self.assertNotIn(words["page.nominal"], limits)
        cards = [card[0] for card in look["cards"]][1:]
        self.assertLess(cards.index(words["page.about"]), cards.index(words["page.report.title"]))
        self.assertLess(cards.index(words["page.report.title"]), cards.index(words["page.limits"]))

    def test_watched_the_report_is_written_and_saved_and_never_checked_or_sent(self):
        result, expected = self.of("scenario_report_watched")
        words = expected["words"]
        (look,) = result["looks"]
        card = self.report_card(look, words)
        self.assertIn(words["page.report.watched"], card)
        self.assertEqual(look["report"]["buttons"], {"write": True, "save": True, "check": None, "send": None})
        self.assertEqual(look["report"]["file"].replace("\r\n", "\n"), FILE)
        self.assertEqual(sent(result, "advanced-report-check"), [])
        self.assertEqual(sent(result, "advanced-report-build"), [{"login": "ExampleUser"}])

    def test_on_the_report_is_written_saved_checked_and_sent_only_on_exactly_the_word(self):
        result, expected = self.of("scenario_report_sent")
        words = expected["words"]
        looks = result["looks"]
        fresh, writing, written, saved, checking, checked, not_word, word, sending, still, done = looks
        self.assertEqual(fresh["report"]["buttons"], {"write": True, "save": None, "check": None, "send": None})
        self.assertEqual(sent(result, "advanced-report-build"), [{"login": "ExampleUser"}], "the login, trimmed")
        self.assertIn(words["page.report.writing"], self.report_card(writing, words))
        self.assertEqual((writing["report"]["kind"], writing["report"]["buttons"]["write"]), ("build", False))
        self.assertIn(SHA, written["report"]["boxes"])
        self.assertEqual(written["report"]["buttons"], {"write": True, "save": True, "check": True, "send": None})
        self.assertEqual(sent(result, "advanced-report-save"), [{"sha256": SHA, "path": "C:\\Reports\\codex-cli-0.158.0.json"}])
        self.assertEqual(saved["report"]["told"], words["page.report.saved"])
        self.assertEqual(sent(result, "advanced-report-check"), [{"sha256": SHA}])
        self.assertEqual((checking["report"]["kind"], checking["report"]["holds"]), ("check", 1))
        card = self.report_card(checked, words)
        self.assertIn(words["page.report.interrupted"], card)
        self.assertIn("• " + words["page.report.w.branch_new"].replace("{name}", BRANCH), card)
        self.assertIn(CHECKED["gh"], checked["report"]["boxes"])
        self.assertEqual(checked["report"]["holds"], 0, "the check let the reopen go")
        self.assertFalse(not_word["report"]["buttons"]["send"])
        self.assertIn("report_send", result["disabled"], "Send could not be pressed on any other word")
        self.assertTrue(word["report"]["buttons"]["send"])
        (request,) = sent(result, "advanced-report-send")
        self.assertEqual(request, {"sha256": SHA, "writes": WRITES, "word": "send"})
        self.assertEqual(set(request), set(surfaces.ARGUMENTS["advanced-report-send"]))
        self.assertEqual((sending["report"]["kind"], sending["report"]["holds"]), ("send", 1))
        self.assertIn(words["page.report.sending"], self.report_card(sending, words))
        self.assertTrue(sending["buttons"]["off"], "Turn off stays live while a send runs")
        self.assertEqual(still["report"]["holds"], 1)
        self.assertEqual((done["report"]["holds"], done["report"]["last"], done["report"]["job"]), (0, "sent", None))
        self.assertIn(SENT["url"], done["report"]["boxes"])
        self.assertIn(words["page.report.after"], self.report_card(done, words))
        self.assertEqual(sending["report"]["word"], "", "the word is typed again for every send")
        self.assertIsNone(done["report"]["word"], "no box for the word once the send has ended")

    def test_what_the_card_sends_is_what_the_real_bridge_takes(self):
        result, _ = self.of("scenario_report_sent")
        for command in ("advanced-report-build", "advanced-report-save", "advanced-report-check", "advanced-report-send",
                        "advanced-report-job"):
            with self.subTest(command):
                for request in sent(result, command):
                    self.assertEqual(set(request), set(surfaces.ARGUMENTS[command]))
        with tempfile.TemporaryDirectory() as home:
            bridge = Bridge(Path(home))
            try:
                self.report_on(bridge)
                for line in result["sent"]:
                    if line.startswith("advanced-report-"):
                        with self.subTest(line=line[:40]):
                            reply = bridge.request(line)
                            self.assertTrue(reply["ok"], reply)
                            self.assertNotEqual(reply["result"].get("refusal"), "invalid_request")
            finally:
                bridge.close()

    def test_a_send_it_cannot_account_for_is_lost_and_checking_again_is_the_way_to_tell(self):
        result, expected = self.of("scenario_report_lost")
        words = expected["words"]
        send_lost, check_lost = result["looks"]
        for look in (send_lost, check_lost):
            self.assertEqual((look["report"]["last"], look["report"]["holds"]), ("lost", 0))
            self.assertIn(words["page.report.lost"], self.report_card(look, words))
        self.assertEqual(result["told"], [], "a lost send is shown, never told as a refusal")

    def test_turned_off_mid_send_the_card_keeps_how_the_send_ended(self):
        result, expected = self.of("scenario_report_turned_off")
        words = expected["words"]
        sending, off, ended = result["looks"]
        self.assertTrue(sending["buttons"]["off"])
        self.assertEqual(sent(result, "advanced-disarm"), [{"capability": REPORT}])
        self.assertEqual(off["report"]["buttons"], {"write": None, "save": None, "check": None, "send": None})
        self.assertEqual(off["report"]["holds"], 1, "the send still runs, and still holds the reopen")
        card = self.report_card(ended, words)
        self.assertEqual(card[:2], [words["page.report.title"], words["page.report.last"]])
        self.assertIn(words["page.report.partial"], card)
        self.assertIn(words["page.report.refused.paused"], card)
        self.assertIn(words["page.report.again"], card)
        self.assertEqual(ended["report"]["holds"], 0)

    def test_on_the_web_the_names_to_type_can_be_selected_and_nothing_is_opened(self):
        result, expected = self.of("scenario_report_web")
        words = expected["words"]
        (look,) = result["looks"]
        card = self.report_card(look, words)
        self.assertIn(words["page.report.web.gh_other_login"].replace("{name}", "SomeoneElse"), card)
        self.assertIn(words["page.report.web.intro"].replace("{name}", "ExampleUser"), card)
        for step in ("1", "2", "3", "4"):
            self.assertIn("%s. %s" % (step, words["page.report.web." + step]), card)
        for name in (PROJECT, BRANCH, TARGET):
            self.assertIn(name, look["report"]["boxes"])
        self.assertIsNone(look["report"]["buttons"]["send"])

    def test_an_installation_that_cannot_answer_shows_no_tab(self):
        result, _ = self.of("scenario_unloaded")
        self.assertFalse(result["tab_visible"])
        self.assertEqual(result["page"], None)
        self.assertEqual([line.split(" ", 1)[0] for line in result["sent"]], ["advanced-words", "advanced-words"])
        self.assertEqual(result["rows"], [])


def audit_data(locale: str, bridge: Bridge) -> dict:  # noqa: C901 - one layout's data
    """The fullest the page shows in `locale`: every capability, the first two refused by a policy, each statement
    with every warning there is, the rules with one the product has come to know and codes the samples saw, the
    samples with a code and without one, and the compatibility report's card in each of its states."""
    words = bridge("advanced-words", {"locale": locale})["result"]["words"]
    listing = bridge("advanced-list", {})["result"]
    listing["policy"] = {"forbid": False, "force_shadow": True, "allowed": [IDS[2]]}
    statements = {}
    for capability in IDS:
        made = bridge("advanced-statement", {"capability": capability, "locale": locale})["result"]
        made["warnings"]["items"] = [{"warning": str(word), "text": statement.CATALOGS.text(statement.warning_key(word), locale)}
                                     for word in ArmingWarning]
        statements[capability] = made
    rules = bridge("advanced-rules", {})["result"]
    if not rules["rules"]:
        for tag, low, high in (("brandNewVariant", 500, 599), ("anotherVeryLongCodeOfCodexsOwnNamingSomethingNew", None, None)):
            assert bridge("advanced-rule-add", {"tag": tag, "status_from": low, "status_to": high, "category": "stream_interrupted",
                                                "generation": bridge("advanced-list", {})["result"]["generation"]})["result"]["done"]
        rules = bridge("advanced-rules", {})["result"]
    rules["rules"][0]["known"] = True
    rules["tags"] = ["brandNewVariant", "seenOnlyInTheSamples"]
    samples = {"done": True, "samples": [
        {"tag": "anotherVeryLongCodeOfCodexsOwnNamingSomethingNew", "status": 503, "form": "tagged", "count": 12, "last": "2027-01-15"},
        {"tag": None, "status": None, "form": "absent", "count": 1, "last": "2027-01-14"}]}
    # Each capability on (v0.6.14), so its Keep it on card shows: by turns not kept on, kept on with its longest notice,
    # and kept on sending again with a resend found twice; Send now on, with the waiting recoveries of the fullest snapshot.
    # An action is never given Send again, and an error of its own is the one notice it can have.
    for index, item in enumerate(listing["capabilities"]):
        action = item["kind"] == "action"
        item.update(stored="armed", state="armed", keep_on=index % 3 != 0, send_again=index % 3 == 2 and not action,
                    notice="hook_exception" if action else (None, "local_check_failed", "duplicate_seen")[index % 3])
    # What each would have done while watched, at its fullest: every answer the log names and one it does not, each
    # counted more often than anyone would see, watched, and cut by the bound.
    first = watchlog.minute(ac.NOW - 29 * 86400)
    watch = {"done": True, "capability": IDS[0], "days": watchlog.WINDOW_DAYS, "watched_since": watchlog.minute(ac.NOW),
             "from": first, "full": True,
             "entries": [{"answer": None if word is None else str(word), "points": ["schedule"], "count": 123456,
                          "first": first, "last": watchlog.minute(ac.NOW)} for word in watchlog.WORDS + (None,)]}
    shot = snapshot()
    return {"words": words, "listing": listing, "statements": statements,
            "kept": {"advanced-rules": rules, "advanced-samples": samples, "advanced-watch-log": watch,
                     "pending": shot["pending"], "advanced-resets": fullest_resets(shot, listing["generation"]),
                     "snapshot": shot},
            "reports": report_states()}


# How long one view of one audit may take to lay out, at most: what it takes on a quiet PC (about 7 seconds at
# v0.6.14), with room for a slower one. A hang is what this catches.
AUDIT_SECONDS = 12


def audited_views() -> int:
    """The views each audit lays out: each capability open, then unread, the narrowest window on two screens, the
    action's card in each report state, and Pending with the reset rules scheduled under its list."""
    return len(IDS) + 3 + len(report_states()) + 1


def audit_timeout(jobs: int, workers: int) -> int:
    """The time the slowest of `workers` processes sharing `jobs` audits is allowed: its share of them, each
    audited_views() views."""
    return AUDIT_SECONDS * audited_views() * -(-jobs // workers)


def fullest_resets(shot, generation) -> dict:
    """advanced-resets at its fullest, as control/resets.view answers: a credit due that waits for a click, one
    counting for the weekly limit, a message held over a gap with words as long as may be, one being sent for a window of
    another length, one counting - and three windows, two full now, the credits read and one used."""
    now = int(ac.NOW)
    long_words = ("Carry on with the release notes, then check every link on the download page once more. " * 40)[:2000]

    def rule(rule_id, capability, minutes, ordinal, state, reason=None, thread=None, words=None, counted=None,
             being_sent=False):
        return {"rule_id": rule_id, "capability": capability, "bucket": "codex", "minutes": minutes, "ordinal": ordinal,
                "repeat": False, "ask_first": capability == "reset_credit", "state": state, "reason": reason,
                "gate": None, "gate_reason": None, "created_at": now - 7200, "adopted_at": now - 7000, "due_at": None,
                "sent_at": None, "finished_at": None, "thread_id": thread, "counted": counted,
                "next_reset": now + 3600, "words": words, "being_sent": being_sent}

    pending = shot["pending"]
    return {"done": True, "refusal": None, "generation": generation,
            "rules": [rule(1, "reset_credit", 300, 1, "ready", "ask_first"),
                      rule(2, "reset_credit", 10080, 1, "counting", counted=0),
                      rule(3, "reset_message", 300, 9, "held", "count_gap", pending[0]["thread_id"], long_words),
                      rule(4, "reset_message", 60, 2, "ready", None, pending[1]["thread_id"], "Carry on.", being_sent=True),
                      rule(5, "reset_message", 300, 1, "counting", None, pending[2]["thread_id"], "Carry on.", counted=0)],
            "families": [{"bucket": "codex", "minutes": 60, "open_reset_at": now + 600, "open_full": True},
                         {"bucket": "codex", "minutes": 300, "open_reset_at": now + 3600, "open_full": True},
                         {"bucket": "codex", "minutes": 10080, "open_reset_at": now + 5 * 86400, "open_full": False}],
            "reading": {"read_at": now, "credits": 12, "nearest_expiry": now + 3 * 86400, "expiry_known": True},
            "last_spend": {"outcome": "reset", "at": now - 3600}, "count_unproven": True,
            "limits": {"messages": 10, "credit_rules": 4, "words": 2000, "ordinals": 9, "use_now_minutes": 15}}


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class LayoutTests(unittest.TestCase):
    """The page in every language at five scalings, each capability open with every warning there is, then unread,
    then in the narrowest window - and a canary that shows the audit finds what does not fit."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        cls.exe = compile_window(work)
        bridge = Bridge(work / "home")
        jobs = []
        try:
            for locale in l10n.LOCALES:
                data = audit_data(locale, bridge)
                for part in ("words", "listing", "statements", "kept", "reports"):
                    (work / ("%s-%s.json" % (part, locale))).write_text(json.dumps(data[part], ensure_ascii=False),
                                                                         encoding="utf-8")
                (work / ("strings-%s.json" % locale)).write_text(json.dumps(strings(locale), ensure_ascii=False),
                                                                  encoding="utf-8")
                for scale in SCALES:
                    jobs.append({"kind": "audit", "name": "%s %.2f" % (locale, scale), "scale": scale,
                                 "strings": "strings-%s.json" % locale, "words": "words-%s.json" % locale,
                                 "listing": "listing-%s.json" % locale, "statements": "statements-%s.json" % locale,
                                 "kept": "kept-%s.json" % locale,
                                 "reports": "reports-%s.json" % locale})
            canary = audit_data("en", bridge)
            canary["words"]["page.limits"] = "W" * 400
            canary["words"]["name." + IDS[0]] = "N" * 400
            # A tab wider than any screen: on the narrowest screen no second row holds it.
            canary["words"]["page.nav"] = "T" * 400
            for part in ("words", "listing", "statements", "kept", "reports"):
                (work / ("%s-canary.json" % part)).write_text(json.dumps(canary[part]), encoding="utf-8")
            jobs.append({"kind": "audit", "name": "canary", "scale": 1.0, "strings": "strings-en.json",
                         "words": "words-canary.json", "listing": "listing-canary.json",
                         "statements": "statements-canary.json", "kept": "kept-canary.json",
                         "reports": "reports-canary.json"})
        finally:
            bridge.close()
        # Four processes side by side: the audits are independent, and one process took 17 minutes for them all.
        # The time allowed grows with the views each audit lays out (AUDIT_SECONDS a view): a capability, a card or a
        # list more is more to lay out, and a fixed allowance ran out when the reset actions added four (v0.6.14).
        cls.run_, cls.answer = probe(work, cls.exe, jobs, timeout=audit_timeout(len(jobs), workers=4), workers=4)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.run_.stderr or self.run_.stdout)[-3000:])

    def test_nothing_is_cut_off_in_any_language_at_any_scaling(self):
        for locale in l10n.LOCALES:
            for scale in SCALES:
                found = self.answer["%s %.2f" % (locale, scale)]
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(found["report"], "", "\n" + "\n".join(found["report"].splitlines()[:40]))
                    # Each capability open, the list unread, and the narrowest window - on a screen that holds the
                    # tabs on one row, and on the narrowest screen the window opens on at this scaling, where they take
                    # two rather than be cut off. Both held from a window wider than Windows allows (AuditNarrowestOn),
                    # so a frame measured from its held Width shows here on any machine, not only on a screen smaller
                    # than the window at 200% (v0.6.11-beta.3: eight languages cut off on a screen 1440 wide).
                    # And the action's card in every state a report can be in (report_states).
                    # And Pending, with the reset rules scheduled under its list (fullest_resets).
                    self.assertEqual(found["audited"], audited_views())

    def test_the_audit_finds_what_does_not_fit(self):
        report = self.answer["canary"]["report"]
        self.assertIn("Label'WWWW", report, "a 400-character heading went unreported, so a quiet report proves nothing")
        self.assertRegex(report, r"advanced/%s/[^\n]*Label'NNNN[^\n]* :: needs " % IDS[0],
                         "a name 400 characters wide over the open capability's cards went unreported, so a quiet report "
                         "on them proves nothing")
        self.assertRegex(report, r"at the narrowest on the narrowest screen/[^\n]*NavButton'TTTT",
                         "a tab wider than the narrowest screen went unreported, so a quiet report on the tabs there "
                         "proves nothing")


class StandardWindowTests(unittest.TestCase):
    """The standard window holds nothing of the page: built as a release builds each (build/make_gui.ps1), the
    standard executable holds none of the overlay's names or literals, which the advanced one holds - the release
    audit's own check (d), with the repository's real advanced tree."""

    @classmethod
    def setUpClass(cls):
        if not (CSC.is_file() and POWERSHELL.is_file()):
            raise unittest.SkipTest("needs the in-box compiler and PowerShell")
        cls.work = Path(tempfile.mkdtemp(prefix="advanced-page-"))
        root = cls.work / "root"
        shutil.copytree(ROOT / "gui", root / "gui")
        shutil.copytree(ROOT / "advanced" / "gui", root / "advanced" / "gui")
        for name in (".codex-plugin/plugin.json", "assets/codex-auto-resume.ico", "build/make_gui.ps1",
                     "build/normalize_pe.py"):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, root / name)
        cls.runs = [subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                    "-File", str(root / "build" / "make_gui.ps1"), "-Root", str(root), *arguments],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
                    for arguments in ((), ("-Edition", "advanced"))]
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        for run in self.runs:
            if run.returncode != 0:
                self.fail("build/make_gui.ps1 failed:\n" + (run.stderr or run.stdout)[-2000:])
        self.standard = (self.root / "build" / WINDOW).read_bytes()
        self.advanced = (self.root / "build" / "advanced" / WINDOW).read_bytes()
        self.launcher = (self.root / "build" / "codex-auto-resume-mcp.exe").read_bytes()

    def test_the_standard_window_holds_no_name_and_no_literal_of_the_page(self):
        tree = edition_audit.inventory(ROOT)
        for name in ("AdvancedPageRun", "AdvancedLayoutAudit", "ArmAdvanced", "advancedList"):
            self.assertIn(name, tree.window)
        for literal in ("advanced-words", "advanced-arm", "advanced-disarm-all", "page.confirm.changed"):
            self.assertIn(literal, tree.literals)
        executables = dict(zip(edition_audit.EXECUTABLES, (self.standard, self.launcher)))
        self.assertEqual(edition_audit.check_executables(executables, tree), [])
        found = edition_audit.check_executables(dict(executables, **{edition_audit.WINDOW: self.advanced}), tree)
        self.assertIn("(d) %s holds ArmAdvanced" % edition_audit.WINDOW, found)
        self.assertIn("(d) %s holds the literal 'advanced-arm'" % edition_audit.WINDOW, found)

    def test_the_standard_window_is_the_one_its_own_sources_make(self):
        """Its build never reads the overlay: the standard window from a tree without advanced/gui at all is the same
        file, byte for byte."""
        bare = self.work / "bare"
        shutil.copytree(self.root, bare, ignore=shutil.ignore_patterns("build"))
        shutil.rmtree(bare / "advanced")
        (bare / "build").mkdir()
        for name in ("make_gui.ps1", "normalize_pe.py"):
            shutil.copyfile(self.root / "build" / name, bare / "build" / name)
        run = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-File", str(bare / "build" / "make_gui.ps1"), "-Root", str(bare)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        self.assertEqual(run.returncode, 0, (run.stderr or run.stdout)[-2000:])
        self.assertEqual((bare / "build" / WINDOW).read_bytes(), self.standard)
        self.assertNotEqual(self.advanced, self.standard)


if __name__ == "__main__":
    unittest.main()

"""What every test module of the Dashboard's Advanced features page shares (advanced/gui/AdvancedPage.cs).

The page's tests are split by what they drive, so that no one file bounds a CI part (scripts/test_parts.py deals the
suite by file): test_advanced_page_arming (the list, Turn on, Watch, Turn off, the hourly limit, the policy, the
keys and the reopen), test_advanced_page_options (a capability's choices, the rules, the samples, the watch log,
Keep it on and Send now), test_advanced_page_resets (the reset actions and Pending's Scheduled tab),
test_advanced_page_report (the compatibility report's card), test_advanced_page_layout_1 to _5 (the audit of every
language at every scaling, each module its share dealt by cost, every audit in one of them) and test_advanced_page_standard
(the standard window holds nothing of the page).

Here: the advanced window compiled from the standard window's sources and the overlay's (compile_window), the probe
that loads it in an STA PowerShell and drives the page through the window's own hooks (AdvancedPageRun,
AdvancedLayoutAudit in advanced/gui/AdvancedPageAudit.cs) the way tests/test_gui_layout.py drives the standard pages
through LayoutAudit, this edition's real bridge in a temporary home (Bridge), the report card's job replies,
PageCase - each module's PageTests, which runs every scenario_* of its own in one window process - and LayoutCase,
each layout module's LayoutTests, which runs its audits (layout_jobs) in four window processes. The window
is never shown, and its bridge is rooted where nothing is: every reply it reads is one a test hands it, made by this
edition's real bridge (controlcli, surfaces, arming) in a temporary home with a policy, a compatibility view and
measurements of the test's own - so nothing here reads the real installation, the real Software\\Policies keys or a
real Codex.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import functools
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from advancedcase import ROOT  # noqa: E402

import guiscan  # noqa: E402
from test_gui_layout import fullest_snapshot  # noqa: E402
from codex_auto_resume import config, control, controlcli, l10n  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, policy, registry, statement, watchlog  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingWarning, Measurement, Verdict  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
OVERLAY = ROOT / "advanced" / "gui" / "window.sources"
WINDOW = "CodexAutoResumeSettings.exe"
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)
IDS = [definition.id for definition in registry.DEFINITIONS]
# The order the rows are in (the owner's, 2026-10-10): the compatibility report first, and so the one open before any
# is chosen - an action, so a scenario that turns the first route on or off chooses it.
# v0.6.19: less any capability waiting hidden in registry.WAITING, which holds its place there but has no row yet.
SHOWN = [capability for capability in registry.SHOWN_ORDER if capability in IDS]
# The capability the turn-on scenario opens: one whose statement carries a warning (M7 unmeasured there), named
# rather than counted, since the registry grew (v0.6.15-beta put queue_for_open third).
MARKER_FREE = "marker_free_continuation"
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


def deal_out(costs: list, workers: int) -> list:
    """The indexes of `costs` in `workers` shares: longest first, each to the share with the least so far (the
    lowest-numbered on a tie), so one long audit is not left behind several others in one process (v0.6.17: the
    Japanese audits took 20 minutes each on GitHub's runners and two of them shared a process). Equal costs deal
    round, the first to the first share. Deterministic."""
    count = max(1, workers)
    loads = [0.0] * count
    shares = [[] for _ in range(count)]
    for index in sorted(range(len(costs)), key=lambda each: (-costs[each], each)):
        least = min(range(count), key=lambda share: (loads[share], share))
        loads[least] += costs[index]
        shares[least].append(index)
    return [sorted(share) for share in shares]


def probe(work: Path, exe: Path, jobs: list, timeout: int, workers: int = 1) -> tuple:
    """Runs `jobs` in the window, in `workers` processes side by side, each an STA PowerShell that loads the window
    once: (the processes, what each job answered). The jobs are independent, so the answers are the same however
    they are shared out; only the time differs - so they are shared out longest first (deal_out, by each job's
    "cost", 1 where it has none: then job i goes to process i % workers, as before v0.6.17)."""
    script = work / "probe.ps1"
    script.write_text(PROBE, encoding="utf-8")
    shares = [[jobs[index] for index in share] for share in deal_out([job.get("cost", 1) for job in jobs], workers)]
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
        # A report job runs on a thread of its own ("compat-report", report/flow.py) and may still be writing
        # this home's advanced state when a test is done with the bridge: it finishes first, or the home cannot
        # be removed (WinError 32 on advanced.sqlite, seen once on a CI runner, dev run 38675702362).
        deadline = time.monotonic() + 30
        for thread in [each for each in threading.enumerate() if each.name == "compat-report"]:
            thread.join(max(0.0, deadline - time.monotonic()))
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


class PageCase(unittest.TestCase):
    """The page driven as a person would: every scenario_* of the subclass in one window process, compiled once for the
    module. A scenario's replies are made in setUpClass and its answers read by the tests, which only read them, so one
    build and one probe serve them all."""

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
                     "advanced-prompts": fullest_prompts(shot, listing["generation"]), "snapshot": shot},
            "reports": report_states()}


# How long one view of one audit may take to lay out, at most: what it takes on a quiet PC (about 7 seconds at
# v0.6.14), with room for a slower one. A hang is what this catches. 12 was too tight for GitHub's runners: dev runs
# 38077769655 and 38082727688 each timed test_advanced_page_layout_3 (ja, fr, pl, he) out in two advanced lanes,
# "the probe did not run", with nothing cut off; 30 still ends a hang long before the job's own limit.
AUDIT_SECONDS = 30


def audited_views() -> int:
    """The views each audit lays out: each capability open, then unread, the narrowest window on two screens, the
    action's card in each report state, (v0.6.19, #50; the owner's decision of 2026-10-24) Pending's one list with a row
    of each kind chosen in turn and History with the completed messages, and early_reset's reading in Why it is
    waiting."""
    return len(IDS) + 3 + len(report_states()) + 3


def audit_timeout(costs: list, workers: int) -> int:
    """The time the slowest of `workers` processes sharing audits of these costs (deal_out) is allowed: for each audit
    in its share, audited_views() views of AUDIT_SECONDS - or, for an audit measured slower than that on GitHub's
    runners (audit_cost), three times what it took there."""
    each = AUDIT_SECONDS * audited_views()
    return int(max(sum(max(each, 3 * costs[index]) for index in share) for share in deal_out(costs, workers)))


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


def fullest_prompts(shot, generation) -> dict:
    """advanced-prompts at its fullest (v0.6.19, #50), as control/prompts.view answers: a message for each place it can
    stand - waiting at a time and waiting for a running turn, a series, held, in Codex's queue, being sent, refused back,
    after this turn - and three completed ones for the Done section, one handed over."""
    now = int(ac.NOW)
    pending = shot["pending"]

    def prompt(prompt_id, thread, trigger, state, *, reason=None, every=None, occurrences=1, sent=0, mode="queue",
               due=None, finished=None, in_codex=False, being_sent=False, completed=False):
        return {"prompt_id": prompt_id, "thread_id": pending[thread % len(pending)]["thread_id"], "trigger": trigger,
                "at": None if trigger == "after_turn" else due, "every": every, "occurrences": occurrences,
                "sent_count": sent, "until": None, "depends": False, "position": prompt_id, "state": state,
                "reason": reason, "gate": None, "gate_reason": None, "created_at": now - 7200,
                "due_at": due if due is not None else now, "sent_at": None, "finished_at": finished,
                "while_running": mode, "words": None if state == "done" else "Carry on.", "in_codex": in_codex,
                "being_sent": being_sent, "completed": completed}

    return {"done": True, "refusal": None, "generation": generation, "after_turn_unproven": True,
            "prompts": [prompt(1, 0, "at_time", "waiting", mode="wait", due=now + 3600, reason="turn_running"),
                        prompt(2, 1, "recurring", "waiting", every="week", occurrences=30, sent=12, due=now + 86400),
                        prompt(3, 2, "at_time", "held", reason="dependency_failed", due=now - 60),
                        prompt(4, 0, "after_turn", "ready", in_codex=True),
                        prompt(5, 1, "at_time", "ready", being_sent=True, due=now - 30),
                        prompt(6, 2, "recurring", "waiting", every="day", occurrences=3, reason="withdraw_refused",
                               due=now + 600, mode="wait"),
                        prompt(7, 0, "after_turn", "waiting"),
                        prompt(8, 1, "at_time", "done", reason="delivered", due=now - 7000, finished=now - 6900,
                               completed=True),
                        prompt(9, 2, "recurring", "done", every="day", occurrences=30, sent=30, reason="delivered",
                               due=now - 5000, finished=now - 4900, completed=True),
                        prompt(10, 0, "after_turn", "done", reason="handed_over", finished=now - 100, completed=True)],
            "limits": {"prompts": 20, "per_conversation": 5, "words": 2000, "occurrences": 30, "days": 30}}


# The modules the layout audit is dealt over (test_advanced_page_layout_1 to _5), each running its audits in
# LAYOUT_WORKERS processes side by side; the last also audits the canary. Each audit is one language at one scaling.
LAYOUT_MODULES = 5
LAYOUT_WORKERS = 4
CANARY_MODULE = LAYOUT_MODULES

# What one audit of a language took on GitHub's runners, in seconds - read off the layout modules' times in
# tests/data/durations.json and dev run 39198984813 (2026-10-19, before v0.6.17 remembered WrapLabel's measurements):
# Japanese, Chinese and, less, Korean are measured in glyphs the window's face borrows from a linked one, and every
# other language took about ten. What the deal weighs audits by; only their order matters, and that held after
# v0.6.17 too (the remembered answers cut every language's measuring, CJK's most).
AUDIT_COST = {"ja": 1270, "zh-TW": 420, "zh-CN": 320, "ko": 50}
OTHER_AUDIT_COST = 10


def audit_cost(locale: str) -> float:
    """What one audit of `locale` took on GitHub's runners (AUDIT_COST), in seconds."""
    return AUDIT_COST.get(str(locale), OTHER_AUDIT_COST)


@functools.lru_cache(maxsize=None)
def layout_deal() -> tuple:
    """Every language at every scaling, dealt over the LAYOUT_MODULES modules by what each audit costs (v0.6.17;
    until then the languages were dealt round, and the module with Japanese took 43 minutes while another took one).

    A module takes as long as the slowest of its LAYOUT_WORKERS processes, and that is at least its longest audit; so
    module by module, the longest audit left sets the module's time and the module is filled - longest first, each to
    its least loaded process - with every audit that fits in that time, keeping one for each module still to come.
    The last module takes what is left, beside the canary. Each (language, scaling) is in exactly one module.
    Deterministic: a tuple per module of (locale, scale), in l10n.LOCALES and SCALES order."""
    locales = [str(locale) for locale in l10n.LOCALES]
    left = sorted(((locale, scale) for locale in locales for scale in SCALES),
                  key=lambda job: (-audit_cost(job[0]), locales.index(job[0]), SCALES.index(job[1])))
    modules = []
    for module in range(1, LAYOUT_MODULES + 1):
        loads = [0.0] * LAYOUT_WORKERS
        if module == CANARY_MODULE:
            loads[-1] += OTHER_AUDIT_COST
        last = module == LAYOUT_MODULES
        later = LAYOUT_MODULES - module
        wall = max([audit_cost(left[0][0])] + loads) if left else max(loads)
        taken = []
        for job in list(left):
            if len(left) <= later:
                break
            least = min(range(LAYOUT_WORKERS), key=lambda share: (loads[share], share))
            if last or loads[least] + audit_cost(job[0]) <= wall:
                loads[least] += audit_cost(job[0])
                taken.append(job)
                left.remove(job)
        modules.append(tuple(sorted(taken, key=lambda job: (locales.index(job[0]), SCALES.index(job[1])))))
    return tuple(modules)


def layout_jobs(module: int) -> tuple:
    """The (locale, scale) audits test_advanced_page_layout_<module> runs (1-based)."""
    return layout_deal()[module - 1]


class LayoutCase(unittest.TestCase):
    """The page in the subclass's JOBS - (locale, scale) audits - each capability open with every warning there is,
    then unread, then in the narrowest window - and, where CANARY, a canary that shows the audit finds what does not
    fit. The audits are dealt over LAYOUT_MODULES modules by what each costs (layout_deal), so that no one file bounds a
    CI part; the modules together audit every language at every scaling. Not collected itself: a module imports it as
    pagecase.LayoutCase."""

    JOBS: tuple = ()
    CANARY = False

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        cls.exe = compile_window(work)
        bridge = Bridge(work / "home")
        jobs = []
        try:
            locales = []
            for locale, _ in cls.JOBS:
                if locale not in locales:
                    locales.append(locale)
            for locale in locales:
                data = audit_data(locale, bridge)
                for part in ("words", "listing", "statements", "kept", "reports"):
                    (work / ("%s-%s.json" % (part, locale))).write_text(json.dumps(data[part], ensure_ascii=False),
                                                                         encoding="utf-8")
                (work / ("strings-%s.json" % locale)).write_text(json.dumps(strings(locale), ensure_ascii=False),
                                                                  encoding="utf-8")
            for locale, scale in cls.JOBS:
                jobs.append({"kind": "audit", "name": "%s %.2f" % (locale, scale), "scale": scale,
                             "cost": audit_cost(locale),
                             "strings": "strings-%s.json" % locale, "words": "words-%s.json" % locale,
                             "listing": "listing-%s.json" % locale, "statements": "statements-%s.json" % locale,
                             "kept": "kept-%s.json" % locale,
                             "reports": "reports-%s.json" % locale})
            if cls.CANARY:
                if "en" not in locales:
                    (work / "strings-en.json").write_text(json.dumps(strings("en"), ensure_ascii=False),
                                                          encoding="utf-8")
                canary = audit_data("en", bridge)
                canary["words"]["page.limits"] = "W" * 400
                canary["words"]["name." + IDS[0]] = "N" * 400
                # A tab wider than any screen: on the narrowest screen no second row holds it.
                canary["words"]["page.nav"] = "T" * 400
                for part in ("words", "listing", "statements", "kept", "reports"):
                    (work / ("%s-canary.json" % part)).write_text(json.dumps(canary[part]), encoding="utf-8")
                jobs.append({"kind": "audit", "name": "canary", "scale": 1.0, "cost": OTHER_AUDIT_COST,
                             "strings": "strings-en.json",
                             "words": "words-canary.json", "listing": "listing-canary.json",
                             "statements": "statements-canary.json", "kept": "kept-canary.json",
                             "reports": "reports-canary.json"})
        finally:
            bridge.close()
        # LAYOUT_WORKERS processes side by side, the longest audits first (deal_out): the audits are independent, and
        # one process took 17 minutes for them all. The time allowed grows with the views each audit lays out
        # (AUDIT_SECONDS a view) - a fixed allowance ran out when the reset actions added four (v0.6.14) - and with
        # what an audit took on GitHub's runners where that was more (audit_timeout).
        costs = [job["cost"] for job in jobs]
        cls.run_, cls.answer = probe(work, cls.exe, jobs, timeout=audit_timeout(costs, workers=LAYOUT_WORKERS),
                                     workers=LAYOUT_WORKERS)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.run_.stderr or self.run_.stdout)[-3000:])

    def test_nothing_is_cut_off_in_any_language_at_any_scaling(self):
        self.assertTrue(self.JOBS, "this module audits nothing")
        for locale, scale in self.JOBS:
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

r"""The Codex compatibility card on the Dashboard's Diagnostics page (v0.6.5).

The window shows the Codex Compatibility Registry to people: the overall state and each part's state in
the registry's four words - verified, compatible, incompatible, unknown - each with what it means; when it
was checked; which data was in force, bundled or refreshed, by its sequence number; and a refresh that
says what it did.

Two rules carry the safety of it, and both are held here:

* **The refresh is the only network request, and only its button makes one.** No timer, no page switch,
  no read. It goes over the one-shot bridge from a worker thread, never over the long-lived pipe the
  window paints from - the refresh can take 150 s, and on that pipe every read behind it would wait, and
  past the pipe's 30 s reply limit the long-lived process would be ended under it.
* **Every answer is said as itself**: refreshed, refused (and why), unavailable, incomplete, failed, and
  busy while an installation or a repair replaces the files it runs. An update check's own refresh is
  read from its `compatibility:` line and said the same way.

The card itself is exercised on the real compiled window, built and never shown, through reflection,
with views the real bridge produced for the registry's hermetic fixture (its own fake Codex, its own
home: nothing of this machine's).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume import compat, control, controlcli, l10n              # noqa: E402

DASHBOARD = ROOT / "gui" / "Dashboard.cs"
SETTINGS = ROOT / "gui" / "SettingsApp.cs"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
ENGLISH = l10n.catalog("en")
REAL_RUN = subprocess.run


def method(source: str, signature: str) -> str:
    start = source.index(signature)
    return source[start:source.index("\n        }\n", start)]


class RefreshRouteTests(unittest.TestCase):
    """Where the refresh can come from, and what it goes over."""

    def setUp(self):
        self.dashboard = DASHBOARD.read_text(encoding="utf-8")
        self.window = SETTINGS.read_text(encoding="utf-8")

    def test_the_refresh_goes_over_the_one_shot_bridge_and_nothing_else_asks_for_it(self):
        both = self.dashboard + self.window
        self.assertEqual(both.count('"compat-refresh"'), 1, "one caller of the refresh")
        run = method(self.dashboard, "private static void RunCompatibilityRefresh(")
        self.assertIn('bridge.CallOnce("compat-refresh", null)', run)
        self.assertNotIn('bridge.Call("compat-refresh"', both, "never on the long-lived pipe the window paints from")

    def test_the_one_shot_call_passes_the_long_lived_process_and_its_lock_by(self):
        once = method(self.dashboard, "internal Dictionary<string, object> CallOnce(")
        self.assertIn("return once.Call(command, argument);", once)
        self.assertNotIn("gate", once, "a two-minute refresh must not hold the lock every read waits on")
        self.assertIn("if (closed) throw", once)

    def test_the_refresh_runs_on_a_worker_and_answers_on_the_window_thread(self):
        refresh = method(self.dashboard, "private void RefreshCompatibility()")
        worker = refresh.index("QueueUserWorkItem")
        self.assertLess(worker, refresh.index("RunCompatibilityRefresh(bridge"))
        self.assertIn("BeginInvoke(finish)", refresh)
        self.assertIn("SetBusy(true);", refresh)
        self.assertIn("SetBusy(false);", refresh)
        self.assertIn("if (compatButton != null) compatButton.Enabled = busy == 0;",
                      method(self.dashboard, "private void SetBusy("), "it waits its turn as every action does")

    def test_only_its_button_asks_for_it(self):
        """No timer, no first visit, no read: a refresh is a request to GitHub."""
        self.assertEqual(self.dashboard.count("RefreshCompatibility()"), 2,
                         "its definition and its button, and nothing else")
        self.assertIn("delegate { RefreshCompatibility(); }", self.dashboard)
        clock = method(self.dashboard, "private void StartClock()")
        self.assertNotIn("RefreshCompatibility", clock)
        self.assertNotIn("RefreshCompatibility", method(self.dashboard, "private void ShowPage("))

    def test_the_card_reads_the_watchers_report_and_never_runs_the_live_check(self):
        load = method(self.dashboard, "private void LoadCompatibility()")
        self.assertIn('bridge.Call("compatibility", null)', load)
        self.assertIn("ApplyCompatibility(view, false)", load, "a report, never a live check")
        self.assertNotIn("LiveArgument", load)
        self.assertNotIn("CallOnce", load)
        self.assertIn("QueueUserWorkItem", load)
        self.assertNotIn('"live"', self.dashboard.replace('Get(view, "live")', ""),
                         "the live views the window shows are the ones a refresh brought")
        clock = method(self.dashboard, "private void StartClock()")
        self.assertIn('if (currentPage == "diagnostics") LoadCompatibility();', clock)
        self.assertIn('if (name == "diagnostics") LoadCompatibility();', method(self.dashboard, "private void ShowPage("))

    def test_the_one_live_check_the_window_asks_for_follows_an_update_check_that_refreshed(self):
        """The refresh button's answer carries a live check, made by the bridge. An update check's refresh has none, so
        the window asks for one - only when the check's line says `refreshed`, on the one-shot bridge, from the update
        check's own worker thread. A live check runs Codex's `--version` and `queue --help`; nothing leaves the machine."""
        self.assertIn('private const string LiveArgument = "{\\"live\\":true}";', self.dashboard)
        self.assertEqual(self.dashboard.count("LiveArgument"), 2, "its definition and its one use")
        after = method(self.dashboard, "private static Dictionary<string, object> CheckAfterRefresh(")
        self.assertIn('bridge.CallOnce("compatibility", LiveArgument)', after)
        self.assertLess(after.index('StartsWith("refreshed ", StringComparison.Ordinal)'), after.index("CallOnce"),
                        "only after new data came in")
        self.assertEqual((self.dashboard + self.window).count("CheckAfterRefresh("), 3, "defined once, called by the two checks")
        for caller in ("private void CheckForUpdates()", "private void OfferUpdate("):
            with self.subTest(caller):
                body = method(self.dashboard, caller)
                worker = body.index("QueueUserWorkItem")
                check = body.index("CheckAfterRefresh(bridge, compatibility);")
                self.assertLess(worker, check, "on the worker thread")
                self.assertLess(check, body.index("MethodInvoker finish"), "never on the window's thread")

    def test_a_live_check_is_relied_on_as_long_as_a_report_is(self):
        self.assertEqual(float(re.search(r"private const double CompatMaxAge = (\d+);", self.dashboard).group(1)),
                         compat.REPORT_MAX_AGE, "compat.REPORT_MAX_AGE")

    def test_busy_looks_at_the_installers_lock_and_never_holds_it(self):
        run = method(self.dashboard, "private static void RunCompatibilityRefresh(")
        self.assertIn('new System.Threading.Mutex(false, "Local\\\\CodexAutoResume.Install")', run)
        self.assertIn('outcome = "busy"', run)
        self.assertLess(run.index("gate.ReleaseMutex();"), run.index('bridge.CallOnce("compat-refresh"'),
                        "let go before the refresh, so an installation that starts meanwhile is not turned away")

    def test_an_update_checks_compatibility_line_reaches_the_card(self):
        for caller in ("private void CheckForUpdates()", "private void OfferUpdate("):
            with self.subTest(caller):
                body = method(self.dashboard, caller)
                self.assertIn("out compatibility);", body)
                self.assertIn("ReportCompatibilityLine(compatibility, live);", body)
        run = self.dashboard[self.dashboard.index("private static void RunBootstrap"):]
        run = run[:run.index("\n        /// The one-line fact")]
        self.assertIn("compatibility = CompatibilityLine(printed);", run)
        self.assertRegex(self.dashboard, r"CheckMilliseconds\s*=\s*(\d+)\s*;")
        self.assertGreaterEqual(int(re.search(r"CheckMilliseconds\s*=\s*(\d+)\s*;", self.dashboard).group(1)), 100000,
                                "the update check's budget holds its refresh (tests/test_compat_bootstrap.py)")


class WordsTests(unittest.TestCase):
    """Every word the card can show is in every language, from the registry's closed vocabularies."""

    def setUp(self):
        self.dashboard = DASHBOARD.read_text(encoding="utf-8")

    def test_every_key_the_card_names_is_english(self):
        section = self.dashboard[self.dashboard.index("// ---------------------------------------------------------- compatibility"):
                                 self.dashboard.index("// ------------------------------------------------------------------ clock")]
        named = {key for key in re.findall(r'S\("((?:compat|diag\.compat)[a-z0-9_.]*)"', section) if not key.endswith(".")}
        self.assertGreater(len(named), 20)
        self.assertEqual(sorted(key for key in named if key not in ENGLISH), [])
        for prefix in re.findall(r'S\("((?:compat)[a-z_.]*\.)"\s*\+', section):
            self.assertIn(prefix, ("compat.state.", "compat.capability.", "compat.meaning.", "compat.status.",
                                   "compat.cache.", "compat.source."), prefix)

    def test_every_value_those_keys_are_built_from_has_words_in_every_language(self):
        keys = ["compat.state." + state for state in compat.STATES]
        keys += ["compat.meaning." + state for state in compat.STATES]
        keys += ["compat.capability." + name for name in compat.CAPABILITIES]
        keys += ["compat.status." + status for status in compat.VIEW_STATUSES if status != "ok"]
        keys += ["compat.cache." + state for state in ("expired", "from_the_future", "rejected", "superseded",
                                                       "from_newer_product")]
        keys += ["compat.source." + source for source in compat.DATA_SOURCES]
        for locale in l10n.LOCALES:
            table = l10n._read(locale)
            for key in keys:
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(table.get(key, "").strip())
        # The cache states the card names are every one that is neither absent nor in force as it is.
        self.assertEqual(set(compat.CACHE_STATES) - {"absent", "ok"},
                         {"expired", "from_the_future", "rejected", "superseded", "from_newer_product"})

    def test_every_refusal_the_validator_can_give_has_plain_words(self):
        """Eighteen codes, six plain reasons: each code is said in words, and the code beside them."""
        refused = method(self.dashboard, "private string RefusedBecause(")
        named = set(re.findall(r'code == "([a-z_]+)"', refused))
        self.assertLessEqual(named, compat.IMPORT_REASONS)
        self.assertIn('return S("compat.refused.invalid"', refused, "every other code is data that is not valid")
        for key in ("compat.refused.invalid", "compat.refused.future", "compat.refused.newer",
                    "compat.refused.rollback", "compat.refused.unreadable", "compat.refused.not_saved"):
            self.assertIn(key, ENGLISH)
        self.assertIn("{code}", ENGLISH["diag.compat_refused"])
        self.assertIn("{reason}", ENGLISH["diag.compat_refused"])

    def test_unavailable_blames_nobody_it_cannot_name(self):
        """`unavailable` is the answer for a network that did not answer, but also for an update check whose time ran
        out after github.com had answered, an installation with no validator, and a refresh that took too long
        (scripts/bootstrap.ps1, compatio.run_refresh). Said in words that are true of all of them."""
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                said = l10n._read(locale)["diag.compat_unavailable"]
                self.assertNotIn("GitHub", said)
        self.assertEqual(ENGLISH["diag.compat_unavailable"], "The compatibility data could not be fetched, so nothing was changed.")

    def test_the_card_is_laid_out_as_the_windows_other_cards_are(self):
        build = method(self.dashboard, "private TableLayoutPanel BuildCompatibility()")
        self.assertIn('MakeCard(S("compat.title", "Codex compatibility"))', build)
        self.assertIn("Facts(card)", build, "facts as the Health card has them")
        self.assertIn("compatLeft = CompatList();", build)
        self.assertIn("compatButton.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;", build,
                      "its button at the card's bottom left, as every card's button now is")
        self.assertIn("row.Margin = Pad(0, LeadGap, 0, 0);", build, "clear of what the card holds, as the Overview's are")
        self.assertIn("compatNote = Note();", build, "what it did, said to a screen reader too")
        self.assertIn("new GateList()", method(self.dashboard, "private GateList CompatList()"),
                      "rows as Why it is waiting draws its checks, which are the panel's settings rows")
        diagnostics = method(self.dashboard, "private Control BuildDiagnostics()")
        self.assertIn("grid.SetColumnSpan(compat, 2);", diagnostics)
        self.assertIn("health.Margin = GridGap(0, false);", diagnostics)
        self.assertIn("tools.Margin = GridGap(1, false);", diagnostics)


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$utf8 = New-Object Text.UTF8Encoding $false
$work = [string]$env:CAR_WORK
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
$cases = Read-Json 'cases.json'
$out = @{ lines = @{}; outcomes = @{}; states = @{} }

$line = $form.GetMethod('CompatibilityLine', $static)
foreach ($pair in $cases['lines'].GetEnumerator()) { $out.lines[$pair.Key] = $line.Invoke($null, [object[]]@([string]$pair.Value)) }
$outcome = $form.GetMethod('CompatibilityOutcome', $static)
foreach ($pair in $cases['outcomes'].GetEnumerator()) { $out.outcomes[$pair.Key] = $outcome.Invoke($null, [object[]]@($pair.Value)) }
$state = $form.GetMethod('CompatState', $static)
# Pairs, not a table: PowerShell's keys ignore case, and VERIFIED and verified are two cases here.
$out.states = @()
foreach ($word in @('VERIFIED', 'verified', 'COMPATIBLE', 'structurally_compatible', 'INCOMPATIBLE', 'incompatible', 'UNKNOWN', 'unknown', 'something', '')) {
    $out.states += ,@([string]$word, [string]$state.Invoke($null, [object[]]@([string]$word)))
}

$ownState = [Windows.Forms.Control].GetMethod('GetState', $instance)
function Test-Own($control) { return [bool]$ownState.Invoke($control, [object[]]@(2)) }
function Get-Field($target, [string]$name) { return $form.GetField($name, $instance).GetValue($target) }
function Set-Field($target, [string]$name, $value) { $form.GetField($name, $instance).SetValue($target, $value) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $m = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $m.Invoke($target, $arguments)
}
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
function New-Window($strings) {
    $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
    $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
    $window = $three.Invoke([object[]]@($bridge, $strings, [Drawing.SystemFonts]::MessageBoxFont))
    Set-Field $window 'auditing' $true
    $window.TopLevel = $false
    return $window
}
function Get-Rows($list) {
    $rows = $list.GetType().GetField('rows', $instance).GetValue($list)
    return @($rows | ForEach-Object { ($_ -join '|') })
}
function Look($window) {
    $notice = Get-Field $window 'compatNotice'
    $legend = Get-Field $window 'compatLegend'
    return @{ overall = [string](Get-Field $window 'compatOverall').Text; engine = [string](Get-Field $window 'compatEngine').Text
              checked = [string](Get-Field $window 'compatChecked').Text; data = [string](Get-Field $window 'compatData').Text
              notice = [string]$notice.Text; noticeShown = (Test-Own $notice); legend = [string]$legend.Text; legendShown = (Test-Own $legend)
              left = @(Get-Rows (Get-Field $window 'compatLeft')); right = @(Get-Rows (Get-Field $window 'compatRight'))
              listsShown = (Test-Own (Get-Field $window 'compatLists'))
              note = [string](Get-Field $window 'compatNote').Text; button = [string](Get-Field $window 'compatButton').Text
              enabled = [bool](Get-Field $window 'compatButton').Enabled }
}
$english = Read-Json 'strings-en.json'
$out.cards = @{}

# Before anything was read: nothing said, nothing guessed.
$window = New-Window $english
Invoke-Window $window 'ShowPage' @('diagnostics') | Out-Null
$out.cards.unread = Look $window
# A read that failed.
Set-Field $window 'compatUnreadable' $true
Invoke-Window $window 'ShowCompatibility' @() | Out-Null
$out.cards.unreadable = Look $window
# Each view, as a read gives it.
foreach ($name in @('ok', 'rich', 'absent', 'engine_changed')) {
    Invoke-Window $window 'ApplyCompatibility' @((Read-Json ($name + '.json')), $false) | Out-Null
    $out.cards[$name] = Look $window
}
# A card updated while another page is on screen: the lines it no longer has are gone when it is shown again.
$hidden = New-Window $english
Invoke-Window $hidden 'ShowPage' @('diagnostics') | Out-Null
Invoke-Window $hidden 'ApplyCompatibility' @((Read-Json 'rich.json'), $false) | Out-Null
Invoke-Window $hidden 'ShowPage' @('overview') | Out-Null
Invoke-Window $hidden 'ApplyCompatibility' @((Read-Json 'ok.json'), $false) | Out-Null
Invoke-Window $hidden 'ShowPage' @('diagnostics') | Out-Null
$out.cards.whileHidden = Look $hidden
$hidden.Dispose()
# A view applied before the page was built is shown when it is.
$early = New-Window $english
Invoke-Window $early 'ApplyCompatibility' @((Read-Json 'rich.json'), $false) | Out-Null
Invoke-Window $early 'ShowPage' @('diagnostics') | Out-Null
$out.cards.early = Look $early
$early.Dispose()

# The live check a refresh answered with stands until a report as new arrives.
Invoke-Window $window 'ApplyCompatibility' @((Read-Json 'live.json'), $true) | Out-Null
$out.cards.live = Look $window
Invoke-Window $window 'ApplyCompatibility' @((Read-Json 'older.json'), $false) | Out-Null
$out.cards.liveKept = Look $window
Invoke-Window $window 'ApplyCompatibility' @((Read-Json 'newer.json'), $false) | Out-Null
$out.cards.liveReplaced = Look $window

# What each answer says, and the button while something is in flight.
$out.said = @{}
foreach ($pair in @(@('refreshed', '12', $null), @('refused', '?', 'from_the_future'), @('refused', '?', 'duplicate_key'),
                    @('refused', '?', 'rollback'), @('refused', '?', 'not_a_json_file'), @('refused', '?', 'write_failed'),
                    @('refused', '?', 'from_newer_product'), @('unavailable', '?', $null), @('incomplete', '?', $null),
                    @('failed', '?', $null), @('busy', '?', $null), @('something', '?', $null))) {
    $key = $pair[0] + ' ' + $pair[2]
    $out.said[$key] = [string](Invoke-Window $window 'CompatibilitySaid' @([string]$pair[0], [string]$pair[1], $pair[2]))
}
Invoke-Window $window 'SetBusy' @($true) | Out-Null
$out.busyEnabled = [bool](Get-Field $window 'compatButton').Enabled
Invoke-Window $window 'SetBusy' @($false) | Out-Null
$out.idleEnabled = [bool](Get-Field $window 'compatButton').Enabled
# An update check's line, said on the card.
try {
    Invoke-Window $window 'ReportCompatibilityLine' @('refused from_the_future', $null) | Out-Null
    $out.lineNote = [string](Get-Field $window 'compatNote').Text
} catch { $out.lineNote = 'failed: ' + $_.Exception.ToString() }
$window.Dispose()

# How long a refresh's live check stands, one window per story: each step a view, as a read or a refresh gives it,
# or an update check's line with the live check made after it. Every story on its own, so one that cannot run says
# why and the others still do.
$out.stories = @{}
foreach ($story in $cases['stories'].GetEnumerator()) {
    try {
        $w = New-Window $english
        Invoke-Window $w 'ShowPage' @('diagnostics') | Out-Null
        $seen = @()
        foreach ($step in $story.Value) {
            if ($step[0] -eq 'line') {
                $live = if ($step[2]) { Read-Json ($step[2] + '.json') } else { $null }
                Invoke-Window $w 'ReportCompatibilityLine' @([string]$step[1], $live) | Out-Null
            } else {
                Invoke-Window $w 'ApplyCompatibility' @((Read-Json ($step[1] + '.json')), ($step[0] -eq 'live')) | Out-Null
            }
            $seen += ,(Look $w)
        }
        $out.stories[$story.Key] = $seen
        $w.Dispose()
    } catch { $out.stories[$story.Key] = 'failed: ' + $_.Exception.ToString() }
}
# The rule itself, at the edge of its age.
$out.stands = @{}
try {
    $stands = $form.GetMethod('LiveStands', $static)
    $reading = $form.GetMethod('Reading', $static)
    foreach ($pair in $cases['stands'].GetEnumerator()) {
        $c = $pair.Value
        $over = [string]$reading.Invoke($null, [object[]]@($c['over']))
        $out.stands[$pair.Key] = [bool]$stands.Invoke($null, [object[]]@($c['live'], $over, $c['report'], [double]$c['now']))
    }
} catch { $out.stands = 'failed: ' + $_.Exception.ToString() }

# In Korean.
$korean = New-Window (Read-Json 'strings-ko.json')
Invoke-Window $korean 'ShowPage' @('diagnostics') | Out-Null
Invoke-Window $korean 'ApplyCompatibility' @((Read-Json 'rich.json'), $false) | Out-Null
$out.cards.korean = Look $korean
$korean.Dispose()

[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""


def rich_view(ok_view: dict, now: float) -> dict:
    """The fullest card: a part incompatible and one unknown, a VERIFIED one, the watcher still acting on what
    it found when it started, and refreshed data that has expired - every line the card can add."""
    view = json.loads(json.dumps(ok_view))
    view["overall"] = "incompatible"
    view["acting"] = "structurally_compatible"
    view["checked_at"] = now - 120
    view["engine"] = {"found": True, "version": "codex-cli 0.155.0"}
    view["data"] = {"bundled": "ok", "bundled_sequence": 1, "cache": "expired", "cache_sequence": 12,
                    "cache_origin": "main", "fetched_at": now - 86400 * 100, "source": "cache", "expired": True}
    view["capabilities"]["queue_withdraw"].update(state="INCOMPATIBLE", reason="registry_incompatible")
    view["capabilities"]["loaded_state_detection"].update(state="UNKNOWN", reason="local_check_unavailable")
    view["capabilities"]["engine_present"].update(state="VERIFIED", reason="registry_verified")
    return view


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                        *[str(ROOT / "gui" / name) for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
                       check=True, capture_output=True, timeout=300)
        views = cls.views()
        now = time.time()
        views["rich"] = rich_view(views["ok"], now)
        views["engine_changed"] = compat.unusable_view("engine_changed", data=views["ok"]["data"],
                                                       checked_at=now - 30, engine=views["ok"]["engine"])
        views["live"] = dict(json.loads(json.dumps(views["ok"])), live=True, checked_at=now,
                             data=dict(views["ok"]["data"], source="cache", cache="ok", cache_sequence=7))
        views["older"] = dict(json.loads(json.dumps(views["ok"])), checked_at=now - 60)
        views["newer"] = dict(json.loads(json.dumps(views["ok"])), checked_at=now + 1)
        # For the live check's lifetime: a watcher that stopped a while ago and its report, still usable; the same
        # report once Codex changed under it, or once it is too old; a live check from past the watcher's own interval.
        ok, data, engine = views["ok"], views["ok"]["data"], views["ok"]["engine"]
        views["report800"] = dict(json.loads(json.dumps(ok)), checked_at=now - 800)
        views["changed800"] = compat.unusable_view("engine_changed", data=data, checked_at=now - 800, engine=engine)
        views["stale800"] = compat.unusable_view("stale", data=data, checked_at=now - 800, engine=engine)
        views["stale4700"] = compat.unusable_view("stale", data=data, checked_at=now - 4700, engine=engine)
        views["live700"] = dict(views["live"], checked_at=now - 700)
        views["live4600"] = dict(views["live"], checked_at=now - 4600)
        cls.views_ = views
        for name, view in views.items():
            (work / (name + ".json")).write_text(json.dumps(view), encoding="utf-8")
        for locale in ("en", "ko"):
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(
                {"ok": True, "language": locale, "strings": l10n.catalog(locale), "preference": locale,
                 "system_language": locale, "endonyms": dict(l10n.ENDONYMS)}, ensure_ascii=False), encoding="utf-8")
        cases = {"lines": {
                     "refreshed": "  Asking raw.githubusercontent.com\ncompatibility: refreshed 12\nupdate: current 0.6.5",
                     "refused": "compatibility: refused from_the_future",
                     "unavailable": "compatibility: unavailable",
                     "last_wins": "compatibility: unavailable\ncompatibility: refreshed 3",
                     "none": "update: current 0.6.5",
                     "no_sequence": "compatibility: refreshed",
                     "not_a_sequence": "compatibility: refreshed 1a",
                     "not_a_code": "compatibility: refused Too-Large",
                     "a_word_it_does_not_know": "compatibility: fine 3",
                     "too_many": "compatibility: refreshed 3 4",
                     "indented": "   compatibility: refreshed 5   "},
                 "outcomes": {
                     "refreshed": {"ok": True, "result": {"answer": "refreshed", "sequence": 3}},
                     "refused": {"ok": True, "result": {"answer": "refused", "reason": "rollback"}},
                     "unavailable": {"ok": True, "result": {"answer": "unavailable"}},
                     "incomplete": {"ok": True, "result": {"answer": "incomplete"}},
                     "failed": {"ok": True, "result": {"answer": "failed"}},
                     "unknown_word": {"ok": True, "result": {"answer": "done"}},
                     "no_result": {"ok": True},
                     "refused_request": {"ok": False, "error": "x", "error_code": "request_failed"},
                     "nothing": None},
                 # Each story: the steps a window sees - a report read, a refresh's live check, or an update check's
                 # line with the live check made after it - and the card after each.
                 "stories": {
                     "watcher_stopped": [["report", "report800"], ["live", "live700"], ["report", "report800"]],
                     "caught_up": [["report", "report800"], ["live", "live"], ["report", "newer"]],
                     "changed_after": [["report", "report800"], ["live", "live"], ["report", "changed800"]],
                     "changed_before": [["report", "changed800"], ["live", "live"], ["report", "changed800"]],
                     "never_ran": [["report", "absent"], ["live", "live"], ["report", "absent"]],
                     "went_stale": [["report", "report800"], ["live", "live"], ["report", "stale800"]],
                     "aged_out": [["report", "stale4700"], ["live", "live4600"], ["report", "stale4700"]],
                     "update_refreshed": [["report", "report800"], ["line", "refreshed 7", "live"], ["report", "report800"]],
                     "update_refused": [["report", "report800"], ["line", "refused rollback", None]]},
                 "stands": {
                     "young": {"live": {"checked_at": 1000.0}, "over": {"status": "ok", "checked_at": 900.0},
                               "report": {"status": "ok", "checked_at": 900.0}, "now": 1000.0 + compat.REPORT_MAX_AGE - 1},
                     "as_old_as_a_report_may_be": {"live": {"checked_at": 1000.0}, "over": {"status": "ok", "checked_at": 900.0},
                                                   "report": {"status": "ok", "checked_at": 900.0},
                                                   "now": 1000.0 + compat.REPORT_MAX_AGE},
                     "report_as_new": {"live": {"checked_at": 1000.0}, "over": {"status": "ok", "checked_at": 900.0},
                                       "report": {"status": "ok", "checked_at": 1000.0}, "now": 1010.0},
                     "unread_then_unusable": {"live": {"checked_at": 1000.0}, "over": None,
                                              "report": {"status": "absent", "checked_at": None}, "now": 1010.0},
                     "invalid_since": {"live": {"checked_at": 1000.0}, "over": {"status": "ok", "checked_at": 900.0},
                                       "report": {"status": "invalid", "checked_at": None}, "now": 1010.0},
                     "invalid_before": {"live": {"checked_at": 1000.0}, "over": {"status": "invalid", "checked_at": None},
                                        "report": {"status": "invalid", "checked_at": None}, "now": 1010.0}}}
        (work / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = REAL_RUN([str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(probe)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=600, env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work)))
        answer = work / "result.json"
        cls.answer = json.loads(answer.read_text(encoding="utf-8-sig")) if answer.is_file() else {}

    @classmethod
    def views(cls) -> dict:
        """The views the bridge's `compatibility` command gives for the registry's hermetic fixture: before the
        watcher wrote a report, and after."""
        from test_compat_characterization import FakeCodex, Fixture
        case = unittest.TestCase()
        try:
            fixture = Fixture(case, codex=FakeCodex(version="codex-cli 0.155.0"))
            ctl = control.Control(fixture.paths)
            with patch.object(control.Control, "watcher_running", return_value=True), \
                 patch.object(control.Control, "startup_enabled", return_value=False):
                absent = controlcli.dispatch(ctl, "compatibility", {})["compatibility"]
                fixture.backend()
                ok = controlcli.dispatch(ctl, "compatibility", {})["compatibility"]
        finally:
            case.doCleanups()
        return {"absent": absent, "ok": ok}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def card(self, name):
        return self.answer["cards"][name]

    def test_the_bridge_views_are_what_the_card_is_given(self):
        self.assertEqual((self.views_["absent"]["status"], self.views_["ok"]["status"]), ("absent", "ok"))
        self.assertEqual(self.views_["ok"]["overall"], "structurally_compatible")

    def test_a_card_read_from_the_watchers_report(self):
        card = self.card("ok")
        self.assertEqual(card["overall"], ENGLISH["compat.state.COMPATIBLE"])
        self.assertEqual(card["engine"], "codex-cli 0.155.0")
        self.assertEqual(card["data"], "%s, #%d" % (ENGLISH["compat.source.bundled"], self.views_["ok"]["data"]["bundled_sequence"]))
        rows = card["left"] + card["right"]
        offered = [name for name, (_, tier) in compat.CAPABILITIES.items() if tier != "unsupported"]
        self.assertEqual([row.split("|")[0] for row in rows], [ENGLISH["compat.capability." + name] for name in offered],
                         "the registry's order, and the four it does not offer yet left out, as the command line leaves them")
        self.assertEqual(len(card["left"]), (len(rows) + 1) // 2, "two lists side by side")
        tone = {"VERIFIED": "PASS", "COMPATIBLE": "PASS", "INCOMPATIBLE": "BLOCK", "UNKNOWN": "UNKNOWN"}
        states = [self.views_["ok"]["capabilities"][name]["state"] for name in offered]
        self.assertEqual([row.split("|")[1:] for row in rows],
                         [[ENGLISH["compat.state." + state], tone[state]] for state in states], "each part's own state")
        # The fixture's Codex has no writer-lock folder, so telling whether a conversation is open is unknown there.
        self.assertIn("UNKNOWN", states)
        self.assertEqual(card["legend"].splitlines(), [ENGLISH["compat.meaning." + state]
                                                       for state in compat.STATES if state in states])
        self.assertFalse(card["noticeShown"], "nothing to add, so no line and no room taken")
        self.assertEqual(card["button"], ENGLISH["diag.compat_refresh"])

    def test_the_fullest_card_says_every_state_and_every_caveat(self):
        card = self.card("rich")
        self.assertEqual(card["overall"], ENGLISH["compat.state.INCOMPATIBLE"])
        self.assertEqual(card["data"], "%s, #12" % ENGLISH["compat.source.cache"])
        rows = {row.split("|")[0]: row.split("|")[1:] for row in card["left"] + card["right"]}
        self.assertEqual(rows[ENGLISH["compat.capability.queue_withdraw"]], [ENGLISH["compat.state.INCOMPATIBLE"], "BLOCK"])
        self.assertEqual(rows[ENGLISH["compat.capability.loaded_state_detection"]], [ENGLISH["compat.state.UNKNOWN"], "UNKNOWN"])
        self.assertEqual(rows[ENGLISH["compat.capability.engine_present"]], [ENGLISH["compat.state.VERIFIED"], "PASS"])
        self.assertEqual(card["legend"].splitlines(), [ENGLISH["compat.meaning." + state] for state in compat.STATES],
                         "each word the card shows, explained, in the registry's order")
        self.assertEqual(card["notice"].splitlines(), [ENGLISH["diag.compat_acting_differs"], ENGLISH["compat.cache.expired"]])
        self.assertTrue(card["noticeShown"])
        self.assertEqual(self.card("early"), card, "a view read before the page was built is shown once it is")

    def test_a_card_updated_while_another_page_shows_keeps_no_line_it_no_longer_has(self):
        """Visible answers false for every label on a page that is not on screen, so the card asks for its own."""
        card = self.card("whileHidden")
        self.assertFalse(card["noticeShown"])
        self.assertEqual(card["notice"], "")
        self.assertEqual(card, self.card("ok"))

    def test_a_report_that_cannot_be_used_says_why_and_lists_nothing(self):
        for name in ("absent", "engine_changed"):
            with self.subTest(name):
                card = self.card(name)
                self.assertEqual(card["overall"], ENGLISH["compat.state.UNKNOWN"])
                self.assertEqual(card["notice"], ENGLISH["compat.status." + name])
                self.assertEqual(card["left"] + card["right"], [])
                self.assertFalse(card["listsShown"], "no parts, and no room kept for them")
                self.assertEqual(card["legend"], "", "the notice says why; the legend's reason for unknown would contradict it")
                self.assertFalse(card["legendShown"])
                self.assertEqual(card["data"], "-", "a report that cannot be used vouches for no data in force")
                self.assertEqual(card["engine"], "-", "nor for the Codex it was about, which may since have changed")
        absent = self.card("absent")
        self.assertEqual(absent["checked"], ENGLISH["time.never"])
        self.assertNotEqual(self.card("engine_changed")["checked"], ENGLISH["time.never"],
                            "when the last report was made is still said")
        self.assertTrue(self.card("ok")["listsShown"])

    def test_nothing_read_is_not_a_guess_and_a_failed_read_says_so(self):
        unread = self.card("unread")
        self.assertEqual((unread["overall"], unread["data"]), ("-", "-"))
        self.assertEqual(unread["left"] + unread["right"], [])
        self.assertFalse(unread["noticeShown"])
        unreadable = self.card("unreadable")
        self.assertEqual(unreadable["overall"], ENGLISH["diag.unknown"])
        self.assertEqual(unreadable["notice"], ENGLISH["pending.unavailable"])

    def test_a_refreshs_live_check_stands_until_a_report_as_new_arrives(self):
        live, kept, replaced = self.card("live"), self.card("liveKept"), self.card("liveReplaced")
        self.assertEqual(live["data"], "%s, #7" % ENGLISH["compat.source.cache"])
        self.assertEqual(kept["data"], live["data"], "an older report does not undo what the refresh just checked")
        self.assertEqual(replaced["data"], self.card("ok")["data"], "the watcher's newer report is what is shown")

    def story(self, name):
        seen = self.answer["stories"][name]
        if isinstance(seen, str):
            self.fail(seen[:3000])
        return seen

    def test_a_stopped_watchers_report_does_not_undo_a_refresh_past_its_interval(self):
        """The watcher is not running, so its report stays as it was - usable for REPORT_MAX_AGE. Ten minutes after a
        refresh the card went back to that report's 'bundled #1', beside a note saying #7 is in force."""
        refreshed = "%s, #7" % ENGLISH["compat.source.cache"]
        steps = self.story("watcher_stopped")
        self.assertEqual(steps[1]["data"], refreshed)
        self.assertEqual(steps[2]["data"], refreshed, "a report older than the live check says nothing newer")
        self.assertEqual(self.story("never_ran")[2]["data"], refreshed, "nor does a report that was never written")
        self.assertEqual(self.story("changed_before")[2]["data"], refreshed,
                         "nor one that already said Codex had changed when the live check looked at the Codex there now")
        caught_up = self.story("caught_up")
        self.assertEqual(caught_up[2]["data"], self.card("ok")["data"], "the watcher's own report, once it is as new")

    def test_a_report_that_became_unusable_ends_the_live_check(self):
        """Codex updated in place after the refresh: the report reads engine_changed, and the card says so rather than
        keep the live check's 'compatible' for the old Codex - failing closed, as every reader of the report does."""
        for name, status in (("changed_after", "engine_changed"), ("went_stale", "stale")):
            with self.subTest(name):
                card = self.story(name)[2]
                self.assertEqual(card["notice"], ENGLISH["compat.status." + status])
                self.assertEqual((card["data"], card["engine"]), ("-", "-"))
                self.assertEqual(card["left"] + card["right"], [])

    def test_a_live_check_as_old_as_a_report_may_be_is_as_stale_as_one(self):
        card = self.story("aged_out")[2]
        self.assertEqual(card["notice"], ENGLISH["compat.status.stale"])
        self.assertEqual(card["data"], "-")
        stands = self.answer["stands"]
        if isinstance(stands, str):
            self.fail(stands[:3000])
        self.assertEqual(stands, {"young": True, "as_old_as_a_report_may_be": False, "report_as_new": False,
                                  "unread_then_unusable": False, "invalid_since": False, "invalid_before": True})

    def test_an_update_checks_refresh_is_shown_as_the_buttons_is(self):
        """Check for updates refreshed the data. With the watcher stopped its report still says the data before was in
        force; the card shows the live check made after the refresh, beside the note that says so."""
        steps = self.story("update_refreshed")
        refreshed = "%s, #7" % ENGLISH["compat.source.cache"]
        self.assertEqual(steps[1]["note"], ENGLISH["diag.compat_refreshed"].replace("{sequence}", "7"))
        self.assertEqual(steps[1]["data"], refreshed)
        self.assertEqual(steps[2]["data"], refreshed)
        refused = self.story("update_refused")
        self.assertEqual(refused[1]["data"], self.card("ok")["data"], "nothing came in, so nothing else is shown")
        self.assertEqual(refused[1]["note"], ENGLISH["diag.compat_refused"].replace("{code}", "rollback")
                         .replace("{reason}", ENGLISH["compat.refused.rollback"]))

    def test_every_answer_is_said_as_itself(self):
        said = self.answer["said"]
        self.assertEqual(said["refreshed "], ENGLISH["diag.compat_refreshed"].replace("{sequence}", "12"))
        for code, key in (("from_the_future", "future"), ("duplicate_key", "invalid"), ("rollback", "rollback"),
                          ("not_a_json_file", "unreadable"), ("write_failed", "not_saved"), ("from_newer_product", "newer")):
            with self.subTest(code):
                self.assertEqual(said["refused " + code], ENGLISH["diag.compat_refused"].replace("{code}", code)
                                 .replace("{reason}", ENGLISH["compat.refused." + key]))
        for outcome in ("unavailable", "incomplete", "failed", "busy"):
            with self.subTest(outcome):
                self.assertEqual(said[outcome + " "], ENGLISH["diag.compat_" + outcome])
        self.assertEqual(said["something "], ENGLISH["diag.compat_failed"], "a word it does not know is not a success")
        self.assertEqual(self.answer["lineNote"], said["refused from_the_future"])

    def test_the_bridges_answer_is_read_as_itself(self):
        self.assertEqual(self.answer["outcomes"], {
            "refreshed": "refreshed", "refused": "refused", "unavailable": "unavailable", "incomplete": "incomplete",
            "failed": "failed", "unknown_word": "failed", "no_result": "failed", "refused_request": "failed",
            "nothing": "failed"})

    def test_the_update_checks_line_is_read_strictly(self):
        self.assertEqual(self.answer["lines"], {
            "refreshed": "refreshed 12", "refused": "refused from_the_future", "unavailable": "unavailable",
            "last_wins": "refreshed 3", "none": None, "no_sequence": None, "not_a_sequence": None,
            "not_a_code": None, "a_word_it_does_not_know": None, "too_many": None, "indented": "refreshed 5"})

    def test_the_registry_words_map_to_its_four_states(self):
        self.assertEqual(dict(self.answer["states"]), {
            "VERIFIED": "VERIFIED", "verified": "VERIFIED", "COMPATIBLE": "COMPATIBLE",
            "structurally_compatible": "COMPATIBLE", "INCOMPATIBLE": "INCOMPATIBLE", "incompatible": "INCOMPATIBLE",
            "UNKNOWN": "UNKNOWN", "unknown": "UNKNOWN", "something": "UNKNOWN", "": "UNKNOWN"})

    def test_the_button_waits_while_anything_else_is_in_flight(self):
        self.assertIs(self.answer["busyEnabled"], False)
        self.assertIs(self.answer["idleEnabled"], True)

    def test_it_speaks_the_windows_language(self):
        korean = l10n.catalog("ko")
        card = self.card("korean")
        self.assertEqual(card["overall"], korean["compat.state.INCOMPATIBLE"])
        self.assertEqual(card["button"], korean["diag.compat_refresh"])
        self.assertIn(korean["compat.meaning.VERIFIED"], card["legend"].splitlines())
        self.assertEqual(card["data"], korean["compat.source_sequence"].replace("{source}", korean["compat.source.cache"])
                         .replace("{sequence}", "12"))


if __name__ == "__main__":
    unittest.main()

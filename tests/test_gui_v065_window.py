r"""The v0.6.5 window, as the review of its first batch found it: the Pending list's switch that snapped, and the
columns that a narrow window cut where they hold the most.

The real compiled window is built in the probe's own process, the way LayoutAudit builds it - a bridge rooted where
nothing is, nothing asked of the watcher - and, where motion has to be seen, placed inside a window of the probe's own
far off the screen and shown without taking activation. Nothing is sent to any other window.

  * Pending's Auto-resume switch glides once its change is confirmed, as the popup's and the panel's do
    (requirement 15): a row's switch already on screen that its record now says is the other way moves there on
    brand's one transition, painting only its cell, and its timer stops when it arrives. A row that appears, a page
    that is not on screen, motion reduced - by the product's setting or by Windows' "Animation effects" - and a change
    refused move nothing.

    Whether Windows animates is the product's own input, Soft.WindowsAnimates, which the probe answers itself: GitHub's
    Windows runner has the switch off, and a probe that took this machine's answer glided nothing there and failed. The
    probe stands "on" in it to see the glide and "off" to see none, on any machine, and never changes Windows' setting.
  * Where even the columns' headings do not fit a list (a window made as narrow as it goes), the headings give way to
    what the columns hold before the cells do, and then the widest cells first (requirement 12): a column is never
    left room past what it holds while another's cells are cut.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import guiscan

from codex_auto_resume import brand, l10n

from test_gui_layout import fullest_snapshot

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

# SettingsForm.ColumnFloors: ((each column's heading, its widest cell, the least it is drawn at, how much of what a
# column holds is kept before a heading gives way, the list's width), widths).
COLUMNS = (
    # The review's German Pending list at 800 px (CSS px): "Status" and "Art" were cut to 53 and 48 while "Versuche"
    # kept 70 for a "2" and "Automatisch fortsetzen" 100 for a switch. Now every column keeps what it holds up to a
    # readable width, the headings give way, the widest first, and a time, a count and the switch stay whole.
    (([92, 53, 48, 110, 70, 150], [330, 250, 104, 64, 20, 56], [48, 48, 48, 48, 48, 56], 96, 464), [92, 96, 96, 64, 58, 58]),
    # Past readable, the headings come first: a state readable, the rest of it after them.
    (([92, 53, 48, 110, 70, 150], [60, 120, 90, 64, 20, 56], [48, 48, 48, 48, 48, 56], 96, 500), [81, 96, 90, 81, 70, 81]),
    # No rows: the headings alone, the widest first - as v0.6.5 first shrank them.
    (([92, 53, 48, 110, 70, 150], [0, 0, 0, 0, 0, 0], [48, 48, 48, 48, 48, 56], 96, 464), [92, 53, 48, 100, 70, 100]),
    # Narrower than every column's least: the least, and the list scrolls sideways on the soft bar.
    (([92, 53, 48, 110, 70, 150], [330, 250, 104, 64, 20, 56], [48, 48, 48, 48, 48, 56], 96, 250), [48, 48, 48, 48, 48, 56]),
    # Not room for every column readable: the widest cells give way; a name holds only as much as its heading.
    (([100, 60, 60], [400, 90, 50], [48, 48, 48], 96, 205), [77, 77, 50]),
    # Room for every column whole but the conversation's, which has what they leave.
    (([92, 53, 48, 110, 70, 150], [330, 250, 104, 64, 20, 56], [48, 48, 48, 48, 48, 56], 96, 900), [216, 250, 104, 110, 70, 150]),
    # Room for every heading whole and every column readable: what is left shared by what each wants past that.
    (([92, 53, 48, 110, 70, 150], [330, 250, 104, 64, 20, 56], [48, 48, 48, 48, 48, 56], 96, 700), [92, 177, 100, 110, 70, 150]),
)

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
# As the window's own Main does before its first control, so text is measured as the window draws it.
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System.Windows.Forms;
public class QuietForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; } }
}
// An answer for one of the window's inputs from Windows (Soft.WindowsAnimates), compiled, so it holds on any thread.
public static class Said {
    public static bool Yes() { return true; }
    public static bool No() { return false; }
    public static System.Func<bool> Answer(bool yes) { return yes ? new System.Func<bool>(Yes) : new System.Func<bool>(No); }
}
'@
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$soft = $assembly.GetType('CodexAutoResume.Soft', $true)
$palette = $assembly.GetType('CodexAutoResume.Palette', $true)
$json = $assembly.GetType('CodexAutoResume.Json', $true)
$parse = $json.GetMethod('Parse', $static)
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
function Read-Json([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Get-Field($target, [string]$name) { return $form.GetField($name, $instance).GetValue($target) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    return $method.Invoke($target, $arguments)
}
function P($target, [string]$name) { return $target.GetType().GetProperty($name, $instance).GetValue($target, $null) }
function Pump([int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 2 } while ($sw.ElapsedMilliseconds -lt $ms) }
$out = @{}
$systemScale = [double]$form.GetField('SystemScale', $static).GetValue($null)
$out.scale = $systemScale
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
function New-Window($catalog, $font) {
    $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
    $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
    $window = $three.Invoke([object[]]@($bridge, $catalog, $font))
    # Built as LayoutAudit builds it: nothing is asked of the watcher, and no clock runs.
    $form.GetField('auditing', $instance).SetValue($window, $true)
    $window.TopLevel = $false
    $window.MinimumSize = [Drawing.Size]::Empty
    return $window
}

# ------------------------------------------------------------------ ColumnFloors, the arithmetic
$floors = $form.GetMethod('ColumnFloors', $static)
$readable = $form.GetField('ReadableCells', $static)
$out.readable = if ($null -eq $readable) { -1 } else { [int]$readable.GetValue($null) }
$out.columns = @()
foreach ($case in (ConvertFrom-Json ([IO.File]::ReadAllText((Join-Path $work 'columns.json'), $utf8)))) {
    if ($null -eq $floors) { $out.columns += ,'SettingsForm has no ColumnFloors'; continue }
    $given = $floors.Invoke($null, [object[]]@([int[]]@($case[0] | ForEach-Object { [int]$_ }), [int[]]@($case[1] | ForEach-Object { [int]$_ }),
                                                [int[]]@($case[2] | ForEach-Object { [int]$_ }), [int]$case[3], [int]$case[4]))
    $out.columns += ,@($given | ForEach-Object { [int]$_ })
}

# ------------------------------------------------------------------ the narrowest window's lists
# Pending and History 800 px wide - the window's MinimumSize - with the fullest reply, in every language at 100% and
# 200%: each column's width, its heading's and its widest cell's, and the least it is drawn at.
$out.narrow = @{}
$snapshot = Read-Json 'snapshot.json'
$listOf = @{ pending = 'pendingList'; history = 'historyList' }
foreach ($scale in @(1.0, 2.0)) {
    $form.GetField('dpiScale', $static).SetValue($null, [double]$scale)
    $factor = [single]($scale / $systemScale)
    $box = [Drawing.SystemFonts]::MessageBoxFont
    [Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * $factor), $box.Style, ([Drawing.GraphicsUnit]::Point)
    foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
        $window = New-Window (Read-Json ('strings-' + $locale + '.json')) $font.PSObject.BaseObject
        $window.ClientSize = New-Object Drawing.Size ([int][Math]::Round(800 * $scale)), ([int][Math]::Round([int]$form.GetField('OpeningHeight', $static).GetValue($null) * $scale))
        Invoke-Window $window 'ApplySnapshot' @($snapshot)
        foreach ($page in @('pending', 'history')) {
            $null = Invoke-Window $window 'ShowPage' @($page)
            $null = $form.GetMethod('Materialise', $static).Invoke($null, [object[]]@($window))
            $window.PerformLayout()
            $list = Get-Field $window $listOf[$page]
            $cells = (Get-Field $window 'cellWidths')[$list]
            $columns = @()
            for ($i = 0; $i -lt $list.Columns.Count; $i++) {
                $columns += ,@([int]$list.Columns[$i].Width, [int](Invoke-Window $window 'HeadingWidth' @($list, [int]$i)),
                               [int]$cells[$i], [int](Invoke-Window $window 'LeastWidth' @($list, [int]$i)))
            }
            $out.narrow[$locale + ' ' + ([double]$scale).ToString('0.0', [Globalization.CultureInfo]::InvariantCulture) + ' ' + $page] = @{ client = [int]$list.ClientSize.Width; columns = $columns; scale = [double]$scale }
        }
        $window.Dispose()
    }
}
$form.GetField('dpiScale', $static).SetValue($null, $systemScale)

# ------------------------------------------------------------------ Pending's Auto-resume switch
# The window, at this machine's scale, inside a window of the probe's own far off the screen, shown without taking
# activation, on the Pending page.
$null = $palette.GetMethod('Adopt', $static).Invoke($null, [object[]]@('light'))
$reduce = $soft.GetField('ReduceMotionSetting', $static)
$reduce.SetValue($null, $false)
# Windows' "Animation effects" as the window reads it: the probe's own answer, "on", whatever this machine's is - the
# product's default input recorded first, so a test can hold it to Windows' own.
$animates = $soft.GetField('WindowsAnimates', $static)
$windowsAnswer = if ($null -eq $animates) { $null } else { $animates.GetValue($null) }
$out.seam = @{ found = ($null -ne $animates); default = $(if ($null -ne $windowsAnswer) { [string]$windowsAnswer.Method.Name } else { '' }) }
if ($null -ne $animates) { $animates.SetValue($null, [Said]::Answer($true)) }
$out.reducedHere = [bool]$soft.GetProperty('ReduceMotion', $static).GetValue($null)
$frame = New-Object QuietForm
$frame.FormBorderStyle = 'None'
$frame.ShowInTaskbar = $false
$frame.StartPosition = 'Manual'
$frame.Location = New-Object Drawing.Point -30000, -30000
$width = [int][Math]::Round([int]$form.GetField('OpeningWidth', $static).GetValue($null) * $systemScale)
$height = [int][Math]::Round([int]$form.GetField('OpeningHeight', $static).GetValue($null) * $systemScale)
$frame.ClientSize = New-Object Drawing.Size $width, $height
$window = New-Window (Read-Json 'strings-en.json') ([Drawing.SystemFonts]::MessageBoxFont)
$window.FormBorderStyle = 'None'
$window.Location = New-Object Drawing.Point 0, 0
$window.ClientSize = $frame.ClientSize
$frame.Controls.Add($window)
$window.Visible = $true
$frame.Show()
Pump 50
$on = Read-Json 'snapshot.json'
$off = Read-Json 'snapshot-off.json'
Invoke-Window $window 'ApplySnapshot' @($on)
$null = Invoke-Window $window 'ShowPage' @('pending')
Pump 50
$list = Get-Field $window 'pendingList'
# Tolerant of a window without them, so a build from before this is measured rather than stopped.
$glides = $null
try { $glides = Get-Field $window 'resumeGlides' } catch { }
$id = [string]$env:CAR_ROW
$item = $null
foreach ($candidate in $list.Items) { if ([string]$candidate.Tag['interruption_id'] -eq $id) { $item = $candidate } }
$out.glide = @{ listShown = [bool]$list.Visible; rowFound = ($null -ne $item); appeared = ($null -ne $glides -and $glides.ContainsKey($id)) }
function Glide { if ($null -ne $glides -and $glides.ContainsKey($id)) { return $glides[$id] } return $null }
# One of the glide's properties, or null when there is no glide.
function GlideOf([string]$name) { $g = Glide; if ($null -eq $g) { return $null } return P $g $name }
$draw = @($form.GetMethods($instance) | Where-Object { $_.Name -eq 'DrawResumeBox' })[0]
function Pixels([scriptblock]$paint) {
    $bitmap = New-Object Drawing.Bitmap 140, 70
    $g = [Drawing.Graphics]::FromImage($bitmap)
    $g.Clear([Drawing.Color]::White)
    try { & $paint $g } catch { $g.Dispose(); $bitmap.Dispose(); return 'not drawn: ' + $_.Exception.Message }
    $g.Dispose()
    $all = New-Object Text.StringBuilder
    for ($y = 0; $y -lt 70; $y++) { for ($x = 0; $x -lt 140; $x++) { $null = $all.Append($bitmap.GetPixel($x, $y).ToArgb()).Append(',') } }
    $bitmap.Dispose()
    return $all.ToString()
}
$cell = New-Object Drawing.Rectangle 0, 0, 140, 70
# The switch at rest, as a row with no glide draws it.
$restOn = Pixels { param($g) $null = $draw.Invoke($window, [object[]]@($g, $cell, $parse.Invoke($null, [object[]]@('{"interruption_id": "at-rest-on", "thread_enabled": true}')), [Drawing.Color]::White)) }
$restOff = Pixels { param($g) $null = $draw.Invoke($window, [object[]]@($g, $cell, $parse.Invoke($null, [object[]]@('{"interruption_id": "at-rest-off", "thread_enabled": false}')), [Drawing.Color]::White)) }
# Confirmed off: the switch glides from on to off. Drawn at once, mid-way, it is neither end; sampled every few ms, it
# only moves one way and arrives, and its timer stops. Only its cell is repainted, and nothing is laid out.
$script:layouts = 0
$list.add_Layout({ $script:layouts++ })
$tries = 0
do {
    $tries++
    Invoke-Window $window 'ApplySnapshot' @($on)
    Pump 250
    $script:layouts = 0
    Invoke-Window $window 'ApplySnapshot' @($off)
    $row = $null
    foreach ($candidate in $list.Items) { if ([string]$candidate.Tag['interruption_id'] -eq $id) { $row = $candidate.Tag } }
    $g0 = Glide
    $mid = Pixels { param($g) $null = $draw.Invoke($window, [object[]]@($g, $cell, $row, [Drawing.Color]::White)) }
    $moving = [bool](GlideOf 'Running')
} while (-not $moving -and $tries -lt 5)
$g0 = Glide
$out.glide.started = @($moving, $(if ($g0) { [double](GlideOf 'Target') } else { -1 }))
$out.glide.midway = @(($mid -ne $restOn), ($mid -ne $restOff))
$area = if ($g0) { $g0.GetType().GetField('Where', $instance).GetValue($g0) } else { $null }
$bounds = $null
foreach ($candidate in $list.Items) { if ([string]$candidate.Tag['interruption_id'] -eq $id) { $bounds = $candidate.SubItems[5].Bounds } }
$out.glide.area = @($(if ($area) { [string]$area.Invoke() } else { '' }), [string]$bounds)
$samples = @()
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.ElapsedMilliseconds -lt 450 -and $null -ne $g0) { $samples += ,@([double](GlideOf 'Value'), [bool](GlideOf 'Running')); Pump 8 }
$out.glide.samples = $samples
$out.glide.layouts = $script:layouts
$out.glide.timerAfter = if ($g0) { [bool]$g0.GetType().GetField('timer', $instance).GetValue($g0).Enabled } else { $null }
foreach ($candidate in $list.Items) { if ([string]$candidate.Tag['interruption_id'] -eq $id) { $row = $candidate.Tag } }
$out.glide.restAfter = ((Pixels { param($g) $null = $draw.Invoke($window, [object[]]@($g, $cell, $row, [Drawing.Color]::White)) }) -eq $restOff)
# The same answer again - a change refused, or a refresh that changes nothing - moves nothing.
Invoke-Window $window 'ApplySnapshot' @($off)
$out.glide.same = GlideOf 'Running'
# Motion reduced: there at once.
$reduce.SetValue($null, $true)
Invoke-Window $window 'ApplySnapshot' @($on)
$out.glide.reduced = @((GlideOf 'Running'), (GlideOf 'Value'))
$reduce.SetValue($null, $false)
# Windows' "Animation effects" off, the product's own setting not: there at once too, both ways - as on GitHub's runner.
$out.glide.windows = @()
if ($null -ne $animates) {
    $animates.SetValue($null, [Said]::Answer($false))
    $out.glide.windowsReduced = [bool]$soft.GetProperty('ReduceMotion', $static).GetValue($null)
    Invoke-Window $window 'ApplySnapshot' @($off)
    $out.glide.windows += ,@((GlideOf 'Running'), (GlideOf 'Value'))
    Invoke-Window $window 'ApplySnapshot' @($on)
    $out.glide.windows += ,@((GlideOf 'Running'), (GlideOf 'Value'))
    $animates.SetValue($null, [Said]::Answer($true))
}
# Another page on screen: Pending is not seen, so there at once too, and drawn as its record says when it comes back.
$null = Invoke-Window $window 'ShowPage' @('history')
Pump 30
Invoke-Window $window 'ApplySnapshot' @($off)
$out.glide.hidden = @((GlideOf 'Running'), (GlideOf 'Value'))
$null = Invoke-Window $window 'ShowPage' @('pending')
Pump 30
# A row that leaves the list takes its glide with it.
$gone = Read-Json 'snapshot-gone.json'
Invoke-Window $window 'ApplySnapshot' @($gone)
$out.glide.forgotten = ($null -ne $glides) -and -not $glides.ContainsKey($id)
$frame.Close()
$frame.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 8 -Compress), $utf8)
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
[Environment]::Exit(0)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)

        def reply(locale):
            return {"ok": True, "language": locale, "strings": l10n.catalog(locale), "endonyms": dict(l10n.ENDONYMS),
                    "preference": locale, "system_language": locale}

        for locale in l10n.LOCALES:
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply(locale), ensure_ascii=False), encoding="utf-8")
        now = time.time()
        fullest = fullest_snapshot(now)
        cls.row = fullest["pending"][0]["interruption_id"]
        off = copy.deepcopy(fullest)
        for part in ("pending", "history"):
            for record in off[part]:
                if record["interruption_id"] == cls.row:
                    record["thread_enabled"] = False
        gone = copy.deepcopy(fullest)
        gone["pending"] = [record for record in gone["pending"] if record["interruption_id"] != cls.row]
        for name, value in (("snapshot.json", fullest), ("snapshot-off.json", off), ("snapshot-gone.json", gone),
                            ("columns.json", [case for case, _ in COLUMNS])):
            (work / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        probe = work / "window.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work), CAR_ROW=cls.row,
                     CAR_LOCALES=json.dumps(list(l10n.LOCALES))))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-4000:])

    # ---------------------------------------------------------------- the columns of a narrow list

    def test_what_a_column_holds_gives_way_after_the_headings_until_it_is_no_longer_readable(self):
        self.assertEqual(len(self.answer["columns"]), len(COLUMNS))
        for (case, expected), given in zip(COLUMNS, self.answer["columns"]):
            with self.subTest(case=case):
                self.assertEqual(given, expected)
                self.assertLessEqual(sum(given), max(case[4], sum(case[2])), "never wider than the list, but for the least")

    def holds(self, found):
        """What each column of a measured list holds - its widest cell, a conversation's name only as far as its heading
        - and that up to a readable width, never less than the least it is drawn at."""
        readable = round(self.answer["readable"] * found["scale"])
        holds, kept = [], []
        for i, (_, heading, cell, least) in enumerate(found["columns"]):
            need = max(least, min(cell, heading) if i == 0 else cell)
            holds.append(need)
            kept.append(max(least, min(need, readable)))
        return holds, kept

    def test_no_column_keeps_room_past_what_it_holds_while_another_is_cut_short(self):
        """The review's German Pending list at 800 px and 200%: "Status" and "Art" cut to three or four letters, while
        "Versuche" kept 70 px for a "2", "Nächste Prüfung" 100 for a time and the last column 100 for its switch. In every
        language at 100% and 200%, Pending and History as narrow as the window goes: no column is wider than what it
        holds - its heading's room - while another's cells are cut short of readable. The last column takes the pixels the
        others leave, and is not counted."""
        self.assertEqual(self.answer["readable"], 96)
        self.assertEqual(len(self.answer["narrow"]), 2 * 2 * len(l10n.LOCALES))
        for key, found in sorted(self.answer["narrow"].items()):
            widths = [c[0] for c in found["columns"]]
            holds, kept = self.holds(found)
            cut = [i for i, width in enumerate(widths) if width < kept[i] - 1]
            spare = [i for i, width in enumerate(widths[:-1]) if width > holds[i] + 1]
            with self.subTest(key, widths=widths, holds=holds):
                self.assertLessEqual(sum(widths), found["client"], "wider than the list")
                self.assertFalse(cut and spare, "column %s keeps room past what it holds while %s is cut short" % (spare, cut))

    def test_the_reviews_german_list_reads_its_status_and_kind(self):
        found = self.answer["narrow"]["de 2.0 pending"]
        widths = [c[0] for c in found["columns"]]
        headings = [c[1] for c in found["columns"]]
        holds, kept = self.holds(found)
        for column in (1, 2):
            with self.subTest(column=column):
                self.assertGreaterEqual(widths[column], kept[column] - 1, "held to its short heading, its cells were cut to a few letters")
                self.assertGreater(widths[column], headings[column])
        for column in (3, 4):
            with self.subTest(column=column):
                self.assertGreaterEqual(widths[column], holds[column] - 1, "a time and a count stay whole")

    # ---------------------------------------------------------------- Pending's Auto-resume switch

    def test_the_pending_switch_glides_once_its_change_is_confirmed(self):
        """Requirement 15: the switch glides on brand's one transition when the control layer's answer comes back, as the
        popup's and the panel's switch for the same conversation do - drawn part-way while it moves, arriving at rest
        exactly as the switch at rest is drawn, and its timer stopped."""
        glide = self.answer["glide"]
        self.assertTrue(glide["listShown"] and glide["rowFound"], glide)
        self.assertFalse(glide["appeared"], "a row that appears is drawn as it is, not glided in")
        self.assertEqual(glide["started"], [True, 0.0], "a switch on screen that its record turns off glides to off")
        self.assertEqual(glide["midway"], [True, True], "drawn part-way, neither on nor off")
        values = [value for value, _ in glide["samples"]]
        self.assertEqual(values, sorted(values, reverse=True), "it only ever moves one way")
        self.assertEqual(glide["samples"][-1], [0.0, False], "it arrives and stops")
        self.assertFalse(glide["timerAfter"], "no timer left running")
        self.assertTrue(glide["restAfter"], "at rest it is exactly the switch at rest")

    def test_the_pending_switch_repaints_its_cell_and_lays_out_nothing(self):
        glide = self.answer["glide"]
        self.assertEqual(glide["layouts"], 0, "paint only: nothing is laid out while it moves")
        where, cell = glide["area"]
        self.assertTrue(where and where == cell, "each frame repaints the switch's cell and nothing else: %r" % (glide["area"],))

    def test_the_pending_switch_is_immediate_where_it_cannot_glide(self):
        glide = self.answer["glide"]
        self.assertFalse(glide["same"], "the same answer again, or a change refused, moves nothing")
        self.assertEqual(glide["reduced"], [False, 1.0], "with motion reduced it is there at once")
        self.assertEqual(glide["hidden"], [False, 0.0], "on a page not on screen it is there at once")
        self.assertTrue(glide["forgotten"], "a row that leaves the list takes its glide with it")

    def test_the_pending_switch_is_immediate_when_windows_reduces_motion(self):
        """Windows' "Animation effects" off - GitHub's runner, or a person who turned it off - and the product's own
        setting on: no glide, either way, as with the product's own Reduce motion."""
        glide = self.answer["glide"]
        self.assertTrue(glide.get("windowsReduced"), "Windows' animation switch off did not reduce motion")
        self.assertEqual(glide["windows"], [[False, 0.0], [False, 1.0]], "there at once, off and back on")

    def test_the_glide_is_brands_transition(self):
        self.assertEqual(brand.MOTION["transition_ms"], 160)
        # Seen on any machine: the probe answers the product's input for Windows' switch (Soft.WindowsAnimates) itself;
        # that what ships there is Windows' own answer is WindowSourceTests'.
        self.assertTrue(self.answer["seam"]["found"], "the window has no input for Windows' animation switch")
        self.assertFalse(self.answer["reducedHere"],
                         "motion was reduced with Windows' switch answered 'on' and the product's setting off")
        samples = self.answer["glide"]["samples"]
        moving = [value for value, running in samples if running]
        self.assertGreater(len(moving), 0)


class WindowSourceTests(unittest.TestCase):
    """What the review asked of the source, so it fails without a compiler too."""

    @classmethod
    def setUpClass(cls):
        cls.dashboard = guiscan.dashboard()
        cls.controls = guiscan.controls()

    def method(self, source, signature):
        start = source.index(signature)
        return source[start:source.index("\n        }\n", start)]

    def test_the_pending_switch_is_drawn_where_its_glide_is(self):
        draw = self.method(self.dashboard, "private void DrawResumeBox(")
        self.assertIn("Soft.SwitchAt(", draw)
        self.assertNotIn("Soft.Switch(g", draw)
        follow = self.method(self.dashboard, "private void FollowResumeSwitches(")
        self.assertIn("Motion.Allowed(pendingList)", follow)
        self.assertIn(".To(", follow)
        self.assertNotIn("PerformLayout", follow)

    def test_a_transition_repaints_only_where_it_is_told(self):
        transition = guiscan.type_body("Transition")
        self.assertIn("internal Func<Rectangle> Where;", transition)
        self.assertNotIn("PerformLayout", transition)

    def test_nothing_moves_on_a_page_not_on_screen(self):
        allowed = self.method(self.controls, "internal static bool Allowed(Control control)")
        self.assertIn("!control.Visible", allowed, "Soft.Shown sees only the control's own style, not a hidden page's")

    def test_windows_animation_switch_is_one_input_the_window_only_reads(self):
        """Motion reads Windows' switch through Soft.WindowsAnimates, which ships as Windows' own answer and which
        nothing in the window sets: a probe's answer there is the only other one it ever has."""
        self.assertIn("internal static Func<bool> WindowsAnimates = WindowsAnimationEffects;", self.controls)
        reduced = self.method(self.controls, "internal static bool ReduceMotion\n")
        self.assertIn("WindowsAnimates", reduced)
        self.assertNotIn("SystemParametersInfo", reduced, "Windows is asked through the input, not beside it")
        asked = self.method(self.controls, "internal static bool WindowsAnimationEffects()")
        self.assertIn("SPI_GETCLIENTAREAANIMATION", asked)
        # Once in the whole window, wherever it is written: what matters is that there is one
        # place it is set, not which file that place is in.
        self.assertEqual(guiscan.whole().count("WindowsAnimates ="), 1)


if __name__ == "__main__":
    unittest.main()

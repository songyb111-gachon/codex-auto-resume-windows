r"""v0.6.12: the power action's card, the last of Settings > General (gui/SettingsPower.cs).

Arming is an act, not a setting (H2/H3, H14): the card's controls are never editors, so Save, the
unsaved-changes baseline and a reopen never see them, and a Save cannot arm again a Once that was spent.
It turns on and off with the switch every on-or-off setting in the window is - the owner, 2026-10-04: a
button inside Settings looked out of place - and it still applies at once. Turning it on asks first with
Cancel the default, so a reflex Enter arms nothing, and the switch is back off after Cancel or a refusal;
turning it off asks nothing, as Pause asks nothing. The switch is on exactly while something is armed,
from every answer and every status, and being set so fires nothing. It joins SetBusy, so it waits its
turn like every other control. Every word it says is a catalog key whose fallback is the English sentence.

The source half reads the window with guiscan; the built half compiles the real window, never shown and
asking no bridge (it is audited, so the card asks nothing), and drives the card through the answers the
bridge gives (tests/golden/bridge/power-action.json) - and lays Settings > General out with the card in the
longest it says, at 150 % in Korean and in English (AuditPower; test_gui_layout.py audits every language
at every scaling). Then a second window, shown off-screen with a bridge that does not exist - so every
call it makes is refused at once and reaches nothing - has its switch clicked, while a timer answers each
question it asks as a person would.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import tempfile
import unittest

import guiscan
from codex_auto_resume import controlcli, l10n, poweraction, settings
from codex_auto_resume.domain.power_vocabulary import PowerAction, PowerAfter, PowerRepeat, PowerUnavailable, PowerWait
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, reply, run_probe

ROOT = Path(__file__).resolve().parents[1]
CARD = "gui/SettingsPower.cs"
# A C# string literal: the escapes the window writes are Python's too (\n, \", \\).
LITERAL = r'"(?:[^"\\\r\n]|\\.)*"'


def card() -> str:
    return guiscan.read(CARD)


def body(member: str) -> str:
    """One SettingsForm method by its declaration - a modifier first, so `else ShowPower();` is never taken for it."""
    whole = guiscan.whole()
    found = re.search(r"(?m)^[ \t]*(?:private|internal|protected|public)\b[^\n;=]*?\b%s\(" % re.escape(member), whole)
    if found is None:
        raise guiscan.ScanError("SettingsForm has no member named %s" % member)
    return guiscan._block(whole, found.start())


class PlaceTests(unittest.TestCase):
    def test_the_card_is_a_settings_source_on_the_compile_list(self):
        self.assertIn(CARD, guiscan.group("settings"))

    def test_it_is_built_right_after_notifications_and_is_the_last_card_of_general(self):
        build = body("BuildEditors")
        notifications = build.index('NewGroup(S("group.notifications", "Notifications"), sections["general"])')
        power = build.index('BuildPower(sections["general"]);')
        self.assertLess(notifications, power)
        # Nothing between them, and no card added to General after it.
        between = build[notifications:power]
        self.assertEqual(between.count(";"), 1, between)
        self.assertNotIn('sections["general"]', build[power + len('BuildPower(sections["general"]);'):])
        self.assertEqual(guiscan.whole().count("BuildPower("), 2, "one call, and the declaration")

    def test_it_follows_the_status_every_read_brings(self):
        self.assertIn("ApplyPowerStatus(status);", body("ApplyStatus"))
        follow = body("ApplyPowerStatus")
        self.assertIn('Map(status, "power_action")', follow)
        self.assertIn('Get(status, "watcher_running")', follow)


class AskedWhenShownTests(unittest.TestCase):
    """B16 and PRIVACY: whether this account may shut down and which sleep states the PC offers are asked when
    the Dashboard shows the card, and when it turns the power action on or off - never because the card was
    built. The Settings editors, the card with them, are built at the first idle after the window opens,
    whatever page it opened on, and building them used to ask Windows on every opening of the Dashboard."""

    def test_building_the_card_asks_only_where_it_is_shown(self):
        build = body("BuildPower")
        self.assertNotIn("LoadPower();", build)
        self.assertIn("LoadPowerWhereShown();", build)
        shown = body("LoadPowerWhereShown")
        for condition in ('currentPage != "settings"', 'currentSection != "general") return;'):
            with self.subTest(condition):
                self.assertIn(condition, shown.split("LoadPower();")[0])
        self.assertIn("LoadPower();", shown)

    def test_showing_settings_or_its_general_section_asks(self):
        for member in ("ShowPage", "ShowSection"):
            with self.subTest(member):
                self.assertIn("LoadPowerWhereShown();", body(member))

    def test_nothing_else_asks(self):
        self.assertEqual(len(re.findall(r"\bLoadPower\(\);", guiscan.whole())), 3,
                         "where the card is shown, after turning it off and after turning it on")


class SwitchTests(unittest.TestCase):
    """The card's one control that acts is the switch every on-or-off setting in the window is (NewCheck,
    a SoftCheck drawn as a switch), never a button, and a click alone never moves it."""

    def test_it_is_the_switch_every_on_or_off_setting_is_and_the_card_has_no_button(self):
        build = body("BuildPower")
        self.assertIn('powerSwitch = NewCheck("", false, false);', build,
                      "NewCheck's last argument false: drawn as a switch, not as a list item's box")
        self.assertIn("private CheckBox powerSwitch;", card())
        self.assertNotIn("MakeButton(", card())
        self.assertNotIn("powerButton", guiscan.whole())

    def test_it_is_the_cards_first_line(self):
        build = body("BuildPower")
        added = re.findall(r"powerCard\.Controls\.Add\((\w+)", build)
        self.assertEqual(added[0], "powerSwitch", added)
        self.assertLess(build.index("NewGroup("), build.index("powerCard.Controls.Add(powerSwitch);"))

    def test_a_click_never_moves_it_and_only_a_click_acts(self):
        build = body("BuildPower")
        self.assertIn("powerSwitch.AutoCheck = false;", build)
        self.assertIn("powerSwitch.Click += delegate { PowerSwitched(); };", build)
        whole = guiscan.whole()
        self.assertNotRegex(whole, r"powerSwitch\.(?:CheckedChanged|CheckStateChanged)\b",
                            "a handler on its state would act when a status sets it")
        self.assertEqual(len(re.findall(r"\bPowerSwitched\(\)", whole)), 2, "the click, and the declaration")

    def test_every_time_it_is_drawn_it_is_on_exactly_while_something_is_armed(self):
        show = body("ShowPower")
        self.assertIn("powerSwitch.Checked = armed != null;", show)
        self.assertIn("powerSwitch.Text = state;", show)
        for line in ('state = S("power.state.off", "Off");', "state = PowerGraceLine(action, ClockTime(until));",
                     "state = PowerOnLine(action);"):
            with self.subTest(line):
                self.assertIn(line, show)

    def test_a_screen_reader_names_it_by_the_card_and_reads_its_line(self):
        build = body("BuildPower")
        self.assertIn('string title = S("power.title", ', build)
        self.assertIn("powerSwitch.AccessibleName = title;", build)
        self.assertIn("powerSwitch.AccessibleDescription = state;", body("ShowPower"))

    def test_the_buttons_words_are_gone_from_every_catalog(self):
        for locale in l10n.LOCALES:
            table = l10n._read(locale)
            for key in ("power.turn_on", "power.turn_off"):
                with self.subTest(locale=str(locale), key=key):
                    self.assertNotIn(key, table)


class NotAnEditorTests(unittest.TestCase):
    def test_none_of_its_controls_is_an_editor(self):
        source = card()
        for name in ("editors", "jsonValues", "baseline"):
            with self.subTest(name):
                self.assertNotRegex(source, r"\b%s\s*[\[.=]" % name)

    def test_save_and_the_edits_it_sends_never_read_the_card(self):
        for member in ("Save", "EditorValues"):
            with self.subTest(member):
                self.assertNotRegex(body(member), r"(?i)power")

    def test_it_asks_the_bridge_itself_and_never_while_audited(self):
        load = body("LoadPower")
        self.assertIn("auditing", load.split("CallAsync")[0])
        self.assertIn('CallAsync("power-action", null', load)
        source = card()
        for command in ("power-action", "power-arm", "power-disarm"):
            with self.subTest(command):
                self.assertIn('"%s"' % command, source)
                self.assertTrue(command in controlcli.PLAIN or command in controlcli.WITH_ARGUMENT)


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.switched = body("PowerSwitched")

    def test_turning_it_on_asks_with_cancel_the_default(self):
        self.assertIn('Dialog(question, S("power.confirm.affirm", "Turn on"), S("action.cancel", "Cancel"))',
                      self.switched, "with `away`, Cancel is the accented default (DashboardActions.Dialog)")
        self.assertNotIn("Say(", self.switched)
        self.assertNotIn("Confirm(", self.switched)
        asked = self.switched.index("if (!Dialog(")
        self.assertLess(asked, self.switched.index('"power-arm"'), "nothing is armed before the yes")

    def test_it_moves_on_only_at_the_yes_and_cancel_leaves_it_off(self):
        asked = self.switched.index("if (!Dialog(")
        cancelled = self.switched[asked:self.switched.index("return;", asked)]
        self.assertIn("powerSwitch.Checked = false;", cancelled)
        self.assertEqual(self.switched.count("powerSwitch.Checked = true;"), 1)
        on = self.switched.index("powerSwitch.Checked = true;")
        self.assertLess(asked, on)
        self.assertLess(on, self.switched.index('"power-arm"'))

    def test_a_refused_arm_turns_it_back_off_before_the_reason_is_said(self):
        arm = self.switched[self.switched.index('"power-arm"'):]
        self.assertIn("if (!Ok(reply)) powerSwitch.Checked = false;", arm)
        self.assertLess(arm.index("powerSwitch.Checked = false;"), arm.index("Report(reply);"))

    def test_turning_it_off_asks_nothing_and_moves_at_once(self):
        disarm = self.switched.index('"power-disarm"')
        asked = self.switched.index("Dialog(")
        self.assertLess(disarm, asked)
        self.assertIn("return;", self.switched[disarm:asked])
        self.assertLess(self.switched.index("powerSwitch.Checked = false;"), disarm)
        refused = self.switched[disarm:asked]
        self.assertIn("if (!Ok(reply)) ShowPower();", refused, "refused, it is still on, and says so")
        self.assertLess(refused.index("ShowPower();"), refused.index("Report(reply);"))

    def test_the_confirmation_is_filled_with_the_cards_own_labels(self):
        for placeholder in ("{action}", "{after}", "{repeat}", "{grace}"):
            with self.subTest(placeholder):
                self.assertIn('.Replace("%s", ChoiceWords(' % placeholder, self.switched)
        self.assertIn('S("power.confirm.shut_down"', self.switched)
        self.assertIn('action == "shut_down"', self.switched)

    def test_it_arms_with_exactly_the_four_values_the_bridge_takes(self):
        keys = re.findall(r'\\"(\w+)\\":', self.switched)
        self.assertEqual(tuple(keys), poweraction.CHOICE_KEYS)


class BusyTests(unittest.TestCase):
    def test_its_switch_joins_set_busy(self):
        self.assertIn("if (powerSwitch != null) powerSwitch.Enabled = busy == 0 && powerCanSwitch;", body("SetBusy"))

    def test_every_time_it_is_drawn_the_switch_still_waits_for_a_call_in_flight(self):
        self.assertIn("powerSwitch.Enabled = busy == 0 && powerCanSwitch;", body("ShowPower"))
        self.assertIn("busy > 0", body("PowerSwitched"))

    def test_nothing_can_be_turned_on_until_windows_answered_what_it_offers(self):
        show = body("ShowPower")
        self.assertIn("powerCanSwitch = powerOptions != null", show)


class VocabularyTests(unittest.TestCase):
    def words(self, name: str) -> list[str]:
        found = re.search(r"%s\s*=\s*\{([^}]*)\}" % name, card())
        return [ast.literal_eval(word.strip()) for word in found.group(1).split(",")]

    def test_its_words_are_the_bridges(self):
        self.assertEqual(self.words("PowerActions"), [str(word) for word in PowerAction])
        self.assertEqual(self.words("PowerAfters"), [str(word) for word in PowerAfter])
        self.assertEqual(self.words("PowerRepeats"), [str(word) for word in PowerRepeat])
        self.assertEqual(tuple(int(word) for word in self.words("PowerGraceMinutes")), poweraction.GRACE_MINUTES)
        self.assertIn('PowerDefaultGrace = "5"', card())

    def test_every_reason_it_waits_and_every_way_a_batch_ends_has_its_line(self):
        wait = body("PowerWaitLine")
        for word in PowerWait:
            with self.subTest(word):
                self.assertIn('if (word == "%s") return S("power.wait.%s"' % (word, word), wait)
        last = body("PowerLastLine")
        for word in ("failed", "skipped", "not_met", "stale", "lapsed", "unavailable"):
            with self.subTest(word):
                self.assertIn('if (result == "%s") return S("power.last.%s"' % (word, word), last)
        unavailable = body("PowerUnavailableLine")
        for word in PowerUnavailable:
            with self.subTest(word):
                self.assertIn('"%s"' % word, unavailable + body("ShowPower"))


class StringTests(unittest.TestCase):
    """Every word by its key, and every fallback the English sentence (test_l10n's rule for the names, for all)."""

    def setUp(self):
        self.english = l10n._read(l10n.DEFAULT)
        self.window = guiscan.whole()

    def test_every_power_key_is_in_the_window_and_said_by_its_key(self):
        keys = sorted(key for key in self.english if key.startswith("power."))
        self.assertGreaterEqual(len(keys), 50)
        for key in keys:
            with self.subTest(key):
                self.assertRegex(self.window, r'S\("%s",\s' % re.escape(key))

    def test_every_fallback_is_the_english_sentence(self):
        call = re.compile(r'S\("((?:power\.[\w.]+)|time\.minutes|action\.cancel)",\s*(%s)' % LITERAL)
        found = set()
        for match in call.finditer(card()):
            key, said = match.group(1), ast.literal_eval(match.group(2))
            found.add(key)
            with self.subTest(key):
                self.assertEqual(said, self.english[key])
        self.assertEqual(found, {key for key in self.english if key.startswith("power.")} | {"time.minutes",
                                                                                              "action.cancel"})
        # Every mention of a power key in the window is such a call, so a fallback written otherwise cannot slip by.
        for key in found - {"time.minutes", "action.cancel"}:
            with self.subTest(key=key, every_mention=True):
                self.assertEqual(self.window.count('"%s"' % key), len(re.findall(r'S\("%s",' % re.escape(key),
                                                                                   self.window)))

    def test_no_key_is_composed_from_a_word(self):
        self.assertNotRegex(card(), r'S\("power\.[\w.]*"\s*\+')

    def test_the_audit_lays_the_card_out_in_the_longest_it_says(self):
        audit = body("LayoutAuditAt")
        self.assertIn("form.AuditPower(findings);", audit)
        self.assertIn("AuditedPower = 0;", audit)
        power = body("AuditPower")
        for word in PowerWait:
            with self.subTest(word):
                self.assertIn('"%s"' % word, power)


# The card driven through the bridge's answers, in a window built and never shown; then LayoutAudit at 150 %;
# then the switch clicked in a window shown off-screen, whose every call is refused at once.
PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
$F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
$J = $assembly.GetType('CodexAutoResume.Json', $true)
$CH = $assembly.GetType('CodexAutoResume.Choice', $true)
$utf8 = New-Object Text.UTF8Encoding $false
function Read($name) { return [IO.File]::ReadAllText((Join-Path $env:CAR_WORK $name), $utf8) }
function Parse([string]$text) { return ,$J.GetMethod('Parse', $flags).Invoke($null, [object[]]@($text)) }
function Call($name, $arguments) {
  $given = New-Object 'object[]' $arguments.Count
  for ($i = 0; $i -lt $arguments.Count; $i++) {
    $value = $arguments[$i]
    if ($null -ne $value -and $value -is [psobject]) { $value = $value.PSObject.BaseObject }
    $given[$i] = $value
  }
  return $F.GetMethod($name, $flags).Invoke($form, $given)
}
function Field($name) { return $F.GetField($name, $flags).GetValue($form) }
$out = @{}

[string]$nowhere = Join-Path $env:CAR_WORK 'nowhere'
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
# A window whose bridge does not exist: no python.exe under `nowhere`, so every call is refused before it starts.
function NewWindow() {
  $bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
  $persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
  $window = $make.Invoke([object[]]@($persistent.PSObject.BaseObject, (Parse (Read 'strings-en.json')), [Drawing.SystemFonts]::MessageBoxFont))
  $F.GetField('auditing', $flags).SetValue($window, $true)
  return $window
}
$form = NewWindow
$form.TopLevel = $false
$form.ClientSize = New-Object Drawing.Size 1000, 664
Call 'BuildEditors' @((Parse (Read 'schema.json')), (Parse (Read 'settings.json'))) | Out-Null
$form.PerformLayout()

$names = @('powerSwitch', 'powerAction', 'powerAfter', 'powerRepeat', 'powerGrace')
$controls = @($names | ForEach-Object { Field $_ })
$editors = Field 'editors'
$out.editors = @($editors.Values | Where-Object { $controls -contains $_ }).Count
$general = (Field 'sections')['general']
$out.last = [object]::ReferenceEquals($general.Controls[$general.Controls.Count - 1], (Field 'powerCard'))
$switch = Field 'powerSwitch'
# Beside the switch every other on-or-off setting is: Run at Windows sign-in's, made by the same NewCheck.
$startup = $editors['__startup']
$box = $switch.GetType().GetProperty('Box', $flags)
$out.kind = @{ type = $switch.GetType().Name; startupType = $startup.GetType().Name
               box = [bool]$box.GetValue($switch, $null); startupBox = [bool]$box.GetValue($startup, $null)
               font = [string]$switch.Font; startupFont = [string]$startup.Font
               margin = [string]$switch.Margin; startupMargin = [string]$startup.Margin
               autoCheck = [bool]$switch.AutoCheck; name = [string]$switch.AccessibleName
               index = (Field 'powerCard').Controls.GetChildIndex($switch) }
$out.unread = @{ enabled = $switch.Enabled; state = $switch.Text; on = $switch.Checked }

# What Save would send, before and after every row of the card - and its switch - is changed.
$before = (Call 'EditorValues' @()) | ConvertTo-Json -Compress
(Field 'powerGrace').SelectedIndex = 4
(Field 'powerRepeat').SelectedIndex = 1
(Field 'powerAfter').SelectedIndex = 2
$switch.Checked = $true
$after = (Call 'EditorValues' @()) | ConvertTo-Json -Compress
$switch.Checked = $false
$out.saveUntouched = ($before -eq $after)

function State($label) {
  $s = Field 'powerSwitch'
  return @{ enabled = $s.Enabled; on = $s.Checked; state = $s.Text; spoken = [string]$s.AccessibleDescription
            then = @((Field 'powerAction').Items | ForEach-Object { $CH.GetField('Value', $flags).GetValue($_) }); rows = (Field 'powerAfter').Enabled
            wait = (Field 'powerWait').Text; unavailable = (Field 'powerUnavailable').Text
            last = (Field 'powerLast').Text; card = (Field 'powerCard').Enabled }
}
$out.states = @{}
$cases = @{}
foreach ($case in (ConvertFrom-Json (Read 'options.json'))) {
  $cases[$case.case] = ($case.options | ConvertTo-Json -Depth 8 -Compress)
  Call 'ApplyPowerOptions' @((Parse $cases[$case.case])) | Out-Null
  $out.states[$case.case] = State
  if ($case.case -eq 'nothing armed, and every action offered') {
    Call 'SetBusy' @($true) | Out-Null
    $out.busy = (Field 'powerSwitch').Enabled
    Call 'SetBusy' @($false) | Out-Null
    $out.free = (Field 'powerSwitch').Enabled
  }
}
# A status with no power_action: its file is gone, so Off, whatever the last answer said.
Call 'ApplyPowerStatus' @((Parse '{"watcher_running": true}')) | Out-Null
$out.statusOff = State
# Armed while the watcher is stopped: nothing happens until it runs.
Call 'ApplyPowerStatus' @((Parse (Read 'status-stopped.json'))) | Out-Null
$out.statusStopped = State
# Set from a status both ways, it called nothing: a call in flight would still count here, as nothing pumps it.
$out.statusBusy = [int](Field 'busy')
$form.Dispose()

$audit = $F.GetMethod('LayoutAudit', $flags)
$audited = $F.GetField('AuditedPower', $flags)
$out.audit = @{}
$out.audited = @{}
foreach ($locale in @('ko', 'en')) {
  $out.audit[$locale] = [string]$audit.Invoke($null, [object[]]@((Read 'schema.json'), (Read 'settings.json'), (Read ('strings-' + $locale + '.json')), '', [double]1.5))
  $out.audited[$locale] = [int]$audited.GetValue($null)
}

# The switch clicked, in a window shown off-screen. It is audited, so nothing of its own asks the bridge.
$form = NewWindow
$form.StartPosition = 'Manual'
$form.Location = New-Object Drawing.Point -4000, -4000
$form.ShowInTaskbar = $false
$form.Show()
[Windows.Forms.Application]::DoEvents()
Call 'BuildEditors' @((Parse (Read 'schema.json')), (Parse (Read 'settings.json'))) | Out-Null
function Offer($name) { Call 'ApplyPowerOptions' @((Parse $cases[$name])) | Out-Null }

# Each dialog holds the thread in ShowDialog, so a timer reads it and answers it as `plan` says: 'enter' presses
# what Enter presses, 'escape' what Escape presses (and answers any dialog the plan does not expect), 'affirm'
# the button that acts.
$script:plan = New-Object Collections.Queue
$script:asked = New-Object Collections.ArrayList
$watch = New-Object Windows.Forms.Timer
$watch.Interval = 100
$watch.Add_Tick({
  foreach ($open in @([Windows.Forms.Application]::OpenForms)) {
    if ([object]::ReferenceEquals($open, $form) -or -not $open.Modal -or -not $open.Visible) { continue }
    try {
      $words = ''
      $buttons = @()
      foreach ($c in $open.Controls) {
        foreach ($k in $c.Controls) {
          if ($k -is [Windows.Forms.Label]) { $words = [string]$k.Text }
          if ($k.GetType().Name -eq 'SoftTextArea') { $words = [string]$k.GetType().GetField('Box', $flags).GetValue($k).Text }
          if ($k -is [Windows.Forms.Button]) { $buttons += ,$k }
        }
      }
      $press = if ($script:plan.Count -gt 0) { [string]$script:plan.Dequeue() } else { 'escape' }
      $target = $open.CancelButton
      if ($press -eq 'enter') { $target = $open.AcceptButton }
      if ($press -eq 'affirm') { $target = @($buttons | Where-Object { -not [object]::ReferenceEquals($_, $open.CancelButton) })[0] }
      $focused = $open.ActiveControl
      [void]$script:asked.Add(@{ words = $words; enter = [string]$open.AcceptButton.Text; escape = [string]$open.CancelButton.Text
                                 focus = $(if ($focused -eq $null) { '' } else { [string]$focused.Text })
                                 on = [bool](Field 'powerSwitch').Checked; press = $press; pressed = [string]$target.Text })
      $target.PerformClick()
    } catch { [void]$script:asked.Add(@{ failed = [string]$_ }) }
    if (-not $open.IsDisposed -and $open.Visible) { $open.Close() }
  }
})
$watch.Start()
$onClick = [Windows.Forms.Control].GetMethod('OnClick', $flags)
# What a click on the switch does: Control.OnClick, through CheckBox's, which moves it only while AutoCheck is on.
function Click() { $onClick.Invoke((Field 'powerSwitch'), [object[]]@([EventArgs]::Empty)) | Out-Null }
function Now() { return @{ on = [bool](Field 'powerSwitch').Checked; busy = [int](Field 'busy'); asked = [int]$script:asked.Count } }
# Until the call in flight has been answered, the answer drawn and any dialog it opened answered.
function Settle() {
  $clock = [Diagnostics.Stopwatch]::StartNew()
  do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 5 } while ([int](Field 'busy') -gt 0 -and $clock.ElapsedMilliseconds -lt 30000)
  $clock.Restart()
  do { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 5 } while ($clock.ElapsedMilliseconds -lt 400)
}
$out.clicks = @{}
Offer 'nothing armed, and every action offered'
$out.clicks.offered = Now
$script:plan.Enqueue('enter')
Click
$out.clicks.cancelled = Now
$script:plan.Enqueue('affirm')
Click
$out.clicks.arming = Now
Settle
$out.clicks.refused = Now
Offer 'armed to shut down every time'
$out.clicks.armed = Now
Click
$out.clicks.disarming = Now
Settle
$out.clicks.stillArmed = Now
Offer "while an administrator's DisablePowerAction is set"
Click
Settle
$out.clicks.greyed = Now
Call 'ApplyPowerStatus' @((Parse (Read 'status-stopped.json'))) | Out-Null
$out.clicks.statusOn = Now
Call 'ApplyPowerStatus' @((Parse '{"watcher_running": true}')) | Out-Null
$out.clicks.statusOff = Now
Settle
$out.clicks.settled = Now
$out.asked = @($script:asked)
$form.Close()
$form.Dispose()
$watch.Stop()
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class BuiltCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(settings.defaults(), ensure_ascii=False), encoding="utf-8")
        for locale in ("en", "ko"):
            (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply(locale), ensure_ascii=False),
                                                             encoding="utf-8")
        golden = json.loads((ROOT / "tests" / "golden" / "bridge" / "power-action.json").read_text(encoding="utf-8"))
        cases = [{"case": case["case"], "options": case["reply"]["result"]} for case in golden["cases"]]
        (work / "options.json").write_text(json.dumps(cases), encoding="utf-8")
        armed = next(case["options"]["view"] for case in cases if case["options"]["view"]["armed"])
        (work / "status-stopped.json").write_text(json.dumps({"watcher_running": False, "power_action": armed}),
                                                  encoding="utf-8")
        cls.answer = run_probe(PROBE, work, 900, CAR_EXE=str(exe))
        cls.english = l10n._read(l10n.DEFAULT)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def state(self, case: str) -> dict:
        return self.answer["states"][case]

    def clicks(self, step: str) -> dict:
        return self.answer["clicks"][step]

    def refusal(self, asked: dict) -> None:
        self.assertTrue(asked["words"].startswith(self.english["action.failed"]), asked)
        self.assertEqual(asked["escape"], self.english["action.close"])

    def test_its_controls_are_not_editors_and_save_sends_the_same_whatever_they_show(self):
        self.assertEqual(self.answer["editors"], 0)
        self.assertTrue(self.answer["saveUntouched"])

    def test_it_is_the_last_card_of_general(self):
        self.assertTrue(self.answer["last"])

    def test_it_is_the_switch_the_other_settings_are_first_in_its_card_and_named_by_it(self):
        kind = self.answer["kind"]
        self.assertEqual(kind["type"], "SoftCheck")
        self.assertEqual(kind["type"], kind["startupType"])
        self.assertFalse(kind["box"], "drawn as a switch, not as a list item's box")
        self.assertEqual(kind["box"], kind["startupBox"])
        self.assertEqual(kind["font"], kind["startupFont"])
        self.assertEqual(kind["margin"], kind["startupMargin"])
        self.assertFalse(kind["autoCheck"], "a click alone never moves it")
        self.assertEqual(kind["name"], self.english["power.title"])
        self.assertEqual(kind["index"], 1, "right under the card's heading")

    def test_before_windows_answered_it_says_off_and_cannot_be_turned_on(self):
        self.assertEqual(self.answer["unread"]["state"], self.english["power.state.off"])
        self.assertFalse(self.answer["unread"]["on"])
        self.assertFalse(self.answer["unread"]["enabled"])

    def test_every_action_offered_can_be_turned_on_and_its_switch_waits_while_busy(self):
        state = self.state("nothing armed, and every action offered")
        self.assertTrue(state["enabled"])
        self.assertFalse(state["on"])
        self.assertTrue(state["rows"])
        self.assertEqual(state["then"], ["sleep", "hibernate", "shut_down"])
        self.assertEqual(state["unavailable"], "")
        self.assertFalse(self.answer["busy"])
        self.assertTrue(self.answer["free"])

    def test_an_action_windows_does_not_offer_is_left_out_with_its_reason(self):
        state = self.state("hibernation off in Windows")
        self.assertEqual(state["then"], ["sleep", "shut_down"])
        self.assertEqual(state["unavailable"], self.english["power.unavailable.hibernate"])
        self.assertTrue(state["enabled"])

    def test_an_account_without_the_privilege_is_offered_nothing_and_told_why_once(self):
        state = self.state("an account Windows lets do none of them")
        self.assertEqual(state["then"], [])
        self.assertEqual(state["unavailable"], self.english["power.unavailable.privilege"])
        self.assertFalse(state["enabled"])
        self.assertFalse(state["on"])
        self.assertFalse(state["rows"])

    def test_an_administrators_key_greys_the_whole_card_and_says_so(self):
        state = self.state("while an administrator's DisablePowerAction is set")
        self.assertFalse(state["card"])
        self.assertFalse(state["enabled"])
        self.assertEqual(state["wait"], self.english["power.managed"])

    def test_armed_its_switch_is_on_and_the_rows_show_the_armed_choices_greyed(self):
        state = self.state("armed to shut down every time")
        self.assertEqual(state["state"], self.english["power.state.on.shut_down"])
        self.assertEqual(state["spoken"], self.english["power.state.on.shut_down"])
        self.assertTrue(state["on"])
        self.assertTrue(state["enabled"])
        self.assertFalse(state["rows"])

    def test_a_status_without_its_file_says_off_and_a_stopped_watcher_is_said(self):
        self.assertEqual(self.answer["statusOff"]["state"], self.english["power.state.off"])
        self.assertFalse(self.answer["statusOff"]["on"])
        self.assertEqual(self.answer["statusStopped"]["wait"], self.english["power.wait.watcher"])
        self.assertTrue(self.answer["statusStopped"]["on"])
        self.assertEqual(self.answer["statusBusy"], 0, "set from a status, the switch called nothing")

    def test_settings_general_holds_the_card_in_the_longest_it_says_at_150_percent_in_korean(self):
        for locale in ("ko", "en"):
            with self.subTest(locale):
                report = self.answer["audit"][locale]
                self.assertEqual(report, "", "\n" + "\n".join(report.splitlines()[:40]))
                self.assertEqual(self.answer["audited"][locale], 3, "the audit laid out every state of the card")

    def test_turning_it_on_asks_first_with_cancel_the_default_so_a_reflex_enter_arms_nothing(self):
        self.assertEqual(self.clicks("offered"), {"on": False, "busy": 0, "asked": 0})
        asked = self.answer["asked"][0]
        self.assertTrue(asked["words"].startswith(self.english["power.confirm"].split("\n")[0]), asked)
        self.assertEqual(asked["enter"], self.english["action.cancel"], "Enter presses Cancel")
        self.assertEqual(asked["escape"], self.english["action.cancel"])
        self.assertEqual(asked["focus"], self.english["action.cancel"], "the keyboard starts on Cancel")
        self.assertFalse(asked["on"], "the switch has not moved while it asks")
        self.assertEqual(self.clicks("cancelled"), {"on": False, "busy": 0, "asked": 1},
                         "Enter pressed Cancel: nothing was sent, and the switch is off")

    def test_at_the_yes_it_moves_on_and_a_refusal_turns_it_back_off_before_the_reason_is_said(self):
        confirm, refusal = self.answer["asked"][1], self.answer["asked"][2]
        self.assertEqual(confirm["pressed"], self.english["power.confirm.affirm"])
        self.assertFalse(confirm["on"])
        self.assertEqual(self.clicks("arming"), {"on": True, "busy": 1, "asked": 2}, "on, with power-arm in flight")
        self.refusal(refusal)
        self.assertFalse(refusal["on"], "back off before the reason is said")
        self.assertEqual(self.clicks("refused"), {"on": False, "busy": 0, "asked": 3})

    def test_turning_it_off_asks_nothing_and_it_moves_at_once(self):
        self.assertEqual(self.clicks("armed"), {"on": True, "busy": 0, "asked": 3})
        self.assertEqual(self.clicks("disarming"), {"on": False, "busy": 1, "asked": 3},
                         "off at once, with power-disarm in flight and nothing asked")
        refusal = self.answer["asked"][3]
        self.refusal(refusal)
        self.assertTrue(refusal["on"], "refused, it is still armed, and the switch is on again before that is said")
        self.assertEqual(self.clicks("stillArmed"), {"on": True, "busy": 0, "asked": 4})

    def test_a_greyed_switch_asks_and_sends_nothing(self):
        self.assertEqual(self.clicks("greyed"), {"on": False, "busy": 0, "asked": 4})

    def test_set_from_a_status_it_follows_what_is_armed_and_fires_nothing(self):
        self.assertEqual(self.clicks("statusOn"), {"on": True, "busy": 0, "asked": 4})
        self.assertEqual(self.clicks("statusOff"), {"on": False, "busy": 0, "asked": 4})
        self.assertEqual(self.clicks("settled"), {"on": False, "busy": 0, "asked": 4})
        self.assertEqual(len(self.answer["asked"]), 4, self.answer["asked"])


if __name__ == "__main__":
    unittest.main()

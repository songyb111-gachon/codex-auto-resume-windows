r"""v0.6.12: the power action's card, the last of Settings > General (gui/SettingsPower.cs).

Arming is an act, not a setting (H2/H3, H14): the card's controls are never editors, so Save, the
unsaved-changes baseline and a reopen never see them, and a Save cannot arm again a Once that was spent.
Turn on... asks first with Cancel the default, so a reflex Enter arms nothing; Turn off asks nothing, as
Pause asks nothing. Its one button joins SetBusy, so it waits its turn like every other. Every word it says
is a catalog key whose fallback is the English sentence.

The source half reads the window with guiscan; the built half compiles the real window, never shown and
asking no bridge (it is audited, so the card asks nothing), and drives the card through the answers the
bridge gives (tests/golden/bridge/power-action.json) - and lays Settings > General out with the card in the
longest it says, at 150 % in Korean and in English (AuditPower; test_gui_layout.py audits every language
at every scaling).
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
                         "where the card is shown, after Turn off and after Turn on")


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
        self.pressed = body("PowerPressed")

    def test_turn_on_asks_with_cancel_the_default(self):
        self.assertIn('Dialog(question, S("power.confirm.affirm", "Turn on"), S("action.cancel", "Cancel"))',
                      self.pressed, "with `away`, Cancel is the accented default (DashboardActions.Dialog)")
        self.assertNotIn("Say(", self.pressed)
        self.assertNotIn("Confirm(", self.pressed)
        asked = self.pressed.index("if (!Dialog(")
        self.assertLess(asked, self.pressed.index('"power-arm"'), "nothing is armed before the yes")

    def test_turn_off_asks_nothing(self):
        disarm = self.pressed.index('"power-disarm"')
        self.assertLess(disarm, self.pressed.index("Dialog("))
        self.assertIn("return;", self.pressed[disarm:self.pressed.index("Dialog(")])

    def test_the_confirmation_is_filled_with_the_cards_own_labels(self):
        for placeholder in ("{action}", "{after}", "{repeat}", "{grace}"):
            with self.subTest(placeholder):
                self.assertIn('.Replace("%s", ChoiceWords(' % placeholder, self.pressed)
        self.assertIn('S("power.confirm.shut_down"', self.pressed)
        self.assertIn('action == "shut_down"', self.pressed)

    def test_it_arms_with_exactly_the_four_values_the_bridge_takes(self):
        keys = re.findall(r'\\"(\w+)\\":', self.pressed)
        self.assertEqual(tuple(keys), poweraction.CHOICE_KEYS)


class BusyTests(unittest.TestCase):
    def test_its_button_joins_set_busy(self):
        self.assertIn("if (powerButton != null) powerButton.Enabled = busy == 0 && powerCanPress;", body("SetBusy"))

    def test_every_time_it_is_drawn_the_button_still_waits_for_a_call_in_flight(self):
        self.assertIn("powerButton.Enabled = busy == 0 && powerCanPress;", body("ShowPower"))
        self.assertIn("busy > 0", body("PowerPressed"))

    def test_nothing_can_be_turned_on_until_windows_answered_what_it_offers(self):
        show = body("ShowPower")
        self.assertIn("powerCanPress = powerOptions != null", show)


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


# The card driven through the bridge's answers, in a window built and never shown; then LayoutAudit at 150 %.
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
$bridge = $BT.GetConstructor($flags, $null, [type[]]@([string]), $null).Invoke([object[]]@($nowhere))
$persistent = $PB.GetConstructor($flags, $null, [type[]]@([string], $BT), $null).Invoke([object[]]@($nowhere, $bridge))
$make = $F.GetConstructor($flags, $null, [type[]]@($PB, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null)
$form = $make.Invoke([object[]]@($persistent.PSObject.BaseObject, (Parse (Read 'strings-en.json')), [Drawing.SystemFonts]::MessageBoxFont))
$F.GetField('auditing', $flags).SetValue($form, $true)
$form.TopLevel = $false
$form.ClientSize = New-Object Drawing.Size 1000, 664
Call 'BuildEditors' @((Parse (Read 'schema.json')), (Parse (Read 'settings.json'))) | Out-Null
$form.PerformLayout()

$names = @('powerAction', 'powerAfter', 'powerRepeat', 'powerGrace', 'powerButton')
$controls = @($names | ForEach-Object { Field $_ })
$editors = Field 'editors'
$out.editors = @($editors.Values | Where-Object { $controls -contains $_ }).Count
$general = (Field 'sections')['general']
$out.last = [object]::ReferenceEquals($general.Controls[$general.Controls.Count - 1], (Field 'powerCard'))
$out.unread = @{ enabled = (Field 'powerButton').Enabled; state = (Field 'powerState').Text; text = (Field 'powerButton').Text }

# What Save would send, before and after every row of the card is changed.
$before = (Call 'EditorValues' @()) | ConvertTo-Json -Compress
(Field 'powerGrace').SelectedIndex = 4
(Field 'powerRepeat').SelectedIndex = 1
(Field 'powerAfter').SelectedIndex = 2
$after = (Call 'EditorValues' @()) | ConvertTo-Json -Compress
$out.saveUntouched = ($before -eq $after)

function State($label) {
  return @{ enabled = (Field 'powerButton').Enabled; text = (Field 'powerButton').Text
            then = @((Field 'powerAction').Items | ForEach-Object { $CH.GetField('Value', $flags).GetValue($_) }); rows = (Field 'powerAfter').Enabled
            state = (Field 'powerState').Text; wait = (Field 'powerWait').Text; unavailable = (Field 'powerUnavailable').Text
            last = (Field 'powerLast').Text; card = (Field 'powerCard').Enabled }
}
$out.states = @{}
foreach ($case in (ConvertFrom-Json (Read 'options.json'))) {
  Call 'ApplyPowerOptions' @((Parse ($case.options | ConvertTo-Json -Depth 8 -Compress))) | Out-Null
  $out.states[$case.case] = State
  if ($case.case -eq 'nothing armed, and every action offered') {
    Call 'SetBusy' @($true) | Out-Null
    $out.busy = (Field 'powerButton').Enabled
    Call 'SetBusy' @($false) | Out-Null
    $out.free = (Field 'powerButton').Enabled
  }
}
# A status with no power_action: its file is gone, so Off, whatever the last answer said.
Call 'ApplyPowerStatus' @((Parse '{"watcher_running": true}')) | Out-Null
$out.statusOff = State
# Armed while the watcher is stopped: nothing happens until it runs.
Call 'ApplyPowerStatus' @((Parse (Read 'status-stopped.json'))) | Out-Null
$out.statusStopped = State
$form.Dispose()

$audit = $F.GetMethod('LayoutAudit', $flags)
$audited = $F.GetField('AuditedPower', $flags)
$out.audit = @{}
$out.audited = @{}
foreach ($locale in @('ko', 'en')) {
  $out.audit[$locale] = [string]$audit.Invoke($null, [object[]]@((Read 'schema.json'), (Read 'settings.json'), (Read ('strings-' + $locale + '.json')), '', [double]1.5))
  $out.audited[$locale] = [int]$audited.GetValue($null)
}
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

    def test_its_controls_are_not_editors_and_save_sends_the_same_whatever_they_show(self):
        self.assertEqual(self.answer["editors"], 0)
        self.assertTrue(self.answer["saveUntouched"])

    def test_it_is_the_last_card_of_general(self):
        self.assertTrue(self.answer["last"])

    def test_before_windows_answered_it_says_off_and_cannot_be_turned_on(self):
        self.assertEqual(self.answer["unread"]["state"], self.english["power.state.off"])
        self.assertEqual(self.answer["unread"]["text"], self.english["power.turn_on"])
        self.assertFalse(self.answer["unread"]["enabled"])

    def test_every_action_offered_can_be_turned_on_and_its_button_waits_while_busy(self):
        state = self.state("nothing armed, and every action offered")
        self.assertTrue(state["enabled"])
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
        self.assertFalse(state["rows"])

    def test_an_administrators_key_greys_the_whole_card_and_says_so(self):
        state = self.state("while an administrator's DisablePowerAction is set")
        self.assertFalse(state["card"])
        self.assertFalse(state["enabled"])
        self.assertEqual(state["wait"], self.english["power.managed"])

    def test_armed_it_shows_the_armed_choices_greyed_and_turns_off(self):
        state = self.state("armed to shut down every time")
        self.assertEqual(state["state"], self.english["power.state.on.shut_down"])
        self.assertEqual(state["text"], self.english["power.turn_off"])
        self.assertTrue(state["enabled"])
        self.assertFalse(state["rows"])

    def test_a_status_without_its_file_says_off_and_a_stopped_watcher_is_said(self):
        self.assertEqual(self.answer["statusOff"]["state"], self.english["power.state.off"])
        self.assertEqual(self.answer["statusOff"]["text"], self.english["power.turn_on"])
        self.assertEqual(self.answer["statusStopped"]["wait"], self.english["power.wait.watcher"])

    def test_settings_general_holds_the_card_in_the_longest_it_says_at_150_percent_in_korean(self):
        for locale in ("ko", "en"):
            with self.subTest(locale):
                report = self.answer["audit"][locale]
                self.assertEqual(report, "", "\n" + "\n".join(report.splitlines()[:40]))
                self.assertEqual(self.answer["audited"][locale], 3, "the audit laid out every state of the card")


if __name__ == "__main__":
    unittest.main()

r"""v0.6.11: Custom... in the Dashboard and in the panel - a value of the person's own beside a drop-down's choices.

The rule is one (ownvalues.py; tests/test_own_values.py holds it). What is held here is that both front ends only
draw it: every drop-down whose schema carries `custom` ends in Custom..., shows a value of the person's own it holds
as one item before it, and edits one in the words the settings store - and neither judges a value itself. The window
asks the bridge's check-setting and takes only what it answers; the panel sends what was typed with Save, and
update_settings answers. So neither front end carries a bound of its own, and each reads the range it says from the
schema.

The window is the real compiled one, its methods called through reflection with the real schema and the English
catalog (WindowTests); the panel runs its own script in Node (PanelTests).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import guiscan
import languages
from codex_auto_resume import l10n, ladder, ownvalues, settings
from codex_auto_resume.mcp import panel as mcpui
from test_mcpui_v064 import NODE, run_page, say, snapshot
from test_own_values import TAKEN

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
DESCRIBED = {entry["name"]: entry for entry in settings.describe()}
OWN_SOURCE = (ROOT / "gui" / "SettingsOwn.cs").read_text(encoding="utf-8")
PANEL = (ROOT / "src" / "codex_auto_resume" / "mcp" / "assets" / "panel.js").read_text(encoding="utf-8")
# The panel's Custom... functions, from its section's heading to the next function outside it.
PANEL_OWN = PANEL[PANEL.index("Custom... (v0.6.11)"):PANEL.index("function segmented(")]

PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$flags = [Reflection.BindingFlags]'NonPublic,Public,Instance,Static'
$json = $assembly.GetType('CodexAutoResume.Json', $true)
$parse = $json.GetMethod('Parse', $flags)
$formType = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
[string]$nowhere = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'car-own-' + [guid]::NewGuid().ToString('N'))
$bridge = $bridgeType.GetConstructors($flags)[0].Invoke([object[]]@([string]$nowhere))
$persistent = $persistentType.GetConstructors($flags)[0].Invoke([object[]]@([string]$nowhere, $bridge))
$schema = $parse.Invoke($null, [object[]]@([string]$env:CAR_SCHEMA))
$byName = @{}
foreach ($entry in $schema) { $byName[[string]$entry['name']] = $entry }
$catalog = $parse.Invoke($null, [object[]]@([string][IO.File]::ReadAllText($env:CAR_STRINGS, [Text.Encoding]::UTF8)))
$ctor = $formType.GetConstructors($flags) | Where-Object { $_.GetParameters().Count -eq 3 }
$form = $ctor.Invoke([object[]]@($persistent, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
$amount = $formType.GetMethod('OwnAmount', $flags)
$label = $formType.GetMethod('OwnLabel', $flags)
$hint = $formType.GetMethod('OwnHint', $flags)
$choiceCombo = $formType.GetMethod('ChoiceCombo', $flags)
$build = $formType.GetMethod('BuildOwnValue', $flags)
$preview = $formType.GetMethod('PreviewWaits', $flags)
$out = @{ amounts = @{}; labels = @{}; hints = @{}; combos = @{}; dialogs = @{}; item = [string]$formType.GetField('OwnItem', $flags).GetValue($null) }
# A drop-down item's stored value, a field the window keeps to itself.
$choiceValue = $assembly.GetType('CodexAutoResume.Choice', $true).GetField('Value', $flags)
function ValueOf($item) { return [string]$choiceValue.GetValue($item) }

foreach ($case in (ConvertFrom-Json $env:CAR_TAKEN).PSObject.Properties) {
    $custom = $byName[$case.Name]['custom']
    $out.amounts[$case.Name] = [double]$amount.Invoke($null, [object[]]@($custom, [string]$case.Value))
    $out.labels[$case.Name] = [string]$label.Invoke($form, [object[]]@($custom, [string]$case.Value))
    $out.hints[$case.Name] = [string]$hint.Invoke($form, [object[]]@($custom))
}

foreach ($case in (ConvertFrom-Json $env:CAR_COMBOS)) {
    [Collections.Generic.Dictionary[string,object]]$current = New-Object 'System.Collections.Generic.Dictionary[string,object]'
    $current.Add([string]$case.name, [string]$case.value)
    $combo = $choiceCombo.Invoke($form, [object[]]@($byName[[string]$case.name], $current, 'choice.'))
    $items = @()
    foreach ($item in $combo.Items) { $items += ,@((ValueOf $item), [string]$item.ToString()) }
    $out.combos[[string]$case.name + '=' + [string]$case.value] = @{ items = $items; selected = $combo.SelectedIndex }
}

# A value taken with Custom... (TakeOwn), and the same value stored when the window opens: one width.
$takeOwn = $formType.GetMethod('TakeOwn', $flags)
$pickType = $assembly.GetType('CodexAutoResume.SettingsForm+OwnPick', $true)
$out.takes = @{}
foreach ($case in (ConvertFrom-Json $env:CAR_TAKES)) {
    $field = $byName[[string]$case.name]
    [Collections.Generic.Dictionary[string,object]]$before = New-Object 'System.Collections.Generic.Dictionary[string,object]'
    $before.Add([string]$case.name, [string]$case.from)
    $combo = $choiceCombo.Invoke($form, [object[]]@($field, $before, 'choice.'))
    $built = [int]$combo.Width
    $state = [Activator]::CreateInstance($pickType, $true)
    $pickType.GetField('Field', $flags).SetValue($state, $field)
    $pickType.GetField('Custom', $flags).SetValue($state, $field['custom'])
    $choices = $pickType.GetField('Choices', $flags).GetValue($state)
    foreach ($choice in $field['choices']) { $choices.Add([string]$choice) | Out-Null }
    $takeOwn.Invoke($form, [object[]]@($combo, $state, [string]$case.take)) | Out-Null
    [Collections.Generic.Dictionary[string,object]]$after = New-Object 'System.Collections.Generic.Dictionary[string,object]'
    $after.Add([string]$case.name, [string]$case.take)
    $reopened = $choiceCombo.Invoke($form, [object[]]@($field, $after, 'choice.'))
    $out.takes[[string]$case.name + '=' + [string]$case.from] = @{ built = $built; taken = [int]$combo.Width;
        reopened = [int]$reopened.Width; shown = [string]$combo.SelectedItem.ToString(); count = [int]$combo.Items.Count;
        reopenedCount = [int]$reopened.Items.Count }
    $combo.Dispose()
    $reopened.Dispose()
}

function Walk($control, $found) {
    foreach ($child in $control.Controls) {
        $found.Add($child) | Out-Null
        Walk $child $found
    }
}
foreach ($case in (ConvertFrom-Json $env:CAR_DIALOGS).PSObject.Properties) {
    $noop = [Action[string]]{ param($v) }
    $dialog = $build.Invoke($form, [object[]]@($byName[$case.Name], [string]$case.Value, $noop))
    $found = New-Object System.Collections.ArrayList
    Walk $dialog $found
    $spins = @($found | Where-Object { $_ -is [Windows.Forms.NumericUpDown] } | ForEach-Object { ,@([double]$_.Value, [double]$_.Minimum, [double]$_.Maximum) })
    $units = @($found | Where-Object { $_.GetType().Name -eq 'SoftCombo' } | ForEach-Object { $c = $_; ,(@($c.Items | ForEach-Object { ValueOf $_ }) + @('=' + (ValueOf $c.SelectedItem))) })
    $checks = @($found | Where-Object { $_ -is [Windows.Forms.CheckBox] } | ForEach-Object { ,@([string]$_.Text, [bool]$_.Checked) })
    $buttons = @($found | Where-Object { $_ -is [Windows.Forms.Button] } | ForEach-Object { [string]$_.Text })
    $out.dialogs[$case.Name] = @{ title = [string]$dialog.Text; spins = $spins; units = $units; checks = $checks; buttons = $buttons }
    $dialog.Dispose()
}

# The retry preview with waits of the person's own, as the window looks it up.
[Collections.Generic.Dictionary[string,Collections.Generic.Dictionary[string,object]]]$limits =
    New-Object 'System.Collections.Generic.Dictionary[string,System.Collections.Generic.Dictionary[string,object]]'
foreach ($entry in $schema) { if ([string]$entry['group'] -eq 'limits') { $limits.Add([string]$entry['name'], $entry) } }
[Collections.Generic.List[string]]$steps = New-Object 'System.Collections.Generic.List[string]'
foreach ($step in (ConvertFrom-Json $env:CAR_STEPS)) { $steps.Add([string]$step) }
$out.preview = @($preview.Invoke($null, [object[]]@($limits, 'custom', $steps)) | ForEach-Object { [double]$_ })
$form.Dispose()
$out | ConvertTo-Json -Depth 6 -Compress
"""

STORED = {name: kept for name, (_sent, kept) in TAKEN.items()}
COMBOS = [{"name": "keep_awake_hours", "value": "m45"}, {"name": "keep_awake_hours", "value": "unlimited"},
          {"name": "quiet_hours_days", "value": "mon,fri"}, {"name": "stall_after", "value": "m30"},
          {"name": "context_guard", "value": "above_300k"}]
DIALOGS = {"keep_awake_hours": "h36", "retry_wait_1": "s90", "quiet_hours_start": "07:05",
           "quiet_hours_days": "mon,fri", "memory_guard_limit": "mb1280", "context_guard": "unlimited"}
STEPS = ["s90", "m45", "h1", "m300", "h5"]
# Taken with Custom... from a drop-down built at `from`: a choice, and a value of the person's own it replaces.
TAKES = [{"name": "quiet_hours_days", "from": "every_day", "take": "mon,tue,wed,thu,sat,sun"},
         {"name": "quiet_hours_days", "from": "mon,fri", "take": "mon,tue,wed,thu,sat,sun"},
         {"name": "keep_awake_hours", "from": "h1", "take": "m10079"}]


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        strings = work / "strings.json"
        # The class speaks English, and gives the process its language back when it ends: the choice is one
        # per process, and a later file that asks what Windows prefers must not be answered "en" by this one.
        cls.addClassCleanup(l10n.set_preference, l10n.preference())
        l10n.set_preference("en")
        strings.write_text(json.dumps({"ok": True, "language": "en", "strings": l10n.catalog("en"), "preference": "en",
                                       "system_language": "en", "endonyms": l10n.offered_endonyms()}),
                           encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, CAR_EXE=str(exe), CAR_SCHEMA=json.dumps(settings.describe()), CAR_STRINGS=str(strings),
                     CAR_TAKEN=json.dumps(STORED), CAR_COMBOS=json.dumps(COMBOS), CAR_DIALOGS=json.dumps(DIALOGS),
                     CAR_STEPS=json.dumps(STEPS), CAR_TAKES=json.dumps(TAKES)))
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.seen = json.loads(result.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_it_reads_a_value_of_the_persons_own_as_the_rule_does(self):
        for name, stored in STORED.items():
            spec = settings.OWN[name]
            with self.subTest(name):
                if spec.kind in (ownvalues.DURATION, ownvalues.COUNT):
                    self.assertEqual(self.seen["amounts"][name], ownvalues.amount(spec, stored))
                else:
                    self.assertEqual(self.seen["amounts"][name], -1, "a time of day or days are said as they are")

    def test_it_says_each_value_and_each_range_in_the_catalogs_words(self):
        labels, hints = self.seen["labels"], self.seen["hints"]
        self.assertEqual(labels["keep_awake_hours"], "45m")
        self.assertEqual(labels["ask_after_sleep_minutes"], "36h")
        self.assertEqual(labels["quiet_hours_days"], "Mon, Fri")
        self.assertEqual(labels["quiet_hours_start"], "07:05")
        self.assertEqual(labels["memory_guard_limit"], "1280 MB")
        self.assertEqual(labels["context_guard"], "Hold above 300,000")
        self.assertEqual(hints["keep_awake_hours"], "From 15m to 7d.")
        self.assertEqual(hints["retry_wait_1"], "From 5s to 2h.")
        self.assertEqual(hints["retry_wait_2"], "From 15m to 6h.")
        self.assertEqual(hints["memory_guard_limit"], "From 128 MB to 16384 MB.")
        self.assertEqual(hints["context_guard"], "From 10,000 to 10,000,000.")
        self.assertEqual(hints["quiet_hours_days"], "Choose at least one day.")

    def test_custom_is_last_and_a_value_of_the_persons_own_is_the_item_before_it(self):
        item = self.seen["item"]
        for case in COMBOS:
            key = case["name"] + "=" + case["value"]
            with self.subTest(key):
                combo = self.seen["combos"][key]
                values = [value for value, _label in combo["items"]]
                choices = [str(choice) for choice in DESCRIBED[case["name"]]["choices"]]
                self.assertEqual(combo["items"][-1], [item, "Custom..."])
                self.assertEqual(values[:len(choices)], choices, "the choices first, in their order")
                self.assertEqual(values[combo["selected"]], case["value"])
                if case["value"] not in choices:
                    self.assertEqual(values[len(choices):], [case["value"], item])
                else:
                    self.assertEqual(len(values), len(choices) + 1)
        unlimited = self.seen["combos"]["keep_awake_hours=unlimited"]
        self.assertEqual(unlimited["items"][-2], ["unlimited", "Unlimited"])

    def test_each_dialog_edits_the_words_and_holds_no_bound_of_its_own(self):
        dialogs = self.seen["dialogs"]
        for name, dialog in dialogs.items():
            with self.subTest(name):
                self.assertEqual(dialog["title"], l10n.catalog("en")["field." + name])
                self.assertEqual(dialog["buttons"], ["Use this value", "Cancel"])
                for _value, low, high in dialog["spins"]:
                    # Wide enough for anything typed: the setting's own range is the bridge's to hold.
                    self.assertEqual(low, 0)
                    self.assertGreaterEqual(high, 99)
        self.assertEqual([spin[0] for spin in dialogs["keep_awake_hours"]["spins"]], [36])
        self.assertEqual(dialogs["keep_awake_hours"]["units"], [["m", "h", "=h"]])
        self.assertEqual([spin[0] for spin in dialogs["retry_wait_1"]["spins"]], [90])
        self.assertEqual(dialogs["retry_wait_1"]["units"], [["s", "m", "h", "=s"]])
        self.assertEqual([spin[0] for spin in dialogs["quiet_hours_start"]["spins"]], [7, 5])
        self.assertEqual([spin[0] for spin in dialogs["memory_guard_limit"]["spins"]], [1280])
        self.assertEqual([spin[0] for spin in dialogs["context_guard"]["spins"]], [10000],
                         "a value that is not one of its own starts at the least")
        self.assertEqual(dialogs["quiet_hours_days"]["checks"],
                         [[day, day in ("Mon", "Fri")] for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")])

    def test_a_value_taken_is_as_wide_as_the_window_opened_with_it(self):
        # The drop-down was measured for its choices when it was built; a value of the person's own taken after that
        # was cut off with an ellipsis until the window was opened again.
        for case in TAKES:
            key = case["name"] + "=" + case["from"]
            with self.subTest(key):
                seen = self.seen["takes"][key]
                self.assertEqual(seen["count"], seen["reopenedCount"], "one item of the person's own")
                self.assertEqual(seen["taken"], seen["reopened"])
        days = self.seen["takes"]["quiet_hours_days=every_day"]
        self.assertEqual(days["shown"], "Mon, Tue, Wed, Thu, Sat, Sun")
        self.assertGreater(days["taken"], days["built"], "longer than any item it was built with")

    def test_the_retry_preview_reads_waits_of_the_persons_own(self):
        values = dict(settings.defaults(), retry_timing="custom",
                      **{field: step for field, step in zip(ladder.STEP_FIELDS, STEPS)})
        self.assertEqual(self.seen["preview"], [float(wait) for wait in ladder.preview(values)])


class SourceTests(unittest.TestCase):
    """Neither front end judges a value: the window takes one only from check-setting's answer."""

    def test_the_window_takes_a_value_only_from_the_bridges_answer(self):
        self.assertEqual(OWN_SOURCE.count('CallAsync("check-setting"'), 1)
        self.assertEqual(re.findall(r"taken\((\w+)\)", OWN_SOURCE), ["stored"])
        self.assertIn('string stored = Ok(reply) ? Str(Map(reply, "result"), "value") : null;', OWN_SOURCE)

    def test_no_bound_of_the_rule_is_written_into_either_front_end(self):
        for spec in settings.OWN.values():
            for bound in (spec.low, spec.high):
                if bound < 1000:
                    continue       # small numbers are everywhere; the large ones are the rule's own
                written = re.compile(r"(?<![0-9])%d(?![0-9])" % bound)
                with self.subTest(bound=bound):
                    self.assertIsNone(written.search(OWN_SOURCE))
                    self.assertIsNone(written.search(PANEL_OWN))

    def test_every_other_drop_down_in_the_window_holds_no_setting_s_value(self):
        # ChoiceCombo is the one place Custom... is added, from the schema. Every other drop-down the window builds is
        # named here with what it holds - and the Statistics page's Period, a span that page counts over, is no setting
        # and is not kept, which the guide says beside Custom... in both languages.
        built = []
        for path in guiscan.sources():
            text = Path(path).read_text(encoding="utf-8")
            for found in re.finditer(r"(\w+) = new SoftCombo\(\)", text):
                method = re.findall(r"\n\s+(?:private|internal|public)[^\n(=;]*?\s(\w+)\(", text[:found.start()])[-1]
                built.append("%s.%s" % (method, found.group(1)))
        self.assertEqual(sorted(built), sorted([
            "ChoiceCombo.combo",            # a setting's choices, and Custom... where the schema offers it
            "LanguageCombo.combo",          # a language, by its endonym
            "BuildContinuation.perReasonCombo",  # which kind of interruption a message is for
            "BuildContinuation.previewReason",   # which kind the preview shows
            "BuildOwnValue.unitCombo",      # the Custom... dialog's own unit
            "BuildStatistics.period",       # how far back the Statistics page counts: no setting, never kept
        ]))
        # main has no Korean documents, and the generated ko branch writes GUIDE.md in Korean.
        english = ("### Values of your own", "**Period** on the Statistics page")
        korean = ("### 직접 정한 값", "통계 페이지의 **기간**")
        guides = [("GUIDE.md",) + (korean if languages.generated_ko_branch() else english)]
        if languages.both_languages():
            guides.append(("GUIDE.ko.md",) + korean)
        for name, heading, words in guides:
            with self.subTest(name):
                guide = (ROOT / "docs" / name).read_text(encoding="utf-8")
                section = guide[guide.index(heading):]
                self.assertIn(words, section[:section.index("\n### ")])

    def test_every_drop_down_with_a_value_of_its_own_is_one_the_schema_says(self):
        self.assertEqual({name for name, entry in DESCRIBED.items() if "custom" in entry}, set(settings.OWN))


def _panel(body, **settings_values):
    return run_page(body, data=snapshot(**settings_values))


SAVE = """
  saveButton().onclick();
  await settle();
"""
SENT = "CALLS.filter(function (c) { return c[0] === 'update_settings'; }).map(function (c) { return c[1]; })"


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelTests(unittest.TestCase):
    def pick(self, name, value):
        return ("var s = byId('car-%s'); s.value = %s; s.fire('change');" % (name, json.dumps(value)))

    def test_custom_is_last_and_a_value_of_the_persons_own_is_the_item_before_it(self):
        observed = _panel("OPEN.limits = true; render();" + say("""['stall_after', 'quiet_hours_days', 'context_guard']
          .map(function (name) { var s = byId('car-' + name);
            return {values: s.options.map(function (o) { return o.value; }), texts: s.options.map(function (o) { return o.textContent; }),
                    value: s.value}; })"""), stall_after="m45", quiet_hours_days="mon,fri", context_guard="above_300k")
        for entry, stored, label in zip(observed, ("m45", "mon,fri", "above_300k"), ("45m", "Mon, Fri", "Hold above 300,000")):
            with self.subTest(stored):
                self.assertEqual(entry["texts"][-1], "Custom...")
                self.assertEqual(entry["values"][-2], stored)
                self.assertEqual(entry["texts"][-2], label)
                self.assertEqual(entry["value"], stored)

    def test_custom_opens_its_editor_at_the_value_held_and_save_sends_the_words(self):
        observed = _panel("OPEN.limits = true; render();" + self.pick("stall_after", "\u0001own") + """
          var editor = byId('car-stall_after').parentNode.parentNode.parentNode.children
            .filter(function (n) { return n.className === 'own'; })[0];
          var shown = !editor.hidden, hint = editor.children[0].textContent;
          var number = editor.all(function (n) { return n.tagName === 'input'; })[0];
          var start = number.value, unit = byId('car-stall_after-unit').value;
          number.value = '36'; number.fire('input');
          var u = byId('car-stall_after-unit'); u.value = 'h'; u.fire('change');
          """ + SAVE + say("{shown: shown, hint: hint, start: start, unit: unit, sent: " + SENT + "}"), stall_after="m30")
        self.assertTrue(observed["shown"])
        self.assertEqual(observed["hint"], "From 5m to 7d.")
        self.assertEqual((observed["start"], observed["unit"]), ("30", "m"))
        self.assertEqual(observed["sent"][-1]["stall_after"], "h36")

    def test_the_page_judges_nothing_and_sends_what_was_typed(self):
        observed = _panel("OPEN.limits = true; render();" + self.pick("stall_after", "\u0001own") + """
          var number = byId('car-stall_after').parentNode.parentNode.parentNode.all(function (n) { return n.tagName === 'input'; })[0];
          number.value = '1'; number.fire('input');
          """ + SAVE + say(SENT))
        self.assertEqual(observed[-1]["stall_after"], "m1", "update_settings refuses it; the page does not")

    def test_days_and_a_time_of_day_are_composed_as_the_settings_spell_them(self):
        observed = _panel("OPEN.limits = true; render();" + self.pick("quiet_hours_days", "\u0001own")
                          + self.pick("quiet_hours_start", "\u0001own") + """
          var days = byId('car-quiet_hours_days').parentNode.parentNode.parentNode.all(function (n) { return n.className === 'check'; });
          var start = days.map(function (d) { return d.checked; });
          days.forEach(function (d, i) { d.checked = i === 1 || i === 5; d.fire('change'); });
          var clock = byId('car-quiet_hours_start').parentNode.parentNode.parentNode.all(function (n) { return n.tagName === 'input'; });
          clock[0].value = '7'; clock[0].fire('input'); clock[1].value = '5'; clock[1].fire('input');
          """ + SAVE + say("{start: start, sent: " + SENT + "}"), quiet_hours_days="weekends")
        self.assertEqual(observed["start"], [False] * 5 + [True, True], "the days a choice names")
        self.assertEqual(observed["sent"][-1]["quiet_hours_days"], "tue,sat")
        self.assertEqual(observed["sent"][-1]["quiet_hours_start"], "07:05")

    def test_a_count_and_a_choice_picked_again_after_custom(self):
        observed = _panel("OPEN.limits = true; render();" + self.pick("context_guard", "\u0001own") + """
          var number = byId('car-context_guard').parentNode.parentNode.parentNode.all(function (n) { return n.tagName === 'input'; })[0];
          number.value = '300000'; number.fire('input');
          """ + SAVE + self.pick("chain_time_ceiling", "\u0001own") + self.pick("chain_time_ceiling", "h3") + SAVE
                          + say(SENT))
        self.assertEqual(observed[0]["context_guard"], "above_300000")
        self.assertEqual(observed[-1]["chain_time_ceiling"], "h3")

    def test_the_retry_preview_reads_waits_of_the_persons_own(self):
        values = {"retry_timing": "custom", **{field: step for field, step in zip(ladder.STEP_FIELDS, STEPS)}}
        observed = _panel("OPEN.limits = true; render();" + say(
            "ROOT_NODE.all(function (n) { return n.tagName === 'p' && n.textContent.indexOf('Waits before') === 0; })"
            ".map(function (n) { return n.textContent; })"), **values)
        self.assertEqual(len(observed), 1)
        self.assertIn("1m 30s · 45m · 1h · 5h · 5h", observed[0])

    def test_a_count_is_grouped_as_the_choices_beside_it_are(self):
        # 300,000 reads as 300 with decimals in German; the choices beside it say 100.000, and so does the Dashboard.
        def spaced(text):
            return re.sub("[\u00a0\u202f]", " ", text)
        for locale in sorted(mcpui.panel_catalogs()):
            catalog = l10n.catalog(locale)
            apart = re.search(r"100(\D+)000", catalog["choice.above_100k"]).group(1)
            observed = _panel("OPEN.limits = true; render();" + say("""(function () {
              var s = byId('car-context_guard');
              var editor = s.parentNode.parentNode.parentNode.children.filter(function (n) { return n.className === 'own'; })[0];
              return {item: s.options[s.options.length - 2].textContent, hint: editor.children[0].textContent}; })()"""),
                              interface_language=str(locale), context_guard="above_300k")
            with self.subTest(str(locale)):
                self.assertEqual(spaced(observed["item"]),
                                 spaced(catalog["own.hold_above"].replace("{n}", "300" + apart + "000")))
                self.assertEqual(spaced(observed["hint"]), spaced(catalog["own.range"].replace(
                    "{low}", "10" + apart + "000").replace("{high}", "10" + apart + "000" + apart + "000")))

    def test_the_retry_preview_promises_no_wait_past_its_bounds(self):
        # Typed and not yet saved: update_settings refuses s1, m1 and h99 at Save, and the watcher keeps the waits
        # it has. The line under the switch says nothing until every wait is one it would keep.
        def typed(name, unit, number):
            return (self.pick(name, "\u0001own") + """
              var editor = byId('car-%s').parentNode.parentNode.parentNode;
              var number = editor.all(function (n) { return n.tagName === 'input'; })[0];
              number.value = %s; number.fire('input');
              var u = byId('car-%s-unit'); u.value = %s; u.fire('change');
              """ % (name, json.dumps(number), name, json.dumps(unit)))
        line = say("ROOT_NODE.all(function (n) { return n.tagName === 'p' && !n.hidden"
                   " && n.textContent.indexOf('Waits before') === 0; }).map(function (n) { return n.textContent; })")
        observed = _panel("OPEN.limits = true; render();" + typed("retry_wait_1", "s", "1") + typed("retry_wait_2", "m", "1")
                          + typed("retry_wait_3", "h", "99") + "var past = " + line.replace("process.stdout.write(", "(")
                          + typed("retry_wait_1", "s", "5") + typed("retry_wait_2", "m", "45")
                          + typed("retry_wait_3", "h", "6") + "var kept = " + line.replace("process.stdout.write(", "(")
                          + say("{past: JSON.parse(past), kept: JSON.parse(kept)}"), retry_timing="custom")
        self.assertEqual(observed["past"], [])
        self.assertEqual(len(observed["kept"]), 1)
        self.assertIn("5s · 45m · 6h · 15m · 15m", observed["kept"][0])
        for name, step in (("retry_wait_1", "s1"), ("retry_wait_2", "m1"), ("retry_wait_3", "h99")):
            with self.subTest(step):
                self.assertIsNone(ownvalues.canonical(settings.OWN[name], step), "the rule refuses it too")


if __name__ == "__main__":
    unittest.main()

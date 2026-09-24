r"""The window's own message box (v0.6.6).

Windows' message box was the last native control this window used: a square grey sheet in the system
font, a title bar that ignores the theme - in dark, a white card in the middle of a dark window - and
buttons that say "Yes" and "No", which name nothing. Fifteen calls raised it. Fourteen are now the
window's own dialog, in the material the rest of the window is made of, and the fifteenth is kept
deliberately (Program.Main, before there is a window, a theme or a catalog).

The dialog is opened for real here: the compiled window is loaded, a dialog is asked for, and while it
is up a timer reads it and presses one of its buttons. So what is checked is what a person would see
and get - where the buttons are, which one Enter and Escape press, and what the answer was - rather
than the shape of the code that builds it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import guiscan
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
EXE = ROOT / "build" / "CodexAutoResumeSettings.exe"
STRINGS = ROOT / "src" / "codex_auto_resume" / "locales" / "en.json"

QUESTION = 'Stop recovering "Refactor the payment retries"? A continuation already running is not stopped.'
NOTICE = "Diagnostics saved."
# What a refusal can carry under its translated sentence: whatever the local service raised.
LONG = "That could not be done." + "\r\n\r\n" + "\r\n".join(
    "  at CodexAutoResume.Bridge.Call(String command, String argument) line %d" % line
    for line in range(1, 61))

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$formType = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$assembly.GetType('CodexAutoResume.Tokens', $true).GetMethod('Adopt', $static).Invoke($null, [object[]]@($false))
$utf8 = New-Object Text.UTF8Encoding $false
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$catalog = $parse.Invoke($null, [object[]]@([string][IO.File]::ReadAllText($env:CAR_STRINGS, $utf8)))
$nowhere = [string](Join-Path $env:CAR_WORK 'nowhere')
$once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
$bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
$three = @($formType.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$window = $three.Invoke([object[]]@($bridge, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
$window.StartPosition = 'Manual'
$window.Location = New-Object Drawing.Point -4000, -4000
$window.Show()
[Windows.Forms.Application]::DoEvents()
$say = @($formType.GetMethods($instance) | Where-Object { $_.Name -eq 'Say' })[0]

# The dialog holds the thread in ShowDialog, so a timer looks at it and presses a button for us.
$script:seen = $null
function Ask([string]$text, $affirm, [string]$press) {
    $script:seen = $null
    $timer = New-Object Windows.Forms.Timer
    $timer.Interval = 400
    $timer.Add_Tick({
        $timer.Stop()
        $dialog = [Windows.Forms.Form]::ActiveForm
        if ($dialog -eq $null -or [object]::ReferenceEquals($dialog, $window)) { return }
        try {
        $row = $null
        $look = @{ words = ''; buttons = @(); client = @($dialog.ClientSize.Width, $dialog.ClientSize.Height)
                   title = [string]$dialog.Text; box = [bool]$dialog.ShowInTaskbar }
        foreach ($c in $dialog.Controls) {
            if ($c -is [Windows.Forms.FlowLayoutPanel]) { $row = $c }
            foreach ($k in $c.Controls) {
                if ($k -is [Windows.Forms.Label]) { $look.words = [string]$k.Text
                                                    $look.wordsAt = @($k.Bounds.Left, $k.Bounds.Right) }
                if ($k.GetType().Name -eq 'SoftTextArea') {
                    $box = $k.GetType().GetField('Box', $instance).GetValue($k)
                    $look.words = [string]$box.Text
                    $look.wordsAt = @($k.Bounds.Left, $k.Bounds.Right)
                    $look.well = $true
                    $look.readonly = [bool]$box.ReadOnly
                }
            }
        }
        foreach ($k in $row.Controls) {
            $look.buttons += ,@([string]$k.Text, [int]$k.Bounds.Left, [int]$k.Bounds.Right,
                                [bool]$k.GetType().GetProperty('Primary', $instance).GetValue($k, $null))
        }
        $look.accept = [string]$dialog.AcceptButton.Text
        $look.cancel = [string]$dialog.CancelButton.Text
        $look.at = @($dialog.Bounds.Left, $dialog.Bounds.Top, $dialog.Bounds.Width, $dialog.Bounds.Height)
        $look.owner = @($window.Bounds.Left, $window.Bounds.Top, $window.Bounds.Width, $window.Bounds.Height)
        $look.start = [string]$dialog.StartPosition
        $work = [Windows.Forms.Screen]::FromControl($dialog).WorkingArea
        $look.work = @($work.Left, $work.Top, $work.Width, $work.Height)
        $look.owned = [bool]($dialog.Owner -ne $null -and [object]::ReferenceEquals($dialog.Owner, $window))
        $look.modal = [bool]$dialog.Modal
        $focused = $dialog.ActiveControl
        $look.focus = if ($focused -eq $null) { '' } else { [string]$focused.Text }
        $look.selected = if ($look.well) { [int]$box.SelectionLength } else { -1 }
        $script:seen = $look
        $target = if ($press -eq 'accept') { $dialog.AcceptButton } else { $dialog.CancelButton }
        $target.PerformClick()
        } catch { $script:seen = @{ failed = [string]$_ } }
        if (-not $dialog.IsDisposed) { $dialog.Close() }
    })
    $timer.Start()
    $answered = $say.Invoke($window, [object[]]@($text, $affirm))
    $out = $script:seen
    if ($out -eq $null) { throw "the dialog was never seen" }
    if ($out.ContainsKey('failed')) { throw $out.failed }
    $out.answer = [bool]$answered
    return $out
}

$result = @{}
$result.taken = Ask $env:CAR_QUESTION 'Cancel' 'accept'
$result.left = Ask $env:CAR_QUESTION 'Cancel' 'cancel'
$result.named = Ask $env:CAR_QUESTION 'Clear history' 'accept'
$result.notice = Ask $env:CAR_NOTICE $null 'accept'
$result.long = Ask $env:CAR_LONG $null 'accept'
$result.work = @([Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Width,
                 [Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Height)
$window.Close()
$result | ConvertTo-Json -Depth 8 -Compress
"""


@unittest.skipUnless(os.name == "nt", "the window is Windows'")
@unittest.skipUnless(EXE.is_file(), "build the window first: build/make_gui.ps1")
class DialogTests(unittest.TestCase):
    answer = None

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as work:
            environment = dict(os.environ)
            environment.update({"CAR_EXE": str(EXE), "CAR_STRINGS": str(STRINGS), "CAR_WORK": work,
                                "CAR_QUESTION": QUESTION, "CAR_NOTICE": NOTICE, "CAR_LONG": LONG})
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass",
                                   "-Command", PROBE],
                                  capture_output=True, text=True, timeout=300, env=environment)
        if done.returncode != 0:
            raise AssertionError(done.stdout + done.stderr)
        cls.answer = json.loads(done.stdout.strip().splitlines()[-1])
        cls.window = guiscan.window()

    def test_a_question_is_answered_by_the_button_that_names_the_action(self):
        taken, left = self.answer["taken"], self.answer["left"]
        self.assertTrue(taken["answer"], "the action's own button says yes")
        self.assertFalse(left["answer"], "the other one says no, and so does Escape")
        self.assertEqual(taken["accept"], "Cancel", "the words the caller already had")
        self.assertEqual(self.answer["named"]["accept"], "Clear history")

    def test_the_other_button_says_cancel_unless_that_is_the_action(self):
        """"Yes" and "No" name nothing, so the affirming button says what will happen and the other one
        says Cancel. Where the action itself is called Cancel - the Pending page's own button - the two
        would be the same word, and the dismissal becomes Close instead."""
        self.assertEqual(self.answer["named"]["cancel"], "Cancel")
        self.assertEqual(self.answer["taken"]["cancel"], "Close", "Cancel beside Cancel names nothing either")

    def test_a_notice_has_one_button_and_it_closes(self):
        notice = self.answer["notice"]
        self.assertEqual([button[0] for button in notice["buttons"]], ["Close"])
        self.assertEqual(notice["accept"], "Close")
        self.assertEqual(notice["cancel"], "Close", "Escape closes it too")
        self.assertFalse(notice["answer"], "a notice answers nothing")

    def test_the_action_is_the_rightmost_button_and_the_only_accent_one(self):
        buttons = self.answer["named"]["buttons"]
        self.assertEqual([button[0] for button in buttons], ["Clear history", "Cancel"])
        self.assertGreater(buttons[0][1], buttons[1][2], "the action is to the right of the dismissal")
        self.assertEqual([button[3] for button in buttons], [True, False], "one accent button, and it acts")

    def test_the_sentence_and_the_buttons_keep_the_same_inset(self):
        """A right-to-left flow lays out from its width less both sides of its padding, so a row padded
        evenly sits a padding further in than the text above it. All of the row's horizontal padding is
        on the right for that reason, and this is what says so."""
        for name in ("taken", "named", "notice", "long"):
            look = self.answer[name]
            with self.subTest(name):
                left, right = look["wordsAt"]
                self.assertEqual(left, look["client"][0] - right, "the sentence is evenly inset")
                self.assertEqual(max(button[2] for button in look["buttons"]), right,
                                 "and the action's button ends where the sentence does")

    def test_a_sentence_too_tall_for_a_dialog_goes_in_a_well_and_scrolls_there(self):
        """A refusal carries the local service's own sentence under the translated one, and that is
        whatever was raised - a path, a stack, a page of it. Sixty lines of it would make a dialog
        taller than the screen, so past a bound the words go into the window's own well, read-only,
        and scroll there on the window's own bar."""
        short, long = self.answer["notice"], self.answer["long"]
        self.assertNotIn("well", short, "a sentence that fits is simply drawn")
        self.assertTrue(long.get("well"), "sixty lines are not")
        self.assertTrue(long["readonly"], "and they cannot be edited")
        self.assertEqual(long["selected"], 0,
                         "a text box answers the focus by selecting everything it holds; this one does not")
        self.assertEqual(long["focus"], "Close",
                         "and the keyboard starts on the button, not on the words")
        self.assertEqual(long["words"].count("\n"), LONG.count("\n"),
                         "all of them are there")
        self.assertLessEqual(long["at"][3], self.answer["work"][1], "and the dialog fits the screen")

    def test_it_is_a_dialog_of_this_window_rather_than_a_second_window(self):
        for name in ("taken", "notice"):
            with self.subTest(name):
                self.assertEqual(self.answer[name]["title"], "Codex Auto Resume")
                self.assertFalse(self.answer[name]["box"], "it is not a second button on the taskbar")
                self.assertTrue(self.answer[name]["owned"], "it belongs to the window that asked")
                self.assertTrue(self.answer[name]["modal"], "and nothing else in the window can be touched")

    def test_it_opens_in_the_middle_of_the_window_that_asked(self):
        """Where a dialog opens is part of what it says. It is centred on the window it belongs to -
        where the person is already looking, and where every modal dialog on this system opens -
        rather than beside the button that raised it, which is what a flyout does and which would
        make the same question appear in three places depending on which page asked it.

        The window this probe builds is held off the desktop so nothing flashes past while the suite
        runs, and Windows will not place a dialog off the desktop: it brings it back onto the screen,
        which is the right thing and is checked here as well. So what is held is that the dialog asks
        for its owner's middle and lands somewhere a person can see."""
        for name in ("taken", "named", "notice"):
            look = self.answer[name]
            with self.subTest(name):
                self.assertEqual(look["start"], "CenterParent")
                left, top, width, height = look["at"]
                work = look["work"]
                self.assertGreaterEqual(left, work[0] - 1)
                self.assertGreaterEqual(top, work[1] - 1)
                self.assertLessEqual(left + width, work[0] + work[2] + 1, "not past the screen's edge")
                self.assertLessEqual(top + height, work[1] + work[3] + 1, "and never under the taskbar")

    def test_no_message_box_is_left_in_the_window(self):
        # One in the whole window, and on purpose: it is raised before there is a window, a
        # theme or a catalog to ask the question with. Counted over both halves of the window
        # rather than over the two files this was written for, so a MessageBox added to any
        # of the nine others is this test failing rather than this test not looking.
        self.assertEqual(self.window.count("MessageBox.Show"), 1,
                         "every other question the window asks is drawn by the window")
        at = self.window.index("MessageBox.Show")
        self.assertIn("not installed in this location", self.window[at:at + 200])
        self.assertIn("no window yet", self.window[at - 400:at], "and it says why it is still Windows'")


# Every label the window can put on the button that acts. `action.failed` is a sentence, not a
# button, and is deliberately not among them.
AFFIRMS = ("action.cancel", "action.cancel_all", "action.reset_budget", "action.thread_off",
           "action.thread_on", "action.resume", "action.clear_history", "action.stop_watcher",
           "action.repair", "action.install", "action.restore")

FIT_PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$formType = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$assembly.GetType('CodexAutoResume.Tokens', $true).GetMethod('Adopt', $static).Invoke($null, [object[]]@($false))
$utf8 = New-Object Text.UTF8Encoding $false
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$cases = $parse.Invoke($null, [object[]]@([string][IO.File]::ReadAllText($env:CAR_CASES, $utf8)))
$nowhere = [string](Join-Path $env:CAR_WORK 'nowhere')
$once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
$bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
$three = @($formType.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
$result = @{}
foreach ($tag in $cases.Keys) {
    $case = $cases[$tag]
    # The window takes a strings *reply*, not a bare catalog: handed the catalog itself it finds
    # no key and falls back to the English written beside each call, which would have made this a
    # nine-language test of English.
    $words = [string][IO.File]::ReadAllText([string]$case['catalog'], $utf8)
    $catalog = $parse.Invoke($null, [object[]]@('{"ok":true,"strings":' + $words + '}'))
    $window = $three.Invoke([object[]]@($bridge, $catalog, [Drawing.SystemFonts]::MessageBoxFont))
    $window.StartPosition = 'Manual'
    $window.Location = New-Object Drawing.Point -4000, -4000
    $window.Show()
    [Windows.Forms.Application]::DoEvents()
    $say = @($formType.GetMethods($instance) | Where-Object { $_.Name -eq 'Say' })[0]
    $script:look = $null
    $timer = New-Object Windows.Forms.Timer
    $timer.Interval = 350
    $timer.Add_Tick({
        $timer.Stop()
        $dialog = [Windows.Forms.Form]::ActiveForm
        if ($dialog -eq $null -or [object]::ReferenceEquals($dialog, $window)) { return }
        try {
            $seen = @{ client = @($dialog.ClientSize.Width, $dialog.ClientSize.Height); buttons = @() }
            foreach ($c in $dialog.Controls) {
                foreach ($k in $c.Controls) {
                    if ($k -is [Windows.Forms.Label]) {
                        $flags = [Windows.Forms.TextFormatFlags]::WordBreak -bor [Windows.Forms.TextFormatFlags]::NoPrefix
                        $needs = [Windows.Forms.TextRenderer]::MeasureText($k.Text, $k.Font,
                                 (New-Object Drawing.Size $k.Width, 0), $flags)
                        $seen.words = @($k.Bounds.Left, $k.Bounds.Top, $k.Width, $k.Height)
                        $seen.needs = @($needs.Width, $needs.Height)
                    }
                    if ($k.GetType().Name -eq 'SoftTextArea') { $seen.well = $true }
                }
                if ($c -is [Windows.Forms.FlowLayoutPanel]) {
                    foreach ($k in $c.Controls) {
                        $seen.buttons += ,@([string]$k.Text, [int]($c.Left + $k.Bounds.Left),
                                            [int]($c.Left + $k.Bounds.Right), [int]$k.Bounds.Top, [int]$k.Bounds.Bottom)
                    }
                    $seen.row = @($c.Left, $c.Top, $c.Width, $c.Height)
                }
            }
            $script:look = $seen
        } catch { $script:look = @{ failed = [string]$_ } }
        if (-not $dialog.IsDisposed) { $dialog.Close() }
    })
    $timer.Start()
    $null = $say.Invoke($window, [object[]]@([string]$case['text'], [string]$case['affirm']))
    if ($script:look -eq $null) { throw "no dialog for $tag" }
    if ($script:look.ContainsKey('failed')) { throw $script:look.failed }
    $result[$tag] = $script:look
    $window.Close()
}
$result | ConvertTo-Json -Depth 8 -Compress
"""


@unittest.skipUnless(os.name == "nt", "the window is Windows'")
@unittest.skipUnless(EXE.is_file(), "build the window first: build/make_gui.ps1")
class DialogFitTests(unittest.TestCase):
    """The dialog holds the longest thing every language can put in it.

    The window's own pages are audited in nine languages at five scalings; the dialog is a form of
    its own and was in none of that. What it is handed is not a fixed string either - it is whatever
    the catalog says, and German's update question is 279 characters where Simplified Chinese's is
    82. So this raises it, in each language, with the longest question that language has and the
    longest label the window can put on the button that acts, and looks at whether the words fit and
    whether the buttons are still on one line.
    """

    answer = None
    cases = None

    @classmethod
    def setUpClass(cls):
        catalogs = ROOT / "src" / "codex_auto_resume" / "locales"
        cases = {}
        for path in sorted(catalogs.glob("*.json")):
            catalog = json.loads(path.read_text(encoding="utf-8"))
            questions = [value for key, value in catalog.items()
                         if key.startswith("confirm.") or key == "settings.confirm_restore"]
            labels = [catalog[key] for key in AFFIRMS if key in catalog]
            if not questions or not labels:
                continue
            cases[path.stem] = {"catalog": str(path),
                                "text": max(questions, key=len).replace("{name}", "example-project")
                                                              .replace("{latest}", "0.6.7"),
                                "affirm": max(labels, key=len)}
        cls.cases = cases
        with tempfile.TemporaryDirectory() as work:
            written = Path(work) / "cases.json"
            written.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
            environment = dict(os.environ)
            environment.update({"CAR_EXE": str(EXE), "CAR_CASES": str(written), "CAR_WORK": work})
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass",
                                   "-Command", FIT_PROBE],
                                  capture_output=True, text=True, timeout=600, env=environment)
        if done.returncode != 0:
            raise AssertionError(done.stdout + done.stderr)
        cls.answer = json.loads(done.stdout.strip().splitlines()[-1])

    def test_every_language_gets_a_dialog_for_its_longest_question(self):
        self.assertEqual(sorted(self.answer), sorted(self.cases), "a language raised no dialog")

    def test_the_words_are_never_cut_off(self):
        for tag, look in sorted(self.answer.items()):
            with self.subTest(tag):
                if look.get("well"):
                    continue                    # too tall to draw, so it scrolls instead: covered above
                width, height = look["words"][2], look["words"][3]
                needs = look["needs"]
                self.assertLessEqual(needs[0], width, "%s: the words are wider than the room" % tag)
                self.assertLessEqual(needs[1], height, "%s: the words are taller than the room" % tag)

    def test_the_buttons_stay_on_one_line_inside_the_dialog(self):
        """The row wraps when what it holds will not fit, which is the right thing for it to do and
        the wrong thing to see: two buttons above one another, with the dialog sized for one row."""
        for tag, look in sorted(self.answer.items()):
            buttons = look["buttons"]
            with self.subTest(tag):
                self.assertEqual(len(buttons), 2, "%s: a question has two buttons" % tag)
                self.assertEqual(buttons[0][3], buttons[1][3], "%s: the buttons are on two lines" % tag)
                self.assertLessEqual(max(b[2] for b in buttons), look["client"][0],
                                     "%s: a button runs past the dialog's edge" % tag)
                self.assertGreaterEqual(min(b[1] for b in buttons), 0,
                                        "%s: a button starts before the dialog's edge" % tag)
                self.assertLessEqual(max(b[4] for b in buttons), look["row"][3],
                                     "%s: a button runs past its row" % tag)


if __name__ == "__main__":
    unittest.main()

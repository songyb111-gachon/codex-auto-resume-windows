"""v0.6.19: while the long-lived bridge is given up, an advanced call says so and runs nothing; a click reopens it.

The one-shot form never reaches the edition (STANDARDS K3), so while the window had given the long-lived bridge up -
five minutes after three failures - every call of the Advanced features page and the pages built on it went to the
one-shot form and came back as an unknown command: nothing said why. Now those calls go through
PersistentBridge.CallAdvanced. A read while given up is answered at once with the reconnecting code, and nothing is
started; an action - a person's click - opens the long-lived bridge again at once and is carried if it opens; a call
the long-lived bridge failed on is answered with the reconnecting code and never asked again, since it may already
have been carried out. The page says it in one note every page shares (note.reconnecting). The core's own calls, the
only ones the standard edition makes, still fall back on the one-shot form as before.

The built half compiles the real window and runs its bridge against a stand-in python.exe this test compiles. Its
long-lived form answers every line (CAR_FAKE_MODE ok) or reads one line and ends without answering (drop: the call
may have been carried out); every line it reads and every one-shot call is written down. Nothing of the real
installation is read, nothing is shown.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from codex_auto_resume import l10n
from test_gui_v0611_access import CSC, NO_WINDOW, POWERSHELL, compile_window, run_probe

ROOT = Path(__file__).resolve().parents[1]

FAKE = r"""
using System;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading;
static class Fake {
    static void Say(string text) {
        string said = Environment.GetEnvironmentVariable("CAR_FAKE_LOG");
        for (int i = 0; i < 50; i++) {
            try { File.AppendAllText(said, text + "\n"); return; }
            catch (IOException) { Thread.Sleep(20); }
        }
    }
    static int Main(string[] args) {
        string mode = Environment.GetEnvironmentVariable("CAR_FAKE_MODE") ?? "ok";
        if (Array.IndexOf(args, "serve") < 0) {
            Say("once " + string.Join(" ", args, 3, args.Length - 3));
            if (Array.IndexOf(args, "-") >= 0) Console.In.ReadToEnd();
            Console.Out.Write("{\"ok\":true,\"by\":\"once\"}");
            return 0;
        }
        string line;
        while ((line = Console.In.ReadLine()) != null) {
            string id = Regex.Match(line, "\"id\":(\\d+)").Groups[1].Value;
            string name = Regex.Match(line, "\"command\":\"([a-z_-]+)\"").Groups[1].Value;
            Say("serve " + name);
            if (mode == "drop") return 0;
            Console.Out.Write("{\"id\":" + id + ",\"reply\":{\"ok\":true,\"by\":\"serve\"}}\n");
            Console.Out.Flush();
        }
        return 0;
    }
}
"""

PROBE = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
    $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
    $flags = [Reflection.BindingFlags]'Instance,Static,NonPublic,Public'
    $BT = $assembly.GetType('CodexAutoResume.Bridge', $true)
    $PB = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
    $work = [string]$env:CAR_WORK
    $home_ = [string]$env:CAR_HOME
    $log = [string]$env:CAR_FAKE_LOG
    $utf8 = New-Object Text.UTF8Encoding $false
    $PB.GetField('RetryMilliseconds', $flags).SetValue($null, [int]600000)
    $advanced = $PB.GetMethod('CallAdvanced', $flags)
    if ($null -eq $advanced) { throw 'PersistentBridge has no CallAdvanced' }
    $call = $PB.GetMethod('Call', $flags, $null, [type[]]@([string], [string]), $null)
    function New-Bridge {
        $script:oneShot = $BT.GetConstructors($flags)[0].Invoke([object[]]@($home_))
        $script:bridge = $PB.GetConstructors($flags)[0].Invoke([object[]]@($home_, $script:oneShot))
    }
    function Lines { if (Test-Path $log) { return ,@([IO.File]::ReadAllLines($log)) } else { return ,@() } }
    function Give-Up {
        $PB.GetField('failures', $flags).SetValue($script:bridge, [int]3)
        $PB.GetField('givenUp', $flags).GetValue($script:bridge).Restart()
    }
    function Answer($reply) { return @{ ok = [bool]$reply['ok']; code = [string]$reply['error_code']; by = [string]$reply['by'] } }
    $out = @{}
    # 1. An action the long-lived bridge read and never answered: it may have run, so it is said and never asked again.
    $env:CAR_FAKE_MODE = 'drop'
    New-Bridge
    $out.dropped = Answer ($advanced.Invoke($script:bridge, [object[]]@('advanced-chat-send', '{"text":"hi"}', $true)))
    $out.afterDrop = Lines
    # 2. Given up: a read starts nothing and says so.
    Give-Up
    $out.read = Answer ($advanced.Invoke($script:bridge, [object[]]@('advanced-list', '{}', $false)))
    $out.afterRead = Lines
    $out.stillGivenUp = [bool]$PB.GetProperty('GivenUp', $flags).GetValue($script:bridge)
    $PB.GetMethod('Stop', $flags).Invoke($script:bridge, @())
    # 3. Given up, and a click: the long-lived bridge is opened again at once and carries it.
    $env:CAR_FAKE_MODE = 'ok'
    New-Bridge
    Give-Up
    $out.click = Answer ($advanced.Invoke($script:bridge, [object[]]@('advanced-keep-on', '{}', $true)))
    $out.reopened = -not [bool]$PB.GetProperty('GivenUp', $flags).GetValue($script:bridge)
    $out.afterClick = Lines
    # 4. The core's own calls, given up, go to the one-shot form as before.
    Give-Up
    $out.core = Answer ($call.Invoke($script:bridge, [object[]]@('status', $null)))
    $out.afterCore = Lines
    $PB.GetMethod('Stop', $flags).Invoke($script:bridge, @())
    [IO.File]::WriteAllText((Join-Path $work 'result.json'), (ConvertTo-Json $out -Compress -Depth 4), $utf8)
    exit 0
} catch {
    [IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'probe.failed'), $_.Exception.ToString())
    exit 3
}
"""


@unittest.skipUnless(CSC.is_file(), "the window is compiled with the in-box C# compiler")
class ReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name).resolve()
        cls.home = work / "home"
        (cls.home / "runtime").mkdir(parents=True)
        (cls.home / "app" / "src").mkdir(parents=True)
        exe = compile_window(work)
        source = work / "fake.cs"
        source.write_text(FAKE, encoding="utf-8")
        for name in ("python.exe", "pythonw.exe"):
            subprocess.run([str(CSC), "/nologo", "/target:exe", "/out:" + str(cls.home / "runtime" / name), str(source)],
                           check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
        cls.failed = work / "probe.failed"
        try:
            cls.answer = run_probe(PROBE, work, 300, CAR_EXE=str(exe), CAR_HOME=str(cls.home),
                                   CAR_FAKE_LOG=str(work / "said.txt"))
        except Exception:
            cls.answer = {}

    @classmethod
    def tearDownClass(cls):
        script = ("Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -and "
                  "$_.Path.StartsWith($env:CAR_HOME, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force")
        subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       timeout=120, creationflags=NO_WINDOW, env=dict(os.environ, CAR_HOME=str(cls.home)))
        cls.folder.cleanup()

    def setUp(self):
        failed = self.failed.read_text(encoding="utf-8") if self.failed.is_file() else ""
        self.assertTrue(self.answer, failed[-3000:] or "the probe wrote no result")

    def test_an_action_that_may_have_run_is_said_and_never_sent_twice(self):
        self.assertEqual(self.answer["dropped"], {"ok": False, "code": "reconnecting", "by": ""})
        self.assertEqual(self.answer["afterDrop"], ["serve advanced-chat-send"], "read once, and no one-shot call")

    def test_while_given_up_a_read_says_so_and_runs_nothing(self):
        self.assertEqual(self.answer["read"]["code"], "reconnecting")
        self.assertEqual(self.answer["afterRead"], self.answer["afterDrop"], "nothing was started for the read")
        self.assertTrue(self.answer["stillGivenUp"])

    def test_a_click_opens_the_long_lived_bridge_again_and_carries_the_action(self):
        self.assertEqual(self.answer["click"], {"ok": True, "code": "", "by": "serve"})
        self.assertTrue(self.answer["reopened"])
        self.assertEqual(self.answer["afterClick"][len(self.answer["afterRead"]):], ["serve advanced-keep-on"])

    def test_no_advanced_call_ever_goes_to_the_one_shot_form(self):
        self.assertEqual([line for line in self.answer["afterCore"] if line.startswith("once advanced")], [])

    def test_the_cores_own_calls_still_fall_back_on_the_one_shot_form(self):
        self.assertEqual(self.answer["core"]["by"], "once")
        self.assertEqual(self.answer["afterCore"][-1], "once status")


class PageTests(unittest.TestCase):
    """The advanced edition's page, which this lane does not compile: what it asks and what it says, in its source."""

    def setUp(self):
        self.page = (ROOT / "advanced" / "gui" / "AdvancedPage.cs").read_text(encoding="utf-8")

    def test_every_advanced_call_goes_through_call_advanced(self):
        self.assertIn("bridge.CallAdvanced(command, argument, action)", self.page)
        self.assertNotIn("bridge.Call(", self.page)

    def test_the_note_is_one_string_in_every_language(self):
        english = l10n.catalog("en")["note.reconnecting"]
        self.assertIn('S("note.reconnecting", "%s")' % english, self.page)
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertTrue(l10n.catalog(locale).get("note.reconnecting"))


if __name__ == "__main__":
    unittest.main()

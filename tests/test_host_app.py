"""v0.6.17: the Dashboard, the setup programs and install.ps1 inside another app's private view of Windows.

A process descended from an MSIX app - the Codex app, Claude desktop - writes HKCU and %APPDATA% into that app's
private view, which Windows never reads. The one signal that held is a live ancestor with package identity
(gui/HostApp.cs, and install.ps1's Find-PackagedAncestor); the way out is the desktop shell or WMI, with a mark that
stops a second relaunch. Here:

* the decision, over process tables of the tests' own - the C# one compiled with a small harness, the PowerShell
  one lifted out of install.ps1 - including how far a walk goes before it stops;
* install.ps1's gate with its process table and its launcher stubbed: it relaunches inside, carries on outside, the
  mark stops a second relaunch, and a relaunch that fails is said once;
* the wiring, by guiscan's blocks: the Dashboard's Main and the setup programs' Started ask before the bridge and the
  window and pass the mark on; Repair, an update's install and Install another version refuse while stuck inside;
* item 3a: the Dashboard started after Finish goes through the routine that brings it to the front.

Nothing here relaunches anything or asks the live process tree a question whose answer depends on where the test
runs: on this laptop the tests run inside Claude, on CI inside nothing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_BUILD = str(ROOT / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)

import guiscan  # noqa: E402
import make_setup  # noqa: E402
from test_installer import VOICE, block, run_probe  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOST = ROOT / "gui" / "HostApp.cs"
INSTALL = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
SETUP = (ROOT / make_setup.SOURCE).read_text(encoding="utf-8")
SETUP_WINDOW = (ROOT / make_setup.WINDOW).read_text(encoding="utf-8")
LOCALES = ROOT / "src" / "codex_auto_resume" / "locales"
CODEX = "OpenAI.Codex_2p2nqsd0c76g0"

# The harness: HostApp.Decide over each table, and how many times it looked a process up there. Compiled with
# gui/HostApp.cs alone, into an executable of the test's own; nothing in the shipped programs is a test's.
HARNESS = r"""
using System;
using System.Collections;
using System.Collections.Generic;
using CodexAutoResume;

namespace HostAppProbe
{
    // A table that counts its lookups, so a walk that went on past where it should have stopped is seen.
    sealed class Counting : IDictionary<int, HostApp.Row>
    {
        readonly Dictionary<int, HostApp.Row> rows = new Dictionary<int, HostApp.Row>();
        internal int Lookups;
        public bool TryGetValue(int key, out HostApp.Row value) { Lookups++; return rows.TryGetValue(key, out value); }
        public HostApp.Row this[int key] { get { Lookups++; return rows[key]; } set { rows[key] = value; } }
        public void Add(int key, HostApp.Row value) { rows.Add(key, value); }
        public bool ContainsKey(int key) { Lookups++; return rows.ContainsKey(key); }
        public bool Remove(int key) { return rows.Remove(key); }
        public ICollection<int> Keys { get { return rows.Keys; } }
        public ICollection<HostApp.Row> Values { get { return rows.Values; } }
        public void Add(KeyValuePair<int, HostApp.Row> item) { rows.Add(item.Key, item.Value); }
        public void Clear() { rows.Clear(); }
        public bool Contains(KeyValuePair<int, HostApp.Row> item) { return rows.ContainsKey(item.Key); }
        public void CopyTo(KeyValuePair<int, HostApp.Row>[] array, int index) { ((ICollection<KeyValuePair<int, HostApp.Row>>)rows).CopyTo(array, index); }
        public bool Remove(KeyValuePair<int, HostApp.Row> item) { return rows.Remove(item.Key); }
        public int Count { get { return rows.Count; } }
        public bool IsReadOnly { get { return false; } }
        public IEnumerator<KeyValuePair<int, HostApp.Row>> GetEnumerator() { return rows.GetEnumerator(); }
        IEnumerator IEnumerable.GetEnumerator() { return rows.GetEnumerator(); }
    }

    static class Program
    {
        static string Quote(string text) { return text == null ? "null" : "\"" + text.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\""; }

        static void Case(string name, int self, params object[] rows)
        {
            var table = new Counting();
            for (int i = 0; i < rows.Length; i += 4)
                table.Add((int)rows[i], new HostApp.Row((int)rows[i + 1], (long)rows[i + 2], (string)rows[i + 3]));
            string found = HostApp.Decide(self, table);
            Console.WriteLine("{\"case\": " + Quote(name) + ", \"found\": " + Quote(found) + ", \"lookups\": " + table.Lookups + "}");
        }

        static int Main()
        {
            // pid, parent, created, package
            Case("packaged ancestor", 100, 100, 90, 50L, null, 90, 80, 40L, null, 80, 4, 30L, "OpenAI.Codex_2p2nqsd0c76g0");
            Case("own package", 100, 100, 90, 50L, "Claude_pzs8sxrjxfjjc", 90, 4, 40L, null);
            Case("no package", 100, 100, 90, 50L, null, 90, 80, 40L, null, 80, 4, 30L, null);
            Case("parent created after its child", 100, 100, 90, 50L, null, 90, 80, 60L, "OpenAI.Codex_2p2nqsd0c76g0");
            Case("parent cannot be opened", 100, 100, 90, 50L, null, 90, 80, 0L, null, 80, 4, 0L, "OpenAI.Codex_2p2nqsd0c76g0");
            Case("cycle", 100, 100, 90, 10L, null, 90, 80, 10L, null, 80, 90, 10L, null);
            Case("self as its own parent", 100, 100, 100, 10L, null);
            var deep = new List<object>();
            for (int pid = 1000; pid > 1000 - HostApp.MaxSteps - 5; pid--) { deep.Add(pid); deep.Add(pid - 1); deep.Add((long)pid); deep.Add(null); }
            deep.Add(1000 - HostApp.MaxSteps - 5); deep.Add(0); deep.Add(1L); deep.Add("Far_away");
            Case("further than the walk goes", 1000, deep.ToArray());
            Console.WriteLine("{\"case\": \"name\", \"found\": " + Quote(HostApp.Name("OpenAI.Codex_2p2nqsd0c76g0") + "|" + HostApp.Name("NoHash")) + ", \"lookups\": 0}");
            Console.WriteLine("{\"case\": \"arguments\", \"found\": " + Quote(HostApp.Arguments(new[] { "--page=settings", "a b", "--outside" })) + ", \"lookups\": 0}");
            Console.WriteLine("{\"case\": \"relaunched\", \"found\": " + Quote(HostApp.Relaunched(new[] { "x", "--outside" }) + "|" + HostApp.Relaunched(new[] { "x" }) + "|" + string.Join(",", HostApp.Without(new[] { "--outside", "-Silent" }))) + ", \"lookups\": 0}");
            return 0;
        }
    }
}
"""


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class DecisionTests(unittest.TestCase):
    """HostApp.Decide over tables of the test's own."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="host-app-"))
        harness = cls.work / "probe.cs"
        harness.write_text(HARNESS, encoding="utf-8")
        exe = cls.work / "probe.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/out:" + str(exe),
                                "/reference:System.dll", "/reference:System.Windows.Forms.dll", str(HOST), str(harness)],
                               capture_output=True, text=True, encoding="mbcs", errors="replace", timeout=300,
                               creationflags=NO_WINDOW)
        cls.built = built.returncode == 0 and exe.is_file()
        cls.build_output = built.stdout + built.stderr
        cls.answers = {}
        if cls.built:
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
            for line in ran.stdout.splitlines():
                answer = json.loads(line)
                cls.answers[answer["case"]] = answer

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def answer(self, case):
        if not self.built:
            self.fail("the harness did not build: " + self.build_output[-3000:])
        return self.answers[case]

    def test_a_packaged_ancestor_is_inside_and_its_family_is_kept(self):
        self.assertEqual(self.answer("packaged ancestor")["found"], CODEX)
        self.assertEqual(self.answer("own package")["found"], "Claude_pzs8sxrjxfjjc")

    def test_no_package_anywhere_is_outside(self):
        self.assertIsNone(self.answer("no package")["found"])

    def test_a_parent_created_after_its_child_ends_the_walk_outside(self):
        """Its id was reused: the packaged process that has it now is no ancestor of this one."""
        self.assertIsNone(self.answer("parent created after its child")["found"])

    def test_a_parent_that_cannot_be_opened_ends_the_walk_outside(self):
        """Whatever lies beyond it: past one that could not be opened, nothing is known to be an ancestor."""
        self.assertIsNone(self.answer("parent cannot be opened")["found"])

    def test_a_cycle_stops_at_once(self):
        for case in ("cycle", "self as its own parent"):
            with self.subTest(case):
                answer = self.answer(case)
                self.assertIsNone(answer["found"])
                self.assertLessEqual(answer["lookups"], 4, "the walk went round the cycle")

    def test_the_walk_goes_no_further_than_its_steps(self):
        answer = self.answer("further than the walk goes")
        self.assertIsNone(answer["found"])
        self.assertLessEqual(answer["lookups"], 34)

    def test_the_relaunch_passes_the_arguments_on_once_and_marks_them(self):
        self.assertEqual(self.answer("name")["found"], "OpenAI.Codex|NoHash")
        self.assertEqual(self.answer("arguments")["found"], '"--page=settings" "a b" --outside')
        self.assertEqual(self.answer("relaunched")["found"], "True|False|-Silent")


# ----------------------------------------------------------------------- the Python walk (Diagnostics)
# The cases HARNESS gives HostApp.Decide, the same tables, for win/kernel.py's decide_host - which Diagnostics asks of
# the watcher's process and the bridge's own (control/tools.py host_app). (pid, parent, created, package) each.
PY_CASES = {
    "packaged ancestor": (100, [(100, 90, 50, None), (90, 80, 40, None), (80, 4, 30, CODEX)]),
    "own package": (100, [(100, 90, 50, "Claude_pzs8sxrjxfjjc"), (90, 4, 40, None)]),
    "no package": (100, [(100, 90, 50, None), (90, 80, 40, None), (80, 4, 30, None)]),
    "parent created after its child": (100, [(100, 90, 50, None), (90, 80, 60, CODEX)]),
    "parent cannot be opened": (100, [(100, 90, 50, None), (90, 80, 0, None), (80, 4, 0, CODEX)]),
    "cycle": (100, [(100, 90, 10, None), (90, 80, 10, None), (80, 90, 10, None)]),
    "self as its own parent": (100, [(100, 100, 10, None)]),
}


class _Counting(dict):
    """A process table that counts its lookups, as HARNESS's Counting does."""
    lookups = 0

    def get(self, key, default=None):
        self.lookups += 1
        return super().get(key, default)


def _table(rows) -> _Counting:
    table = _Counting()
    for pid, parent, created, package in rows:
        dict.__setitem__(table, pid, (parent, created, package))
    return table


def _chain(depth_of_package: int) -> _Counting:
    """A line of ancestors under pid 1000, each created before its child, the package `depth_of_package` parents up."""
    rows, pid = [], 1000
    for depth in range(60):
        rows.append((pid, pid - 1, 10_000 - depth, "Far.away_abcdefghijklm" if depth == depth_of_package else None))
        pid -= 1
    return _table(rows)


class PythonWalkTests(unittest.TestCase):
    """win/kernel.py's walk: HostApp.Decide's answers over HostApp.Decide's tables, guard by guard, with no live
    process asked - each guard taken out fails one of these."""

    def setUp(self):
        from codex_auto_resume.win import kernel
        self.kernel = kernel

    def decide(self, case):
        start, rows = PY_CASES[case]
        table = _table(rows)
        return self.kernel.decide_host(start, table), table.lookups

    def test_the_same_answers_as_hostapp_decide(self):
        """The answers DecisionTests holds the C# walk to, case by case."""
        expected = {"packaged ancestor": CODEX, "own package": "Claude_pzs8sxrjxfjjc", "no package": None,
                    "parent created after its child": None, "parent cannot be opened": None, "cycle": None,
                    "self as its own parent": None}
        for case, found in expected.items():
            with self.subTest(case):
                self.assertEqual(self.decide(case)[0], found)

    def test_a_parent_created_after_its_child_is_not_its_parent(self):
        self.assertIsNone(self.decide("parent created after its child")[0])

    def test_a_parent_that_cannot_be_opened_ends_the_walk(self):
        found, lookups = self.decide("parent cannot be opened")
        self.assertIsNone(found)
        self.assertLessEqual(lookups, 2, "the walk went past a parent it could not open")

    def test_a_cycle_stops_at_once(self):
        for case in ("cycle", "self as its own parent"):
            with self.subTest(case):
                found, lookups = self.decide(case)
                self.assertIsNone(found)
                self.assertLessEqual(lookups, 4, "the walk went round the cycle")

    def test_the_walk_goes_as_far_as_hostapp_and_no_further(self):
        steps = self.kernel.HOST_MAX_STEPS
        self.assertEqual(steps, 32, "HostApp.MaxSteps")
        self.assertEqual(self.kernel.decide_host(1000, _chain(steps)), "Far.away_abcdefghijklm")
        table = _chain(steps + 1)
        self.assertIsNone(self.kernel.decide_host(1000, table))
        self.assertLessEqual(table.lookups, steps + 2)

    def test_the_apps_name_drops_the_publisher_id(self):
        self.assertEqual(self.kernel.app_name(CODEX), "OpenAI.Codex")
        self.assertEqual(self.kernel.app_name("NoHash"), "NoHash")
        self.assertEqual(self.kernel.app_name(None), "")

    def test_the_verdict_says_inside_outside_or_unknown_and_never_more_than_the_family(self):
        verdict = self.kernel.host_verdict
        start, rows = PY_CASES["packaged ancestor"]
        self.assertEqual(verdict(start, _table(rows)), {"state": "inside", "family": CODEX, "app": "OpenAI.Codex"})
        start, rows = PY_CASES["no package"]
        self.assertEqual(verdict(start, _table(rows))["state"], "outside")
        self.assertEqual(verdict(4242, _table(rows))["state"], "unknown", "a process not in the table")
        self.assertEqual(verdict(100, _table([(100, 90, 0, None)]))["state"], "unknown", "one that cannot be opened")
        odd = verdict(100, _table([(100, 90, 50, "C:\\Users\\ExampleUser\\not a family")]))
        self.assertEqual(odd, {"state": "inside", "family": None, "app": None}, "what is not a family name is not said")

    def test_a_watcher_id_given_to_a_newer_process_is_unknown(self):
        """The heartbeat says when the watcher started; a process with its id created later is another one."""
        epoch = 116444736000000000
        started_at = 1_800_000_000.0
        created = epoch + int(started_at * 1e7)
        rows = [(4242, 90, created, None), (90, 4, created - 10, CODEX)]
        verdict = self.kernel.host_verdict
        self.assertEqual(verdict(4242, _table(rows), started_by=started_at)["state"], "inside")
        later = [(4242, 90, created + int(60 * 1e7), None), (90, 4, created - 10, CODEX)]
        self.assertEqual(verdict(4242, _table(later), started_by=started_at)["state"], "unknown")
        self.assertEqual(verdict(4242, _table(later))["state"], "inside", "without a start to hold it to")

    def test_the_live_table_is_gathered_as_hostapp_gathers_it(self):
        """Parent by Toolhelp, each process opened once, the gathering ended where one cannot be opened, on a
        cycle and after the steps - with Windows stood in for, so no live process is asked."""
        from unittest.mock import patch
        kernel = self.kernel
        parents = {100: 90, 90: 80, 80: 70, 70: 4}
        opened = {100: (50, None), 90: (40, None), 80: (0, None), 70: (30, CODEX)}
        asked = []

        def fake_open(_k, pid, own):
            asked.append((pid, own))
            return opened[pid]
        with patch.object(kernel, "_toolhelp_parents", return_value=parents), \
                patch.object(kernel, "_opened", side_effect=fake_open), \
                patch.object(kernel.os, "getpid", return_value=100):
            table = kernel._host_table(object(), 100)
        self.assertEqual(sorted(table), [80, 90, 100], "gathering stops at the one that cannot be opened")
        self.assertEqual(asked[0], (100, True), "this process's own package is asked as its own")
        self.assertTrue(all(not own for _pid, own in asked[1:]))
        with patch.object(kernel, "_toolhelp_parents", return_value={100: 90, 90: 100}), \
                patch.object(kernel, "_opened", return_value=(10, None)), \
                patch.object(kernel.os, "getpid", return_value=1):
            self.assertEqual(sorted(kernel._host_table(object(), 100)), [90, 100], "a cycle is gathered once")
        long_line = {pid: pid - 1 for pid in range(2, 200)}
        with patch.object(kernel, "_toolhelp_parents", return_value=long_line), \
                patch.object(kernel, "_opened", return_value=(10, None)), \
                patch.object(kernel.os, "getpid", return_value=1):
            self.assertEqual(len(kernel._host_table(object(), 199)), kernel.HOST_MAX_STEPS + 2)

    def test_it_never_raises(self):
        from unittest.mock import patch
        with patch.object(self.kernel, "_kernel", side_effect=OSError("boom")):
            self.assertEqual(self.kernel.host_app(), {"state": "unknown", "family": None, "app": None})


# ----------------------------------------------------------------------- install.ps1
GATE = block(INSTALL, "$script:HostAppSource = @'", "$outsideSwitches = @(")

# A table builder and a launcher of the test's own, defined after the script's so they are the ones called.
STUBS = r"""
$script:launched = 0
function Get-ProcessTable {
    param([int]$Self)
    $table = @{}
    $table[$Self] = @{ Parent = 41; Created = 50; Package = $null }
    $table[41] = @{ Parent = 40; Created = 40; Package = $null }
    $table[40] = @{ Parent = 4; Created = 30; Package = $env:CAR_PACKAGE }
    return $table
}
function Invoke-Outside {
    param([string]$Source, [string]$Log, [string]$CodeFile)
    $script:launched++
    Write-Host ('SOURCE ' + ($Source -replace "`r`n", ' | '))
    if ($env:CAR_LAUNCH -eq 'fail') { return $null }
    return 7
}
"""

DECIDE = r"""
Add-Type -TypeDefinition @'
public class CountingTable : System.Collections.Hashtable
{
    public int Lookups;
    public override object this[object key] { get { Lookups++; return base[key]; } set { base[key] = value; } }
}
'@
function Table($rows) {
    $table = New-Object CountingTable
    foreach ($row in $rows) { $table[[int]$row[0]] = @{ Parent = [int]$row[1]; Created = [long]$row[2]; Package = $row[3] } }
    return ,$table
}
$cases = [ordered]@{
    'packaged ancestor' = @(@(100, 90, 50, $null), @(90, 80, 40, $null), @(80, 4, 30, 'OpenAI.Codex_2p2nqsd0c76g0'))
    'own package' = @(@(100, 90, 50, 'Claude_pzs8sxrjxfjjc'), @(90, 4, 40, $null))
    'no package' = @(@(100, 90, 50, $null), @(90, 80, 40, $null), @(80, 4, 30, $null))
    'parent created after its child' = @(@(100, 90, 50, $null), @(90, 80, 60, 'OpenAI.Codex_2p2nqsd0c76g0'))
    'parent cannot be opened' = @(@(100, 90, 50, $null), @(90, 80, 0, $null), @(80, 4, 0, 'OpenAI.Codex_2p2nqsd0c76g0'))
    'cycle' = @(@(100, 90, 10, $null), @(90, 80, 10, $null), @(80, 90, 10, $null))
}
$answers = [ordered]@{}
foreach ($name in $cases.Keys) {
    $table = Table $cases[$name]
    $found = Find-PackagedAncestor -Table $table -Self 100
    $answers[$name] = @{ found = $found; lookups = $table.Lookups }
}
'JSON ' + ($answers | ConvertTo-Json -Compress)
"""


@unittest.skipUnless(POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class InstallerGateTests(unittest.TestCase):
    """install.ps1's own functions, lifted out of it, with its process table and its launcher stubbed."""

    def run_gate(self, script: str, **environment) -> subprocess.CompletedProcess:
        saved = {name: os.environ.get(name) for name in ("CAR_PACKAGE", "CAR_LAUNCH", "CODEX_AUTO_RESUME_OUTSIDE")}
        try:
            for name in saved:
                os.environ.pop(name, None)
            os.environ.update(environment)
            done = run_probe(VOICE + GATE + STUBS, script)
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done

    RESOLVE = ("$code = Resolve-OutsideRun -Script 'C:\\x\\install.ps1' -Switches @('Silent', 'SkipStartup') "
               "-Values @{ PluginName = 'codex-auto-resume'; MarketplaceName = 'it''s' }\n"
               "'CODE ' + $(if ($null -eq $code) { 'none' } else { $code })\n"
               "'LAUNCHED ' + $script:launched\n"
               "'MARK ' + [string]$env:CODEX_AUTO_RESUME_OUTSIDE + '.'\n")

    def lines(self, done, prefix):
        return [line[len(prefix):] for line in done.stdout.splitlines() if line.startswith(prefix)]

    def test_the_decision_over_tables_of_its_own(self):
        done = self.run_gate(DECIDE)
        answers = json.loads(self.lines(done, "JSON ")[0])
        self.assertEqual(answers["packaged ancestor"]["found"], CODEX)
        self.assertEqual(answers["own package"]["found"], "Claude_pzs8sxrjxfjjc")
        for case in ("no package", "parent created after its child", "parent cannot be opened", "cycle"):
            with self.subTest(case):
                self.assertIsNone(answers[case]["found"])
        self.assertLessEqual(answers["cycle"]["lookups"], 4, "the walk went round the cycle")

    def test_inside_it_runs_again_outside_with_its_parameters_and_ends_with_that_code(self):
        done = self.run_gate(self.RESOLVE, CAR_PACKAGE=CODEX)
        self.assertEqual(self.lines(done, "CODE "), ["7"])
        self.assertEqual(self.lines(done, "LAUNCHED "), ["1"])
        source = self.lines(done, "SOURCE ")[0]
        self.assertIn("& 'C:\\x\\install.ps1' -Silent -SkipStartup -MarketplaceName 'it''s' -PluginName 'codex-auto-resume'",
                      source)
        self.assertIn("*>&1", source)
        self.assertIn("exit $code", source)
        self.assertNotIn("[!]", done.stdout, "a relaunch that worked says nothing of its own")

    def test_outside_it_carries_on_and_starts_nothing(self):
        done = self.run_gate(self.RESOLVE)
        self.assertEqual(self.lines(done, "CODE "), ["none"])
        self.assertEqual(self.lines(done, "LAUNCHED "), ["0"])

    def test_the_mark_stops_a_second_relaunch_and_goes_no_further(self):
        done = self.run_gate(self.RESOLVE, CAR_PACKAGE=CODEX, CODEX_AUTO_RESUME_OUTSIDE="1")
        self.assertEqual(self.lines(done, "CODE "), ["none"])
        self.assertEqual(self.lines(done, "LAUNCHED "), ["0"], "a run outside never relaunches")
        self.assertEqual(self.lines(done, "MARK "), ["."], "its children ask for themselves")

    def test_a_relaunch_that_fails_carries_on_and_says_once_what_stays_inside(self):
        done = self.run_gate(self.RESOLVE, CAR_PACKAGE=CODEX, CAR_LAUNCH="fail")
        self.assertEqual(self.lines(done, "CODE "), ["none"])
        warnings = [line for line in done.stdout.splitlines() if line.startswith("  [!]")]
        self.assertEqual(len(warnings), 1, done.stdout)
        self.assertIn("may be running inside OpenAI.Codex.", warnings[0])
        for named in ("Settings > Apps", "sign-in", "Start menu", "Repair installation"):
            self.assertIn(named, warnings[0])

    def test_every_word_of_it_allows_for_an_ancestor_that_keeps_no_private_view(self):
        """A packaged ancestor is not always an app with a private view - Windows Terminal is packaged, and a shell in
        one of its tabs counts as inside it. The relaunch is kept (it costs nothing there); what is said where it fails
        says what may be so: the scripts' warning, and the window's English, which is the catalog's."""
        catalog = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
        self.assertTrue(catalog["diag.inside_app"].startswith("This Dashboard may have been opened from inside {app}."))
        self.assertTrue(catalog["installer.inside_app"].startswith("This may have been started from inside {app}."))
        self.assertIn('"%s"' % catalog["diag.inside_app"], guiscan.member_body("SettingsForm", "RefusedInside"))
        self.assertIn('"%s"' % catalog["installer.inside_app"], guiscan.member_body("InstallerWindow", "InsideNote"))
        for script in (INSTALL, BOOTSTRAP_TEXT):
            self.assertIn("Warn ('This may be running inside ' + $name", outside_gate(script))
            self.assertNotIn("This runs inside", script)

    def test_the_gate_runs_before_anything_else_the_script_does(self):
        gate = INSTALL.index("$outsideCode = Resolve-OutsideRun -Script $PSCommandPath")
        self.assertLess(gate, INSTALL.index("New-Object System.Threading.Mutex($false, 'Local\\CodexAutoResume.Install')"))
        self.assertLess(gate, INSTALL.index("Write-Host 'Codex Auto Resume'"))
        self.assertIn("if ($null -ne $outsideCode) { exit $outsideCode }", INSTALL)
        for switch in ("SkipStartup", "Uninstall", "Purge", "AllowEditionChange", "Silent"):
            self.assertRegex(INSTALL, r"param\(\s[\s\S]*\[switch\]\$%s\b" % switch)
            self.assertIn("'%s'" % switch, INSTALL[INSTALL.index("$outsideSwitches = @("):gate])
        launch = guiscan._block(INSTALL, INSTALL.index("function Invoke-Outside"))
        self.assertIn("ShowWindow = [uint16]0", launch, "no console window shows")
        self.assertIn("'CODEX_AUTO_RESUME_OUTSIDE=1'", launch)
        self.assertIn("[Environment]::GetEnvironmentVariables()", launch, "the run outside gets this run's environment")


# The run outside, for real but not through WMI: Win32_ProcessStartup and Win32_Process.Create stand in as functions,
# which are found before cmdlets. The startup object is written down; Create starts the very command line it is given
# as an ordinary hidden child of the probe, so the relay, the exit code and the source the run outside executes are the
# script's own. The stand-in for the work prints two lines, one of them Korean, adds a last line with no line end to
# the log by itself, and ends with 7.
RELAY = r"""
$script:startupSeen = $null
function New-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName, [switch]$ClientOnly, [hashtable]$Property)
    $script:startupSeen = $Property
    return $Property
}
function Invoke-CimMethod {
    [CmdletBinding()]
    param([string]$ClassName, [string]$MethodName, [hashtable]$Arguments)
    $line = [string]$Arguments.CommandLine
    $close = $line.IndexOf('"', 1)
    $info = New-Object System.Diagnostics.ProcessStartInfo($line.Substring(1, $close - 1), $line.Substring($close + 2))
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::Start($info)
    return [pscustomobject]@{ ReturnValue = 0; ProcessId = $process.Id }
}
$folder = $env:CAR_FOLDER
$log = Join-Path $folder 'output.txt'
$codeFile = Join-Path $folder 'code.txt'
$env:CAR_LOG = $log
$env:CAR_PROBE_VAR = 'present'
$source = Get-OutsideSource -Script $env:CAR_STAND_IN -Switches @('Silent') -Log $log -CodeFile $codeFile
$code = Invoke-Outside -Source $source -Log $log -CodeFile $codeFile
'CODE ' + $code
'ENV ' + (@($script:startupSeen.EnvironmentVariables) -join '|')
'SHOW ' + $script:startupSeen.ShowWindow
"""

STAND_IN = """param([switch]$Silent)
Write-Host ('first line, silent ' + $Silent)
Write-Host 'Korean: 한국어'
[IO.File]::AppendAllText($env:CAR_LOG, 'last line without an end', (New-Object System.Text.UTF8Encoding $false))
exit 7
"""


@unittest.skipUnless(POWERSHELL.is_file(), "the installer is PowerShell on Windows")
class RelayTests(unittest.TestCase):
    """install.ps1's relay, exit code and environment, run for real against a stand-in for the process outside."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="host-app-relay-"))
        stand_in = cls.work / "stand-in.ps1"
        stand_in.write_text(STAND_IN, encoding="utf-8-sig")
        folder = cls.work / "outside"
        folder.mkdir()
        saved = {name: os.environ.get(name) for name in ("CAR_FOLDER", "CAR_STAND_IN")}
        os.environ.update(CAR_FOLDER=str(folder), CAR_STAND_IN=str(stand_in))
        try:
            cls.done = run_probe(VOICE + GATE, RELAY)
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def lines(self, prefix):
        return [line[len(prefix):] for line in self.done.stdout.splitlines() if line.startswith(prefix)]

    def test_what_the_run_outside_prints_is_passed_on_line_by_line_with_the_last_unended_line(self):
        printed = self.done.stdout.splitlines()
        self.assertEqual(self.done.returncode, 0, self.done.stdout + self.done.stderr)
        for line in ("first line, silent True", "Korean: 한국어", "last line without an end"):
            with self.subTest(line):
                self.assertIn(line, printed)
        self.assertLess(printed.index("first line, silent True"), printed.index("last line without an end"))

    def test_its_exit_code_is_the_run_s(self):
        self.assertEqual(self.lines("CODE "), ["7"], self.done.stdout + self.done.stderr)

    def test_the_run_outside_gets_this_run_s_environment_and_the_mark_with_no_window(self):
        environment = self.lines("ENV ")[0].split("|")
        self.assertIn("CAR_PROBE_VAR=present", environment)
        self.assertIn("CODEX_AUTO_RESUME_OUTSIDE=1", environment)
        self.assertEqual([entry for entry in environment if entry.startswith("CODEX_AUTO_RESUME_OUTSIDE=")],
                         ["CODEX_AUTO_RESUME_OUTSIDE=1"])
        self.assertEqual(self.lines("SHOW "), ["0"])


# ----------------------------------------------------------------------- bootstrap.ps1's repair branch
BOOTSTRAP_TEXT = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")


def outside_gate(text: str) -> str:
    """The outside gate as a script carries it: from its first line to its end marker."""
    start = text.index("# Opens a process for limited query")
    return text[start:text.index("# <<< the outside gate", start)]


# The installation's runtime\python.exe, standing in: it says how it was run, and ends with 5.
FAKE_PYTHON = r"""
static class FakePython
{
    static int Main(string[] args)
    {
        System.Console.WriteLine("FAKE-PYTHON args=" + string.Join(" ", args) + " marker=" +
                                 System.Environment.GetEnvironmentVariable("CODEX_AUTO_RESUME_OUTSIDE"));
        string ran = System.Environment.GetEnvironmentVariable("CAR_RAN");
        if (!string.IsNullOrEmpty(ran)) System.IO.File.AppendAllText(ran, string.Join(" ", args) + "\n");
        // 5 unless a case says otherwise: CAR_PROBE_CODE for `watcher-running`, CAR_SETUP_CODE for anything else.
        // The script's command follows the interpreter's options (-X disable-remote-debug, v0.6.19-beta.3) and the script.
        int script = 0;
        while (script < args.Length && args[script].StartsWith("-")) script += args[script] == "-X" ? 2 : 1;
        string said = System.Environment.GetEnvironmentVariable(
            args.Length > script + 1 && args[script + 1] == "watcher-running" ? "CAR_PROBE_CODE" : "CAR_SETUP_CODE");
        int code;
        return int.TryParse(said, out code) ? code : 5;
    }
}
"""

# Aliases are found before functions, so these stand in for the script's own Get-ProcessTable and Invoke-Outside
# while the whole script runs: a process table with or without a packaged parent, and a launcher that writes down
# what it would run outside and answers 7, or fails.
ALIASED = r"""
function global:Fake-ProcessTable {
    param([int]$Self)
    $table = @{}
    $table[$Self] = @{ Parent = 41; Created = 50; Package = $null }
    $table[41] = @{ Parent = 4; Created = 40; Package = $env:CAR_PACKAGE }
    return $table
}
function global:Fake-Outside {
    param([string]$Source, [string]$Log, [string]$CodeFile)
    Write-Host ('SOURCE ' + ($Source -replace "`r`n", ' | '))
    if ($env:CAR_LAUNCH -eq 'fail') { return $null }
    if ($env:CAR_OUTSIDE_CODE) { return [int]$env:CAR_OUTSIDE_CODE }
    return 7
}
Set-Alias -Scope Global Get-ProcessTable Fake-ProcessTable
Set-Alias -Scope Global Invoke-Outside Fake-Outside
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class BootstrapRepairTests(unittest.TestCase):
    """bootstrap.ps1 at the version already installed checks the installation over with its own setup, never
    through install.ps1: inside another app's view that setup runs outside, as install.ps1 does (v0.6.17). The whole
    script runs over a scratch plugin and a scratch home at the same version, with the network stubbed as
    tests/test_edition_bootstrap.py stubs it and the installation's python a stand-in."""

    @classmethod
    def setUpClass(cls):
        from test_edition_bootstrap import NOWHERE, RELEASE, RUN
        cls.run_script = ALIASED + RUN
        cls.work = Path(tempfile.mkdtemp(prefix="host-app-bootstrap-"))
        plugin = cls.work / "plugin"
        (plugin / "scripts").mkdir(parents=True)
        (plugin / ".codex-plugin").mkdir()
        shutil.copyfile(ROOT / "scripts" / "bootstrap.ps1", plugin / "scripts" / "bootstrap.ps1")
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        (plugin / ".codex-plugin" / "plugin.json").write_text(json.dumps(dict(manifest, version="9.9.9")),
                                                               encoding="utf-8")
        release = dict(RELEASE, download=NOWHERE + "/download/v{version}/", latest=NOWHERE + "/latest")
        (plugin / "scripts" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        cls.script = plugin / "scripts" / "bootstrap.ps1"
        cls.home = cls.work / "home"
        (cls.home / "runtime").mkdir(parents=True)
        (cls.home / "app" / ".codex-plugin").mkdir(parents=True)
        (cls.home / "app" / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "codex-auto-resume", "version": "9.9.9"}), encoding="utf-8")
        (cls.home / "app" / "scripts").mkdir()
        (cls.home / "app" / "src" / "codex_auto_resume").mkdir(parents=True)
        source = cls.work / "fake.cs"
        source.write_text(FAKE_PYTHON, encoding="utf-8")
        cls.python = cls.home / "runtime" / "python.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:exe", "/out:" + str(cls.python), str(source)],
                               capture_output=True, text=True, encoding="mbcs", errors="replace", timeout=300,
                               creationflags=NO_WINDOW)
        cls.built = built.returncode == 0
        cls.temp = cls.work / "temp"
        cls.temp.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def run_it(self, **environment):
        if not self.built:
            self.fail("the stand-in python did not build")
        values = dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(self.home), TEMP=str(self.temp),
                      TMP=str(self.temp), CAR_SCRIPT=str(self.script), CAR_ARGUMENTS="{}",
                      CAR_REQUESTS=str(self.work / "requests.txt"), CAR_INSTALLED=str(self.work / "installed.json"),
                      CAR_LATEST="")
        for name in ("CAR_PACKAGE", "CAR_LAUNCH", "CODEX_AUTO_RESUME_OUTSIDE", "CAR_SETUP_CODE", "CAR_PROBE_CODE",
                     "CAR_OUTSIDE_CODE"):
            values.pop(name, None)
        values.update(environment)
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", self.run_script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", timeout=300, env=values,
                              creationflags=NO_WINDOW)
        self.assertIn("already installed", done.stdout, done.stdout[-2000:])
        return done.returncode, done.stdout

    def test_inside_the_check_over_runs_outside_and_ends_with_its_code(self):
        code, output = self.run_it(CAR_PACKAGE=CODEX)
        self.assertEqual(code, 7, output[-2000:])
        sources = [line for line in output.splitlines() if line.startswith("SOURCE ")]
        self.assertEqual(len(sources), 1, output[-2000:])
        setup = self.home / "app" / "scripts" / "plugin_setup.py"
        self.assertIn("& '%s' '-X' 'disable-remote-debug' '%s' 'setup' '--keep-state'" % (self.python, setup), sources[0])
        self.assertNotIn("FAKE-PYTHON", output, "the setup ran here as well")

    def test_a_relaunch_that_fails_runs_it_here_and_says_so_once(self):
        code, output = self.run_it(CAR_PACKAGE=CODEX, CAR_LAUNCH="fail")
        self.assertEqual(code, 5, output[-2000:])
        self.assertIn("FAKE-PYTHON args=", output)
        self.assertEqual(len([line for line in output.splitlines() if line.startswith("  [!]")]), 1, output[-2000:])

    def test_a_watcher_that_started_after_the_setup_s_wait_ends_the_check_over_with_0(self):
        """v0.6.17 live acceptance: setup's 2 - it could not confirm the watcher within its wait - is looked at once
        more (plugin_setup.py watcher-running), here and after a run outside alike, and a watcher holding its mutex
        by then is running: 0. One still not running stays 2."""
        setup = self.home / "app" / "scripts" / "plugin_setup.py"
        for environment, expected in (({"CAR_SETUP_CODE": "2", "CAR_PROBE_CODE": "0"}, 0),
                                      ({"CAR_SETUP_CODE": "2", "CAR_PROBE_CODE": "2"}, 2),
                                      ({"CAR_PACKAGE": CODEX, "CAR_OUTSIDE_CODE": "2", "CAR_PROBE_CODE": "0"}, 0),
                                      ({"CAR_PACKAGE": CODEX, "CAR_OUTSIDE_CODE": "2", "CAR_PROBE_CODE": "2"}, 2)):
            with self.subTest(environment):
                code, output = self.run_it(**environment)
                self.assertEqual(code, expected, output[-2000:])
                self.assertIn("FAKE-PYTHON args=-X disable-remote-debug %s watcher-running" % setup, output)

    def test_only_a_2_is_looked_at_again(self):
        code, output = self.run_it(CAR_SETUP_CODE="1", CAR_PROBE_CODE="0")
        self.assertEqual(code, 1, output[-2000:])
        self.assertNotIn("watcher-running", output)

    def test_the_mark_and_a_run_outside_any_app_run_it_here(self):
        for environment in ({"CAR_PACKAGE": CODEX, "CODEX_AUTO_RESUME_OUTSIDE": "1"}, {}):
            with self.subTest(environment):
                code, output = self.run_it(**environment)
                self.assertEqual(code, 5, output[-2000:])
                self.assertIn("FAKE-PYTHON args=", output)
                self.assertIn("setup --keep-state", output)
                self.assertNotIn("SOURCE ", output)
                self.assertNotIn("  [!]", output)

    # ------------------------------------------------------------------ the other two runs of the installed setup
    # The downgrade path's `remove-entry` (Remove-EntryBeforeOlder) and a failed conversion's `setup --keep-state`
    # (Start-CurrentWatcher) write the registry too, so they go through the gate as the repair branch does. Each is
    # lifted out of the script with the gate and run alone, with the process table and launcher stubbed and the
    # stand-in python writing down that it ran here.
    LIFTED = ("Find-PackagedAncestor", "Get-OutsideSource", "Resolve-OutsideRun", "Invoke-InstalledSetup",
              "Remove-EntryBeforeOlder", "Start-CurrentWatcher", "Get-VersionParts", "Compare-ProductVersion")
    CALLS = r"""
$EntryFrom = '0.6.16'
$script:sources = @()
$script:warned = @()
function Get-ProcessTable {
    param([int]$Self)
    $table = @{}
    $table[$Self] = @{ Parent = 41; Created = 50; Package = $null }
    $table[41] = @{ Parent = 4; Created = 40; Package = $env:CAR_PACKAGE }
    return $table
}
function Invoke-Outside {
    param([string]$Source, [string]$Log, [string]$CodeFile)
    $script:sources += ,($Source -replace "`r`n", ' | ')
    if ($env:CAR_LAUNCH -eq 'fail') { return $null }
    return 0
}
function Warn { param([string]$m) $script:warned += ,$m }
$answer = $null
if ($env:CAR_WHICH -eq 'entry') { $answer = Remove-EntryBeforeOlder -Home_ $env:CAR_HOME -Installed '0.6.16' -Target '0.6.15' }
else { Start-CurrentWatcher -Home_ $env:CAR_HOME }
@{ answer = $answer; sources = @($script:sources); warned = @($script:warned) } | ConvertTo-Json -Compress
"""

    def call(self, which, **environment):
        from test_edition_bootstrap import LIFT
        ran = self.work / "ran.txt"
        if ran.exists():
            ran.unlink()
        values = dict(os.environ, CAR_SCRIPT=str(ROOT / "scripts" / "bootstrap.ps1"), CAR_FUNCTIONS=",".join(self.LIFTED),
                      CAR_CASES="[]", CAR_HOME=str(self.home), CAR_WHICH=which, CAR_RAN=str(ran))
        for name in ("CAR_PACKAGE", "CAR_LAUNCH", "CODEX_AUTO_RESUME_OUTSIDE"):
            values.pop(name, None)
        values.update(environment)
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", LIFT + self.CALLS], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300, env=values, creationflags=NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        answer = json.loads(done.stdout.strip().splitlines()[-1])
        here = ran.read_text(encoding="utf-8").splitlines() if ran.exists() else []
        return answer, here

    def check_gated(self, which, command):
        answer, here = self.call(which, CAR_PACKAGE=CODEX)
        self.assertEqual(len(answer["sources"]), 1, answer)
        self.assertIn("'%s'" % (self.home / "app" / "scripts" / "plugin_setup.py"), answer["sources"][0])
        self.assertIn(command, answer["sources"][0])
        self.assertEqual(here, [], "it ran here as well")
        self.assertEqual(answer["warned"], [])
        if which == "entry":
            self.assertEqual(answer["answer"], "removed", "the code of the run outside decides")
        answer, here = self.call(which, CAR_PACKAGE=CODEX, CAR_LAUNCH="fail")
        self.assertEqual(len(answer["warned"]), 1, answer)
        self.assertEqual(len(here), 1, "a relaunch that fails runs it here")
        for environment in ({"CAR_PACKAGE": CODEX, "CODEX_AUTO_RESUME_OUTSIDE": "1"}, {}):
            with self.subTest(environment):
                answer, here = self.call(which, **environment)
                self.assertEqual(answer["sources"], [])
                self.assertEqual(len(here), 1)

    def test_the_downgrade_s_remove_entry_runs_outside_as_the_repair_does(self):
        self.check_gated("entry", "'remove-entry'")

    def test_a_failed_conversion_s_watcher_start_runs_outside_as_the_repair_does(self):
        self.check_gated("watcher", "'setup' '--keep-state'")

    def test_the_two_scripts_carry_one_gate(self):
        """Both scripts ship in every archive, but neither finds the other from everywhere it runs (the kept
        uninstaller, Codex's copy of the plugin), so each carries the gate; this holds the copies equal."""
        self.assertEqual(outside_gate(BOOTSTRAP_TEXT), outside_gate(INSTALL))
        branch = BOOTSTRAP_TEXT[BOOTSTRAP_TEXT.index("Step 'Checking it over'"):]
        gate = branch.index("$outsideCode = Resolve-OutsideRun -Script $python -Arguments $arguments")
        self.assertLess(branch.index("$held = $lock.WaitOne(0)"), gate, "the lock is held while it runs outside")
        self.assertLess(gate, branch.index("& $python @arguments"))


# ----------------------------------------------------------------------- the wiring
def setup_method(name: str) -> str:
    found = re.search(r"\n[ \t]+(?:internal |private |public )?static \w+ %s\(" % re.escape(name), SETUP)
    return guiscan._block(SETUP, found.start())


def setup_window_method(name: str) -> str:
    found = re.search(r"\n[ \t]+(?:internal |private |public )?static \w+ %s\(" % re.escape(name), SETUP_WINDOW)
    return guiscan._block(SETUP_WINDOW, found.start())


class WiringTests(unittest.TestCase):
    def test_host_app_is_built_into_the_dashboard_and_the_setup_programs(self):
        self.assertIn("gui/HostApp.cs", guiscan.group("installer"))
        self.assertIn("gui/HostApp.cs", make_setup.window_sources())

    def test_the_dashboard_asks_before_the_bridge_and_relaunches_itself_marked(self):
        main = guiscan.member_body("Program", "Main")
        asked = main.index("HostApp.Inside()")
        self.assertLess(main.index("SettingsRemove.IsAsked(argv)"), asked)
        self.assertLess(main.index("SettingsForm.RenderJob"), asked)
        self.assertLess(asked, main.index("new Bridge(root)"))
        relaunch = main[asked:main.index("new Bridge(root)")]
        self.assertIn("!HostApp.Relaunched(argv)", relaunch)
        self.assertIn("HostApp.Relaunch(Application.ExecutablePath, HostApp.Arguments(argv), root))", relaunch)
        self.assertIn("return 0;", relaunch)
        self.assertIn("HostApp.StuckInside = inside;", relaunch)
        self.assertIn("Soft.StillReady == null ? HostApp.Inside() : null", main, "a capture's window stays")
        arguments = guiscan.member_body("HostApp", "Arguments")
        self.assertIn(".Append(Outside)", arguments)

    def test_the_setup_window_asks_before_it_opens_and_relaunches_itself_marked(self):
        started = setup_method("Started")
        self.assertLess(started.index("HostApp.Without(arguments)"), started.index("Passed.Acceptable(arguments)"))
        asked = started.index("HostApp.Inside()")
        self.assertLess(asked, started.index("return Windowed(arguments);"))
        self.assertIn("HostApp.Arguments(arguments)", started[asked:])
        self.assertIn("!relaunched", started[asked:started.index("return Windowed(arguments);")])
        self.assertIn("HostApp.StuckInside = inside;", started)
        self.assertIn("arguments[0] != CodexAutoResume.HostApp.Outside", setup_method("Hook"),
                      "the mark is no test's hook")

    def test_a_window_that_stayed_inside_passes_the_mark_to_its_reopening(self):
        """The window's own parser ignores what it does not know, and the setup program's, which refuses it, has it
        taken off first (Started, above). A reopen passes it on only for a window that stayed inside, which does
        not try again in the middle of a reopen."""
        self.assertIn("if (HostApp.StuckInside != null) arguments.Add(HostApp.Outside);",
                      guiscan.member_body("SettingsForm", "ReopenArguments"))

    def test_a_moved_sign_in_switch_is_not_saved_while_stuck_inside(self):
        """The Settings page's Save writes the sign-in entry through the bridge's `startup` (HKCU Run): the only other
        HKCU write the window reaches. Stuck inside, it is refused as Repair is, and the switch goes back."""
        save = guiscan.member_body("SettingsForm", "Save")
        call = save.index('CallAsync("startup"')
        refused = save.rindex("if (RefusedInside())", 0, call)
        self.assertIn("startup.Checked = startupBaseline;", save[refused:call])
        self.assertIn("return;", save[refused:call])
        self.assertLess(save.index("startAtSignIn != startupBaseline"), refused)

    def test_the_three_maintenance_actions_refuse_while_stuck_inside(self):
        refused = guiscan.member_body("SettingsForm", "RefusedInside")
        self.assertIn("if (HostApp.StuckInside == null) return false;", refused)
        self.assertIn('S("diag.inside_app"', refused)
        self.assertIn('"app", HostApp.Name(HostApp.StuckInside)', refused)
        for member, before in (("Repair", "Confirm("), ("InstallUpdate", "SetBusy(true)"),
                               ("OpenVersions", "BuildVersions()")):
            with self.subTest(member):
                body = guiscan.member_body("SettingsForm", member)
                self.assertIn("if (RefusedInside()) return;", body)
                self.assertLess(body.index("RefusedInside()"), body.index(before))

    def test_the_setup_window_says_so_before_it_installs_or_removes(self):
        note = guiscan.member_body("InstallerWindow", "InsideNote")
        self.assertIn("if (HostApp.StuckInside == null) return;", note)
        self.assertIn('words.Say("installer.inside_app"', note)
        for page in ("BuildOptions", "BuildMaintain", "BuildConfirm"):
            with self.subTest(page):
                self.assertIn("InsideNote(", guiscan.member_body("InstallerWindow", page))

    def test_every_language_says_both_with_the_app_named(self):
        for catalog in sorted(LOCALES.glob("*.json")):
            words = json.loads(catalog.read_text(encoding="utf-8"))
            for key in ("diag.inside_app", "installer.inside_app"):
                with self.subTest(catalog=catalog.name, key=key):
                    self.assertIn("{app}", words.get(key, ""))


class FrontTests(unittest.TestCase):
    """v0.6.17 item 3a: after Finish, the Dashboard opened behind the windows already there."""

    def test_the_dashboard_after_finish_is_started_in_front(self):
        opened = setup_window_method("OpenDashboard")
        self.assertIn("HostApp.StartInFront(exe, null, home);", opened)
        self.assertNotIn("Process.Start(", opened)
        reopened = guiscan.member_body("SettingsForm", "OpenNewDashboard")
        self.assertIn("HostApp.StartInFront(exe, null, root)", reopened)
        self.assertNotIn("Process.Start(", reopened)
        started = guiscan.member_body("HostApp", "StartInFront")
        self.assertIn("AllowSetForegroundWindow(started.Id);", started)

    def test_a_window_a_person_opened_brings_itself_forward(self):
        main = guiscan.member_body("Program", "Main")
        self.assertIn("if (request.Generation == 0 && Soft.StillReady == null) HostApp.BringToFront(window);", main)
        self.assertLess(main.index("HostApp.BringToFront(window);"), main.index("Application.Run(window);"))
        run = setup_window_method("Run")
        self.assertLess(run.index("HostApp.BringToFront(window);"), run.index("Application.Run(window);"))
        # v0.6.20: what it does once shown is ComeForward, which the Dashboard also does when the watcher asks it to.
        self.assertIn("window.Shown += delegate { ComeForward(window); };", guiscan.member_body("HostApp", "BringToFront"))
        front = guiscan.member_body("HostApp", "ComeForward")
        self.assertIn("SetForegroundWindow(window.Handle);", front)
        self.assertIn("ShowWindow(window.Handle, SwRestore);", front)
        self.assertIn("HostApp.Present(window);", guiscan.member_body("SettingsRemove", "Present"))

    def test_the_relaunch_lets_the_new_window_take_the_foreground(self):
        relaunch = guiscan.member_body("HostApp", "Relaunch")
        self.assertLess(relaunch.index("AllowSetForegroundWindow(AsfwAny);"), relaunch.index("ShellRun("))


if __name__ == "__main__":
    unittest.main()

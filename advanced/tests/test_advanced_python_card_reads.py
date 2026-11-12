"""The Python version card (advanced/gui/AdvancedPythons.cs) reads itself only while it is on screen, and keeps the
keyboard's place across a rebuild (v0.6.23, the windows audit's G3).

While a download runs the card's timer reads `advanced-python` every 0.7 s and every read that sees more bytes builds
the cards again. Off screen - the person on the Overview or Settings - the timer asks nothing (PollPython); back on
the Advanced page its next tick reads. And a rebuild puts the keyboard back on the control in the same place of the
cards built again (PlaceOf, AtPlace, FocusPlace in ShowAdvancedDetail), not on the capability list.

The window is compiled once, never shown, and its bridge rooted where nothing is (pagecase.PageCase); the place
helpers are pure and called by reflection on controls never shown.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh).
    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests -p test_advanced_python_card_reads.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
import guiscan  # noqa: E402
from pagecase import POWERSHELL, PageCase, snapshot  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PYTHON = "python_choice"
RUNNING = {"ok": True, "result": {"done": True, "refusal": None, "bundled": "3.14.10", "chosen": None, "in_use": "3.14.10",
                                  "button": True, "checked": True, "offers": [], "missing": [], "outcome": None,
                                  "returned": None, "job": {"stage": "downloading", "version": "3.15.0",
                                                            "got": 1048576, "total": 31457280}}}

PLACES = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::SetUnhandledExceptionMode([Windows.Forms.UnhandledExceptionMode]::ThrowException)
try {
  $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
  $F = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
  $flags = [Reflection.BindingFlags]'Static,NonPublic,Public'
  $placeOf = $F.GetMethod('PlaceOf', $flags)
  $atPlace = $F.GetMethod('AtPlace', $flags)
  function Tree() {
    $root = [Windows.Forms.Panel]::new()
    foreach ($i in 0..2) {
      $card = [Windows.Forms.Panel]::new()
      foreach ($j in 0..3) { $b = [Windows.Forms.Button]::new(); $b.Text = "$i.$j"; $card.Controls.Add($b) }
      $root.Controls.Add($card)
    }
    return ,$root
  }
  $one = Tree
  $inner = $one.Controls[2].Controls[1]
  $place = $placeOf.Invoke($null, [object[]]@($one.psobject.BaseObject, $inner))
  $again = Tree
  $found = $atPlace.Invoke($null, [object[]]@($again.psobject.BaseObject, $place))
  $short = [Windows.Forms.Panel]::new()
  $short.Controls.Add(([Windows.Forms.Panel]::new()))
  $outside = [Windows.Forms.Button]::new()
  $listed = [System.Collections.Generic.List[int]]::new()
  $listed.Add(0); $listed.Add(3)
  $out = @{
    place = @($place)
    found = [string]$found.Text
    same_place_other_tree = [bool]($found -ne $inner)
    gone = ($null -eq $atPlace.Invoke($null, [object[]]@($short.psobject.BaseObject, $listed.psobject.BaseObject)))
    outside = ($null -eq $placeOf.Invoke($null, [object[]]@($one.psobject.BaseObject, $outside.psobject.BaseObject)))
    root = ($null -eq $placeOf.Invoke($null, [object[]]@($one.psobject.BaseObject, $one.psobject.BaseObject)))
  }
  $out | ConvertTo-Json -Compress
} catch {
  $thrown = $_.Exception
  while ($thrown.InnerException) { $thrown = $thrown.InnerException }
  [Console]::Error.WriteLine($thrown.ToString())
  exit 3
}
"""


class PythonCardTests(PageCase):
    @classmethod
    def scenario_python_card_off_screen(cls, bridge):
        """python_choice open with a download running; its timer ticks on the Advanced page, on the Overview, on
        Settings, and again on the Advanced page."""
        from codex_auto_resume import control
        from codex_auto_resume_advanced import plug as advanced, registry
        made = registry.Registry(registry.REGISTRY.definitions + registry.INSTALLED_ONLY)
        bridge.plug = advanced.AdvancedPlug(bridge.paths, registry=made, clock=lambda: ac.NOW, policy=lambda: bridge.policy,
                                            view=lambda: bridge.view, measured=lambda: bridge.measured)
        bridge.control = control.Control(bridge.paths, plug=bridge.plug)
        script = cls.opening(bridge, "en")
        script["advanced-statement " + PYTHON] = [bridge("advanced-statement", {"capability": PYTHON, "locale": "en"})]
        script["advanced-python"] = [RUNNING]
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}, {"do": "choose", "id": PYTHON},
                 {"do": "look"}, {"do": "tick_python"}, {"do": "look"},
                 {"do": "page", "name": "overview"}, {"do": "tick_python"}, {"do": "tick_python"},
                 {"do": "page", "name": "settings"}, {"do": "tick_python"}, {"do": "look"},
                 {"do": "show"}, {"do": "tick_python"}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {}

    def test_the_timer_reads_only_while_the_card_is_on_screen(self):
        """Fails with PollPython's page check reverted: the three ticks off screen read too."""
        result, _ = self.of("scenario_python_card_off_screen")
        reads = [line for line in result["sent"] if line.split(" ", 1)[0] == "advanced-python"]
        # Not turned on, the card is not read as it opens: one tick on screen, none on the Overview or Settings, one
        # back on the page.
        self.assertEqual(len(reads), 2, reads)
        self.assertEqual([look["page"] for look in result["looks"]], ["advanced", "advanced", "settings", "advanced"])

    def test_the_place_found_again_in_cards_built_again(self):
        """PlaceOf and AtPlace: the control at the same place of a tree built again, nothing where it has no such place."""
        exe = self.exe
        script = Path(self.folder.name) / "places.ps1"
        script.write_text(PLACES, encoding="utf-8")
        run = subprocess.run([str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-File", str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=300, creationflags=NO_WINDOW, env=dict(os.environ, CAR_EXE=str(exe)))
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        found = json.loads(run.stdout)
        self.assertEqual(found["place"], [2, 1])
        self.assertEqual(found["found"], "2.1")
        self.assertTrue(found["same_place_other_tree"])
        self.assertTrue(found["gone"])
        self.assertTrue(found["outside"])
        self.assertTrue(found["root"])


class SourceTests(unittest.TestCase):
    GUI = Path(__file__).resolve().parents[2] / "advanced" / "gui"

    def test_a_rebuild_keeps_the_keyboard_on_the_python_card(self):
        """Fails with the rebuild sending the keyboard back to the list from the Python version card."""
        page = (self.GUI / "AdvancedPage.cs").read_text(encoding="utf-8")
        shown = guiscan.type_body("SettingsForm", page)
        shown = shown[shown.index("private void ShowAdvancedDetail()"):shown.index("private void BuildAdvancedCards(")]
        self.assertIn("List<int> pythonPlace = focused && advancedOpen == PythonId ? PlaceOf(advancedStack, FocusedControl()) : null;",
                      shown)
        self.assertLess(shown.index("PlaceOf(advancedStack"), shown.index("advancedStack.Controls.Clear();"))
        self.assertLess(shown.index("!FocusPlace(pythonPlace)"), shown.index("advancedList.Focus();"))

    def test_the_timer_asks_only_on_screen(self):
        pythons = (self.GUI / "AdvancedPythons.cs").read_text(encoding="utf-8")
        poll = pythons[pythons.index("private void PollPython()"):pythons.index("internal static List<int> PlaceOf(")]
        self.assertIn("if (pythonPolling || advancedOpen != PythonId || currentPage != AdvancedPageName) return;", poll)


if __name__ == "__main__":
    unittest.main()

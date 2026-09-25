r"""One rule for the word and the light a header shows, held against all three headers (v0.6.10).

Until v0.6.10 three hand-written copies decided what the popup, the Codex panel and the settings
window said the watcher was doing, and they disagreed about one moment: an incompatible engine was
"attention" in the popup and "waiting" in the other two, a record being withdrawn was "recovering"
everywhere but the window, an older watcher still owning the state counted only in the window, and
only the popup drew a stopped watcher's light amber and breathing. `tests/data/light_states.json`
is the rule as a table - what a surface read, and the word and light it must show - and this file
runs every vector through each implementation in its own language:

  * the popup: `ui/popup/model.activity` and `light_for`, and the view the window draws from;
  * the panel: `activity` and `lightFor` in `mcp/assets/panel.js`, run in Node - which, drawn once
    and never redrawn, has no clock and so says waiting where the others say checking (`panel`);
  * the window: `SettingsForm.ActivityWord`, `HeaderLight` and `Activity`, compiled with csc and
    called through reflection, as tests/test_gui_v065_taskbar.py calls it.

The words under the headline are one set too: the window's `HeroFacts` is held to the panel's
`heroFacts`, in English and in Korean, from the catalogs the two are served.

The taskbar button (`SettingsForm.TrayActivity`) is not held to the table: it keeps the
notification-area icon's own rule on purpose, with a failure nobody has seen red (standard J14),
which no header shows. The vectors that carry `taskbar` say so.
"""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import guiscan  # noqa: E402
from test_mcpui_v063 import NODE, run_javascript  # noqa: E402

from codex_auto_resume import brand, l10n, machine  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import model as popup_model  # noqa: E402

TABLE_PATH = ROOT / "tests" / "data" / "light_states.json"
TABLE = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
VECTORS = TABLE["vectors"]
NOW = TABLE["now"]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
FACT_LANGUAGES = ("en", "ko")
SEPARATOR = "\x1f"


def panel_expected(vector):
    """The word and light the panel shows: the vector's, except where it says the panel's own."""
    own = vector.get("panel") or {}
    return own.get("word", vector["word"]), own.get("light", vector["light"])


@lru_cache(maxsize=None)
def panel_answers():
    """Each vector through the panel's own code: [word, light, {language: facts}]. Facts only where there is a
    status, as the panel is always handed one."""
    cases = [[vector["status"], vector["rows"]] for vector in VECTORS]
    catalogs = {language: l10n.catalog(language) for language in FACT_LANGUAGES}
    return run_javascript(["t", "fill", "activity", "attentionCause", "lightFor", "heroFacts"], """
      var catalogs = %s;
      var out = %s.map(function (c) {
        var word = activity(c[0], c[1]);
        var facts = {};
        if (c[0] !== null) {
          Object.keys(catalogs).forEach(function (language) {
            S = catalogs[language];
            facts[language] = heroFacts(c[0], word, c[1]);
          });
        }
        return [word, lightFor(c[0], word, c[1]), facts];
      });
      process.stdout.write(JSON.stringify(out));
    """ % (json.dumps(catalogs, ensure_ascii=False), json.dumps(cases)))


# ------------------------------------------------------------------------------------------ the table
class TableTests(unittest.TestCase):
    """The table is the rule, so it is held to the product's own vocabularies first."""

    def test_every_vector_is_named_once_and_says_a_word_and_a_light(self):
        names = [vector["name"] for vector in VECTORS]
        self.assertEqual(len(names), len(set(names)))
        for vector in VECTORS:
            with self.subTest(vector["name"]):
                self.assertIn(vector["word"], popup.STATES)
                self.assertIn(vector["light"], brand.STATUS_FILL)
                self.assertNotEqual(vector["light"], "failed", "red is the icon's, never a header's (J14)")

    def test_the_light_is_the_word_except_for_a_watcher_not_known_to_run(self):
        """Not known to run: the status does not say it runs, or a row is held for a watcher that is not - the list
        and the status read a moment apart, and a light that moves beside "Watcher not running" would claim both."""
        held = []
        for vector in VECTORS:
            with self.subTest(vector["name"]):
                stopped = any("engine_unavailable" in row["overlays"] for row in vector["rows"] or ())
                said = (vector["status"] or {}).get("watcher_running") is True
                running = said and not stopped
                self.assertEqual(vector["light"], vector["word"] if running else "idle")
                if not running:
                    self.assertEqual(vector["word"], "attention")
                if said and stopped:
                    held.append(vector["name"])
        self.assertTrue(held, "the table holds a status that says the watcher runs beside a row held for it stopped")

    def test_every_word_and_light_the_rule_can_give_is_in_the_table(self):
        self.assertEqual({vector["word"] for vector in VECTORS}, set(popup.STATES))
        self.assertEqual({vector["light"] for vector in VECTORS}, set(popup.STATES) | {"idle"})

    def test_every_word_is_in_every_language(self):
        for locale in l10n.LOCALES:
            catalog = l10n._read(locale)
            for word in popup.STATES:
                with self.subTest(locale=locale, word=word):
                    self.assertTrue(catalog.get("activity." + word, "").strip())

    def test_the_rows_are_what_the_control_layer_describes(self):
        """Each row's code is the public code of its state (machine.public_code), its overlays are overlays the
        control layer writes, and a row waits exactly when its code is not one of `moving`."""
        moving = set(TABLE["moving"])
        self.assertEqual(moving, set(popup_model.MOVING_CODES))
        self.assertEqual(moving & set(machine.WAITING_CODES), set())
        for vector in VECTORS:
            for row in vector["rows"] or ():
                with self.subTest(vector=vector["name"], state=row["state"]):
                    codes = {machine.public_code(dict(row, last_error=error, queue_id=queue))
                             for error in (None, "queue_process_not_started") for queue in (None, "queue-entry")}
                    self.assertIn(row["code"], codes)
                    self.assertNotIn(row["state"], machine.TERMINAL)
                    self.assertEqual(row["code"] in moving, row["state"] not in machine.WAITING)
                    self.assertLessEqual(set(row["overlays"]), set(machine.OVERLAYS))

    def test_the_panel_parts_only_where_a_time_has_come(self):
        """The panel is drawn once from one tool result, so it has no clock to say a time has come by (the critic's
        correction to F5): it says waiting, and each row says "due now". Nowhere else does it part."""
        for vector in VECTORS:
            with self.subTest(vector["name"]):
                if vector["word"] == "checking":
                    self.assertEqual(vector.get("panel"), {"word": "waiting", "light": "waiting"})
                else:
                    self.assertNotIn("panel", vector)

    def test_the_taskbar_keeps_its_red_and_no_header_shows_it(self):
        with_taskbar = [vector for vector in VECTORS if "taskbar" in vector]
        red = [vector for vector in with_taskbar if vector["taskbar"] == "failed"]
        self.assertTrue(red)
        for vector in red:
            self.assertTrue(vector["status"]["failure_unseen"])
            self.assertNotEqual(vector["light"], "failed")


# ------------------------------------------------------------------------------------------ the popup
class PopupTests(unittest.TestCase):
    def test_the_popup_says_each_vector_s_word_and_light(self):
        for vector in VECTORS:
            with self.subTest(vector["name"]):
                word = popup.activity(vector["status"], vector["rows"], NOW)
                self.assertEqual(word, vector["word"])
                self.assertEqual(popup.light_for(vector["status"], word, vector["rows"]), vector["light"])

    def test_the_view_it_draws_is_that_word_and_that_light(self):
        english = l10n.catalog("en")
        for vector in VECTORS:
            with self.subTest(vector["name"]):
                vm = popup.view_model(vector["rows"], vector["status"], english, NOW)
                self.assertEqual((vm["state"], vm["light"]), (vector["word"], vector["light"]))
                self.assertEqual(vm["state_text"], english["activity." + vector["word"]])


# ------------------------------------------------------------------------------------------ the panel
@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelTests(unittest.TestCase):
    def test_the_panel_says_each_vector_s_word_and_light(self):
        answers = panel_answers()
        self.assertEqual(len(answers), len(VECTORS))
        for vector, (word, light, _) in zip(VECTORS, answers):
            with self.subTest(vector["name"]):
                self.assertEqual((word, light), panel_expected(vector))

    def test_a_running_watcher_that_needs_a_person_says_why_and_not_that_recovery_is_on(self):
        english = l10n.catalog("en")
        for vector, (word, _, facts) in zip(VECTORS, panel_answers()):
            status = vector["status"]
            if word != "attention" or status is None:
                continue
            with self.subTest(vector["name"]):
                said = facts["en"]
                self.assertNotIn(english["status.recovery_on"], said)
                if status.get("watcher_running") is True:
                    self.assertEqual(len(said), 2)
                    self.assertNotIn(english["status.unknown"], said)
                    self.assertNotIn(english["status.recovery_idle"], said)


# ------------------------------------------------------------------------------------------ the window
PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$parse = $assembly.GetType('CodexAutoResume.Json', $true).GetMethod('Parse', $static)
$utf8 = New-Object Text.UTF8Encoding $false
function Read-Json([string]$path) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText($path, $utf8))) }
$methods = @{}
foreach ($name in @('ActivityWord', 'HeaderLight', 'Activity', 'HeroFacts', 'TrayActivity')) {
    $methods[$name] = $form.GetMethod($name, $static)
    if (-not $methods[$name]) { throw ('missing ' + $name) }
}
$table = Read-Json $env:CAR_VECTORS
$catalogs = Read-Json $env:CAR_CATALOGS
$now = [double]$table['now']
$separator = [string][char]31
$out = @()
foreach ($vector in $table['vectors']) {
    $status = $vector['status']
    $rows = $vector['rows']
    $word = [string]$methods['ActivityWord'].Invoke($null, [object[]]@($status, $rows, $now))
    $light = [string]$methods['HeaderLight'].Invoke($null, [object[]]@($status, $rows, $word))
    $activity = [string]$methods['Activity'].Invoke($null, [object[]]@($status, $rows, $now))
    $tray = [string]$methods['TrayActivity'].Invoke($null, [object[]]@($status, $rows, $now))
    $facts = @{}
    if ($null -ne $status) {
        foreach ($language in $catalogs.Keys) {
            $said = $methods['HeroFacts'].Invoke($null, [object[]]@($catalogs[$language], $status, $rows, $word))
            $facts[[string]$language] = [string]::Join($separator, $said.ToArray())
        }
    }
    $out += ,@([string]$vector['name'], $word, $light, $activity, $tray, $facts)
}
[IO.File]::WriteAllText($env:CAR_OUT, (ConvertTo-Json -InputObject $out -Depth 5 -Compress), $utf8)
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowTests(unittest.TestCase):
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
        catalogs = work / "catalogs.json"
        catalogs.write_text(json.dumps({language: l10n.catalog(language) for language in FACT_LANGUAGES},
                                       ensure_ascii=False), encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        out = work / "result.json"
        cls.result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_VECTORS=str(TABLE_PATH), CAR_CATALOGS=str(catalogs),
                     CAR_OUT=str(out)))
        cls.answer = (json.loads(out.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and out.is_file() else [])

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def rows(self):
        self.assertEqual([row[0] for row in self.answer], [vector["name"] for vector in VECTORS])
        return zip(VECTORS, self.answer)

    def test_the_window_says_each_vector_s_word_and_light(self):
        for vector, (_, word, light, activity, _, _) in self.rows():
            with self.subTest(vector["name"]):
                self.assertEqual(word, vector["word"])
                self.assertEqual(light, vector["light"])
                # Activity, what the header dot and the taskbar tests read, is that light.
                self.assertEqual(activity, vector["light"])

    def test_the_taskbar_keeps_the_icon_s_rule_where_the_table_says(self):
        for vector, (_, _, _, _, tray, _) in self.rows():
            if "taskbar" in vector:
                with self.subTest(vector["name"]):
                    self.assertEqual(tray, vector["taskbar"])

    @unittest.skipUnless(NODE, "needs Node to run the panel's own code")
    def test_the_window_s_facts_are_the_panel_s(self):
        """The words under the headline, in each language the window and the panel are served: the same facts in
        the same order. The panel's soonest check, a clock time, is its own (soonestFact) and not among them."""
        for (vector, (_, _, _, _, _, facts)), (_, _, panel) in zip(self.rows(), panel_answers()):
            if vector["status"] is None:
                continue
            for language in FACT_LANGUAGES:
                with self.subTest(vector=vector["name"], language=language):
                    self.assertEqual(facts[language].split(SEPARATOR), panel[language])

    def test_every_fact_is_the_catalog_s(self):
        """Nothing under the headline is an English fallback in another language."""
        for language in FACT_LANGUAGES:
            said = set(l10n.catalog(language).values())
            for vector, (_, _, _, _, _, facts) in self.rows():
                if vector["status"] is None:
                    continue
                for fact in facts[language].split(SEPARATOR):
                    with self.subTest(vector=vector["name"], language=language, fact=fact):
                        self.assertTrue(fact in said or any(fact == value.replace("{n}", str(n))
                                                            for value in said if "{n}" in value
                                                            for n in range(2, 10)))


if __name__ == "__main__":
    unittest.main()

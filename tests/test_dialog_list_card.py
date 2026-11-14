r"""v0.6.20 (the owner, 2026-10-28): a dialog's list is on the same card History's is, made in one place.

The progress log (Timeline), the log, Install another version and the advanced edition's Find a conversation used to
put their list in a plain Panel on the canvas: no card, no white surface, no lift. They call `DialogListCard` now
(gui/Dashboard.cs, beside `ListCard`): a ground that fills the dialog's middle, with the room round the card that
History's page keeps, holding `ListCard(list)` - the SoftCard that holds the soft list host. The rows stay the flat
hairline rows every list here has.

* The source: the helper is the one place; the three dialogs here call it and make no host or panel of their own;
  `new SoftListHost` is written once in the window, in `ListCard`.
* The built dialogs, never shown: the layout audit (gui/WindowAudit.cs, ListOffCard) walks up from each list and reports
  a list whose host is not in a SoftCard, whose card does not stand on a ground, or with a plain Panel between that
  ground and the dialog. Run here at 100% and 200%, in English, with the lists it audited named. The fourth, Find a
  conversation, is built and held to the same in advanced/tests/test_advanced_page_find.py.

GUI test module (it compiles the window): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import time
import unittest

import guiscan
from codex_auto_resume import settings
from test_gui_layout import fullest_snapshot
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, reply, run_probe

ROOT = Path(__file__).resolve().parents[1]
TYPE = "SettingsForm"
DIALOGS = (("Timeline", "BuildTimeline"), ("Log", "BuildLogs"), ("Install another version", "BuildVersions"))


class SourceTests(unittest.TestCase):
    def test_the_helper_is_a_ground_holding_the_card_with_the_pages_room(self):
        helper = guiscan.member_body(TYPE, "DialogListCard")
        self.assertIn("new SoftStack()", helper, "a ground, so the card's lift is drawn")
        self.assertIn("DockStyle.Fill", helper)
        self.assertIn("ground.Padding = CardRoom();", helper, "the room History's page keeps for the lift")
        self.assertIn("ListCard(list)", helper, "History's card itself, not a copy of it")
        self.assertNotIn("new Panel()", helper)
        self.assertNotIn("new SoftListHost", helper, "the host is the card's")
        self.assertIn("ColumnStyle(SizeType.Percent, 100f)", helper)
        self.assertIn("RowStyle(SizeType.Percent, 100f)", helper)

    def test_the_history_page_and_the_dialogs_share_the_card(self):
        card = guiscan.member_body(TYPE, "ListCard")
        self.assertIn("new SoftCard()", card)
        self.assertIn("new SoftListHost(list)", card)
        self.assertIn("ListCard(historyList)", guiscan.member_body(TYPE, "BuildHistory"))

    def test_each_dialog_makes_its_list_through_the_helper_and_no_host_or_panel_of_its_own(self):
        for name, builder in DIALOGS:
            with self.subTest(name):
                body = guiscan.member_body(TYPE, builder)
                self.assertRegex(body, r"DialogListCard\(view\)")
                self.assertNotIn("new SoftListHost", body)
                self.assertNotIn("new Panel()", body, "a plain panel round the list is the card it lacked")

    def test_the_find_dialog_does_too(self):
        source = (ROOT / "advanced" / "gui" / "AdvancedFind.cs").read_text(encoding="utf-8")
        start = source.index("private Form BuildFind()")
        body = guiscan._block(source, source.index("{", start))
        self.assertIn("DialogListCard(findList)", body)
        self.assertNotIn("new SoftListHost", body)
        self.assertNotIn("new Panel()", body)

    def test_the_soft_list_host_is_made_once_in_the_window_and_in_the_card(self):
        made = [name for name in guiscan.manifest()
                for _ in re.finditer(r"new SoftListHost\(", guiscan.read(name))]
        self.assertEqual(made, ["gui/Dashboard.cs"], "a list's host is made by ListCard and nowhere else")
        for path in (ROOT / "advanced" / "gui").glob("*.cs"):
            with self.subTest(path.name):
                self.assertNotIn("new SoftListHost(", path.read_text(encoding="utf-8"))

    def test_the_audit_holds_every_list_to_a_card_on_a_ground(self):
        audit = guiscan.member_body(TYPE, "AuditList")
        self.assertIn("ListOffCard(list)", audit)
        off = guiscan.member_body(TYPE, "ListOffCard")
        for needle in ("as SoftListHost", "as SoftCard", "is ISoftGround", "typeof(Panel)"):
            self.assertIn(needle, off)


AUDIT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
# A probe that hosts forms never shows a dialog on the owner's desktop: an error is thrown, caught and ends the probe.
[Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
try {
  $assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
  $static = [Reflection.BindingFlags]'Static,NonPublic,Public'
  $form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
  $audit = $form.GetMethod('LayoutAuditAt', $static)
  $cards = $form.GetField('AuditedCards', $static)
  $utf8 = New-Object Text.UTF8Encoding $false
  $work = [string]$env:CAR_WORK
  $schema = [IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)
  $current = [IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)
  $snapshot = [IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)
  $catalog = [IO.File]::ReadAllText((Join-Path $work 'strings-en.json'), $utf8)
  $out = @{ audit = @{}; cards = @{} }
  foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
    $key = ([double]$scale).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
    $out.audit[$key] = [string]$audit.Invoke($null, [object[]]@($schema, $current, $catalog, $snapshot, [double]$scale, [double]1.0))
    $out.cards[$key] = [string]$cards.GetValue($null)
  }
  [IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 5 -Compress), $utf8)
} catch {
  [Console]::Error.WriteLine([string]$_)
  exit 1
}
"""

SCALES = (1.0, 2.0)


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class BuiltDialogTests(unittest.TestCase):
    """The dialogs built and laid out, never shown, by the layout audit; the lists it names stand on a card."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = compile_window(work)
        current = dict(settings.defaults(), continuation_style="custom", custom_message_mode="per_reason")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False),
                                            encoding="utf-8")
        (work / "strings-en.json").write_text(json.dumps(reply("en"), ensure_ascii=False), encoding="utf-8")
        cls.answer = run_probe(AUDIT, work, 1500, CAR_EXE=str(exe), CAR_SCALES=json.dumps(list(SCALES)))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_every_dialog_list_the_audit_names_stands_on_a_card_on_a_ground(self):
        for scale in SCALES:
            key = "%.2f" % scale
            with self.subTest(scale=scale):
                self.assertNotIn("not on a card", self.answer["audit"][key])
                seen = self.answer["cards"][key].split(";")
                for place in ("timeline", "logs", "versions", "pending", "history"):
                    self.assertIn(place, seen, "the audit looked at %s's list" % place)

    def test_nothing_is_cut_off_with_the_card_round_the_lists(self):
        for scale in SCALES:
            report = self.answer["audit"]["%.2f" % scale]
            with self.subTest(scale=scale):
                self.assertEqual(report, "", "\n" + "\n".join(report.splitlines()[:40]))


if __name__ == "__main__":
    unittest.main()

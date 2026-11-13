r"""A page pressed before it is ready is made ready first, a step a turn, and shown then (v0.6.23, the final's live
acceptance G5/R4 and the tracer's runs on the owner's installation, 2026-11-14).

Settings pressed while it was still being made ready - its editors not all built, its native controls not made - was
finished in the click, in one turn of the window's thread: 1.5 s on a quiet PC (the tracer's `show settings`, mostly its
drop-downs' windows made), 4.1 s under load; pressed before its settings had even been read, the editors were built at
once as the answer came (2.7-3.2 s on months of scratch data with a real bridge). The Advanced features page was never
made ready ahead (AdvancedReadyAhead was false) and was built in the click: 650-750 ms.

Now a press of Settings (and of the Advanced features page) before it is ready leaves the page on screen as it is, makes
the pressed page ready in the steps making it ready ahead takes, one an idle turn with whatever waits going first
(FinishFirst, UrgentStep), and shows it once it is - the page a person sees is the one shown after making it ready ahead
(the render-mode pixel proof). Settings is made ready first among the pages (PrepareOrder), and the Advanced features
page is built ahead in three steps with what they make held from laying itself out (AdvancedSteps, HeldAsBuilt).

The live probe: the real window, standard edition, shown far off the screen in a frame that is never activated, answered
from the pictures' pinned scratch installation as the render mode is; its idle turns raised one at a time. What it counts
is controls and native windows made inside the click and in each turn, never time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ADVANCED_PAGE = ROOT / "advanced" / "gui" / "AdvancedPage.cs"


class SourceTests(unittest.TestCase):
    def test_settings_pressed_before_it_is_ready_is_made_ready_first(self):
        show = guiscan.member_body("SettingsForm", "ShowPage")
        first = show.index('if (name == "settings" && FinishFirst(name, delegate { ShowPage("settings"); })) return;')
        self.assertLess(first, show.index("BuildPendingEditors();"), "made ready first, before anything is built in the click")
        self.assertLess(first, show.index("PageFor(name)"))

    def test_a_step_a_turn_and_one_more_turn_asked_for(self):
        step = guiscan.member_body("SettingsForm", "UrgentStep")
        self.assertIn("BuildEditorsStep();", step)
        self.assertIn("try { ready = !PrepareNext(); }", step)
        self.assertIn("Nudge();", step)
        self.assertNotIn("while (", step, "one step a turn")
        self.assertIn("urgentPage != null ||", guiscan.member_body("SettingsForm", "IdleStepWaits"))

    def test_settings_is_made_ready_first_among_the_pages(self):
        self.assertIn("foreach (string name in PrepareOrder)", guiscan.member_body("SettingsForm", "NextToPrepare"))
        dashboard = guiscan.read("gui/Dashboard.cs")
        self.assertIn('PrepareOrder = { "settings", "overview", "pending", "history", "statistics", "diagnostics" };', dashboard)

    @unittest.skipUnless(ADVANCED_PAGE.is_file(), "the advanced edition's sources are not in this tree")
    def test_the_advanced_features_page_is_made_ready_ahead_in_steps(self):
        page = ADVANCED_PAGE.read_text(encoding="utf-8")
        self.assertIn("private static readonly bool AdvancedReadyAhead = true;", page)
        steps = guiscan._block(page, page.index("private IEnumerator<bool> AdvancedSteps(PageBuild build)"))
        self.assertEqual(steps.count("yield return true;"), 2, "its frame, its list and its cards each a step")
        self.assertLess(steps.index("AdvancedFrame()"), steps.index("FillAdvancedList();"))
        self.assertLess(steps.index("FillAdvancedList();"), steps.index("ShowAdvancedDetail();"))
        built = guiscan._block(page, page.index("private Control AdvancedPageBuilt()"))
        self.assertIn("pageBuilds.TryGetValue(AdvancedPageName, out begun)", built)
        self.assertIn("LetGoBuilt(begun);", built)
        shown = guiscan._block(page, page.index("private void ShowAdvanced()"))
        self.assertLess(shown.index("if (FinishFirst(AdvancedPageName, ShowAdvanced)) return;"), shown.index("AdvancedPageBuilt()"))
        self.assertLess(shown.index("LetGoAll();"), shown.index("AdvancedPageBuilt()"))
        frame = guiscan._block(page, page.index("private Control AdvancedFrame()"))
        for held in ("HeldAsBuilt(new SoftStack())", "HeldAsBuilt(new SoftPage())"):
            self.assertIn(held, frame)


PROBE = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed class PressedFrame : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; }
        }
    }

    internal static class PressedProbe
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            try { return SettingsForm.PressedRun(argv[0], argv[1]); }
            catch (Exception e) { File.WriteAllText(argv[1], "{\"error\":" + Json.Write(e.ToString()) + "}"); return 3; }
        }
    }

    internal sealed partial class SettingsForm
    {
        private static void PressedPump(int ms, Func<bool> until)
        {
            var all = System.Diagnostics.Stopwatch.StartNew();
            while (all.ElapsedMilliseconds < ms)
            {
                Application.DoEvents();
                if (until != null && until()) return;
                System.Threading.Thread.Sleep(5);
            }
        }

        // Controls under `parent`, and how many of them have a native window.
        private static int[] Made(Control parent)
        {
            var n = new int[2];
            foreach (Control child in parent.Controls)
            {
                n[0]++;
                if (child.IsHandleCreated) n[1]++;
                int[] inner = Made(child);
                n[0] += inner[0];
                n[1] += inner[1];
            }
            return n;
        }

        // The window off the screen as the idle-turns probe has it - but not in the render mode, which shows a page
        // the moment it is asked (FinishFirst never waits there).
        private static SettingsForm PressedWindow(PressedFrame frame)
        {
            frame.FormBorderStyle = FormBorderStyle.None;
            frame.ShowInTaskbar = false;
            frame.StartPosition = FormStartPosition.Manual;
            frame.Location = new Point(-30000, -30000);
            string nowhere = Path.Combine(Path.GetTempPath(), "car-pressed-nowhere");
            var form = new SettingsForm(new PersistentBridge(nowhere, new Bridge(nowhere)), RenderAnswer("strings", null), null);
            form.rendering = true;
            Size opened = form.ClientSize;
            form.TopLevel = false;
            form.FormBorderStyle = FormBorderStyle.None;
            form.Location = Point.Empty;
            frame.ClientSize = opened;
            form.ClientSize = opened;
            frame.Controls.Add(form);
            form.Visible = true;
            frame.Show();
            if (form.currentPage == null) form.OnLoad(EventArgs.Empty);
            if (!form.shown) form.OnShown(EventArgs.Empty);
            form.rendering = false;
            return form;
        }

        // Idle turns, each after the messages waiting, until `until` or `most` turns; how many it took, and the most controls
        // and native windows of Settings any one of them made.
        private static int[] Turns(SettingsForm form, int most, Func<bool> until)
        {
            int turns = 0, mostMade = 0, mostWindows = 0;
            int[] before = Made(form.columns);
            while (turns < most && !until())
            {
                Application.DoEvents();
                Application.RaiseIdle(EventArgs.Empty);
                turns++;
                int[] now = Made(form.columns);
                mostMade = Math.Max(mostMade, now[0] - before[0]);
                mostWindows = Math.Max(mostWindows, now[1] - before[1]);
                before = now;
                System.Threading.Thread.Sleep(1);
            }
            return new[] { turns, mostMade, mostWindows };
        }

        internal static int PressedRun(string answersPath, string outPath)
        {
            Theme.Opened = "light";
            Design.Opened = "soft";
            Palette.AdoptDesign("soft");
            Palette.Adopt(Theme.Current("light"));
            var job = Json.Parse(File.ReadAllText(answersPath, new UTF8Encoding(false))) as Dictionary<string, object>;
            renderAnswers = Items(job, "answers");
            PersistentBridge.Answers = RenderAnswer;
            DialogAnswers = delegate { return false; };
            var outMap = new Dictionary<string, object>();

            // 1. Pressed while its editors are being built on the idle turns.
            var frame = new PressedFrame();
            var form = PressedWindow(frame);
            PressedPump(30000, delegate { return form.settingsRead && form.snapshot != null && form.buildQueued; });
            for (int i = 0; i < 3; i++) Application.RaiseIdle(EventArgs.Empty);
            outMap["editors_left"] = form.pendingSchema != null || form.editorSteps != null;
            int[] before = Made(form.columns);
            form.navButtons["settings"].PerformClick();
            int[] after = Made(form.columns);
            outMap["click_made"] = (double)(after[0] - before[0]);
            outMap["click_windows"] = (double)(after[1] - before[1]);
            outMap["page_after_click"] = form.currentPage;
            int[] turns = Turns(form, 3000, delegate { return form.currentPage == "settings"; });
            outMap["turns"] = (double)turns[0];
            outMap["most_made_in_a_turn"] = (double)turns[1];
            outMap["most_windows_in_a_turn"] = (double)turns[2];
            int[] whole = Made(form.columns);
            outMap["made"] = (double)whole[0];
            outMap["windows"] = (double)whole[1];
            outMap["shown"] = form.currentPage;
            outMap["editors"] = (double)form.editors.Count;
            outMap["prepared"] = form.preparedPages.Contains("settings");
            outMap["visible"] = Soft.OwnVisible(form.columns) && form.columns.IsHandleCreated;
            frame.Close();
            frame.Dispose();

            // 2. Pressed before its settings have been read: nothing is shown in the click, and the answer, when it comes,
            // is built a step a turn rather than all in the turn it comes in.
            frame = new PressedFrame();
            form = PressedWindow(frame);
            outMap["read_at_press"] = form.settingsRead;
            form.navButtons["settings"].PerformClick();
            outMap["early_page_after_click"] = form.currentPage;
            int madeAtAnswer = -1;
            var clock = System.Diagnostics.Stopwatch.StartNew();
            while (clock.ElapsedMilliseconds < 30000 && !form.settingsRead)
            {
                Application.DoEvents();
                if (form.settingsRead) madeAtAnswer = Made(form.columns)[0];
                System.Threading.Thread.Sleep(2);
            }
            outMap["made_when_answered"] = (double)madeAtAnswer;
            turns = Turns(form, 3000, delegate { return form.currentPage == "settings"; });
            outMap["early_turns"] = (double)turns[0];
            outMap["early_most_made_in_a_turn"] = (double)turns[1];
            outMap["early_made"] = (double)Made(form.columns)[0];
            outMap["early_shown"] = form.currentPage;
            frame.Close();
            frame.Dispose();

            // 3. Another page pressed meanwhile is shown at once, and Settings is not shown after it.
            frame = new PressedFrame();
            form = PressedWindow(frame);
            PressedPump(30000, delegate { return form.settingsRead && form.snapshot != null && form.buildQueued; });
            form.navButtons["settings"].PerformClick();
            outMap["dropped_waiting"] = form.currentPage;
            form.navButtons["history"].PerformClick();
            outMap["dropped_page_after"] = form.currentPage;
            Turns(form, 400, delegate { return false; });
            outMap["dropped_page_later"] = form.currentPage;
            frame.Close();
            frame.Dispose();

            lock (RenderMisses) outMap["misses"] = new List<object>(RenderMisses.ToArray());
            File.WriteAllText(outPath, Json.Write(outMap), new UTF8Encoding(false));
            return 0;
        }
    }
}
"""


@unittest.skipUnless(os.name == "nt" and CSC.is_file(), "needs Windows and the in-box C# compiler")
class PressedTests(unittest.TestCase):
    """The real window off the screen, Settings pressed before it is ready, its idle turns raised one at a time."""

    @classmethod
    def setUpClass(cls):
        import advanced_shots
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        read, _envelope = advanced_shots.read_answers("standard", "base", "en")
        answers = work / "answers.json"
        answers.write_text(json.dumps(advanced_shots.form_answers(read), ensure_ascii=False), encoding="utf-8")
        probe = work / "PressedProbe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        exe = work / "Pressed.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                                "/main:CodexAutoResume.PressedProbe", "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
                                "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                                *[str(path) for path in guiscan.sources()], str(probe)],
                               capture_output=True, timeout=600, creationflags=NO_WINDOW)
        cls.failure = None if built.returncode == 0 else built.stdout.decode("mbcs", "replace")[-3000:]
        cls.answer = {}
        if cls.failure is None:
            out = work / "out.json"
            environment = dict(os.environ, CODEX_HOME=str(work / "no-codex"), LOCALAPPDATA=str(work / "no-local"))
            done = subprocess.run([str(exe), str(answers), str(out)], capture_output=True, timeout=300,
                                  creationflags=NO_WINDOW, env=environment)
            cls.answer = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
            if done.returncode != 0 or "error" in cls.answer:
                cls.failure = "the probe failed (exit %d): %s" % (done.returncode, cls.answer.get("error"))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if self.failure:
            self.fail(self.failure)

    def test_every_read_was_answered(self):
        self.assertEqual(self.answer["misses"], [])
        self.assertTrue(self.answer["editors_left"], "Settings was pressed with editors still to build")

    def test_the_click_builds_nothing_and_shows_nothing_yet(self):
        self.assertEqual(self.answer["click_made"], 0, "editors built in the click")
        self.assertEqual(self.answer["click_windows"], 0, "native windows made in the click")
        self.assertEqual(self.answer["page_after_click"], "overview")

    def test_it_is_made_ready_a_step_a_turn_and_then_shown(self):
        self.assertEqual(self.answer["shown"], "settings")
        self.assertTrue(self.answer["visible"])
        self.assertTrue(self.answer["prepared"], "shown as a page made ready ahead")
        self.assertGreater(self.answer["editors"], 20)
        self.assertGreater(self.answer["turns"], 5)
        # No turn made most of it: each took one step.
        self.assertLess(self.answer["most_made_in_a_turn"], self.answer["made"] / 2)
        self.assertLess(self.answer["most_windows_in_a_turn"], self.answer["windows"] / 2)

    def test_pressed_before_its_settings_are_read_it_waits_for_them_and_builds_them_in_steps(self):
        self.assertFalse(self.answer["read_at_press"], "pressed before the settings were read")
        self.assertEqual(self.answer["early_page_after_click"], "overview")
        self.assertGreaterEqual(self.answer["made_when_answered"], 0)
        self.assertLess(self.answer["made_when_answered"], self.answer["early_made"] / 2,
                        "the editors were built all at once as the answer came")
        self.assertEqual(self.answer["early_shown"], "settings")
        self.assertLess(self.answer["early_most_made_in_a_turn"], self.answer["early_made"] / 2)

    def test_another_page_pressed_meanwhile_is_shown_and_settings_is_not(self):
        self.assertEqual(self.answer["dropped_waiting"], "overview", "Settings was shown in the click")
        self.assertEqual(self.answer["dropped_page_after"], "history")
        self.assertEqual(self.answer["dropped_page_later"], "history")


if __name__ == "__main__":
    unittest.main()

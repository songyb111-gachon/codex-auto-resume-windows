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

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr window, int index);

        // Whether `control` paints: WM_SETREDRAW off clears WS_VISIBLE from its style while it stays Visible to .NET.
        private static bool Painting(Control control)
        {
            return (GetWindowLong(control.Handle, -16) & 0x10000000) != 0;
        }

        private static readonly System.Reflection.FieldInfo SuspendCount =
            typeof(Control).GetField("layoutSuspendCount", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        // Every control under `parent`, in order: its kind, place, size, whether it shows and its words.
        private static string Shape(Control parent)
        {
            var text = new StringBuilder();
            var next = new Stack<Control>();
            next.Push(parent);
            while (next.Count > 0)
            {
                Control control = next.Pop();
                text.Append(control.GetType().Name).Append(' ').Append(control.Bounds.ToString()).Append(' ')
                    .Append(Soft.OwnVisible(control) ? "shown" : "hidden").Append(' ').Append(control.Text).Append('\n');
                for (int i = control.Controls.Count - 1; i >= 0; i--) next.Push(control.Controls[i]);
            }
            return text.ToString();
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
            return PressedWindow(frame, null);
        }

        // `page`: the page it opens on, as a window reopened after a language save opens on Settings (--page=settings).
        private static SettingsForm PressedWindow(PressedFrame frame, string page)
        {
            frame.FormBorderStyle = FormBorderStyle.None;
            frame.ShowInTaskbar = false;
            frame.StartPosition = FormStartPosition.Manual;
            frame.Location = new Point(-30000, -30000);
            string nowhere = Path.Combine(Path.GetTempPath(), "car-pressed-nowhere");
            var form = new SettingsForm(new PersistentBridge(nowhere, new Bridge(nowhere)), RenderAnswer("strings", null), null);
            form.rendering = true;
            if (page != null) form.firstPage = page;
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
            // The owner (2026-11-14): the pressed tab chosen in the click's own turn, the one left not.
            outMap["tab_chosen_in_click"] = form.navButtons["settings"].Current && !form.navButtons["overview"].Current;
            outMap["tab_accessible_selected"] =
                (form.navButtons["settings"].AccessibilityObject.State & AccessibleStates.Selected) != 0 &&
                (form.navButtons["overview"].AccessibilityObject.State & AccessibleStates.Selected) == 0;
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
            outMap["dropped_tab"] = form.navButtons["history"].Current && !form.navButtons["settings"].Current;
            Turns(form, 400, delegate { return false; });
            outMap["dropped_page_later"] = form.currentPage;
            frame.Close();
            frame.Dispose();

            // 4. Opened on Settings, as after a language save: the editors are built a step a turn when the read comes, the
            // page host's painting held until they are all built.
            frame = new PressedFrame();
            form = PressedWindow(frame, "settings");
            outMap["opened_page"] = form.currentPage;
            outMap["opened_read_at_open"] = form.settingsRead;
            int openedTurns = 0, openedMost = 0, openedWindowsMost = 0, heldTurns = 0;
            bool heldAtEnd = true;
            int[] openedBefore = Made(form.columns);
            clock = System.Diagnostics.Stopwatch.StartNew();
            while (clock.ElapsedMilliseconds < 60000 &&
                   !(form.settingsRead && form.pendingSchema == null && form.editorSteps == null && !form.buildQueued))
            {
                Application.DoEvents();
                Application.RaiseIdle(EventArgs.Empty);
                openedTurns++;
                int[] now = Made(form.columns);
                openedMost = Math.Max(openedMost, now[0] - openedBefore[0]);
                openedWindowsMost = Math.Max(openedWindowsMost, now[1] - openedBefore[1]);
                openedBefore = now;
                if (form.settingsRead && (form.pendingSchema != null || form.editorSteps != null) && !Painting(form.pageHost)) heldTurns++;
                System.Threading.Thread.Sleep(1);
            }
            heldAtEnd = !Painting(form.pageHost);
            int[] openedWhole = Made(form.columns);
            outMap["opened_turns"] = (double)openedTurns;
            outMap["opened_most_made_in_a_turn"] = (double)openedMost;
            outMap["opened_most_windows_in_a_turn"] = (double)openedWindowsMost;
            outMap["opened_made"] = (double)openedWhole[0];
            outMap["opened_windows"] = (double)openedWhole[1];
            outMap["opened_editors"] = (double)form.editors.Count;
            outMap["opened_held_turns"] = (double)heldTurns;
            outMap["opened_held_at_end"] = heldAtEnd;
            outMap["opened_shown"] = form.currentPage;
            outMap["opened_visible"] = Soft.OwnVisible(form.columns) && form.columns.IsHandleCreated;
            SettingsForm settled = form;
            PressedPump(15000, delegate { return settled.Settled(); });
            PressedPump(300, null);
            string builtInSteps = Shape(form.columns);
            frame.Close();
            frame.Dispose();

            // 5. The same, built at once as before (a window in the render mode builds them so): the same page.
            frame = new PressedFrame();
            form = PressedWindow(frame, "settings");
            form.rendering = true;
            PressedPump(60000, delegate { return form.settingsRead && form.pendingSchema == null && form.editorSteps == null && !form.buildQueued; });
            SettingsForm atOnce = form;
            PressedPump(15000, delegate { return atOnce.Settled(); });
            PressedPump(300, null);
            string builtAtOnce = Shape(form.columns);
            outMap["shape_same"] = builtInSteps == builtAtOnce;
            outMap["shape_controls"] = (double)(builtAtOnce.Split('\n').Length);
            if (builtInSteps != builtAtOnce)
            {
                string[] a = builtInSteps.Split('\n'), b = builtAtOnce.Split('\n');
                var differ = new List<object>();
                for (int i = 0; i < Math.Min(a.Length, b.Length); i++)
                    if (a[i] != b[i]) differ.Add(a[i] + " | " + b[i]);
                outMap["shape_first_difference"] = differ.Count + " differ, lengths " + a.Length + "/" + b.Length + ": " +
                                                   string.Join(" || ", differ.GetRange(0, Math.Min(6, differ.Count)).ConvertAll(x => (string)x).ToArray());
            }
            frame.Close();
            frame.Dispose();

            // 6. A page built whole (PageFor, as the Overview before the first paint and a page on its first click are):
            // what it made is held from laying itself out until it has its place - counted as it is put in the page host.
            frame = new PressedFrame();
            form = PressedWindow(frame);
            int heldPage = -1, cards = 0, heldCards = 0;
            ControlEventHandler added = delegate(object sender, ControlEventArgs e)
            {
                heldPage = Convert.ToInt32(SuspendCount.GetValue(e.Control));
                var next = new Stack<Control>();
                next.Push(e.Control);
                while (next.Count > 0)
                {
                    Control control = next.Pop();
                    if (control is SoftCard)
                    {
                        cards++;
                        if (Convert.ToInt32(SuspendCount.GetValue(control)) > 0) heldCards++;
                    }
                    foreach (Control child in control.Controls) next.Push(child);
                }
            };
            form.pageHost.ControlAdded += added;
            bool built = !form.pages.ContainsKey("diagnostics");
            form.PageFor("diagnostics");
            form.pageHost.ControlAdded -= added;
            outMap["whole_built_here"] = built;
            outMap["whole_page_held"] = (double)heldPage;
            outMap["whole_cards"] = (double)cards;
            outMap["whole_cards_held"] = (double)heldCards;
            outMap["whole_page_let_go"] = Convert.ToInt32(SuspendCount.GetValue(form.pages["diagnostics"])) == 0;
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

    def test_the_pressed_tab_is_chosen_in_the_click_and_said_so(self):
        self.assertTrue(self.answer["tab_chosen_in_click"], "the old tab stayed chosen until the page was ready")
        self.assertTrue(self.answer["tab_accessible_selected"], "a screen reader was not told the pressed tab is selected")

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

    def test_opened_on_settings_its_editors_are_built_a_step_a_turn_behind_the_page_as_it_stands(self):
        """A window reopened after a language save opens on Settings: its editors were built all in the turn the read came
        in (1.8-2.9 s on months of scratch data), the header standing still."""
        self.assertEqual(self.answer["opened_page"], "settings")
        self.assertFalse(self.answer["opened_read_at_open"])
        self.assertEqual(self.answer["opened_shown"], "settings")
        self.assertGreater(self.answer["opened_editors"], 20)
        self.assertGreater(self.answer["opened_turns"], 5)
        self.assertLess(self.answer["opened_most_made_in_a_turn"], self.answer["opened_made"] / 2,
                        "the editors were built all at once as the read came")
        self.assertLess(self.answer["opened_most_windows_in_a_turn"], self.answer["opened_windows"] / 2)
        self.assertGreater(self.answer["opened_held_turns"], 0, "the page host painted a half-built page")
        self.assertFalse(self.answer["opened_held_at_end"], "the page host's painting was not let go")
        self.assertTrue(self.answer["opened_visible"])

    def test_opened_on_settings_the_page_built_in_steps_is_the_page_built_at_once(self):
        self.assertGreater(self.answer["shape_controls"], 50)
        self.assertTrue(self.answer["shape_same"], self.answer.get("shape_first_difference"))

    def test_a_page_built_whole_lays_nothing_out_before_it_has_its_place(self):
        """The Overview before the first paint, and a page on its first click, laid each card, grid and row out again as
        each was added (10,640 measures of the Overview's labels before the first paint on scratch, 5,760 now)."""
        self.assertTrue(self.answer["whole_built_here"])
        self.assertGreater(self.answer["whole_page_held"], 0, "the page laid itself out as it was built")
        self.assertGreater(self.answer["whole_cards"], 0)
        self.assertEqual(self.answer["whole_cards_held"], self.answer["whole_cards"], "a card laid itself out as it was built")
        self.assertTrue(self.answer["whole_page_let_go"], "the page was left held")

    def test_another_page_pressed_meanwhile_is_shown_and_settings_is_not(self):
        self.assertEqual(self.answer["dropped_waiting"], "overview", "Settings was shown in the click")
        self.assertEqual(self.answer["dropped_page_after"], "history")
        self.assertTrue(self.answer["dropped_tab"], "the tab pressed meanwhile did not take the selection")
        self.assertEqual(self.answer["dropped_page_later"], "history")


if __name__ == "__main__":
    unittest.main()

r"""What the window does on its idle turns waits for its glides and its person, and survives a step that throws (v0.6.23).

The second round's audit (design and motion F2; windows G6 and G4):

* F2 - in the first seconds after the window opened, its idle turns made the pages ready ahead (PrepareNext) and built the
  Settings editors (BuildEditorsLater), a step a turn. A step taken between two frames of a glide held the glide for the
  step's length, and the editors' steps did not wait for the mouse or the keyboard at all. Both handlers now take no step
  while a glide is on its way (Transition.Moving) or within PrepareAfterInputMilliseconds of a key or the mouse, on one
  clock (IdleStepWaits, PrepareInput, HearInput).
* G6 - a step of making a page ready that threw was taken again on every idle turn, several exceptions a second, until
  UiFaults ended the window; and a page shown kept the page host held from laying itself out when something threw while it
  was held. A step that throws is now written to errors.log once and its page given up (PrepareFailed); ShowPage lets go
  of what it holds in its finally.
* G4 - the Settings editors built again (Restore defaults, the settings read again) took the old ones off the page
  without disposing them, so each kept its window handle for the life of the process. They are disposed once the new
  ones are built.

The live probe: the real window, standard edition, shown far off the screen in a frame that is never activated, answered
from the pictures' pinned scratch installation as the render mode is; its idle turns raised one at a time.
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


class SourceTests(unittest.TestCase):
    def test_both_idle_handlers_wait_on_one_clock_and_the_glides(self):
        waits = guiscan.member_body("SettingsForm", "IdleStepWaits")
        self.assertIn("Transition.Moving > 0", waits)
        self.assertIn("prepareInput.Since < PrepareAfterInputMilliseconds", waits)
        # v0.6.23 (perffix): but for the step a pressed page takes to be made ready first (FinishFirst, prepareUrgent).
        self.assertIn("if (busy > 0 || (!prepareUrgent && (refreshing || IdleStepWaits()))) return true;",
                      guiscan.member_body("SettingsForm", "PrepareNext"))
        page = guiscan.read("gui/SettingsPage.cs")
        later = guiscan._block(page, page.index("private void BuildEditorsLater()"))
        self.assertIn("IdleStepWaits()", later)
        for handler in (later, guiscan.member_body("SettingsForm", "PreparePagesLater")):
            self.assertIn("HearInput(true);", handler)
            self.assertIn("HearInput(false);", handler)
        # The page host's holds are let go in ShowPage's finally.
        show = guiscan.member_body("SettingsForm", "ShowPage")
        final = show[show.index("finally"):]
        self.assertIn("if (hostHeld) pageHost.ResumeLayout(false);", final)


PROBE = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed class IdleTurnsFrame : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; }
        }
    }

    internal static class IdleTurnsProbe
    {
        [DllImport("user32.dll")]
        internal static extern bool PostMessage(IntPtr window, int message, IntPtr w, IntPtr l);

        [STAThread]
        internal static int Main(string[] argv)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            try { return SettingsForm.IdleTurnsRun(argv[0], argv[1], argv[2]); }
            catch (Exception e) { File.WriteAllText(argv[1], "{\"error\":" + Json.Write(e.ToString()) + "}"); return 3; }
        }
    }

    internal sealed partial class SettingsForm
    {
        // A page whose own layout throws while it is told to - a bug of a page's, standing in; and how often it threw.
        private static int[] Throwing(Control page, Func<bool> throws)
        {
            var thrown = new int[1];
            page.Layout += delegate
            {
                if (!throws()) return;
                thrown[0]++;
                throw new InvalidOperationException("the idle-turns probe: a layout that throws");
            };
            return thrown;
        }

        private static readonly System.Reflection.FieldInfo SuspendCount =
            typeof(Control).GetField("layoutSuspendCount", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        private static double Held(Control control)
        {
            return Convert.ToDouble(SuspendCount.GetValue(control));
        }

        private static void IdlePump(int ms, Func<bool> until)
        {
            var all = System.Diagnostics.Stopwatch.StartNew();
            while (all.ElapsedMilliseconds < ms)
            {
                Application.DoEvents();
                if (until != null && until()) return;
                System.Threading.Thread.Sleep(5);
            }
        }

        private static int Count(Control parent)
        {
            int n = 0;
            foreach (Control child in parent.Controls) n += 1 + Count(child);
            return n;
        }

        private static SettingsForm IdleWindow(IdleTurnsFrame frame)
        {
            frame.FormBorderStyle = FormBorderStyle.None;
            frame.ShowInTaskbar = false;
            frame.StartPosition = FormStartPosition.Manual;
            frame.Location = new Point(-30000, -30000);
            string nowhere = Path.Combine(Path.GetTempPath(), "car-idle-turns-nowhere");
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
            return form;
        }

        internal static int IdleTurnsRun(string answersPath, string outPath, string home)
        {
            Theme.Opened = "light";
            Design.Opened = "soft";
            Palette.AdoptDesign("soft");
            Palette.Adopt(Theme.Current("light"));
            var job = Json.Parse(File.ReadAllText(answersPath, new UTF8Encoding(false))) as Dictionary<string, object>;
            renderAnswers = Items(job, "answers");
            PersistentBridge.Answers = RenderAnswer;
            DialogAnswers = delegate { return false; };
            Directory.CreateDirectory(Path.Combine(home, "logs"));
            UiFaults.Follow(home, null);
            string errors = Path.Combine(Path.Combine(home, "logs"), "errors.log");
            var outMap = new Dictionary<string, object>();

            // F2: the editors and the pages made ready ahead wait for a glide and for the mouse.
            var frame = new IdleTurnsFrame();
            var form = IdleWindow(frame);
            IdlePump(30000, delegate { return form.settingsRead && form.snapshot != null && form.buildQueued && !form.IdleStepWaits(); });
            outMap["queued"] = form.buildQueued;
            int built = Count(form.columns);
            var glide = new Transition(form.stateDot, 0.0);
            glide.To(1.0, true, 60000);
            for (int i = 0; i < 20; i++) Application.RaiseIdle(EventArgs.Empty);
            outMap["editors_changed_while_moving"] = Count(form.columns) != built || !form.buildQueued;
            glide.To(1.0, false);
            outMap["moving_after"] = (double)Transition.Moving;
            Application.RaiseIdle(EventArgs.Empty);
            Application.RaiseIdle(EventArgs.Empty);
            outMap["editors_changed_once_still"] = Count(form.columns) != built;
            // A mouse move on the window, heard as the message loop takes it.
            IdleTurnsProbe.PostMessage(form.Handle, 0x0200, IntPtr.Zero, (IntPtr)((40 << 16) | 40));
            Application.DoEvents();
            // Only turns raised while the mouse is still recent count: the clock read before each, so a runner that stalls
            // past PrepareAfterInputMilliseconds between two turns (GitHub's, 2026-11-13) stops raising them, and the turns
            // it did raise are held to what they must do. A step taken on any of them fails, as before.
            built = Count(form.columns);
            int recentTurns = 0;
            bool changedAfterInput = false;
            for (int i = 0; i < 20; i++)
            {
                if (form.prepareInput.Since >= PrepareAfterInputMilliseconds - 20) break;
                Application.RaiseIdle(EventArgs.Empty);
                recentTurns++;
                if (Count(form.columns) != built || !form.buildQueued) changedAfterInput = true;
            }
            outMap["turns_after_input"] = (double)recentTurns;
            outMap["editors_changed_after_input"] = changedAfterInput;
            System.Threading.Thread.Sleep(PrepareAfterInputMilliseconds + 50);
            for (int i = 0; i < 500 && form.buildQueued; i++) Application.RaiseIdle(EventArgs.Empty);
            outMap["editors_built"] = !form.buildQueued && form.editors.Count > 20;
            // The pages made ready ahead: one step taken, then a glide, then nothing moves on.
            IdlePump(30000, delegate { return form.bridge.InFlight == 0 && !form.refreshing && !form.IdleStepWaits(); });
            for (int i = 0; i < 50 && form.preparing == null; i++) Application.RaiseIdle(EventArgs.Empty);
            outMap["preparing"] = form.preparing;
            string at = form.preparing + ":" + form.prepareStep + ":" + form.preparedPages.Count;
            glide.To(0.0, true, 60000);
            for (int i = 0; i < 20; i++) Application.RaiseIdle(EventArgs.Empty);
            outMap["pages_changed_while_moving"] = (form.preparing + ":" + form.prepareStep + ":" + form.preparedPages.Count) != at;
            glide.To(0.0, false);
            glide.Dispose();
            frame.Close();
            frame.Dispose();

            // G6: a step of making History ready that throws, every time, while History is being made ready.
            frame = new IdleTurnsFrame();
            form = IdleWindow(frame);
            IdlePump(30000, delegate { return form.settingsRead && form.snapshot != null; });
            SettingsForm shown = form;
            Control history = form.PageFor("history");
            int[] thrower = Throwing(history, delegate { return shown.preparing == "history"; });
            int thrownOut = 0, thrownElsewhere = 0;
            var clock = System.Diagnostics.Stopwatch.StartNew();
            while (clock.ElapsedMilliseconds < 60000 && thrownOut < 30)
            {
                try { Application.DoEvents(); }
                catch (InvalidOperationException) { thrownElsewhere++; }
                try { Application.RaiseIdle(EventArgs.Empty); }
                catch (InvalidOperationException) { thrownOut++; }
                if (form.snapshot != null && form.settingsRead && !form.buildQueued && !form.prepareQueued && form.bridge.InFlight == 0) break;
                System.Threading.Thread.Sleep(2);
            }
            outMap["thrower_threw"] = (double)thrower[0];
            outMap["thrown_out"] = (double)thrownOut;
            outMap["thrown_elsewhere"] = (double)thrownElsewhere;
            string logged = File.Exists(errors) ? File.ReadAllText(errors, new UTF8Encoding(false)) : "";
            int entries = 0;
            for (int i = logged.IndexOf("] the window\n", StringComparison.Ordinal); i >= 0; i = logged.IndexOf("] the window\n", i + 1, StringComparison.Ordinal)) entries++;
            outMap["logged"] = (double)entries;
            outMap["logged_the_throw"] = logged.Contains("the idle-turns probe: a layout that throws");
            outMap["prepared"] = new List<object>(form.preparedPages.ToArray());
            outMap["still_queued"] = form.prepareQueued;
            frame.Close();
            frame.Dispose();

            // G6: a page shown that throws while it is held lets go of the page host all the same.
            frame = new IdleTurnsFrame();
            form = IdleWindow(frame);
            IdlePump(30000, delegate { return form.settingsRead && form.snapshot != null && form.bridge.InFlight == 0; });
            history = form.PageFor("history");
            form.WriteIfStale("history");
            bool armed = true;
            int[] shower = Throwing(history, delegate { return armed; });
            bool threw = false;
            try { form.navButtons["history"].PerformClick(); }
            catch (InvalidOperationException) { threw = true; }
            armed = false;
            outMap["show_threw"] = threw && shower[0] > 0;
            outMap["host_held_after_throw"] = Held(form.pageHost);
            outMap["page_held_after_throw"] = Held(history);
            form.navButtons["overview"].PerformClick();
            outMap["host_held_after_next"] = Held(form.pageHost);
            outMap["overview_shown"] = form.currentPage == "overview" && Soft.OwnVisible(form.pages["overview"]);
            frame.Close();
            frame.Dispose();

            // G4: the editors built again (the settings read again, on Settings, as Restore defaults reads them) dispose
            // the ones they replace.
            frame = new IdleTurnsFrame();
            form = IdleWindow(frame);
            IdlePump(30000, delegate { return form.settingsRead && form.snapshot != null && form.bridge.InFlight == 0; });
            form.navButtons["settings"].PerformClick();
            var old = new List<Control>();
            foreach (TableLayoutPanel stack in form.sections.Values) foreach (Control control in stack.Controls) old.Add(control);
            Control oldCombo = form.interfaceCombo;
            form.Reload();
            IdlePump(30000, delegate { return form.interfaceCombo != oldCombo && !form.buildQueued && form.pendingSchema == null && form.editorSteps == null; });
            int disposed = 0;
            foreach (Control control in old) if (control.IsDisposed) disposed++;
            outMap["rebuilt"] = form.interfaceCombo != oldCombo;
            outMap["removed"] = (double)old.Count;
            outMap["removed_disposed"] = (double)disposed;
            outMap["new_ones_alive"] = !form.interfaceCombo.IsDisposed && form.interfaceCombo.Parent != null;
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
class IdleTurnTests(unittest.TestCase):
    """The real window off the screen, its idle turns raised one at a time."""

    @classmethod
    def setUpClass(cls):
        import advanced_shots
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        read, _envelope = advanced_shots.read_answers("standard", "base", "en")
        answers = work / "answers.json"
        answers.write_text(json.dumps(advanced_shots.form_answers(read), ensure_ascii=False), encoding="utf-8")
        probe = work / "IdleTurnsProbe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        exe = work / "IdleTurns.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                                "/main:CodexAutoResume.IdleTurnsProbe", "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
                                "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                                *[str(path) for path in guiscan.sources()], str(probe)],
                               capture_output=True, timeout=600, creationflags=NO_WINDOW)
        cls.failure = None if built.returncode == 0 else built.stdout.decode("mbcs", "replace")[-3000:]
        cls.answer = {}
        if cls.failure is None:
            out = work / "out.json"
            home = work / "home"
            environment = dict(os.environ, CODEX_HOME=str(work / "no-codex"), LOCALAPPDATA=str(work / "no-local"))
            done = subprocess.run([str(exe), str(answers), str(out), str(home)], capture_output=True, timeout=300,
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
        self.assertTrue(self.answer["queued"], "the editors waited for the idle turns")

    def test_the_editors_wait_while_a_glide_is_on_its_way_and_after_the_mouse(self):
        self.assertFalse(self.answer["editors_changed_while_moving"], "a step of the editors was taken in a glide's frames")
        self.assertEqual(self.answer["moving_after"], 0)
        self.assertTrue(self.answer["editors_changed_once_still"], "nothing moving: the next turn takes a step")
        self.assertGreater(self.answer["turns_after_input"], 0, "an idle turn was raised while the mouse was recent")
        self.assertFalse(self.answer["editors_changed_after_input"], "a step of the editors was taken just after the mouse")
        self.assertTrue(self.answer["editors_built"], "built all the same once the mouse was still")

    def test_the_pages_made_ready_ahead_wait_while_a_glide_is_on_its_way(self):
        self.assertIsNotNone(self.answer["preparing"])
        self.assertFalse(self.answer["pages_changed_while_moving"], "a page was made ready in a glide's frames")

    def test_a_step_that_throws_is_written_once_and_its_page_given_up(self):
        self.assertGreater(self.answer["thrower_threw"], 0, "the stand-in bug was reached")
        self.assertEqual(self.answer["thrown_out"], 0, "thrown out of the idle turn: %r" % self.answer)
        self.assertEqual(self.answer["logged"], 1)
        self.assertTrue(self.answer["logged_the_throw"])
        self.assertFalse(self.answer["still_queued"], "the pages after it were made ready all the same")
        for page in ("pending", "history", "statistics", "diagnostics", "settings"):
            self.assertIn(page, self.answer["prepared"])

    def test_a_page_that_throws_as_it_shows_lets_go_of_the_page_host(self):
        self.assertTrue(self.answer["show_threw"], "the stand-in bug was reached")
        self.assertEqual(self.answer["host_held_after_throw"], 0, "the page host left held")
        self.assertEqual(self.answer["page_held_after_throw"], 0, "the page left held")
        self.assertEqual(self.answer["host_held_after_next"], 0)
        self.assertTrue(self.answer["overview_shown"])

    def test_the_editors_built_again_dispose_the_ones_they_replace(self):
        self.assertTrue(self.answer["rebuilt"])
        self.assertGreater(self.answer["removed"], 5)
        self.assertEqual(self.answer["removed_disposed"], self.answer["removed"], "an old editor kept its handle")
        self.assertTrue(self.answer["new_ones_alive"])


if __name__ == "__main__":
    unittest.main()

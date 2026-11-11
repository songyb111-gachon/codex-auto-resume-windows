r"""The Settings editors are built a step a turn, never all in one (v0.6.23, the owner, 2026-11-11).

Built on the first idle turn after the window opened (BuildEditorsLater), the editors held the window's thread for
570-1080 ms in one turn - the longest the window took after it opened: its light stood still, a hover or a click
waited. They are now built by EditorSteps, an iterator that hands the thread back after the General cards and the
groups, every EditorSliceMilliseconds through the schema's fields, before the Continuation cards and before the page
is laid out - the same editors in the same order, only built over several turns. `buildQueued` stays set until the last
step, so whatever waits for the editors waits for all of them; a switch to Settings before then builds what is left at
once (BuildPendingEditors), and settings read again during the build start it again.

The live probe: the real window, standard edition, shown far off the screen in a frame that is never activated, answered
from the pictures' pinned scratch installation as the render mode is. Its idle turns are raised one at a time: the
editors take several; what they built, the moment the last step ends, is the very page one build makes in another window
opened alike (every control in order, its words, its own visibility, tab index and enabled state, and every editor's
value); and a press on the Settings tab after two steps shows the page a press before any step shows.
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
    def test_the_idle_turns_take_one_step_each_until_the_last(self):
        page = guiscan.read("gui/SettingsPage.cs")
        # By its declaration: member_body takes `else BuildEditorsLater();` for one.
        later = guiscan._block(page, page.index("private void BuildEditorsLater()"))
        self.assertIn("if (!IsDisposed && BuildEditorsStep()) return;", later)
        self.assertLess(later.index("BuildEditorsStep()"), later.index("Application.Idle -= idle;"))
        self.assertLess(later.index("Application.Idle -= idle;"), later.index("buildQueued = false;"),
                        "set until the last step, so what waits for the editors waits for all of them")
        self.assertIn("while (BuildEditorsStep()) { }", guiscan.member_body("SettingsForm", "BuildPendingEditors"))
        step = guiscan.member_body("SettingsForm", "BuildEditorsStep")
        self.assertIn("if (pendingSchema != null) editorSteps = EditorSteps(pendingSchema, pendingSettings);", step)

    def test_the_build_hands_the_thread_back_between_its_parts(self):
        steps = guiscan.member_body("SettingsForm", "EditorSteps")
        self.assertGreaterEqual(steps.count("yield return true;"), 4)
        self.assertLess(steps.index("BuildHomes(sections[\"advanced\"]);"), steps.index("yield return true;"))
        self.assertIn("if (slice.ElapsedMilliseconds >= EditorSliceMilliseconds)", steps)
        self.assertLess(steps.rindex("yield return true;"), steps.index("columns.ResumeLayout(true);"))
        self.assertIn("ForgetPins();", steps, "rows built again after Restore defaults leave nothing pinned behind")
        once = guiscan.member_body("SettingsForm", "BuildEditors")
        self.assertIn("while (editorSteps.MoveNext()) { }", once, "a build asked for at once is still one build")


PROBE = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed class StepsQuietFrame : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; }
        }
    }

    internal static class EditorStepsProbe
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            try { return SettingsForm.EditorStepsRun(argv[0], argv[1]); }
            catch (Exception e) { File.WriteAllText(argv[1], "{\"error\":" + Json.Write(e.ToString()) + "}"); return 3; }
        }
    }

    internal sealed partial class SettingsForm
    {
        private static void StepsPump(int ms, Func<bool> until)
        {
            var all = System.Diagnostics.Stopwatch.StartNew();
            while (all.ElapsedMilliseconds < ms)
            {
                Application.DoEvents();
                if (until != null && until()) return;
                System.Threading.Thread.Sleep(5);
            }
        }

        private static void Tree(Control parent, StringBuilder into)
        {
            foreach (Control child in parent.Controls)
            {
                into.Append(child.GetType().Name).Append('|').Append(child.Text).Append('|')
                    .Append(Soft.OwnVisible(child) ? "v" : "h").Append('|').Append(child.TabIndex).Append('|')
                    .Append(child.Enabled ? "e" : "d").Append('\n');
                Tree(child, into);
            }
        }

        private static StepsQuietFrame StepsFrame()
        {
            var frame = new StepsQuietFrame();
            frame.FormBorderStyle = FormBorderStyle.None;
            frame.ShowInTaskbar = false;
            frame.StartPosition = FormStartPosition.Manual;
            frame.Location = new Point(-30000, -30000);
            return frame;
        }

        private static SettingsForm StepsWindow(StepsQuietFrame frame)
        {
            string nowhere = Path.Combine(Path.GetTempPath(), "car-editor-steps-nowhere");
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
            // The settings read and the editors queued for the idle turns, none of which has come yet.
            StepsPump(30000, delegate { return form.settingsRead && form.buildQueued; });
            return form;
        }

        private string StepsValues()
        {
            var values = new SortedDictionary<string, string>(EditorValues());
            var parts = new List<string>();
            foreach (var pair in values) parts.Add(pair.Key + "=" + pair.Value);
            return string.Join("\n", parts.ToArray());
        }

        internal static int EditorStepsRun(string answersPath, string outPath)
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

            // The idle turns raised one at a time, nothing else let in between (no read lands mid-build): how many the
            // editors take, and what they built - looked at the moment the last step ends.
            var frame = StepsFrame();
            var form = StepsWindow(frame);
            outMap["queued"] = form.buildQueued;
            int turns = 0;
            while (form.buildQueued && turns < 500)
            {
                Application.RaiseIdle(EventArgs.Empty);
                turns++;
            }
            outMap["turns"] = (double)turns;
            outMap["built"] = (double)form.editors.Count;
            var stepped = new StringBuilder();
            Tree(form.columns, stepped);
            outMap["stepped_tree"] = stepped.ToString();
            outMap["stepped_values"] = form.StepsValues();
            frame.Close();
            frame.Dispose();

            // Another window as it was opened, its editors built at once (BuildPendingEditors, as a switch to Settings
            // before any step builds them), looked at the moment that ends.
            frame = StepsFrame();
            form = StepsWindow(frame);
            form.BuildPendingEditors();
            var once = new StringBuilder();
            Tree(form.columns, once);
            outMap["once_tree"] = once.ToString();
            outMap["once_values"] = form.StepsValues();
            frame.Close();
            frame.Dispose();

            // A press on the Settings tab after two steps, and one before any: the same whole page.
            frame = StepsFrame();
            form = StepsWindow(frame);
            Application.RaiseIdle(EventArgs.Empty);
            Application.RaiseIdle(EventArgs.Empty);
            outMap["partial"] = (double)form.editors.Count;
            outMap["partial_open"] = form.editorSteps != null;
            form.navButtons["settings"].PerformClick();
            outMap["clicked_page"] = form.currentPage;
            outMap["clicked_built"] = (double)form.editors.Count;
            outMap["clicked_open"] = form.editorSteps != null;
            var clicked = new StringBuilder();
            Tree(form.columns, clicked);
            outMap["clicked_tree"] = clicked.ToString();
            outMap["clicked_values"] = form.StepsValues();
            // And the idle turn after it finds nothing left to build.
            Application.RaiseIdle(EventArgs.Empty);
            outMap["clicked_queued_after"] = form.buildQueued;
            frame.Close();
            frame.Dispose();

            frame = StepsFrame();
            form = StepsWindow(frame);
            form.navButtons["settings"].PerformClick();
            var direct = new StringBuilder();
            Tree(form.columns, direct);
            outMap["direct_tree"] = direct.ToString();
            outMap["direct_values"] = form.StepsValues();
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
class StepsTests(unittest.TestCase):
    """The real window off the screen, its idle turns raised one at a time."""

    @classmethod
    def setUpClass(cls):
        import advanced_shots
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        read, _envelope = advanced_shots.read_answers("standard", "base", "en")
        answers = work / "answers.json"
        answers.write_text(json.dumps(advanced_shots.form_answers(read), ensure_ascii=False), encoding="utf-8")
        probe = work / "EditorStepsProbe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        exe = work / "EditorSteps.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                                "/main:CodexAutoResume.EditorStepsProbe", "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
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
        self.assertTrue(self.answer["queued"], "the editors waited for the idle turns")

    def test_the_editors_take_several_turns(self):
        self.assertGreaterEqual(self.answer["turns"], 4, "built in one turn again")
        self.assertGreater(self.answer["built"], 20)

    def test_what_the_steps_built_is_what_one_build_makes(self):
        self.assertEqual(self.answer["stepped_tree"], self.answer["once_tree"])
        self.assertEqual(self.answer["stepped_values"], self.answer["once_values"])

    def test_a_press_on_settings_before_the_last_step_shows_the_whole_page(self):
        self.assertTrue(self.answer["partial_open"], "the press came while the build was under way")
        self.assertLess(self.answer["partial"], self.answer["built"])
        self.assertEqual(self.answer["clicked_page"], "settings")
        self.assertFalse(self.answer["clicked_open"])
        self.assertEqual(self.answer["clicked_built"], self.answer["built"])
        self.assertEqual(self.answer["clicked_tree"], self.answer["direct_tree"], "as a press before any step shows it")
        self.assertEqual(self.answer["clicked_values"], self.answer["direct_values"])
        self.assertFalse(self.answer["clicked_queued_after"], "the idle turn after it found nothing left to build")


if __name__ == "__main__":
    unittest.main()

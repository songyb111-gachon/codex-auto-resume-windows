r"""A page's first visit is as quick as its next (v0.6.23, the owner, 2026-11-11).

Pressing a tab, the page took a moment to appear the first time: it was built, its native controls made and it was laid
out on the click - Pending 150-630 ms, Diagnostics 440-1420 ms, Settings 320-760 ms, the Advanced features page
340-680 ms, where a page seen before took 15-320. And each line written into a page asked the whole page for a layout of
its own, so the first compatibility read after Diagnostics was opened held the window 1-3 s, and showing a page laid out
each of its cards outermost first, each asking the one around it again.

Now (gui/Dashboard.cs):
* once the window is on screen and has read its first snapshot, each page not yet shown is made ready on the idle turns
  after - built by PageFor as a click builds it, given the room it will fill, its controls made and laid out, hidden all
  the while - one step a turn and none while the window has just had a key or the mouse (PreparePagesLater, PrepareNext);
  Statistics and Diagnostics read once then what they read on each visit, and read it again on the visit as before;
* a snapshot, a statistics answer and the compatibility card are written with every page's layout held, and each page
  laid out once after (HoldPages, LayOutHeld);
* a page shown has everything in it that lays others out held while it becomes visible, and let go innermost first
  (HoldWithin, LetGoWithin).

Nothing drawn changes: every page, light and dark, in English, Korean, Japanese and Arabic, in both editions, drawn
offscreen by the render mode before and after was the same bytes (the seat's proof, plans/v0623-seats/firstopen-measure.md).

The live probe: the real window, standard edition, shown far off the screen in a frame that is never activated, answered
from the pictures' pinned scratch installation as the render mode is - after it is shown and idle, every page is built
with its controls made and the room it fills, and a press on its tab builds no page and makes no control.
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
    def test_the_pages_are_made_ready_once_the_window_is_shown(self):
        later = guiscan.member_body("SettingsForm", "PreparePagesLater")
        self.assertIn("if (!shown || prepareQueued || auditing || IsDisposed) return;", later)
        self.assertIn("Application.Idle += idle;", later)
        self.assertIn("Application.AddMessageFilter(prepareInput);", later)
        self.assertIn("Application.RemoveMessageFilter(prepareInput);", later)
        settings = guiscan.read("gui/SettingsApp.cs")
        shown = settings[settings.index("Shown += delegate"):settings.index("FormClosed += delegate")]
        self.assertLess(shown.index("BuildEditorsLater();"), shown.index("PreparePagesLater();"))

    def test_a_page_is_made_ready_as_a_click_would_make_it_one_step_a_turn(self):
        step = guiscan.member_body("SettingsForm", "PrepareNext")
        # After the first snapshot and the Settings editors, never while an action runs or the window has just had input.
        self.assertIn("if (snapshot == null || !settingsRead || pendingSchema != null || buildQueued) return true;", step)
        self.assertIn("prepareInput.Since < PrepareAfterInputMilliseconds", step)
        for part in ("page.Bounds = pageHost.DisplayRectangle;", "IntPtr made = page.Handle;", "Materialise(page);",
                     "page.PerformLayout();", 'if (preparing == "statistics") LoadStatistics();',
                     'if (preparing == "diagnostics") LoadCompatibility();'):
            self.assertIn(part, step)
        self.assertIn("if (page == null || Soft.OwnVisible(page))", step, "a page on screen is left as it is")
        # Its own reads' answers written, what they added is made and laid out too.
        self.assertEqual(step.count("Materialise(page);"), 2)
        self.assertIn("else if (!loadingStats && !loadingCompat && bridge.InFlight == 0)", step)
        # Built by the very function a click builds it with, so it is the same page with the same snapshot.
        built = guiscan.member_body("SettingsForm", "PreparedPage")
        self.assertIn("return PageFor(name);", built)
        self.assertIn('if (name == "settings") return columns;', built)
        self.assertIn("EditionPageFor(name, ref page);", built)
        self.assertNotIn("snapshotAge", step + built)
        self.assertNotIn("RefreshNow", step + built)

    def test_only_a_key_or_the_mouse_on_the_window_holds_a_step_back(self):
        filter_ = guiscan.type_body("PrepareInput")
        self.assertIn("return false;", filter_, "every message goes on to the window")
        for message in ("0x0100", "0x0109", "0x0200", "0x020E", "0x00A0", "0x00AD"):
            self.assertIn(message, filter_)

    def test_the_advanced_page_is_made_ready_after_the_standard_ones(self):
        page = (ROOT / "advanced" / "gui" / "AdvancedPage.cs").read_text(encoding="utf-8")
        named = guiscan.type_body("SettingsForm", page)
        self.assertIn("partial void EditionPageNamed(List<string> prepared, ref string name)", named)
        self.assertIn("if (name == AdvancedPageName && advancedWords != null) page = AdvancedPageBuilt();", named)
        words = named[named.index("advancedWords = words;"):]
        words = words[:words.index("\n        }\n")]
        self.assertIn("PreparePagesLater();", words)

    def test_what_a_page_shows_is_written_with_the_pages_layout_held(self):
        hold = guiscan.member_body("SettingsForm", "HoldPages")
        self.assertIn("foreach (Control page in pageHost.Controls)", hold)
        self.assertIn("page.SuspendLayout();", hold)
        self.assertIn("page.ResumeLayout(true);", guiscan.member_body("SettingsForm", "LayOutHeld"))
        applied = guiscan.member_body("SettingsForm", "ApplySnapshot")
        self.assertLess(applied.index("List<Control> held = HoldPages();"), applied.index("ApplyStatus(status, null);"))
        self.assertLess(applied.index("SnapshotApplied(reply);"), applied.index("finally { LayOutHeld(held); }"))
        compat = guiscan.member_body("SettingsForm", "ShowCompatibility")
        self.assertLess(compat.index("HoldPages();"), compat.index("WriteCompatibility();"))
        self.assertIn("finally { LayOutHeld(held); }", compat)
        actions = guiscan.read("gui/DashboardActions.cs")
        statistics = guiscan._block(actions, actions.index("private void LoadStatistics(bool afterChange)"))
        self.assertLess(statistics.index("HoldPages();"), statistics.index("ApplyStatistics(Map(reply, \"result\"));"))

    def test_a_page_shown_lets_what_it_holds_lay_out_innermost_first(self):
        show = guiscan.member_body("SettingsForm", "ShowPage")
        self.assertLess(show.index("List<Control> inner = HoldWithin(page);"), show.index("page.Visible = true;"))
        self.assertLess(show.index("page.Visible = true;"), show.index("LetGoWithin(inner);"))
        self.assertLess(show.index("LetGoWithin(inner);"), show.index("page.ResumeLayout(true);"))
        self.assertIn("for (int i = held.Count - 1; i >= 0; i--) held[i].ResumeLayout(true);",
                      guiscan.member_body("SettingsForm", "LetGoWithin"))


PROBE = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed class ReadyQuietFrame : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; }
        }
    }

    internal static class ReadyAheadProbe
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            try { return SettingsForm.ReadyAheadRun(argv[0], argv[1]); }
            catch (Exception e) { File.WriteAllText(argv[1], "{\"error\":" + Json.Write(e.ToString()) + "}"); return 3; }
        }
    }

    internal sealed partial class SettingsForm
    {
        private static void ReadyPump(int ms, Func<bool> until)
        {
            var all = System.Diagnostics.Stopwatch.StartNew();
            while (all.ElapsedMilliseconds < ms)
            {
                Application.DoEvents();
                Application.RaiseIdle(EventArgs.Empty);
                if (until != null && until()) return;
                System.Threading.Thread.Sleep(5);
            }
        }

        private static void Handles(Control parent, List<Control> into)
        {
            foreach (Control child in parent.Controls)
            {
                if (!Soft.OwnVisible(child)) continue;
                into.Add(child);
                Handles(child, into);
            }
        }

        internal static int ReadyAheadRun(string answersPath, string outPath)
        {
            Theme.Opened = "light";
            Design.Opened = "soft";
            Palette.AdoptDesign("soft");
            Palette.Adopt(Theme.Current("light"));
            var job = Json.Parse(File.ReadAllText(answersPath, new UTF8Encoding(false))) as Dictionary<string, object>;
            renderAnswers = Items(job, "answers");
            PersistentBridge.Answers = RenderAnswer;
            DialogAnswers = delegate { return false; };
            var frame = new ReadyQuietFrame();
            frame.FormBorderStyle = FormBorderStyle.None;
            frame.ShowInTaskbar = false;
            frame.StartPosition = FormStartPosition.Manual;
            frame.Location = new Point(-30000, -30000);
            string nowhere = Path.Combine(Path.GetTempPath(), "car-ready-ahead-nowhere");
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
            // Shown and idle: the turns after the first snapshot, until nothing is left to make ready.
            ReadyPump(60000, delegate { return form.snapshot != null && form.settingsRead && form.pendingSchema == null &&
                                                !form.prepareQueued && form.bridge.InFlight == 0; });
            var outMap = new Dictionary<string, object>();
            outMap["opened_on"] = form.currentPage;
            var pagesOut = new Dictionary<string, object>();
            foreach (string name in PageOrder)
            {
                if (name == form.currentPage) continue;
                var seen = new Dictionary<string, object>();
                Control page = name == "settings" ? (Control)form.columns : form.pages.ContainsKey(name) ? form.pages[name] : null;
                seen["built"] = page != null;
                int pagesBefore = form.pages.Count;
                var inPage = new List<Control>();
                if (page != null) Handles(page, inPage);
                int unmade = 0;
                foreach (Control control in inPage) if (!control.IsHandleCreated) unmade++;
                seen["handle"] = page != null && page.IsHandleCreated;
                seen["unmade"] = (double)unmade;
                seen["room"] = page != null && page.Bounds == form.pageHost.DisplayRectangle;
                form.navButtons[name].PerformClick();
                int madeOnClick = 0;
                foreach (Control control in inPage) if (!control.IsDisposed && control.IsHandleCreated) madeOnClick++;
                seen["made_on_click"] = (double)(madeOnClick - (inPage.Count - unmade));
                seen["pages_built_on_click"] = (double)(form.pages.Count - pagesBefore);
                seen["shown"] = form.currentPage == name;
                pagesOut[name] = seen;
                ReadyPump(1500, delegate { return form.bridge.InFlight == 0 && !form.refreshing && !form.loadingStats && !form.loadingCompat; });
                form.navButtons["overview"].PerformClick();
                ReadyPump(1500, delegate { return form.bridge.InFlight == 0 && !form.refreshing; });
            }
            outMap["pages"] = pagesOut;
            lock (RenderMisses) outMap["misses"] = new List<object>(RenderMisses.ToArray());
            frame.Close();
            frame.Dispose();
            File.WriteAllText(outPath, Json.Write(outMap), new UTF8Encoding(false));
            return 0;
        }
    }
}
"""


@unittest.skipUnless(os.name == "nt" and CSC.is_file(), "needs Windows and the in-box C# compiler")
class FirstVisitTests(unittest.TestCase):
    """The real window, shown off the screen and idle: every page is ready before its tab is pressed."""

    @classmethod
    def setUpClass(cls):
        import advanced_shots
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        read, _envelope = advanced_shots.read_answers("standard", "base", "en")
        answers = work / "answers.json"
        answers.write_text(json.dumps(advanced_shots.form_answers(read), ensure_ascii=False), encoding="utf-8")
        probe = work / "ReadyAheadProbe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        exe = work / "ReadyAhead.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                                "/main:CodexAutoResume.ReadyAheadProbe", "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
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

    def test_it_opened_on_the_overview_with_every_read_answered(self):
        self.assertEqual(self.answer["opened_on"], "overview")
        self.assertEqual(self.answer["misses"], [])

    def test_every_page_is_ready_before_its_tab_is_pressed(self):
        pages = self.answer["pages"]
        self.assertEqual(sorted(pages), ["diagnostics", "history", "pending", "settings", "statistics"])
        for name, seen in pages.items():
            with self.subTest(page=name):
                self.assertTrue(seen["built"], "built while the window was idle")
                self.assertTrue(seen["handle"], "its controls made while it was hidden")
                self.assertEqual(seen["unmade"], 0, "every control on it made")
                self.assertTrue(seen["room"], "given the room it fills")

    def test_a_press_on_its_tab_builds_no_page_and_makes_no_control(self):
        for name, seen in self.answer["pages"].items():
            with self.subTest(page=name):
                self.assertTrue(seen["shown"])
                self.assertEqual(seen["pages_built_on_click"], 0)
                self.assertEqual(seen["made_on_click"], 0)


if __name__ == "__main__":
    unittest.main()

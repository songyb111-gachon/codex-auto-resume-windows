r"""The window's long single steps, split (v0.6.23, the second round; idlefix2).

The idle probe (the real window under its own message loop, off the screen, an installation that had run for months)
left these steps on the window's thread longer than a slice, each holding the header's light and every glide while it
ran:

* History's list made with its 200 rows: up to 450 ms in one step - making the list's window inserted every row. The
  rows of a list made ready ahead are now held aside while its window is made and put back a slice a turn
  (SoftList.HoldRows, PutBackRows; PrepareNext's steps 2 and 3); anything that reads the rows meanwhile, and the page
  shown, has them all back first.
* A page's own last layout as it was made ready ahead: Settings up to 500 ms, Diagnostics up to 360. What the page held
  was let go innermost first, each card and table laying itself out at the size it was built at, and the page's own
  layout, last, gave each its real size and laid the whole page out again in that one step. Now each is first laid out
  at its size and held again, outermost first, the page first of all, and only then let go innermost first (LetGoSome):
  no card lays itself out before the page around it has, and on Settings each card lays itself out only at the size it
  keeps; the steps are a slice each.
* Pending's and Diagnostics' build steps: every control added to the page, a card or a grid asked it for a layout at the
  size it had before the page had a room - and the page's place in the page host brought the window's font, which laid
  the whole of Diagnostics out again in its last step (40-140 ms). Built ahead, the page, its cards, grids and button
  rows are held from laying themselves out as they are made (HeldAsBuilt) until the page is in the page host (PageFor,
  LetGoBuilt), and they lay themselves out once, when the page is.

The live probe: the real window, standard edition, shown far off the screen in a frame that is never activated, answered
from the pictures' pinned scratch installation as the render mode is, its History grown to 200 rows and Pending to 60;
its idle turns raised one at a time.
"""
from __future__ import annotations

import copy
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

HISTORY_ROWS = 200
PENDING_ROWS = 60


class SourceTests(unittest.TestCase):
    def test_a_lists_rows_are_held_aside_while_its_window_is_made(self):
        step = guiscan.member_body("SettingsForm", "PrepareNext")
        self.assertIn("if (prepareMake == null) HoldRows(page);", step)
        self.assertLess(step.index("if (prepareMake == null) HoldRows(page);"), step.index("if (MakeSome(page)) prepareStep = 3;"))
        self.assertIn("if (!PutBackSomeRows()) return true;", step)
        hold = guiscan.member_body("SoftList", "HoldRows")
        self.assertIn("if (heldRows != null || IsHandleCreated || IsDisposed || Items.Count == 0) return false;", hold)
        back = guiscan.member_body("SoftList", "PutBackRows")
        # Not BeginUpdate: ListView keeps every row added under it until EndUpdate and inserts them all there at once.
        self.assertNotIn("BeginUpdate", back)
        self.assertIn("WM_SETREDRAW", back)
        # Every reader of the rows has them all first, and so has a page shown, given up or finished.
        data = guiscan.read("gui/DashboardData.cs")
        selected = guiscan._block(data, data.index("private static Dictionary<string, object> Selected(ListView list)"))
        self.assertIn("AllRows(list);", selected)
        for name in ("FillList", "ShowUnreadable", "Contains"):
            with self.subTest(reader=name):
                self.assertIn("AllRows(list);", guiscan.member_body("SettingsForm", name))
        self.assertIn("if (preparing == name) PutBackAllRows();", guiscan.member_body("SettingsForm", "ShowPage"))
        self.assertIn("PutBackAllRows();", guiscan.member_body("SettingsForm", "Prepared"))
        self.assertIn("PutBackAllRows();", guiscan.member_body("SettingsForm", "PrepareFailed"))

    def test_a_page_built_ahead_is_held_until_it_is_in_the_page_host(self):
        some = guiscan.member_body("SettingsForm", "BuildSome")
        self.assertIn("buildHolding = build;", some)
        self.assertIn("finally { buildHolding = before; }", some)
        built = guiscan.member_body("SettingsForm", "PageFor")
        self.assertLess(built.index("pageHost.Controls.Add(page);"), built.index("if (begun != null) LetGoBuilt(begun);"))
        held = guiscan.member_body("SettingsForm", "LetGoBuilt")
        self.assertIn("held[i].ResumeLayout(false);", held)
        # The page, its cards, facts, grids and button rows are held as they are made - only while built ahead.
        for maker in ("Page", "Facts", "Grid", "ButtonRow", "MakeCard"):
            with self.subTest(maker=maker):
                self.assertIn("HeldAsBuilt(new Soft", guiscan.member_body("SettingsForm", maker))
        dashboard = guiscan.read("gui/Dashboard.cs")
        hold = guiscan._block(dashboard, dashboard.index("private T HeldAsBuilt<T>(T control) where T : Control"))
        self.assertIn("if (buildHolding == null) return control;", hold)


PROBE = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed class LongStepsFrame : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; }
        }
    }

    internal static class LongStepsProbe
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            try { return SettingsForm.LongStepsRun(argv[0], argv[1], argv[2]); }
            catch (Exception e) { File.WriteAllText(argv[1], "{\"error\":" + Json.Write(e.ToString()) + "}"); return 3; }
        }
    }

    internal sealed partial class SettingsForm
    {
        private static void LongPump(int ms, Func<bool> until)
        {
            var all = System.Diagnostics.Stopwatch.StartNew();
            while (all.ElapsedMilliseconds < ms)
            {
                Application.DoEvents();
                if (until != null && until()) return;
                System.Threading.Thread.Sleep(5);
            }
        }

        private static SettingsForm LongWindow(LongStepsFrame frame)
        {
            frame.FormBorderStyle = FormBorderStyle.None;
            frame.ShowInTaskbar = false;
            frame.StartPosition = FormStartPosition.Manual;
            frame.Location = new Point(-30000, -30000);
            string nowhere = Path.Combine(Path.GetTempPath(), "car-long-steps-nowhere");
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
            LongPump(30000, delegate { return form.settingsRead && form.snapshot != null && form.bridge.InFlight == 0; });
            return form;
        }

        // The rows' ids in the list's order, and the ones chosen and focused.
        private static string RowIds(ListView list)
        {
            var ids = new List<string>();
            foreach (ListViewItem item in list.Items)
                ids.Add(ListRowId(item.Tag as Dictionary<string, object>) + (item.Selected ? "*" : "") + (item.Focused ? "^" : ""));
            return string.Join(",", ids.ToArray());
        }

        private static string SnapshotIds(Dictionary<string, object> snapshot, string part)
        {
            var ids = new List<string>();
            foreach (object row in Items(snapshot, part) ?? new List<object>()) ids.Add(ListRowId(row as Dictionary<string, object>));
            return string.Join(",", ids.ToArray());
        }

        // Whether a list holds rows aside (SoftList.HoldsRows), read by reflection so that the probe builds against a window
        // without it too - there the answer is no, and the rows go in with the list's window.
        private static bool Holds(ListView list)
        {
            var held = typeof(SoftList).GetProperty("HoldsRows", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
            return held != null && (bool)held.GetValue(list, null);
        }

        private static int Turns(SettingsForm form, Func<bool> until)
        {
            int turns = 0;
            var clock = System.Diagnostics.Stopwatch.StartNew();
            while (clock.ElapsedMilliseconds < 60000 && !until())
            {
                // The bridge's answers taken as the message loop takes them, then one idle turn.
                Application.DoEvents();
                if (form.bridge.InFlight > 0 || form.refreshing || form.IdleStepWaits())
                {
                    System.Threading.Thread.Sleep(5);
                    continue;
                }
                Application.RaiseIdle(EventArgs.Empty);
                turns++;
            }
            return turns;
        }

        internal static int LongStepsRun(string answersPath, string outPath, string home)
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
            var outMap = new Dictionary<string, object>();

            // History and Pending made ready ahead: each list's window made with no rows, the rows put back after, all of
            // them, in their order, the first chosen.
            var frame = new LongStepsFrame();
            var form = LongWindow(frame);
            Control history = form.PageFor("history");
            Control pending = form.PageFor("pending");
            var made = new Dictionary<string, object>();
            form.historyList.HandleCreated += delegate { made["history"] = (double)form.historyList.Items.Count; };
            form.pendingList.HandleCreated += delegate { made["pending"] = (double)form.pendingList.Items.Count; };
            int heldTurns = 0;
            Turns(form, delegate
            {
                if (form.preparing == "history" && form.prepareStep == 3 && Holds(form.historyList)) heldTurns++;
                return form.preparedPages.Contains("history") && form.preparedPages.Contains("pending");
            });
            outMap["made_with_rows"] = made;
            outMap["history_turns_held"] = (double)heldTurns;
            outMap["history_rows"] = RowIds(form.historyList);
            outMap["history_snapshot"] = SnapshotIds(form.snapshot, "history");
            outMap["pending_rows"] = RowIds(form.pendingList);
            outMap["pending_snapshot"] = SnapshotIds(form.snapshot, "pending");
            outMap["history_handle"] = form.historyList.IsHandleCreated;
            outMap["history_native_rows"] = (double)SendMessage(form.historyList.Handle, 0x1004, IntPtr.Zero, IntPtr.Zero).ToInt64();
            frame.Close();
            frame.Dispose();

            // History shown while its rows are held aside: every row is there as it shows.
            frame = new LongStepsFrame();
            form = LongWindow(frame);
            form.PageFor("history");
            Turns(form, delegate
            {
                return (form.preparing == "history" && form.prepareStep == 3 && Holds(form.historyList)) ||
                       form.preparedPages.Contains("history");
            });
            outMap["held_before_click"] = form.preparing == "history" && Holds(form.historyList);
            form.navButtons["history"].PerformClick();
            outMap["clicked_shown"] = form.currentPage == "history" && Soft.OwnVisible(form.pages["history"]);
            outMap["clicked_held"] = Holds(form.historyList);
            outMap["clicked_rows"] = RowIds(form.historyList);
            outMap["clicked_native_rows"] = (double)SendMessage(form.historyList.Handle, 0x1004, IntPtr.Zero, IntPtr.Zero).ToInt64();
            outMap["clicked_snapshot"] = SnapshotIds(form.snapshot, "history");
            frame.Close();
            frame.Dispose();

            // Settings and Diagnostics made ready ahead: from the turn their holds begin to be let go, every size each card on
            // them lays itself out at, against the size it keeps.
            frame = new LongStepsFrame();
            form = LongWindow(frame);
            foreach (string name in new[] { "diagnostics", "settings" })
            {
                SettingsForm here = form;
                string page = name;
                Turns(form, delegate { return (here.preparing == page && here.prepareStep == 6) || here.preparedPages.Contains(page); });
                outMap[name + "_reached"] = form.preparing == page && form.prepareStep == 6;
                Control root = name == "settings" ? (Control)form.columns : form.pages[name];
                var sizes = new Dictionary<Control, List<Size>>();
                // Whether the page itself has laid itself out since its holds began to be let go, and the card layouts before.
                var pageFirst = new int[2];
                root.Layout += delegate { if (here.preparing == page) pageFirst[0] = 1; };
                var next = new Stack<Control>();
                next.Push(root);
                while (next.Count > 0)
                {
                    Control control = next.Pop();
                    if (control is SoftCard)
                    {
                        Control card = control;
                        var seen = new List<Size>();
                        sizes[card] = seen;
                        card.Layout += delegate
                        {
                            if (here.preparing != page) return;
                            seen.Add(card.Size);
                            if (pageFirst[0] == 0) pageFirst[1]++;
                        };
                    }
                    foreach (Control child in control.Controls) next.Push(child);
                }
                Turns(form, delegate { return here.preparedPages.Contains(page); });
                int layouts = 0, elsewhere = 0;
                foreach (var pair in sizes)
                    foreach (Size size in pair.Value)
                    {
                        layouts++;
                        if (size != pair.Key.Size) elsewhere++;
                    }
                outMap[name + "_cards"] = (double)sizes.Count;
                outMap[name + "_layouts"] = (double)layouts;
                outMap[name + "_layouts_at_another_size"] = (double)elsewhere;
                outMap[name + "_layouts_before_the_page"] = (double)pageFirst[1];
            }
            frame.Close();
            frame.Dispose();

            // Pending and Diagnostics built ahead a step a turn: how many times the page, and each card on it, lays itself
            // out while it is being built and put in the page host.
            frame = new LongStepsFrame();
            form = LongWindow(frame);
            foreach (string name in new[] { "pending", "diagnostics" })
            {
                SettingsForm here = form;
                string page = name;
                var laid = new int[2];
                var watched = new HashSet<Control>();
                Action<Control> watch = null;
                watch = delegate(Control control)
                {
                    if (!watched.Add(control)) return;
                    bool root = control is SoftPage && control.Parent == null;
                    if (root || control is SoftCard)
                        control.Layout += delegate
                        {
                            if (here.preparing != page || here.prepareStep != 0) return;
                            laid[root ? 0 : 1]++;
                        };
                    control.ControlAdded += delegate(object sender, ControlEventArgs e) { watch(e.Control); };
                    foreach (Control child in control.Controls) watch(child);
                };
                int steps = 0;
                Turns(form, delegate
                {
                    PageBuild begun;
                    if (here.pageBuilds.TryGetValue(page, out begun) && begun.Page != null) watch(begun.Page);
                    if (here.preparing == page && here.prepareStep == 0) steps++;
                    return here.preparedPages.Contains(page) || (here.preparing == page && here.prepareStep > 0);
                });
                outMap[name + "_build_turns"] = (double)steps;
                outMap[name + "_page_layouts_while_built"] = (double)laid[0];
                outMap[name + "_card_layouts_while_built"] = (double)laid[1];
                outMap[name + "_watched"] = (double)watched.Count;
            }
            frame.Close();
            frame.Dispose();

            lock (RenderMisses) outMap["misses"] = new List<object>(RenderMisses.ToArray());
            File.WriteAllText(outPath, Json.Write(outMap), new UTF8Encoding(false));
            return 0;
        }
    }
}
"""


def grown_answers() -> dict:
    """The pictures' answers, English, standard, with History grown to HISTORY_ROWS rows and Pending to PENDING_ROWS."""
    import advanced_shots
    read, _envelope = advanced_shots.read_answers("standard", "base", "en")
    form = advanced_shots.form_answers(read)
    for answer in form["answers"]:
        if answer["command"] != "dashboard" or not isinstance(answer["reply"], dict):
            continue
        reply = answer["reply"]
        for part, count in (("history", HISTORY_ROWS), ("pending", PENDING_ROWS)):
            rows = reply.get(part) or []
            if not rows:
                continue
            grown = []
            for i in range(count):
                row = copy.deepcopy(rows[i % len(rows)])
                row["interruption_id"] = "%s-%04d-%s" % (part, i, row.get("interruption_id") or "")
                grown.append(row)
            reply[part] = grown
    return form


@unittest.skipUnless(os.name == "nt" and CSC.is_file(), "needs Windows and the in-box C# compiler")
class LongStepTests(unittest.TestCase):
    """The real window off the screen, its idle turns raised one at a time."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        answers = work / "answers.json"
        answers.write_text(json.dumps(grown_answers(), ensure_ascii=False), encoding="utf-8")
        probe = work / "LongStepsProbe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        exe = work / "LongSteps.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                                "/main:CodexAutoResume.LongStepsProbe", "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
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

    def test_a_lists_window_is_made_with_no_rows_and_they_all_come_back(self):
        self.assertEqual(self.answer["made_with_rows"], {"history": 0, "pending": 0},
                         "a list's window was made with its rows in it, in one step")
        self.assertGreater(self.answer["history_turns_held"], 0, "the rows went back on turns of their own")
        for part, count in (("history", HISTORY_ROWS), ("pending", PENDING_ROWS)):
            with self.subTest(part=part):
                rows = self.answer[part + "_rows"].split(",")
                self.assertEqual(len(rows), count)
                self.assertEqual([row.rstrip("*^") for row in rows], self.answer[part + "_snapshot"].split(","),
                                 "the same rows in the same order")
                self.assertTrue(rows[0].rstrip("^").endswith("*"), "the first row chosen, as it was")
                self.assertEqual(sum(1 for row in rows if row.rstrip("^").endswith("*")), 1)
        self.assertTrue(self.answer["history_handle"])
        self.assertEqual(self.answer["history_native_rows"], HISTORY_ROWS, "every row in the list's window")

    def test_a_page_made_ready_lays_itself_out_before_its_cards(self):
        for name in ("diagnostics", "settings"):
            with self.subTest(page=name):
                self.assertTrue(self.answer[name + "_reached"], "the probe saw the page's holds before they were let go")
                self.assertGreater(self.answer[name + "_cards"], 0)
                self.assertGreater(self.answer[name + "_layouts"], 0, "its cards were laid out as they were let go")
                self.assertEqual(self.answer[name + "_layouts_before_the_page"], 0,
                                 "a card laid itself out before the page around it had: innermost first")
        self.assertEqual(self.answer["settings_layouts_at_another_size"], 0,
                         "a Settings card laid itself out at a size it does not keep, to be laid out again")

    def test_a_page_built_ahead_lays_nothing_out_while_it_is_built(self):
        for name in ("pending", "diagnostics"):
            with self.subTest(page=name):
                self.assertGreater(self.answer[name + "_build_turns"], 2, "built a step a turn")
                self.assertGreater(self.answer[name + "_watched"], 10)
                self.assertEqual(self.answer[name + "_page_layouts_while_built"], 0,
                                 "the page laid itself out while it was built")
        self.assertEqual(self.answer["diagnostics_card_layouts_while_built"], 0,
                         "a Diagnostics card laid itself out while it was built")

    def test_history_shown_while_its_rows_are_held_shows_every_row(self):
        self.assertTrue(self.answer["held_before_click"], "the click came while the rows were held aside")
        self.assertTrue(self.answer["clicked_shown"])
        self.assertFalse(self.answer["clicked_held"])
        rows = self.answer["clicked_rows"].split(",")
        self.assertEqual([row.rstrip("*^") for row in rows], self.answer["clicked_snapshot"].split(","))
        self.assertEqual(self.answer["clicked_native_rows"], HISTORY_ROWS)


if __name__ == "__main__":
    unittest.main()

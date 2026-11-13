r"""A refresh writes only the page on screen; the others are written when they are shown (v0.6.23, the live acceptance).

The live acceptance of v0.6.23-beta.2 (2026-11-11, on an installation that had run for months) found the window busy for
0.16-0.59 s every 5 s with nobody touching it: every refresh (ApplySnapshot) wrote the snapshot into every page built -
Pending's and History's lists re-measured, Diagnostics' facts laid out - for pages out of sight. Now a page out of sight
is marked (Writes, stalePages) and written from the snapshot then held just before it is shown (WriteIfStale, ShowPage);
a page made ready ahead is written as it is built (writingPage), and the layout audits write every page.

The live probe: the real window, standard edition, off the screen in a frame never activated, answered from the
pictures' pinned scratch installation grown to months of use (200 rows of History, 60 tasks waiting). Every page made
ready, then a refresh with History's newest row and every waiting task changed, on the Overview: no list is filled, both
pages are marked; History shown: its list is filled once and shows the new row.
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
HISTORY, PENDING = 200, 60


def grown(answers: dict) -> dict:
    """The answers with the dashboard grown to months of use: made-up ids, names and times only."""
    for answer in answers["answers"]:
        if answer["command"] != "dashboard":
            continue
        reply = answer["reply"]
        for part, count, base in (("history", HISTORY, 0x10000), ("pending", PENDING, 0x90000)):
            rows = reply.get(part) or []
            grown_rows = []
            for i in range(count):
                row = copy.deepcopy(rows[i % len(rows)])
                row["interruption_id"] = "%064x" % (base + i)
                row["chain_origin_id"] = row["interruption_id"]
                row["thread_id"] = "%08x-0000-7000-8000-%012x" % (base, i)
                if row.get("name"):
                    row["name"] = "%s %d" % (row["name"], i + 1)
                for key in ("detected_at", "outcome_at"):
                    if isinstance(row.get(key), (int, float)) and part == "history":
                        row[key] = row[key] - i * 77760.0
                grown_rows.append(row)
            reply[part] = grown_rows
    return answers


class SourceTests(unittest.TestCase):
    def test_every_page_part_of_a_snapshot_asks_whether_it_is_written(self):
        applied = guiscan.member_body("SettingsForm", "ApplySnapshot")
        for page in ("overview", "diagnostics", "pending", "history"):
            with self.subTest(page=page):
                self.assertIn('Writes("%s")' % page, applied)
        self.assertIn('bool pending = pendingList != null && Writes("pending");', applied)
        self.assertIn('bool history = historyList != null && Writes("history");', applied)
        writes = guiscan.member_body("SettingsForm", "Writes")
        self.assertIn("if (auditing || page == currentPage || page == writingPage) return true;", writes)
        self.assertIn("stalePages.Add(page);", writes)

    def test_a_page_made_ready_is_held_given_its_sizes_and_let_go_innermost_first(self):
        step = guiscan.member_body("SettingsForm", "PrepareNext")
        self.assertLess(step.index("prepareHeld = HoldWithin(page);"), step.index("page.Bounds = pageHost.DisplayRectangle;"))
        self.assertIn("if (LetGoSome()) prepareStep = 7;", step)
        let = guiscan.member_body("SettingsForm", "LetGoSome")
        # v0.6.23 (idlefix2): first, outermost first, each laid out at its size and held again, so what it holds has its
        # size before it lays itself out; then let go innermost first. Let go innermost first alone, the page's own last
        # layout laid the whole page out again in one step (Settings up to 500 ms).
        sized = let.index("Control first = prepareHeld[prepareSized++];")
        self.assertLess(sized, let.index("first.ResumeLayout(true);"))
        self.assertLess(let.index("first.ResumeLayout(true);"), let.index("first.SuspendLayout();"))
        self.assertLess(sized, let.index("Control last = prepareHeld[prepareHeld.Count - 1];"), "then innermost first")
        self.assertIn("if (preparing == name) LetGoAll();", guiscan.member_body("SettingsForm", "ShowPage"),
                      "a page shown before it is let go is let go at once, as it would be")
        self.assertIn("LetGoAll();", guiscan.member_body("SettingsForm", "Prepared"))

    def test_a_page_is_brought_up_to_date_before_it_shows(self):
        show = guiscan.member_body("SettingsForm", "ShowPage")
        self.assertLess(show.index("Control page = PageFor(name);"), show.index("WriteIfStale(name);"))
        self.assertLess(show.index("WriteIfStale(name);"), show.index("page.Visible = true;"))
        stale = guiscan.member_body("SettingsForm", "WriteIfStale")
        self.assertIn("if (!stalePages.Remove(page) || snapshot == null) return;", stale)
        self.assertIn("ApplySnapshot(snapshot);", stale)
        # A page made ready ahead is built marked, and written on a step of its own (PrepareNext, WriteIfStale).
        built = guiscan.member_body("SettingsForm", "PageFor")
        self.assertIn("if (snapshot != null && !Writes(name)) return page;", built)
        step = guiscan.member_body("SettingsForm", "PrepareNext")
        self.assertIn("WriteIfStale(preparing);", step)


PROBE = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed class HiddenQuietFrame : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get { CreateParams cp = base.CreateParams; cp.ExStyle |= 0x08000000 | 0x80; return cp; }
        }
    }

    internal static class HiddenPagesProbe
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            try { return SettingsForm.HiddenPagesRun(argv[0], argv[1]); }
            catch (Exception e) { File.WriteAllText(argv[1], "{\"error\":" + Json.Write(e.ToString()) + "}"); return 3; }
        }
    }

    internal sealed partial class SettingsForm
    {
        internal static int HiddenPagesRun(string answersPath, string outPath)
        {
            Theme.Opened = "light";
            Design.Opened = "soft";
            Palette.AdoptDesign("soft");
            Palette.Adopt(Theme.Current("light"));
            var job = Json.Parse(File.ReadAllText(answersPath, new UTF8Encoding(false))) as Dictionary<string, object>;
            renderAnswers = Items(job, "answers");
            PersistentBridge.Answers = RenderAnswer;
            DialogAnswers = delegate { return false; };
            var frame = new HiddenQuietFrame();
            frame.FormBorderStyle = FormBorderStyle.None;
            frame.ShowInTaskbar = false;
            frame.StartPosition = FormStartPosition.Manual;
            frame.Location = new Point(-30000, -30000);
            string nowhere = Path.Combine(Path.GetTempPath(), "car-hidden-pages-nowhere");
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
            // The idle turns raised one at a time, counted by the page made ready and its step on each.
            var turns = new Dictionary<string, object>();
            var clock = System.Diagnostics.Stopwatch.StartNew();
            while (clock.ElapsedMilliseconds < 90000 && !(form.snapshot != null && form.settingsRead && !form.buildQueued &&
                                                           !form.prepareQueued && form.bridge.InFlight == 0))
            {
                Application.DoEvents();
                string at = form.preparing == null ? null : form.preparing + ":" + form.prepareStep;
                Application.RaiseIdle(EventArgs.Empty);
                if (at != null)
                {
                    object seen;
                    turns[at] = (turns.TryGetValue(at, out seen) ? (double)seen : 0.0) + 1.0;
                }
                System.Threading.Thread.Sleep(2);
            }
            var outMap = new Dictionary<string, object>();
            outMap["opened_on"] = form.currentPage;
            outMap["turns"] = turns;
            outMap["built"] = new List<object>(new List<string>(form.pages.Keys).ToArray());
            outMap["history_rows"] = (double)form.historyList.Items.Count;
            outMap["pending_rows"] = (double)form.pendingList.Items.Count;

            // A refresh on the Overview with History's newest row and every waiting task changed.
            var changed = Json.Parse(Json.Write(form.snapshot)) as Dictionary<string, object>;
            var newest = Items(changed, "history")[0] as Dictionary<string, object>;
            newest["name"] = "A conversation renamed while the Overview was in front";
            foreach (object item in Items(changed, "pending"))
            {
                var row = item as Dictionary<string, object>;
                row["recovery_attempts"] = 3.0;
            }
            form.stalePages.Clear();
            int fills = ListFills;
            form.ApplySnapshot(changed);
            outMap["fills_on_refresh"] = (double)(ListFills - fills);
            var stale = new List<object>();
            foreach (string page in form.stalePages) stale.Add(page);
            stale.Sort();
            outMap["stale"] = stale;
            outMap["history_first_before"] = form.historyList.Items[0].Text;

            // History shown: written once, before it shows.
            fills = ListFills;
            form.navButtons["history"].PerformClick();
            outMap["fills_on_show"] = (double)(ListFills - fills);
            outMap["history_first_after"] = form.historyList.Items[0].Text;
            outMap["history_stale_after"] = form.stalePages.Contains("history");
            outMap["pending_stale_after"] = form.stalePages.Contains("pending");
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
class RefreshTests(unittest.TestCase):
    """The real window off the screen, every page made ready, then a refresh on the Overview."""

    @classmethod
    def setUpClass(cls):
        import advanced_shots
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        read, _envelope = advanced_shots.read_answers("standard", "base", "en")
        answers = work / "answers.json"
        answers.write_text(json.dumps(grown(advanced_shots.form_answers(read)), ensure_ascii=False), encoding="utf-8")
        probe = work / "HiddenPagesProbe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        exe = work / "HiddenPages.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                                "/main:CodexAutoResume.HiddenPagesProbe", "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
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

    def test_it_opened_on_the_overview_with_every_page_ready_and_every_row(self):
        self.assertEqual(self.answer["opened_on"], "overview")
        self.assertEqual(self.answer["misses"], [])
        self.assertEqual(self.answer["history_rows"], HISTORY)
        self.assertGreaterEqual(self.answer["pending_rows"], PENDING)
        for page in ("pending", "history", "statistics", "diagnostics"):
            self.assertIn(page, self.answer["built"])

    def test_making_a_page_s_controls_takes_turns_of_its_own_budget(self):
        """Settings' controls - its combo boxes, every editor - took 860 ms in one turn on months of data; made a slice at
        a time (MakeSome, PrepareSliceMilliseconds), they take several turns. Counted, not timed."""
        turns = self.answer["turns"]
        self.assertGreaterEqual(turns.get("settings:2", 0), 3, "Settings' controls made in one turn again: %r" % turns)
        self.assertGreaterEqual(turns.get("pending:1", 0), 1, "Pending written on a turn of its own: %r" % turns)
        # v0.6.23 (round 5): Pending and Diagnostics built a part a turn (PendingSteps, DiagnosticsSteps).
        self.assertGreaterEqual(turns.get("pending:0", 0), 5, "Pending built in one turn again: %r" % turns)
        self.assertGreaterEqual(turns.get("diagnostics:0", 0), 4, "Diagnostics built in one turn again: %r" % turns)
        # v0.6.23 (round 5): a page made ready is held from laying itself out from its room on (so its room, its writes
        # and its reads' answers lay nothing out) and let go a few at a time, the page itself on a turn of its own.
        self.assertGreaterEqual(turns.get("settings:6", 0), 2, "Settings let go in one turn again: %r" % turns)

    def test_a_refresh_on_the_overview_fills_no_hidden_list(self):
        self.assertEqual(self.answer["fills_on_refresh"], 0, "a hidden list was written by a refresh")
        self.assertEqual(self.answer["stale"], ["diagnostics", "history", "pending"])
        self.assertNotEqual(self.answer["history_first_before"], "A conversation renamed while the Overview was in front")

    def test_a_page_shown_is_written_once_before_it_shows(self):
        self.assertEqual(self.answer["fills_on_show"], 1)
        self.assertEqual(self.answer["history_first_after"], "A conversation renamed while the Overview was in front")
        self.assertFalse(self.answer["history_stale_after"])
        self.assertTrue(self.answer["pending_stale_after"], "Pending, still out of sight, waits")


if __name__ == "__main__":
    unittest.main()

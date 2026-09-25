// Codex Auto Resume - the Dashboard: what the watcher is doing, what is waiting and when
// it is next looked at, what happened before, how often it worked, the watcher's health,
// and the settings - in one native window, with no local web server and no browser.
//
// Like the rest of the window it owns nothing: every fact comes from the same control
// layer every other interface uses, over one long-lived bridge process, and every action
// addresses a recovery by its exact interruption id. The countdowns are drawn locally
// from the time the watcher persisted; reaching zero means the watcher looks again, not
// that anything is sent.
//
// Nothing that talks to the bridge runs on the window's own thread. A read can take as
// long as the store and the interpreter take, and a window that stops repainting while it
// waits looks exactly like one that has hung.
//
// C# 5 (the in-box compiler): no string interpolation, no null-conditional operator.
//
// The window is one `partial class SettingsForm`, written across several files since
// v0.6.10-alpha. This one is the Dashboard's own controls, its page frame and its two lists -
// Pending and History - with the column fitting and cell drawing they are measured and painted
// by. Beside it: gui/DashboardPages.cs is what each page is built out of, gui/DashboardCompat.cs
// the compatibility card, gui/DashboardData.cs the clock and the snapshot every page reads,
// gui/DashboardActions.cs what a button does, and gui/DashboardMaintenance.cs the Diagnostics
// actions that run a process. `gui/window.sources` is the list of them all.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Forms.Automation;

namespace CodexAutoResume
{
    /// One control process for the life of the window, instead of one per call.
    ///
    /// Requests and replies are single JSON lines (controlcli serve). The request bytes
    /// are written as UTF-8 by hand: .NET Framework encodes a redirected stdin with the
    /// console code page, which is CP949 on a Korean machine, and the other end reads
    /// UTF-8. Anything that goes wrong - a crash, a timeout, a reply out of turn - stops
    /// the process and answers that call through the one-shot bridge instead, so a broken
    /// pipe costs speed, never a wrong or missing answer.
    internal sealed class PersistentBridge
    {
        private const int ReplyMilliseconds = 30000;
        // After this many failures in a row the long-lived process is given up for the life
        // of the window. Each failed start costs an interpreter launch on top of the one-shot
        // call that answers it, and a start that has failed three times running is not going
        // to succeed on the fourth - the first version of this class failed every start for
        // a missing "-c", and the fallback hid it completely.
        private const int MaxFailures = 3;
        private readonly Bridge once;
        private readonly string python;
        private readonly string appSrc;
        private readonly object gate = new object();
        private Process process;
        private int nextId;
        private int failures;
        private volatile bool closed;

        internal PersistentBridge(string root, Bridge once)
        {
            this.once = once;
            python = Path.Combine(root, "runtime", "python.exe");
            appSrc = Path.Combine(root, "app", "src");
        }

        internal bool Available { get { return once.Available; } }

        internal Dictionary<string, object> Call(string command, string argument)
        {
            if (closed) throw new ObjectDisposedException("the window is closing");
            lock (gate)
            {
                if (closed) throw new ObjectDisposedException("the window is closing");
                if (failures < MaxFailures)
                {
                    try
                    {
                        var reply = Ask(command, argument);
                        failures = 0;
                        return reply;
                    }
                    catch (Exception)
                    {
                        failures++;
                        StopLocked();
                        // Ended by Stop while the window closes: the request may already have
                        // been carried out, and there is nobody left to show a second answer to.
                        if (closed) throw;
                    }
                }
                return once.Call(command, argument);
            }
        }

        /// One call on the one-shot bridge, past the long-lived process and its lock (v0.6.5): for a command that can
        /// take minutes - the compatibility refresh waits up to 150 s on the network - which on the long-lived pipe
        /// would hold every read the window paints from, and past the pipe's own 30 s reply limit would end the
        /// process under it. Called from a worker thread only, as every bridge call is.
        internal Dictionary<string, object> CallOnce(string command, string argument)
        {
            if (closed) throw new ObjectDisposedException("the window is closing");
            return once.Call(command, argument);
        }

        private Dictionary<string, object> Ask(string command, string argument)
        {
            if (process == null || process.HasExited) StartLocked();
            int id = ++nextId;
            var line = new StringBuilder("{\"id\":").Append(id.ToString(CultureInfo.InvariantCulture))
                                                     .Append(",\"command\":").Append(Json.Escape(command));
            if (!string.IsNullOrEmpty(argument)) line.Append(",\"argument\":").Append(argument);
            line.Append("}\n");
            byte[] bytes = new UTF8Encoding(false).GetBytes(line.ToString());
            Stream input = process.StandardInput.BaseStream;
            input.Write(bytes, 0, bytes.Length);
            input.Flush();
            Task<string> read = process.StandardOutput.ReadLineAsync();
            if (!read.Wait(ReplyMilliseconds)) throw new TimeoutException("the local service did not answer");
            if (read.Result == null) throw new InvalidOperationException("the local service closed");
            var envelope = (Dictionary<string, object>)Json.Parse(read.Result);
            object got;
            if (!envelope.TryGetValue("id", out got) || got == null ||
                Convert.ToInt32(got, CultureInfo.InvariantCulture) != id)
                throw new InvalidOperationException("the local service answered out of turn");
            return (Dictionary<string, object>)envelope["reply"];
        }

        private void StartLocked()
        {
            var info = new ProcessStartInfo();
            info.FileName = python;
            string code = "import sys;sys.path.insert(0,sys.argv[1]);" +
                          "from codex_auto_resume.controlcli import main;" +
                          "sys.exit(main(sys.argv[2:]))";
            // "-c", as the one-shot bridge has it: without it python.exe takes the code for a
            // script path, exits, and every call silently falls back to the one-shot bridge.
            info.Arguments = "-c " + Bridge.Quote(code) + " " + Bridge.Quote(appSrc) + " serve";
            info.UseShellExecute = false;
            info.RedirectStandardInput = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.CreateNoWindow = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            process = Process.Start(info);
            // Drained, so a child that writes to stderr can never block on a full pipe.
            process.ErrorDataReceived += delegate { };
            process.BeginErrorReadLine();
        }

        /// Called as the window closes, on its own thread - so it must not wait for a call
        /// that a worker is in the middle of. Waiting would hold the closing window for up
        /// to the reply timeout; ending the process ends that call instead.
        internal void Stop()
        {
            closed = true;
            if (System.Threading.Monitor.TryEnter(gate))
            {
                try { StopLocked(); }
                finally { System.Threading.Monitor.Exit(gate); }
                return;
            }
            Process running = process;
            try { if (running != null && !running.HasExited) running.Kill(); }
            catch (Exception) { }
        }

        private void StopLocked()
        {
            Process running = process;
            process = null;
            if (running == null) return;
            try
            {
                if (!running.HasExited)
                {
                    running.StandardInput.Close();
                    if (!running.WaitForExit(2000)) running.Kill();
                }
            }
            catch (Exception) { }
            // The pipes and the process handle are released now rather than whenever the
            // finalizer gets to them.
            try { running.Dispose(); } catch (Exception) { }
        }
    }

    /// A page tab that tells assistive technology it is one, and which one is selected.
    ///
    /// A plain button with AccessibleRole.PageTab announced its role but never its state,
    /// so a screen reader said "Overview, page tab" for every tab alike.
    internal sealed class NavButton : Button
    {
        private bool current, hover;

        /// A section in a vertical list rather than a tab in a strip: text starts at the left.
        internal bool Vertical;

        internal NavButton()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            Cursor = Cursors.Hand;
        }

        internal bool Current
        {
            get { return current; }
            set
            {
                if (current == value) return;
                current = value;
                Invalidate();
                if (IsHandleCreated)
                {
                    AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
                    if (value) AccessibilityNotifyClients(AccessibleEvents.Selection, -1);
                }
            }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        /// The tab's body. Room is kept around it for the focus ring, which a child window cannot
        /// draw outside itself.
        internal Rectangle Face
        {
            get
            {
                int ring = Soft.Px(Brand.FocusOffset + Brand.FocusWidth);
                return Rectangle.Inflate(ClientRectangle, -ring, -ring);
            }
        }

        /// Where the name is set: the body, and in the section list less its indent.
        internal Rectangle TextBounds
        {
            get
            {
                Rectangle bounds = Face;
                if (Vertical)
                {
                    bounds.X += Soft.Px(12);
                    bounds.Width = Math.Max(0, bounds.Width - Soft.Px(16));
                }
                return bounds;
            }
        }

        // The panel's tab, drawn as its segmented control draws a choice. The pages not chosen
        // are muted words straight on the canvas, which come up as a raised body with a hairline
        // under the pointer; the chosen page is pressed into a well, its name in the accent. The
        // state is also in the weight of the text and in what a screen reader is told, never in
        // colour alone. v0.6.10: in Classic the chosen page is underlined in the accent, as v0.6.2's
        // tabs were (a section of Settings, whose tabs stand in a column, has the bar at its left), and
        // in Plain it is a flat quiet-accent ground - neither design has a well to press it into.
        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            // The ground behind the tab, lifts included: the header card's shadow runs on under
            // the tabs rather than stopping at the edge of each one.
            Ground.PaintArea(this, g, ClientRectangle);
            Rectangle face = Face;
            float radius = Soft.PxF(Palette.RadiusControl);
            if (current)
            {
                // High Contrast keeps what it had: Highlight, with HighlightText on it.
                if (Palette.Contrast) Soft.Body(g, face, radius, Palette.AccentSoft, Palette.AccentSoft, false);
                else if (Palette.AccentBar) Underline(g, face);
                else if (!Palette.Depth) Soft.Body(g, face, radius, Palette.AccentSoft, Palette.AccentSoft, false);
                else Soft.Body(g, face, radius, Palette.Inset, Palette.Inset, true);
            }
            else if (hover) Soft.Body(g, face, radius, Palette.Raised, Palette.Line, false);
            Color text = !current ? Palette.Secondary : Palette.Contrast ? SystemColors.HighlightText : Palette.Accent;
            TextRenderer.DrawText(g, Text, Font, TextBounds, text,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis |
                                  (Vertical ? TextFormatFlags.Left : TextFormatFlags.HorizontalCenter));
            if (Focused && ShowFocusCues) Soft.Ring(g, face, radius);
        }

        /// Classic's current tab (v0.6.2's): an AccentBar-high line in the accent along the bottom of `face`, in from
        /// its ends as that release's was - or, for a section of Settings in its column, as high as the name and at
        /// the left. Paint only, inside the body the tab always had.
        internal void Underline(Graphics g, Rectangle face)
        {
            int bar = Soft.Px(Brand.AccentBar), inset = Soft.Px(Brand.SpaceXs);
            Rectangle line = Vertical
                ? new Rectangle(face.X, face.Y + inset, bar, face.Height - 2 * inset)
                : new Rectangle(face.X + inset, face.Bottom - bar, face.Width - 2 * inset, bar);
            if (line.Width > 0 && line.Height > 0) g.FillRectangle(Soft.Fill(Palette.Accent), line);
        }

        protected override AccessibleObject CreateAccessibilityInstance()
        {
            return new NavAccessible(this);
        }

        private sealed class NavAccessible : ButtonBase.ButtonBaseAccessibleObject
        {
            private readonly NavButton owner;

            internal NavAccessible(NavButton owner) : base(owner) { this.owner = owner; }

            public override AccessibleRole Role { get { return AccessibleRole.PageTab; } }

            public override AccessibleStates State
            {
                get
                {
                    AccessibleStates state = base.State | AccessibleStates.Selectable;
                    if (owner.Current) state |= AccessibleStates.Selected;
                    return state;
                }
            }
        }
    }

    /// A line that reports what an action did.
    ///
    /// Declared a polite live region (see Note()), which is what a screen reader follows
    /// for a sentence that appears somewhere the focus is not; the name-change event
    /// below is the same news through the older interface. Neither announces a repeat of
    /// the identical sentence, which is why the note is also left on screen.
    internal sealed class NoteLabel : WrapLabel
    {
        protected override void OnTextChanged(EventArgs e)
        {
            base.OnTextChanged(e);
            if (IsHandleCreated && Text.Length > 0) AccessibilityNotifyClients(AccessibleEvents.NameChange, -1);
        }
    }

    /// A line of text straight on the canvas beside a card.
    ///
    /// It paints the ground behind it, lifts included. A plain label paints a flat patch of its
    /// background colour, and the card below "Nothing is waiting" had no light along its top edge
    /// where the label covered it.
    internal sealed class GroundLabel : Label
    {
        internal GroundLabel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A line of text that stays one line - a conversation's name, how its recovery ended - and
    /// ends in an ellipsis where it does not fit.
    ///
    /// A table asks a label for its size at the width of its column, and a plain label answers
    /// with as many lines as the text wraps to: four long conversation names took the Overview to
    /// 713 px of window at 150%, and 729 in German (measured, 900 px wide). The whole text is still
    /// the label's name for a screen reader; only what is drawn is cut.
    internal sealed class LineLabel : Label
    {
        internal LineLabel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
            AutoSize = true;
            AutoEllipsis = true;
            // A conversation is called whatever its owner called it, ampersands included.
            UseMnemonic = false;
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            Size line = TextRenderer.MeasureText(string.IsNullOrEmpty(Text) ? " " : Text, Font, new Size(int.MaxValue, int.MaxValue),
                                                 TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
            int width = line.Width + Padding.Horizontal;
            if (MaximumSize.Width > 0) width = Math.Min(width, MaximumSize.Width);
            if (proposedSize.Width > 1 && proposedSize.Width < width) width = proposedSize.Width;
            return new Size(width, line.Height + Padding.Vertical);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var bounds = new Rectangle(Padding.Left, Padding.Top, Math.Max(0, Width - Padding.Horizontal), Math.Max(0, Height - Padding.Vertical));
            TextRenderer.DrawText(e.Graphics, Text, Font, bounds, ForeColor,
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix |
                                  TextFormatFlags.Left | TextFormatFlags.Top);
        }
    }

    /// A small bar chart of how recoveries ended, drawn to the same scale for every bar.
    internal sealed class OutcomeChart : Panel
    {
        internal List<KeyValuePair<string, int>> Bars = new List<KeyValuePair<string, int>>();
        // Every bar in one colour, the accent (BarColor): the word beside each bar tells the outcomes apart. v0.6.10
        // tried History's colour for each outcome's bar, and the owner put the one colour back.
        internal Color BarColor, TextColor;
        internal string EmptyText = "";

        internal OutcomeChart()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        }

        // Spacing is written at 96 DPI and scaled like the rest of the window. The text is
        // already scaled by its font, so unscaled gaps beside it look cramped at 200%.
        private static int Px(int atNinetySix)
        {
            return (int)Math.Round(atNinetySix * SettingsForm.DpiScale);
        }

        internal int RowHeight()
        {
            return Font.Height + Px(8);
        }

        /// The numbers as words, for whoever cannot see the bars.
        internal void Describe()
        {
            var spoken = new List<string>();
            foreach (var bar in Bars)
                spoken.Add(bar.Key + " " + bar.Value.ToString(CultureInfo.CurrentCulture));
            AccessibleDescription = spoken.Count == 0 ? EmptyText : string.Join(", ", spoken.ToArray());
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.Clear(BackColor);
            int max = 0;
            foreach (var bar in Bars) max = Math.Max(max, bar.Value);
            using (var text = new SolidBrush(TextColor))
            using (var fill = new SolidBrush(BarColor))
            {
                if (max == 0)
                {
                    e.Graphics.DrawString(EmptyText, Font, text, 0, 0);
                    return;
                }
                int row = RowHeight();
                int labelWidth = 0;
                foreach (var bar in Bars)
                    labelWidth = Math.Max(labelWidth, TextRenderer.MeasureText(bar.Key, Font).Width);
                int numberWidth = TextRenderer.MeasureText("0000", Font).Width;
                int track = Math.Max(Px(10), Width - labelWidth - numberWidth - Px(24));
                int y = 0;
                foreach (var bar in Bars)
                {
                    TextRenderer.DrawText(e.Graphics, bar.Key, Font, new Point(0, y), TextColor);
                    int length = (int)Math.Round(track * (bar.Value / (double)max));
                    e.Graphics.FillRectangle(fill, labelWidth + Px(12), y + Px(3), Math.Max(Px(2), length), row - Px(12));
                    TextRenderer.DrawText(e.Graphics, bar.Value.ToString(CultureInfo.CurrentCulture), Font,
                                          new Point(labelWidth + Px(18) + length, y), TextColor);
                    y += row;
                }
            }
        }

        protected override AccessibleObject CreateAccessibilityInstance()
        {
            return new ChartAccessible(this);
        }

        // Screen readers read a control's value more consistently than its description, so
        // the chart's data is its value as well.
        private sealed class ChartAccessible : Control.ControlAccessibleObject
        {
            private readonly OutcomeChart chart;

            internal ChartAccessible(OutcomeChart owner) : base(owner) { chart = owner; }

            public override string Value { get { return chart.AccessibleDescription ?? ""; } }
        }
    }

    /// Why a task is waiting: the watcher's safety checks, each with its last result.
    ///
    /// The results are the ones the watcher itself recorded the last time it looked at the
    /// task, read back from the store - nothing here evaluates a check, and nothing here can
    /// make one pass.
    internal sealed class GateList : Control
    {
        private readonly List<string[]> rows = new List<string[]>();   // label, result word, result code
        private string empty = "";

        internal GateList()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            TabStop = false;
            AccessibleRole = AccessibleRole.List;
            AutoSize = true;
        }

        private int RowHeight { get { return Font.Height + Soft.Px(12); } }

        internal void SetRows(List<string[]> fresh, string whenEmpty)
        {
            // The snapshot arrives every five seconds and the checks in it rarely move, so the same
            // thirteen rows were rebuilt, given a new accessible description and handed a full parent
            // layout every time - on the window's thread, whether or not this page was the one on
            // screen. Identical rows are now nothing to do.
            if (Same(fresh, whenEmpty)) return;
            GateFills++;
            rows.Clear();
            rows.AddRange(fresh);
            empty = whenEmpty ?? "";
            var spoken = new List<string>();
            foreach (string[] row in rows) spoken.Add(row[0] + ": " + row[1]);
            AccessibleDescription = rows.Count == 0 ? empty : string.Join(", ", spoken.ToArray());
            if (Parent != null) Parent.PerformLayout();
            Invalidate();
        }

        internal static int GateFills;

        /// Whether these are the rows it already holds, word for word, in the same order.
        private bool Same(List<string[]> fresh, string whenEmpty)
        {
            if (fresh == null || rows.Count != fresh.Count || empty != (whenEmpty ?? "")) return false;
            for (int i = 0; i < rows.Count; i++)
            {
                string[] mine = rows[i], theirs = fresh[i];
                if (mine == null || theirs == null || mine.Length != theirs.Length) return false;
                for (int c = 0; c < mine.Length; c++)
                    if (mine[c] != theirs[c]) return false;
            }
            return true;
        }

        // What it says with no checks to show: wrapped, Korean between its words (Soft.Wrap).
        private const TextFormatFlags EmptyFormat = TextFormatFlags.WordBreak | TextFormatFlags.Left;

        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = proposedSize.Width > 0 && proposedSize.Width < 20000 ? proposedSize.Width : Soft.Px(260);
            string text = empty.Length == 0 ? " " : empty;
            int height = rows.Count == 0
                ? TextRenderer.MeasureText(Soft.Wrap(text, Font, width, EmptyFormat), Font, new Size(width, int.MaxValue),
                                           EmptyFormat).Height
                : rows.Count * RowHeight;
            return new Size(width, height);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Color ground = Parent != null ? Parent.BackColor : Palette.Card;
            g.Clear(ground);
            if (rows.Count == 0)
            {
                TextRenderer.DrawText(g, Soft.Wrap(empty, Font, Width, EmptyFormat), Font, ClientRectangle, Palette.Secondary,
                                      EmptyFormat);
                return;
            }
            int y = 0, height = RowHeight;
            // The rows of a settings list in the panel: a hairline between each two, and the result
            // as a borderless chip at the end of the row.
            using (var rule = new SolidBrush(Palette.Line))
                foreach (string[] row in rows)
                {
                    Color tone = row[2] == "PASS" ? Palette.Success : row[2] == "WAIT" ? Palette.Waiting
                               : row[2] == "BLOCK" ? Palette.Danger : Palette.Paused;
                    if (y > 0) g.FillRectangle(rule, 0, y, Width, Soft.Hairline);
                    Size chip = Soft.ChipSize(row[1], Font);
                    var label = new Rectangle(0, y, Math.Max(0, Width - chip.Width - Soft.Px(8)), height);
                    TextRenderer.DrawText(g, row[0], Font, label, Palette.Ink,
                                          TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                          TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
                    Soft.Chip(g, new Rectangle(Math.Max(0, Width - chip.Width), y, chip.Width, height), row[1], Font, tone, ground);
                    y += height;
                }
        }
    }

    internal sealed partial class SettingsForm
    {
        // ------------------------------------------------------------------ state
        // Both are grounds on the canvas (see Ground): the tabs sit straight on it, under the
        // header card, and the header card's lift runs on across them.
        private readonly Panel nav = new SoftPage();
        private readonly Panel pageHost = new SoftPage();
        // How long ago the snapshot on screen was read (see ShowPage). Started again only when a
        // read answers (Reread): a page built later is handed the snapshot already held (PageFor),
        // and restarting it there made an old snapshot look new, so a first visit never read.
        private readonly Stopwatch snapshotAge = new Stopwatch();
        private const int FreshMilliseconds = 2000;
        private readonly Dictionary<string, Control> pages = new Dictionary<string, Control>();
        private readonly Dictionary<string, NavButton> navButtons = new Dictionary<string, NavButton>();
        private static readonly string[] PageOrder = { "overview", "pending", "history", "statistics",
                                                       "diagnostics", "settings" };
        private string firstPage = "overview";
        private string currentPage;
        private Button saveButton, restoreButton;
        private Timer clock;
        private int ticks;
        // One dashboard read at a time; a request made during one is remembered here.
        private bool refreshing, refreshAgain;
        // Actions in flight. While there is one, every other action waits its turn, visibly.
        private int busy;
        // Which statistics request is the latest, so an older answer never overwrites a newer one.
        private int statsToken;
        // One statistics read at a time; a period change made during one is remembered here.
        private bool loadingStats, statsAgain;
        // What the pause button currently stands for; null until a status has been read.
        private bool? shownEnabled;
        private Dictionary<string, object> snapshot;
        // Lists whose first row has already been preselected once (see Preselect).
        private readonly Dictionary<ListView, bool> preselected = new Dictionary<ListView, bool>();
        // Set while a list is being rebuilt, when its selection events say nothing about
        // what the person chose.
        private bool filling;

        // Overview
        private Label nowRecovery, nowWatcher, nowEngine, nowLastCheck, waitingLine, nextLine,
                      runningLine, weekDetected, weekSent, weekRecovered, weekSuccess, recentEmpty;
        private Button toggleButton;
        private TableLayoutPanel recentGrid;
        private string recentShown;
        // Pending and history
        private ListView pendingList, historyList;
        private Label pendingEmpty, historyEmpty;
        private Button retryButton, cancelButton, timelineButton, threadButton, cancelAllButton;
        // Why the selected task is waiting.
        private GateList explainList;
        private Label explainAsOf;
        // The Pending list's Auto-resume column, a check box for the task on its row.
        private const int ResumeColumn = 5;
        // The Pending list's Next check column, which the clock writes (UpdateCountdowns).
        private const int CountdownColumn = 3;
        // The note that belongs to no single record: what Cancel all did.
        private const string BulkNote = "*";
        // The watcher's safety checks, in the order it evaluates them (machine.GATES).
        private static readonly string[] GateOrder = { "consent", "engine_compatible", "single_owner",
            "submission_safe", "identity", "known_failure", "schedule", "chain_budget", "attempt_budget",
            "no_progress_budget", "thread_available", "no_newer_user_work", "usage" };
        private NoteLabel pendingNote, historyNote;
        private string pendingNoteFor, pendingNoteText = "";
        private Button historyTimeline, historyReset, historyThread, historyClear;
        // Statistics
        private ComboBox period;
        private Label statsDetected, statsSent, statsRecovered, statsSuccess, statsWait, statsRecover,
                      statsRetry, statsKinds;
        private OutcomeChart chart;
        // Diagnostics
        private Label diagVersion, diagWatcher, diagLastCheck, diagEngine, diagRecovery, diagStartup,
                      diagUpgrade, diagUpdate;
        private Button exportButton, repairButton, stopButton, updateButton;
        // Codex compatibility (v0.6.5; BuildCompatibility): its facts, what the view cannot vouch for - a callout each,
        // since v0.6.10 - the parts in two lists, what each state word means, and the refresh with what it last answered.
        // What others report of the Codex version (v0.6.10) is one muted fact under it, compatReported.
        private Label compatOverall, compatEngine, compatReported, compatChecked, compatData, compatLegend;
        private TableLayoutPanel compatNotice;
        private GateList compatLeft, compatRight;
        private Control compatLists;
        private NoteLabel compatNote;
        private Button compatButton;
        private string compatSaid = "";
        // The watcher's report as last read; the live check a refresh brought, shown instead while it stands over the
        // reports read after it (LiveStands); and whether the last read failed.
        private Dictionary<string, object> compatView, compatLive;
        // What the report said when the live check arrived (Reading): news the live check has already seen past.
        private string compatLiveOver;
        private bool compatUnreadable, loadingCompat, compatRefreshing;

        // ----------------------------------------------------------------- chrome
        private void BuildDashboard()
        {
            // `--page=<name>` opens on that page (`--settings` is the older spelling) and `--section=<name>`
            // on that Settings section; each is checked against the pages and sections there are
            // (ParseArguments), and anything else opens the Overview and General.
            if (request.Page != null) firstPage = request.Page;
            if (request.Section != null) currentSection = request.Section;

            nav.Dock = DockStyle.Top;
            nav.Padding = Pad(12, 0, 14, 0);
            var strip = new SoftFlow();
            strip.Dock = DockStyle.Fill;
            strip.FlowDirection = FlowDirection.LeftToRight;
            strip.WrapContents = false;
            strip.Margin = new Padding(0);
            strip.AccessibleRole = AccessibleRole.PageTabList;
            string[] fallbacks = { "Overview", "Pending", "History", "Statistics", "Diagnostics", "Settings" };
            for (int i = 0; i < PageOrder.Length; i++)
            {
                string name = PageOrder[i];
                var button = new NavButton();
                button.Text = S("nav." + name, fallbacks[i]);
                button.Font = Soft.RoleFont("nav");
                button.AutoSize = true;
                button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                button.FlatStyle = FlatStyle.Flat;
                button.FlatAppearance.BorderSize = 0;
                button.ForeColor = Secondary;
                // The panel's tab padding, 7 by 14, inside the room NavButton keeps for its ring.
                button.Padding = Pad(18, 8, 18, 8);
                button.Margin = Pad(0, 0, 2, 0);
                button.Cursor = Cursors.Hand;
                button.UseVisualStyleBackColor = false;
                string target = name;
                button.Click += delegate { ShowPage(target); };
                navButtons[name] = button;
                strip.Controls.Add(button);
            }
            nav.Controls.Add(strip);
            // As tall as the tabs, measured, and again whenever the window's font changes.
            EventHandler fit = delegate { nav.Height = strip.PreferredSize.Height + nav.Padding.Vertical; };
            fit(this, EventArgs.Empty);
            FontChanged += fit;

            pageHost.Dock = DockStyle.Fill;

            // The Dashboard's pages are built the first time each is shown (PageFor). Settings is
            // built here, empty, and filled with editors once the settings have been read.
            columns.Visible = false;
            pageHost.Controls.Add(columns);
            pages["settings"] = columns;

            KeyPreview = true;
            KeyDown += delegate(object sender, KeyEventArgs e)
            {
                // Ctrl+Tab and Ctrl+Shift+Tab move between pages, as in any tabbed window.
                if (e.Control && e.KeyCode == Keys.Tab)
                {
                    int index = Array.IndexOf(PageOrder, currentPage);
                    index = (index + (e.Shift ? PageOrder.Length - 1 : 1)) % PageOrder.Length;
                    ShowPage(PageOrder[index]);
                    e.Handled = true;
                }
                else if (e.KeyCode == Keys.F5)
                {
                    RefreshNow();
                    if (currentPage == "statistics") LoadStatistics();
                    if (currentPage == "diagnostics") LoadCompatibility();
                    e.Handled = true;
                }
            };
        }

        private void ShowPage(string name)
        {
            if (Array.IndexOf(PageOrder, name) < 0) name = "overview";
            currentPage = name;
            bool settings = name == "settings";
            // Settings asked for before its editors were built on idle: built now, before it shows.
            if (settings) BuildPendingEditors();
            // Painting stops while one page is hidden and the next shown, so the page is painted
            // once, finished (see Redraw).
            bool paused = Redraw(pageHost, false);
            try
            {
                Control page = PageFor(name);
                // Every page stays in the host once built and only the one shown is visible: taking a
                // page off and putting the next on moved every native control in it to Windows'
                // parking window and back.
                pageHost.SuspendLayout();
                foreach (Control other in pageHost.Controls)
                    if (other != page) other.Visible = false;
                // Held while it becomes visible and laid out once after, as ShowSection holds a
                // section - and the Settings page holds the section it shows, which is where each
                // control that sizes itself asked for another layout: a switch to Settings took 113 ms
                // once its sections kept one width, and takes 58 held (measured, 150%).
                TableLayoutPanel section = settings && sections.ContainsKey(currentSection) ? sections[currentSection] : null;
                page.SuspendLayout();
                if (section != null) section.SuspendLayout();
                page.Visible = true;
                if (section != null) section.ResumeLayout(true);
                page.ResumeLayout(true);
                pageHost.ResumeLayout(false);
                pageHost.PerformLayout();
                foreach (var pair in navButtons)
                {
                    pair.Value.ForeColor = pair.Key == name ? Ink : Secondary;
                    // Cached: a switch used to create a font for every tab.
                    pair.Value.Font = Soft.RoleFont(pair.Key == name ? "nav_current" : "nav");
                    pair.Value.Current = pair.Key == name;
                }
                if (saveButton != null) saveButton.Visible = settings;
                if (restoreButton != null) restoreButton.Visible = settings;
            }
            finally
            {
                if (paused) Redraw(pageHost, true);
            }
            // Coming back to Pending: the countdowns the clock did not write while it was hidden.
            if (name == "pending" && snapshot != null) WriteCountdowns(Now());
            if (auditing) return;
            if (name == "statistics") LoadStatistics();
            if (name == "diagnostics") LoadCompatibility();
            // Not when the snapshot on screen is under two seconds old: switching pages straight
            // after a read asked for the same answer again - 17-87 ms of Python and up to 45 ms of
            // redrawing, for nothing new.
            if (!settings && (snapshot == null || snapshotAge.ElapsedMilliseconds >= FreshMilliseconds)) RefreshNow();
        }

        /// A page, built the first time it is shown. Building all five before the first screen
        /// cost 75-290 ms, for pages most openings never visit. A page built after a snapshot has
        /// arrived is given that snapshot at once, so it never shows its placeholders.
        private Control PageFor(string name)
        {
            Control page;
            if (pages.TryGetValue(name, out page)) return page;
            page = name == "pending" ? BuildPending()
                 : name == "history" ? BuildHistory()
                 : name == "statistics" ? BuildStatistics()
                 : name == "diagnostics" ? BuildDiagnostics()
                 : BuildOverview();
            page.Visible = false;
            pages[name] = page;
            pageHost.Controls.Add(page);
            if (snapshot != null) ApplySnapshot(snapshot);
            return page;
        }

        private Panel Page()
        {
            var page = new SoftPage();
            page.Dock = DockStyle.Fill;
            // A page may scroll, and while it does it is the edge of the shadows on it (see Ground):
            // the cards' lift is kept inside its padding.
            page.Padding = CardRoom();
            page.Scrolls = true;
            return page;
        }

        private Label Value(string text)
        {
            // A value that wraps breaks Korean between its words (WrapLabel).
            var label = new WrapLabel();
            label.Text = text;
            label.AutoSize = true;
            label.ForeColor = Ink;
            label.Margin = Pad(0, 3, 0, 3);
            return label;
        }

        /// A line of text straight on the canvas beside a card, which keeps the card's lift where
        /// a plain label would cover it (see GroundLabel).
        private Label GroundText(string text)
        {
            var label = new GroundLabel();
            label.Text = text;
            label.AutoSize = true;
            label.ForeColor = Ink;
            label.Margin = Pad(0, 3, 0, 3);
            return label;
        }

        private NoteLabel Note()
        {
            var note = new NoteLabel();
            note.AutoSize = true;
            note.ForeColor = Secondary;
            note.LiveSetting = AutomationLiveSetting.Polite;
            note.Margin = Pad(4, 8, 0, 0);
            return note;
        }

        private static void SetNote(Label note, string text)
        {
            if (note.Text != text) note.Text = text;
        }

        private TableLayoutPanel Facts(TableLayoutPanel card)
        {
            var grid = new SoftStack();
            grid.ColumnCount = 2;
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            grid.AutoSize = true;
            grid.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            grid.Dock = DockStyle.Fill;
            // None of its own: the default is 3 px that never scaled, which set every fact 3 px in
            // from the card's heading and added 6 px to each card of the Overview.
            grid.Margin = new Padding(0);
            // Opaque, in the card's own colour. See-through, every repaint of the grid and of each
            // label in it asked the card to paint its background again, shadow and all: 23 card
            // backgrounds for one Overview, and 1.4 s the first time Statistics was shown. A ground
            // (SoftStack), because a button pinned beside the facts lifts over the grid.
            grid.BackColor = Card;
            card.Controls.Add(grid);
            return grid;
        }

        private Label Fact(TableLayoutPanel grid, string label)
        {
            var name = Value(label);
            name.ForeColor = Secondary;
            name.Margin = Pad(0, 3, 18, 3);
            var value = Value("-");
            grid.Controls.Add(name);
            grid.Controls.Add(value);
            return value;
        }

        private TableLayoutPanel Grid(int columnCount)
        {
            var grid = new SoftStack();
            grid.Dock = DockStyle.Top;
            grid.AutoSize = true;
            grid.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            grid.ColumnCount = columnCount;
            for (int i = 0; i < columnCount; i++) grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / columnCount));
            return grid;
        }

        /// The gap around a card in a grid of two columns, as the panel's page gap: half of it on
        /// each side of the gutter between the columns, all of it under every row but the last.
        private Padding GridGap(int column, bool lastRow)
        {
            int half = Brand.PageGap / 2;
            return Pad(column == 0 ? 0 : half, 0, column == 0 ? half : 0, lastRow ? 0 : Brand.PageGap);
        }

        /// The gap around a card in the Overview's grid, whose rows FitOverview sizes: between the columns as GridGap
        /// has it, and between the rows half of the page gap under the one and half over the other, so rows of one
        /// height are cards of one height.
        private Padding RowGap(int column, int row)
        {
            int half = Brand.PageGap / 2;
            return Pad(column == 0 ? 0 : half, row == 0 ? 0 : half, column == 0 ? half : 0, row == 0 ? half : 0);
        }

        private FlowLayoutPanel ButtonRow()
        {
            var row = new SoftFlow();
            row.Dock = DockStyle.Bottom;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.WrapContents = true;
            row.Padding = Pad(0, 12, 0, 0);
            return row;
        }

        private ListView List(string accessibleName, params KeyValuePair<string, int>[] columnSpec)
        {
            var list = new SoftList();
            list.View = View.Details;
            list.FullRowSelect = true;
            list.MultiSelect = false;
            list.HideSelection = false;
            list.Dock = DockStyle.Fill;
            list.BorderStyle = BorderStyle.None;
            list.BackColor = Card;
            list.ForeColor = Ink;
            list.AccessibleName = accessibleName;
            // Rows tall enough for a state chip at any scaling. A ListView takes its row height
            // from its small image list and from nothing else it will listen to.
            list.SmallImageList = new ImageList();
            list.SmallImageList.ImageSize = new Size(1, Math.Max(16, Math.Min(255, Px(34))));
            list.OwnerDraw = true;
            list.DrawColumnHeader += DrawHeader;
            list.DrawItem += delegate { };
            list.DrawSubItem += DrawCell;
            var weights = new int[columnSpec.Length];
            for (int i = 0; i < columnSpec.Length; i++)
            {
                list.Columns.Add(columnSpec[i].Key, Px(columnSpec[i].Value));
                weights[i] = columnSpec[i].Value;
            }
            // The columns share the list's width in the proportions they were declared with, so
            // the last one - the Auto-resume box - is never pushed past a scroll bar.
            columnWeights[list] = weights;
            list.ClientSizeChanged += delegate { FitColumns(list); };
            return list;
        }

        private readonly Dictionary<ListView, int[]> columnWeights = new Dictionary<ListView, int[]>();

        private void FitColumns(ListView list)
        {
            int[] weights;
            if (!columnWeights.TryGetValue(list, out weights) || list.Columns.Count != weights.Length) return;
            int total = 0;
            foreach (int weight in weights) total += weight;
            // All of it: the header control paints whatever the columns leave in plain white.
            int available = list.ClientSize.Width;
            if (available < Px(160) || total <= 0) return;
            // Each column's heading, the widest cell under it and the least it is drawn at; how wide each is then
            // follows what the list has room for (ColumnFloors), and what is left past that is shared in the declared
            // proportions.
            int[] cells;
            cellWidths.TryGetValue(list, out cells);
            var heading = new int[weights.Length];
            var least = new int[weights.Length];
            for (int i = 0; i < weights.Length; i++)
            {
                heading[i] = HeadingWidth(list, i);
                least[i] = LeastWidth(list, i);
            }
            int[] floor = ColumnFloors(heading, cells, least, Px(ReadableCells), available);
            int floors = 0;
            foreach (int width in floor) floors += width;
            int spare = Math.Max(0, available - floors);
            int used = 0;
            for (int i = 0; i < weights.Length; i++)
            {
                int width = i == weights.Length - 1 ? Math.Max(floor[i], available - used)
                          : floor[i] + (int)Math.Floor(spare * (double)weights[i] / total);
                if (list.Columns[i].Width != width) list.Columns[i].Width = width;
                used += width;
            }
        }

        /// How much of what a column holds is kept before a heading gives way (ColumnFloors): about a dozen characters,
        /// with the cell's inset - twice the least a column is drawn at (LeastWidth).
        internal const int ReadableCells = 96;

        /// The least each of a list's columns is given, `available` wide (v0.6.5): `heading` each heading's width whole,
        /// `cells` each column's widest cell (null before any was measured), `least` the least each is drawn at
        /// (LeastWidth), `readable` how much of what a column holds is kept before a heading gives way (ReadableCells).
        /// What the list has past their total is shared in the declared proportions (FitColumns).
        ///
        /// As the list narrows, what gives way, in turn:
        ///   * a conversation's name past its heading: every other column keeps its heading and its widest cell whole,
        ///     and the conversation's has what they leave - a name may be as long as its owner made it, and a state or a
        ///     kind cut short says nothing. From the headings alone, a status needed the window 1,239 px wide before
        ///     "waiting for the usage reset" was drawn whole (measured, 150%);
        ///   * cells past a readable width: every heading stays whole - "Next check", "Attempts" and "Auto-resume" were
        ///     cut short in a window of v0.6.2's width - and every column keeps what it holds up to `readable`; each is
        ///     given the same part of what it wants past that;
        ///   * headings wider than what their column holds, the widest first, each down to the next widest, never below
        ///     what the column holds, readable;
        ///   * last, the cells, the widest first, never below the least. Only a list narrower than every column's least
        ///     is wider than its card, and scrolls sideways on the soft bar (SoftListHost).
        /// A heading and the cells under it that no longer fit end in an ellipsis (DrawHeader, DrawCell). The columns kept
        /// every heading whole whatever the list's width until v0.6.5, so a list narrower than its headings - a window
        /// made narrower than it opens - was wider than its card, with Windows' own white bar under the rows; then the
        /// headings alone gave way, and the review found the German Pending list 800 px wide at 200% with "Status" and
        /// "Art" at three or four letters of what they hold while "Versuche" kept 70 px for a single digit and the
        /// switch's column 100 for its 40 px switch. Widest first rather than in proportion, so a time or a count - which
        /// says nothing cut - stays whole while a long state or name ends in an ellipsis.
        internal static int[] ColumnFloors(int[] heading, int[] cells, int[] least, int readable, int available)
        {
            int count = heading.Length, others = 0, keeps = 0, holds = 0, wanted = 0;
            var full = new int[count];
            var hold = new int[count];
            var keep = new int[count];
            for (int i = 0; i < count; i++)
            {
                int cell = cells != null && i < cells.Length ? cells[i] : 0;
                // A conversation's name holds only as much as its heading, past which it gives way first.
                int need = Math.Max(least[i], i == 0 ? Math.Min(cell, heading[0]) : cell);
                full[i] = Math.Max(heading[i], i == 0 ? cell : need);
                hold[i] = Math.Max(least[i], Math.Min(need, readable));
                keep[i] = Math.Max(heading[i], hold[i]);
                if (i > 0)
                {
                    others += full[i];
                    wanted += full[i] - keep[i];
                }
                keeps += keep[i];
                holds += hold[i];
            }
            var widths = new int[count];
            if (count == 0) return widths;
            if (heading[0] + others <= available)
            {
                for (int i = 1; i < count; i++) widths[i] = full[i];
                widths[0] = Math.Max(heading[0], Math.Min(full[0], available - others));
                return widths;
            }
            if (keeps <= available)
            {
                widths[0] = keep[0];
                for (int i = 1; i < count; i++)
                    widths[i] = keep[i] + (wanted > 0 ? (int)Math.Floor((full[i] - keep[i]) * (double)(available - keeps) / wanted) : 0);
                return widths;
            }
            bool headings = holds <= available;
            int top = 0;
            for (int i = 0; i < count; i++) top = Math.Max(top, headings ? keep[i] : hold[i]);
            // The widest a heading, or else a cell, may stay: the largest cap under which the columns fit.
            int low = 0, high = top;
            while (low < high)
            {
                int cap = (low + high + 1) / 2;
                if (Capped(keep, hold, least, cap, headings, null) <= available) low = cap;
                else high = cap - 1;
            }
            Capped(keep, hold, least, low, headings, widths);
            return widths;
        }

        // The columns' total with every heading (`headings`: each column between what it holds and its heading), or else
        // every cell (between the least and what it holds), held to `cap`; each width into `widths` when it is given.
        private static int Capped(int[] keep, int[] hold, int[] least, int cap, bool headings, int[] widths)
        {
            int total = 0;
            for (int i = 0; i < keep.Length; i++)
            {
                int width = headings ? Math.Max(hold[i], Math.Min(keep[i], cap)) : Math.Max(least[i], Math.Min(hold[i], cap));
                if (widths != null) widths[i] = width;
                total += width;
            }
            return total;
        }

        /// The narrowest a column is drawn: an ellipsis and a letter or two of its heading - DrawHeader's inset and
        /// 34 px - or, for Pending's Auto-resume column, its switch whole (DrawResumeBox) with DrawCell's inset.
        private int LeastWidth(ListView list, int column)
        {
            if (list == pendingList && column == ResumeColumn) return Px(Brand.SwitchWidth + 2) + Px(14);
            return Px(48);
        }

        // The widest cell of each column, as DrawCell draws it, measured when a list's rows change
        // (MeasureCells) - not on every resize, which for a long history was every cell again.
        private readonly Dictionary<ListView, int[]> cellWidths = new Dictionary<ListView, int[]>();

        /// Measures the widest cell of every column, and fits the columns again.
        private void MeasureCells(ListView list)
        {
            var widths = new int[list.Columns.Count];
            var unbounded = new Size(int.MaxValue, int.MaxValue);
            int rows = 0;
            foreach (ListViewItem item in list.Items)
            {
                // Enough to know the widths by; a history of thousands is not measured whole.
                if (++rows > 200) break;
                for (int c = 0; c < widths.Length && c < item.SubItems.Count; c++)
                {
                    // The countdown as the clock writes it now: the cell holds only what the last tick wrote, and nothing
                    // yet in a row just added, so a list's first fit left the column no room for its time (v0.6.5).
                    string text = list == pendingList && c == CountdownColumn ? CountdownText(item.Tag as Dictionary<string, object>, Now())
                                : item.SubItems[c].Text;
                    // A state chip where DrawCell draws one: the second column of a row that has its record.
                    int width = c == 1 && item.Tag is Dictionary<string, object> ? Soft.ChipSize(text, list.Font).Width
                              : list == pendingList && c == ResumeColumn ? Px(Brand.SwitchWidth + 2)
                              : TextRenderer.MeasureText(text, list.Font, unbounded, TextFormatFlags.SingleLine).Width;
                    // DrawCell's inset: 10 before, 4 after.
                    widths[c] = Math.Max(widths[c], width + Px(14));
                }
            }
            cellWidths[list] = widths;
            FitColumns(list);
        }

        /// How wide a column must be for its heading to be drawn whole: the heading in the list's
        /// font, DrawHeader's inset around it, and never less than 48 px.
        private int HeadingWidth(ListView list, int column)
        {
            int heading = TextRenderer.MeasureText(list.Columns[column].Text, list.Font, new Size(int.MaxValue, int.MaxValue),
                                                   TextFormatFlags.SingleLine).Width;
            return Math.Max(Px(48), heading + Px(14));
        }

        /// How wide a list must be for every heading to be drawn whole.
        private int HeadingsWidth(ListView list)
        {
            int total = 0;
            for (int i = 0; i < list.Columns.Count; i++) total += HeadingWidth(list, i);
            return total;
        }

        /// A list on its own card, filling it.
        private Control ListCard(ListView list)
        {
            var card = new SoftCard();
            card.Dock = DockStyle.Fill;
            card.ColumnCount = 1;
            card.RowCount = 1;
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            // Its body is the whole control; the page it stands on draws its lift (see SoftCard).
            card.Padding = Pad(8, 8, 8, 8);
            card.Margin = new Padding(0);
            // The list scrolls on the soft bar, not its own (see SoftListHost).
            var host = new SoftListHost(list);
            host.Dock = DockStyle.Fill;
            host.Margin = new Padding(0);
            card.Controls.Add(host, 0, 0);
            return card;
        }

        private void DrawHeader(object sender, DrawListViewColumnHeaderEventArgs e)
        {
            e.Graphics.FillRectangle(Soft.Fill(Card), e.Bounds);
            e.Graphics.FillRectangle(Soft.Fill(Line), e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline, e.Bounds.Width, Soft.Hairline);
            var bounds = new Rectangle(e.Bounds.X + Px(10), e.Bounds.Y, Math.Max(0, e.Bounds.Width - Px(14)), e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, e.Header.Text, e.Font, bounds, Secondary,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }

        private void DrawCell(object sender, DrawListViewSubItemEventArgs e)
        {
            var list = (ListView)sender;
            bool selected = e.Item.Selected;
            // Rows on the card's surface with a full hairline between them, as the panel's setting
            // rows have; the chosen row is pressed into the inset colour. High Contrast keeps
            // Highlight for it.
            Color back = !selected ? Card : Palette.Contrast ? Palette.AccentSoft : Palette.Inset;
            // Brushes from Soft.Fill, which keeps one per colour: a list of twenty rows across six columns
            // allocated two hundred and forty brushes every time it repainted, and it repaints on every
            // scroll, selection and refresh.
            e.Graphics.FillRectangle(Soft.Fill(back), e.Bounds);
            e.Graphics.FillRectangle(Soft.Fill(Line), e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline, e.Bounds.Width, Soft.Hairline);
            var row = e.Item.Tag as Dictionary<string, object>;
            var cell = new Rectangle(e.Bounds.X + Px(10), e.Bounds.Y, Math.Max(0, e.Bounds.Width - Px(14)), e.Bounds.Height);
            string text = e.SubItem == null ? "" : e.SubItem.Text;
            Color ink = Palette.Contrast && selected ? SystemColors.HighlightText : Ink;
            // The quieter columns and the focus mark too: in High Contrast a selected row is
            // Highlight, and anything mixed away from HighlightText fell to about 2.4:1 on it.
            Color quiet = Palette.Contrast && selected ? ink : Soft.Mix(ink, Secondary, 0.4);
            if (e.ColumnIndex == 1 && row != null)
                Soft.Chip(e.Graphics, cell, text, list.Font, Palette.Contrast && selected ? ink : ToneFor(row), back);
            else if (list == pendingList && e.ColumnIndex == ResumeColumn && row != null)
                DrawResumeBox(e.Graphics, cell, row, back);
            else
                TextRenderer.DrawText(e.Graphics, text, list.Font, cell, e.ColumnIndex == 0 ? ink : quiet,
                                      TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                      TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
            if (e.ColumnIndex == 0 && selected && list.Focused)
                using (var pen = new Pen(Palette.Contrast ? ink : Palette.Focus, Soft.PxF(2)))
                    e.Graphics.DrawLine(pen, e.Item.Bounds.Left + Px(2), e.Item.Bounds.Top + Px(6),
                                        e.Item.Bounds.Left + Px(2), e.Item.Bounds.Bottom - Px(6));
        }

        /// The Auto-resume box, drawn as the switch every other on-or-off setting in the window is,
        /// on the row's own ground: where its record says, or part-way there while it glides
        /// (FollowResumeSwitches).
        private void DrawResumeBox(Graphics g, Rectangle cell, Dictionary<string, object> row, Color ground)
        {
            int width = Px(Brand.SwitchWidth), height = Px(Brand.SwitchHeight);
            var track = new Rectangle(cell.X + Px(2), cell.Y + (cell.Height - height) / 2, width, height);
            double on = ThreadOn(row) ? 1.0 : 0.0;
            Transition glide;
            string id = Str(row, "interruption_id");
            if (id != null && resumeGlides.TryGetValue(id, out glide) && glide.Running) on = glide.Value;
            Soft.SwitchAt(g, track, on, true, ground);
        }

        // Pending's Auto-resume switches (v0.6.5): each row's as it was last drawn, by its record's id, and the glide of
        // each that has moved.
        private readonly Dictionary<string, bool> resumeShown = new Dictionary<string, bool>();
        private readonly Dictionary<string, Transition> resumeGlides = new Dictionary<string, Transition>();

        /// Every Auto-resume switch in Pending, after its rows were written (v0.6.5). The switch never moves when it is
        /// pressed: the press sends the change, and the list is read again once the control layer has answered
        /// (ToggleAutoResume, Send). A switch already on screen that its record now says is the other way then glides
        /// there - brand's one transition on its one curve, the knob sliding and the track cross-fading, as the popup's
        /// and the panel's switch for the same conversation do - repainting only its own cell each frame (ResumeCell),
        /// with no layout and no timer once it has arrived. A change refused leaves the record as it was, and nothing
        /// moves. A row that appears is drawn as it is; with motion reduced, or Pending not on screen, the switch is
        /// where its record says at once.
        private void FollowResumeSwitches()
        {
            bool animate = Motion.Allowed(pendingList);
            var present = new HashSet<string>();
            foreach (ListViewItem item in pendingList.Items)
            {
                var row = item.Tag as Dictionary<string, object>;
                string id = Str(row, "interruption_id");
                if (id == null || !present.Add(id)) continue;
                bool on = ThreadOn(row), was;
                bool known = resumeShown.TryGetValue(id, out was);
                resumeShown[id] = on;
                Transition glide;
                resumeGlides.TryGetValue(id, out glide);
                if (!known || (was == on && (glide == null || glide.Target == (on ? 1.0 : 0.0)))) continue;
                if (glide == null)
                {
                    if (!animate) continue;
                    glide = new Transition(pendingList, was ? 1.0 : 0.0);
                    string key = id;
                    glide.Where = delegate { return ResumeCell(key); };
                    resumeGlides[id] = glide;
                }
                glide.To(on ? 1.0 : 0.0, animate);
            }
            foreach (string id in new List<string>(resumeShown.Keys))
            {
                if (present.Contains(id)) continue;
                resumeShown.Remove(id);
                Transition glide;
                if (resumeGlides.TryGetValue(id, out glide))
                {
                    glide.Dispose();
                    resumeGlides.Remove(id);
                }
            }
        }

        /// Where the Auto-resume switch of the row for `id` is in Pending's list now, or nothing when that row is not
        /// there: the cell a glide repaints, found again each frame, so a list that scrolls meanwhile is followed.
        private Rectangle ResumeCell(string id)
        {
            if (pendingList == null || pendingList.IsDisposed) return Rectangle.Empty;
            foreach (ListViewItem item in pendingList.Items)
                if (Str(item.Tag as Dictionary<string, object>, "interruption_id") == id && item.SubItems.Count > ResumeColumn)
                    return item.SubItems[ResumeColumn].Bounds;
            return Rectangle.Empty;
        }

        /// The colour a record's state word is drawn in. Always beside the word itself.
        internal static Color ToneFor(Dictionary<string, object> row)
        {
            if (HasOverlay(row, "paused") || HasOverlay(row, "thread_disabled")) return Palette.Paused;
            // Comparisons rather than a switch, for the reason in Controls.DotColour: a string
            // switch this long made the in-box compiler emit a randomly named class.
            string code = Str(row, "code") ?? "";
            if (code == "recovered" || code == "delivered_legacy") return Palette.Success;
            if (code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" || code == "scheduled")
                return Palette.Waiting;
            if (code == "submission_claimed" || code == "submitted" || code == "turn_running" ||
                code == "turn_finishing")
                return Palette.Accent;
            if (code == "failed_retryable" || code == "no_progress" || code == "exhausted" ||
                code == "handed_over" || code == "outcome_unverified" || code == "submission_unknown" ||
                code == "withdrawing")
                return Palette.Warning;
            if (code == "failed_terminal" || code == "recovery_failed") return Palette.Danger;
            return Palette.Paused;
        }

        private static KeyValuePair<string, int> Col(string name, int width)
        {
            return new KeyValuePair<string, int>(name, width);
        }

    }
}

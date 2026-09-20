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
        // colour alone.
        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            // The ground behind the tab, lifts included: the header card's shadow runs on under
            // the tabs rather than stopping at the edge of each one.
            Ground.PaintArea(this, g, ClientRectangle);
            Rectangle face = Face;
            float radius = Soft.PxF(Brand.RadiusControl);
            if (current)
            {
                // High Contrast keeps what it had: Highlight, with HighlightText on it.
                if (Palette.Contrast) Soft.Body(g, face, radius, Palette.AccentSoft, Palette.AccentSoft, false);
                else Soft.Body(g, face, radius, Palette.Inset, Palette.Inset, true);
            }
            else if (hover) Soft.Body(g, face, radius, Palette.Raised, Palette.Line, false);
            Color text = !current ? Palette.Secondary : Palette.Contrast ? SystemColors.HighlightText : Palette.Accent;
            TextRenderer.DrawText(g, Text, Font, TextBounds, text,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis |
                                  (Vertical ? TextFormatFlags.Left : TextFormatFlags.HorizontalCenter));
            if (Focused && ShowFocusCues) Soft.Ring(g, face, radius);
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
            rows.Clear();
            rows.AddRange(fresh);
            empty = whenEmpty ?? "";
            var spoken = new List<string>();
            foreach (string[] row in rows) spoken.Add(row[0] + ": " + row[1]);
            AccessibleDescription = rows.Count == 0 ? empty : string.Join(", ", spoken.ToArray());
            if (Parent != null) Parent.PerformLayout();
            Invalidate();
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
        // Codex compatibility (v0.6.5; BuildCompatibility): its facts, what the view cannot vouch for, the parts in two
        // lists, what each state word means, and the refresh with what it last answered.
        private Label compatOverall, compatEngine, compatChecked, compatData, compatNotice, compatLegend;
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
            using (var brush = new SolidBrush(Card)) e.Graphics.FillRectangle(brush, e.Bounds);
            using (var brush = new SolidBrush(Line))
                e.Graphics.FillRectangle(brush, e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline, e.Bounds.Width, Soft.Hairline);
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
            using (var brush = new SolidBrush(back)) e.Graphics.FillRectangle(brush, e.Bounds);
            using (var brush = new SolidBrush(Line))
                e.Graphics.FillRectangle(brush, e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline, e.Bounds.Width, Soft.Hairline);
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

        // ---------------------------------------------------------------- overview
        private Control BuildOverview()
        {
            Panel page = Page();
            // Two rows of two cards, and under them a row of space. How tall each is follows what the cards hold and the
            // page's height (FitOverview). A ground, so the cards' lift is drawn on it. AutoSize, though the page decides
            // its size: a table answers its parent's layout from its own only when it sizes itself, and WinForms then
            // lays the parent out once the table's own layout has finished - so a card that grows on a page already laid
            // out has the page fit the rows again, and scroll (as SoftRows did in v0.6.4).
            var grid = new SoftStack();
            grid.Dock = DockStyle.Fill;
            grid.AutoSize = true;
            grid.Margin = new Padding(0);
            grid.ColumnCount = 2;
            grid.RowCount = OverviewRows + 1;
            for (int i = 0; i < 2; i++) grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            for (int i = 0; i < OverviewRows; i++) grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 0f));
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

            TableLayoutPanel now = MakeCard(S("overview.now", "Right now"));
            now.Margin = RowGap(0, 0);
            TableLayoutPanel facts = Facts(now);
            // Automatic recovery first, what the button pauses and resumes, then the watcher, the engine and the last
            // check. The button stands under the facts, so they have the card's whole width - "ne répond pas",
            // "nicht unterstützt", "no se está ejecutando" among them - in every language at every scaling and state
            // (tests/test_gui_layout.py).
            nowRecovery = Fact(facts, S("overview.recovery", "Automatic recovery"));
            nowWatcher = Fact(facts, S("diag.watcher", "Watcher"));
            nowEngine = Fact(facts, S("overview.engine", "Codex engine"));
            nowLastCheck = Fact(facts, S("overview.last_check", "Last check"));
            nowFacts = facts;
            toggleButton = MakeButton(S("action.pause", "Pause recovery"), false, delegate { TogglePause(); });
            Lead(now, toggleButton);

            TableLayoutPanel waiting = MakeCard(S("overview.waiting", "Waiting"));
            waiting.Margin = RowGap(1, 0);
            waitingLine = Value("-");
            // The count as the page's figure: its size as it has always been, the panel's weight.
            waitingLine.Font = Soft.RoleFont("figure");
            nextLine = Value("");
            nextLine.ForeColor = Accent;
            runningLine = Value("");
            runningLine.ForeColor = Secondary;
            waiting.Controls.Add(waitingLine);
            waiting.Controls.Add(nextLine);
            waiting.Controls.Add(runningLine);
            Lead(waiting, MakeButton(S("nav.pending", "Pending"), false, delegate { ShowPage("pending"); }));

            TableLayoutPanel week = MakeCard(S("overview.week", "Last 7 days"));
            week.Margin = RowGap(0, 1);
            TableLayoutPanel weekFacts = Facts(week);
            weekDetected = Fact(weekFacts, S("overview.detected", "Interruptions"));
            weekSent = Fact(weekFacts, S("overview.sent", "Continuations sent"));
            weekRecovered = Fact(weekFacts, S("overview.recovered", "Recovered"));
            weekSuccess = Fact(weekFacts, S("overview.success", "Success rate"));
            Lead(week, null);

            // The last few recoveries that finished, so the page answers "did it work" as
            // well as "is it working" without a trip to the History page.
            TableLayoutPanel recent = MakeCard(S("overview.recent", "Recently finished"));
            recent.Margin = RowGap(1, 1);
            recentGrid = Facts(recent);
            recentEmpty = Value(S("history.empty", "No recoveries yet"));
            recentEmpty.ForeColor = Secondary;
            recent.Controls.Add(recentEmpty);
            Lead(recent, MakeButton(S("nav.history", "History"), false, delegate { ShowPage("history"); }));
            recentGrid.SizeChanged += delegate { FitRecentNames(); };

            grid.Controls.Add(now, 0, 0);
            grid.Controls.Add(waiting, 1, 0);
            grid.Controls.Add(week, 0, 1);
            grid.Controls.Add(recent, 1, 1);
            page.Controls.Add(grid);
            overviewGrid = grid;
            // Before the page lays the grid out, every time it does: the rows follow the page's height and what the
            // cards hold (FitOverview).
            var scroller = (SoftPage)page;
            page.Layout += delegate { FitOverview(scroller, grid); };
            return page;
        }

        // The Overview's rows of cards.
        private const int OverviewRows = 2;

        // The Overview's proportions (v0.6.5), every one a step of brand's scale. Chosen from renders of the window at
        // 632, 648 and 664 px high, with card padding of 16 by 18 and 16 by 24, in English and Korean, light and dark,
        // full and as a first installation shows it, side by side (SettingsForm.OpeningHeight says why 664).
        //
        // Under the last row the page keeps its own padding (CardRoom), the mirror of the padding over the first row, as
        // every page keeps under its last card - so the gap above the footer stays where it is as the tabs change.
        //
        // The most a row is given past what the tallest row needs. A little more room than the content needs reads as a
        // card at ease; past this it reads as content floating in an empty card, and the rest is space under the rows.
        internal const int OverviewComfort = Brand.SpaceXl;
        // The clear space above a card's button: the largest step of the scale with which the Overview still fits a
        // 1920 by 1080 screen at 150% (SpaceL needed 637 px of window there, where the screen leaves 634).
        internal const int LeadGap = Brand.SpaceM;

        private TableLayoutPanel overviewGrid;
        private TableLayoutPanel nowFacts;
        // Whether the page fits the Overview's rows (FitOverview). Only tests/test_gui_layout.py turns it off, to show the
        // audit a page laid out otherwise.
        private bool fitOverview = true;

        /// An Overview card as v0.6.2 had it and as the person asked for it again in v0.6.5: its heading at the top
        /// left, what it holds under the heading, and the button it leads to at its bottom LEFT, in a row of its own
        /// under the last line. The row takes whatever height the card is given past what it holds, and the button
        /// stands at the row's bottom, so a card stretched beside a taller one keeps its button in its corner and its
        /// content at its top. Every Overview card has the panel's first gap under its heading, button or not, so the
        /// facts in two cards side by side start on one line. A card that leads nowhere (`button` null) keeps its
        /// content where it is.
        ///
        /// v0.6.4 pinned the button to the bottom RIGHT, beside the last lines where they left room (SoftPin); the
        /// person found the first screen better with v0.6.2's buttons at the left, where the eye comes down the card
        /// and finds them - and a button under the content never makes a name wrap for its sake.
        private void Lead(TableLayoutPanel card, Button button)
        {
            Control heading = card.Controls[0];
            heading.Margin = Pad(0, 0, 0, Brand.CardFirstGap);
            card.RowStyles.Clear();
            for (int i = 0; i < card.Controls.Count; i++) card.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            if (button == null) return;
            // Clear of the last line by the scale's medium step, never less, and at the bottom of what is left.
            button.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;
            button.Margin = Pad(0, LeadGap, 0, 0);
            card.Controls.Add(button);
            card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            led[button] = card;
        }

        // Every control led to from the bottom left of an Overview card (Lead), and that card, for LayoutAudit to hold
        // each to its corner.
        private readonly Dictionary<Control, Control> led = new Dictionary<Control, Control>();

        /// What each of the Overview's rows needs `width` wide, margins and all: its tallest card as a table measures
        /// it, at the narrower column's width.
        private static int[] OverviewRowNeeds(TableLayoutPanel grid, int width)
        {
            var needs = new int[OverviewRows];
            int column = Math.Max(1, (width - grid.Padding.Horizontal) / Math.Max(1, grid.ColumnCount));
            foreach (Control child in grid.Controls)
            {
                if (!Soft.OwnVisible(child)) continue;
                int row = grid.GetPositionFromControl(child).Row;
                if (row < 0 || row >= needs.Length) continue;
                int room = Math.Max(1, column - child.Margin.Horizontal);
                int height = child.AutoSize ? child.GetPreferredSize(new Size(room, 0)).Height : child.Height;
                needs[row] = Math.Max(needs[row], height + child.Margin.Vertical);
            }
            return needs;
        }

        /// The Overview's rows and the space under them (v0.6.5). The person found v0.6.4's cards, stretched down the
        /// whole page, emptier than they should be, with what they held floating at their tops - "white space is part
        /// of the design". Now every card is as tall as the tallest row needs, and a little more, and what a taller
        /// window has past that is space under the last row, not a band inside every card (OverviewHeights). Under the
        /// last row the page keeps its own padding, as every page keeps under its last card: v0.6.5 first kept the gap
        /// between cards there as well, inside that padding, and the review found 41 px above the footer where Pending
        /// and History leave 27 - and 87 on a first installation, whose short second row was left short over a band.
        /// Worked out before the page lays the grid out (its Layout event), at the width the grid is about to be given;
        /// the grid's MinimumSize is what the rows need, which is how tall the page counts it (SoftPage), so the page
        /// scrolls only when the rows themselves do not fit.
        private void FitOverview(SoftPage page, TableLayoutPanel grid)
        {
            int width = page.DisplayRectangle.Width;
            // From the first row's top to the page's edge, and the page's own padding under the last row.
            int room = page.ClientSize.Height - page.Padding.Top;
            int rest = page.Padding.Bottom;
            if (!fitOverview || width <= 0 || room - rest <= 0) return;
            int[] needs = OverviewRowNeeds(grid, width);
            int[] heights = OverviewHeights(needs, room, rest, Px(OverviewComfort));
            int total = 0;
            foreach (int need in needs) total += need;
            bool changed = grid.MinimumSize.Height != total;
            for (int i = 0; i < heights.Length && !changed; i++)
                changed = grid.RowStyles[i].SizeType != SizeType.Absolute || (int)grid.RowStyles[i].Height != heights[i];
            if (!changed) return;
            // One layout of the grid for all of it, at the size it has; the page then gives it its new one.
            grid.SuspendLayout();
            if (grid.MinimumSize.Height != total) grid.MinimumSize = new Size(0, total);
            for (int i = 0; i < heights.Length; i++)
            {
                grid.RowStyles[i].SizeType = SizeType.Absolute;
                grid.RowStyles[i].Height = heights[i];
            }
            grid.ResumeLayout(true);
        }

        /// How tall each of the Overview's rows is, for rows that need `needs` (margins and all), `room` from the first
        /// row's top to the page's edge, with `rest` - the page's own padding - kept under the last row (v0.6.5):
        ///   * the rows are alike, each as tall as the tallest needs and an even share of what is left past that, never
        ///     more than `comfort`: a grid of cards of one height, the gap under it the page's own, and in a taller window
        ///     what is left past comfort is space under the rows rather than every card stretching until what it holds
        ///     floats. A card's room does not follow how little the other row holds - Right now stays where it is when
        ///     History cannot be read, or when a first installation has nothing finished yet. v0.6.5 first left such a
        ///     short row short, over a band 87 px high above the footer;
        ///   * where the page has no room for every row as tall as the tallest, each row what it needs, and what the page
        ///     has past that raises the shortest rows toward the tallest;
        ///   * where it has less than they need, the rows what they need, and the page scrolls.
        /// In whole pixels.
        internal static int[] OverviewHeights(int[] needs, int room, int rest, int comfort)
        {
            int rows = needs.Length, total = 0, tallest = 0;
            foreach (int need in needs)
            {
                total += need;
                tallest = Math.Max(tallest, need);
            }
            var heights = new int[rows];
            if (rows == 0) return heights;
            int free = room - rest;
            if (free >= rows * tallest)
            {
                int part = Math.Min(comfort, (free - rows * tallest) / rows);
                for (int i = 0; i < rows; i++) heights[i] = tallest + part;
                return heights;
            }
            for (int i = 0; i < rows; i++) heights[i] = needs[i];
            // A pixel at a time to the shortest row, the first of those alike: fewer than the rows' difference in all.
            for (int left = free - total; left > 0; left--)
            {
                int shortest = 0;
                for (int i = 1; i < rows; i++)
                    if (heights[i] < heights[shortest]) shortest = i;
                if (heights[shortest] >= tallest) break;
                heights[shortest]++;
            }
            return heights;
        }

        // Every control pinned to the bottom right of a block - the header, a row - and that block, for LayoutAudit to
        // hold each to its corner.
        private readonly Dictionary<Control, Control> pinned = new Dictionary<Control, Control>();

        private void Pinned(Control control, Control block)
        {
            pinned[control] = block;
        }

        /// Forgets the pinned controls no longer in the window: the Settings editors are built again after
        /// Restore defaults, and the rows the old ones were pinned in are gone.
        private void ForgetPins()
        {
            foreach (Control control in new List<Control>(pinned.Keys))
            {
                bool inWindow = false;
                for (Control c = pinned[control]; c != null && !inWindow; c = c.Parent) inWindow = c == this;
                if (!inWindow) pinned.Remove(control);
            }
        }

        /// The longest a finished conversation's name is drawn in Recently finished: what how each one
        /// ended leaves of the card, so the outcome and its age are whole and a long name gives way -
        /// down to 80 px, past which the outcome gives way too. Again whenever the outcomes and their ages
        /// are written (FillRecent) and whenever the card's width changes.
        private void FitRecentNames()
        {
            int widest = 0;
            foreach (Control control in recentGrid.Controls)
                if (control.Tag != null) widest = Math.Max(widest, control.GetPreferredSize(Size.Empty).Width + control.Margin.Horizontal);
            int room = Math.Max(Px(80), recentGrid.ClientSize.Width - widest - Px(18));
            foreach (Control control in recentGrid.Controls)
                if (control.Tag == null && control.MaximumSize.Width != room) control.MaximumSize = new Size(room, 0);
        }

        private const int RecentRows = 4;

        private void FillRecent(List<object> history)
        {
            // Rebuilt only when what it shows changed: every five seconds the same rows
            // would otherwise be torn down and put back, and the card would flicker.
            var rows = new List<Dictionary<string, object>>();
            if (history != null)
                foreach (object entry in history)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row != null && Number(row, "outcome_at") > 0) rows.Add(row);
                    if (rows.Count == RecentRows) break;
                }
            var signature = new StringBuilder();
            foreach (var row in rows)
                signature.Append(Str(row, "interruption_id")).Append(Str(row, "code"))
                         .Append(Conversation(row)).Append('|');
            string key = signature.ToString();
            recentGrid.SuspendLayout();
            if (key != recentShown)
            {
                recentShown = key;
                recentGrid.Controls.Clear();
                foreach (var row in rows)
                {
                    // One line each, whatever the names are (see LineLabel).
                    var name = new LineLabel();
                    name.Text = Conversation(row);
                    name.ForeColor = Secondary;
                    name.Margin = Pad(0, 3, 18, 3);
                    var outcome = new LineLabel();
                    outcome.Text = CodeLabel(row);
                    outcome.ForeColor = Ink;
                    outcome.Margin = Pad(0, 3, 0, 3);
                    outcome.Tag = row;
                    recentGrid.Controls.Add(name);
                    recentGrid.Controls.Add(outcome);
                }
                recentEmpty.Text = S("history.empty", "No recoveries yet");
                recentEmpty.Visible = rows.Count == 0;
            }
            // The age moves on its own, so it is rewritten every time without a rebuild.
            foreach (Control control in recentGrid.Controls)
            {
                var row = control.Tag as Dictionary<string, object>;
                if (row != null) control.Text = CodeLabel(row) + "  ·  " + Ago(Number(row, "outcome_at"));
            }
            // Fitted to what each outcome now says, age and all. Fitted while the outcomes held no age, rows
            // rebuilt on a page already laid out gave the names the outcomes' room, and the grid - its width
            // unchanged - never fitted them again: every outcome ended in an ellipsis until the window was
            // resized (v0.6.4, measured). Unchanged, it changes nothing and nothing is laid out.
            FitRecentNames();
            recentGrid.ResumeLayout(true);
        }

        private void ClearRecent(string reason)
        {
            recentShown = null;
            recentGrid.Controls.Clear();
            recentEmpty.Text = reason;
            recentEmpty.Visible = true;
        }

        // ----------------------------------------------------------------- pending
        private Control BuildPending()
        {
            Panel page = Page();
            pendingList = List(S("nav.pending", "Pending"),
                               Col(S("pending.col_conversation", "Conversation"), 140),
                               Col(S("pending.col_status", "Status"), 190),
                               Col(S("pending.col_category", "Kind"), 110),
                               Col(S("pending.col_next", "Next check"), 84),
                               Col(S("pending.col_attempts", "Attempts"), 70),
                               Col(S("pending.col_resume", "Auto-resume"), 100));
            pendingEmpty = GroundText(S("pending.empty", "Nothing is waiting"));
            pendingEmpty.ForeColor = Secondary;
            pendingEmpty.Dock = DockStyle.Top;
            pendingEmpty.Padding = Pad(8, 0, 0, 10);

            FlowLayoutPanel row = ButtonRow();
            retryButton = MakeButton(S("action.retry_now", "Retry now"), true, delegate { RetryNow(); });
            cancelButton = MakeButton(S("action.cancel", "Cancel"), false, delegate { CancelSelected(); });
            timelineButton = MakeButton(S("action.timeline", "Timeline"), false, delegate { ShowTimeline(pendingList); });
            threadButton = MakeButton(S("action.thread_off", "Turn off for this conversation"), false,
                                      delegate { ToggleThread(pendingList); });
            // Only cancelling is offered for everything at once: it can only reduce what runs.
            cancelAllButton = MakeButton(S("action.cancel_all", "Cancel all"), false, delegate { CancelAll(); });
            foreach (Button button in new[] { retryButton, cancelButton, timelineButton, threadButton, cancelAllButton })
            {
                button.Margin = Pad(0, 0, 6, 0);
                row.Controls.Add(button);
            }
            // What the last Retry now actually did, in words - it is a request to look again,
            // and saying so each time is how nobody comes to read it as "send now". It stays
            // until another row is chosen or its record leaves the list.
            pendingNote = Note();
            row.Controls.Add(pendingNote);
            pendingList.SelectedIndexChanged += delegate
            {
                if (filling) return;
                if (pendingNoteFor == BulkNote) pendingNoteFor = null;
                ShowPendingNote();
                ShowExplain();
                UpdatePendingButtons();
            };
            // The Auto-resume column is a check box for exactly the task on its row. A left click
            // on it, or Space on the chosen row, switches it. The request carries that row's
            // interruption and conversation ids, and the control layer refuses it if the record
            // has since finished, gone, or turned out to belong to another conversation.
            pendingList.MouseClick += delegate(object sender, MouseEventArgs e)
            {
                // A ListView raises MouseClick for the right button as well, and turning recovery
                // off asks nothing, so a right-click on the box switched a conversation off.
                if (e.Button != MouseButtons.Left) return;
                ListViewHitTestInfo hit = pendingList.HitTest(e.Location);
                if (hit.Item == null || hit.SubItem == null) return;
                if (hit.Item.SubItems.IndexOf(hit.SubItem) != ResumeColumn) return;
                ToggleAutoResume(hit.Item.Tag as Dictionary<string, object>);
            };
            pendingList.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode != Keys.Space) return;
                ToggleAutoResume(Selected(pendingList));
                e.Handled = true;
            };

            // As tall as the list's card beside it, always: its checks scroll inside it, on the soft bar,
            // below its heading. It used to scroll as a whole and ask the page for its full height, and
            // thirteen checks made the whole Pending page scroll, list and buttons with it.
            TableLayoutPanel explain = MakeCard(S("explain.title", "Why it is waiting"));
            explain.Dock = DockStyle.Fill;
            explain.AutoSize = false;
            explain.Margin = Pad(Brand.PageGap, 0, 0, 0);
            explainAsOf = Value("");
            explainAsOf.ForeColor = Secondary;
            explain.Controls.Add(explainAsOf);
            explainList = new GateList();
            explainList.Dock = DockStyle.Top;
            explainList.Font = Font;
            explainList.AccessibleName = S("explain.title", "Why it is waiting");
            var gates = new SoftPage();
            gates.BackColor = Card;
            gates.Dock = DockStyle.Fill;
            gates.Margin = new Padding(0);
            // A little room between the results and the bar when it shows; the card's padding is past it.
            gates.Padding = Pad(0, 0, 6, 0);
            gates.Controls.Add(explainList);
            gates.Scrolls = true;
            explain.Controls.Add(gates);
            explain.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            explain.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            explain.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

            // The list and why its task waits, side by side with the panel's gap between them. A
            // table rather than two docked cards: docking ignores margins, and the gap is one. The
            // explanation is a little narrower than it was, so the list keeps its columns in a
            // window of v0.6.2's width.
            var split = new SoftStack();
            split.Dock = DockStyle.Fill;
            split.ColumnCount = 2;
            split.RowCount = 1;
            split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            split.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(Brand.PageGap + 256)));
            split.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            Control listCard = ListCard(pendingList);
            split.Controls.Add(listCard, 0, 0);
            split.Controls.Add(explain, 1, 0);
            // The explanation gives way, down to 200 px, when the list's column headings need the
            // room: Spanish needs about 20 px more than the list has beside a 256-px explanation.
            EventHandler share = delegate
            {
                int needed = HeadingsWidth(pendingList) + listCard.Padding.Horizontal;
                int width = Math.Max(Px(Brand.PageGap + 200), Math.Min(Px(Brand.PageGap + 256), split.ClientSize.Width - needed));
                if ((int)split.ColumnStyles[1].Width != width) split.ColumnStyles[1].Width = width;
            };
            split.SizeChanged += share;
            pendingList.FontChanged += share;

            page.Controls.Add(split);
            page.Controls.Add(pendingEmpty);
            page.Controls.Add(row);
            UpdatePendingButtons();
            ShowExplain();
            return page;
        }

        // ----------------------------------------------------------------- history
        private Control BuildHistory()
        {
            Panel page = Page();
            historyList = List(S("nav.history", "History"),
                               Col(S("pending.col_conversation", "Conversation"), 220),
                               Col(S("history.col_outcome", "Outcome"), 200),
                               Col(S("pending.col_category", "Kind"), 130),
                               Col(S("history.col_detected", "Detected"), 130),
                               Col(S("history.col_finished", "Finished"), 130));
            historyList.SelectedIndexChanged += delegate { if (!filling) UpdateHistoryButtons(); };
            historyEmpty = GroundText(S("history.empty", "No recoveries yet"));
            historyEmpty.ForeColor = Secondary;
            historyEmpty.Dock = DockStyle.Top;
            historyEmpty.Padding = Pad(8, 0, 0, 10);

            FlowLayoutPanel row = ButtonRow();
            historyTimeline = MakeButton(S("action.timeline", "Timeline"), false, delegate { ShowTimeline(historyList); });
            historyReset = MakeButton(S("action.reset_budget", "Give attempts back"), false, delegate { ResetSelected(); });
            // Turning a conversation back on is offered here as well as on Pending: turning it
            // off cancelled its waiting recoveries, so they are in this list, not that one.
            historyThread = MakeButton(S("action.thread_on", "Turn on for this conversation"), false,
                                       delegate { ToggleThread(historyList); });
            historyThread.Visible = false;
            historyClear = MakeButton(S("action.clear_history", "Clear history"), false, delegate { ClearHistory(); });
            foreach (Button button in new[] { historyTimeline, historyReset, historyThread, historyClear })
            {
                button.Margin = Pad(0, 0, 9, 0);
                row.Controls.Add(button);
            }
            historyNote = Note();
            row.Controls.Add(historyNote);
            page.Controls.Add(ListCard(historyList));
            page.Controls.Add(historyEmpty);
            page.Controls.Add(row);
            UpdateHistoryButtons();
            return page;
        }

        // -------------------------------------------------------------- statistics
        private Control BuildStatistics()
        {
            Panel page = Page();
            // A ground, so the lift of the cards under it is not covered where it runs up into it.
            var top = new SoftFlow();
            top.Dock = DockStyle.Top;
            top.AutoSize = true;
            top.Padding = Pad(0, 0, 0, 12);
            var label = GroundText(S("stats.period", "Period"));
            // On the drop-down's centre line: half of what the field is taller than a line of the
            // window's text. Measured in the window's font - the label has no parent yet, and would
            // measure itself in the default one.
            label.Margin = new Padding(0, Math.Max(0, (SoftCombo.FieldHeight - TextRenderer.MeasureText("Ag", Font).Height) / 2), Px(12), 0);
            // A well, as every other drop-down in the window is.
            period = new SoftCombo();
            period.Width = Px(180);
            IgnoreWheel(period);
            period.Items.Add(new Choice("7", S("stats.days7", "Last 7 days")));
            period.Items.Add(new Choice("30", S("stats.days30", "Last 30 days")));
            period.Items.Add(new Choice("", S("stats.all", "All time")));
            period.SelectedIndex = 0;
            period.AccessibleName = S("stats.period", "Period");
            period.SelectedIndexChanged += delegate { LoadStatistics(true); };
            top.Controls.Add(label);
            top.Controls.Add(period);

            TableLayoutPanel grid = Grid(2);
            TableLayoutPanel numbers = MakeCard(S("nav.statistics", "Statistics"));
            numbers.Margin = GridGap(0, true);
            TableLayoutPanel facts = Facts(numbers);
            statsDetected = Fact(facts, S("overview.detected", "Interruptions"));
            statsSent = Fact(facts, S("overview.sent", "Continuations sent"));
            statsRecovered = Fact(facts, S("overview.recovered", "Recovered"));
            statsSuccess = Fact(facts, S("overview.success", "Success rate"));
            statsWait = Fact(facts, S("stats.median_wait", "Median wait before sending"));
            statsRecover = Fact(facts, S("stats.median_recovery", "Median time to recover"));
            statsRetry = Fact(facts, S("stats.retry_now", "Retry now requests"));
            statsKinds = Fact(facts, S("stats.by_category", "By kind"));

            TableLayoutPanel outcomes = MakeCard(S("stats.outcomes", "How recoveries ended"));
            outcomes.Margin = GridGap(1, true);
            chart = new OutcomeChart();
            chart.Dock = DockStyle.Top;
            chart.Height = Px(220);
            chart.BackColor = Card;
            chart.BarColor = Accent;
            chart.TextColor = Ink;
            chart.EmptyText = S("stats.none", "Nothing yet");
            chart.AccessibleName = S("stats.outcomes", "How recoveries ended");
            chart.AccessibleRole = AccessibleRole.Chart;
            chart.Describe();
            outcomes.Controls.Add(chart);

            grid.Controls.Add(numbers, 0, 0);
            grid.Controls.Add(outcomes, 1, 0);
            page.Controls.Add(grid);
            page.Controls.Add(top);
            return page;
        }

        // ------------------------------------------------------------- diagnostics
        private Control BuildDiagnostics()
        {
            Panel page = Page();
            TableLayoutPanel grid = Grid(2);
            TableLayoutPanel health = MakeCard(S("diag.health", "Health"));
            health.Margin = GridGap(0, false);
            TableLayoutPanel facts = Facts(health);
            diagVersion = Fact(facts, S("diag.version", "Version"));
            diagWatcher = Fact(facts, S("diag.watcher", "Watcher"));
            diagLastCheck = Fact(facts, S("diag.last_check", "Last check"));
            diagEngine = Fact(facts, S("diag.engine", "Codex engine"));
            diagRecovery = Fact(facts, S("diag.recovery", "Automatic recovery"));
            diagStartup = Fact(facts, S("diag.startup", "Starts at sign-in"));
            // Blank until somebody asks. Nothing here contacts github.com on its own, so a
            // window that has just opened has nothing to say about updates and says nothing.
            diagUpdate = Fact(facts, S("diag.update", "Updates"));
            diagUpdate.Text = S("diag.update_unasked", "not checked");
            diagUpgrade = Value("");
            diagUpgrade.ForeColor = Accent;
            diagUpgrade.MaximumSize = new Size(Px(360), 0);
            health.Controls.Add(diagUpgrade);

            TableLayoutPanel tools = MakeCard(S("diag.tools", "Tools"));
            tools.Margin = GridGap(1, false);
            exportButton = MakeButton(S("action.export", "Export diagnostics..."), false, delegate { ExportDiagnostics(); });
            repairButton = MakeButton(S("action.repair", "Repair installation"), false, delegate { Repair(); });
            // Repair and update are different things and the two buttons say so: one runs
            // setup over the files that are here, the other fetches different files. They
            // used to be one word apart in a support conversation.
            updateButton = MakeButton(S("action.check_updates", "Check for updates..."), false, delegate { CheckForUpdates(); });
            // The other half of what the upgrade-pending message tells people to do. Starting
            // the watcher has always been in the header; stopping it lived only in the command
            // line, which is the one place a person who uses this window never goes.
            stopButton = MakeButton(S("action.stop_watcher", "Stop watcher"), false, delegate { StopWatcher(); });
            foreach (Button button in new[] {
                exportButton,
                MakeButton(S("action.open_logs", "Open logs folder"), false, delegate { OpenLogs(); }),
                updateButton,
                repairButton,
                stopButton })
            {
                button.Margin = Pad(0, 0, 0, 9);
                tools.Controls.Add(button);
            }
            grid.Controls.Add(health, 0, 0);
            grid.Controls.Add(tools, 1, 0);
            // Under both, across the page: what the Codex Compatibility Registry says about the engine on this machine.
            TableLayoutPanel compat = BuildCompatibility();
            grid.Controls.Add(compat, 0, 1);
            grid.SetColumnSpan(compat, 2);
            page.Controls.Add(grid);
            return page;
        }

        // ---------------------------------------------------------- compatibility
        // The Codex Compatibility Registry, shown to people (v0.6.5): for the Codex engine on this machine, which of the
        // things this product does can be relied on, in the four words the registry has - verified, compatible,
        // incompatible, unknown - each with what it means; when that was checked; and which data was in force, the data
        // bundled with this version or data refreshed from GitHub, by its sequence number. The panel in Codex shows the
        // same view, read-only (mcpui.renderCompatibility).
        //
        // What is shown is the watcher's report, read on the long-lived bridge like every other fact on this page: the
        // bridge validates it and checks it still describes the engine on disk, and says why when it cannot be used. It
        // is never the live check, which runs Codex, except after a refresh: the one the refresh button's answer carries,
        // and the one made after an update check's refresh (CheckAfterRefresh). Either stands in for the report until
        // the watcher's own catches up, never longer than a report may be relied on, and not past a report that has
        // since become unusable (LiveStands) - so a watcher that is not running cannot put the data before back on the
        // card beside a note saying it is no longer in force.
        //
        // The refresh is the only thing here that reaches the network, and only when its button is pressed: the bridge
        // runs this installation's own bootstrap, which asks raw.githubusercontent.com for the one document and hands it
        // to the validator. It can take minutes, so it goes over the one-shot bridge from a worker thread - never over
        // the long-lived pipe the page is painted from, which it would hold for all that time. Every answer is said as
        // itself: refreshed, refused (and why), unavailable, incomplete, failed, and busy while an installation or a
        // repair is replacing the files it runs. Check for updates refreshes the data too, and says so here in the same
        // words (CheckForUpdates, CompatibilityLine).

        // The capabilities, in the registry's own order (compat.CAPABILITIES). Four are not offered yet; their rows are
        // left out, as the command line leaves them out.
        private static readonly string[] CompatOrder = { "engine_present", "exact_thread_recovery", "usage_limit_detection",
            "usage_reset_hint", "usage_probe", "thread_eligibility", "loaded_state_detection", "recovery_turn_tracking",
            "queue_withdraw", "outcome_observation", "transient_classification", "projection_freshness",
            "empty_response_recovery", "not_loaded_recovery", "goal_continuation", "subagent_recovery" };

        // The four states, in the order their meanings are listed.
        private static readonly string[] CompatStates = { "VERIFIED", "COMPATIBLE", "INCOMPATIBLE", "UNKNOWN" };

        // How long the live check a refresh brought may stand in for the watcher's report at most: as long as a report
        // may be relied on at all (compat.REPORT_MAX_AGE - the watcher's interval between evaluations, its longest wait
        // between ticks, and a margin). Past it the live check is as old as a report too old to use, and the report,
        // older still, says so.
        private const double CompatMaxAge = 4500;

        // The argument that asks the bridge's `compatibility` for a live check instead of the watcher's report.
        private const string LiveArgument = "{\"live\":true}";

        private TableLayoutPanel BuildCompatibility()
        {
            TableLayoutPanel card = MakeCard(S("compat.title", "Codex compatibility"));
            // The width of the page, under the two cards over it: no gap of its own beside them or under it.
            card.Margin = new Padding(0);
            TableLayoutPanel facts = Facts(card);
            compatOverall = Fact(facts, S("compat.overall", "Overall"));
            compatEngine = Fact(facts, S("compat.engine", "Codex version"));
            compatChecked = Fact(facts, S("compat.checked", "Checked"));
            compatData = Fact(facts, S("compat.data", "Data in force"));
            // What the view cannot vouch for - no report, one too old, an engine that changed, a watcher still acting on
            // what it found when it started, refreshed data that expired - in the accent, as the upgrade note above is.
            compatNotice = HelpText("");
            compatNotice.ForeColor = Accent;
            // Every group on the card - the facts, this, the parts, what the words mean, the refresh - the scale's
            // medium step apart, as the button is from what its card holds (LeadGap).
            compatNotice.Margin = Pad(0, Brand.SpaceM, 0, 0);
            // As wide as the card, which is the page's width: at the help text's 600 px a sentence of this card broke
            // in two with most of the card empty beside it.
            compatNotice.MaximumSize = Size.Empty;
            card.Controls.Add(compatNotice);
            // The parts, in two lists side by side: rows as the panel's settings rows are, a hairline between each two
            // and the state as a chip at the end (GateList, as Why it is waiting draws its checks).
            var lists = new SoftStack();
            lists.ColumnCount = 2;
            lists.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            lists.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            lists.AutoSize = true;
            lists.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            lists.Dock = DockStyle.Fill;
            lists.Margin = Pad(0, Brand.SpaceM, 0, 0);
            lists.BackColor = Card;
            compatLeft = CompatList();
            compatLeft.Margin = Pad(0, 0, Brand.SpaceXl / 2, 0);
            compatRight = CompatList();
            compatRight.Margin = Pad(Brand.SpaceXl / 2, 0, 0, 0);
            lists.Controls.Add(compatLeft, 0, 0);
            lists.Controls.Add(compatRight, 1, 0);
            card.Controls.Add(lists);
            compatLists = lists;
            // What each state word on the card means, one line each, for the words the card shows.
            compatLegend = HelpText("");
            compatLegend.Margin = Pad(0, Brand.SpaceM, 0, 0);
            compatLegend.MaximumSize = Size.Empty;
            card.Controls.Add(compatLegend);
            // The refresh, at the card's bottom left as every card's button now is, and beside it what it last answered.
            var row = new SoftStack();
            row.ColumnCount = 2;
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.Dock = DockStyle.Fill;
            row.Margin = Pad(0, LeadGap, 0, 0);
            row.BackColor = Card;
            compatButton = MakeButton(S("diag.compat_refresh", "Refresh compatibility data"), false, delegate { RefreshCompatibility(); });
            compatButton.Margin = new Padding(0);
            compatButton.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;
            compatButton.Enabled = busy == 0;
            compatNote = Note();
            compatNote.AutoSize = true;
            compatNote.Anchor = AnchorStyles.Left | AnchorStyles.Right;
            compatNote.Margin = Pad(Brand.SpaceM, 0, 0, 0);
            compatNote.Text = compatSaid;
            row.Controls.Add(compatButton, 0, 0);
            row.Controls.Add(compatNote, 1, 0);
            card.Controls.Add(row);
            ShowCompatibility();
            return card;
        }

        private GateList CompatList()
        {
            var list = new GateList();
            list.Dock = DockStyle.Fill;
            list.Font = Font;
            list.AccessibleName = S("compat.title", "Codex compatibility");
            return list;
        }

        /// A view of the registry has arrived: the watcher's report (`live` false), read on the long-lived bridge, or the
        /// live check a refresh brought - the refresh button's answer, or the check made after an update check's refresh.
        /// The live check is shown for as long as it stands over the reports read after it (LiveStands).
        private void ApplyCompatibility(Dictionary<string, object> view, bool live)
        {
            if (view == null) return;
            if (live)
            {
                compatLive = view;
                // What the watcher's report said as this check was made: whatever it says later that it did not say
                // then is news this check never saw.
                compatLiveOver = Reading(compatView);
            }
            else
            {
                compatView = view;
                if (compatLive != null && !LiveStands(compatLive, compatLiveOver, view, Now())) compatLive = null;
            }
            compatUnreadable = false;
            ShowCompatibility();
        }

        /// Whether the live check a refresh brought (`live`) still stands over the watcher's report just read. A live
        /// check is relied on as a report is, and no longer:
        /// - a usable report as new as it takes its place: the watcher has caught up;
        /// - past the age a report may have (CompatMaxAge) it is as stale as one;
        /// - a report that has since become unusable - Codex changed under it, or it went missing, unreadable or too
        ///   old - ends it, failing closed as every reader of the report does, since the live check cannot tell whether
        ///   that change reached it too. What the report already said when the check was made (`over`), the check has
        ///   seen past: a watcher that is not running, whose report is missing, older or about the Codex before, leaves
        ///   it standing - and never snaps the card back to the data before the refresh.
        internal static bool LiveStands(Dictionary<string, object> live, string over, Dictionary<string, object> report, double now)
        {
            double at = Number(live, "checked_at");
            if (now - at >= CompatMaxAge) return false;
            if (Str(report, "status") == "ok") return Number(report, "checked_at") < at;
            return Reading(report) == over;
        }

        /// What a read of the report said, as its status and its time: "ok@1757000000.5", "absent@0", or "" for none.
        internal static string Reading(Dictionary<string, object> view)
        {
            if (view == null) return "";
            return (Str(view, "status") ?? "invalid") + "@" + Number(view, "checked_at").ToString("R", CultureInfo.InvariantCulture);
        }

        /// The Diagnostics card from the view in hand (ApplyCompatibility): nothing yet before the first read, and a read
        /// that failed said as one - never the last answer as if it were current.
        private void ShowCompatibility()
        {
            if (compatOverall == null) return;
            Dictionary<string, object> view = compatLive ?? compatView;
            var shown = new List<string[]>();
            var notices = new List<string>();
            var states = new List<string>();
            if (view == null)
            {
                string nothing = compatUnreadable ? S("pending.unavailable", "This cannot be read right now") : "-";
                compatOverall.Text = compatEngine.Text = compatChecked.Text = compatData.Text = compatUnreadable ? S("diag.unknown", "unknown") : "-";
                SetLines(compatNotice, compatUnreadable ? new List<string> { nothing } : notices);
                ShowParts(shown);
                SetLines(compatLegend, notices);
                return;
            }
            string status = Str(view, "status") ?? "invalid";
            bool usable = status == "ok";
            string overall = CompatState(Str(view, "overall"));
            compatOverall.Text = S("compat.state." + overall, overall.ToLowerInvariant());
            var engine = Map(view, "engine");
            string version = Str(engine, "version");
            // A report that cannot be used vouches for nothing it says - not the Codex it was about, which may since have
            // changed, nor the data then in force: "-" for both, as the panel has them, and never "not found". When it
            // was made is still said: it is what makes a report too old.
            compatEngine.Text = !usable ? "-" : !string.IsNullOrEmpty(version) ? version : S("compat.engine_none", "not found");
            compatChecked.Text = Ago(Number(view, "checked_at"));
            compatData.Text = usable ? CompatData(Map(view, "data")) : "-";
            // Why the view cannot be used - every part is unknown then, for that one reason, so the parts are not listed.
            if (!usable) notices.Add(S("compat.status." + status, S("compat.status.invalid", "The last check could not be read, so nothing in it is relied on.")));
            string acting = Str(view, "acting");
            if (usable && acting != null && acting != Str(view, "overall"))
                notices.Add(S("diag.compat_acting_differs",
                              "The watcher is still acting on what it found when it started. Stop it and start it again from this page to check again."));
            string cache = usable ? Str(Map(view, "data"), "cache") : null;
            if (cache == "expired" || cache == "from_the_future" || cache == "rejected" || cache == "superseded" || cache == "from_newer_product")
                notices.Add(S("compat.cache." + cache, cache.Replace('_', ' ')));
            SetLines(compatNotice, notices);
            var capabilities = Map(view, "capabilities");
            // The words the card shows, explained: the overall's and the parts', when there are parts to show. A view that
            // cannot be used is unknown for the one reason its notice gives, which the legend's reason would contradict.
            if (usable) states.Add(overall);
            if (usable && capabilities != null)
                foreach (string name in CompatOrder)
                {
                    var entry = Map(capabilities, name);
                    if (entry == null || Str(entry, "reason") == "not_implemented") continue;
                    string state = CompatState(Str(entry, "state"));
                    if (!states.Contains(state)) states.Add(state);
                    shown.Add(new[] { S("compat.capability." + name, name.Replace('_', ' ')),
                                      S("compat.state." + state, state.ToLowerInvariant()),
                                      state == "INCOMPATIBLE" ? "BLOCK" : state == "UNKNOWN" ? "UNKNOWN" : "PASS" });
                }
            ShowParts(shown);
            var meanings = new List<string>();
            foreach (string state in CompatStates)
                if (states.Contains(state)) meanings.Add(S("compat.meaning." + state, state));
            SetLines(compatLegend, meanings);
        }

        /// The parts in the two lists, the first half on the left - and no room taken while there are none.
        private void ShowParts(List<string[]> shown)
        {
            int half = (shown.Count + 1) / 2;
            compatLeft.SetRows(shown.GetRange(0, half), "");
            compatRight.SetRows(shown.GetRange(half, shown.Count - half), "");
            bool any = shown.Count > 0;
            if (Soft.OwnVisible(compatLists) != any) compatLists.Visible = any;
        }

        /// A registry state word from any of the vocabularies a view carries it in: the four capability states, and the
        /// coarse word the overall and the watcher's gate use. Anything else is UNKNOWN, as the registry reads it.
        internal static string CompatState(string word)
        {
            if (word == "VERIFIED" || word == "verified") return "VERIFIED";
            if (word == "COMPATIBLE" || word == "structurally_compatible") return "COMPATIBLE";
            if (word == "INCOMPATIBLE" || word == "incompatible") return "INCOMPATIBLE";
            return "UNKNOWN";
        }

        /// Which data was in force: the data bundled with this version, data refreshed from GitHub, or none, with its
        /// sequence number.
        private string CompatData(Dictionary<string, object> data)
        {
            if (data == null) return "-";
            string source = Str(data, "source") ?? "none";
            if (source != "cache" && source != "bundled") source = "none";
            string said = S("compat.source." + source, source);
            object sequence = Get(data, source == "cache" ? "cache_sequence" : "bundled_sequence");
            if (source == "none" || !(sequence is double)) return said;
            return S("compat.source_sequence", "{source}, #{sequence}").Replace("{source}", said)
                   .Replace("{sequence}", ((int)(double)sequence).ToString(CultureInfo.InvariantCulture));
        }

        /// Lines of text in a label that says nothing, and takes no room, while it has none. Its own visibility, not
        /// Visible's answer, which is false for every label on a page that is not on screen - a card updated while
        /// another page was showing kept a line it no longer had.
        private static void SetLines(Label label, List<string> lines)
        {
            string text = string.Join(Environment.NewLine, lines.ToArray());
            if (label.Text != text) label.Text = text;
            bool any = text.Length > 0;
            if (Soft.OwnVisible(label) != any) label.Visible = any;
        }

        /// The registry's view for the card: the watcher's report, as the page is shown and with every read while it is.
        /// A file read, as quick as the dashboard's own, so it goes over the long-lived bridge; never the live check.
        private void LoadCompatibility()
        {
            if (compatOverall == null || loadingCompat || auditing) return;
            loadingCompat = true;
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call("compatibility", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    loadingCompat = false;
                    var view = Ok(reply) ? Map(reply, "compatibility") : null;
                    if (view != null) ApplyCompatibility(view, false);
                    else
                    {
                        // Unreadable now: the last report is not shown as if it were current. A live check still
                        // stands - a failed read says nothing about it - but no longer than a report would.
                        compatView = null;
                        compatUnreadable = true;
                        if (compatLive != null && Now() - Number(compatLive, "checked_at") >= CompatMaxAge) compatLive = null;
                        ShowCompatibility();
                    }
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { loadingCompat = false; }
            });
        }

        /// The refresh button: the registry data asked for once, from its one address, on the one-shot bridge from a
        /// worker thread (see the note at the top of this section). Every other action waits while it runs, as it does
        /// for any action here, and what it answered is said beside the button.
        private void RefreshCompatibility()
        {
            if (compatRefreshing) return;
            compatRefreshing = true;
            SetBusy(true);
            SetCompatNote(S("diag.compat_refreshing", "Asking GitHub for the compatibility data..."));
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string outcome;
                Dictionary<string, object> result;
                RunCompatibilityRefresh(bridge, out outcome, out result);
                MethodInvoker finish = delegate
                {
                    compatRefreshing = false;
                    SetBusy(false);
                    var view = Map(result, "compatibility");
                    if (view != null) ApplyCompatibility(view, Equals(Get(view, "live"), true));
                    object sequence = Get(result, "sequence") ?? Get(Map(view, "data"), "cache_sequence");
                    SetCompatNote(CompatibilitySaid(outcome, sequence is double ? ((int)(double)sequence).ToString(CultureInfo.InvariantCulture) : "?",
                                                    Str(result, "reason")));
                    if (view == null) LoadCompatibility();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// Runs the refresh and says which of six things happened. Busy first: an installation or a repair holds the
        /// installer's lock while it replaces the files the refresh would run, so the lock is looked at - taken and let
        /// go at once, never held for the refresh, so an installation that starts meanwhile is not turned away for it.
        private static void RunCompatibilityRefresh(PersistentBridge bridge, out string outcome, out Dictionary<string, object> result)
        {
            outcome = "failed";
            result = null;
            try
            {
                using (var gate = new System.Threading.Mutex(false, "Local\\CodexAutoResume.Install"))
                {
                    bool free;
                    try { free = gate.WaitOne(0); }
                    catch (System.Threading.AbandonedMutexException) { free = true; }
                    if (!free) { outcome = "busy"; return; }
                    gate.ReleaseMutex();
                }
                Dictionary<string, object> reply = bridge.CallOnce("compat-refresh", null);
                result = Ok(reply) ? Map(reply, "result") : null;
                outcome = CompatibilityOutcome(reply);
            }
            catch (Exception) { outcome = "failed"; }
        }

        /// The refresh's answer from the bridge's reply: `refreshed`, `refused`, `unavailable` or `incomplete` as it said
        /// it, and anything else - no reply, a refusal of the request, a word this window does not know - `failed`.
        internal static string CompatibilityOutcome(Dictionary<string, object> reply)
        {
            if (!Ok(reply)) return "failed";
            string answer = Str(Map(reply, "result"), "answer");
            if (answer == "refreshed" || answer == "refused" || answer == "unavailable" || answer == "incomplete") return answer;
            return "failed";
        }

        /// The `compatibility:` line an update check prints once github.com has answered - `refreshed <sequence>`,
        /// `refused <reason>` or `unavailable` (scripts/bootstrap.ps1) - as those words, or null when there is none or
        /// it says something else. The last one counts, as the `update:` line's does.
        internal static string CompatibilityLine(string printed)
        {
            string line = null;
            foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
            {
                string trimmed = raw.Trim();
                if (trimmed.StartsWith("compatibility: ", StringComparison.Ordinal)) line = trimmed.Substring("compatibility: ".Length);
            }
            if (line == null) return null;
            string[] words = line.Split(' ');
            if (words.Length == 1 && words[0] == "unavailable") return "unavailable";
            if (words.Length != 2) return null;
            if (words[0] == "refreshed" && Plain(words[1], true)) return line;
            if (words[0] == "refused" && Plain(words[1], false)) return line;
            return null;
        }

        // A sequence number (digits), or a refusal's code (lower-case letters and underscores), one to forty long.
        private static bool Plain(string word, bool digits)
        {
            if (word.Length == 0 || word.Length > 40) return false;
            foreach (char c in word)
                if (digits ? !(c >= '0' && c <= '9') : !((c >= 'a' && c <= 'z') || c == '_')) return false;
            return true;
        }

        /// What the update check's `compatibility:` line said, on the card, in the refresh's own words - the second
        /// request the check made, and its result - with the live check made after it when it brought new data
        /// (CheckAfterRefresh), as the refresh button's answer carries one, and the card read again.
        private void ReportCompatibilityLine(string line, Dictionary<string, object> live)
        {
            if (line == null) return;
            string[] words = line.Split(' ');
            SetCompatNote(CompatibilitySaid(words[0], words[0] == "refreshed" ? words[1] : "?", words[0] == "refused" ? words[1] : null));
            // A watcher that is not running has not looked at the new data, and its last report still says the data
            // before was in force - beside a note saying it no longer is. The live check says what is in force now.
            if (live != null) ApplyCompatibility(live, true);
            LoadCompatibility();
        }

        /// After an update check brought in new data (its `compatibility:` line says `refreshed`): the live check the
        /// refresh button's answer carries, which the check's own script does not make. It runs Codex's `--version` and
        /// `queue --help` on this machine and asks nothing of the network; on the one-shot bridge, from the update
        /// check's worker thread, never on the long-lived pipe the window paints from. Null for any other answer, or
        /// when the check could not be made - the watcher's report is what the card has then.
        private static Dictionary<string, object> CheckAfterRefresh(PersistentBridge bridge, string line)
        {
            if (line == null || !line.StartsWith("refreshed ", StringComparison.Ordinal)) return null;
            try
            {
                Dictionary<string, object> reply = bridge.CallOnce("compatibility", LiveArgument);
                var view = Ok(reply) ? Map(reply, "compatibility") : null;
                return view != null && Equals(Get(view, "live"), true) ? view : null;
            }
            catch (Exception) { return null; }
        }

        /// One sentence for what a refresh answered, from the refresh button or an update check.
        internal string CompatibilitySaid(string outcome, string sequence, string reason)
        {
            if (outcome == "refreshed")
                return S("diag.compat_refreshed", "Compatibility data #{sequence} is now in force.", "sequence", sequence);
            if (outcome == "refused")
                return S("diag.compat_refused", "The downloaded data was refused ({code}): {reason}. The data in force before still applies.")
                       .Replace("{code}", reason ?? "?").Replace("{reason}", RefusedBecause(reason));
            if (outcome == "unavailable")
                return S("diag.compat_unavailable", "GitHub could not be reached, so nothing was changed.");
            if (outcome == "incomplete")
                return S("diag.compat_incomplete",
                         "Files this installation is made of are missing, so the data could not be refreshed. Install it again from the release archive.");
            if (outcome == "busy")
                return S("diag.compat_busy", "An installation or a repair is running. Refresh once it has finished.");
            return S("diag.compat_failed", "The refresh did not finish, so nothing was changed.");
        }

        /// Why the validator refused a document, in plain words: one of six, for the eighteen codes it can give
        /// (compat.IMPORT_REASONS). The code itself is said beside it, for whoever asks for help with it.
        private string RefusedBecause(string code)
        {
            if (code == "from_the_future") return S("compat.refused.future", "it is dated after this computer's clock");
            if (code == "from_newer_product") return S("compat.refused.newer", "it needs a newer version of Codex Auto Resume");
            if (code == "rollback") return S("compat.refused.rollback", "it is older than the data already in force");
            if (code == "unreadable" || code == "not_a_json_file") return S("compat.refused.unreadable", "it could not be read");
            if (code == "write_failed") return S("compat.refused.not_saved", "it could not be saved on this computer");
            return S("compat.refused.invalid", "it is not valid compatibility data");
        }

        /// What the refresh last answered, beside its button: kept for a card built later, and said to a screen reader as
        /// it changes (NoteLabel).
        private void SetCompatNote(string text)
        {
            compatSaid = text ?? "";
            if (compatNote != null) SetNote(compatNote, compatSaid);
        }

        // ------------------------------------------------------------------ clock
        private void StartClock()
        {
            // Started again, the same clock: after a reopen whose new window never came up (FinishReopen).
            if (clock != null)
            {
                clock.Start();
                return;
            }
            clock = new Timer();
            clock.Interval = 1000;
            clock.Tick += delegate
            {
                ticks++;
                UpdateCountdowns();
                // The taskbar button asks again whether it may move - a Reduce motion saved, Windows' animation
                // effects, High Contrast or battery saver turned on or off - within a second of it (TaskbarMark.Sync).
                if (taskbar != null) taskbar.Sync();
                // Every second too, so a usage reset that passes while a row stays selected
                // makes Retry now available without waiting for the next read.
                UpdatePendingButtons();
                // The data every five seconds, the countdown every second. Nothing on the
                // Settings page is refreshed under a person who is editing it.
                if (ticks % 5 == 0 && currentPage != "settings")
                {
                    RefreshNow();
                    if (currentPage == "statistics") LoadStatistics();
                    // The watcher's report, read as the rest of the page is. Never the refresh: that is a request to
                    // GitHub, and only its button makes one.
                    if (currentPage == "diagnostics") LoadCompatibility();
                }
                // A language or theme changed elsewhere, or edits put back under a pending reopen.
                TickReopen();
            };
            clock.Start();
        }

        private void StopClock()
        {
            if (clock != null) clock.Stop();
        }

        // A read for its own sake: the clock, a page switch, F5.
        private void RefreshNow()
        {
            Reread(false);
        }

        // A read after this window changed something. If a read is already in flight it may
        // have started before that change, so its answer is thrown away and a new read made.
        private void RefreshAfterChange()
        {
            Reread(true);
        }

        private void Reread(bool afterChange)
        {
            if (refreshing)
            {
                if (afterChange) refreshAgain = true;
                return;
            }
            refreshing = true;
            refreshAgain = false;
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply = null;
                try { reply = bridge.Call("dashboard", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    refreshing = false;
                    if (refreshAgain)
                    {
                        refreshAgain = false;
                        Reread(false);
                        return;
                    }
                    if (Ok(reply))
                    {
                        snapshotAge.Restart();
                        ApplySnapshot(reply);
                    }
                    else MarkUnavailable();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { refreshing = false; refreshAgain = false; }
            });
        }

        // -------------------------------------------------------------- json access
        // Every read of a reply goes through these: a key the local service did not send is
        // an absent value here, never a KeyNotFoundException in a paint or a timer.
        private static object Get(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        private static bool Ok(Dictionary<string, object> reply)
        {
            return reply != null && Equals(Get(reply, "ok"), true);
        }

        private static double Number(Dictionary<string, object> map, string key)
        {
            object value = Get(map, key);
            return value is double ? (double)value : 0;
        }

        private static int Whole(object value)
        {
            return value is double ? (int)(double)value : 0;
        }

        private static string Str(Dictionary<string, object> map, string key)
        {
            return Get(map, key) as string;
        }

        private static List<object> Items(Dictionary<string, object> map, string key)
        {
            return Get(map, key) as List<object>;
        }

        private static Dictionary<string, object> Map(Dictionary<string, object> map, string key)
        {
            return Get(map, key) as Dictionary<string, object>;
        }

        private static double Now()
        {
            return (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        }

        // -------------------------------------------------------------------- words
        private string Countdown(double seconds)
        {
            int total = Math.Max(0, (int)seconds);
            int hours = total / 3600, minutes = (total % 3600) / 60, secs = total % 60;
            if (hours > 0) return string.Format(CultureInfo.InvariantCulture, "{0}:{1:00}:{2:00}", hours, minutes, secs);
            if (minutes > 0) return string.Format(CultureInfo.InvariantCulture, "{0}:{1:00}", minutes, secs);
            return S("time.seconds", "{n}s", "n", secs);
        }

        private string Duration(double seconds)
        {
            // How long something took: "9m 20s", not the "9:20" a countdown would show,
            // which reads as a time of day.
            int total = Math.Max(0, (int)Math.Round(seconds));
            if (total < 60) return S("time.seconds", "{n}s", "n", total);
            if (total < 3600)
                return S("time.minutes", "{n}m", "n", total / 60) +
                       (total % 60 == 0 ? "" : " " + S("time.seconds", "{n}s", "n", total % 60));
            return S("time.hours", "{n}h", "n", total / 3600) +
                   ((total % 3600) / 60 == 0 ? "" : " " + S("time.minutes", "{n}m", "n", (total % 3600) / 60));
        }

        private string Age(double seconds)
        {
            // How long ago, in the largest unit that is not zero. A countdown is read to
            // the second; an age of "26:04:11" is not read at all.
            int total = Math.Max(0, (int)seconds);
            if (total < 5) return S("time.just_now", "just now");
            if (total < 60) return S("time.ago", "{time} ago", "time", S("time.seconds", "{n}s", "n", total));
            if (total < 3600) return S("time.ago", "{time} ago", "time", S("time.minutes", "{n}m", "n", total / 60));
            if (total < 86400) return S("time.ago", "{time} ago", "time", S("time.hours", "{n}h", "n", total / 3600));
            return S("time.ago", "{time} ago", "time", S("time.days", "{n}d", "n", total / 86400));
        }

        private static string When(double stamp)
        {
            if (stamp <= 0) return "";
            DateTime local = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(stamp).ToLocalTime();
            return local.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
        }

        private string Ago(double stamp)
        {
            if (stamp <= 0) return S("time.never", "never");
            return Age(Now() - stamp);
        }

        private string Conversation(Dictionary<string, object> row)
        {
            string name = Str(row, "name") ?? Str(row, "project") ?? Str(row, "cwd_basename");
            string thread = Str(row, "thread_id") ?? "";
            return name ?? (thread.Length >= 8 ? thread.Substring(0, 8) : thread);
        }

        private string CodeLabel(Dictionary<string, object> row)
        {
            string code = Str(row, "code") ?? Str(row, "state") ?? "";
            var parts = new List<string>();
            parts.Add(S("code." + code, code.Replace('_', ' ')));
            var overlays = Items(row, "overlays");
            if (overlays != null)
                foreach (object overlay in overlays)
                    parts.Add(S("overlay." + overlay, Convert.ToString(overlay).Replace('_', ' ')));
            return string.Join(" · ", parts.ToArray());
        }

        private string KindLabel(Dictionary<string, object> row)
        {
            // The reason's own name, as the notifications and the popup say it.
            string category = Str(row, "category") ?? "";
            return S("reason." + category, S("field.recover_" + category, category.Replace('_', ' ')));
        }

        private static bool HasOverlay(Dictionary<string, object> row, string name)
        {
            var overlays = Items(row, "overlays");
            if (overlays != null)
                foreach (object overlay in overlays)
                    if (Convert.ToString(overlay) == name) return true;
            return false;
        }

        private static bool ThreadOn(Dictionary<string, object> row)
        {
            object value = Get(row, "thread_enabled");
            return value == null || Equals(value, true);
        }

        // ------------------------------------------------------------ snapshot use
        private void ApplySnapshot(Dictionary<string, object> reply)
        {
            snapshot = reply;
            var status = Map(reply, "status");
            // Only the pages built so far have anything to write to. A page built later is handed
            // this same snapshot when it is (PageFor), so every part below checks for its page.
            if (status != null)
            {
                ApplyStatus(status, null);
                var watcher = Map(status, "watcher");
                bool enabled = Equals(Get(status, "enabled"), true);
                shownEnabled = enabled;
                bool upgrade = Equals(Get(status, "upgrade_pending"), true);
                string recovery = enabled ? S("overview.on", "on") : S("overview.off", "paused");
                object running = Get(status, "watcher_running");
                string watcherText = running == null ? S("diag.unknown", "unknown")
                                   : !Equals(running, true) ? S("diag.not_running", "not running")
                                   : Equals(Get(watcher, "ticking"), false) ? S("diag.not_responding", "not responding")
                                   : S("diag.running", "running");
                string engine = Str(watcher, "engine_state") ?? "unknown";
                string engineText = S("engine." + engine, engine);
                double last = Number(watcher, "last_tick_at");
                if (nowRecovery != null)
                {
                    nowRecovery.Text = recovery;
                    nowWatcher.Text = watcherText;
                    nowEngine.Text = engineText;
                    nowLastCheck.Text = Ago(last);
                }
                if (diagVersion != null)
                {
                    diagVersion.Text = "v" + Convert.ToString(Get(status, "version"), CultureInfo.InvariantCulture);
                    diagWatcher.Text = watcherText;
                    diagEngine.Text = engineText;
                    diagLastCheck.Text = Ago(last);
                    diagRecovery.Text = recovery;
                    diagStartup.Text = Equals(Get(status, "startup_enabled"), true) ? S("diag.yes", "yes") : S("diag.no", "no");
                    diagUpgrade.Text = upgrade ? S("diag.upgrade_pending", "An older watcher still owns the state") : "";
                }
            }
            UpdateToggle();

            // A part that could not be read is shown as unreadable, never as empty. "Nothing
            // is waiting" over a list that could not be read is the one wrong answer this page
            // must not give - recoveries may well be waiting, and an older watcher may still
            // be sending them.
            string unreadable = UnreadableReason(status);
            var week = Map(reply, "week");
            if (weekDetected != null)
            {
                if (week != null)
                {
                    var outcomes = Map(week, "outcomes");
                    weekDetected.Text = ((int)Number(week, "interruptions_detected")).ToString(CultureInfo.CurrentCulture);
                    weekSent.Text = ((int)Number(week, "continuations_submitted")).ToString(CultureInfo.CurrentCulture);
                    weekRecovered.Text = ((int)Number(outcomes, "recovered")).ToString(CultureInfo.CurrentCulture);
                    weekSuccess.Text = Rate(week);
                }
                else
                {
                    weekDetected.Text = weekSent.Text = weekRecovered.Text = weekSuccess.Text = "-";
                }
            }
            if (pendingList != null)
            {
                if (Unreadable(reply, "pending")) ShowUnreadableList(pendingList, pendingEmpty, unreadable);
                else
                {
                    FillList(pendingList, Items(reply, "pending"), true);
                    pendingEmpty.Text = S("pending.empty", "Nothing is waiting");
                    pendingEmpty.Visible = pendingList.Items.Count == 0;
                }
            }
            bool historyUnreadable = Unreadable(reply, "history");
            if (historyList != null)
            {
                if (historyUnreadable) ShowUnreadableList(historyList, historyEmpty, unreadable);
                else
                {
                    FillList(historyList, Items(reply, "history"), false);
                    historyEmpty.Text = S("history.empty", "No recoveries yet");
                    historyEmpty.Visible = historyList.Items.Count == 0;
                }
            }
            if (recentGrid != null)
            {
                if (historyUnreadable) ClearRecent(unreadable);
                else FillRecent(Items(reply, "history"));
            }
            // A Retry now note belongs to one record; once that record has left Pending -
            // sent, finished or cancelled - the note no longer describes anything on screen.
            if (pendingNoteFor != null && pendingNoteFor != BulkNote && pendingList != null && !Contains(pendingList, pendingNoteFor))
                pendingNoteFor = null;
            ShowPendingNote();
            ShowExplain();
            UpdateCountdowns();
            UpdatePendingButtons();
            UpdateHistoryButtons();
        }

        /// Whether one part of a snapshot came back as an error rather than as data.
        ///
        /// Each part of the Overview is read on its own and fails on its own, which is the
        /// point: a history query that cannot run should not cost the pending list. The
        /// distinction that matters is between "there is nothing" and "this could not be
        /// read", because the first is an answer and the second is not - and showing the
        /// first when the second is true tells somebody nothing is waiting while recoveries
        /// wait, which is the one wrong thing this page can say.
        internal static bool Unreadable(Dictionary<string, object> reply, string part)
        {
            return reply != null && reply.ContainsKey(part + "_error");
        }

        private static void ShowUnreadable(ListView list, Label empty, string reason)
        {
            list.Items.Clear();
            empty.Text = reason;
            empty.Visible = true;
        }

        /// The same, and the columns fitted again: with no rows there are no cells to keep room for, and the columns
        /// share the list's width by their headings (FitColumns).
        private void ShowUnreadableList(ListView list, Label empty, string reason)
        {
            ShowUnreadable(list, empty, reason);
            MeasureCells(list);
            if (list == pendingList) FollowResumeSwitches();
        }

        private void MarkUnavailable()
        {
            // The same unavailable state the header shows when the status cannot be read,
            // and nothing drawn from data that is no longer being read: no countdown, and no
            // list whose rows an action could be taken on. Keeping the last good snapshot on
            // screen said "watching, recovery on" for as long as the reads kept failing.
            snapshot = null;
            shownEnabled = null;
            stateDot.State = "idle";
            TellTaskbar(null, null, 0);
            headline.Text = S("status.unavailable", "Status unavailable");
            detail.Text = S("status.unavailable_detail", "Settings can still be changed and saved");
            header.Invalidate(true);
            // Only the pages built so far have labels; a page built later starts from its own
            // placeholders, which say no more than these do.
            string unknown = S("diag.unknown", "unknown");
            foreach (Label label in new[] { nowRecovery, nowWatcher, nowEngine, nowLastCheck,
                                            diagWatcher, diagEngine, diagLastCheck, diagRecovery })
                if (label != null) label.Text = unknown;
            string unreadable = S("pending.unavailable", "This cannot be read right now");
            if (pendingList != null) ShowUnreadableList(pendingList, pendingEmpty, unreadable);
            if (historyList != null) ShowUnreadableList(historyList, historyEmpty, unreadable);
            if (recentGrid != null) ClearRecent(unreadable);
            if (waitingLine != null)
            {
                waitingLine.Text = unreadable;
                nextLine.Text = "";
                runningLine.Text = "";
            }
            // The week's figures and the Statistics page are read the same way and have
            // failed the same way; left as they were, they would be the last good answer
            // under a header that says the state cannot be read.
            if (weekDetected != null) weekDetected.Text = weekSent.Text = weekRecovered.Text = weekSuccess.Text = "-";
            MarkStatisticsUnavailable();
            pendingNoteFor = null;
            if (pendingNote != null) SetNote(pendingNote, "");
            ShowExplain();
            UpdatePendingButtons();
            UpdateHistoryButtons();
            UpdateToggle();
        }

        /// Why a part of a snapshot says nothing: an older watcher still owns the state, or the
        /// part could not be read.
        private string UnreadableReason(Dictionary<string, object> status)
        {
            return Equals(Get(status, "upgrade_pending"), true)
                 ? S("diag.upgrade_pending", "An older watcher still owns the state")
                 : S("pending.unavailable", "This cannot be read right now");
        }

        private string Rate(Dictionary<string, object> stats)
        {
            object rate = Get(stats, "success_rate");
            if (rate is double)
                return ((int)Math.Round((double)rate * 100)).ToString(CultureInfo.CurrentCulture) + "%";
            return S("overview.not_enough", "not enough data yet");
        }

        private static bool Contains(ListView list, string interruptionId)
        {
            foreach (ListViewItem item in list.Items)
                if (Str(item.Tag as Dictionary<string, object>, "interruption_id") == interruptionId) return true;
            return false;
        }

        // The cells of one row. Null where a cell is written elsewhere: the countdown column
        // is kept by the clock.
        private string[] Cells(Dictionary<string, object> row, bool pending)
        {
            return pending
                ? new[] { Conversation(row), CodeLabel(row), KindLabel(row), null,
                          ((int)Number(row, "recovery_attempts")).ToString(CultureInfo.CurrentCulture), "" }
                : new[] { Conversation(row), CodeLabel(row), KindLabel(row),
                          When(Number(row, "detected_at")), When(Number(row, "outcome_at")) };
        }

        private void FillList(ListView list, List<object> rows, bool pending)
        {
            var fresh = new List<Dictionary<string, object>>();
            if (rows != null)
                foreach (object entry in rows)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row != null) fresh.Add(row);
                }

            filling = true;
            try
            {
                // The same records in the same order: only the cells that changed are
                // rewritten, so the scroll position, the focus and the selection stay where
                // the person left them. Rebuilding every five seconds sent a long history back
                // to the top and a keyboard user back to its first row.
                bool same = list.Items.Count == fresh.Count;
                for (int i = 0; same && i < fresh.Count; i++)
                    same = Str(list.Items[i].Tag as Dictionary<string, object>, "interruption_id") ==
                           Str(fresh[i], "interruption_id");
                if (same)
                {
                    for (int i = 0; i < fresh.Count; i++)
                    {
                        ListViewItem item = list.Items[i];
                        item.Tag = fresh[i];
                        string[] cells = Cells(fresh[i], pending);
                        for (int c = 0; c < cells.Length; c++)
                            if (cells[c] != null && item.SubItems[c].Text != cells[c]) item.SubItems[c].Text = cells[c];
                    }
                    // A row is drawn from its record as well as its text - the state chip's
                    // colour, the Auto-resume box - so a record that changed repaints.
                    list.Invalidate();
                }
                else
                {
                    var chosen = Selected(list);
                    string selectedId = chosen == null ? null : Str(chosen, "interruption_id");
                    string focusedId = list.FocusedItem == null ? null
                                     : Str(list.FocusedItem.Tag as Dictionary<string, object>, "interruption_id");
                    string topId = list.TopItem == null ? null
                                 : Str(list.TopItem.Tag as Dictionary<string, object>, "interruption_id");
                    ListViewItem top = null;
                    list.BeginUpdate();
                    list.Items.Clear();
                    foreach (var row in fresh)
                    {
                        string[] cells = Cells(row, pending);
                        var item = new ListViewItem(cells[0]);
                        for (int c = 1; c < cells.Length; c++) item.SubItems.Add(cells[c] ?? "");
                        item.Tag = row;
                        list.Items.Add(item);
                        string id = Str(row, "interruption_id");
                        // Kept only while that record is still here. When the chosen record has
                        // left the list nothing is selected: an action must never move onto a
                        // conversation the person did not choose.
                        if (id != null && id == selectedId) item.Selected = true;
                        if (id != null && id == focusedId) item.Focused = true;
                        if (id != null && id == topId) top = item;
                    }
                    list.EndUpdate();
                    if (top != null)
                    {
                        try { list.TopItem = top; }
                        catch (Exception) { }
                    }
                }
                Preselect(list);
                MeasureCells(list);
                if (list == pendingList) FollowResumeSwitches();
            }
            finally
            {
                filling = false;
            }
        }

        private void Preselect(ListView list)
        {
            // The first time a list has rows its first row starts selected, so the actions
            // under it say what they would do instead of sitting greyed out. Only that once:
            // after that the selection is the person's, including having none. Selecting sends
            // nothing, and every action still asks, naming the conversation it acts on.
            if (preselected.ContainsKey(list) || list.Items.Count == 0) return;
            preselected[list] = true;
            if (list.SelectedItems.Count == 0)
            {
                list.Items[0].Selected = true;
                list.Items[0].Focused = true;
            }
        }

        private void UpdateCountdowns()
        {
            if (snapshot == null) return;
            double now = Now();
            var status = Map(snapshot, "status");
            bool unreadable = snapshot.ContainsKey("pending_error");
            var pending = unreadable ? null : Items(snapshot, "pending");
            // The one place a snapshot decides the header dot (ApplyStatus leaves it alone once
            // there is one), and every second, so a task that has just come due shows the watcher
            // checking. Before an unreadable list returns, which leaves Activity the status alone.
            stateDot.State = Activity(status, pending, now);
            TellTaskbar(status, pending, now);
            if (unreadable)
            {
                if (waitingLine != null)
                {
                    waitingLine.Text = UnreadableReason(status);
                    nextLine.Text = "";
                    runningLine.Text = "";
                }
                return;
            }
            int waiting = 0, running = 0;
            double next = 0;
            if (pending != null)
            {
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row == null) continue;
                    double eligible = Number(row, "eligible_at");
                    if (eligible > 0)
                    {
                        waiting++;
                        if (next == 0 || eligible < next) next = eligible;
                    }
                    else running++;
                }
            }
            bool enabled = Equals(Get(status, "enabled"), true);
            if (waitingLine != null)
            {
                waitingLine.Text = waiting == 0 && running == 0 ? S("overview.none_waiting", "Nothing is waiting to be recovered")
                                 : S("overview.waiting_count", "{n} waiting", "n", waiting);
                nextLine.Text = !(waiting > 0 && enabled && next > 0) ? ""
                    : next <= now ? S("overview.due", "Due to be checked now")
                    : S("overview.next", "Next check in {time}", "time", Countdown(next - now));
                runningLine.Text = running > 0 ? S("overview.running_count", "{n} running in Codex", "n", running) : "";
            }
            if (pendingList == null) return;
            foreach (ListViewItem item in pendingList.Items)
            {
                string text = CountdownText(item.Tag as Dictionary<string, object>, now);
                if (item.SubItems[CountdownColumn].Text != text) item.SubItems[CountdownColumn].Text = text;
            }
        }

        /// What a waiting row's Next check says at `now`: how long until it is checked, that it is due, or nothing for a
        /// row that is not waiting.
        private string CountdownText(Dictionary<string, object> row, double now)
        {
            double eligible = Number(row, "eligible_at");
            return eligible <= 0 ? "" : eligible <= now ? S("pending.due", "due now") : Countdown(eligible - now);
        }

        private static Dictionary<string, object> Selected(ListView list)
        {
            if (list == null || list.SelectedItems.Count == 0) return null;
            return list.SelectedItems[0].Tag as Dictionary<string, object>;
        }

        // The note says what the last Retry now did, and it says it without naming the
        // conversation - so it is shown only while that record is the chosen one. The
        // selection can move between the click and the reply, and a sentence about one
        // conversation read under another is a sentence about the other one.
        private void ShowPendingNote()
        {
            if (pendingNote == null) return;
            var chosen = Selected(pendingList);
            bool mine = pendingNoteFor == BulkNote || (pendingNoteFor != null && chosen != null &&
                        Str(chosen, "interruption_id") == pendingNoteFor);
            SetNote(pendingNote, mine ? pendingNoteText : "");
        }

        /// Whether Retry now is worth offering for this record.
        ///
        /// Lifted out of the button handler so something can drive it: this is a decision
        /// about a record, and a decision that only exists inside a method that reads a
        /// ListView control is a decision nothing can check. It is not the authority - the
        /// engine re-evaluates everything when the request arrives, and refuses there too -
        /// but a button that is certain to be refused is not an action, and one that is
        /// missing where it would have worked is a person concluding the product is stuck.
        internal static bool CanRetryNow(Dictionary<string, object> row, bool idle, double now)
        {
            if (row == null || !idle) return false;
            string code = Str(row, "code");
            bool waiting = code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" ||
                           code == "scheduled" || code == "failed_retryable";
            if (!waiting) return false;
            if (Equals(Get(row, "cancel_requested"), true)) return false;
            // Retry now brings the check forward. It never moves past a usage reset that is
            // still ahead, and never past a pause or a conversation that is switched off; where
            // it could do none of that it is not offered. A reset that has passed, or one that
            // is unknown, is exactly where it helps.
            if (Number(row, "reset_at") > now) return false;
            if (HasOverlay(row, "paused") || HasOverlay(row, "thread_disabled")) return false;
            return true;
        }

        /// Whether giving this record its attempts back could succeed. The store allows it a
        /// limited number of times; past that the button would always be refused.
        internal static bool CanGiveAttemptsBack(Dictionary<string, object> row, bool idle)
        {
            if (row == null || !idle) return false;
            if (Str(row, "code") != "exhausted") return false;
            if (Equals(Get(row, "cancel_requested"), true)) return false;
            return Number(row, "budget_resets_left") > 0;
        }

        private void UpdatePendingButtons()
        {
            if (pendingList == null) return;
            var row = Selected(pendingList);
            bool idle = busy == 0;
            bool cancelled = Equals(Get(row, "cancel_requested"), true);
            retryButton.Enabled = CanRetryNow(row, idle, Now());
            cancelButton.Enabled = idle && row != null && !cancelled;
            timelineButton.Enabled = idle && row != null;
            threadButton.Enabled = idle && row != null;
            string text = ThreadOn(row) ? S("action.thread_off", "Turn off for this conversation")
                                        : S("action.thread_on", "Turn on for this conversation");
            if (threadButton.Text != text) threadButton.Text = text;
            if (cancelAllButton != null) cancelAllButton.Enabled = idle && pendingList.Items.Count > 0;
        }

        private void UpdateHistoryButtons()
        {
            if (historyList == null) return;
            var row = Selected(historyList);
            bool idle = busy == 0;
            historyTimeline.Enabled = idle && row != null;
            bool exhausted = Str(row, "code") == "exhausted" && !Equals(Get(row, "cancel_requested"), true);
            bool resetsLeft = Number(row, "budget_resets_left") > 0;
            historyReset.Enabled = CanGiveAttemptsBack(row, idle);
            SetNote(historyNote, exhausted && !resetsLeft
                ? S("history.reset_limit", "Its attempts were already given back as many times as allowed; continue this task in Codex yourself.")
                : "");
            bool off = row != null && !ThreadOn(row);
            // Set every time. While History is not the page on screen `Visible` answers false
            // whatever the button was told, and a write skipped for that left it offered beside a
            // row whose conversation is on.
            historyThread.Visible = off;
            historyThread.Enabled = idle && off;
            historyClear.Enabled = idle && historyList.Items.Count > 0;
        }

        private void UpdateToggle()
        {
            if (toggleButton == null) return;
            toggleButton.Enabled = busy == 0;
            string text = shownEnabled == false ? S("action.resume", "Resume recovery") : S("action.pause", "Pause recovery");
            if (toggleButton.Text != text) toggleButton.Text = text;
        }

        // ---------------------------------------------------------------- actions
        private void SetBusy(bool on)
        {
            busy = Math.Max(0, busy + (on ? 1 : -1));
            // While an action is in flight every other action waits its turn, visibly. A second
            // click on a button whose first click has not been answered yet is how a person
            // ends up acting twice, or on the row that happened to be selected by then.
            UseWaitCursor = busy > 0;
            UpdatePendingButtons();
            UpdateHistoryButtons();
            UpdateToggle();
            if (exportButton != null) exportButton.Enabled = busy == 0;
            if (repairButton != null) repairButton.Enabled = busy == 0;
            if (updateButton != null) updateButton.Enabled = busy == 0;
            if (stopButton != null) stopButton.Enabled = busy == 0;
            if (compatButton != null) compatButton.Enabled = busy == 0;
            if (saveButton != null) saveButton.Enabled = busy == 0;
            if (restoreButton != null) restoreButton.Enabled = busy == 0;
        }

        /// Runs one bridge command on a worker and hands its reply back on this thread.
        /// Confirmation and file dialogs stay on this thread, before the call starts.
        private void CallAsync(string command, string argument, Action<Dictionary<string, object>> done)
        {
            SetBusy(true);
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call(command, argument); }
                catch (Exception error) { reply = Failure(error); }
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    done(reply);
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        private void Send(string command, string argument)
        {
            CallAsync(command, argument, delegate(Dictionary<string, object> reply)
            {
                Report(reply);
                RefreshAfterChange();
            });
        }

        private bool Confirm(string question, string affirm)
        {
            return question == null || Say(question, affirm);
        }

        /// A notice: one sentence and one button that closes it.
        private void Tell(string text)
        {
            Say(text, null);
        }

        // ---------------------------------------------------------------- the window's own message box
        /// What Windows' message box was, in the material the rest of this window is made of.
        ///
        /// It was the last native piece here. Windows' box is a square grey sheet with a system font and
        /// a title bar that ignores the theme - in dark it is a white card in the middle of a dark window
        /// - and its buttons say "Yes" and "No", which name nothing. This one says what will happen: the
        /// words of the button that was pressed to ask. The panel settled that pattern first (confirmOff:
        /// the action's own label beside `action.cancel`), so both halves of the product ask the same way.
        ///
        /// No new words were needed for it. A notice closes with `action.close`; a question affirms with
        /// the label its caller already has and dismisses with `action.cancel` - or with `action.close`
        /// where those two would be the same word, as they are for the Pending page's own Cancel.
        private bool Say(string text, string affirm)
        {
            using (var dialog = new Form())
            {
                dialog.Text = "Codex Auto Resume";
                dialog.Font = Font;
                dialog.BackColor = Canvas;
                dialog.ForeColor = Ink;
                // In the window's theme, title bar and all.
                Soft.TitleBar(dialog);
                dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
                dialog.StartPosition = FormStartPosition.CenterParent;
                dialog.MinimizeBox = false;
                dialog.MaximizeBox = false;
                dialog.ShowInTaskbar = false;
                dialog.ShowIcon = false;

                // A measure a sentence is read at, not a box stretched to whatever it holds: the words
                // wrap inside it, and a short one still gets a dialog wide enough to look deliberate.
                int pad = Px(16);
                Size measured = TextRenderer.MeasureText(text ?? "", Font, new Size(Px(420), 0),
                                                         TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix);
                int width = Math.Max(Px(300), measured.Width);
                // And a height a dialog can be. A refusal carries the local service's own sentence
                // under the translated one, and that sentence is whatever was raised - a path, a stack,
                // a page of it. Past this the words go in a well and scroll there, on the window's own
                // bar, rather than making a dialog taller than the screen it opens on.
                int tallest = Px(240);
                bool scrolls = measured.Height > tallest;
                int room = scrolls ? tallest : measured.Height;

                var padding = new Panel();
                padding.BackColor = Canvas;
                padding.Dock = DockStyle.Fill;
                padding.Padding = Pad(16, 16, 16, 0);
                if (scrolls)
                {
                    var well = new SoftTextArea();
                    well.Dock = DockStyle.Fill;
                    well.Font = Font;
                    well.Box.Font = Font;
                    well.Box.ReadOnly = true;
                    well.Box.Text = text ?? "";
                    // Read from the top, unselected. A text box takes the focus a dialog hands its first
                    // control and answers it by selecting everything it holds, which reads as a page of
                    // highlighted text nobody asked to highlight - and leaves the well wearing the focus
                    // ring while the button that closes it has none.
                    dialog.Shown += delegate { well.Box.Select(0, 0); };
                    well.Box.AccessibleName = "Codex Auto Resume";
                    padding.Controls.Add(well);
                }
                else
                {
                    var words = new Label();
                    words.Text = text ?? "";
                    words.ForeColor = Ink;
                    words.BackColor = Canvas;
                    words.UseMnemonic = false;     // an ampersand in a conversation's name is a letter
                    words.AutoSize = false;
                    words.Dock = DockStyle.Fill;
                    padding.Controls.Add(words);
                }
                dialog.Controls.Add(padding);

                bool said = false;
                FlowLayoutPanel buttons = ButtonRow();
                buttons.FlowDirection = FlowDirection.RightToLeft;
                // A right-to-left flow lays its first control out from its own width less both sides
                // of its padding, so what stands between the rightmost button and the edge is the two
                // added together. All of it is put on the right, where it is the gap, and the row is
                // then inset by the same 16 as the sentence above it.
                buttons.Padding = Pad(0, 12, 16, 16);
                Button accept, dismiss;
                if (affirm == null)
                {
                    accept = dismiss = MakeButton(S("action.close", "Close"), true, delegate { dialog.Close(); });
                    buttons.Controls.Add(accept);
                }
                else
                {
                    accept = MakeButton(affirm, true, delegate { said = true; dialog.Close(); });
                    string away = S("action.cancel", "Cancel");
                    if (string.Equals(away, affirm, StringComparison.CurrentCultureIgnoreCase))
                        away = S("action.close", "Close");
                    dismiss = MakeButton(away, false, delegate { dialog.Close(); });
                    // Right to left, so the button that does the thing is the rightmost.
                    buttons.Controls.Add(accept);
                    buttons.Controls.Add(dismiss);
                }
                dialog.Controls.Add(buttons);
                dialog.AcceptButton = accept;
                dialog.CancelButton = dismiss;     // which is also what Escape presses
                // The keyboard starts on the button that acts, not on the words: a dialog hands the
                // focus to its first control, and where the words are in a well that is the well.
                dialog.ActiveControl = accept;

                dialog.ClientSize = new Size(width + 2 * pad, room + pad + buttons.PreferredSize.Height);
                dialog.ShowDialog(this);
                return said;
            }
        }

        // A confirmation that names the conversation it acts on. The row is the one read at
        // the click, and so is the id the action is sent with: what the person agrees to and
        // what is done are the same record, whatever a refresh does to the list meanwhile.
        private string Named(string key, string fallback, Dictionary<string, object> row)
        {
            return S(key, fallback, "name", Conversation(row));
        }

        private void Report(Dictionary<string, object> reply)
        {
            if (Ok(reply)) return;
            // Every refusal carries a code from a closed set, and the catalog has that code's
            // sentence in the language this window is speaking. The English sentence beside it
            // comes from the local service and stays underneath, because it is what a bug
            // report needs - except where it would only repeat the line above it.
            string code = Str(reply, "error_code");
            string english = Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture);
            // The generic code is the exception: it is what a refusal carries when the
            // sentence beside it is the informative half - a setting naming the bounds it
            // refused, say - so translating it would replace the only useful words with
            // "the request could not be completed".
            string said = string.IsNullOrEmpty(code) || code == "request_failed"
                        ? null : S("error." + code, null);
            string lead = said ?? S("action.failed", "That could not be done.");
            Tell(lead + (said != null || string.IsNullOrEmpty(english)
                         ? "" : Environment.NewLine + Environment.NewLine + english));
        }

        private static Dictionary<string, object> Failure(Exception error)
        {
            var reply = new Dictionary<string, object>();
            reply["ok"] = false;
            reply["error"] = error.Message;
            return reply;
        }

        private static string IdArgument(Dictionary<string, object> row)
        {
            return "{\"interruption_id\":" + Json.Escape(Str(row, "interruption_id")) + "}";
        }

        private void RetryNow()
        {
            var row = Selected(pendingList);
            if (row == null) return;
            string key = Str(row, "interruption_id");
            CallAsync("retry-now", IdArgument(row), delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    RefreshAfterChange();
                    return;
                }
                var result = Map(reply, "result");
                pendingNoteFor = key;
                pendingNoteText = Number(result, "eligible_at") > Now() + 1
                    ? S("retry.later", "The usage reset is later; the watcher checks then.")
                    : Equals(Get(result, "woke"), true)
                    ? S("retry.checking", "Checking now. Every safety check still applies.")
                    : S("retry.next_poll", "The watcher checks at its next poll. Every safety check still applies.");
                ShowPendingNote();
                RefreshAfterChange();
            });
        }

        private void CancelSelected()
        {
            var row = Selected(pendingList);
            if (row == null) return;
            if (!Confirm(Named("confirm.cancel",
                               "Stop recovering \"{name}\"? A continuation already running in Codex is not stopped.", row),
                         S("action.cancel", "Cancel")))
                return;
            Send("cancel", IdArgument(row));
        }

        private void ResetSelected()
        {
            var row = Selected(historyList);
            if (row == null) return;
            if (!Confirm(Named("confirm.reset",
                               "Give \"{name}\" its attempts back? It waits and is checked again; nothing is sent now.", row),
                         S("action.reset_budget", "Give attempts back")))
                return;
            CallAsync("reset-budget", IdArgument(row), delegate(Dictionary<string, object> reply)
            {
                Report(reply);
                string notice = BudgetResetNotice(reply,
                    S("history.reset_done", "Attempts restored. Nothing was sent."),
                    S("history.reset_thread_off", "Automatic recovery is off for this conversation; switch it on before recovery can run."));
                if (notice != null)
                    Tell(notice);
                RefreshAfterChange();
            });
        }

        internal static string BudgetResetNotice(Dictionary<string, object> reply, string restored, string threadOff)
        {
            if (!Ok(reply)) return null;
            var result = Map(reply, "result");
            if (result == null) return null;
            return restored + (string.IsNullOrEmpty(Str(result, "note")) ? ""
                              : Environment.NewLine + Environment.NewLine + threadOff);
        }

        private void ToggleThread(ListView list)
        {
            var row = Selected(list);
            if (row == null) return;
            bool on = ThreadOn(row);
            if (!Confirm(on ? Named("confirm.thread_off",
                                    "Turn automatic recovery off for \"{name}\"? Its waiting recoveries are cancelled.", row)
                            : Named("confirm.thread_on",
                                    "Turn automatic recovery back on for \"{name}\"? Nothing is sent now; every check still applies.", row),
                         on ? S("action.thread_off", "Turn off for this conversation")
                            : S("action.thread_on", "Turn on for this conversation")))
                return;
            string thread = Json.Escape(Str(row, "thread_id"));
            if (on) Send("cancel-thread", "{\"thread_id\":" + thread + "}");
            else Send("thread-enabled", "{\"thread_id\":" + thread + ",\"enabled\":true}");
        }

        /// The Auto-resume box on one row: automatic recovery on or off for that exact task.
        private void ToggleAutoResume(Dictionary<string, object> row)
        {
            if (row == null || busy > 0) return;
            string id = Str(row, "interruption_id"), thread = Str(row, "thread_id");
            if (id == null || thread == null) return;
            bool enable = !ThreadOn(row);
            // Off only ever reduces what runs, so it happens at once. On asks first, naming the
            // conversation, exactly as the button beside the list does.
            if (enable && !Confirm(Named("confirm.thread_on",
                                         "Turn automatic recovery back on for \"{name}\"? Nothing is sent now; every check still applies.", row),
                                   S("action.thread_on", "Turn on for this conversation")))
                return;
            Send("interruption-recovery", "{\"interruption_id\":" + Json.Escape(id) + ",\"thread_id\":" +
                 Json.Escape(thread) + ",\"enabled\":" + (enable ? "true" : "false") + "}");
        }

        private void CancelAll()
        {
            if (busy > 0 || pendingList.Items.Count == 0) return;
            if (!Confirm(S("confirm.cancel_all",
                           "Stop every pending recovery? Anything already handed to Codex is withdrawn only if it is still queued."),
                         S("action.cancel_all", "Cancel all")))
                return;
            CallAsync("cancel-all", null, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    RefreshAfterChange();
                    return;
                }
                var result = Map(reply, "result");
                pendingNoteFor = BulkNote;
                pendingNoteText = S("result.cancel_all", "Cancelled: {n}", "n", (int)Number(result, "cancelled"));
                ShowPendingNote();
                RefreshAfterChange();
            });
        }

        /// What the watcher is doing, as the header's status light shows it.
        ///
        /// Pure, so the rule can be checked without a window. A watcher that is not running, or
        /// not known to be, is a light that is off - grey, as it was until v0.6.3, with the
        /// headline beside it saying what is wrong. One that runs but is not responding, or that
        /// an unfinished upgrade still shares the state with, needs a person; a pause is still; a
        /// continuation in Codex is recovering; a task that has come due is being checked; anything
        /// else waiting is waiting; and a running watcher with nothing to do is monitoring. With no
        /// pending list - it could not be read - the status's own count says whether anything is
        /// waiting, so a list that cannot be read is never shown as nothing to do.
        internal static string Activity(Dictionary<string, object> status, List<object> pending, double now)
        {
            if (status == null) return "idle";
            if (!Equals(Get(status, "watcher_running"), true)) return "idle";
            var watcher = Map(status, "watcher");
            if (Equals(Get(status, "upgrade_pending"), true) || Equals(Get(watcher, "ticking"), false))
                return "attention";
            if (!Equals(Get(status, "enabled"), true)) return "paused";
            if (pending == null) return Number(status, "pending") > 0 ? "waiting" : "monitoring";
            bool waiting = false, due = false, recovering = false;
            foreach (object entry in pending)
            {
                var row = entry as Dictionary<string, object>;
                if (row == null) continue;
                string code = Str(row, "code") ?? "";
                if (code == "submission_claimed" || code == "submitted" || code == "turn_running" ||
                    code == "turn_finishing")
                    recovering = true;
                double eligible = Number(row, "eligible_at");
                if (eligible > 0)
                {
                    waiting = true;
                    if (eligible <= now) due = true;
                }
            }
            if (recovering) return "recovering";
            if (due) return "checking";
            return waiting ? "waiting" : "monitoring";
        }

        /// What the notification-area icon shows for the watcher the window read, as the status-light word its state
        /// is made from (v0.6.5): the taskbar button's, which TaskbarMark maps as the icon does (Brand.Mark.IconState,
        /// tray.ICON_FOR_LIGHT).
        ///
        /// The icon's own rule, not the header light's (Activity), which parts from it for a record being withdrawn,
        /// an incompatible engine and a list that cannot be read. tray.icon_state is ICON_FOR_LIGHT of
        /// tray_popup.snapshot_activity: the tick's snapshot of the store (tray.snapshot_from) - a pause, then any
        /// record sent or being followed, then any waiting - with, while its popup is open, the popup's word that a
        /// person must act (tray_popup.activity). The window reads what that popup reads, get_status and list_pending,
        /// and reads it now, so this is the icon with its popup open. With no list the status's counts of the store's
        /// records by public code say the same (status.codes). Where no icon of this version can be showing, it is the
        /// header light's word: grey with no watcher running or none known to be, and needing a person while an older
        /// watcher still owns the state. Pure, so tests/test_gui_v065_taskbar.py holds it to tray.py's own code.
        internal static string TrayActivity(Dictionary<string, object> status, List<object> pending, double now)
        {
            if (status == null || !Equals(Get(status, "watcher_running"), true)) return "idle";
            if (Equals(Get(status, "upgrade_pending"), true)) return "attention";
            var watcher = Map(status, "watcher");
            if (Equals(Get(watcher, "ticking"), false) || Str(watcher, "engine_state") == "incompatible")
                return "attention";
            if (pending != null)
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    // tray_popup.ATTENTION_OVERLAYS: a record held for one of the above, or for a watcher not running.
                    if (row != null && (HasOverlay(row, "compatibility_blocked") || HasOverlay(row, "engine_unavailable") ||
                                        HasOverlay(row, "watcher_not_ticking")))
                        return "attention";
                }
            object enabled;
            if (status.TryGetValue("enabled", out enabled) && (enabled == null || Equals(enabled, false))) return "paused";
            bool waiting = false, due = false, running = false;
            if (pending != null)
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row == null) continue;
                    if (!WaitingCode(Str(row, "code")))
                    {
                        running = true;
                        continue;
                    }
                    waiting = true;
                    double eligible = Number(row, "eligible_at");
                    if (eligible > 0 && eligible <= now) due = true;
                }
            else
            {
                var codes = Map(status, "codes");
                if (codes != null)
                    foreach (KeyValuePair<string, object> code in codes)
                    {
                        if (!(code.Value is double) || (double)code.Value <= 0) continue;
                        if (WaitingCode(code.Key)) waiting = true;
                        else running = true;
                    }
            }
            if (running) return "recovering";
            if (due) return "checking";
            return waiting ? "waiting" : "monitoring";
        }

        /// A pending record's public code that means it waits (machine.WAITING_CODES): every other pending record has
        /// been sent into Codex, or is being followed or taken back out of it.
        private static bool WaitingCode(string code)
        {
            return code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" || code == "scheduled" ||
                   code == "failed_retryable";
        }

        /// The taskbar button told what the window read (TrayActivity), wherever the header light is told.
        private void TellTaskbar(Dictionary<string, object> status, List<object> pending, double now)
        {
            if (taskbar != null) taskbar.Follow(TrayActivity(status, pending, now));
        }

        /// The selected task's safety checks, as the watcher last recorded them.
        private void ShowExplain()
        {
            if (explainList == null) return;
            var row = Selected(pendingList);
            var rows = new List<string[]>();
            if (row == null)
            {
                explainAsOf.Text = "";
                explainList.SetRows(rows, S("explain.none_selected", "Select a task to see why it is waiting."));
                return;
            }
            var gates = Map(row, "gates");
            double at = Number(row, "gates_at");
            // Said once: either when the checks were last run, or - in the list's own place -
            // that they have not been run yet.
            explainAsOf.Text = gates == null || at <= 0 ? "" : S("explain.as_of", "Last checked {time}", "time", Ago(at));
            if (gates != null)
                foreach (string name in GateOrder)
                {
                    var result = Items(gates, name);
                    string code = result != null && result.Count > 0 ? Convert.ToString(result[0], CultureInfo.InvariantCulture) : "UNKNOWN";
                    string word = code == "PASS" ? S("gate.result.pass", "OK")
                                : code == "WAIT" ? S("gate.result.wait", "Waiting")
                                : code == "BLOCK" ? S("gate.result.block", "Blocked")
                                : S("gate.result.unknown", "Unknown");
                    rows.Add(new[] { S("gate." + name, name.Replace('_', ' ')), word, code });
                }
            explainList.SetRows(rows, S("explain.not_checked", "Not checked yet"));
        }

        private void TogglePause()
        {
            if (shownEnabled.HasValue)
            {
                SetEnabled(!shownEnabled.Value);
                return;
            }
            // No status has been read yet, or the last read failed, and the button then
            // shows "Pause recovery" only because it has to show something. So the state is
            // read first rather than guessed: pressing "Pause recovery" must never turn
            // recovery on, and if it is already paused there is nothing to do.
            CallAsync("status", null, delegate(Dictionary<string, object> reply)
            {
                var status = Ok(reply) ? Map(reply, "status") : null;
                if (status == null)
                {
                    Tell(S("status.unavailable", "Status unavailable"));
                    return;
                }
                bool enabled = Equals(Get(status, "enabled"), true);
                shownEnabled = enabled;
                UpdateToggle();
                if (enabled) SetEnabled(false);
            });
        }

        private void SetEnabled(bool enable)
        {
            // Pausing never asks: it only reduces what happens. Turning recovery back on does.
            if (enable && !Confirm(S("confirm.resume", "Turn automatic recovery back on?"),
                                   S("action.resume", "Resume recovery"))) return;
            Send("enabled", enable ? "{\"enabled\":true}" : "{\"enabled\":false}");
        }

        private void ClearHistory()
        {
            if (!Confirm(S("confirm.clear", "Hide finished recoveries from the history?"),
                         S("action.clear_history", "Clear history"))) return;
            Send("clear-history", null);
        }

        // A statistics read for its own sake: the clock, a page switch, F5.
        private void LoadStatistics()
        {
            LoadStatistics(false);
        }

        // A read after the period changed. An answer already in flight is for the period
        // before it, so it is thrown away and a new read made.
        private void LoadStatistics(bool afterChange)
        {
            // One read at a time. Without this the clock queues another every five
            // seconds whether or not the last one has answered, and a bridge that is
            // slow - every call a fresh interpreter once the long-lived one is given up -
            // leaves a growing pile of them waiting on its lock.
            if (period == null) return;
            if (loadingStats)
            {
                if (afterChange) { statsAgain = true; statsToken++; }
                return;
            }
            loadingStats = true;
            statsAgain = false;
            var choice = period.SelectedItem as Choice;
            string argument = choice == null || choice.Value.Length == 0 ? "{}" : "{\"days\":" + choice.Value + "}";
            int mine = ++statsToken;
            // Not through CallAsync: reading numbers is not an action, and must not grey out
            // every button of the window each time the page refreshes.
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call("statistics", argument); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    loadingStats = false;
                    if (statsAgain)
                    {
                        statsAgain = false;
                        LoadStatistics(false);
                        return;
                    }
                    if (mine != statsToken) return;
                    if (Ok(reply)) ApplyStatistics(Map(reply, "result"));
                    else MarkStatisticsUnavailable();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { loadingStats = false; statsAgain = false; }
            });
        }

        private void MarkStatisticsUnavailable()
        {
            // The same rule as the Overview: a number that could not be read is shown as
            // unknown, never as the answer to a different question - the period before
            // this one, or a week whose figures are no longer being read.
            if (chart == null) return;
            foreach (Label label in new[] { statsDetected, statsSent, statsRecovered, statsSuccess,
                                            statsWait, statsRecover, statsRetry, statsKinds })
                label.Text = "-";
            chart.Bars.Clear();
            chart.EmptyText = S("pending.unavailable", "This cannot be read right now");
            chart.Font = Font;
            chart.Height = chart.RowHeight() + Px(4);
            chart.Describe();
            chart.Invalidate();
        }

        private void ApplyStatistics(Dictionary<string, object> stats)
        {
            var outcomes = Map(stats, "outcomes");
            statsDetected.Text = ((int)Number(stats, "interruptions_detected")).ToString(CultureInfo.CurrentCulture);
            statsSent.Text = ((int)Number(stats, "continuations_submitted")).ToString(CultureInfo.CurrentCulture);
            statsRecovered.Text = ((int)Number(outcomes, "recovered")).ToString(CultureInfo.CurrentCulture);
            statsSuccess.Text = Rate(stats);
            object wait = Get(stats, "median_wait_seconds");
            object recover = Get(stats, "median_recovery_seconds");
            statsWait.Text = wait is double ? Duration((double)wait) : "-";
            statsRecover.Text = recover is double ? Duration((double)recover) : "-";
            statsRetry.Text = ((int)Number(stats, "retry_now_requests")).ToString(CultureInfo.CurrentCulture);
            var kinds = Map(stats, "by_category");
            var parts = new List<string>();
            if (kinds != null)
                foreach (var pair in kinds)
                    parts.Add(S("field.recover_" + pair.Key, pair.Key) + " " +
                              Whole(pair.Value).ToString(CultureInfo.CurrentCulture));
            // One kind per line: a wrapped list breaks Korean inside a word.
            statsKinds.Text = parts.Count == 0 ? "-" : string.Join(Environment.NewLine, parts.ToArray());
            chart.Bars.Clear();
            if (outcomes != null)
                foreach (var pair in outcomes)
                {
                    int count = Whole(pair.Value);
                    if (count > 0) chart.Bars.Add(new KeyValuePair<string, int>(S("code." + pair.Key, pair.Key), count));
                }
            // Most common first, and as tall as its bars rather than a fixed box.
            chart.Bars.Sort(delegate(KeyValuePair<string, int> a, KeyValuePair<string, int> b)
            {
                int order = b.Value.CompareTo(a.Value);
                return order != 0 ? order : string.CompareOrdinal(a.Key, b.Key);
            });
            chart.EmptyText = S("stats.none", "Nothing yet");
            chart.Font = Font;
            chart.Height = Math.Max(1, chart.Bars.Count) * chart.RowHeight() + Px(4);
            chart.Describe();
            chart.Invalidate();
        }

        private void ShowTimeline(ListView list)
        {
            var row = Selected(list);
            if (row == null) return;
            CallAsync("timeline", IdArgument(row), delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply)) { Report(reply); return; }
                OpenTimeline(row, Items(Map(reply, "result"), "events"));
            });
        }

        private void OpenTimeline(Dictionary<string, object> row, List<object> events)
        {
            using (Form dialog = BuildTimeline(row, events)) dialog.ShowDialog(this);
        }

        /// The Timeline dialog for `row`'s `events`, built and not shown - OpenTimeline shows it, LayoutAudit
        /// measures it.
        private Form BuildTimeline(Dictionary<string, object> row, List<object> events)
        {
            {
                var dialog = new Form();
                dialog.Text = S("timeline.title", "Timeline") + " - " + Conversation(row);
                dialog.Font = Font;
                dialog.BackColor = Canvas;
                dialog.ForeColor = Ink;
                // In the window's theme, title bar and all.
                Soft.TitleBar(dialog);
                dialog.StartPosition = FormStartPosition.CenterParent;
                dialog.ClientSize = new Size(Px(640), Px(420));
                dialog.MinimizeBox = false;
                dialog.ShowInTaskbar = false;
                var view = List(S("timeline.title", "Timeline"),
                                Col(S("timeline.col_time", "Time"), 140),
                                Col(S("timeline.col_event", "Event"), 250),
                                Col(S("timeline.col_detail", "Detail"), 220));
                if (events != null)
                {
                    foreach (object entry in events)
                    {
                        var item = entry as Dictionary<string, object>;
                        if (item == null) continue;
                        string code = Str(item, "code") ?? "other";
                        var line = new ListViewItem(When(Number(item, "at")));
                        line.SubItems.Add(S("event." + code, code));
                        // The state it moved to, in the words the lists use. The engine's reason
                        // codes are not shown: they are a closed vocabulary for logs and tools,
                        // and a translated label for each would say no more than the state does.
                        string to = Str(item, "to_code");
                        line.SubItems.Add(to == null ? "" : S("code." + to, to.Replace('_', ' ')));
                        view.Items.Add(line);
                    }
                }
                // Each column's widest cell, so the columns share the dialog's width by what they hold (FitColumns).
                MeasureCells(view);
                var padding = new Panel();
                padding.BackColor = Canvas;
                padding.Dock = DockStyle.Fill;
                padding.Padding = Pad(12, 12, 12, 12);
                // On the soft scroll bar, as the lists in the window are (see SoftListHost).
                var host = new SoftListHost(view);
                host.Dock = DockStyle.Fill;
                padding.Controls.Add(host);
                dialog.Controls.Add(padding);
                var close = MakeButton(S("action.close", "Close"), true, delegate { dialog.Close(); });
                var buttons = ButtonRow();
                buttons.FlowDirection = FlowDirection.RightToLeft;
                buttons.Padding = Pad(12, 0, 12, 12);
                buttons.Controls.Add(close);
                dialog.Controls.Add(buttons);
                dialog.AcceptButton = close;
                dialog.CancelButton = close;
                // Escape closes it whatever has the focus, the list included, which is where
                // the focus is when the dialog opens.
                dialog.KeyPreview = true;
                dialog.KeyDown += delegate(object sender, KeyEventArgs e)
                {
                    if (e.KeyCode == Keys.Escape) { e.Handled = true; dialog.Close(); }
                };
                timelineList = view;
                return dialog;
            }
        }

        // The last Timeline dialog's list, for LayoutAudit.
        private ListView timelineList;

        private void ExportDiagnostics()
        {
            string target;
            using (var save = new SaveFileDialog())
            {
                save.Filter = "JSON (*.json)|*.json";
                save.FileName = "codex-auto-resume-diagnostics-" +
                                DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".json";
                // The export never replaces a file, so the dialog does not offer to either.
                save.OverwritePrompt = false;
                if (save.ShowDialog(this) != DialogResult.OK) return;
                target = save.FileName;
            }
            if (File.Exists(target))
            {
                Tell(S("diag.export_exists", "That file already exists; choose a new name."));
                return;
            }
            CallAsync("diagnostics", "{\"path\":" + Json.Escape(target) + "}", delegate(Dictionary<string, object> reply)
            {
                if (Ok(reply))
                    Tell(S("diag.export_done", "Diagnostics saved."));
                else Report(reply);
            });
        }

        private void StopWatcher()
        {
            if (!Confirm(S("confirm.stop_watcher",
                           "Stop the watcher? It finishes the check it is in and then stops. Nothing waiting is lost, and nothing is recovered until it runs again."),
                         S("action.stop_watcher", "Stop watcher"))) return;
            CallAsync("stop-watcher", null, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply)) { Report(reply); RefreshAfterChange(); return; }
                // What the single-instance mutex actually said. "It let go" and "nobody could
                // tell" are different answers, and only one of them means it is safe to
                // replace the files underneath it - so they get different sentences.
                string state = Str(Map(reply, "result"), "state") ?? "unknown";
                string text = state == "stopped" ? S("diag.stop_stopped", "The watcher stopped.")
                            : state == "still-finishing" ? S("diag.stop_finishing", "The watcher is finishing the check it is in, and stops when that is done.")
                            : state == "not-running" ? S("diag.stop_not_running", "The watcher was not running.")
                            : S("diag.stop_unknown", "Whether the watcher stopped could not be told.");
                Tell(text);
                RefreshAfterChange();
            });
        }

        private void OpenLogs()
        {
            string logs = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs");
            if (!Directory.Exists(logs)) return;
            try { Process.Start("explorer.exe", "\"" + logs + "\""); }
            catch (Exception error) { Report(Failure(error)); }
        }

        // Long enough for a setup that is doing real work on a slow machine, and short
        // enough that the window says something before a person gives up on it.
        private const int RepairMilliseconds = 120000;

        private void Repair()
        {
            if (!Confirm(S("confirm.repair", "Run setup again to repair the Windows registrations?"),
                         S("action.repair", "Repair installation"))) return;
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string python = Path.Combine(root, "runtime", "python.exe");
            string setup = Path.Combine(root, "app", "scripts", "plugin_setup.py");
            SetBusy(true);
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string outcome, detail;
                RunRepair(root, python, setup, out outcome, out detail);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    ReportRepair(outcome, detail);
                    RefreshAfterChange();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// Runs setup over this installation and says which of five things happened:
        /// done, busy, incomplete, running or failed. They are five different sentences
        /// because they ask for five different things from the person, and one of them -
        /// a setup that is still working - is not a failure at all.
        private static void RunRepair(string root, string python, string setup,
                                      out string outcome, out string detail)
        {
            outcome = "failed";
            detail = "";
            // Nothing to run: this installation is missing the files setup is made of, so
            // saying "setup did not finish" would describe the wrong problem.
            if (!File.Exists(python) || !File.Exists(setup)) { outcome = "incomplete"; return; }
            // The installer holds this while it works, and its own repair branch takes it
            // for the same reason: two processes rewriting the same registrations at once
            // is the one case the lock exists for. An abandoned lock means its holder died,
            // so it is taken rather than read as contention.
            using (var gate = new System.Threading.Mutex(false, "Local\\CodexAutoResume.Install"))
            {
                bool held = false;
                try { held = gate.WaitOne(0); }
                catch (System.Threading.AbandonedMutexException) { held = true; }
                if (!held) { outcome = "busy"; return; }
                try
                {
                    // --keep-state: a repair repairs. It re-registers what is broken and
                    // starts a stopped watcher, and never undoes a pause or adds back a
                    // sign-in start the person switched off - a plain `setup` does both, as
                    // a first install should.
                    var info = new ProcessStartInfo(python, Bridge.Quote(setup) + " setup --keep-state");
                    info.UseShellExecute = false;
                    // The installation this window belongs to. Setup resolves its target from
                    // this variable, so without it Repair would repair whichever installation
                    // the environment happens to point at - not the one being repaired.
                    info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;
                    info.CreateNoWindow = true;
                    info.RedirectStandardOutput = true;
                    info.RedirectStandardError = true;
                    using (Process process = Process.Start(info))
                    {
                        // Both pipes read without blocking on either, so a child that fills
                        // one of them cannot stall the wait - and the wait is what decides
                        // between "still working" and "failed".
                        Task<string> output = process.StandardOutput.ReadToEndAsync();
                        Task<string> failure = process.StandardError.ReadToEndAsync();
                        if (!process.WaitForExit(RepairMilliseconds))
                        {
                            // Left running on purpose: it is still registering things, and
                            // killing it halfway is how an installation ends up half written.
                            // The lock goes back now rather than being held by a thread that
                            // has stopped watching, which the installer's own comment allows
                            // for by treating an abandoned lock as free.
                            outcome = "running";
                            return;
                        }
                        output.Wait(5000);
                        failure.Wait(5000);
                        detail = Tail((output.IsCompleted ? output.Result : "") + "\n" +
                                      (failure.IsCompleted ? failure.Result : ""));
                        // 2 means everything was done but the watcher was not yet seen
                        // running - and it is also what setup exits with when it rejects an
                        // argument it does not know, such as --keep-state on a copy older
                        // than this window. So a 2 counts only with the line setup prints
                        // when it has finished its work.
                        if (process.ExitCode == 0 ||
                            (process.ExitCode == 2 &&
                             output.IsCompleted && output.Result.IndexOf("state: ", StringComparison.Ordinal) >= 0))
                            outcome = "done";
                    }
                }
                catch (Exception error) { detail = error.Message; }
                finally { gate.ReleaseMutex(); }
            }
        }

        /// The last few lines setup printed, which is where it says what went wrong. The
        /// line naming the installation folder is dropped: it is the one line that is a
        /// path rather than a reason.
        private static string Tail(string output)
        {
            var lines = new List<string>();
            foreach (string line in (output ?? "").Replace("\r", "").Split('\n'))
            {
                string trimmed = line.Trim();
                if (trimmed.Length == 0 || trimmed.StartsWith("state: ", StringComparison.Ordinal)) continue;
                lines.Add(trimmed);
            }
            var last = new List<string>();
            for (int i = Math.Max(0, lines.Count - 3); i < lines.Count; i++) last.Add(lines[i]);
            string text = string.Join(Environment.NewLine, last.ToArray());
            return text.Length > 400 ? text.Substring(text.Length - 400) : text;
        }

        // ------------------------------------------------------------------ updates
        // Nothing here runs unless the button is pressed. There is no timer, no check on
        // open and no check on a schedule: an update check is a request to github.com, and
        // a product that makes one without being asked has made the person's machine talk
        // to a server they did not choose to talk to.
        //
        // The four answers and their codes are scripts/bootstrap.ps1's, read back rather
        // than re-derived here. In particular "could not ask" is its own answer: a machine
        // with no network must never be told it is up to date, which is the one wrong thing
        // an update check can say.
        private const int UpdateCurrent = 0;
        private const int UpdateAvailable = 10;
        private const int UpdateLocalNewer = 11;
        private const int UpdateUnavailable = 12;
        // One request against a redirect. An install downloads a release and runs the
        // installer over it, on whatever connection the machine has.
        private const int CheckMilliseconds = 120000;
        private const int UpdateMilliseconds = 1200000;

        private void CheckForUpdates()
        {
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string script = Path.Combine(root, "app", "scripts", "bootstrap.ps1");
            if (!File.Exists(script))
            {
                diagUpdate.Text = S("diag.update_unavailable", "could not be checked");
                ReportUpdate("incomplete", null, null, null);
                return;
            }
            SetBusy(true);
            diagUpdate.Text = S("diag.update_asking", "asking...");
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string answer, current, latest, detail, compatibility;
                RunBootstrap(root, script, "-CheckOnly", CheckMilliseconds,
                             out answer, out current, out latest, out detail, out compatibility);
                Dictionary<string, object> live = CheckAfterRefresh(bridge, compatibility);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    diagUpdate.Text = UpdateFact(answer, current, latest);
                    // The check's second request, once github.com had answered: the Codex compatibility data, said on its
                    // card before the update's own answer is.
                    ReportCompatibilityLine(compatibility, live);
                    if (answer == "available") OfferUpdate(root, script, current, latest);
                    else ReportUpdate(answer, current, latest, detail);
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        private void OfferUpdate(string root, string script, string current, string latest)
        {
            if (!Confirm(S("confirm.update",
                           "Version {latest} has been published. Download and install it? Your settings, your pause and everything waiting are kept.",
                           "latest", latest).Replace("{current}", current ?? ""),
                         S("action.install", "Install")))
            {
                ReportUpdate("available", current, latest, null);
                return;
            }
            // Who is running now. `code_version` is no use for this: an old watcher reads the
            // version out of the files under it and starts reporting the new one the moment
            // they are replaced, so only a start time that moved says a watcher restarted.
            string before = WatcherIdentity();
            SetBusy(true);
            diagUpdate.Text = S("diag.update_installing", "installing...");
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string answer, from, to, detail, compatibility;
                RunBootstrap(root, script, "-Update", UpdateMilliseconds,
                             out answer, out from, out to, out detail, out compatibility);
                Dictionary<string, object> live = CheckAfterRefresh(bridge, compatibility);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    ReportCompatibilityLine(compatibility, live);
                    if (answer == "installed") AfterUpdate(before, latest, detail);
                    else
                    {
                        diagUpdate.Text = UpdateFact(answer, from, to);
                        ReportUpdate(answer, from, to, detail);
                    }
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// The identity of the process holding the watcher's heartbeat, or null where there
        /// is none to read. Two fields, because a pid on its own is reused by Windows.
        private string WatcherIdentity()
        {
            var watcher = Map(Map(snapshot, "status"), "watcher");
            if (watcher == null) return null;
            object pid = Get(watcher, "pid");
            object started = Get(watcher, "started_at");
            if (pid == null || started == null) return null;
            return Convert.ToString(pid, CultureInfo.InvariantCulture) + "@" +
                   Convert.ToString(started, CultureInfo.InvariantCulture);
        }

        /// Says what happened, and then whether the watcher actually changed hands. The
        /// installer asks the old watcher to stop and starts a new one; if the old one is
        /// still there, the files under it are now a different version from the code it is
        /// running, and that is worth saying out loud rather than reporting a clean success.
        private void AfterUpdate(string before, string latest, string detail)
        {
            diagUpdate.Text = S("diag.update_installed", "v{version} installed", "version", latest);
            CallAsync("status", null, delegate(Dictionary<string, object> reply)
            {
                string handover = "unknown";
                if (Ok(reply))
                {
                    var status = Map(reply, "result");
                    if (status == null) status = Map(reply, "status");
                    var watcher = Map(status, "watcher");
                    if (watcher != null)
                    {
                        object pid = Get(watcher, "pid");
                        object started = Get(watcher, "started_at");
                        string now = pid == null || started == null ? null
                                   : Convert.ToString(pid, CultureInfo.InvariantCulture) + "@" +
                                     Convert.ToString(started, CultureInfo.InvariantCulture);
                        if (now != null && before != null) handover = now == before ? "same" : "restarted";
                        else if (now != null && before == null) handover = "restarted";
                    }
                }
                string text = S("diag.update_done", "Version {version} is installed.", "version", latest);
                text += Environment.NewLine + Environment.NewLine +
                        (handover == "restarted"
                            ? S("diag.update_watcher_restarted", "The watcher was restarted and is running the new version.")
                         : handover == "same"
                            ? S("diag.update_watcher_same", "The watcher that is running is still the one from before the update, so it is running the old code. Stop it and start it again from this page.")
                            : S("diag.update_watcher_unknown", "Whether the watcher restarted could not be told."));
                text += Environment.NewLine + Environment.NewLine +
                        S("diag.update_reopen", "Close this window and open it again so it runs the new version.");
                Tell(text);
                RefreshAfterChange();
            });
        }

        /// Runs scripts/bootstrap.ps1 with one switch and reads the line it prints for a
        /// caller - and, since v0.6.5, the `compatibility:` line before it, the answer to the
        /// check's second request (CompatibilityLine; null when it made none). The lines are
        /// the contract; the rest of the output is for a person.
        private static void RunBootstrap(string root, string script, string flag, int milliseconds,
                                         out string answer, out string current, out string latest,
                                         out string detail, out string compatibility)
        {
            answer = "failed";
            current = null;
            latest = null;
            detail = "";
            compatibility = null;
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                             "WindowsPowerShell", "v1.0", "powershell.exe");
            // By full path, never by bare name: a `powershell.exe` earlier on PATH is the
            // whole of v0.5.7's system-executable fix, and this is a new caller of one.
            if (!File.Exists(powershell)) { answer = "incomplete"; return; }
            try
            {
                var info = new ProcessStartInfo(powershell,
                    "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " +
                    Bridge.Quote(script) + " " + flag);
                info.UseShellExecute = false;
                // The installation this window belongs to, not whichever one the environment
                // happens to name.
                info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                using (Process process = Process.Start(info))
                {
                    Task<string> output = process.StandardOutput.ReadToEndAsync();
                    Task<string> failure = process.StandardError.ReadToEndAsync();
                    if (!process.WaitForExit(milliseconds))
                    {
                        // Not killed: it may be part way through replacing an installation,
                        // and half an installation is worse than a slow one.
                        answer = "running";
                        return;
                    }
                    output.Wait(5000);
                    failure.Wait(5000);
                    string printed = output.IsCompleted ? output.Result : "";
                    detail = Tail(printed + "\n" + (failure.IsCompleted ? failure.Result : ""));
                    compatibility = CompatibilityLine(printed);
                    string line = null;
                    foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
                    {
                        string trimmed = raw.Trim();
                        if (trimmed.StartsWith("update: ", StringComparison.Ordinal)) line = trimmed;
                    }
                    string[] words = line == null ? new string[0]
                                   : line.Substring("update: ".Length).Split(' ');
                    string said = words.Length > 0 ? words[0] : "";
                    if (words.Length > 1) current = words[1];
                    if (words.Length > 2) latest = words[2];
                    int code = process.ExitCode;
                    // The code and the line have to agree. Either alone could be an older
                    // script, a crash after printing, or an exit code Windows supplied; a
                    // disagreement is not an answer and is reported as one that failed.
                    if (code == UpdateCurrent && said == "current") answer = "current";
                    else if (code == UpdateAvailable && said == "available") answer = "available";
                    else if (code == UpdateLocalNewer && said == "newer-local") answer = "newer-local";
                    else if (code == UpdateUnavailable && said == "unavailable") answer = "unavailable";
                    // An install runs on past the line and exits with the installer's code.
                    else if (code == 0 && said == "available") answer = "installed";
                }
            }
            catch (Exception error) { detail = error.Message; }
        }

        /// The one-line fact beside "Updates" on the Health card.
        private string UpdateFact(string answer, string current, string latest)
        {
            if (answer == "current")
                return S("diag.update_current", "up to date");
            if (answer == "available")
                return S("diag.update_available", "v{version} available", "version", latest);
            if (answer == "newer-local")
                return S("diag.update_newer_local", "ahead of v{version}", "version", latest);
            if (answer == "installed")
                return S("diag.update_installed", "v{version} installed", "version", latest);
            return S("diag.update_unavailable", "could not be checked");
        }

        private void ReportUpdate(string answer, string current, string latest, string detail)
        {
            string text =
                answer == "current"
                    ? S("diag.update_is_current", "Version {version} is the newest published release.", "version", current)
              : answer == "available"
                    ? S("diag.update_is_available", "Version {version} has been published.", "version", latest)
              : answer == "newer-local"
                    // A development build, or a release that was withdrawn. Either way there
                    // is nothing to install, and installing would go backwards.
                    ? S("diag.update_is_newer_local", "This build is ahead of the newest published release, so there is nothing to install.")
              : answer == "unavailable"
                    ? S("diag.update_could_not_ask", "GitHub could not be asked just now. This says nothing about whether an update exists.")
              : answer == "running"
                    ? S("diag.update_running", "It is taking longer than usual and is still working. It carries on in the background; look at this page again in a few minutes.")
              : answer == "incomplete"
                    ? S("diag.update_incomplete", "Files this installation is made of are missing, so it could not be checked. Install it again from the release archive.")
                    : S("diag.update_failed", "The update check did not finish.");
            if ((answer == "failed" || answer == "unavailable") && !string.IsNullOrEmpty(detail))
                text += Environment.NewLine + Environment.NewLine + detail;
            Tell(text);
        }

        private void ReportRepair(string outcome, string detail)
        {
            string text = outcome == "done" ? S("diag.repair_done", "Setup finished.")
                        : outcome == "running" ? S("diag.repair_running", "Setup is taking longer than usual and is still working. It carries on in the background; look at this page again in a minute.")
                        : outcome == "busy" ? S("diag.repair_busy", "An installation or a repair is already running. Try again once it has finished.")
                        : outcome == "incomplete" ? S("diag.repair_incomplete", "Files this installation is made of are missing, so setup could not run. Install it again from the release archive.")
                        : S("diag.repair_failed", "Setup did not finish.");
            // What setup printed, but only where it is the answer: for the outcomes above it
            // would be noise beside a sentence that already says what to do.
            if (outcome == "failed" && !string.IsNullOrEmpty(detail))
                text += Environment.NewLine + Environment.NewLine + detail;
            Tell(text);
        }
    }
}

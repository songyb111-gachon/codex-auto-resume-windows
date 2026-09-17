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
    internal sealed class NoteLabel : Label
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

        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = proposedSize.Width > 0 && proposedSize.Width < 20000 ? proposedSize.Width : Soft.Px(260);
            int height = rows.Count == 0
                ? TextRenderer.MeasureText(empty.Length == 0 ? " " : empty, Font, new Size(width, int.MaxValue),
                                           TextFormatFlags.WordBreak).Height
                : rows.Count * RowHeight;
            return new Size(width, height);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Color ground = Parent != null ? Parent.BackColor : Palette.Surface;
            g.Clear(ground);
            if (rows.Count == 0)
            {
                TextRenderer.DrawText(g, empty, Font, ClientRectangle, Palette.Secondary,
                                      TextFormatFlags.WordBreak | TextFormatFlags.Left);
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

        // ----------------------------------------------------------------- chrome
        private void BuildDashboard()
        {
            // `--page=<name>` opens on that page; `--settings` is the older spelling.
            foreach (string argument in Environment.GetCommandLineArgs())
            {
                if (argument == "--settings") firstPage = "settings";
                else if (argument.StartsWith("--page=", StringComparison.Ordinal))
                    firstPage = argument.Substring(7);
                // Which section the Settings page opens on; anything unknown is General.
                else if (argument.StartsWith("--section=", StringComparison.Ordinal))
                    currentSection = argument.Substring(10);
            }

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
            var label = new Label();
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
            var grid = new TableLayoutPanel();
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
            // backgrounds for one Overview, and 1.4 s the first time Statistics was shown.
            grid.BackColor = Surface;
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
            list.BackColor = Surface;
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
            // Every column first gets its heading, whole, in the list's font; what is left is shared
            // in the declared proportions. Shared out alone, the proportions cut "Next check",
            // "Attempts" and "Auto-resume" short in a window of v0.6.2's width.
            //
            // Then each column keeps room for the widest thing it holds: every column but the
            // conversation's first, and the conversation's from what they leave - a name may be as long
            // as its owner made it, and a state or a kind cut short says nothing. From the headings
            // alone, a status needed the window 1,239 px wide before "waiting for the usage reset" was
            // drawn whole (measured, 150%), because its column only ever had its share of what the
            // headings left.
            var floor = new int[weights.Length];
            int floors = 0, others = 0, wanted = 0;
            int[] cells;
            cellWidths.TryGetValue(list, out cells);
            var want = new int[weights.Length];
            for (int i = 0; i < weights.Length; i++)
            {
                floor[i] = HeadingWidth(list, i);
                floors += floor[i];
                want[i] = cells != null && i < cells.Length ? Math.Max(floor[i], cells[i]) : floor[i];
                if (i > 0) others += want[i];
                if (i > 0) wanted += want[i] - floor[i];
            }
            if (floor[0] + others <= available)
            {
                for (int i = 1; i < weights.Length; i++) floor[i] = want[i];
                floor[0] = Math.Max(floor[0], Math.Min(want[0], available - others));
                floors = floor[0] + others;
            }
            else if (floors < available && wanted > 0)
            {
                // Not room for all of that: each of those columns is given the same part of what it
                // wants past its heading, so none is cut to its heading while another is drawn whole.
                int more = floor[0];
                for (int i = 1; i < weights.Length; i++)
                {
                    floor[i] += (int)Math.Floor((want[i] - floor[i]) * (double)(available - floors) / wanted);
                    more += floor[i];
                }
                floors = more;
            }
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
                    string text = item.SubItems[c].Text;
                    int width = c == 1 ? Soft.ChipSize(text, list.Font).Width
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
            using (var brush = new SolidBrush(Surface)) e.Graphics.FillRectangle(brush, e.Bounds);
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
            Color back = !selected ? Surface : Palette.Contrast ? Palette.AccentSoft : Palette.Inset;
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
                DrawResumeBox(e.Graphics, cell, ThreadOn(row), back);
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
        /// on the row's own ground.
        private void DrawResumeBox(Graphics g, Rectangle cell, bool on, Color ground)
        {
            int width = Px(Brand.SwitchWidth), height = Px(Brand.SwitchHeight);
            var track = new Rectangle(cell.X + Px(2), cell.Y + (cell.Height - height) / 2, width, height);
            Soft.Switch(g, track, on, true, ground);
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
            TableLayoutPanel grid = Grid(2);

            TableLayoutPanel now = MakeCard(S("overview.now", "Right now"));
            now.Margin = GridGap(0, false);
            TableLayoutPanel facts = Facts(now);
            nowRecovery = Fact(facts, S("overview.recovery", "Automatic recovery"));
            nowWatcher = Fact(facts, S("diag.watcher", "Watcher"));
            nowEngine = Fact(facts, S("overview.engine", "Codex engine"));
            nowLastCheck = Fact(facts, S("overview.last_check", "Last check"));
            toggleButton = MakeButton(S("action.pause", "Pause recovery"), false, delegate { TogglePause(); });
            HeadWith(now, toggleButton);

            TableLayoutPanel waiting = MakeCard(S("overview.waiting", "Waiting"));
            waiting.Margin = GridGap(1, false);
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
            HeadWith(waiting, MakeButton(S("nav.pending", "Pending"), false, delegate { ShowPage("pending"); }));

            TableLayoutPanel week = MakeCard(S("overview.week", "Last 7 days"));
            week.Margin = GridGap(0, true);
            HeadWith(week, null);
            TableLayoutPanel weekFacts = Facts(week);
            weekDetected = Fact(weekFacts, S("overview.detected", "Interruptions"));
            weekSent = Fact(weekFacts, S("overview.sent", "Continuations sent"));
            weekRecovered = Fact(weekFacts, S("overview.recovered", "Recovered"));
            weekSuccess = Fact(weekFacts, S("overview.success", "Success rate"));

            // The last few recoveries that finished, so the page answers "did it work" as
            // well as "is it working" without a trip to the History page.
            TableLayoutPanel recent = MakeCard(S("overview.recent", "Recently finished"));
            recent.Margin = GridGap(1, true);
            recentGrid = Facts(recent);
            recentEmpty = Value(S("history.empty", "No recoveries yet"));
            recentEmpty.ForeColor = Secondary;
            recent.Controls.Add(recentEmpty);
            HeadWith(recent, MakeButton(S("nav.history", "History"), false, delegate { ShowPage("history"); }));
            recentGrid.SizeChanged += delegate { FitRecentNames(); };

            grid.Controls.Add(now, 0, 0);
            grid.Controls.Add(waiting, 1, 0);
            grid.Controls.Add(week, 0, 1);
            grid.Controls.Add(recent, 1, 1);
            page.Controls.Add(grid);
            return page;
        }

        /// A card's heading with what the card leads to beside it, as the panel's card head has it:
        /// the heading at the left, the button at the right, the card's gap between them. Every
        /// Overview card has this row, one button high whether it holds a button or not, so the
        /// facts in two cards side by side start on one line.
        ///
        /// Under the card's content the button cost its card a button and a gap more, and the page
        /// was then taller than a window that fits a 1920 by 1080 screen at 150%: 646 px of window
        /// with the screenshots' conversations (measured), where that screen leaves 634.
        private void HeadWith(TableLayoutPanel card, Button button)
        {
            Control heading = card.Controls[0];
            var head = new SoftStack();
            head.BackColor = Surface;
            head.ColumnCount = 2;
            head.RowCount = 1;
            head.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            head.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            head.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            head.AutoSize = true;
            head.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            head.Dock = DockStyle.Fill;
            head.MinimumSize = new Size(0, Px(Brand.ButtonHeight));
            // The panel's gap between a card's head and the first thing under it.
            head.Margin = Pad(0, 0, 0, Brand.CardFirstGap);
            heading.Margin = new Padding(0);
            heading.Anchor = AnchorStyles.Left;
            card.Controls.Remove(heading);
            head.Controls.Add(heading, 0, 0);
            if (button != null)
            {
                button.Anchor = AnchorStyles.Right;
                button.Margin = Pad(Brand.CardHeadGap, 0, 0, 0);
                head.Controls.Add(button, 1, 0);
            }
            card.Controls.Add(head);
            card.Controls.SetChildIndex(head, 0);
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
            gates.BackColor = Surface;
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
            chart.BackColor = Surface;
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
            health.Margin = GridGap(0, true);
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
            tools.Margin = GridGap(1, true);
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
            page.Controls.Add(grid);
            return page;
        }

        // ------------------------------------------------------------------ clock
        private void StartClock()
        {
            clock = new Timer();
            clock.Interval = 1000;
            clock.Tick += delegate
            {
                ticks++;
                UpdateCountdowns();
                // Every second too, so a usage reset that passes while a row stays selected
                // makes Retry now available without waiting for the next read.
                UpdatePendingButtons();
                // The data every five seconds, the countdown every second. Nothing on the
                // Settings page is refreshed under a person who is editing it.
                if (ticks % 5 == 0 && currentPage != "settings")
                {
                    RefreshNow();
                    if (currentPage == "statistics") LoadStatistics();
                }
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
                if (Unreadable(reply, "pending")) ShowUnreadable(pendingList, pendingEmpty, unreadable);
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
                if (historyUnreadable) ShowUnreadable(historyList, historyEmpty, unreadable);
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

        private void MarkUnavailable()
        {
            // The same unavailable state the header shows when the status cannot be read,
            // and nothing drawn from data that is no longer being read: no countdown, and no
            // list whose rows an action could be taken on. Keeping the last good snapshot on
            // screen said "watching, recovery on" for as long as the reads kept failing.
            snapshot = null;
            shownEnabled = null;
            stateDot.State = "idle";
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
            if (pendingList != null) ShowUnreadable(pendingList, pendingEmpty, unreadable);
            if (historyList != null) ShowUnreadable(historyList, historyEmpty, unreadable);
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
                var row = item.Tag as Dictionary<string, object>;
                double eligible = Number(row, "eligible_at");
                string text = eligible <= 0 ? "" : eligible <= now ? S("pending.due", "due now") : Countdown(eligible - now);
                if (item.SubItems[3].Text != text) item.SubItems[3].Text = text;
            }
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

        private bool Confirm(string question)
        {
            return question == null || MessageBox.Show(this, question, "Codex Auto Resume",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes;
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
            MessageBox.Show(this, lead + (said != null || string.IsNullOrEmpty(english)
                                          ? "" : Environment.NewLine + Environment.NewLine + english),
                            "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Warning);
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
                               "Stop recovering \"{name}\"? A continuation already running in Codex is not stopped.", row)))
                return;
            Send("cancel", IdArgument(row));
        }

        private void ResetSelected()
        {
            var row = Selected(historyList);
            if (row == null) return;
            if (!Confirm(Named("confirm.reset",
                               "Give \"{name}\" its attempts back? It waits and is checked again; nothing is sent now.", row)))
                return;
            CallAsync("reset-budget", IdArgument(row), delegate(Dictionary<string, object> reply)
            {
                Report(reply);
                string notice = BudgetResetNotice(reply,
                    S("history.reset_done", "Attempts restored. Nothing was sent."),
                    S("history.reset_thread_off", "Automatic recovery is off for this conversation; switch it on before recovery can run."));
                if (notice != null)
                    MessageBox.Show(this, notice, "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Information);
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
                                    "Turn automatic recovery back on for \"{name}\"? Nothing is sent now; every check still applies.", row)))
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
                                         "Turn automatic recovery back on for \"{name}\"? Nothing is sent now; every check still applies.", row)))
                return;
            Send("interruption-recovery", "{\"interruption_id\":" + Json.Escape(id) + ",\"thread_id\":" +
                 Json.Escape(thread) + ",\"enabled\":" + (enable ? "true" : "false") + "}");
        }

        private void CancelAll()
        {
            if (busy > 0 || pendingList.Items.Count == 0) return;
            if (!Confirm(S("confirm.cancel_all",
                           "Stop every pending recovery? Anything already handed to Codex is withdrawn only if it is still queued.")))
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
                    MessageBox.Show(this, S("status.unavailable", "Status unavailable"), "Codex Auto Resume",
                                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
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
            if (enable && !Confirm(S("confirm.resume", "Turn automatic recovery back on?"))) return;
            Send("enabled", enable ? "{\"enabled\":true}" : "{\"enabled\":false}");
        }

        private void ClearHistory()
        {
            if (!Confirm(S("confirm.clear", "Hide finished recoveries from the history?"))) return;
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
            using (var dialog = new Form())
            {
                dialog.Text = S("timeline.title", "Timeline") + " - " + Conversation(row);
                dialog.Font = Font;
                dialog.BackColor = Canvas;
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
                var padding = new Panel();
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
                dialog.ShowDialog(this);
            }
        }

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
                MessageBox.Show(this, S("diag.export_exists", "That file already exists; choose a new name."),
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            CallAsync("diagnostics", "{\"path\":" + Json.Escape(target) + "}", delegate(Dictionary<string, object> reply)
            {
                if (Ok(reply))
                    MessageBox.Show(this, S("diag.export_done", "Diagnostics saved."), "Codex Auto Resume",
                                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                else Report(reply);
            });
        }

        private void StopWatcher()
        {
            if (!Confirm(S("confirm.stop_watcher",
                           "Stop the watcher? It finishes the check it is in and then stops. Nothing waiting is lost, and nothing is recovered until it runs again."))) return;
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
                MessageBox.Show(this, text, "Codex Auto Resume", MessageBoxButtons.OK,
                                state == "unknown" ? MessageBoxIcon.Warning : MessageBoxIcon.Information);
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
            if (!Confirm(S("confirm.repair", "Run setup again to repair the Windows registrations?"))) return;
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
                string answer, current, latest, detail;
                RunBootstrap(root, script, "-CheckOnly", CheckMilliseconds,
                             out answer, out current, out latest, out detail);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    diagUpdate.Text = UpdateFact(answer, current, latest);
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
                           "latest", latest).Replace("{current}", current ?? "")))
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
                string answer, from, to, detail;
                RunBootstrap(root, script, "-Update", UpdateMilliseconds,
                             out answer, out from, out to, out detail);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
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
                MessageBox.Show(this, text, "Codex Auto Resume", MessageBoxButtons.OK,
                                handover == "restarted" ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
                RefreshAfterChange();
            });
        }

        /// Runs scripts/bootstrap.ps1 with one switch and reads the one line it prints for
        /// a caller. The line is the contract; the rest of the output is for a person.
        private static void RunBootstrap(string root, string script, string flag, int milliseconds,
                                         out string answer, out string current, out string latest,
                                         out string detail)
        {
            answer = "failed";
            current = null;
            latest = null;
            detail = "";
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
            bool calm = answer == "current" || answer == "available" || answer == "newer-local";
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
            MessageBox.Show(this, text, "Codex Auto Resume", MessageBoxButtons.OK,
                            calm ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
        }

        private void ReportRepair(string outcome, string detail)
        {
            bool calm = outcome == "done" || outcome == "running";
            string text = outcome == "done" ? S("diag.repair_done", "Setup finished.")
                        : outcome == "running" ? S("diag.repair_running", "Setup is taking longer than usual and is still working. It carries on in the background; look at this page again in a minute.")
                        : outcome == "busy" ? S("diag.repair_busy", "An installation or a repair is already running. Try again once it has finished.")
                        : outcome == "incomplete" ? S("diag.repair_incomplete", "Files this installation is made of are missing, so setup could not run. Install it again from the release archive.")
                        : S("diag.repair_failed", "Setup did not finish.");
            // What setup printed, but only where it is the answer: for the outcomes above it
            // would be noise beside a sentence that already says what to do.
            if (outcome == "failed" && !string.IsNullOrEmpty(detail))
                text += Environment.NewLine + Environment.NewLine + detail;
            MessageBox.Show(this, text, "Codex Auto Resume", MessageBoxButtons.OK,
                            calm ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
        }
    }
}

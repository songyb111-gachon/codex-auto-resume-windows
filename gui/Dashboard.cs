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
        private bool current;

        internal bool Current
        {
            get { return current; }
            set
            {
                if (current == value) return;
                current = value;
                if (IsHandleCreated)
                {
                    AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
                    if (value) AccessibilityNotifyClients(AccessibleEvents.Selection, -1);
                }
            }
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

    internal sealed partial class SettingsForm
    {
        // ------------------------------------------------------------------ state
        private readonly Panel nav = new BufferedPanel();
        private readonly Panel pageHost = new Panel();
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
        private Button retryButton, cancelButton, timelineButton, threadButton;
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
                      diagUpgrade;
        private Button exportButton, repairButton;

        // ----------------------------------------------------------------- chrome
        private void BuildDashboard()
        {
            // `--page=<name>` opens on that page; `--settings` is the older spelling.
            foreach (string argument in Environment.GetCommandLineArgs())
            {
                if (argument == "--settings") firstPage = "settings";
                else if (argument.StartsWith("--page=", StringComparison.Ordinal))
                    firstPage = argument.Substring(7);
            }

            nav.Dock = DockStyle.Top;
            nav.BackColor = Surface;
            // The bottom padding keeps the strip of buttons off the band where the nav
            // draws the selected page's underline and its closing hairline; a docked child
            // covers whatever of its parent it is given, painting included.
            nav.Padding = Pad(14, 0, 14, 4);
            var strip = new FlowLayoutPanel();
            strip.Dock = DockStyle.Fill;
            strip.FlowDirection = FlowDirection.LeftToRight;
            strip.WrapContents = false;
            strip.BackColor = Surface;
            strip.Margin = new Padding(0);
            strip.AccessibleRole = AccessibleRole.PageTabList;
            string[] fallbacks = { "Overview", "Pending", "History", "Statistics", "Diagnostics", "Settings" };
            for (int i = 0; i < PageOrder.Length; i++)
            {
                string name = PageOrder[i];
                var button = new NavButton();
                button.Text = S("nav." + name, fallbacks[i]);
                button.AutoSize = true;
                button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                button.FlatStyle = FlatStyle.Flat;
                button.FlatAppearance.BorderSize = 0;
                button.BackColor = Surface;
                button.ForeColor = Secondary;
                button.Padding = Pad(10, 6, 10, 6);
                button.Margin = Pad(0, 4, 2, 0);
                button.Cursor = Cursors.Hand;
                button.UseVisualStyleBackColor = false;
                string target = name;
                button.Click += delegate { ShowPage(target); };
                navButtons[name] = button;
                strip.Controls.Add(button);
            }
            nav.Controls.Add(strip);
            nav.Height = strip.PreferredSize.Height + Px(14);
            nav.Paint += delegate(object sender, PaintEventArgs e)
            {
                // The selected page is underlined in the accent; a hairline closes the strip.
                using (var pen = new Pen(Line))
                    e.Graphics.DrawLine(pen, 0, nav.Height - 1, nav.Width, nav.Height - 1);
                NavButton selected;
                if (currentPage != null && navButtons.TryGetValue(currentPage, out selected))
                {
                    Rectangle bounds = nav.RectangleToClient(selected.RectangleToScreen(selected.ClientRectangle));
                    using (var brush = new SolidBrush(Accent))
                        e.Graphics.FillRectangle(brush, bounds.Left + Px(6), nav.Height - Px(3),
                                                 bounds.Width - Px(12), Px(3));
                }
            };

            pageHost.Dock = DockStyle.Fill;
            pageHost.BackColor = Canvas;

            pages["overview"] = BuildOverview();
            pages["pending"] = BuildPending();
            pages["history"] = BuildHistory();
            pages["statistics"] = BuildStatistics();
            pages["diagnostics"] = BuildDiagnostics();
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
            if (!pages.ContainsKey(name)) name = "overview";
            currentPage = name;
            pageHost.SuspendLayout();
            pageHost.Controls.Clear();
            pageHost.Controls.Add(pages[name]);
            pageHost.ResumeLayout(true);
            foreach (var pair in navButtons)
            {
                pair.Value.ForeColor = pair.Key == name ? Ink : Secondary;
                pair.Value.Font = new Font(Font, pair.Key == name ? FontStyle.Bold : FontStyle.Regular);
                pair.Value.Current = pair.Key == name;
            }
            bool settings = name == "settings";
            if (saveButton != null) saveButton.Visible = settings;
            if (restoreButton != null) restoreButton.Visible = settings;
            nav.Invalidate();
            if (name == "statistics") LoadStatistics();
            if (!settings) RefreshNow();
        }

        private Panel Page()
        {
            var page = new Panel();
            page.Dock = DockStyle.Fill;
            page.BackColor = Canvas;
            page.Padding = Pad(18, 16, 18, 8);
            page.AutoScroll = true;
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
            grid.BackColor = Color.Transparent;
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
            var grid = new TableLayoutPanel();
            grid.Dock = DockStyle.Top;
            grid.AutoSize = true;
            grid.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            grid.ColumnCount = columnCount;
            for (int i = 0; i < columnCount; i++) grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / columnCount));
            grid.BackColor = Canvas;
            return grid;
        }

        private FlowLayoutPanel ButtonRow()
        {
            var row = new FlowLayoutPanel();
            row.Dock = DockStyle.Bottom;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.WrapContents = true;
            row.BackColor = Canvas;
            row.Padding = Pad(0, 10, 0, 4);
            return row;
        }

        private ListView List(string accessibleName, params KeyValuePair<string, int>[] columnSpec)
        {
            var list = new ListView();
            list.View = View.Details;
            list.FullRowSelect = true;
            list.MultiSelect = false;
            list.HideSelection = false;
            list.Dock = DockStyle.Fill;
            list.BorderStyle = BorderStyle.FixedSingle;
            list.BackColor = Surface;
            list.ForeColor = Ink;
            list.AccessibleName = accessibleName;
            foreach (var column in columnSpec) list.Columns.Add(column.Key, Px(column.Value));
            return list;
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
            now.Margin = Pad(0, 0, 9, 14);
            TableLayoutPanel facts = Facts(now);
            nowRecovery = Fact(facts, S("overview.recovery", "Automatic recovery"));
            nowWatcher = Fact(facts, S("diag.watcher", "Watcher"));
            nowEngine = Fact(facts, S("overview.engine", "Codex engine"));
            nowLastCheck = Fact(facts, S("overview.last_check", "Last check"));
            toggleButton = MakeButton(S("action.pause", "Pause recovery"), false, delegate { TogglePause(); });
            toggleButton.Margin = Pad(0, 12, 0, 0);
            now.Controls.Add(toggleButton);

            TableLayoutPanel waiting = MakeCard(S("overview.waiting", "Waiting"));
            waiting.Margin = Pad(9, 0, 0, 14);
            waitingLine = Value("-");
            waitingLine.Font = new Font(Font.FontFamily, Font.Size + 3f, FontStyle.Bold);
            nextLine = Value("");
            nextLine.ForeColor = Accent;
            runningLine = Value("");
            runningLine.ForeColor = Secondary;
            waiting.Controls.Add(waitingLine);
            waiting.Controls.Add(nextLine);
            waiting.Controls.Add(runningLine);
            var show = MakeButton(S("nav.pending", "Pending"), false, delegate { ShowPage("pending"); });
            show.Margin = Pad(0, 12, 0, 0);
            waiting.Controls.Add(show);

            TableLayoutPanel week = MakeCard(S("overview.week", "Last 7 days"));
            week.Margin = Pad(0, 0, 9, 14);
            TableLayoutPanel weekFacts = Facts(week);
            weekDetected = Fact(weekFacts, S("overview.detected", "Interruptions"));
            weekSent = Fact(weekFacts, S("overview.sent", "Continuations sent"));
            weekRecovered = Fact(weekFacts, S("overview.recovered", "Recovered"));
            weekSuccess = Fact(weekFacts, S("overview.success", "Success rate"));

            // The last few recoveries that finished, so the page answers "did it work" as
            // well as "is it working" without a trip to the History page.
            TableLayoutPanel recent = MakeCard(S("overview.recent", "Recently finished"));
            recent.Margin = Pad(9, 0, 0, 14);
            recentGrid = Facts(recent);
            recentEmpty = Value(S("history.empty", "No recoveries yet"));
            recentEmpty.ForeColor = Secondary;
            recent.Controls.Add(recentEmpty);
            var all = MakeButton(S("nav.history", "History"), false, delegate { ShowPage("history"); });
            all.Margin = Pad(0, 12, 0, 0);
            recent.Controls.Add(all);

            grid.Controls.Add(now, 0, 0);
            grid.Controls.Add(waiting, 1, 0);
            grid.Controls.Add(week, 0, 1);
            grid.Controls.Add(recent, 1, 1);
            page.Controls.Add(grid);
            return page;
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
            if (key != recentShown)
            {
                recentShown = key;
                recentGrid.SuspendLayout();
                recentGrid.Controls.Clear();
                foreach (var row in rows)
                {
                    var name = Value(Conversation(row));
                    name.ForeColor = Secondary;
                    name.Margin = Pad(0, 3, 18, 3);
                    var outcome = Value(CodeLabel(row));
                    outcome.Tag = row;
                    recentGrid.Controls.Add(name);
                    recentGrid.Controls.Add(outcome);
                }
                recentGrid.ResumeLayout(true);
                recentEmpty.Text = S("history.empty", "No recoveries yet");
                recentEmpty.Visible = rows.Count == 0;
            }
            // The age moves on its own, so it is rewritten every time without a rebuild.
            foreach (Control control in recentGrid.Controls)
            {
                var row = control.Tag as Dictionary<string, object>;
                if (row != null) control.Text = CodeLabel(row) + "  ·  " + Ago(Number(row, "outcome_at"));
            }
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
                               Col(S("pending.col_conversation", "Conversation"), 220),
                               Col(S("pending.col_status", "Status"), 200),
                               Col(S("pending.col_category", "Kind"), 130),
                               Col(S("pending.col_next", "Next check"), 110),
                               Col(S("pending.col_attempts", "Attempts"), 80));
            pendingEmpty = Value(S("pending.empty", "Nothing is waiting"));
            pendingEmpty.ForeColor = Secondary;
            pendingEmpty.Dock = DockStyle.Top;

            FlowLayoutPanel row = ButtonRow();
            retryButton = MakeButton(S("action.retry_now", "Retry now"), true, delegate { RetryNow(); });
            cancelButton = MakeButton(S("action.cancel", "Cancel"), false, delegate { CancelSelected(); });
            timelineButton = MakeButton(S("action.timeline", "Timeline"), false, delegate { ShowTimeline(pendingList); });
            threadButton = MakeButton(S("action.thread_off", "Turn off for this conversation"), false,
                                      delegate { ToggleThread(pendingList); });
            foreach (Button button in new[] { retryButton, cancelButton, timelineButton, threadButton })
            {
                button.Margin = Pad(0, 0, 9, 0);
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
                ShowPendingNote();
                UpdatePendingButtons();
            };
            page.Controls.Add(pendingList);
            page.Controls.Add(pendingEmpty);
            page.Controls.Add(row);
            UpdatePendingButtons();
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
            historyEmpty = Value(S("history.empty", "No recoveries yet"));
            historyEmpty.ForeColor = Secondary;
            historyEmpty.Dock = DockStyle.Top;

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
            page.Controls.Add(historyList);
            page.Controls.Add(historyEmpty);
            page.Controls.Add(row);
            UpdateHistoryButtons();
            return page;
        }

        // -------------------------------------------------------------- statistics
        private Control BuildStatistics()
        {
            Panel page = Page();
            var top = new FlowLayoutPanel();
            top.Dock = DockStyle.Top;
            top.AutoSize = true;
            top.BackColor = Canvas;
            top.Padding = Pad(0, 0, 0, 10);
            var label = Value(S("stats.period", "Period"));
            label.Margin = Pad(0, 7, 12, 0);
            period = new ComboBox();
            period.DropDownStyle = ComboBoxStyle.DropDownList;
            period.Width = Px(160);
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
            numbers.Margin = Pad(0, 0, 9, 14);
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
            outcomes.Margin = Pad(9, 0, 0, 14);
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
            health.Margin = Pad(0, 0, 9, 14);
            TableLayoutPanel facts = Facts(health);
            diagVersion = Fact(facts, S("diag.version", "Version"));
            diagWatcher = Fact(facts, S("diag.watcher", "Watcher"));
            diagLastCheck = Fact(facts, S("diag.last_check", "Last check"));
            diagEngine = Fact(facts, S("diag.engine", "Codex engine"));
            diagRecovery = Fact(facts, S("diag.recovery", "Automatic recovery"));
            diagStartup = Fact(facts, S("diag.startup", "Starts at sign-in"));
            diagUpgrade = Value("");
            diagUpgrade.ForeColor = Accent;
            diagUpgrade.MaximumSize = new Size(Px(360), 0);
            health.Controls.Add(diagUpgrade);

            TableLayoutPanel tools = MakeCard(S("diag.tools", "Tools"));
            tools.Margin = Pad(9, 0, 0, 14);
            exportButton = MakeButton(S("action.export", "Export diagnostics..."), false, delegate { ExportDiagnostics(); });
            repairButton = MakeButton(S("action.repair", "Repair installation"), false, delegate { Repair(); });
            foreach (Button button in new[] {
                exportButton,
                MakeButton(S("action.open_logs", "Open logs folder"), false, delegate { OpenLogs(); }),
                repairButton })
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
                    if (Ok(reply)) ApplySnapshot(reply);
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
            string category = Str(row, "category") ?? "";
            return S("field.recover_" + category, category.Replace('_', ' '));
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
            bool upgrade = false;
            if (status != null)
            {
                ApplyStatus(status, null);
                var watcher = Map(status, "watcher");
                bool enabled = Equals(Get(status, "enabled"), true);
                shownEnabled = enabled;
                upgrade = Equals(Get(status, "upgrade_pending"), true);
                nowRecovery.Text = enabled ? S("overview.on", "on") : S("overview.off", "paused");
                object running = Get(status, "watcher_running");
                string watcherText = running == null ? S("diag.unknown", "unknown")
                                   : !Equals(running, true) ? S("diag.not_running", "not running")
                                   : Equals(Get(watcher, "ticking"), false) ? S("diag.not_responding", "not responding")
                                   : S("diag.running", "running");
                string engine = Str(watcher, "engine_state") ?? "unknown";
                string engineText = S("engine." + engine, engine);
                double last = Number(watcher, "last_tick_at");
                nowWatcher.Text = watcherText;
                nowEngine.Text = engineText;
                nowLastCheck.Text = Ago(last);
                diagVersion.Text = "v" + Convert.ToString(Get(status, "version"), CultureInfo.InvariantCulture);
                diagWatcher.Text = watcherText;
                diagEngine.Text = engineText;
                diagLastCheck.Text = Ago(last);
                diagRecovery.Text = nowRecovery.Text;
                diagStartup.Text = Equals(Get(status, "startup_enabled"), true) ? S("diag.yes", "yes") : S("diag.no", "no");
                diagUpgrade.Text = upgrade ? S("diag.upgrade_pending", "An older watcher still owns the state") : "";
            }
            UpdateToggle();

            // A part that could not be read is shown as unreadable, never as empty. "Nothing
            // is waiting" over a list that could not be read is the one wrong answer this page
            // must not give - recoveries may well be waiting, and an older watcher may still
            // be sending them.
            string unreadable = upgrade ? S("diag.upgrade_pending", "An older watcher still owns the state")
                                        : S("pending.unavailable", "This cannot be read right now");
            var week = Map(reply, "week");
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
            if (reply.ContainsKey("pending_error")) ShowUnreadable(pendingList, pendingEmpty, unreadable);
            else
            {
                FillList(pendingList, Items(reply, "pending"), true);
                pendingEmpty.Text = S("pending.empty", "Nothing is waiting");
                pendingEmpty.Visible = pendingList.Items.Count == 0;
            }
            if (reply.ContainsKey("history_error"))
            {
                ShowUnreadable(historyList, historyEmpty, unreadable);
                ClearRecent(unreadable);
            }
            else
            {
                FillList(historyList, Items(reply, "history"), false);
                FillRecent(Items(reply, "history"));
                historyEmpty.Text = S("history.empty", "No recoveries yet");
                historyEmpty.Visible = historyList.Items.Count == 0;
            }
            // A Retry now note belongs to one record; once that record has left Pending -
            // sent, finished or cancelled - the note no longer describes anything on screen.
            if (pendingNoteFor != null && !Contains(pendingList, pendingNoteFor)) pendingNoteFor = null;
            ShowPendingNote();
            UpdateCountdowns();
            UpdatePendingButtons();
            UpdateHistoryButtons();
        }

        private void ShowUnreadable(ListView list, Label empty, string reason)
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
            dotColor = Idle;
            headline.Text = S("status.unavailable", "Status unavailable");
            detail.Text = S("status.unavailable_detail", "Settings can still be changed and saved");
            header.Invalidate(true);
            string unknown = S("diag.unknown", "unknown");
            foreach (Label label in new[] { nowRecovery, nowWatcher, nowEngine, nowLastCheck,
                                            diagWatcher, diagEngine, diagLastCheck, diagRecovery })
                label.Text = unknown;
            string unreadable = S("pending.unavailable", "This cannot be read right now");
            ShowUnreadable(pendingList, pendingEmpty, unreadable);
            ShowUnreadable(historyList, historyEmpty, unreadable);
            ClearRecent(unreadable);
            waitingLine.Text = unreadable;
            nextLine.Text = "";
            runningLine.Text = "";
            // The week's figures and the Statistics page are read the same way and have
            // failed the same way; left as they were, they would be the last good answer
            // under a header that says the state cannot be read.
            weekDetected.Text = weekSent.Text = weekRecovered.Text = weekSuccess.Text = "-";
            MarkStatisticsUnavailable();
            pendingNoteFor = null;
            SetNote(pendingNote, "");
            UpdatePendingButtons();
            UpdateHistoryButtons();
            UpdateToggle();
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
                          ((int)Number(row, "recovery_attempts")).ToString(CultureInfo.CurrentCulture) }
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
            if (snapshot.ContainsKey("pending_error"))
            {
                waitingLine.Text = pendingEmpty.Text;
                nextLine.Text = "";
                runningLine.Text = "";
                return;
            }
            double now = Now();
            var status = Map(snapshot, "status");
            var pending = Items(snapshot, "pending");
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
            waitingLine.Text = waiting == 0 && running == 0 ? S("overview.none_waiting", "Nothing is waiting to be recovered")
                             : S("overview.waiting_count", "{n} waiting", "n", waiting);
            nextLine.Text = !(waiting > 0 && enabled && next > 0) ? ""
                : next <= now ? S("overview.due", "Due to be checked now")
                : S("overview.next", "Next check in {time}", "time", Countdown(next - now));
            runningLine.Text = running > 0 ? S("overview.running_count", "{n} running in Codex", "n", running) : "";
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
            var chosen = Selected(pendingList);
            bool mine = pendingNoteFor != null && chosen != null &&
                        Str(chosen, "interruption_id") == pendingNoteFor;
            SetNote(pendingNote, mine ? pendingNoteText : "");
        }

        private void UpdatePendingButtons()
        {
            var row = Selected(pendingList);
            bool idle = busy == 0;
            string code = Str(row, "code");
            bool cancelled = Equals(Get(row, "cancel_requested"), true);
            bool waiting = code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" ||
                           code == "scheduled" || code == "failed_retryable";
            // Retry now brings the check forward. It never moves past a usage reset that is
            // still ahead, and never past a pause or a conversation that is switched off; where
            // it could do none of that it is not offered. A reset that has passed, or one that
            // is unknown, is exactly where it helps.
            bool resetAhead = Number(row, "reset_at") > Now();
            bool consentHeld = HasOverlay(row, "paused") || HasOverlay(row, "thread_disabled");
            retryButton.Enabled = idle && waiting && !cancelled && !resetAhead && !consentHeld;
            cancelButton.Enabled = idle && row != null && !cancelled;
            timelineButton.Enabled = idle && row != null;
            threadButton.Enabled = idle && row != null;
            string text = ThreadOn(row) ? S("action.thread_off", "Turn off for this conversation")
                                        : S("action.thread_on", "Turn on for this conversation");
            if (threadButton.Text != text) threadButton.Text = text;
        }

        private void UpdateHistoryButtons()
        {
            var row = Selected(historyList);
            bool idle = busy == 0;
            historyTimeline.Enabled = idle && row != null;
            bool exhausted = Str(row, "code") == "exhausted" && !Equals(Get(row, "cancel_requested"), true);
            // Offered only while it can succeed: the store gives attempts back a limited number
            // of times, and a button that is certain to be refused is not an action.
            bool resetsLeft = Number(row, "budget_resets_left") > 0;
            historyReset.Enabled = idle && exhausted && resetsLeft;
            SetNote(historyNote, exhausted && !resetsLeft
                ? S("history.reset_limit", "Its attempts were already given back as many times as allowed; continue this task in Codex yourself.")
                : "");
            bool off = row != null && !ThreadOn(row);
            if (historyThread.Visible != off) historyThread.Visible = off;
            historyThread.Enabled = idle && off;
            historyClear.Enabled = idle && historyList.Items.Count > 0;
        }

        private void UpdateToggle()
        {
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
            // A sentence in the window's own language first. The detail after it comes from
            // the local service, which speaks English; it stays because it is what a bug
            // report needs.
            string reason = Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture);
            MessageBox.Show(this, S("action.failed", "That could not be done.") +
                                  (string.IsNullOrEmpty(reason) ? "" : Environment.NewLine + Environment.NewLine + reason),
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
            Send("reset-budget", IdArgument(row));
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
                padding.Controls.Add(view);
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

        private void OpenLogs()
        {
            string logs = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs");
            if (!Directory.Exists(logs)) return;
            try { Process.Start("explorer.exe", "\"" + logs + "\""); }
            catch (Exception error) { Report(Failure(error)); }
        }

        private void Repair()
        {
            if (!Confirm(S("confirm.repair", "Run setup again to repair the Windows registrations?"))) return;
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string python = Path.Combine(root, "runtime", "python.exe");
            string setup = Path.Combine(root, "app", "scripts", "plugin_setup.py");
            if (!File.Exists(python) || !File.Exists(setup))
            {
                MessageBox.Show(this, S("diag.repair_failed", "Setup did not finish."), "Codex Auto Resume",
                                MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            SetBusy(true);
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                bool ok = false;
                try
                {
                    // --keep-state: repair repairs. It re-registers what is broken and starts a
                    // stopped watcher, and never undoes a pause or adds back a sign-in start the
                    // person switched off - a plain `setup` does both, as a first install should.
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
                        // Both pipes drained concurrently, so neither can fill and stall the other.
                        Task<string> error = process.StandardError.ReadToEndAsync();
                        string output = process.StandardOutput.ReadToEnd();
                        error.Wait(120000);
                        process.WaitForExit(120000);
                        // 2 means everything was done but the watcher was not yet seen
                        // running - and it is also what an older setup exits with when it
                        // rejects an argument it does not know, such as --keep-state. So a
                        // 2 counts only with the line setup prints when it has finished its
                        // work; "Setup finished" over a setup that never ran is worse than
                        // saying it failed.
                        ok = process.HasExited &&
                             (process.ExitCode == 0 ||
                              (process.ExitCode == 2 && output.IndexOf("state: ", StringComparison.Ordinal) >= 0));
                    }
                }
                catch (Exception) { ok = false; }
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    MessageBox.Show(this, ok ? S("diag.repair_done", "Setup finished.")
                                             : S("diag.repair_failed", "Setup did not finish."),
                                    "Codex Auto Resume", MessageBoxButtons.OK,
                                    ok ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
                    RefreshAfterChange();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }
    }
}

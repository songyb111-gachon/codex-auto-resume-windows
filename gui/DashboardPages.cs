// Codex Auto Resume - what each Dashboard page is built out of.
//
// The Overview and its four cards, with the row fitting that keeps them on a 1920 by 1080
// screen at 150%; then Pending, History, Statistics and Diagnostics.

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
    internal sealed partial class SettingsForm
    {
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
            // Each bar in its outcome's own colour, as History draws the outcome's word (OutcomeChart.Bar).
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
    }
}

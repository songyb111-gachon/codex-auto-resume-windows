// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the advanced edition's own page of the Dashboard: Advanced features.
//
// Every capability of this edition starts off, and stays off until a person turns it on - or has it
// watched first - one at a time, here and nowhere else, after reading its statement (the owner's rules of
// 2026-09-26). The bridge refuses every other actor (advanced/src/codex_auto_resume_advanced/arming.py);
// this page is the Dashboard that rule names. It lists every capability in the registry's order, one flat
// row each - its name and its state in the registry's words - and the one that is open shows its statement
// in the person's language, what an administrator's Windows policy refuses of it, the warnings its statement
// carries now, and its limits, with the one limit a person may set: lower, and never above the registry's.
//
// Its place is after Settings, the last tab. The Dashboard's pages are gui/Dashboard.cs's PageOrder, and the
// window's navigation is that one strip of tabs: nothing in it is a place for an edition's page, and a Settings
// section would not do - the Settings page is saved with its Save button and is never read again under a person
// editing it, where this page acts at once and follows every read. A tab after the last moves none of the
// standard ones: the six keep the places they have in the standard window, and Ctrl+Tab goes on from Settings to
// this page and back to the Overview (ProcessCmdKey). The tab shows once this edition has answered with its
// words, which are its own catalogs' and not core's (the bridge's advanced-words); an installation whose
// advanced package could not be loaded answers nothing, and shows no page it could not act on.
//
// The page is built as Pending is, from the same parts: the list on its card, flat rows with a hairline between
// them and the state in its chip; beside it, the open capability's cards in a column that scrolls, as the
// Settings page's sections stand beside their list, made of the Settings page's cards, captions, help lines and
// rows, with what a policy refuses in the accent as Diagnostics says what needs noticing; and under both, the row
// of buttons that act on the chosen row, with what the last action did beside them. The window's own dialog asks.
// Nothing here draws anything the standard window does not draw.
//
// Turning a capability on, or watching it, asks first, in the window's own dialog, with the statement and every
// warning it carries (ArmQuestion); the safe answer is the default, so only the button that names the action says
// yes. What is sent is exactly what was shown - the generation the page read the list at, the statement's
// revision, its warnings and the Codex version it named (ArmArgument) - and when the bridge answers that something
// changed since, the page reads the list and the statement again and asks again, with what holds now. Turning off
// asks nothing: it only ever does less.
//
// advanced/gui/AdvancedPageAudit.cs is this page's audit, and the hooks its tests drive it through.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // ---------------------------------------------------------------- state
        // The page's name among the Dashboard's (currentPage, navButtons).
        private const string AdvancedPageName = "advanced";
        // The states, in the registry's words (vocabulary.ArmingState).
        private const string StateOff = "off", StateShadow = "shadow", StateArmed = "armed";
        // The list's column, in logical pixels, at the window's opening width and wider; narrower, it gives way to the
        // open capability's cards down to what its rows need (ShareAdvanced).
        private const int AdvancedListWidth = 360;
        // How many times a statement that changed while it was being read is shown again before the page stops
        // asking and says so.
        private const int AdvancedAsks = 3;
        // How long the hourly limit waits after the last change of its choice before it is sent: a keyboard that
        // walks through the choices sends the one it stops on.
        private const int HourlyPause = 700;

        private NavButton advancedTab;
        private Control advancedPage;
        private ListView advancedList;
        private Control advancedListCard;
        private TableLayoutPanel advancedSplit;
        private SoftPage advancedScroll;
        private TableLayoutPanel advancedStack;
        private NoteLabel advancedNote;
        private Button advancedOn, advancedWatch, advancedOff, advancedAllOff;
        private SoftCombo advancedHourly;
        private Timer hourlyTimer;
        // The hourly limit the person stopped on, which the pause sends whatever the cards were rebuilt to meanwhile.
        private int hourlyChosen;
        // The page's words (advanced-words): null until this edition has answered, and the tab shows only then.
        private Dictionary<string, object> advancedWords;
        // The list as last read (advanced-list's answer), or null when it could not be read.
        private Dictionary<string, object> advancedListing;
        // Each capability's statement as last read, in the person's language.
        private readonly Dictionary<string, Dictionary<string, object>> advancedStatements =
            new Dictionary<string, Dictionary<string, object>>();
        // The capability whose cards are showing; what they were built from; the status's `advanced` as last seen.
        private string advancedOpen, advancedShown, advancedBadge;
        private bool advancedAsking, advancedReading, advancedReadAgain, advancedFilling, hourlyFilling;
        // What waits for the read in flight to finish, in order (ReadAdvanced).
        private readonly List<MethodInvoker> advancedThen = new List<MethodInvoker>();

        // ---------------------------------------------------------------- joining the window
        partial void DashboardBuilt()
        {
            NavButton settings;
            if (!navButtons.TryGetValue("settings", out settings) || settings.Parent == null) return;
            // A tab as BuildDashboard makes each of its own, at the end of the same strip, hidden until the words.
            var tab = new NavButton();
            tab.Font = Soft.RoleFont("nav");
            tab.AutoSize = true;
            tab.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            tab.FlatStyle = FlatStyle.Flat;
            tab.FlatAppearance.BorderSize = 0;
            tab.ForeColor = Secondary;
            tab.Padding = settings.Padding;
            tab.Margin = settings.Margin;
            tab.Cursor = Cursors.Hand;
            tab.UseVisualStyleBackColor = false;
            tab.Visible = false;
            tab.Click += delegate { ShowAdvanced(); };
            settings.Parent.Controls.Add(tab);
            navButtons[AdvancedPageName] = tab;
            advancedTab = tab;
            // Asked once the window opens, as its other reads are; a window the layout audit builds never opens.
            Load += delegate { if (!auditing) ReadAdvancedWords(); };
        }

        partial void SnapshotApplied(Dictionary<string, object> reply)
        {
            if (reply == null) return;
            if (advancedWords == null)
            {
                // Until this edition has answered: asked again with each read, as the window's reads go on.
                ReadAdvancedWords();
                return;
            }
            // The status carries this edition's badge (surfaces.badge): a change there is a capability turned on or
            // off, here or anywhere, and the list is read again. While the page is on screen it follows every read.
            string badge = AdvancedWritten(Map(Map(reply, "status"), "advanced"));
            bool changed = badge != advancedBadge;
            advancedBadge = badge;
            if (changed || currentPage == AdvancedPageName) ReadAdvanced(null);
        }

        /// Ctrl+Tab from Settings comes here, and from here goes on to the Overview; Ctrl+Shift+Tab the other way. Every
        /// other key, and every other page's Ctrl+Tab, is the standard window's (BuildDashboard).
        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (advancedWords != null && advancedTab != null && (keyData & ~Keys.Shift) == (Keys.Control | Keys.Tab))
            {
                bool back = (keyData & Keys.Shift) == Keys.Shift;
                string first = PageOrder[0], last = PageOrder[PageOrder.Length - 1];
                if (currentPage == AdvancedPageName)
                {
                    ShowPage(back ? last : first);
                    return true;
                }
                if (currentPage == (back ? first : last))
                {
                    ShowAdvanced();
                    return true;
                }
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        // ---------------------------------------------------------------- words
        /// One of this page's words, in the person's language, or `fallback` before this edition has answered.
        private string Word(string key, string fallback)
        {
            object value;
            if (advancedWords != null && advancedWords.TryGetValue(key, out value) && value is string && ((string)value).Length > 0)
                return (string)value;
            return fallback;
        }

        private string Word(string key, string fallback, string token, object replacement)
        {
            return Word(key, fallback).Replace("{" + token + "}", Convert.ToString(replacement, CultureInfo.CurrentCulture));
        }

        /// A capability's name as the page lists it; its id where no catalog has one.
        private string AdvancedName(string id)
        {
            return Word("name." + id, id ?? "");
        }

        /// A state in the registry's words: Off, Watching, On.
        private string StateWord(string state)
        {
            if (state == StateArmed) return Word("state.armed", "On");
            if (state == StateShadow) return Word("state.shadow", "Watching");
            return Word("state.off", "Off");
        }

        /// The colour a state's chip is drawn in, always beside its word: on as a recovery that worked, watched as
        /// what is waiting, off as what is deliberately quiet.
        private static Color StateTone(string state)
        {
            if (state == StateArmed) return Palette.Success;
            if (state == StateShadow) return Palette.Waiting;
            return Palette.Paused;
        }

        /// This page's words from advanced-words, and the tab that shows it with them.
        private void AdoptAdvancedWords(Dictionary<string, object> words)
        {
            if (words == null) return;
            advancedWords = words;
            if (advancedTab == null) return;
            advancedTab.Text = Word("page.nav", "Advanced features");
            advancedTab.AccessibleName = advancedTab.Text;
            advancedTab.Visible = true;
            HoldTabs();
        }

        /// The window no narrower than its tabs, this page's among them. The strip neither wraps nor scrolls, and in some
        /// languages the standard six fill nearly all of the standard window's narrowest width (800), so a seventh
        /// would be cut off there: the narrowest this window goes is as wide as the strip, and never wider than the
        /// screen it is on (KeepOnScreen). A window narrower than that is made that wide.
        private void HoldTabs()
        {
            Control strip = advancedTab == null ? null : advancedTab.Parent;
            if (strip == null) return;
            // The strip as it is now, less what the chosen tab's heavier words add to it, plus the most any tab's would:
            // whichever page is on screen, its tab is set in nav_current (ShowPage).
            int now = 0, heaviest = 0;
            var any = new Size(int.MaxValue, int.MaxValue);
            foreach (Control control in strip.Controls)
            {
                var tab = control as NavButton;
                if (tab == null) continue;
                int regular = TextRenderer.MeasureText(tab.Text, Soft.RoleFont("nav"), any, TextFormatFlags.SingleLine).Width;
                now += TextRenderer.MeasureText(tab.Text, tab.Font, any, TextFormatFlags.SingleLine).Width - regular;
                heaviest = Math.Max(heaviest, TextRenderer.MeasureText(tab.Text, Soft.RoleFont("nav_current"), any,
                                                                       TextFormatFlags.SingleLine).Width - regular);
            }
            int least = strip.PreferredSize.Width - now + heaviest + nav.Padding.Horizontal + (Width - ClientSize.Width);
            try { least = Math.Min(least, Screen.FromControl(this).WorkingArea.Width); }
            catch (Exception) { }
            if (MinimumSize.Width < least) MinimumSize = new Size(least, MinimumSize.Height);
        }

        // ---------------------------------------------------------------- showing the page
        private void ShowAdvanced()
        {
            if (advancedWords == null) return;
            currentPage = AdvancedPageName;
            // As ShowPage shows a page: painting held while one page is hidden and this one shown, every page staying
            // in the host once built.
            bool paused = Redraw(pageHost, false);
            try
            {
                Control page = AdvancedPageBuilt();
                pageHost.SuspendLayout();
                foreach (Control other in pageHost.Controls)
                    if (other != page) other.Visible = false;
                page.SuspendLayout();
                page.Visible = true;
                page.ResumeLayout(true);
                pageHost.ResumeLayout(false);
                pageHost.PerformLayout();
                foreach (var pair in navButtons)
                {
                    bool here = pair.Key == AdvancedPageName;
                    pair.Value.ForeColor = here ? Ink : Secondary;
                    pair.Value.Font = Soft.RoleFont(here ? "nav_current" : "nav");
                    pair.Value.Current = here;
                }
                if (saveButton != null) saveButton.Visible = false;
                if (restoreButton != null) restoreButton.Visible = false;
            }
            finally
            {
                if (paused) Redraw(pageHost, true);
            }
            FitAdvancedStack();
            UpdateAdvancedButtons();
            if (Offline) return;
            ReadAdvanced(null);
            if (advancedScript == null && (snapshot == null || snapshotAge.ElapsedMilliseconds >= FreshMilliseconds)) RefreshNow();
        }

        /// Whether nothing is to be read: a window the layout audit builds, with no replies of a test's to read.
        private bool Offline
        {
            get { return auditing && advancedScript == null; }
        }

        /// The page, built the first time it is shown, as the standard pages are (PageFor).
        private Control AdvancedPageBuilt()
        {
            if (advancedPage != null) return advancedPage;
            var page = (SoftPage)Page();
            // The list's card on the page, and the open capability's cards in a column that scrolls, which keeps the
            // room for their lift itself, as a Settings section does: so the page keeps it only where the list's card
            // is, and the two cards' tops are level.
            Padding room = CardRoom();
            page.Padding = new Padding(room.Left, 0, 0, room.Bottom);

            advancedList = List(Word("page.nav", "Advanced features"),
                                Col(Word("page.col_feature", "Feature"), 220),
                                Col(Word("page.col_state", "State"), 120));
            // Its state chip in the state's own colour (DrawAdvancedCell); every other cell as every list's.
            advancedList.DrawSubItem -= DrawCell;
            advancedList.DrawSubItem += DrawAdvancedCell;
            advancedList.SelectedIndexChanged += delegate
            {
                if (advancedFilling) return;
                string chosen = SelectedAdvanced();
                if (chosen != null) OpenAdvanced(chosen);
                // Nothing chosen - a click under the rows, or the moment between one row and the next - leaves the open
                // capability chosen, once the list has finished choosing: its cards are what the buttons act on, and
                // the list says which it is.
                else if (IsHandleCreated)
                    BeginInvoke(new MethodInvoker(delegate { if (SelectedAdvanced() == null) FillAdvancedList(); }));
            };
            Control listCard = ListCard(advancedList);
            listCard.Margin = new Padding(0, room.Top, 0, 0);
            advancedListCard = listCard;

            var stack = new SoftStack();
            // Not docked, and as wide as its column less a scroll bar whether or not one shows (FitAdvancedStack),
            // as a Settings section is (FitSections).
            stack.Location = Point.Empty;
            stack.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            stack.ColumnCount = 1;
            stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            stack.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            stack.AutoSize = true;
            stack.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            stack.Font = Font;
            stack.Padding = new Padding(room.Left, room.Top, room.Right, Math.Max(0, room.Bottom - Px(Brand.PageGap)));
            advancedStack = stack;
            var scroll = new SoftPage();
            scroll.Dock = DockStyle.Fill;
            scroll.Margin = new Padding(0);
            scroll.Controls.Add(stack);
            scroll.Scrolls = true;
            scroll.SizeChanged += delegate { FitAdvancedStack(); };
            advancedScroll = scroll;

            var split = new SoftStack();
            split.Dock = DockStyle.Fill;
            split.ColumnCount = 2;
            split.RowCount = 1;
            split.Margin = new Padding(0);
            split.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(AdvancedListWidth)));
            split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            split.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            split.Controls.Add(listCard, 0, 0);
            split.Controls.Add(scroll, 1, 0);
            advancedSplit = split;
            split.SizeChanged += delegate { ShareAdvanced(); };

            // Under both, as Pending's are under its list: what can be done with the chosen row, then what can only
            // reduce what runs, for all of it - and what the last action did, in words, until the next.
            FlowLayoutPanel row = ButtonRow();
            advancedOn = MakeButton(Word("page.turn_on", "Turn on"), false, delegate { ArmAdvanced(advancedOpen, StateArmed, 0); });
            advancedWatch = MakeButton(Word("page.watch", "Watch first"), false, delegate { ArmAdvanced(advancedOpen, StateShadow, 0); });
            advancedOff = MakeButton(Word("page.turn_off", "Turn off"), false, delegate { DisarmAdvanced(advancedOpen); });
            advancedAllOff = MakeButton(Word("page.all_off", "Turn every advanced feature off"), false, delegate { AllOffAdvanced(); });
            foreach (Button button in new[] { advancedOn, advancedWatch, advancedOff, advancedAllOff })
            {
                button.Margin = Pad(0, 0, 9, 0);
                row.Controls.Add(button);
            }
            advancedNote = Note();
            row.Controls.Add(advancedNote);

            page.Controls.Add(split);
            page.Controls.Add(row);
            page.Visible = false;
            pageHost.Controls.Add(page);
            advancedPage = page;
            FitAdvancedStack();
            FillAdvancedList();
            ShowAdvancedDetail();
            return page;
        }

        /// The list's column: AdvancedListWidth at the window's opening width and wider, and in a narrower window three
        /// eighths of the page, down to what its rows and headings need whole - the cards beside it are what is read,
        /// and a narrow window left them too little room for a limit's value beside its name (as Pending's
        /// explanation gives way to its list's headings).
        private void ShareAdvanced()
        {
            if (advancedSplit == null || advancedList == null || advancedListCard == null) return;
            int[] cells;
            cellWidths.TryGetValue(advancedList, out cells);
            int needed = advancedListCard.Padding.Horizontal;
            for (int i = 0; i < advancedList.Columns.Count; i++)
                needed += Math.Max(HeadingWidth(advancedList, i), cells != null && i < cells.Length ? cells[i] : 0);
            int width = Math.Max(needed, Math.Min(Px(AdvancedListWidth), advancedSplit.ClientSize.Width * 3 / 8));
            width = Math.Min(width, Px(AdvancedListWidth));
            if ((int)advancedSplit.ColumnStyles[0].Width != width) advancedSplit.ColumnStyles[0].Width = width;
        }

        /// The open capability's column as wide as it is less the scroll bar's gutter, whether or not the bar shows,
        /// so its cards are laid out again only when the window's width changes (FitSections).
        private void FitAdvancedStack()
        {
            if (advancedScroll == null || advancedStack == null) return;
            int width = advancedScroll.Width - SoftBar.Gutter;
            if (width <= Px(160)) return;
            if (advancedStack.MinimumSize.Width == width && advancedStack.MaximumSize.Width == width) return;
            // In the order that never has the minimum above the maximum.
            if (width < advancedStack.MinimumSize.Width)
            {
                advancedStack.MinimumSize = new Size(width, 0);
                advancedStack.MaximumSize = new Size(width, 0);
            }
            else
            {
                advancedStack.MaximumSize = new Size(width, 0);
                advancedStack.MinimumSize = new Size(width, 0);
            }
        }

        // ---------------------------------------------------------------- reading
        private void ReadAdvancedWords()
        {
            if (advancedAsking || advancedWords != null) return;
            advancedAsking = true;
            AdvancedCall("advanced-words", LocaleArgument(null), false, delegate(Dictionary<string, object> reply)
            {
                advancedAsking = false;
                Dictionary<string, object> result = AdvancedResult(reply);
                if (!AdvancedDone(result)) return;
                AdoptAdvancedWords(Map(result, "words"));
                ReadAdvanced(null);
            });
        }

        /// The list, and then the open capability's statement, read again; `then` once both have been shown. One read
        /// at a time: asked for during one, it is made again when that one ends, and everything waiting runs after it.
        private void ReadAdvanced(MethodInvoker then)
        {
            if (advancedWords == null) return;
            if (then != null) advancedThen.Add(then);
            if (advancedReading)
            {
                advancedReadAgain = true;
                return;
            }
            advancedReading = true;
            advancedReadAgain = false;
            AdvancedCall("advanced-list", "{}", false, delegate(Dictionary<string, object> reply)
            {
                ShowAdvancedList(AdvancedResult(reply));
                string id = advancedOpen;
                if (id == null || advancedListing == null)
                {
                    AdvancedReadDone();
                    return;
                }
                AdvancedCall("advanced-statement", LocaleArgument(id), false, delegate(Dictionary<string, object> answer)
                {
                    ShowAdvancedStatement(id, AdvancedResult(answer));
                    AdvancedReadDone();
                });
            });
        }

        private void AdvancedReadDone()
        {
            advancedReading = false;
            if (advancedReadAgain)
            {
                ReadAdvanced(null);
                return;
            }
            var waiting = new List<MethodInvoker>(advancedThen);
            advancedThen.Clear();
            foreach (MethodInvoker next in waiting) next();
        }

        /// A list as advanced-list answers it, or null where it could not be read: shown, with the first capability
        /// open when none is.
        private void ShowAdvancedList(Dictionary<string, object> result)
        {
            bool read = AdvancedDone(result) && Items(result, "capabilities") != null;
            advancedListing = read ? result : null;
            if (read && AdvancedItem(advancedOpen) == null)
            {
                advancedOpen = null;
                foreach (object entry in Items(result, "capabilities"))
                {
                    advancedOpen = Str(entry as Dictionary<string, object>, "id");
                    if (advancedOpen != null) break;
                }
            }
            FillAdvancedList();
            ShowAdvancedDetail();
        }

        /// A statement as advanced-statement answers it; one that could not be read is none, and nothing can be turned
        /// on or watched from a statement nobody has read.
        private void ShowAdvancedStatement(string id, Dictionary<string, object> result)
        {
            if (AdvancedDone(result) && Str(result, "capability") == id) advancedStatements[id] = result;
            else advancedStatements.Remove(id);
            ShowAdvancedDetail();
        }

        /// The capability the list holds under `id`, as last read, or null.
        private Dictionary<string, object> AdvancedItem(string id)
        {
            if (id == null) return null;
            foreach (object entry in Items(advancedListing, "capabilities") ?? new List<object>())
            {
                var item = entry as Dictionary<string, object>;
                if (Str(item, "id") == id) return item;
            }
            return null;
        }

        private Dictionary<string, object> AdvancedStatement(string id)
        {
            Dictionary<string, object> statement;
            return id != null && advancedStatements.TryGetValue(id, out statement) ? statement : null;
        }

        private string SelectedAdvanced()
        {
            if (advancedList == null || advancedList.SelectedItems.Count == 0) return null;
            return Str(advancedList.SelectedItems[0].Tag as Dictionary<string, object>, "id");
        }

        private void OpenAdvanced(string id)
        {
            if (id == null || id == advancedOpen) return;
            advancedOpen = id;
            ShowAdvancedDetail();
            if (!Offline) ReadAdvanced(null);
        }

        // ---------------------------------------------------------------- the list
        /// Every capability in the registry's order, one row each: its name, and its state in a chip. Rows are only
        /// rewritten where they changed, so the selection and the focus stay where the person left them.
        private void FillAdvancedList()
        {
            if (advancedList == null) return;
            var rows = new List<Dictionary<string, object>>();
            foreach (object entry in Items(advancedListing, "capabilities") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                if (row != null && Str(row, "id") != null) rows.Add(row);
            }
            advancedFilling = true;
            try
            {
                bool same = advancedList.Items.Count == rows.Count;
                for (int i = 0; same && i < rows.Count; i++)
                    same = Str(advancedList.Items[i].Tag as Dictionary<string, object>, "id") == Str(rows[i], "id");
                if (!same)
                {
                    advancedList.BeginUpdate();
                    advancedList.Items.Clear();
                    foreach (var row in rows)
                    {
                        var item = new ListViewItem(AdvancedName(Str(row, "id")));
                        item.SubItems.Add(StateWord(Str(row, "state")));
                        item.Tag = row;
                        advancedList.Items.Add(item);
                    }
                    advancedList.EndUpdate();
                }
                else
                {
                    for (int i = 0; i < rows.Count; i++)
                    {
                        ListViewItem item = advancedList.Items[i];
                        item.Tag = rows[i];
                        string state = StateWord(Str(rows[i], "state"));
                        if (item.SubItems[1].Text != state) item.SubItems[1].Text = state;
                    }
                    advancedList.Invalidate();
                }
                foreach (ListViewItem item in advancedList.Items)
                {
                    bool open = Str(item.Tag as Dictionary<string, object>, "id") == advancedOpen;
                    if (item.Selected != open) item.Selected = open;
                    if (open && advancedList.FocusedItem == null) item.Focused = true;
                }
                MeasureCells(advancedList);
            }
            finally
            {
                advancedFilling = false;
            }
            ShareAdvanced();
        }

        /// A row's cell as every list's (DrawCell), but the state's chip in the state's own colour.
        private void DrawAdvancedCell(object sender, DrawListViewSubItemEventArgs e)
        {
            var row = e.Item.Tag as Dictionary<string, object>;
            if (e.ColumnIndex != 1 || row == null)
            {
                DrawCell(sender, e);
                return;
            }
            var list = (ListView)sender;
            bool selected = e.Item.Selected;
            Color back = !selected ? Card : Palette.Contrast ? Palette.AccentSoft : Palette.Inset;
            e.Graphics.FillRectangle(Soft.Fill(back), e.Bounds);
            e.Graphics.FillRectangle(Soft.Fill(Line), e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline, e.Bounds.Width, Soft.Hairline);
            var cell = new Rectangle(e.Bounds.X + Px(10), e.Bounds.Y, Math.Max(0, e.Bounds.Width - Px(14)), e.Bounds.Height);
            Color tone = Palette.Contrast && selected ? SystemColors.HighlightText : StateTone(Str(row, "state"));
            Soft.Chip(e.Graphics, cell, e.SubItem == null ? "" : e.SubItem.Text, list.Font, tone, back);
        }

        // ---------------------------------------------------------------- the open capability
        /// The open capability's cards, built again only when what they show changed.
        private void ShowAdvancedDetail()
        {
            if (advancedStack == null) return;
            Dictionary<string, object> item = AdvancedItem(advancedOpen);
            Dictionary<string, object> statement = item == null ? null : AdvancedStatement(advancedOpen);
            string shown = (advancedListing == null ? "unread" : "read") + "|" + AdvancedWritten(item) + "|" +
                           AdvancedWritten(statement) + "|" + AdvancedWritten(Get(advancedListing, "policy")) + "|" +
                           AdvancedWritten(Get(advancedListing, "global_hourly"));
            if (shown == advancedShown)
            {
                UpdateAdvancedButtons();
                return;
            }
            advancedShown = shown;
            bool focused = advancedStack.ContainsFocus;
            advancedStack.SuspendLayout();
            var old = new List<Control>();
            foreach (Control control in advancedStack.Controls) old.Add(control);
            advancedStack.Controls.Clear();
            foreach (Control control in old) control.Dispose();
            advancedStack.RowStyles.Clear();
            advancedHourly = null;
            if (item == null)
            {
                TableLayoutPanel card = NewGroup(Word("page.nav", "Advanced features"), advancedStack);
                card.Controls.Add(HelpText(advancedListing == null ? Word("page.unavailable", "The advanced features cannot be read right now.")
                                                                    : Word("page.choose", "Choose a feature to read what it does.")));
            }
            else BuildAdvancedCards(item, statement);
            advancedStack.ResumeLayout(true);
            if (advancedScroll != null) advancedScroll.PerformLayout();
            UpdateAdvancedButtons();
            // A limit that was being chosen is gone with the cards it was on: the keyboard goes back to the list.
            if (focused && advancedList != null && advancedList.CanFocus) advancedList.Focus();
        }

        private void BuildAdvancedCards(Dictionary<string, object> item, Dictionary<string, object> statement)
        {
            string id = Str(item, "id");
            // Its name and where it stands; what an administrator refuses of it; and what its statement warns of now.
            TableLayoutPanel head = NewGroup(AdvancedName(id), advancedStack);
            TableLayoutPanel facts = Facts(head);
            Fact(facts, Word("page.col_state", "State")).Text = StateWord(Str(item, "state"));
            // What an administrator's policy refuses, in the accent, as Diagnostics says what needs noticing under its facts
            // (diagUpgrade, diagPlugin). Lines rather than callouts: a callout holds each of its words whole, and this
            // column is narrower than the compatibility card's, where a sentence of Japanese - one word to it - fits.
            string refused = PolicyRefusal(id);
            if (refused != null)
            {
                Label line = HelpText(refused);
                line.ForeColor = Accent;
                line.Margin = Pad(0, Brand.SpaceS, 0, 0);
                head.Controls.Add(line);
            }
            // Each warning under their title, as a field of the statement is under its own, and the note that none of
            // them stops the person under them.
            Dictionary<string, object> warnings = Map(statement, "warnings");
            List<object> said = Items(warnings, "items");
            if (said != null && said.Count > 0)
            {
                head.Controls.Add(Caption(Str(warnings, "title") ?? "Warnings"));
                foreach (object entry in said)
                {
                    var warning = entry as Dictionary<string, object>;
                    string text = Str(warning, "text") ?? Str(warning, "warning");
                    if (string.IsNullOrEmpty(text)) continue;
                    Label line = HelpText(text);
                    line.ForeColor = Ink;
                    line.Margin = Pad(0, 2, 0, 4);
                    head.Controls.Add(line);
                }
                string note = Str(warnings, "note");
                if (!string.IsNullOrEmpty(note)) head.Controls.Add(HelpText(note));
            }

            // Its statement: the five fields, each under its title, in the person's language - the standards it departs
            // from among them, glossed in words.
            if (statement != null)
            {
                TableLayoutPanel about = NewGroup(Word("page.about", "About this feature"), advancedStack);
                bool first = true;
                foreach (object entry in Items(statement, "fields") ?? new List<object>())
                {
                    var field = entry as Dictionary<string, object>;
                    string title = Str(field, "title"), text = Str(field, "text");
                    if (string.IsNullOrEmpty(text)) continue;
                    Label caption = Caption(title ?? "");
                    if (first) caption.Margin = Pad(0, 0, 0, 4);
                    first = false;
                    Label body = HelpText(text);
                    body.ForeColor = Ink;
                    about.Controls.Add(caption);
                    about.Controls.Add(body);
                }
            }

            // Its limits, and the one a person may set for every capability together: lower, never above the registry's.
            TableLayoutPanel limits = NewGroup(Word("page.limits", "Limits"), advancedStack);
            TableLayoutPanel numbers = Facts(limits);
            Dictionary<string, object> ceilings = Map(item, "ceilings");
            Fact(numbers, Word("page.per_day", "Sends a day, all conversations together")).Text = CeilingText(Get(ceilings, "per_day"));
            Fact(numbers, Word("page.per_conversation", "Sends a day in any one conversation")).Text = CeilingText(Get(ceilings, "per_conversation"));
            if (Equals(Get(item, "sends"), false))
                limits.Controls.Add(HelpText(Word("page.nominal", "It sends nothing itself, so these limits never come into play.")));
            advancedHourly = HourlyCombo();
            limits.Controls.Add(NewRow(Word("page.hourly", "Sends an hour, all advanced features together"), advancedHourly));
            limits.Controls.Add(HelpText(Word("page.hourly_note", "You can lower this limit. It never goes above {n}.", "n", HourlyMost())));
        }

        private static string CeilingText(object value)
        {
            return value is double ? ((int)(double)value).ToString(CultureInfo.CurrentCulture) : "-";
        }

        /// What an administrator's Windows policy refuses of `id`, in words, or null (policy.py, as the list carries it).
        private string PolicyRefusal(string id)
        {
            Dictionary<string, object> policy = Map(advancedListing, "policy");
            if (policy == null) return null;
            if (Equals(Get(policy, "forbid"), true))
                return Word("page.policy.forbid", "Your administrator's Windows policy turns off every advanced feature on this PC. None can be turned on or watched.");
            List<object> allowed = Items(policy, "allowed");
            if (allowed != null && !allowed.Contains(id))
                return Word("page.policy.not_allowed", "Your administrator's Windows policy does not allow this feature on this PC. It cannot be turned on or watched.");
            if (Equals(Get(policy, "force_shadow"), true))
                return Word("page.policy.shadow_only", "Your administrator's Windows policy lets this feature be watched, not turned on.");
            return null;
        }

        private bool PolicyAdmits(string id)
        {
            Dictionary<string, object> policy = Map(advancedListing, "policy");
            if (policy == null) return true;
            List<object> allowed = Items(policy, "allowed");
            return !Equals(Get(policy, "forbid"), true) && (allowed == null || allowed.Contains(id));
        }

        /// What each button may do now: Turn on and Watch first once the statement they show has been read, where an
        /// administrator's policy allows it and the capability is not already so; Turn off while it is stored as
        /// anything but off; every feature off at any time. None while another action is under way.
        private void UpdateAdvancedButtons()
        {
            bool idle = busy == 0;
            if (advancedAllOff != null) advancedAllOff.Enabled = idle;
            Dictionary<string, object> item = AdvancedItem(advancedOpen);
            bool read = item != null && AdvancedStatement(advancedOpen) != null;
            string state = Str(item, "state") ?? StateOff, stored = Str(item, "stored") ?? StateOff;
            bool admits = item != null && PolicyAdmits(Str(item, "id"));
            bool forced = Equals(Get(Map(advancedListing, "policy"), "force_shadow"), true);
            if (advancedOn != null) advancedOn.Enabled = idle && read && admits && !forced && state != StateArmed;
            if (advancedWatch != null) advancedWatch.Enabled = idle && read && admits && state != StateShadow;
            if (advancedOff != null) advancedOff.Enabled = idle && item != null && stored != StateOff;
            if (advancedHourly != null) advancedHourly.Enabled = idle && advancedListing != null;
        }

        // ---------------------------------------------------------------- the hourly limit
        /// The highest the limit for every capability together may be: the registry's (GLOBAL_HOURLY).
        private int HourlyMost()
        {
            return Math.Max(1, Whole(Get(advancedListing, "global_hourly_default")));
        }

        /// A choice of 1 to the registry's limit, at what the list says it is now. A choice is sent once the person
        /// stops on it (HourlyPause).
        private SoftCombo HourlyCombo()
        {
            var combo = new SoftCombo();
            IgnoreWheel(combo);
            int most = HourlyMost(), now = Math.Max(1, Math.Min(most, Whole(Get(advancedListing, "global_hourly"))));
            hourlyFilling = true;
            try
            {
                for (int n = 1; n <= most; n++)
                    combo.Items.Add(new Choice(n.ToString(CultureInfo.InvariantCulture), n.ToString(CultureInfo.CurrentCulture)));
                combo.SelectedIndex = now - 1;
            }
            finally
            {
                hourlyFilling = false;
            }
            combo.Width = Px(150);
            combo.AccessibleName = Word("page.hourly", "Sends an hour, all advanced features together");
            combo.SelectedIndexChanged += delegate
            {
                if (hourlyFilling) return;
                hourlyChosen = combo.SelectedIndex + 1;
                if (hourlyTimer == null)
                {
                    hourlyTimer = new Timer();
                    hourlyTimer.Interval = HourlyPause;
                    hourlyTimer.Tick += delegate
                    {
                        hourlyTimer.Stop();
                        SetHourly(hourlyChosen);
                    };
                    Disposed += delegate { hourlyTimer.Dispose(); };
                }
                hourlyTimer.Stop();
                hourlyTimer.Start();
            };
            return combo;
        }

        /// The limit for every capability together set to `value`, from 1 to the registry's, with the generation the
        /// page read the list at.
        private void SetHourly(int value)
        {
            if (advancedListing == null || busy > 0 || value < 1 || value > HourlyMost() ||
                value == Whole(Get(advancedListing, "global_hourly")))
                return;
            string argument = "{\"global_hourly\":" + value.ToString(CultureInfo.InvariantCulture) +
                              ",\"generation\":" + Whole(Get(advancedListing, "generation")).ToString(CultureInfo.InvariantCulture) + "}";
            AdvancedCall("advanced-ceiling", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                // The choice shows what holds after, whatever it was left on.
                advancedShown = null;
                if (AdvancedDone(result))
                    SetNote(advancedNote, Word("page.done.hourly", "All advanced features together now send at most {n} an hour.", "n", value));
                ReadAdvanced(null);
                if (!AdvancedDone(result))
                    TellAdvanced(Str(result, "refusal") == "stale_generation"
                                 ? Word("page.refused.hourly", "Something changed while you were choosing, so the limit stays as it was. Choose again.")
                                 : AdvancedRefusal(result));
            });
        }

        // ---------------------------------------------------------------- turning on, watching, turning off
        /// Asks the person to turn `id` on (`state` armed) or watch it (shadow), with its statement and every warning
        /// it carries as the page shows them, and sends exactly that. `round` counts the times it was asked again
        /// because something changed after it was shown.
        private void ArmAdvanced(string id, string state, int round)
        {
            Dictionary<string, object> item = AdvancedItem(id), statement = AdvancedStatement(id);
            if (item == null || statement == null || advancedListing == null || busy > 0) return;
            string name = AdvancedName(id);
            // What is sent is decided here, from what the dialog is about to show, and from nothing read later.
            string argument = ArmArgument(id, state, Whole(Get(advancedListing, "generation")), statement);
            string affirm = state == StateArmed ? Word("page.turn_on", "Turn on") : Word("page.watch", "Watch first");
            // The safe answer is the default: Enter and Escape leave it as it is, and only the button that names the
            // action says yes (Dialog, as the update check's offer of a pre-release asks).
            if (!AskAdvanced(ArmQuestion(name, state, statement, round > 0), affirm)) return;
            AdvancedCall("advanced-arm", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                {
                    SetNote(advancedNote, state == StateArmed ? Word("page.done.on", "{name} is on.", "name", name)
                                                              : Word("page.done.watch", "{name} is being watched. It does nothing yet.", "name", name));
                    ReadAdvanced(null);
                    return;
                }
                string refusal = Str(result, "refusal");
                if (StaleRefusal(refusal) && round + 1 < AdvancedAsks)
                {
                    // Something changed after the page showed it - a capability turned off elsewhere, a new statement, a
                    // warning, a Codex version: what holds now is read, and asked about again.
                    ReadAdvanced(delegate
                    {
                        if (advancedOpen == id && AdvancedStatement(id) != null) ArmAdvanced(id, state, round + 1);
                    });
                    return;
                }
                ReadAdvanced(null);
                TellAdvanced(AdvancedRefusal(result));
            });
        }

        /// The advanced-arm request for what the page shows: the capability, the state asked for, the statement's
        /// revision, the generation the list was read at, the Codex version the statement named (null where it named
        /// none), and the words of every warning it carried - which the person confirms by saying yes.
        internal static string ArmArgument(string id, string state, int generation, Dictionary<string, object> statement)
        {
            var text = new StringBuilder("{\"capability\":").Append(Json.Escape(id))
                .Append(",\"state\":").Append(Json.Escape(state))
                .Append(",\"revision\":").Append(Whole(Get(statement, "revision")).ToString(CultureInfo.InvariantCulture))
                .Append(",\"generation\":").Append(generation.ToString(CultureInfo.InvariantCulture))
                .Append(",\"engine_version\":");
            string version = Str(statement, "engine_version");
            text.Append(version == null ? "null" : Json.Escape(version)).Append(",\"warnings\":[");
            bool first = true;
            foreach (object entry in Items(Map(statement, "warnings"), "items") ?? new List<object>())
            {
                string word = Str(entry as Dictionary<string, object>, "warning");
                if (word == null) continue;
                if (!first) text.Append(',');
                first = false;
                text.Append(Json.Escape(word));
            }
            return text.Append("]}").ToString();
        }

        /// The question the dialog asks: that something changed, when it did; what is asked; every warning, with its
        /// title and the note under them; for "on", the Codex version it is for; and the statement's five fields.
        private string ArmQuestion(string name, string state, Dictionary<string, object> statement, bool changed)
        {
            string gap = Environment.NewLine + Environment.NewLine;
            var text = new StringBuilder();
            if (changed) text.Append(Word("page.confirm.changed", "Something changed since this was shown. This is how it stands now.")).Append(gap);
            text.Append(state == StateArmed
                        ? Word("page.confirm.on", "Turn on {name}?", "name", name)
                        : Word("page.confirm.watch", "Watch {name} first? It is asked wherever it would act and notes what it would have done, but does nothing.", "name", name));
            Dictionary<string, object> warnings = Map(statement, "warnings");
            List<object> said = Items(warnings, "items");
            if (said != null && said.Count > 0)
            {
                text.Append(gap).Append(Str(warnings, "title") ?? "Warnings");
                foreach (object entry in said)
                {
                    var warning = entry as Dictionary<string, object>;
                    text.Append(Environment.NewLine).Append("• ").Append(Str(warning, "text") ?? Str(warning, "warning") ?? "");
                }
                string note = Str(warnings, "note");
                if (!string.IsNullOrEmpty(note)) text.Append(Environment.NewLine).Append(note);
            }
            string version = Str(statement, "engine_version");
            if (state == StateArmed && version != null)
                text.Append(gap).Append(Word("page.confirm.version", "You are turning it on for Codex {version}. A new version of Codex turns it off until you turn it on again.", "version", version));
            foreach (object entry in Items(statement, "fields") ?? new List<object>())
            {
                var field = entry as Dictionary<string, object>;
                string body = Str(field, "text");
                if (string.IsNullOrEmpty(body)) continue;
                text.Append(gap).Append(Str(field, "title") ?? "").Append(Environment.NewLine).Append(body);
            }
            return text.ToString();
        }

        private void DisarmAdvanced(string id)
        {
            if (AdvancedItem(id) == null || busy > 0) return;
            string name = AdvancedName(id);
            AdvancedCall("advanced-disarm", "{\"capability\":" + Json.Escape(id) + "}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) SetNote(advancedNote, Word("page.done.off", "{name} is off.", "name", name));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(AdvancedRefusal(result));
            });
        }

        private void AllOffAdvanced()
        {
            if (busy > 0) return;
            AdvancedCall("advanced-disarm-all", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) SetNote(advancedNote, Word("page.done.all_off", "Every advanced feature is off."));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(AdvancedRefusal(result));
            });
        }

        /// A refusal in words (vocabulary.Refusal). An administrator's policy says what it refuses; a confirmation that
        /// went on changing, that it did; a state that could not be written, or a bridge that did not answer, that
        /// nothing could be changed; anything else, that the request was refused.
        private string AdvancedRefusal(Dictionary<string, object> result)
        {
            string refusal = Str(result, "refusal");
            if (refusal == "forbidden_by_policy")
                return Word("page.policy.forbid", "Your administrator's Windows policy turns off every advanced feature on this PC. None can be turned on or watched.");
            if (refusal == "not_allowed_by_policy")
                return Word("page.policy.not_allowed", "Your administrator's Windows policy does not allow this feature on this PC. It cannot be turned on or watched.");
            if (refusal == "shadow_forced_by_policy")
                return Word("page.policy.shadow_only", "Your administrator's Windows policy lets this feature be watched, not turned on.");
            if (StaleRefusal(refusal))
                return Word("page.refused.changed", "It kept changing while you read it, so nothing was turned on. Try again in a moment.");
            if (refusal == null || refusal == "state_unavailable")
                return Word("page.refused.unavailable", "The advanced features could not be changed right now. Nothing was changed.");
            return Word("page.refused.other", "That request was refused. Nothing was changed.");
        }

        /// Whether a refusal says only that what the person confirmed no longer holds, which they can confirm again.
        private static bool StaleRefusal(string refusal)
        {
            return refusal == "stale_generation" || refusal == "stale_revision" || refusal == "stale_confirmation";
        }

        private static bool AdvancedDone(Dictionary<string, object> result)
        {
            return result != null && Equals(Get(result, "done"), true);
        }

        // ---------------------------------------------------------------- asking and telling
        /// The window's own dialog, with the safe answer the default (Dialog); a test's answer in a window a test drives.
        private bool AskAdvanced(string question, string affirm)
        {
            if (advancedScript == null) return Dialog(question, affirm, S("action.cancel", "Cancel"));
            advancedAsked.Add(question);
            bool yes = advancedAnswers.Count > 0 && advancedAnswers[0];
            if (advancedAnswers.Count > 0) advancedAnswers.RemoveAt(0);
            return yes;
        }

        /// A notice in the window's own dialog (Tell); written down in a window a test drives.
        private void TellAdvanced(string text)
        {
            if (advancedScript == null) Tell(text);
            else advancedTold.Add(text);
        }

        // ---------------------------------------------------------------- the bridge
        /// A reply's `result` - what this edition answered - or null where the bridge refused or could not answer.
        private static Dictionary<string, object> AdvancedResult(Dictionary<string, object> reply)
        {
            return Ok(reply) ? Map(reply, "result") : null;
        }

        /// The argument of a request in the person's language: the Interface language the window's words were
        /// resolved for, `system` included, which the bridge resolves as it resolves core's (surfaces._locale).
        private string LocaleArgument(string capability)
        {
            var text = new StringBuilder("{");
            if (capability != null) text.Append("\"capability\":").Append(Json.Escape(capability));
            if (!string.IsNullOrEmpty(openedLanguage))
                text.Append(capability != null ? "," : "").Append("\"locale\":").Append(Json.Escape(openedLanguage));
            return text.Append("}").ToString();
        }

        /// One request of this page's, on a worker as every bridge call is, its reply handed back on this thread. An
        /// action holds every other action until it is answered (SetBusy); a read does not. In a window a test drives,
        /// answered at once from the test's replies (AdvancedScripted).
        private void AdvancedCall(string command, string argument, bool action, Action<Dictionary<string, object>> done)
        {
            if (advancedScript != null)
            {
                done(AdvancedScripted(command, argument));
                UpdateAdvancedButtons();
                return;
            }
            if (auditing) return;
            if (action) SetBusy(true);
            UpdateAdvancedButtons();
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call(command, argument); }
                catch (Exception error) { reply = Failure(error); }
                MethodInvoker finish = delegate
                {
                    if (action) SetBusy(false);
                    done(reply);
                    UpdateAdvancedButtons();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// A reply's part written out, to compare with what was shown; "" for one that cannot be.
        private static string AdvancedWritten(object value)
        {
            try { return Json.Write(value); }
            catch (FormatException) { return ""; }
        }
    }
}

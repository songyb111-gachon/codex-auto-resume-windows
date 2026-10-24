// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - Pending's two tabs (v0.6.19, issue #50): Recoveries | Scheduled (N).
//
// While prompt_queue stands on or watched, or a reset action's rule or a queued message waits, Pending gets a tab strip
// drawn in the nav strip's own tabs (NavButton: the chosen one pressed into a well, its name in the accent and heavier):
// Recoveries, which is today's Pending as it was, and Scheduled with how many wait. With nothing scheduled and the queue
// off there is no strip: Pending looks exactly as the standard edition's. The standard page is not edited - this is the
// PendingBuilt point (gui/Dashboard.cs): the page's own controls are moved, as they are, into the Recoveries view.
//
// Scheduled is a flat list (window-lists-stay-flat) - the conversation, where each stands, when it goes and what it does
// while a turn runs - of every reset rule still to act (AdvancedResets.cs, their own form stays on their card) and every
// message still to go, with Schedule a message..., Edit... (a waiting message), Cancel and Go on under it, acting on the
// row chosen. The editor (AdvancedEditor.cs) is the one place a message is written; once it saves, the list is read
// again and the saved row is chosen. Under them, while any is, a Done section lists the completed messages of the last 30
// days, newest first, and Delete completed (N)... asks, then sends the ids it shows and the generation it read
// (advanced-prompts-clear-done) and says how many were deleted and how many kept because they changed.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // Pending's page, its two views, the strip that chooses between them and which is chosen.
        private Panel scheduledPage;
        private SoftPage recoveriesView, scheduleView;
        private SoftFlow scheduleTabs;
        private NavButton recoveriesTab, scheduledTab;
        private bool scheduleChosen, scheduleWanted;
        // The Scheduled view: its list, its buttons and note, the Done section, and what it was last filled from.
        private ListView scheduledList, doneList;
        private Control doneCard;
        private SoftStack doneHolder;
        private Button scheduleAddButton, scheduleEditButton, scheduleCancelButton, scheduleGoOnButton, clearDoneButton;
        private NoteLabel scheduledNote;
        private string scheduledShown;

        // ---------------------------------------------------------------- built
        /// Pending's tab strip and its Scheduled view, beside the page's own controls - which move, as they are, into the
        /// Recoveries view, now and as the page adds the rest of them.
        partial void PendingBuilt(Panel page)
        {
            scheduledPage = page;
            recoveriesView = NewView();
            scheduleView = NewView();
            scheduleView.Visible = false;
            var own = new List<Control>();
            foreach (Control control in page.Controls) own.Add(control);
            foreach (Control control in own)
            {
                page.Controls.Remove(control);
                recoveriesView.Controls.Add(control);
            }
            page.Controls.Add(recoveriesView);
            page.Controls.Add(scheduleView);
            // early_reset's line at the top of the Recoveries view, while it stands on (AdvancedEarly.cs).
            BuildEarlyLine(recoveriesView);
            page.ControlAdded += delegate(object sender, ControlEventArgs e)
            {
                if (e.Control == recoveriesView || e.Control == scheduleView || e.Control == scheduleTabs) return;
                page.Controls.Remove(e.Control);
                recoveriesView.Controls.Add(e.Control);
            };

            scheduleTabs = new SoftFlow();
            scheduleTabs.Dock = DockStyle.Top;
            scheduleTabs.AutoSize = true;
            scheduleTabs.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            scheduleTabs.WrapContents = false;
            scheduleTabs.Margin = new Padding(0);
            scheduleTabs.Padding = Pad(0, 0, 0, 8);
            scheduleTabs.AccessibleRole = AccessibleRole.PageTabList;
            scheduleTabs.AccessibleName = S("nav.pending", "Pending");
            recoveriesTab = NewScheduleTab(delegate { ChooseSchedule(false); });
            scheduledTab = NewScheduleTab(delegate { ChooseSchedule(true); });
            scheduleTabs.Controls.Add(recoveriesTab);
            scheduleTabs.Controls.Add(scheduledTab);
            scheduleTabs.Visible = false;
            // The chosen tab pressed from the strip's first paint: Recoveries, the view shown, until a tab is chosen.
            MarkScheduleTabs();
            page.Controls.Add(scheduleTabs);

            BuildScheduleView();
            scheduledShown = null;
            FillScheduled();
        }

        private static SoftPage NewView()
        {
            var view = new SoftPage();
            view.Dock = DockStyle.Fill;
            view.Margin = new Padding(0);
            view.Padding = new Padding(0);
            view.Scrolls = false;
            return view;
        }

        private NavButton NewScheduleTab(EventHandler click)
        {
            var tab = new NavButton();
            tab.Font = Soft.RoleFont("nav");
            tab.AutoSize = true;
            tab.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            tab.ForeColor = Secondary;
            // The nav strip's tab padding (BuildDashboard), inside the room NavButton keeps for its ring.
            tab.Padding = Pad(18, 8, 18, 8);
            tab.Margin = Pad(0, 0, 2, 0);
            tab.Click += click;
            return tab;
        }

        private void BuildScheduleView()
        {
            scheduledList = List(Word("page.scheduled", "Scheduled"),
                                 Col(S("pending.col_conversation", "Conversation"), 150),
                                 Col(S("pending.col_status", "Status"), 170),
                                 Col(Word("page.queue.when", "When"), 190),
                                 Col(Word("page.scheduled.col_mode", "While a turn runs"), 150));
            scheduledList.SelectedIndexChanged += delegate { UpdateScheduleButtons(); };
            scheduledList.DoubleClick += delegate { EditChosen(); };
            Control listCard = ListCard(scheduledList);

            FlowLayoutPanel row = ButtonRow();
            scheduleAddButton = MakeButton(Word("page.scheduled.add", "Schedule a message..."), true, delegate { OpenEditor(null); });
            scheduleEditButton = MakeButton(Word("page.queue.edit", "Edit..."), false, delegate { EditChosen(); });
            scheduleCancelButton = MakeButton(Word("page.resets.cancel", "Cancel"), false, delegate { CancelChosen(); });
            scheduleGoOnButton = MakeButton(Word("page.queue.go_on", "Go on"), false, delegate { GoOnChosen(); });
            foreach (Button button in new[] { scheduleAddButton, scheduleEditButton, scheduleCancelButton, scheduleGoOnButton })
            {
                button.Margin = Pad(0, 0, 6, 0);
                row.Controls.Add(button);
            }
            scheduledNote = Note();
            row.Controls.Add(scheduledNote);

            // The Done section: its own card, as tall as its rows need and never more than two fifths of the view.
            doneList = List(Word("page.scheduled.done", "Done"),
                            Col(S("pending.col_conversation", "Conversation"), 150),
                            Col(S("pending.col_status", "Status"), 150),
                            Col(Word("page.queue.when", "When"), 190),
                            Col(Word("page.scheduled.col_finished", "Finished"), 130));
            doneCard = ListCard(doneList);
            doneHolder = new SoftStack();
            doneHolder.ColumnCount = 1;
            doneHolder.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            doneHolder.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            doneHolder.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            doneHolder.Dock = DockStyle.Bottom;
            doneHolder.Margin = new Padding(0);
            doneHolder.Padding = Pad(0, Brand.PageGap, 0, 0);
            doneHolder.Controls.Add(doneCard, 0, 0);
            FlowLayoutPanel doneRow = ButtonRow();
            doneRow.Dock = DockStyle.Fill;
            clearDoneButton = MakeButton(Word("page.scheduled.clear", "Delete completed ({n})...", "n", 0), false,
                                         delegate { ClearDone(); });
            doneRow.Controls.Add(clearDoneButton);
            doneHolder.Controls.Add(doneRow, 0, 1);
            doneHolder.Visible = false;

            // Docked from the bottom up: the Done section, then the buttons, then the list fills what is left.
            scheduleView.Controls.Add(listCard);
            scheduleView.Controls.Add(row);
            scheduleView.Controls.Add(doneHolder);
            scheduleView.SizeChanged += delegate { FitDone(); };
        }

        private void FitDone()
        {
            // Read from its rows, not its Visible: a page never shown has no visible control.
            if (doneHolder == null || scheduleView == null || doneList.Items.Count == 0) return;
            int rows = Math.Max(1, doneList.Items.Count);
            int each = doneList.SmallImageList != null ? doneList.SmallImageList.ImageSize.Height : Px(34);
            int needed = doneHolder.Padding.Vertical + Px(16) + each * (rows + 1) + clearDoneButton.Height + Px(24);
            int most = Math.Max(Px(140), scheduleView.ClientSize.Height * 2 / 5);
            int height = Math.Min(needed, most);
            if (doneHolder.Height != height) doneHolder.Height = height;
        }

        // ---------------------------------------------------------------- shown
        /// The strip shown while anything is scheduled or the queue stands, and the view it chooses.
        private void ChooseSchedule(bool scheduled)
        {
            if (scheduleTabs == null) return;
            scheduleChosen = scheduled && scheduleWanted;
            bool paused = scheduledPage != null && scheduledPage.IsHandleCreated && Redraw(scheduledPage, false);
            try
            {
                recoveriesView.Visible = !scheduleChosen;
                scheduleView.Visible = scheduleChosen;
                MarkScheduleTabs();
            }
            finally
            {
                if (paused) Redraw(scheduledPage, true);
            }
            if (scheduleChosen && !auditing && advancedScript == null && advancedListing != null) ReadResets(null);
            UpdateScheduleButtons();
        }

        /// The tab of the view shown pressed into its well, its name in the accent and heavier, as the nav strip marks its
        /// chosen page; the other plain.
        private void MarkScheduleTabs()
        {
            foreach (NavButton tab in new[] { recoveriesTab, scheduledTab })
            {
                bool current = (tab == scheduledTab) == scheduleChosen;
                tab.ForeColor = current ? Ink : Secondary;
                tab.Font = Soft.RoleFont(current ? "nav_current" : "nav");
                tab.Current = current;
            }
        }

        /// The list read: the queued messages read once where the prompt queue stands and they were not yet, else the tabs
        /// shown again as the list now has it.
        private void ScheduleListingApplied()
        {
            Dictionary<string, object> queue = advancedListing == null ? null : AdvancedItem(PromptQueueId);
            if (queue != null && Standing(queue) && advancedPrompts == null && (!auditing || advancedScript != null)) ReadPrompts(null);
            else FillScheduled();
        }

        /// Whether the strip is there: prompt_queue on or watched, or anything scheduled.
        private bool ScheduleWanted(List<object> rules, List<Dictionary<string, object>> prompts, List<Dictionary<string, object>> done)
        {
            Dictionary<string, object> queue = advancedListing == null ? null : AdvancedItem(PromptQueueId);
            return (queue != null && Standing(queue)) || rules.Count + prompts.Count + done.Count > 0;
        }

        /// The completed messages advanced-prompts lists (control/prompts.py marks them), newest first.
        private List<Dictionary<string, object>> CompletedPrompts()
        {
            var found = new List<Dictionary<string, object>>();
            foreach (object entry in Items(advancedPrompts, "prompts") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                if (row != null && Equals(Get(row, "completed"), true)) found.Add(row);
            }
            found.Sort(delegate(Dictionary<string, object> a, Dictionary<string, object> b)
            {
                return Number(b, "finished_at").CompareTo(Number(a, "finished_at"));
            });
            return found;
        }

        /// The Scheduled view as the last reads hold it: each rule and message still to go a row, the Done section, the
        /// strip and its count - written only when something it shows changed, the chosen row kept (or the one just saved
        /// chosen).
        private void FillScheduled()
        {
            if (scheduledList == null || scheduledList.IsDisposed) return;
            List<object> rules = ResetRules(null, true);
            List<Dictionary<string, object>> prompts = PendingPrompts();
            List<Dictionary<string, object>> done = CompletedPrompts();
            bool wanted = ScheduleWanted(rules, prompts, done);
            string shown = AdvancedWritten(rules) + "|" + AdvancedWritten(new List<object>(prompts.ToArray())) + "|" +
                           AdvancedWritten(new List<object>(done.ToArray())) + "|" +
                           AdvancedWritten(ConversationsWritten()) + "|" + wanted + "|" + (advancedWords == null);
            if (shown == scheduledShown && editorSaved < 0)
            {
                UpdateScheduleButtons();
                return;
            }
            scheduledShown = shown;
            object keep = ChosenTag() == null ? null : RowKey(ChosenTag());
            if (editorSaved >= 0) keep = "prompt " + editorSaved.ToString(CultureInfo.InvariantCulture);
            editorSaved = -1;
            scheduledList.BeginUpdate();
            try
            {
                scheduledList.Items.Clear();
                foreach (object entry in rules) AddScheduledRow(RuleRow(entry as Dictionary<string, object>), keep);
                foreach (Dictionary<string, object> row in prompts) AddScheduledRow(PromptRow(row), keep);
            }
            finally
            {
                scheduledList.EndUpdate();
            }
            doneList.BeginUpdate();
            try
            {
                doneList.Items.Clear();
                foreach (Dictionary<string, object> row in done)
                {
                    var tag = new Dictionary<string, object>();
                    tag["code"] = "recovered";
                    tag["row"] = row;
                    var item = new ListViewItem(ConversationOf(Str(row, "thread_id")));
                    item.SubItems.Add(Str(row, "reason") == "handed_over"
                        ? Word("page.scheduled.state.handed_over", "handed over to you")
                        : Word("page.scheduled.state.delivered", "delivered"));
                    item.SubItems.Add(PromptWhen(row));
                    item.SubItems.Add(ClockTime(Number(row, "finished_at")));
                    item.Tag = tag;
                    doneList.Items.Add(item);
                }
            }
            finally
            {
                doneList.EndUpdate();
            }
            clearDoneButton.Text = Word("page.scheduled.clear", "Delete completed ({n})...", "n", done.Count);
            clearDoneButton.AccessibleName = clearDoneButton.Text;
            doneHolder.Visible = done.Count > 0;
            recoveriesTab.Text = Word("page.pending.recoveries", "Recoveries");
            scheduledTab.Text = Word("page.pending.scheduled", "Scheduled ({n})", "n", rules.Count + prompts.Count);
            scheduleWanted = wanted;
            scheduleTabs.Visible = wanted;
            if (!wanted && scheduleChosen) ChooseSchedule(false);
            FitDone();
            UpdateScheduleButtons();
        }

        /// The row standing for `key` ("prompt 5", "rule 2") chosen, as a click on it chooses it.
        private void ChooseScheduledRow(string key)
        {
            if (scheduledList == null) return;
            foreach (ListViewItem item in scheduledList.Items)
                if (RowKey(item.Tag as Dictionary<string, object>) == key)
                {
                    item.Selected = true;
                    item.Focused = true;
                }
            UpdateScheduleButtons();
        }

        private static string RowKey(Dictionary<string, object> tag)
        {
            return Str(tag, "key");
        }

        private void AddScheduledRow(ListViewItem item, object keep)
        {
            scheduledList.Items.Add(item);
            if (keep != null && Equals(RowKey(item.Tag as Dictionary<string, object>), keep))
            {
                item.Selected = true;
                item.Focused = true;
            }
        }

        /// A reset rule's row: its conversation (a credit has none), where it stands, what it waits for.
        private ListViewItem RuleRow(Dictionary<string, object> rule)
        {
            string state = Str(rule, "state");
            var tag = new Dictionary<string, object>();
            tag["code"] = state == "held" ? "exhausted" : Equals(Get(rule, "being_sent"), true) ? "submitted" : "scheduled";
            tag["row"] = rule;
            tag["kind"] = "rule";
            tag["key"] = "rule " + Whole(Get(rule, "rule_id")).ToString(CultureInfo.InvariantCulture);
            string thread = Str(rule, "thread_id");
            var item = new ListViewItem(thread != null ? ConversationOf(thread) : Word("name.reset_credit", "Reset credit"));
            item.SubItems.Add(RuleStateWord(rule));
            item.SubItems.Add(RuleWhat(rule));
            item.SubItems.Add("");
            item.Tag = tag;
            return item;
        }

        /// A queued message's row: its conversation, where it stands, when it goes, what it does while a turn runs.
        private ListViewItem PromptRow(Dictionary<string, object> row)
        {
            string state = Str(row, "state");
            var tag = new Dictionary<string, object>();
            tag["code"] = state == "held" || Str(row, "reason") == "withdraw_refused" ? "exhausted"
                        : Equals(Get(row, "in_codex"), true) || Equals(Get(row, "being_sent"), true) ? "submitted" : "scheduled";
            tag["row"] = row;
            tag["kind"] = "prompt";
            tag["key"] = "prompt " + Whole(Get(row, "prompt_id")).ToString(CultureInfo.InvariantCulture);
            var item = new ListViewItem(ConversationOf(Str(row, "thread_id")));
            item.SubItems.Add(PromptState(row));
            item.SubItems.Add(PromptWhen(row));
            item.SubItems.Add(Str(row, "trigger") == "after_turn" || Str(row, "while_running") != "wait"
                ? Word("page.scheduled.mode.queue", "Codex's queue")
                : Word("page.scheduled.mode.wait", "waits"));
            item.Tag = tag;
            return item;
        }

        /// The chosen row's tag, read from the items themselves: a list whose window was never made has no SelectedItems yet.
        private Dictionary<string, object> ChosenTag()
        {
            if (scheduledList == null) return null;
            foreach (ListViewItem item in scheduledList.Items)
                if (item.Selected) return item.Tag as Dictionary<string, object>;
            return null;
        }

        private Dictionary<string, object> ChosenRow(out string kind)
        {
            Dictionary<string, object> tag = ChosenTag();
            kind = Str(tag, "kind");
            return Map(tag, "row");
        }

        private void UpdateScheduleButtons()
        {
            if (scheduleAddButton == null) return;
            bool listed = busy == 0 && advancedListing != null && advancedPrompts != null;
            string kind;
            Dictionary<string, object> row = ChosenRow(out kind);
            Dictionary<string, object> queue = advancedListing == null ? null : AdvancedItem(PromptQueueId);
            scheduleAddButton.Enabled = listed && queue != null && Standing(queue);
            string state = Str(row, "state");
            scheduleEditButton.Enabled = listed && kind == "prompt" && state == "waiting";
            scheduleCancelButton.Enabled = busy == 0 && advancedListing != null && row != null &&
                                           !Equals(Get(row, "being_sent"), true) && Str(row, "reason") != "withdraw_refused";
            scheduleGoOnButton.Enabled = busy == 0 && advancedListing != null && row != null && state == "held";
            clearDoneButton.Enabled = listed && doneList.Items.Count > 0;
        }

        // ---------------------------------------------------------------- acted on
        private void EditChosen()
        {
            string kind;
            Dictionary<string, object> row = ChosenRow(out kind);
            if (kind == "prompt" && scheduleEditButton.Enabled) OpenEditor(row);
        }

        private void CancelChosen()
        {
            string kind;
            Dictionary<string, object> row = ChosenRow(out kind);
            if (row == null || !scheduleCancelButton.Enabled) return;
            if (kind == "rule") CancelReset(Whole(Get(row, "rule_id")));
            else CancelPrompt(Whole(Get(row, "prompt_id")));
        }

        private void GoOnChosen()
        {
            string kind;
            Dictionary<string, object> row = ChosenRow(out kind);
            if (row == null || !scheduleGoOnButton.Enabled) return;
            if (kind == "rule") GoOnReset(Whole(Get(row, "rule_id")));
            else GoOnPrompt(Whole(Get(row, "prompt_id")));
        }

        /// Delete completed (N)...: asked first, then the ids the Done section shows, against the generation they were read
        /// at; how many were deleted, and how many kept because they changed, said beside the buttons.
        private void ClearDone()
        {
            if (busy > 0 || advancedListing == null || advancedPrompts == null || doneList.Items.Count == 0) return;
            var ids = new List<string>();
            foreach (ListViewItem item in doneList.Items)
                ids.Add(Whole(Get(Map(item.Tag as Dictionary<string, object>, "row"), "prompt_id")).ToString(CultureInfo.InvariantCulture));
            string question = Word("page.confirm.clear",
                "Delete {n} completed messages from this list? Waiting, held, cancelled and failed ones are kept, and nothing in Codex changes.",
                "n", ids.Count);
            if (!AskAdvanced(question, Affirm(Word("page.scheduled.clear", "Delete completed ({n})...", "n", ids.Count)))) return;
            string generation = Get(advancedPrompts, "generation") is double
                ? Whole(Get(advancedPrompts, "generation")).ToString(CultureInfo.InvariantCulture) : AdvancedGeneration();
            string argument = "{\"prompts\":[" + string.Join(",", ids.ToArray()) + "],\"generation\":" + generation + "}";
            AdvancedCall("advanced-prompts-clear-done", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                {
                    int deleted = Whole(Get(result, "deleted")), skipped = Whole(Get(result, "skipped"));
                    ResetNote(skipped > 0
                        ? Word("page.done.cleared_kept", "Deleted {deleted}, kept {skipped} that changed.", "deleted", deleted)
                              .Replace("{skipped}", skipped.ToString(CultureInfo.CurrentCulture))
                        : Word("page.done.cleared", "Deleted {deleted}.", "deleted", deleted));
                    advancedPrompts = result;
                    FillScheduled();
                }
                else
                {
                    ReadPrompts(null);
                    TellAdvanced(PromptRefusal(Str(result, "refusal")));
                }
            });
        }
    }
}

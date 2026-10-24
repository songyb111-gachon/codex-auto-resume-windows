// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - Pending is one list (v0.6.19, issue #50; the owner's decision of 2026-10-24).
//
// The reset rules still to act (AdvancedResets.cs, their own form stays on their card) and the messages still to go
// (AdvancedQueue.cs) are rows of Pending's one list, after the recoveries - no tab strip, nothing above the list. The
// list stays flat (window-lists-stay-flat), and its Kind column tells a recovery, a scheduled message and a reset rule
// apart. A row of this edition's own (gui/Dashboard.cs RowKindKey) is offered none of a recovery's buttons: under the
// list, the buttons that apply to the chosen row's kind show and the others are hidden - a recovery's Retry now,
// Cancel, Timeline and Turn off; a message's Edit..., Go on and Cancel; a rule's Go on and Cancel - in one group as
// wide as the widest kind's, so Cancel all, Rescan and Schedule a message... never move as the choice moves. Schedule a
// message... is there only while the prompt queue stands on. A double click on a waiting message opens its editor
// (AdvancedEditor.cs, the one place a message is written); on a recovery, its menu, as always. Once the editor saves,
// the list is read again and the saved row is chosen.
//
// Completed messages are History: the delivered and handed-over messages of the last 30 days are rows of History's list,
// and Delete completed (N)... - shown under it while any is - asks, then sends the ids it shows and the generation it
// read (advanced-prompts-clear-done) and says how many were deleted and how many kept because they changed.
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
        // The kinds of row this edition joins to Pending and History (RowKindKey).
        private const string KindMessage = "message", KindRule = "rule", KindDone = "message_done";
        // The cells of a joined row, as CellsWritten writes them (AdvancedRuns.cs).
        private const string RowCellsKey = "row_cells", RowSourceKey = "row_source";
        // The chosen row's own buttons: a recovery's (core's, moved in here) and a message's or a rule's (this edition's).
        private SoftFlow kindButtons;
        private Button scheduleAddButton, scheduleEditButton, scheduleCancelButton, scheduleGoOnButton, clearDoneButton;
        // What the joined rows were last made from, and the rows themselves.
        private string scheduledShown;
        private readonly List<Dictionary<string, object>> joinedPending = new List<Dictionary<string, object>>();
        private readonly List<Dictionary<string, object>> joinedDone = new List<Dictionary<string, object>>();
        // What the last Delete completed did, said under History until another row there is chosen.
        private string doneNote, doneNoteFor;

        // ---------------------------------------------------------------- built
        /// Pending's buttons: the chosen row's own in one group at the start - core's four for a recovery, then Edit...,
        /// Go on and Cancel for a message or a rule - and Schedule a message... after Rescan.
        partial void PendingButtonsBuilt(FlowLayoutPanel row)
        {
            kindButtons = new SoftFlow();
            kindButtons.AutoSize = true;
            kindButtons.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            kindButtons.WrapContents = false;
            kindButtons.Margin = new Padding(0);
            kindButtons.Padding = new Padding(0);
            scheduleEditButton = MakeButton(Word("page.queue.edit", "Edit..."), false, delegate { EditChosen(); });
            scheduleGoOnButton = MakeButton(Word("page.queue.go_on", "Go on"), false, delegate { GoOnChosen(); });
            scheduleCancelButton = MakeButton(Word("page.resets.cancel", "Cancel"), false, delegate { CancelChosen(); });
            foreach (Button button in new[] { retryButton, cancelButton, timelineButton, threadButton })
            {
                row.Controls.Remove(button);
                kindButtons.Controls.Add(button);
            }
            foreach (Button button in new[] { scheduleEditButton, scheduleGoOnButton, scheduleCancelButton })
            {
                button.Margin = Pad(0, 0, 6, 0);
                button.Visible = false;
                kindButtons.Controls.Add(button);
            }
            row.Controls.Add(kindButtons);
            row.Controls.SetChildIndex(kindButtons, 0);
            scheduleAddButton = MakeButton(Word("page.scheduled.add", "Schedule a message..."), false, delegate { OpenEditor(null); });
            scheduleAddButton.Margin = Pad(0, 0, 6, 0);
            scheduleAddButton.Visible = false;
            row.Controls.Add(scheduleAddButton);
            FitKindButtons();
        }

        /// History's buttons: Delete completed (N)..., shown while completed messages are listed.
        partial void HistoryButtonsBuilt(FlowLayoutPanel row)
        {
            clearDoneButton = MakeButton(Word("page.scheduled.clear", "Delete completed ({n})...", "n", 0), false,
                                         delegate { ClearDone(); });
            clearDoneButton.Margin = Pad(0, 0, 9, 0);
            clearDoneButton.Visible = false;
            row.Controls.Add(clearDoneButton);
        }

        /// The group as wide as the widest kind's buttons - Turn off and Turn on measured both - so what follows it never
        /// moves as the chosen row's kind changes. Asked when the words are made, never from a layout.
        private void FitKindButtons()
        {
            if (kindButtons == null) return;
            int recovery = Across(retryButton) + Across(cancelButton) + Across(timelineButton) +
                           Math.Max(Across(threadButton, S("action.thread_off", "Turn off for this conversation")),
                                    Across(threadButton, S("action.thread_on", "Turn on for this conversation")));
            int message = Across(scheduleEditButton) + Across(scheduleGoOnButton) + Across(scheduleCancelButton);
            int widest = Math.Max(recovery, message);
            if (kindButtons.MinimumSize.Width != widest) kindButtons.MinimumSize = new Size(widest, 0);
        }

        /// What `button` takes along the row - its width and its margins - saying `text` (its own words where null).
        private static int Across(Button button, string text = null)
        {
            if (button == null) return 0;
            int width = button.GetPreferredSize(Size.Empty).Width;
            if (text != null && text != button.Text)
                width += TextRenderer.MeasureText(text, button.Font).Width - TextRenderer.MeasureText(button.Text, button.Font).Width;
            return Math.Max(button.MinimumSize.Width, width) + button.Margin.Horizontal;
        }

        // ---------------------------------------------------------------- the rows
        /// Pending's rows of this edition's own after the recoveries, and History's completed messages after its recoveries.
        partial void ListRowsJoined(ListView list, List<Dictionary<string, object>> rows)
        {
            if (list == null || rows == null) return;
            if (list == pendingList) rows.AddRange(joinedPending);
            else if (list == historyList) rows.AddRange(joinedDone);
        }

        /// A joined row's cells, as it was made (CellsWritten, AdvancedRuns.cs): true where `row` is one.
        private static bool WriteJoinedCells(Dictionary<string, object> row, string[] cells)
        {
            var own = Get(row, RowCellsKey) as string[];
            if (own == null) return false;
            for (int i = 0; i < cells.Length && i < own.Length; i++) cells[i] = own[i];
            return true;
        }

        /// The list read: the queued messages read once where the prompt queue stands and they were not yet, else the rows
        /// made again as the list now has it.
        private void ScheduleListingApplied()
        {
            Dictionary<string, object> queue = advancedListing == null ? null : AdvancedItem(PromptQueueId);
            if (queue != null && Standing(queue) && advancedPrompts == null && (!auditing || advancedScript != null)) ReadPrompts(null);
            else FillScheduled();
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

        /// The rows of this edition's own as the last reads hold them, made again only when something they show changed,
        /// and Pending and History filled again with them - the chosen row kept, or the one just saved chosen.
        private void FillScheduled()
        {
            // Made whether or not either page has been built yet: a page built later joins them as it is filled.
            List<object> rules = ResetRules(null, true);
            List<Dictionary<string, object>> prompts = PendingPrompts();
            List<Dictionary<string, object>> done = CompletedPrompts();
            string shown = AdvancedWritten(rules) + "|" + AdvancedWritten(new List<object>(prompts.ToArray())) + "|" +
                           AdvancedWritten(new List<object>(done.ToArray())) + "|" +
                           AdvancedWritten(ConversationsWritten()) + "|" + (advancedWords == null);
            if (shown != scheduledShown || editorSaved >= 0)
            {
                scheduledShown = shown;
                joinedPending.Clear();
                foreach (object entry in rules) joinedPending.Add(RuleRow(entry as Dictionary<string, object>));
                foreach (Dictionary<string, object> row in prompts) joinedPending.Add(PromptRow(row));
                joinedDone.Clear();
                foreach (Dictionary<string, object> row in done) joinedDone.Add(DoneRow(row));
                RefillLists();
                // The saved row chosen once Pending's list is there to choose it in; kept until then.
                if (editorSaved >= 0 && pendingList != null)
                {
                    ChooseScheduledRow("prompt " + editorSaved.ToString(CultureInfo.InvariantCulture));
                    editorSaved = -1;
                }
            }
            FitKindButtons();
            UpdatePendingButtons();
            UpdateHistoryButtons();
        }

        /// The row standing for `key` ("prompt 5", "rule 2") chosen on Pending, as a click on it chooses it.
        private void ChooseScheduledRow(string key)
        {
            if (pendingList == null) return;
            foreach (ListViewItem item in pendingList.Items)
                if (Str(item.Tag as Dictionary<string, object>, RowKeyKey) == key)
                {
                    pendingList.SelectedIndices.Clear();
                    item.Selected = true;
                    item.Focused = true;
                }
            UpdatePendingButtons();
        }

        /// A joined row: its kind, the key it is known by, the tone of its state, its source, its cells and what Why it is
        /// waiting says of it.
        private static Dictionary<string, object> Joined(string kind, string key, string code, Dictionary<string, object> source,
                                                         string[] cells, string said)
        {
            var row = new Dictionary<string, object>();
            row[RowKindKey] = kind;
            row[RowKeyKey] = key;
            row["code"] = code;
            row["thread_id"] = Str(source, "thread_id");
            row[RowSourceKey] = source;
            row[RowCellsKey] = cells;
            row[RowSaidKey] = said;
            return row;
        }

        /// A reset rule's row: its conversation (a credit has none), where it stands, a rule, what it waits for.
        private Dictionary<string, object> RuleRow(Dictionary<string, object> rule)
        {
            string state = Str(rule, "state");
            string code = state == "held" ? "exhausted" : Equals(Get(rule, "being_sent"), true) ? "submitted" : "scheduled";
            string thread = Str(rule, "thread_id");
            string stands = RuleStateWord(rule), what = RuleWhat(rule);
            var cells = new[] { thread != null ? ConversationOf(thread) : Word("name.reset_credit", "Reset credit"), stands,
                                Word("page.pending.kind.rule", "Reset rule"), what, "", "" };
            return Joined(KindRule, "rule " + Whole(Get(rule, "rule_id")).ToString(CultureInfo.InvariantCulture), code, rule,
                          cells, stands + " · " + what);
        }

        /// A queued message's row: its conversation, where it stands, a message and what it does while a turn runs, when.
        private Dictionary<string, object> PromptRow(Dictionary<string, object> row)
        {
            string state = Str(row, "state");
            string code = state == "held" || Str(row, "reason") == "withdraw_refused" ? "exhausted"
                        : Equals(Get(row, "in_codex"), true) || Equals(Get(row, "being_sent"), true) ? "submitted" : "scheduled";
            string mode = Str(row, "trigger") == "after_turn" || Str(row, "while_running") != "wait"
                ? Word("page.scheduled.mode.queue", "Codex's queue")
                : Word("page.scheduled.mode.wait", "waits");
            string stands = PromptState(row), when = PromptWhen(row);
            var cells = new[] { ConversationOf(Str(row, "thread_id")), stands, Word("page.pending.kind.message", "Scheduled message"),
                                when, "", "" };
            // What it does while a turn runs is said in Why it is waiting, beside where it stands and when it goes.
            return Joined(KindMessage, "prompt " + Whole(Get(row, "prompt_id")).ToString(CultureInfo.InvariantCulture), code, row,
                          cells, stands + " · " + when + " · " + mode);
        }

        /// A completed message's row in History: its conversation, delivered or handed over, a message, when it was due and
        /// when it finished.
        private Dictionary<string, object> DoneRow(Dictionary<string, object> row)
        {
            string outcome = Str(row, "reason") == "handed_over"
                ? Word("page.scheduled.state.handed_over", "handed over to you")
                : Word("page.scheduled.state.delivered", "delivered");
            var cells = new[] { ConversationOf(Str(row, "thread_id")), outcome, Word("page.pending.kind.message", "Scheduled message"),
                                PromptWhen(row), ClockTime(Number(row, "finished_at")) };
            return Joined(KindDone, "done " + Whole(Get(row, "prompt_id")).ToString(CultureInfo.InvariantCulture), "recovered",
                          row, cells, outcome);
        }

        // ---------------------------------------------------------------- offered
        /// The chosen Pending row's own buttons, by its kind: a message's Edit..., Go on and Cancel, a rule's Go on and
        /// Cancel, shown only for them (core's four only for a recovery); Schedule a message... while the queue stands.
        partial void PendingButtonsUpdated(Dictionary<string, object> row, bool idle)
        {
            if (scheduleAddButton == null) return;
            string kind = Str(row, RowKindKey);
            Dictionary<string, object> source = Map(row, RowSourceKey);
            bool message = kind == KindMessage, rule = kind == KindRule;
            Show(scheduleEditButton, message);
            Show(scheduleGoOnButton, message || rule);
            Show(scheduleCancelButton, message || rule);
            bool listed = idle && advancedListing != null && advancedPrompts != null;
            string state = Str(source, "state");
            scheduleEditButton.Enabled = listed && message && state == "waiting";
            scheduleCancelButton.Enabled = idle && advancedListing != null && source != null &&
                                           !Equals(Get(source, "being_sent"), true) && Str(source, "reason") != "withdraw_refused";
            scheduleGoOnButton.Enabled = idle && advancedListing != null && source != null && state == "held";
            Dictionary<string, object> queue = advancedListing == null ? null : AdvancedItem(PromptQueueId);
            bool standing = queue != null && Standing(queue);
            Show(scheduleAddButton, standing);
            scheduleAddButton.Enabled = listed && standing;
        }

        /// History's Delete completed (N)..., offered while completed messages are listed and nothing else runs.
        partial void HistoryButtonsUpdated(Dictionary<string, object> row, bool idle)
        {
            if (clearDoneButton == null) return;
            string text = Word("page.scheduled.clear", "Delete completed ({n})...", "n", joinedDone.Count);
            if (clearDoneButton.Text != text)
            {
                clearDoneButton.Text = text;
                clearDoneButton.AccessibleName = text;
            }
            Show(clearDoneButton, joinedDone.Count > 0);
            clearDoneButton.Enabled = idle && advancedListing != null && advancedPrompts != null && joinedDone.Count > 0;
            if (doneNote != null && ListRowId(Selected(historyList)) != doneNoteFor) doneNote = null;
            if (doneNote != null && historyNote != null) SetNote(historyNote, doneNote);
        }

        /// Shown or hidden by its own bit, so nothing is laid out again while it stays as it was.
        private static void Show(Control control, bool shown)
        {
            if (control != null && Soft.OwnVisible(control) != shown) control.Visible = shown;
        }

        /// A double click on a row of this edition's own: a waiting message opens its editor.
        partial void EditionRowOpened(Dictionary<string, object> row)
        {
            if (Str(row, RowKindKey) == KindMessage) EditChosen();
        }

        // ---------------------------------------------------------------- acted on
        private Dictionary<string, object> ChosenRow(out string kind)
        {
            Dictionary<string, object> chosen = Selected(pendingList);
            kind = Str(chosen, RowKindKey);
            return Map(chosen, RowSourceKey);
        }

        private void EditChosen()
        {
            string kind;
            Dictionary<string, object> row = ChosenRow(out kind);
            if (kind == KindMessage && scheduleEditButton.Enabled) OpenEditor(row);
        }

        private void CancelChosen()
        {
            string kind;
            Dictionary<string, object> row = ChosenRow(out kind);
            if (row == null || !scheduleCancelButton.Enabled) return;
            if (kind == KindRule) CancelReset(Whole(Get(row, "rule_id")));
            else if (kind == KindMessage) CancelPrompt(Whole(Get(row, "prompt_id")));
        }

        private void GoOnChosen()
        {
            string kind;
            Dictionary<string, object> row = ChosenRow(out kind);
            if (row == null || !scheduleGoOnButton.Enabled) return;
            if (kind == KindRule) GoOnReset(Whole(Get(row, "rule_id")));
            else if (kind == KindMessage) GoOnPrompt(Whole(Get(row, "prompt_id")));
        }

        /// Delete completed (N)...: asked first, then the ids History lists, against the generation they were read at; how
        /// many were deleted, and how many kept because they changed, said beside History's buttons.
        private void ClearDone()
        {
            if (busy > 0 || advancedListing == null || advancedPrompts == null || joinedDone.Count == 0) return;
            var ids = new List<string>();
            foreach (Dictionary<string, object> row in joinedDone)
                ids.Add(Whole(Get(Map(row, RowSourceKey), "prompt_id")).ToString(CultureInfo.InvariantCulture));
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
                    string said = skipped > 0
                        ? Word("page.done.cleared_kept", "Deleted {deleted}, kept {skipped} that changed.", "deleted", deleted)
                              .Replace("{skipped}", skipped.ToString(CultureInfo.CurrentCulture))
                        : Word("page.done.cleared", "Deleted {deleted}.", "deleted", deleted);
                    doneNote = said;
                    doneNoteFor = ListRowId(Selected(historyList));
                    if (advancedNote != null) SetNote(advancedNote, said);
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

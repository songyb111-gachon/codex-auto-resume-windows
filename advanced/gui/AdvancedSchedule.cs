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
// wide as the widest kind's, so Cancel all and Rescan never move as the choice moves, and the row stands on one line in
// every language. Schedule... stands in one fixed place after them, whenever the prompt queue stands on, whatever row
// is chosen or none; the prompt queue's card on the Advanced features page has it too (AdvancedQueue.cs). A double click on a waiting message opens its editor
// (AdvancedEditor.cs, the one place a message is written); on a recovery, its menu, as always. Once the editor saves,
// the list is read again and the saved row is chosen.
//
// Completed messages are History: the delivered and handed-over messages of the last 30 days are rows of History's list,
// and History's one Clear history clears them with the finished recoveries - it asks, saying how many of each, hides the
// recoveries as it always did, sends the ids of the messages it shows and the generation it read
// (advanced-prompts-clear-done), and says how many were deleted and how many kept because they changed.
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
        private Button scheduleAddButton, scheduleEditButton, scheduleCancelButton, scheduleGoOnButton;
        // What the joined rows were last made from, and the rows themselves.
        private string scheduledShown;
        private readonly List<Dictionary<string, object>> joinedPending = new List<Dictionary<string, object>>();
        private readonly List<Dictionary<string, object>> joinedDone = new List<Dictionary<string, object>>();
        // What the last Clear history did of the messages, said under History until another row there is chosen.
        private string doneNote, doneNoteFor;

        // ---------------------------------------------------------------- built
        /// Pending's buttons: the chosen row's own in one group at the start - core's four for a recovery, then Edit...,
        /// Go on and Cancel for a message, Go on and Cancel for a rule.
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
            // Schedule... in one fixed place, after Cancel all and Rescan, there whenever the prompt queue stands on -
            // whatever row is chosen, or none (the owner's decision of 2026-10-24: a button never moves on Pending).
            // The prompt queue's card on the Advanced features page has it too.
            scheduleAddButton = MakeButton(Word("page.scheduled.add", "Schedule..."), false, delegate { OpenEditor(null); });
            scheduleAddButton.Margin = Pad(0, 0, 6, 0);
            scheduleAddButton.Visible = false;
            row.Controls.Add(scheduleAddButton);
            FitKindButtons();
        }

        /// The group as wide as the widest kind's buttons - Turn off and Turn on measured both - so what follows it never
        /// moves as the chosen row's kind changes. Each button is measured as it stands with nothing held (NaturalWidth),
        /// so the widths SpreadKindButtons gives are never measured into the next. Asked when the words are made and when
        /// the buttons are updated, never from a layout.
        private void FitKindButtons()
        {
            if (kindButtons == null) return;
            int recovery = Across(retryButton) + Across(cancelButton) + Across(timelineButton) +
                           Math.Max(Across(threadButton, S("action.thread_off", "Turn off for this conversation")),
                                    Across(threadButton, S("action.thread_on", "Turn on for this conversation")));
            int message = Across(scheduleEditButton) + Across(scheduleGoOnButton) + Across(scheduleCancelButton);
            int widest = Math.Max(recovery, message);
            // Held at that width both ways: a size measured while one kind's buttons are shown and the other's not yet
            // hidden is never kept (the layout audit found the group 920 px wide with no row chosen, all seven counted).
            if (kindButtons.MinimumSize.Width != widest) kindButtons.MinimumSize = new Size(widest, 0);
            if (kindButtons.MaximumSize.Width != widest) kindButtons.MaximumSize = new Size(widest, 0);
        }

        /// What `button` takes along the row with nothing held - its width and its margins - saying `text` (its own words
        /// where null).
        private int Across(Button button, string text = null)
        {
            return button == null ? 0 : NaturalWidth(button, text) + button.Margin.Horizontal;
        }

        /// The chosen kind's own buttons - a message's three, a rule's two - share the group's width, each as wide as it
        /// stands and the rest of the room dealt out evenly, so the gap after the group is the gap between any two buttons.
        /// Up to v0.6.19-beta.3 they stood as they were and the rest of the group, held as wide as a recovery's four, was a
        /// gap before Cancel all (the owner, 2026-10-25). A recovery's own four are as they stand.
        private void SpreadKindButtons(params Button[] shown)
        {
            if (kindButtons == null) return;
            int height = scheduleEditButton.MinimumSize.Height;
            var widths = new int[shown.Length];
            int taken = 0;
            for (int i = 0; i < shown.Length; i++)
            {
                widths[i] = NaturalWidth(shown[i], null);
                taken += widths[i] + shown[i].Margin.Horizontal;
            }
            int rest = Math.Max(0, kindButtons.MinimumSize.Width - taken);
            for (int i = 0; i < shown.Length; i++)
                widths[i] += rest / shown.Length + (i == shown.Length - 1 ? rest % shown.Length : 0);
            foreach (Button button in new[] { scheduleEditButton, scheduleGoOnButton, scheduleCancelButton })
            {
                int index = Array.IndexOf(shown, button);
                int width = index >= 0 ? widths[index] : Px(ButtonLeast);
                if (button.MinimumSize.Width != width) button.MinimumSize = new Size(width, height);
            }
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
            // Each row told whether it is the one, as a list with no window of its own keeps no SelectedIndices to clear.
            foreach (ListViewItem item in pendingList.Items)
            {
                bool one = Str(item.Tag as Dictionary<string, object>, RowKeyKey) == key;
                if (item.Selected != one) item.Selected = one;
                if (one) item.Focused = true;
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
            var cells = new[] { thread != null ? ConversationOf(thread) : Word("name.reset_credit", "Reset credit"), RuleStateShort(rule),
                                Word("page.pending.kind.rule", "Reset rule"), RuleWhen(rule), "", "" };
            return Joined(KindRule, "rule " + Whole(Get(rule, "rule_id")).ToString(CultureInfo.InvariantCulture), code, rule,
                          cells, stands + " · " + what);
        }

        /// When one rule acts, short enough for Pending's Next check column: its limit ("the 5-hour limit"), and which of its
        /// resets where it is not the next one ("the 5-hour limit (3 from now)") - in the words the whole sentence is made
        /// of (RuleWhat), which is what Why it is waiting says of the row. Up to v0.6.19-beta.3 the column held that whole
        /// sentence, cut to "the 5-hour..." in a window of the opening size (the owner, 2026-10-25).
        private string RuleWhen(Dictionary<string, object> rule)
        {
            int minutes = Whole(Get(rule, "minutes")), ordinal = Whole(Get(rule, "ordinal"));
            return ordinal <= 1 ? WindowWord(minutes) : WindowWord(minutes) + " (" + OrdinalWord(ordinal) + ")";
        }

        /// Where one rule stands, in a word short enough for Pending's Status column; the whole sentence (RuleStateWord) is
        /// what Why it is waiting says of the row.
        private string RuleStateShort(Dictionary<string, object> rule)
        {
            string state = Str(rule, "state");
            if (Equals(Get(rule, "being_sent"), true)) return Word("page.resets.state.being_sent", "being sent");
            if (state == "held") return Word("page.pending.rule.held", "held");
            if (state == "ready") return Word("page.resets.state.due", "due");
            object counted = Get(rule, "counted");
            if (state == "counting" && counted is double)
                return Word("page.resets.state.counting", "{n} of {of} counted", "n", Whole(counted))
                    .Replace("{of}", Whole(Get(rule, "ordinal")).ToString(CultureInfo.CurrentCulture));
            return Word("page.queue.state.waiting", "waiting");
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
            // Its times as a recovery's are written in History (When): when it was due, when it finished.
            var cells = new[] { ConversationOf(Str(row, "thread_id")), outcome, Word("page.pending.kind.message", "Scheduled message"),
                                When(Number(row, "due_at")), When(Number(row, "finished_at")) };
            return Joined(KindDone, "done " + Whole(Get(row, "prompt_id")).ToString(CultureInfo.InvariantCulture), "recovered",
                          row, cells, outcome);
        }

        // ---------------------------------------------------------------- offered
        /// The chosen Pending row's own buttons, by its kind: a message's Edit..., Go on and Cancel, a rule's Go on and
        /// Cancel, shown only for them (core's four only for a recovery).
        partial void PendingButtonsUpdated(Dictionary<string, object> row, bool idle)
        {
            if (scheduleEditButton == null) return;
            // Measured again here, with the words and the scale the window has now: the group's width taken when it was
            // built was the buttons' before the window was scaled to its screen (at 150% the group stood 918 px for
            // buttons of 827, and Schedule... went to a line of its own).
            FitKindButtons();
            string kind = Str(row, RowKindKey);
            Dictionary<string, object> source = Map(row, RowSourceKey);
            bool message = kind == KindMessage, rule = kind == KindRule;
            Show(scheduleEditButton, message);
            Show(scheduleGoOnButton, message || rule);
            Show(scheduleCancelButton, message || rule);
            if (message) SpreadKindButtons(scheduleEditButton, scheduleGoOnButton, scheduleCancelButton);
            else if (rule) SpreadKindButtons(scheduleGoOnButton, scheduleCancelButton);
            else SpreadKindButtons();
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

        /// History's Clear history, offered while completed messages are listed too - it clears them with the recoveries -
        /// and what the last one said, until another row there is chosen.
        partial void HistoryButtonsUpdated(Dictionary<string, object> row, bool idle)
        {
            if (historyClear == null) return;
            if (joinedDone.Count > 0 && advancedListing != null && advancedPrompts != null) historyClear.Enabled = idle;
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

        /// Clear history while History lists completed messages (the owner's decision of 2026-10-24: one action, not two):
        /// asked first, saying how many finished recoveries it hides and how many delivered messages it deletes; then the
        /// recoveries hidden as Clear history always hid them (clear-history), and only the completed messages it showed
        /// that are unchanged since deleted, against the generation they were read at (advanced-prompts-clear-done); how
        /// many it deleted and how many it kept because they changed said under History. Nothing waiting, held, cancelled
        /// or failed, and nothing of Codex's, is touched.
        partial void ClearHistoryPressed(ref bool handled)
        {
            if (joinedDone.Count == 0 || advancedListing == null || advancedPrompts == null) return;
            handled = true;
            if (busy > 0) return;
            int recoveries = 0;
            foreach (ListViewItem item in historyList.Items)
            {
                var row = item.Tag as Dictionary<string, object>;
                if (row != null && !EditionRow(row) && !IsDemo(row) && Number(row, "outcome_at") > 0) recoveries++;
            }
            var ids = new List<string>();
            foreach (Dictionary<string, object> row in joinedDone)
                ids.Add(Whole(Get(Map(row, RowSourceKey), "prompt_id")).ToString(CultureInfo.InvariantCulture));
            string question = recoveries > 0
                ? Word("page.confirm.clear_both",
                       "Hide {recoveries} finished recoveries from the history and delete {n} delivered messages? Messages that changed since, and waiting, held, cancelled and failed ones, are kept, and nothing in Codex changes.",
                       "n", ids.Count).Replace("{recoveries}", recoveries.ToString(CultureInfo.CurrentCulture))
                : Word("page.confirm.clear",
                       "Delete {n} completed messages from this list? Waiting, held, cancelled and failed ones are kept, and nothing in Codex changes.",
                       "n", ids.Count);
            if (!AskAdvanced(question, Affirm(S("action.clear_history", "Clear history")))) return;
            string generation = Get(advancedPrompts, "generation") is double
                ? Whole(Get(advancedPrompts, "generation")).ToString(CultureInfo.InvariantCulture) : AdvancedGeneration();
            string argument = "{\"prompts\":[" + string.Join(",", ids.ToArray()) + "],\"generation\":" + generation + "}";
            MethodInvoker messages = delegate
            {
                AdvancedCall("advanced-prompts-clear-done", argument, true, delegate(Dictionary<string, object> reply)
                {
                    Dictionary<string, object> result = AdvancedResult(reply);
                    if (AdvancedDone(result))
                    {
                        int deleted = Whole(Get(result, "deleted")), skipped = Whole(Get(result, "skipped"));
                        doneNote = skipped > 0
                            ? Word("page.done.cleared_kept", "Deleted {deleted}, kept {skipped} that changed.", "deleted", deleted)
                                  .Replace("{skipped}", skipped.ToString(CultureInfo.CurrentCulture))
                            : Word("page.done.cleared", "Deleted {deleted}.", "deleted", deleted);
                        doneNoteFor = ListRowId(Selected(historyList));
                        advancedPrompts = result;
                        FillScheduled();
                    }
                    else
                    {
                        ReadPrompts(null);
                        TellAdvanced(PromptRefusal(Str(result, "refusal")));
                    }
                });
            };
            if (recoveries == 0)
            {
                messages();
                return;
            }
            // The recoveries first, as Clear history hides them; the messages once that has answered.
            AdvancedCall("clear-history", null, true, delegate(Dictionary<string, object> reply)
            {
                Report(reply);
                RefreshAfterChange();
                messages();
            });
        }
    }
}

// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the prompt queue on the Advanced features page, and on Pending's Scheduled group (v0.6.15-beta).
//
// While prompt_queue is on or watched, its column has a card under its limits that says messages are scheduled on Pending >
// Scheduled, with Go to Scheduled (v0.6.19, issue #50: one place for one result). There (AdvancedSchedule.cs) each message
// is a row with Edit..., Cancel and Go on, and Schedule a message... opens the editor (AdvancedEditor.cs). Cancel takes back
// one Codex already holds (the owner's answer of 2026-10-09); one being sent it no longer reaches. Each request is the
// bridge's (advanced-prompts, advanced-prompt-add, advanced-prompt-edit, advanced-prompt-cancel, advanced-prompt-go-on,
// advanced-prompts-clear-done), with the generation the list was read at.
//
// Nothing here draws anything the page does not draw already.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string PromptQueueId = "prompt_queue";
        private const int SeriesMost = 30;

        // advanced-prompts' last answer, or null where it was not read or the read failed.
        private Dictionary<string, object> advancedPrompts;
        private Button queueAdd;

        private string QueueShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != PromptQueueId) return "";
            return AdvancedWritten(advancedPrompts) + "|" + AdvancedWritten(ConversationsWritten());
        }

        /// Read advanced-prompts, keep it, and show it on the page and on Pending; `done` once it is shown.
        private void ReadPrompts(MethodInvoker done)
        {
            AdvancedCall("advanced-prompts", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedPrompts = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                FillScheduled();
                if (done != null) done();
            });
        }

        /// The prompts still to go, in their order.
        private List<Dictionary<string, object>> PendingPrompts()
        {
            var found = new List<Dictionary<string, object>>();
            foreach (object entry in Items(advancedPrompts, "prompts") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                string state = Str(row, "state");
                if (row != null && (state == "waiting" || state == "ready" || state == "held")) found.Add(row);
            }
            return found;
        }

        /// When one goes, in words: after this turn, at a time, or a series with how many of it went.
        private string PromptWhen(Dictionary<string, object> row)
        {
            string trigger = Str(row, "trigger");
            if (trigger == "after_turn") return Word("page.queue.when.after_turn", "After this turn");
            double at = Get(row, "due_at") is double ? (double)Get(row, "due_at") : 0;
            string time = ClockTime(at);
            if (trigger == "at_time") return Word("page.queue.at", "at {time}", "time", time);
            string every = Str(row, "every") == "week" ? Word("page.queue.when.weekly", "Every week")
                                                       : Word("page.queue.when.daily", "Every day");
            return Word("page.queue.series", "{every} at {time}, {sent} of {n}", "every", every).Replace("{time}", time)
                   .Replace("{sent}", Whole(Get(row, "sent_count")).ToString(CultureInfo.CurrentCulture))
                   .Replace("{n}", Whole(Get(row, "occurrences")).ToString(CultureInfo.CurrentCulture));
        }

        /// Where one stands, in words.
        private string PromptState(Dictionary<string, object> row)
        {
            if (Str(row, "reason") == "withdraw_refused")
                return Word("page.queue.state.refused", "Codex would not give it back; it is never sent again");
            if (Str(row, "state") == "held") return Word("page.queue.state.held", "held for you: go on or cancel");
            if (Equals(Get(row, "in_codex"), true)) return Word("page.queue.state.in_codex", "queued in Codex - Cancel takes it back");
            if (Equals(Get(row, "being_sent"), true)) return Word("page.queue.state.being_sent", "being sent");
            return Word("page.queue.state.waiting", "waiting");
        }

        // ---------------------------------------------------------------- the card
        private void BuildQueue(Dictionary<string, object> item)
        {
            ForgetQueueCard();
            if (Str(item, "id") != PromptQueueId || !Standing(item) || advancedPrompts == null) return;
            TableLayoutPanel card = NewGroup(Word("page.queue.title", "Queued messages"), advancedStack);
            // v0.6.19 (#50): one place for one result - messages are written, changed and cancelled as rows of Pending's
            // one list (AdvancedSchedule.cs), and this card says so and goes there.
            card.Controls.Add(HelpText(Word("page.queue.moved", "Messages are scheduled on {pending}.", "pending",
                                            S("nav.pending", "Pending"))));
            queueAdd = CardButton(card, Word("page.queue.go", "Open {pending}", "pending", S("nav.pending", "Pending")),
                                  delegate { GoToScheduled(); });
            queueAdd.Margin = Pad(0, 8, 0, 4);
        }

        /// Pending, with the first message chosen where one waits.
        private void GoToScheduled()
        {
            ShowPage("pending");
            FillScheduled();
            foreach (Dictionary<string, object> row in joinedPending)
                if (Str(row, RowKindKey) == KindMessage)
                {
                    ChooseScheduledRow(Str(row, RowKeyKey));
                    break;
                }
        }

        private void ForgetQueueCard()
        {
            queueAdd = null;
        }

        private void UpdateQueueButtons(bool idle)
        {
            bool listed = idle && advancedListing != null && advancedPrompts != null;
            if (queueAdd != null) queueAdd.Enabled = listed;
        }

        /// The next time the hour chosen comes, in Codex's seconds: today's, or tomorrow's where it has gone by.
        private static double NextHour(int hour)
        {
            DateTime now = DateTime.Now;
            DateTime at = now.Date.AddHours(hour);
            if (at <= now.AddMinutes(1)) at = at.AddDays(1);
            return (at.ToUniversalTime() - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        }

        private void CancelPrompt(int prompt)
        {
            if (busy > 0 || advancedListing == null) return;
            string argument = "{\"prompt\":" + prompt.ToString(CultureInfo.InvariantCulture) + ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-prompt-cancel", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.reset_cancelled", "Cancelled."));
                ReadAdvanced(null);
                if (advancedOpen != PromptQueueId) ReadPrompts(null);
                if (!AdvancedDone(result)) TellAdvanced(PromptRefusal(Str(result, "refusal")));
            });
        }

        private void GoOnPrompt(int prompt)
        {
            if (busy > 0 || advancedListing == null) return;
            string argument = "{\"prompt\":" + prompt.ToString(CultureInfo.InvariantCulture) + ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-prompt-go-on", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.prompt_added", "Queued."));
                ReadAdvanced(null);
                if (advancedOpen != PromptQueueId) ReadPrompts(null);
                if (!AdvancedDone(result)) TellAdvanced(PromptRefusal(Str(result, "refusal")));
            });
        }

        private string PromptRefusal(string refusal)
        {
            if (refusal == "prompt_refused")
                return Word("page.refused.prompt_refused", "That message cannot be queued: it is empty or too long, holds a marker of this product's, or is one of its own continuations.");
            if (refusal == "queue_full")
                return Word("page.refused.queue_full", "As many messages are queued as may: five for a conversation, twenty in all. Cancel one to queue another.");
            if (refusal == "dependency_unknown")
                return Word("page.refused.dependency_unknown", "No message is queued before it in that conversation, so it cannot wait for one.");
            return ResetRefusal(refusal);
        }
    }
}

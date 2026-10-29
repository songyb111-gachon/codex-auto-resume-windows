// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - keep going on the Advanced features page (v0.6.15-beta).
//
// While keep_going is on, its column has a card under its limits: each conversation kept going, a flat line saying how
// many continuations it has had of how many it may have now, with Stop under it; then the form one is picked with - the
// conversation and how many continuations, 1 to 10 - and Keep it going..., which asks first. Until MK is measured on the
// Codex in force no more than three are sent, which the card says. Each request is the bridge's (advanced-keep-going,
// advanced-keep-going-set, advanced-keep-going-stop), with the generation the list was read at, and the card is read
// again after each.
//
// Nothing here draws anything the page does not draw already: the cards, captions, help lines, rows, drop-downs and
// buttons are the Settings page's.
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
        private const string KeepGoingId = "keep_going";
        private const int KeepGoingMost = 10;

        // advanced-keep-going's last answer, or null where it was not read or the read failed.
        private Dictionary<string, object> advancedKeepGoing;
        // The card's form as it was built, and each conversation's Stop.
        private SoftCombo keepConversation, keepCount;
        private Button keepAdd;
        private readonly List<Button> keepStops = new List<Button>();

        /// What the keep going card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string KeepGoingShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != KeepGoingId) return "";
            return AdvancedWritten(advancedKeepGoing) + "|" + AdvancedWritten(ConversationsWritten());
        }

        /// Read advanced-keep-going, keep it, and show it; `done` once it is shown.
        private void ReadKeepGoing(MethodInvoker done)
        {
            AdvancedCall("advanced-keep-going", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedKeepGoing = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        /// The open capability's card, while keep_going is on or watched (v0.6.16-beta.3): the conversations kept going, then
        /// the form.
        private void BuildKeepGoing(Dictionary<string, object> item)
        {
            ForgetKeepGoingCard();
            if (Str(item, "id") != KeepGoingId || !Standing(item) || advancedKeepGoing == null) return;
            TableLayoutPanel card = NewGroup(Word("page.keep.title", "Conversations kept going"), advancedStack);
            int shown = 0;
            foreach (object entry in Items(advancedKeepGoing, "rows") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                if (row == null || Str(row, "state") != "on") continue;
                shown++;
                string thread = Str(row, "thread_id");
                string text = Word("page.keep.line", "{conversation} · kept going {used} of {allowed}",
                                   "conversation", ConversationOf(thread))
                              .Replace("{used}", Mirror.Embed(Whole(Get(row, "used")).ToString(CultureInfo.CurrentCulture)))
                              .Replace("{allowed}", Mirror.Embed(Whole(Get(row, "allowed")).ToString(CultureInfo.CurrentCulture)));
                Label line = HelpText(text);
                line.ForeColor = Ink;
                line.Margin = Pad(0, 6, 0, 2);
                card.Controls.Add(line);
                Button stop = CardButton(card, Word("page.keep.stop", "Stop"), delegate { StopKeepGoing(thread); });
                stop.Tag = thread;
                stop.AccessibleName = Word("page.keep.stop", "Stop") + " " + text;
                keepStops.Add(stop);
            }
            if (shown == 0) card.Controls.Add(HelpText(Word("page.keep.none", "No conversation is kept going.")));
            string conversation = Word("page.resets.field.conversation", "Conversation");
            keepConversation = NewResetCombo(conversation, 260, "keep.conversation");
            foreach (KeyValuePair<string, string> pair in Conversations())
                keepConversation.Items.Add(new Choice(pair.Key, pair.Value));
            PickDraft(keepConversation, "keep.conversation");
            card.Controls.Add(NewRow(conversation, keepConversation));
            if (keepConversation.Items.Count == 0)
                card.Controls.Add(HelpText(Word("page.resets.no_conversation",
                    "No conversation is listed yet. One is offered here once Pending or History lists it.")));
            string count = Word("page.keep.count", "How many continuations");
            keepCount = NewResetCombo(count, 120, "keep.count");
            for (int n = 1; n <= KeepGoingMost; n++)
                keepCount.Items.Add(new Choice(n.ToString(CultureInfo.InvariantCulture), n.ToString(CultureInfo.CurrentCulture)));
            PickDraft(keepCount, "keep.count");
            if (keepCount.SelectedItem == null) keepCount.SelectedIndex = 2;
            card.Controls.Add(NewRow(count, keepCount));
            if (Equals(Get(advancedKeepGoing, "count_capped"), true))
                card.Controls.Add(HelpText(Word("page.keep.capped",
                    "Until this has been measured on this Codex, no more than {n} are sent.", "n",
                    Whole(Get(Map(advancedKeepGoing, "limits"), "unmeasured")))));
            keepAdd = CardButton(card, Word("page.keep.button", "Keep it going..."), delegate { AddKeepGoing(); });
            keepAdd.Margin = Pad(0, 8, 0, 4);
        }

        private void ForgetKeepGoingCard()
        {
            keepConversation = keepCount = null;
            keepAdd = null;
            keepStops.Clear();
        }

        private void UpdateKeepGoingButtons(bool idle)
        {
            bool listed = idle && advancedListing != null && advancedKeepGoing != null;
            if (keepAdd != null)
                keepAdd.Enabled = listed && keepConversation != null && keepConversation.SelectedItem != null &&
                                  keepCount != null && keepCount.SelectedItem != null;
            foreach (Button button in keepStops) button.Enabled = listed;
        }

        private void AddKeepGoing()
        {
            if (busy > 0 || advancedListing == null || keepConversation == null || keepCount == null) return;
            var conversation = keepConversation.SelectedItem as Choice;
            var count = keepCount.SelectedItem as Choice;
            if (conversation == null || count == null) return;
            string question = Word("page.confirm.keep_going",
                "Keep {conversation} going for up to {n} continuations? Each is sent after a turn that ended well, and it stops on no progress, a finished plan or an active goal.",
                "conversation", conversation.ToString()).Replace("{n}", Mirror.Embed(count.ToString()));
            if (!AskAdvanced(question, Affirm(Word("page.keep.button", "Keep it going...")))) return;
            string argument = "{\"thread_id\":" + Json.Escape(conversation.Value) + ",\"count\":" + count.Value +
                              ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-keep-going-set", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.keep_going", "It keeps going from its next finished turn."));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepGoingRefusal(Str(result, "refusal")));
            });
        }

        private void StopKeepGoing(string thread)
        {
            if (busy > 0 || advancedListing == null || thread == null) return;
            string argument = "{\"thread_id\":" + Json.Escape(thread) + ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-keep-going-stop", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.reset_cancelled", "Cancelled."));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepGoingRefusal(Str(result, "refusal")));
            });
        }

        private string KeepGoingRefusal(string refusal)
        {
            if (refusal == "keep_count_invalid")
                return Word("page.refused.keep_count_invalid", "That number is not one on offer. Nothing was changed.");
            return ResetRefusal(refusal);
        }
    }
}

// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Advanced features page's Keep it on and Send now (v0.6.14, stage 3b).
//
// Keep it on (the owner's K8): for the open capability while it is on or watched, a card under its limits that says
// whether it turns itself off when something it relies on goes wrong, and what it noted instead where it is kept on - and
// three buttons, each shown where it can act: Keep it on..., Also send again when unsure... (with Keep on, never for a
// capability that resends itself, nor for an action, which sends no continuation) and Let it turn itself off. Each
// turn-on asks first in the window's own dialog, with its warning, the safe answer the default (AskAdvanced), and sends
// exactly what that warning was, confirmed in its words (advanced-keep-on); letting go asks nothing, as turning off never
// does. What a kept-on capability noted is a line in the accent under its state on its first card (KeptText), beside what
// turned one off (TrippedText); turning it on again is how the person confirms again.
//
// Send now: while Send now is on - not watched: the bridge refuses a request it could only journal - a card of the
// recoveries waiting now, flat lines from the pending list the window already holds (SnapshotApplied), each with its own
// Send now... under it, as each rule has its Remove; pressing one asks first, and sends that record's interruption id
// (advanced-send-now). The watcher sends it at its next look, if every check passes; the list then shows what happened.
//
// Nothing here draws anything the page does not draw already: the cards, captions, help lines and buttons are the
// Settings page's, and the lines in the accent are the page's own.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // The capability that is Send now (registry.SEND_NOW), whose card lists the waiting recoveries.
        private const string SendNowId = "send_now";
        // The public codes of a record that waits (domain/public.py, WAITING_CODES): the rows Send now offers.
        private static readonly string[] WaitingCodes =
            { "waiting_reset", "waiting_usage", "waiting_thread", "scheduled", "failed_retryable" };

        // The pending list as the last snapshot held it (SnapshotApplied), or null before one.
        private List<object> advancedPending;
        // The open capability's Keep it on buttons, and each waiting recovery's Send now, as its cards were built.
        private Button keepOnButton, sendAgainButton, letGoButton;
        private readonly List<Button> sendNowButtons = new List<Button>();

        // ---------------------------------------------------------------- what the cards show
        /// The waiting recoveries the snapshot holds, in its order: the rows Send now is offered for.
        private List<Dictionary<string, object>> WaitingRows()
        {
            var rows = new List<Dictionary<string, object>>();
            foreach (object entry in advancedPending ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                if (row != null && Str(row, "interruption_id") != null && Array.IndexOf(WaitingCodes, Str(row, "code")) >= 0)
                    rows.Add(row);
            }
            return rows;
        }

        /// What the open capability's Keep it on and Send now cards are built from, for ShowAdvancedDetail to compare.
        private string KeptShown(Dictionary<string, object> item)
        {
            if (item == null) return "";
            string shown = AdvancedWritten(Get(item, "keep_on")) + AdvancedWritten(Get(item, "send_again")) +
                           AdvancedWritten(Get(item, "notice"));
            if (Str(item, "id") == SendNowId) shown += "|" + AdvancedWritten(WaitingRows());
            return shown;
        }

        /// What a kept-on capability noted in place of turning itself off, in words, or null where it noted nothing.
        private string KeptText(Dictionary<string, object> item)
        {
            if ((Str(item, "stored") ?? StateOff) == StateOff || !Equals(Get(item, "keep_on"), true)) return null;
            string notice = Str(item, "notice");
            if (notice == "duplicate_seen")
                return Word("page.kept.duplicate_seen", "A continuation it sent again was found twice, so sending again is off. It stays on.");
            if (notice == "statement_changed")
                return Word("page.kept.statement_changed", "It stayed on although what it does has changed. Read it again and turn it on to confirm.");
            if (notice == "measurement_failed")
                return Word("page.kept.measurement_failed", "It stayed on although a measurement of what it relies on failed.");
            if (notice == "failed_here")
                return Word("page.kept.failed_here", "It stayed on although a compatibility check of what it relies on failed on this computer.");
            if (notice == "incompatible")
                return Word("page.kept.incompatible", "It stayed on although the compatibility data says what it relies on does not work with this version of Codex.");
            if (notice == "local_check_failed")
                return Word("page.kept.local_check_failed", "It stayed on although a check on this computer found that this version of Codex lacks what it relies on.");
            if (notice == "hook_exception")
                return Word("page.kept.hook_exception", "It stayed on after an error of its own, and skipped the recovery it happened in.");
            if (notice == "submission_unknown")
                return Word("page.kept.submission_unknown", "It stayed on although it could not prove that a continuation it sent arrived.");
            if (notice == "engine_changed")
                return Word("page.kept.engine_changed", "It stayed on although the version of Codex changed. Turn it on again to confirm this version.");
            return null;
        }

        // ---------------------------------------------------------------- the cards
        /// The open capability's Keep it on card, while it is stored on or watched: whether it turns itself off, and the
        /// buttons that can act on that now.
        private void BuildKeepOn(Dictionary<string, object> item)
        {
            keepOnButton = sendAgainButton = letGoButton = null;
            if ((Str(item, "stored") ?? StateOff) == StateOff) return;
            string id = Str(item, "id");
            bool kept = Equals(Get(item, "keep_on"), true), again = Equals(Get(item, "send_again"), true);
            TableLayoutPanel card = NewGroup(Word("page.keep_on", "Keep it on"), advancedStack);
            Label state = HelpText(!kept ? Word("page.keep_on.off", "It turns itself off when something it relies on goes wrong.")
                                   : again ? Word("page.keep_on.again", "Kept on, and an uncertain continuation is sent once more.")
                                   : Word("page.keep_on.on", "Kept on: it does not turn itself off."));
            state.ForeColor = Ink;
            card.Controls.Add(state);
            if (!kept) keepOnButton = CardButton(card, Word("page.keep_on.turn_on", "Keep it on..."), delegate { KeepOnAdvanced(id, false); });
            if (kept && !again && !Equals(Get(item, "resends"), true) && !IsAction(item))
                sendAgainButton = CardButton(card, Word("page.keep_on.send_again", "Also send again when unsure..."),
                                             delegate { KeepOnAdvanced(id, true); });
            if (kept) letGoButton = CardButton(card, Word("page.keep_on.turn_off", "Let it turn itself off"), delegate { LetGoAdvanced(id); });
        }

        /// Send now's card, while it is on: each recovery waiting now, a line with its own Send now... under it.
        private void BuildSendNow(Dictionary<string, object> item)
        {
            sendNowButtons.Clear();
            if (Str(item, "id") != SendNowId || Str(item, "state") != StateArmed) return;
            TableLayoutPanel card = NewGroup(Word("page.send_now.title", "Waiting recoveries"), advancedStack);
            List<Dictionary<string, object>> rows = WaitingRows();
            if (rows.Count == 0) card.Controls.Add(HelpText(Word("page.send_now.none", "No recovery is waiting.")));
            foreach (Dictionary<string, object> row in rows)
            {
                string key = Str(row, "interruption_id");
                Label line = HelpText(Conversation(row) + " · " + CodeLabel(row));
                line.ForeColor = Ink;
                line.Margin = Pad(0, 6, 0, 2);
                card.Controls.Add(line);
                Button send = CardButton(card, Word("page.send_now.button", "Send now..."), delegate { SendNowAdvanced(key); });
                send.Tag = key;
                send.AccessibleName = Word("page.send_now.button", "Send now...") + " " + Conversation(row);
                sendNowButtons.Add(send);
            }
        }

        /// A button on a card, under what it acts on, as a rule's Remove is.
        private Button CardButton(TableLayoutPanel card, string text, EventHandler onClick)
        {
            Button button = MakeButton(text, false, onClick);
            button.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            button.Margin = Pad(0, 2, 0, 8);
            card.Controls.Add(button);
            return button;
        }

        /// What the Keep it on and Send now buttons may do now: nothing while another action is under way; the turn-ons
        /// only where an administrator's policy admits what they would do - Send again, the once-more capability too.
        private void UpdateKeptButtons(bool idle)
        {
            string id = advancedOpen;
            bool listed = idle && advancedListing != null && id != null;
            if (keepOnButton != null) keepOnButton.Enabled = listed && PolicyAdmits(id) && Str(AdvancedItem(id), "state") != StateOff;
            if (sendAgainButton != null)
                sendAgainButton.Enabled = listed && PolicyAdmits(id) && PolicyAdmits("once_more_when_unsure") &&
                                          Str(AdvancedItem(id), "state") != StateOff;
            if (letGoButton != null) letGoButton.Enabled = listed;
            foreach (Button send in sendNowButtons) send.Enabled = listed;
        }

        // ---------------------------------------------------------------- acting
        /// Keep `id` on - with Send again, `again` - after its warning, the safe answer the default; sent with the
        /// generation the list was read at and the warning's words as the person's confirmation.
        private void KeepOnAdvanced(string id, bool again)
        {
            if (busy > 0 || advancedListing == null || AdvancedItem(id) == null) return;
            string name = AdvancedName(id);
            string question = again
                ? Word("page.confirm.send_again", "Also send again when unsure? When a continuation {name} sent cannot be proven to have arrived, it is sent once more with the same marker, between 15 minutes and 6 hours later, only if neither Codex's history nor its queue holds it and nothing has happened in the conversation since. If the first one arrives after all, the conversation gets the same continuation twice. If the marker is then found twice, sending again turns itself off. This departs from 0.2, A6, E2 and H2, and works only where your administrator's policy also allows Once more when unsure.", "name", name)
                : Word("page.confirm.keep_on", "Keep {name} on? It will not turn itself off. When what it does changes, a warning appears, a part of it fails, a continuation it sent cannot be proven to have arrived, or Codex is updated, it stays on and this page tells you; a part that fails skips only that one recovery. You can always turn it off here, from Codex or with every advanced feature at once. Its limits stay, and your administrator's policy still applies.", "name", name);
            string affirm = Affirm(again ? Word("page.keep_on.send_again", "Also send again when unsure...")
                                         : Word("page.keep_on.turn_on", "Keep it on..."));
            string argument = KeepOnArgument(id, true, again, AdvancedGeneration());
            if (!AskAdvanced(question, affirm)) return;
            AdvancedCall("advanced-keep-on", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) SetNote(advancedNote, Word("page.done.keep_on", "{name} is kept on.", "name", name));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepOnRefusal(result));
            });
        }

        /// Let `id` turn itself off again, Send again with it: it only ever does less, so nothing is asked.
        private void LetGoAdvanced(string id)
        {
            if (busy > 0 || AdvancedItem(id) == null) return;
            string name = AdvancedName(id);
            AdvancedCall("advanced-keep-on", KeepOnArgument(id, false, false, null), true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                    SetNote(advancedNote, Word("page.done.keep_on_off", "{name} turns itself off again when something goes wrong.", "name", name));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepOnRefusal(result));
            });
        }

        /// Ask, then send one waiting recovery's continuation at the watcher's next look.
        private void SendNowAdvanced(string key)
        {
            if (busy > 0 || key == null) return;
            if (!AskAdvanced(Word("page.confirm.send_now", "Send this recovery's continuation now? Every check still runs first; it does not wait for its schedule, a postponement or the 15 minutes since the last continuation."),
                             Affirm(Word("page.send_now.button", "Send now..."))))
                return;
            AdvancedCall("advanced-send-now", "{\"interruption_id\":" + Json.Escape(key) + "}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                    SetNote(advancedNote, Word("page.done.send_now", "Asked. If every check passes, the watcher sends it at its next look; the list shows what happened."));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepOnRefusal(result));
            });
        }

        /// The advanced-keep-on request: to keep it on, with the generation the list was read at and the warning's words
        /// confirmed - "keep_on", and "send_again" after it; to let it go, nothing but the capability and the two flags.
        internal static string KeepOnArgument(string id, bool keepOn, bool again, string generation)
        {
            var text = new StringBuilder("{\"capability\":").Append(Json.Escape(id))
                .Append(",\"keep_on\":").Append(keepOn ? "true" : "false")
                .Append(",\"send_again\":").Append(again ? "true" : "false");
            if (keepOn)
                text.Append(",\"generation\":").Append(generation ?? "null")
                    .Append(",\"confirmed\":[\"keep_on\"").Append(again ? ",\"send_again\"" : "").Append(']');
            return text.Append('}').ToString();
        }

        /// A button's words as the dialog's yes says them: without the dots that say a question follows.
        private static string Affirm(string text)
        {
            return (text ?? "").TrimEnd('.', '…', ' ', '。');
        }

        /// A refusal of Keep it on or Send now in words: one that is not on, said so; every other as the page says it.
        private string KeepOnRefusal(Dictionary<string, object> result)
        {
            if (Str(result, "refusal") == "not_on") return Word("page.refused.not_on", "Turn it on first.");
            return AdvancedRefusal(result);
        }
    }
}

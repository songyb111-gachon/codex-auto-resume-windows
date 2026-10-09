// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the reset actions on the Advanced features page, and Pending's scheduled ones (v0.6.14).
//
// Two capabilities act at a usage reset a person picks: a reset credit used when the limit they pick is reached
// (reset_credit), and a message of their own sent to a conversation when the window they pick resets (reset_message).
// While one is on, its column has a card under its limits: its rules, each a flat line saying what it waits for and
// where its count stands, with Cancel under it - Go on counting for one held over a gap, and Use a reset credit now
// for a credit due that waits for a click - then the form a rule is added with: the window (the 5-hour limit, the
// weekly one, and any other Codex reports) and which of its next resets or fills, from the next one to 9 from now -
// only the next for the weekly one; for a credit, how often and whether it asks first; for a message, the conversation
// and the words, counted to the bound. Add asks first, with what it will do. Each request is the bridge's
// (advanced-resets, advanced-reset-add, advanced-reset-cancel, advanced-reset-go-on, advanced-credit-now), with the
// generation the list was read at, and the card is read again after each. What is being written is kept while the
// card is built again, and the keyboard goes back to where it was.
//
// On Pending (PendingBuilt), a group under the list, shown only while something is scheduled: one flat line for each
// rule still to act, with Cancel - and Go on counting for one held over a gap - so a message waiting for a reset is seen
// beside the recoveries waiting for theirs.
// It is read when the status's counts of them change (surfaces.status).
//
// Nothing here draws anything the page does not draw already: the cards, captions, help lines, rows, drop-downs, text
// box and buttons are the Settings page's.
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
        private const string ResetCreditId = "reset_credit", ResetMessageId = "reset_message";
        private const int WeekMinutes = 10080, MostOrdinal = 9;

        // advanced-resets' last answer, or null where it was not read or the read failed; the status's counts of the
        // rules waiting as last seen, which a change of reads it again.
        private Dictionary<string, object> advancedResets;
        private string advancedResetCounts = "";
        // The open capability's form, as its card was built: the window, which one, how often, whether it asks, the
        // conversation, the words and their count, and Add; each rule's Cancel and Go on counting, and Use now.
        private SoftCombo resetFamily, resetOrdinal, resetRepeat, resetAsk, resetConversation;
        private SoftTextArea resetWords;
        private Label resetCount;
        private Button resetAdd;
        private readonly List<Button> resetCancels = new List<Button>();
        private readonly List<Button> resetGoOns = new List<Button>();
        private readonly List<Button> creditNowButtons = new List<Button>();
        // What is being written in each form ("credit.family", "message.words", ...), kept while its card is built again.
        private readonly Dictionary<string, string> resetDrafts = new Dictionary<string, string>();
        // Pending's group of what is scheduled, its card, its Cancel and Go on counting buttons, and what it was last
        // filled from.
        private Panel scheduledPage;
        private SoftStack scheduledHolder;
        private TableLayoutPanel scheduledCard, scheduledLines;
        private SoftPage scheduledScroll;
        private readonly List<Button> scheduledCancels = new List<Button>();
        private readonly List<Button> scheduledGoOns = new List<Button>();
        private string scheduledShown;

        private static bool IsResets(string id)
        {
            return id == ResetCreditId || id == ResetMessageId;
        }

        /// Whether `item` is the compatibility report, the one action with a card of its own (AdvancedReport.cs).
        private static bool IsReport(Dictionary<string, object> item)
        {
            return IsAction(item) && Str(item, "id") == ReportId;
        }

        /// What the reset cards are built from, for ShowAdvancedDetail to build them again only when it changed.
        private string ResetsShown(Dictionary<string, object> item)
        {
            if (item == null || !IsResets(Str(item, "id"))) return "";
            return AdvancedWritten(advancedResets) + "|" + AdvancedWritten(ConversationsWritten());
        }

        /// Read advanced-resets, keep it, and show it where it shows; `done` once it is shown.
        private void ReadResets(MethodInvoker done)
        {
            AdvancedCall("advanced-resets", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedResets = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                FillScheduled();
                if (done != null) done();
            });
        }

        /// The status's counts of the reset rules waiting (surfaces.status), written to compare: "" where none waits.
        private static string ResetCounts(Dictionary<string, object> advanced)
        {
            if (advanced == null || !(Get(advanced, "messages") is double || Get(advanced, "credit_rules") is double)) return "";
            return AdvancedWritten(Get(advanced, "messages")) + "," + AdvancedWritten(Get(advanced, "credit_rules")) + "," +
                   AdvancedWritten(Get(advanced, "ready"));
        }

        /// A snapshot's counts read: the rules read again when they changed - one added, due or ended, here or anywhere.
        private void ResetCountsApplied(Dictionary<string, object> reply)
        {
            string counts = ResetCounts(Map(Map(reply, "status"), "advanced"));
            if (counts == advancedResetCounts) return;
            advancedResetCounts = counts;
            ReadResets(null);
        }

        // ---------------------------------------------------------------- words
        /// A window family in words: the 5-hour limit, the weekly limit, or one of another length.
        private string WindowWord(int minutes)
        {
            if (minutes == 300) return Word("page.resets.window.300", "the 5-hour limit");
            if (minutes == WeekMinutes) return Word("page.resets.window.10080", "the weekly limit");
            return Word("page.resets.window.other", "the {n}-minute limit", "n", minutes);
        }

        /// Which of a window's next resets or fills, in words: the next one, or how many from now.
        private string OrdinalWord(int ordinal)
        {
            if (ordinal <= 1) return Word("page.resets.ordinal.1", "the next one");
            return Word("page.resets.ordinal.n", "{n} from now", "n", ordinal);
        }

        /// Where one rule stands, in words.
        private string RuleStateWord(Dictionary<string, object> rule)
        {
            string state = Str(rule, "state"), reason = Str(rule, "reason");
            if (Equals(Get(rule, "being_sent"), true)) return Word("page.resets.state.being_sent", "being sent");
            if (state == "held")
                return reason == "window_gone"
                    ? Word("page.resets.state.window_gone", "held: Codex no longer reports this window")
                    : Word("page.resets.state.count_gap", "held: this PC was off or paused for longer than the window, so a reset may have been missed");
            if (state == "ready")
            {
                if (reason == "ask_first") return Word("page.resets.state.ask_first", "due: waiting for your click");
                if (reason == "count_unknown") return Word("page.resets.state.count_unknown", "due: how many reset credits you have cannot be read");
                if (reason == "expiry_unknown") return Word("page.resets.state.expiry_unknown", "due: when your reset credits expire cannot be read");
                if (reason == "bound") return Word("page.resets.state.bound", "due: two were used today or seven this week");
                if (reason == "no_method") return Word("page.resets.state.no_method", "due: this Codex cannot use one from here; /usage in Codex can");
                if (reason == "nothing_waiting") return Word("page.resets.state.nothing_waiting", "due: no recovery is waiting for usage");
                return Word("page.resets.state.due", "due");
            }
            if (state == "counting")
            {
                object counted = Get(rule, "counted");
                string text = counted is double
                    ? Word("page.resets.state.counting", "{n} of {of} counted", "n", Whole(counted))
                          .Replace("{of}", Whole(Get(rule, "ordinal")).ToString(CultureInfo.CurrentCulture))
                    : Word("page.resets.state.starting", "counting starts at the next reading");
                object next = Get(rule, "next_reset");
                if (next is double)
                    text += " · " + Word("page.resets.state.next", "the window open now resets {time}", "time", When((double)next));
                return text;
            }
            if (state == "cancelled")
            {
                if (reason == "conversation_off") return Word("page.resets.state.conversation_off", "cancelled: its conversation was turned off");
                if (reason == "turned_off") return Word("page.resets.state.turned_off", "cancelled: the feature was turned off");
                return Word("page.resets.state.by_person", "cancelled");
            }
            if (reason == "spent") return Word("page.resets.state.spent", "a reset credit was used");
            if (reason == "nothing_to_reset") return Word("page.resets.state.nothing_to_reset", "nothing was used: no window needed a reset");
            if (reason == "no_credit") return Word("page.resets.state.no_credit", "nothing was used: there was no reset credit");
            if (reason == "lapsed") return Word("page.resets.state.lapsed", "nothing was used: the window reset first");
            if (reason == "delivered") return Word("page.resets.state.delivered", "sent");
            if (reason == "expired") return Word("page.resets.state.expired", "not sent: it waited too long");
            if (reason == "not_started") return Word("page.resets.state.not_started", "not sent: Codex did not start it");
            if (reason == "unknown") return Word("page.resets.state.unknown", "what came of it cannot be known");
            return Word("page.resets.state.done", "done");
        }

        /// What one rule does, at which reset, in words.
        private string RuleWhat(Dictionary<string, object> rule)
        {
            int minutes = Whole(Get(rule, "minutes")), ordinal = Whole(Get(rule, "ordinal"));
            if (Str(rule, "capability") == ResetCreditId)
                return ordinal == 0
                    ? Word("page.resets.rule.now", "A reset credit now, for {window}", "window", WindowWord(minutes))
                    : Word("page.resets.rule.credit", "A reset credit when {window} is reached ({which})", "window", WindowWord(minutes))
                          .Replace("{which}", OrdinalWord(ordinal));
            return Word("page.resets.rule.message", "A message to {conversation} when {window} resets ({which})", "window", WindowWord(minutes))
                .Replace("{which}", OrdinalWord(ordinal)).Replace("{conversation}", ConversationOf(Str(rule, "thread_id")));
        }

        /// One rule in words: what it does, at which reset, and where it stands.
        private string RuleLine(Dictionary<string, object> rule)
        {
            return RuleWhat(rule) + " · " + RuleStateWord(rule);
        }

        /// The conversations the snapshot names that are not turned off, as its lists have them: {thread id: label}, a
        /// label two share told apart by the start of each one's id.
        private Dictionary<string, string> Conversations()
        {
            var found = new Dictionary<string, string>();
            if (snapshot == null) return found;
            var labels = new Dictionary<string, int>();
            foreach (string list in new[] { "pending", "history" })
                foreach (object entry in Items(snapshot, list) ?? new List<object>())
                {
                    var row = entry as Dictionary<string, object>;
                    string thread = Str(row, "thread_id");
                    if (row == null || thread == null || IsDemo(row) || found.ContainsKey(thread)) continue;
                    if (Equals(Get(row, "thread_enabled"), false)) continue;
                    string label = Conversation(row);
                    found[thread] = label;
                    int seen;
                    labels[label] = labels.TryGetValue(label, out seen) ? seen + 1 : 1;
                }
            foreach (string thread in new List<string>(found.Keys))
                if (labels[found[thread]] > 1 && thread.Length >= 8)
                    found[thread] = found[thread] + " (" + thread.Substring(0, 8) + ")";
            return found;
        }

        private Dictionary<string, object> ConversationsWritten()
        {
            var written = new Dictionary<string, object>();
            foreach (KeyValuePair<string, string> pair in Conversations()) written[pair.Key] = pair.Value;
            return written;
        }

        private string ConversationOf(string thread)
        {
            string label;
            if (thread != null && Conversations().TryGetValue(thread, out label)) return label;
            return thread != null && thread.Length >= 8 ? thread.Substring(0, 8) : (thread ?? "");
        }

        /// The rules of `capability` (every one for null) still to act - or, for `pending` false, those that ended.
        private List<object> ResetRules(string capability, bool pending)
        {
            var rules = new List<object>();
            foreach (object entry in Items(advancedResets, "rules") ?? new List<object>())
            {
                var rule = entry as Dictionary<string, object>;
                if (rule == null || (capability != null && Str(rule, "capability") != capability)) continue;
                string state = Str(rule, "state");
                bool still = state == "counting" || state == "ready" || state == "held";
                if (still == pending) rules.Add(rule);
            }
            return rules;
        }

        /// The window families Codex reports that are full now: what Use a reset credit now acts on.
        private List<Dictionary<string, object>> FullFamilies()
        {
            var full = new List<Dictionary<string, object>>();
            foreach (object entry in Items(advancedResets, "families") ?? new List<object>())
            {
                var family = entry as Dictionary<string, object>;
                if (family != null && Equals(Get(family, "open_full"), true)) full.Add(family);
            }
            return full;
        }

        private static string FamilyValue(Dictionary<string, object> family)
        {
            return (Str(family, "bucket") ?? "codex") + " " + Whole(Get(family, "minutes")).ToString(CultureInfo.InvariantCulture);
        }

        private int WordsLimit()
        {
            return Math.Max(1, Whole(Get(Map(advancedResets, "limits"), "words")));
        }

        // ---------------------------------------------------------------- the card
        /// The open reset capability's card, while it is on: its rules, then the form a rule is added with.
        private void BuildResets(Dictionary<string, object> item)
        {
            ForgetResetCard();
            string id = Str(item, "id");
            if (!IsResets(id) || Str(item, "state") != StateArmed || advancedResets == null) return;
            bool credit = id == ResetCreditId;
            string kind = credit ? "credit." : "message.";
            TableLayoutPanel card = NewGroup(credit ? Word("page.resets.credit.title", "Reset credit rules")
                                                    : Word("page.resets.message.title", "Messages at a reset"), advancedStack);
            if (credit)
            {
                Label reading = HelpText(ReadingLine());
                reading.ForeColor = Ink;
                card.Controls.Add(reading);
            }
            List<object> rules = ResetRules(id, true);
            if (rules.Count == 0)
                card.Controls.Add(HelpText(credit ? Word("page.resets.credit.none", "No rule yet.")
                                                  : Word("page.resets.message.none", "No message is waiting.")));
            foreach (object rule in rules) AddRuleLine(card, (Dictionary<string, object>)rule);
            if (credit)
            {
                List<Dictionary<string, object>> full = FullFamilies();
                if (full.Count == 0)
                    card.Controls.Add(HelpText(Word("page.resets.now.none", "Use a reset credit now is offered while a usage limit is reached.")));
                foreach (Dictionary<string, object> family in full)
                {
                    string window = WindowWord(Whole(Get(family, "minutes")));
                    Label line = HelpText(Capital(Word("page.resets.now.note", "{window} is reached now.", "window", window)));
                    line.ForeColor = Ink;
                    line.Margin = Pad(0, 6, 0, 2);
                    card.Controls.Add(line);
                    string value = FamilyValue(family);
                    Button now = CardButton(card, Word("page.resets.now", "Use a reset credit now..."), delegate { CreditNow(null, value, window); });
                    now.Tag = value;
                    now.AccessibleName = Word("page.resets.now", "Use a reset credit now...") + " " + window;
                    creditNowButtons.Add(now);
                }
            }
            card.Controls.Add(Caption(credit ? Word("page.resets.credit.add", "Add a rule") : Word("page.resets.message.add", "Add a message")));
            if (!credit)
            {
                string conversation = Word("page.resets.field.conversation", "Conversation");
                resetConversation = NewResetCombo(conversation, 260, kind + "conversation");
                foreach (KeyValuePair<string, string> pair in Conversations())
                    resetConversation.Items.Add(new Choice(pair.Key, pair.Value));
                PickDraft(resetConversation, kind + "conversation");
                card.Controls.Add(NewRow(conversation, resetConversation));
                if (resetConversation.Items.Count == 0)
                    card.Controls.Add(HelpText(Word("page.resets.no_conversation",
                        "No conversation is listed yet. One is offered here once Pending or History lists it.")));
                string words = Word("page.resets.field.words", "Message");
                resetWords = new SoftTextArea();
                resetWords.Font = Font;
                resetWords.Box.Font = Font;
                resetWords.Box.MaxLength = WordsLimit();
                resetWords.Box.AccessibleName = words;
                resetWords.Height = Px(96);
                resetWords.Dock = DockStyle.Fill;
                resetWords.Margin = Pad(0, 4, 0, 2);
                string draft;
                if (resetDrafts.TryGetValue(kind + "words", out draft)) resetWords.Box.Text = draft;
                card.Controls.Add(Caption(words));
                card.Controls.Add(resetWords);
                resetCount = HelpText("");
                card.Controls.Add(resetCount);
                SoftTextArea box = resetWords;
                box.Box.TextChanged += delegate
                {
                    resetDrafts["message.words"] = box.Box.Text;
                    CountResetWords();
                    UpdateResetButtons(busy == 0);
                };
                CountResetWords();
            }
            string windowName = Word("page.resets.field.window", "Window");
            resetFamily = NewResetCombo(windowName, 220, kind + "family");
            foreach (object entry in Items(advancedResets, "families") ?? new List<object>())
            {
                var family = entry as Dictionary<string, object>;
                if (family != null) resetFamily.Items.Add(new Choice(FamilyValue(family), Capital(WindowWord(Whole(Get(family, "minutes"))))));
            }
            PickDraft(resetFamily, kind + "family");
            card.Controls.Add(NewRow(windowName, resetFamily));
            string which = credit ? Word("page.resets.field.which_reached", "Which time it is reached")
                                  : Word("page.resets.field.which", "Which reset");
            resetOrdinal = NewResetCombo(which, 220, kind + "ordinal");
            card.Controls.Add(NewRow(which, resetOrdinal));
            resetFamily.SelectionChangeCommitted += delegate { FillOrdinals(kind); };
            FillOrdinals(kind);
            if (credit)
            {
                string often = Word("page.resets.field.repeat", "How often");
                resetRepeat = NewResetCombo(often, 220, kind + "repeat");
                resetRepeat.Items.Add(new Choice("once", Word("page.resets.repeat.once", "Once")));
                resetRepeat.Items.Add(new Choice("every", Word("page.resets.repeat.every", "Every time it is reached")));
                PickDraft(resetRepeat, kind + "repeat");
                card.Controls.Add(NewRow(often, resetRepeat));
                string ask = Word("page.resets.field.ask", "When it is reached");
                resetAsk = NewResetCombo(ask, 220, kind + "ask");
                resetAsk.Items.Add(new Choice("own", Word("page.resets.ask.no", "Use it on its own")));
                resetAsk.Items.Add(new Choice("ask", Word("page.resets.ask.yes", "Ask me first")));
                PickDraft(resetAsk, kind + "ask");
                card.Controls.Add(NewRow(ask, resetAsk));
                card.Controls.Add(HelpText(Word("page.resets.ask.note",
                    "Until using a reset credit from here has been measured on this Codex, each one waits for your click. None is used unless a recovery is waiting for usage.")));
            }
            resetAdd = CardButton(card, credit ? Word("page.resets.credit.button", "Add rule...") : Word("page.resets.message.button", "Add message..."),
                                  delegate { AddReset(credit); });
            resetAdd.Margin = Pad(0, 8, 0, 4);
            card.Controls.Add(HelpText(credit
                ? Word("page.resets.credit.note", "It counts from the next reading, so a limit reached now is not the next one.")
                : Word("page.resets.message.note", "It counts from the next reading, so the window open now is the first to reset. It is sent once, exactly as written, and a recovery waiting in that conversation for the same reset sends it in place of its own continuation.")));
        }

        private void ForgetResetCard()
        {
            resetFamily = resetOrdinal = resetRepeat = resetAsk = resetConversation = null;
            resetWords = null;
            resetCount = null;
            resetAdd = null;
            resetCancels.Clear();
            resetGoOns.Clear();
            creditNowButtons.Clear();
        }

        /// A rule's line and its buttons: Go on counting, held; Use a reset credit now, for a credit due that waits for a
        /// click; and Cancel, while it can be.
        private void AddRuleLine(TableLayoutPanel card, Dictionary<string, object> rule)
        {
            int ruleId = Whole(Get(rule, "rule_id"));
            string line = RuleLine(rule);
            Label shown = HelpText(line);
            shown.ForeColor = Ink;
            shown.Margin = Pad(0, 6, 0, 2);
            card.Controls.Add(shown);
            string words = Str(rule, "words");
            if (!string.IsNullOrEmpty(words))
                card.Controls.Add(HelpText("“" + (words.Length > 160 ? words.Substring(0, 160) + "…" : words) + "”"));
            if (Str(rule, "state") == "held")
            {
                Button goOn = CardButton(card, Word("page.resets.go_on", "Go on counting"), delegate { GoOnReset(ruleId); });
                goOn.Tag = (double)ruleId;
                goOn.AccessibleName = Word("page.resets.go_on", "Go on counting") + " " + line;
                resetGoOns.Add(goOn);
            }
            if (Str(rule, "capability") == ResetCreditId && Str(rule, "state") == "ready" && Str(rule, "reason") == "ask_first")
            {
                string window = WindowWord(Whole(Get(rule, "minutes")));
                Button now = CardButton(card, Word("page.resets.now", "Use a reset credit now..."), delegate { CreditNow(ruleId, null, window); });
                now.Tag = (double)ruleId;
                now.AccessibleName = Word("page.resets.now", "Use a reset credit now...") + " " + line;
                creditNowButtons.Add(now);
            }
            if (!Equals(Get(rule, "being_sent"), true))
            {
                Button cancel = CardButton(card, Word("page.resets.cancel", "Cancel"), delegate { CancelReset(ruleId); });
                cancel.Tag = (double)ruleId;
                cancel.AccessibleName = Word("page.resets.cancel", "Cancel") + " " + line;
                resetCancels.Add(cancel);
            }
        }

        /// The last reading of the reset credits, and the last one used.
        private string ReadingLine()
        {
            Dictionary<string, object> reading = Map(advancedResets, "reading");
            object count = Get(reading, "credits"), soonest = Get(reading, "nearest_expiry");
            string text = !(count is double)
                ? Word("page.resets.reading.unknown", "How many reset credits you have has not been read yet.")
                : soonest is double
                    ? Word("page.resets.reading", "Reset credits: {n} · the soonest expires {time}", "n", Whole(count))
                          .Replace("{time}", When((double)soonest))
                    : Word("page.resets.reading.no_expiry", "Reset credits: {n}", "n", Whole(count));
            Dictionary<string, object> last = Map(advancedResets, "last_spend");
            object at = Get(last, "at");
            if (Str(last, "outcome") == "reset" && at is double)
                text += " · " + Word("page.resets.reading.last", "one was used {time}", "time", When((double)at));
            return text;
        }

        /// A drop-down of the form, whose choice is kept as `draft` while the card is built again.
        private SoftCombo NewResetCombo(string name, int width, string draft)
        {
            var combo = new SoftCombo();
            combo.Width = Px(width);
            IgnoreWheel(combo);
            combo.AccessibleName = name;
            combo.SelectionChangeCommitted += delegate
            {
                var choice = combo.SelectedItem as Choice;
                if (choice != null) resetDrafts[draft] = choice.Value;
                UpdateResetButtons(busy == 0);
            };
            return combo;
        }

        /// The choice kept as `draft` chosen again where it is still offered, or else the first.
        private void PickDraft(SoftCombo combo, string draft)
        {
            string value;
            int index = combo.Items.Count > 0 ? 0 : -1;
            if (resetDrafts.TryGetValue(draft, out value))
                for (int i = 0; i < combo.Items.Count; i++)
                {
                    var choice = combo.Items[i] as Choice;
                    if (choice != null && choice.Value == value) index = i;
                }
            combo.SelectedIndex = index;
        }

        /// What the chosen window offers: the next one to 9 from now - only the next for a weekly one.
        private void FillOrdinals(string kind)
        {
            if (resetOrdinal == null) return;
            resetOrdinal.Items.Clear();
            int most = ChosenMinutes() >= WeekMinutes ? 1 : MostOrdinal;
            for (int n = 1; n <= most; n++)
                resetOrdinal.Items.Add(new Choice(n.ToString(CultureInfo.InvariantCulture), Capital(OrdinalWord(n))));
            PickDraft(resetOrdinal, kind + "ordinal");
        }

        private static string Capital(string text)
        {
            if (string.IsNullOrEmpty(text)) return text ?? "";
            return char.ToUpper(text[0], CultureInfo.CurrentCulture) + text.Substring(1);
        }

        private int ChosenMinutes()
        {
            var choice = resetFamily == null ? null : resetFamily.SelectedItem as Choice;
            if (choice == null) return 0;
            string[] parts = choice.Value.Split(' ');
            int minutes;
            return parts.Length == 2 && int.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out minutes) ? minutes : 0;
        }

        private string ChosenBucket()
        {
            var choice = resetFamily == null ? null : resetFamily.SelectedItem as Choice;
            return choice == null ? null : choice.Value.Split(' ')[0];
        }

        private void CountResetWords()
        {
            if (resetWords == null || resetCount == null) return;
            resetCount.Text = Word("page.resets.count", "{n} of {most} characters", "n", resetWords.Box.Text.Length)
                .Replace("{most}", WordsLimit().ToString(CultureInfo.CurrentCulture));
        }

        /// What the reset buttons may do now: nothing while another action is under way; Add only with a window, which one,
        /// and - for a message - a conversation and words.
        private void UpdateResetButtons(bool idle)
        {
            bool listed = idle && advancedListing != null && advancedResets != null;
            if (resetAdd != null)
                resetAdd.Enabled = listed && resetFamily != null && resetFamily.SelectedItem != null && resetOrdinal != null &&
                                   resetOrdinal.SelectedItem != null &&
                                   (resetConversation == null || (resetConversation.SelectedItem != null && resetWords != null &&
                                                                  resetWords.Box.Text.Trim().Length > 0));
            foreach (Button button in creditNowButtons) button.Enabled = listed;
            foreach (Button button in resetCancels) button.Enabled = listed;
            foreach (Button button in resetGoOns) button.Enabled = listed;
            foreach (Button button in scheduledCancels) button.Enabled = idle && advancedListing != null;
            foreach (Button button in scheduledGoOns) button.Enabled = idle && advancedListing != null;
        }

        /// Which of the form's boxes or drop-downs has the keyboard, or null.
        private string ResetFocus()
        {
            if (resetWords != null && resetWords.ContainsFocus) return "words";
            if (resetConversation != null && resetConversation.Focused) return "conversation";
            if (resetFamily != null && resetFamily.Focused) return "family";
            if (resetOrdinal != null && resetOrdinal.Focused) return "ordinal";
            if (resetRepeat != null && resetRepeat.Focused) return "repeat";
            if (resetAsk != null && resetAsk.Focused) return "ask";
            if (resetAdd != null && resetAdd.Focused) return "add";
            return null;
        }

        /// The keyboard back on the box or drop-down `name` names in the card as built again, where it can take it.
        private bool FocusResets(string name)
        {
            Control target = name == "words" && resetWords != null ? resetWords.Box
                           : name == "conversation" ? resetConversation : name == "family" ? resetFamily
                           : name == "ordinal" ? resetOrdinal : name == "repeat" ? resetRepeat
                           : name == "ask" ? resetAsk : name == "add" ? (Control)resetAdd : null;
            if (target == null || !target.CanFocus) return false;
            target.Focus();
            return true;
        }

        // ---------------------------------------------------------------- acting
        private void AddReset(bool credit)
        {
            if (busy > 0 || advancedListing == null || resetFamily == null || resetOrdinal == null) return;
            var ordinal = resetOrdinal.SelectedItem as Choice;
            string bucket = ChosenBucket();
            int minutes = ChosenMinutes();
            if (ordinal == null || bucket == null || minutes <= 0) return;
            string window = WindowWord(minutes), which = OrdinalWord(int.Parse(ordinal.Value, CultureInfo.InvariantCulture));
            var argument = new System.Text.StringBuilder("{\"kind\":");
            argument.Append(Json.Escape(credit ? "credit" : "message")).Append(",\"bucket\":").Append(Json.Escape(bucket))
                    .Append(",\"minutes\":").Append(minutes.ToString(CultureInfo.InvariantCulture)).Append(",\"ordinal\":").Append(ordinal.Value);
            string question;
            if (credit)
            {
                var often = resetRepeat == null ? null : resetRepeat.SelectedItem as Choice;
                var ask = resetAsk == null ? null : resetAsk.SelectedItem as Choice;
                bool every = often != null && often.Value == "every", first = ask != null && ask.Value == "ask";
                argument.Append(",\"repeat\":").Append(every ? "true" : "false").Append(",\"ask_first\":").Append(first ? "true" : "false");
                question = Word("page.confirm.reset_credit",
                    "Use a reset credit when {window} is reached ({which}), if a recovery is waiting for usage then? A reset credit used cannot be given back.",
                    "window", window).Replace("{which}", which);
            }
            else
            {
                var conversation = resetConversation == null ? null : resetConversation.SelectedItem as Choice;
                if (conversation == null || resetWords == null) return;
                argument.Append(",\"thread_id\":").Append(Json.Escape(conversation.Value))
                        .Append(",\"words\":").Append(Json.Escape(resetWords.Box.Text));
                question = Word("page.confirm.reset_message",
                    "Send this message to {conversation} when {window} resets ({which})? It is sent once, exactly as written.",
                    "window", window).Replace("{which}", which).Replace("{conversation}", conversation.ToString());
            }
            argument.Append(",\"generation\":").Append(AdvancedGeneration()).Append('}');
            if (!AskAdvanced(question, Affirm(credit ? Word("page.resets.credit.button", "Add rule...")
                                                     : Word("page.resets.message.button", "Add message...")))) return;
            AdvancedCall("advanced-reset-add", argument.ToString(), true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                {
                    resetDrafts.Remove("message.words");
                    ResetNote(Word("page.done.reset_added", "Added. It counts from the next reading."));
                }
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(ResetRefusal(Str(result, "refusal")));
            });
        }

        private void CancelReset(int rule)
        {
            if (busy > 0 || advancedListing == null) return;
            string argument = "{\"rule\":" + rule.ToString(CultureInfo.InvariantCulture) + ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-reset-cancel", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.reset_cancelled", "Cancelled."));
                // The list read again - and the rules with it, where the open capability is one of these - and Pending's
                // group read either way.
                ReadAdvanced(null);
                if (!IsResets(advancedOpen)) ReadResets(null);
                if (!AdvancedDone(result)) TellAdvanced(ResetRefusal(Str(result, "refusal")));
            });
        }

        private void GoOnReset(int rule)
        {
            if (busy > 0 || advancedListing == null) return;
            string argument = "{\"rule\":" + rule.ToString(CultureInfo.InvariantCulture) + ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-reset-go-on", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.go_on", "It counts again from the next reading."));
                ReadAdvanced(null);
                if (!IsResets(advancedOpen)) ReadResets(null);
                if (!AdvancedDone(result)) TellAdvanced(ResetRefusal(Str(result, "refusal")));
            });
        }

        /// Use a reset credit now - for a due rule's window (`rule`), or a family reached now (`family`, "bucket minutes")
        /// - after asking: it cannot be undone.
        private void CreditNow(int? rule, string family, string window)
        {
            if (busy > 0 || advancedListing == null) return;
            if (!AskAdvanced(Word("page.confirm.credit_now", "Use one reset credit now for {window}? It cannot be undone.", "window", window),
                             Affirm(Word("page.resets.now", "Use a reset credit now...")))) return;
            var argument = new System.Text.StringBuilder("{");
            if (rule.HasValue) argument.Append("\"rule\":").Append(rule.Value.ToString(CultureInfo.InvariantCulture)).Append(',');
            else if (family != null)
            {
                string[] parts = family.Split(' ');
                argument.Append("\"bucket\":").Append(Json.Escape(parts[0])).Append(",\"minutes\":").Append(parts[1]).Append(',');
            }
            argument.Append("\"generation\":").Append(AdvancedGeneration()).Append('}');
            AdvancedCall("advanced-credit-now", argument.ToString(), true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                    ResetNote(Word("page.done.credit_now", "Asked. The watcher uses it at its next look if every check passes."));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(ResetRefusal(Str(result, "refusal")));
            });
        }

        /// What a reset action did, beside the page's buttons - where the page has been built: Cancel is pressed on
        /// Pending too, which says it by the line that goes.
        private void ResetNote(string text)
        {
            if (advancedNote != null) SetNote(advancedNote, text);
        }

        /// A refusal of a reset action in words; one of every page's as the page says it.
        private string ResetRefusal(string refusal)
        {
            if (refusal == "occasion_invalid")
                return Word("page.refused.occasion_invalid", "That window or that number is not one on offer, or no usage limit is reached now. Nothing was changed.");
            if (refusal == "resets_full")
                return Word("page.refused.resets_full", "As many are waiting as may. Cancel one to add another.");
            if (refusal == "message_refused")
                return Word("page.refused.message_refused", "That message cannot be sent: it is empty or too long, holds a control character or a marker of this product's, or is one of its own continuations.");
            if (refusal == "already_scheduled")
                return Word("page.refused.already_scheduled", "A message already waits for that conversation. Cancel it to write another.");
            if (refusal == "being_sent")
                return Word("page.refused.being_sent", "It is being sent, so it can no longer be cancelled.");
            if (refusal == "not_on") return Word("page.refused.not_on", "Turn it on first.");
            return KeptRefusal(refusal);
        }

        // ---------------------------------------------------------------- Pending's scheduled group
        /// Pending's group of what is scheduled, under its list and above its buttons (PendingBuilt), hidden while
        /// nothing is.
        partial void PendingBuilt(Panel page)
        {
            scheduledPage = page;
            scheduledHolder = new SoftStack();
            scheduledHolder.ColumnCount = 1;
            scheduledHolder.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            scheduledHolder.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            scheduledHolder.Dock = DockStyle.Bottom;
            scheduledHolder.Margin = new Padding(0);
            // The page's gap between the list's card and this one: docking keeps no margin.
            scheduledHolder.Padding = Pad(0, Brand.PageGap, 0, 0);
            scheduledHolder.Visible = false;
            // As the explanation beside the list is: its lines scroll inside it, on the soft bar, below its heading, so
            // however many wait the list keeps most of the page and the page itself never scrolls.
            scheduledCard = MakeCard(Word("page.scheduled", "Scheduled"));
            scheduledCard.Dock = DockStyle.Fill;
            scheduledCard.AutoSize = false;
            scheduledCard.Margin = new Padding(0);
            scheduledScroll = new SoftPage();
            scheduledScroll.BackColor = Card;
            scheduledScroll.Dock = DockStyle.Fill;
            scheduledScroll.Margin = new Padding(0);
            scheduledScroll.Padding = Pad(0, 0, 6, 0);
            scheduledLines = new TableLayoutPanel();
            scheduledLines.ColumnCount = 1;
            scheduledLines.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            scheduledLines.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            scheduledLines.AutoSize = true;
            scheduledLines.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            scheduledLines.Dock = DockStyle.Top;
            scheduledLines.BackColor = Card;
            scheduledLines.Margin = new Padding(0);
            scheduledLines.Padding = new Padding(0);
            scheduledScroll.Controls.Add(scheduledLines);
            scheduledScroll.Scrolls = true;
            scheduledCard.Controls.Add(scheduledScroll);
            scheduledCard.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            scheduledCard.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            scheduledHolder.Controls.Add(scheduledCard);
            page.Controls.Add(scheduledHolder);
            page.SizeChanged += delegate { FitScheduled(); };
            scheduledShown = null;
            FillScheduled();
        }

        /// The group as tall as its lines need, and never more than two fifths of the page.
        private void FitScheduled()
        {
            if (scheduledHolder == null || scheduledHolder.IsDisposed || scheduledPage == null) return;
            int width = Math.Max(Px(120), scheduledPage.ClientSize.Width - scheduledPage.Padding.Horizontal -
                                          scheduledCard.Padding.Horizontal - scheduledScroll.Padding.Horizontal);
            Control heading = scheduledCard.Controls[0];
            int needed = scheduledHolder.Padding.Vertical + scheduledCard.Padding.Vertical + heading.Height +
                         heading.Margin.Vertical + scheduledLines.GetPreferredSize(new System.Drawing.Size(width, 0)).Height;
            int most = Math.Max(Px(120), (scheduledPage.ClientSize.Height - scheduledPage.Padding.Vertical) * 2 / 5);
            int height = Math.Min(needed, most);
            if (scheduledHolder.Height != height) scheduledHolder.Height = height;
        }

        /// Each rule still to act, a flat line with its Cancel - and Go on counting, held - as the last advanced-resets
        /// read held them.
        private void FillScheduled()
        {
            if (scheduledCard == null || scheduledCard.IsDisposed) return;
            List<object> rules = ResetRules(null, true);
            string heading = Word("page.scheduled", "Scheduled");
            string shown = heading + "|" + AdvancedWritten(rules) + "|" + AdvancedWritten(ConversationsWritten());
            if (shown == scheduledShown)
            {
                UpdateResetButtons(busy == 0);
                return;
            }
            scheduledShown = shown;
            scheduledLines.SuspendLayout();
            scheduledCard.Controls[0].Text = heading;
            var old = new List<Control>();
            foreach (Control control in scheduledLines.Controls) old.Add(control);
            scheduledLines.Controls.Clear();
            scheduledLines.RowStyles.Clear();
            foreach (Control control in old) control.Dispose();
            scheduledCancels.Clear();
            scheduledGoOns.Clear();
            foreach (object entry in rules)
            {
                var rule = (Dictionary<string, object>)entry;
                int ruleId = Whole(Get(rule, "rule_id"));
                string text = RuleLine(rule);
                Label line = HelpText(text);
                line.ForeColor = Ink;
                line.Margin = Pad(0, 4, 0, 2);
                scheduledLines.Controls.Add(line);
                if (Str(rule, "state") == "held")
                {
                    Button goOn = CardButton(scheduledLines, Word("page.resets.go_on", "Go on counting"), delegate { GoOnReset(ruleId); });
                    goOn.Tag = (double)ruleId;
                    goOn.AccessibleName = Word("page.resets.go_on", "Go on counting") + " " + text;
                    scheduledGoOns.Add(goOn);
                }
                if (Equals(Get(rule, "being_sent"), true)) continue;
                Button cancel = CardButton(scheduledLines, Word("page.resets.cancel", "Cancel"), delegate { CancelReset(ruleId); });
                cancel.Tag = (double)ruleId;
                cancel.AccessibleName = Word("page.resets.cancel", "Cancel") + " " + text;
                scheduledCancels.Add(cancel);
            }
            scheduledLines.ResumeLayout(true);
            if (scheduledHolder != null) scheduledHolder.Visible = rules.Count > 0;
            FitScheduled();
            UpdateResetButtons(busy == 0);
        }
    }
}

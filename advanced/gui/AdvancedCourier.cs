// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the courier's card on the Advanced features page, and the status feed's line on the Overview
// (v0.6.20, plans/v0619-design/D-courier.md).
//
// While Send notices to your phone or inbox is on or watched, its column has a card "Where notices go": for each channel
// - ntfy, a webhook, Telegram, e-mail - a flat line saying whether it is saved, its switch, the fields it needs (what
// holds a secret typed into a masked box and never shown again: the bridge only ever says whether it is saved), and Save
// (or Replace), Forget, Send a test and, for Telegram, Pair this chat, which shows the one-time code to send the bot. Then
// a card "Which notices go": a switch for each event a push may say, kept in push_events as a bit set, one at least
// always on. The card's requests are the bridge's (advanced-courier, advanced-courier-save, advanced-courier-forget,
// advanced-courier-test), the Dashboard's alone; the switches are each an advanced-option, as every choice of the page is.
//
// While Show OpenAI's service status is on and the page says something is wrong, the Overview's Right now card gains one
// fact, "OpenAI status", saying degraded service or an outage (surfaces.feed_view); nothing is shown otherwise.
//
// Nothing here draws anything the page does not draw already: the cards, captions, help lines, rows, boxes, switches and
// buttons are the Settings page's and the other cards'.
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
        private const string PushId = "push_notices";
        private static readonly string[] CourierChannels = { "ntfy", "webhook", "telegram", "email" };
        // Each channel's fields: its key, the catalog word's key and fallback, and whether it holds a secret (masked).
        private static readonly string[][] CourierFields =
        {
            new[] { "ntfy", "url", "page.courier.field.url", "Address (https)", "secret" },
            new[] { "webhook", "url", "page.courier.field.url", "Address (https)", "secret" },
            new[] { "webhook", "token", "page.courier.field.token", "Bearer token (optional)", "secret" },
            new[] { "telegram", "token", "page.courier.field.bot_token", "Bot token", "secret" },
            new[] { "email", "host", "page.courier.field.host", "Mail server", "" },
            new[] { "email", "user", "page.courier.field.user", "User name", "" },
            new[] { "email", "password", "page.courier.field.password", "Password", "secret" },
            new[] { "email", "from", "page.courier.field.from", "From", "" },
            new[] { "email", "to", "page.courier.field.to", "To", "" },
        };

        // advanced-courier's last answer, or null; the pairing code shown, and what the last test said, by channel.
        private Dictionary<string, object> advancedCourier;
        private string courierCode;
        private readonly Dictionary<string, string> courierResults = new Dictionary<string, string>();
        // The card as it was built: each box by "<channel>.<field>", the port's drop-down, and every button by its Tag
        // ("save ntfy", "forget ntfy", "test ntfy", "pair telegram").
        private readonly Dictionary<string, SoftTextArea> courierBoxes = new Dictionary<string, SoftTextArea>();
        private SoftCombo courierPort;
        private readonly List<Button> courierButtons = new List<Button>();
        private readonly List<SoftCheck> courierEvents = new List<SoftCheck>();
        // The Overview's status line (one fact of Right now), made the first time the page says something is wrong.
        private Label feedName, feedValue;

        /// Whether `key` is one of push_notices' choices this card shows itself, so the Choices card passes it over.
        private static bool CourierChoice(string key)
        {
            return key == "push_events" || Array.IndexOf(CourierChannels, key) >= 0;
        }

        /// The open capability's choices less the courier's own, which its card shows.
        private static List<object> WithoutCourierChoices(List<object> options)
        {
            if (options == null) return null;
            var kept = new List<object>();
            foreach (object entry in options)
                if (!CourierChoice(Str(entry as Dictionary<string, object>, "key") ?? "")) kept.Add(entry);
            return kept;
        }

        /// What the courier's cards are built from, for ShowAdvancedDetail to build them again only when it changed.
        private string CourierShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != PushId) return "";
            var results = new List<string>();
            foreach (KeyValuePair<string, string> pair in courierResults) results.Add(pair.Key + "=" + pair.Value);
            return AdvancedWritten(advancedCourier) + "|" + (courierCode ?? "") + "|" + string.Join(",", results.ToArray()) +
                   "|" + AdvancedWritten(Get(item, "options"));
        }

        /// Read advanced-courier, keep it, and show it; `done` once it is shown.
        private void ReadCourier(MethodInvoker done)
        {
            AdvancedCall("advanced-courier", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedCourier = AdvancedDone(result) ? result : null;
                if (advancedCourier != null && !Equals(Get(Map(advancedCourier, "telegram"), "pairing"), true)) courierCode = null;
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        private void ForgetCourierCard()
        {
            courierBoxes.Clear();
            courierPort = null;
            courierButtons.Clear();
            courierEvents.Clear();
        }

        /// The courier's two cards, while push_notices is on or watched and its card was read.
        private void BuildCourier(Dictionary<string, object> item)
        {
            ForgetCourierCard();
            if (Str(item, "id") != PushId || !Standing(item) || advancedCourier == null) return;
            TableLayoutPanel card = NewGroup(Word("page.courier.title", "Where notices go"), advancedStack);
            card.Controls.Add(HelpText(Word("page.courier.secret_note",
                "What you type here is kept in Windows Credential Manager and never shown again.")));
            var options = new Dictionary<string, int>();
            foreach (object entry in Items(item, "options") ?? new List<object>())
            {
                var option = entry as Dictionary<string, object>;
                if (Str(option, "key") != null) options[Str(option, "key")] = Whole(Get(option, "value"));
            }
            foreach (object entry in Items(advancedCourier, "channels") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                string channel = Str(row, "channel");
                if (row == null || Array.IndexOf(CourierChannels, channel) < 0) continue;
                BuildCourierChannel(card, channel, row, options);
            }
            BuildCourierEvents(options);
        }

        private void BuildCourierChannel(TableLayoutPanel card, string channel, Dictionary<string, object> row,
                                         Dictionary<string, int> options)
        {
            string name = Word("page.courier.channel." + channel, channel);
            Label caption = Caption(name);
            caption.Margin = Pad(0, 10, 0, 2);
            card.Controls.Add(caption);
            bool saved = Equals(Get(row, "saved"), true);
            Label state = HelpText(saved ? Word("page.courier.saved", "Saved in Windows Credential Manager.")
                                         : Word("page.courier.not_saved", "Not set up yet."));
            state.ForeColor = Ink;
            card.Controls.Add(state);
            if (Equals(Get(row, "tripped"), true))
            {
                Label tripped = HelpText(Word("page.courier.tripped",
                    "Switched off after {n} refusals today. Check the address, then switch it on again.", "n",
                    Whole(Get(row, "refused_today"))));
                tripped.ForeColor = Accent;
                card.Controls.Add(tripped);
            }
            CourierSwitch(card, channel, name, options.ContainsKey(channel) && options[channel] == SwitchOn);
            foreach (string[] field in CourierFields)
            {
                if (field[0] != channel) continue;
                string label = Word(field[2], field[3]);
                SoftTextArea box = OneLine(label, 260, 512);
                if (field[4] == "secret")
                {
                    box.Box.Multiline = false;
                    box.Box.UseSystemPasswordChar = true;
                }
                courierBoxes[channel + "." + field[1]] = box;
                card.Controls.Add(NewRow(label, box));
            }
            if (channel == "email")
            {
                string port = Word("page.courier.field.port", "Port");
                courierPort = NewResetCombo(port, 120, "courier.port");
                courierPort.Items.Add(new Choice("465", "465"));
                courierPort.Items.Add(new Choice("587", "587"));
                courierPort.SelectedIndex = 0;
                card.Controls.Add(NewRow(port, courierPort));
            }
            CourierButton(card, saved ? Word("page.courier.replace", "Replace") : Word("page.courier.save", "Save"),
                          "save " + channel, name, delegate { SaveCourier(channel); });
            if (channel == "telegram")
            {
                Dictionary<string, object> telegram = Map(advancedCourier, "telegram");
                if (courierCode != null)
                    card.Controls.Add(HelpText(Word("page.courier.pair_code", "Send {code} to your bot within two minutes.",
                                                    "code", courierCode)));
                else
                    card.Controls.Add(HelpText(Equals(Get(telegram, "paired"), true)
                        ? Word("page.courier.paired", "A chat is paired.")
                        : Word("page.courier.not_paired", "No chat is paired yet. Save the bot's token, then pair a chat.")));
                if (Equals(Get(telegram, "token_saved"), true))
                    CourierButton(card, Word("page.courier.pair", "Pair this chat"), "pair telegram", name,
                                  delegate { PairCourier(); });
            }
            if (saved)
            {
                CourierButton(card, Word("page.courier.test", "Send a test"), "test " + channel, name,
                              delegate { TestCourier(channel); });
                CourierButton(card, Word("page.courier.forget", "Forget"), "forget " + channel, name,
                              delegate { ForgetCourier(channel); });
            }
            string said;
            if (courierResults.TryGetValue(channel, out said))
                card.Controls.Add(HelpText(Word("page.courier.result." + said, said)));
        }

        private void CourierButton(TableLayoutPanel card, string text, string tag, string channel, EventHandler onClick)
        {
            Button button = CardButton(card, text, onClick);
            button.Tag = tag;
            button.AccessibleName = text + " " + channel;
            courierButtons.Add(button);
        }

        /// A channel's switch: the Dashboard's own (as BuildAdvancedSwitch draws one), sent as an advanced-option.
        private void CourierSwitch(TableLayoutPanel card, string channel, string label, bool on)
        {
            var toggle = (SoftCheck)NewCheck("", on, false);
            toggle.AutoCheck = false;
            toggle.AutoSize = false;
            toggle.Size = new Size(Px(Brand.SwitchWidth), toggle.GetPreferredSize(Size.Empty).Height);
            toggle.AccessibleName = label;
            toggle.Tag = channel;
            SoftCheck pressed = toggle;
            toggle.Click += delegate { SwitchAdvancedOption(PushId, channel, pressed); };
            card.Controls.Add(NewRow(label, toggle));
            advancedSwitches.Add(toggle);
        }

        /// Which notices go: a switch for each event, the bit set push_events sent whole; the last one on cannot go off.
        private void BuildCourierEvents(Dictionary<string, int> options)
        {
            List<object> order = Items(advancedCourier, "event_order");
            if (order == null || order.Count == 0) return;
            int bits = options.ContainsKey("push_events") ? options["push_events"] : Whole(Get(advancedCourier, "events"));
            TableLayoutPanel card = NewGroup(Word("page.courier.events", "Which notices go"), advancedStack);
            for (int i = 0; i < order.Count; i++)
            {
                string evt = order[i] as string;
                if (evt == null) continue;
                int bit = 1 << i;
                string label = Word("page.push." + evt, evt);
                var toggle = (SoftCheck)NewCheck("", (bits & bit) != 0, false);
                toggle.AutoCheck = false;
                toggle.AutoSize = false;
                toggle.Size = new Size(Px(Brand.SwitchWidth), toggle.GetPreferredSize(Size.Empty).Height);
                toggle.AccessibleName = label;
                toggle.Tag = evt;
                int mine = bit, all = bits;
                toggle.Click += delegate
                {
                    int next = all ^ mine;
                    if (choiceFilling || advancedListing == null || busy > 0 || next == 0) return;
                    SetAdvancedOptionValue(PushId, "push_events", next.ToString(CultureInfo.InvariantCulture));
                };
                card.Controls.Add(NewRow(label, toggle));
                courierEvents.Add(toggle);
            }
        }

        private void UpdateCourierButtons(bool idle)
        {
            bool listed = idle && advancedListing != null && advancedCourier != null;
            foreach (Button button in courierButtons) button.Enabled = listed;
            int on = 0;
            foreach (SoftCheck toggle in courierEvents) if (toggle.Checked) on++;
            foreach (SoftCheck toggle in courierEvents) toggle.Enabled = listed && !(toggle.Checked && on == 1);
        }

        private string CourierBox(string key)
        {
            SoftTextArea box;
            return courierBoxes.TryGetValue(key, out box) ? box.Box.Text.Trim() : "";
        }

        /// Save (or Replace): what the channel's boxes hold, sent once and cleared from the card.
        private void SaveCourier(string channel)
        {
            if (busy > 0 || advancedListing == null) return;
            string argument;
            if (channel == "ntfy") argument = "{\"channel\":\"ntfy\",\"url\":" + Json.Escape(CourierBox("ntfy.url")) + "}";
            else if (channel == "webhook")
                argument = "{\"channel\":\"webhook\",\"url\":" + Json.Escape(CourierBox("webhook.url")) + ",\"token\":" +
                           Json.Escape(CourierBox("webhook.token")) + "}";
            else if (channel == "telegram")
                argument = "{\"channel\":\"telegram\",\"token\":" + Json.Escape(CourierBox("telegram.token")) + "}";
            else
            {
                var port = courierPort == null ? null : courierPort.SelectedItem as Choice;
                argument = "{\"channel\":\"email\",\"host\":" + Json.Escape(CourierBox("email.host")) + ",\"port\":" +
                           (port == null ? "465" : port.Value) + ",\"user\":" + Json.Escape(CourierBox("email.user")) +
                           ",\"password\":" + Json.Escape(CourierBox("email.password")) + ",\"from\":" +
                           Json.Escape(CourierBox("email.from")) + ",\"to\":" + Json.Escape(CourierBox("email.to")) + "}";
            }
            foreach (KeyValuePair<string, SoftTextArea> pair in courierBoxes)
                if (pair.Key.StartsWith(channel + ".", StringComparison.Ordinal)) pair.Value.Box.Text = "";
            AdvancedCall("advanced-courier-save", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.courier_saved", "Saved."));
                ReadCourier(null);
                if (!AdvancedDone(result)) TellAdvanced(CourierRefusal(Str(result, "refusal")));
            });
        }

        private void PairCourier()
        {
            if (busy > 0 || advancedListing == null) return;
            AdvancedCall("advanced-courier-save", "{\"channel\":\"telegram\",\"pair\":true}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                courierCode = AdvancedDone(result) ? Str(result, "code") : null;
                ReadCourier(null);
                if (!AdvancedDone(result)) TellAdvanced(CourierRefusal(Str(result, "refusal")));
            });
        }

        private void TestCourier(string channel)
        {
            if (busy > 0 || advancedListing == null) return;
            AdvancedCall("advanced-courier-test", "{\"channel\":" + Json.Escape(channel) + "}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) courierResults[channel] = Str(result, "outcome") ?? "no_answer";
                ShowAdvancedDetail();
                if (!AdvancedDone(result)) TellAdvanced(CourierRefusal(Str(result, "refusal")));
            });
        }

        private void ForgetCourier(string channel)
        {
            if (busy > 0 || advancedListing == null) return;
            if (!AskAdvanced(Word("page.confirm.courier_forget", "Forget this channel's address and secret?"),
                             Affirm(Word("page.courier.forget", "Forget"))))
                return;
            AdvancedCall("advanced-courier-forget", "{\"channel\":" + Json.Escape(channel) + "}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                {
                    courierResults.Remove(channel);
                    ResetNote(Word("page.done.courier_forgotten", "Forgotten."));
                }
                ReadCourier(null);
                if (!AdvancedDone(result)) TellAdvanced(CourierRefusal(Str(result, "refusal")));
            });
        }

        private string CourierRefusal(string refusal)
        {
            if (refusal == "address_refused")
                return Word("page.refused.address_refused", "That cannot be used: an address must start with https, name a host and carry no user name or password, and a token has no spaces.");
            if (refusal == "secret_unavailable")
                return Word("page.refused.secret_unavailable", "Windows Credential Manager did not keep it. Nothing was saved.");
            if (refusal == "not_saved") return Word("page.refused.not_saved", "Save the bot's token first.");
            if (refusal == "courier_unavailable") return Word("page.refused.courier_unavailable", "The courier could not be started.");
            return ResetRefusal(refusal);
        }

        // ---------------------------------------------------------------- the Overview's status line
        /// From each snapshot: OpenAI's status as the status feed last read it (surfaces.feed_view), one fact of Right now
        /// while it says degraded service or an outage, and hidden otherwise.
        private void FeedApplied(Dictionary<string, object> reply)
        {
            Dictionary<string, object> feed = Map(Map(Map(reply, "status"), "advanced"), "feed");
            string word = Str(feed, "word"), codex = Str(feed, "codex_word");
            string shown = word == "outage" || codex == "outage" ? Word("page.feed.outage", "OpenAI reports an outage")
                         : word == "degraded" || codex == "degraded" ? Word("page.feed.degraded", "OpenAI reports degraded service")
                         : null;
            if (shown == null)
            {
                if (feedName != null) feedName.Visible = feedValue.Visible = false;
                return;
            }
            if (nowFacts == null) return;
            if (feedValue == null)
            {
                feedValue = Fact(nowFacts, Word("page.feed.label", "OpenAI status"));
                feedName = nowFacts.Controls[nowFacts.Controls.Count - 2] as Label;
            }
            feedValue.Text = shown;
            feedValue.ForeColor = Accent;
            if (feedName != null) feedName.Visible = true;
            feedValue.Visible = true;
        }
    }
}

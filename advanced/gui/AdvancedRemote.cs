// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the loopback API's card and Telegram's on the Advanced features page (v0.6.22,
// plans/v0619-design/D-remote.md).
//
// While Read this PC's status from a browser or a script is on or watched, its column has a card "Address and token": how
// the server stands (running once it bound its port, starting, starting with the watcher that is not running, stopped for
// this hour, or its port taken), the address without its token - and, open to the local network, this PC's addresses there
// and which one to copy - whether a token is kept, Copy address - the address carrying the token in its fragment, which a
// browser never sends - and Copy token, the token alone for a script, both only while the server runs, and New token...,
// which asks first once there is one to replace. The port is its Choices card's, as every choice of the page
// is; what widens it (pausing and cancelling, the local network) are rows of their own in the list. The card's requests are
// the bridge's (advanced-api, advanced-api-token-new), the Dashboard's alone; the token is never drawn and never kept here:
// it goes to the clipboard once and is forgotten.
//
// While Control recovery from Telegram is on or watched, its column has a card "Your Telegram chat": how the reading stands
// (read, or not read for want of a bot token or a paired chat), which chat is paired - by its name as Telegram gave it - or
// the one-time code to send the bot, Pair this chat once the bot's token is saved on the notices card (one pairing, two
// capabilities) or, with none saved, Open the notices card, and what the chat may send as a plain list, the two commands of Let Telegram
// continue among them only while that is on (advanced-remote-pair-state, advanced-remote-pair-start).
//
// Nothing here draws anything the page does not draw already: the card, its help lines and its buttons are the Settings
// page's, in both themes and both designs, mirrored for Arabic and Hebrew by the page. It opens no window of its own.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.IO;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string ApiId = "local_api", TelegramId = "telegram_remote";

        // advanced-api's last answer - never one asked with copy - or null where it was not read or the read failed.
        private Dictionary<string, object> advancedApi;
        // advanced-remote-pair-state's last answer, or null; the one-time code the card shows.
        private Dictionary<string, object> advancedTelegram;
        private string telegramCode;
        // Open to the local network: this PC's addresses Copy address may carry instead of 127.0.0.1, and the one picked.
        private readonly List<string> apiHosts = new List<string>();
        private string apiPicked;
        // The cards' buttons by their Tag ("copy api", "token api", "pair telegram"); what a test's run copied instead of
        // the clipboard.
        private readonly List<Button> remoteButtons = new List<Button>();
        private List<string> remoteCopied;

        /// What the card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string RemoteShown(Dictionary<string, object> item)
        {
            string id = Str(item, "id");
            return id == ApiId ? AdvancedWritten(advancedApi)
                 : id == TelegramId ? AdvancedWritten(advancedTelegram) + "|" + (telegramCode ?? "") : "";
        }

        /// Read advanced-api, keep it, and show it; `done` once it is shown.
        private void ReadApi(MethodInvoker done)
        {
            AdvancedCall("advanced-api", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedApi = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        private void ForgetRemoteCard()
        {
            remoteButtons.Clear();
        }

        /// The open capability's card, while it is on or watched and it was read.
        private void BuildRemote(Dictionary<string, object> item)
        {
            ForgetRemoteCard();
            if (Str(item, "id") == ApiId && Standing(item) && advancedApi != null) BuildApiCard();
            if (Str(item, "id") == TelegramId && Standing(item) && advancedTelegram != null) BuildTelegramCard();
        }

        private void BuildApiCard()
        {
            TableLayoutPanel card = NewGroup(Word("page.api.card", "Address and token"), advancedStack);
            string state = ApiStateLine(Str(advancedApi, "state"));
            if (state != null)
            {
                Label line = HelpText(state);
                line.ForeColor = Str(advancedApi, "state") == "running" ? Ink : Accent;
                card.Controls.Add(line);
            }
            card.Controls.Add(HelpText(Word("page.api.address", "Address: {url}", "url", Mirror.Embed(Str(advancedApi, "url") ?? ""))));
            bool kept = Equals(Get(advancedApi, "token_saved"), true);
            card.Controls.Add(HelpText(kept
                ? Word("page.api.token_kept", "A token is kept in Windows Credential Manager. Whatever asks needs it; Copy address carries it.")
                : Word("page.api.no_token", "There is no token yet, so nothing can read this. Make one with New token.")));
            // Only while the server runs - bound, not starting, not on another program's port: that program's page would read
            // the token (and the bridge answers neither otherwise).
            bool up = kept && Str(advancedApi, "state") == "running";
            apiHosts.Clear();
            if (Equals(Get(advancedApi, "lan"), true))
            {
                Label lan = HelpText(Word("page.api.lan", "Open to your local network, without encryption."));
                lan.ForeColor = Accent;
                card.Controls.Add(lan);
                foreach (object each in Items(advancedApi, "lan_urls") ?? new List<object>())
                {
                    string url = each as string;
                    Uri made;
                    if (string.IsNullOrEmpty(url) || !Uri.TryCreate(url, UriKind.Absolute, out made)) continue;
                    card.Controls.Add(HelpText(Word("page.api.lan_address", "On your local network: {url}", "url", Mirror.Embed(url))));
                    apiHosts.Add(made.Host);
                }
                if (up && apiHosts.Count > 0) ApiHostPicker(card);
            }
            if (up)
            {
                RemoteButton(card, Word("page.api.copy", "Copy address"), "copy api", delegate { CopyApiAddress(); });
                RemoteButton(card, Word("page.api.copy_token", "Copy token"), "copy token", delegate { CopyApiToken(); });
            }
            RemoteButton(card, Word("page.api.new_token", "New token..."), "token api", delegate { NewApiToken(kept); });
        }

        /// Which address Copy address carries: this PC's addresses on the network, the first picked unless another was,
        /// then 127.0.0.1.
        private void ApiHostPicker(TableLayoutPanel card)
        {
            string name = Word("page.api.copy_which", "Address to copy");
            card.Controls.Add(Caption(name));
            var combo = new SoftCombo();
            combo.Width = Px(260);
            IgnoreWheel(combo);
            combo.AccessibleName = name;
            foreach (string host in apiHosts) combo.Items.Add(host);
            combo.Items.Add("127.0.0.1");
            int picked = apiPicked == null ? 0 : Math.Max(0, combo.Items.IndexOf(apiPicked));
            combo.SelectedIndex = picked;
            apiPicked = combo.Items[picked] as string;
            combo.SelectionChangeCommitted += delegate { apiPicked = combo.SelectedItem as string; };
            combo.Margin = Pad(0, 2, 0, 4);
            card.Controls.Add(combo);
        }

        /// How the server stands, in a line; null while it is off.
        private string ApiStateLine(string state)
        {
            if (state == "running") return Word("page.api.state.running", "The server is running.");
            if (state == "starting") return Word("page.api.state.starting", "The server starts with the watcher's next look.");
            if (state == "no_watcher") return Word("page.api.state.no_watcher", "The server starts with the watcher, which is not running.");
            if (state == "stopped") return Word("page.api.state.stopped", "The server stopped too often, so it is not started again for now. It is tried again within the hour.");
            if (state == "port_taken") return Word("page.api.state.port_taken", "Another program holds this port. Choose another below.");
            return null;
        }

        private void RemoteButton(TableLayoutPanel card, string text, string tag, EventHandler onClick)
        {
            Button button = CardButton(card, text, onClick);
            button.Tag = tag;
            button.AccessibleName = text;
            remoteButtons.Add(button);
        }

        private void UpdateRemoteButtons(bool idle)
        {
            foreach (Button button in remoteButtons) button.Enabled = idle && advancedListing != null;
        }

        /// The address carrying the token, onto the clipboard - or, in a test's run, into its list: never the real one there.
        /// Marked for Windows to keep out of its clipboard history and its cloud clipboard (the formats Windows documents for
        /// that), so the token stays on this PC as far as Windows keeps the promise.
        private bool PutOnClipboard(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            if (remoteCopied != null)
            {
                remoteCopied.Add(text);
                return true;
            }
            try
            {
                var data = new DataObject();
                data.SetData(DataFormats.UnicodeText, text);
                data.SetData("ExcludeClipboardContentFromMonitorProcessing", new MemoryStream(new byte[] { 0, 0, 0, 0 }));
                data.SetData("CanIncludeInClipboardHistory", new MemoryStream(BitConverter.GetBytes(0)));
                data.SetData("CanUploadToCloudClipboard", new MemoryStream(BitConverter.GetBytes(0)));
                Clipboard.SetDataObject(data, true);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private void CopyApiAddress()
        {
            if (busy > 0 || advancedListing == null) return;
            // One of this PC's own network addresses where one is picked; the bridge carries no other.
            string host = apiPicked != null && apiHosts.Contains(apiPicked) ? apiPicked : null;
            string argument = host == null ? "{\"copy\":true}" : "{\"copy\":true,\"host\":" + Json.Escape(host) + "}";
            AdvancedCall("advanced-api", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result) && PutOnClipboard(Str(result, "copy_url")))
                    ResetNote(Word("page.done.api_copied", "Copied. Whoever has this address can read this PC's status."));
                else TellAdvanced(Word("page.refused.api_not_copied", "The address could not be copied."));
            });
        }

        /// The token alone, for a script's Authorization header - as the address, only while the server runs.
        private void CopyApiToken()
        {
            if (busy > 0 || advancedListing == null) return;
            AdvancedCall("advanced-api", "{\"copy_token\":true}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result) && PutOnClipboard(Str(result, "copy_token")))
                    ResetNote(Word("page.done.api_token_copied", "Copied. Whoever has this token can read this PC's status."));
                else TellAdvanced(Word("page.refused.api_token_not_copied", "The token could not be copied."));
            });
        }

        /// Read advanced-remote-pair-state, keep it, and show it; `done` once it is shown.
        private void ReadTelegram(MethodInvoker done)
        {
            AdvancedCall("advanced-remote-pair-state", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedTelegram = AdvancedDone(result) ? result : null;
                if (advancedTelegram != null && !Equals(Get(advancedTelegram, "pairing"), true)) telegramCode = null;
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        private void BuildTelegramCard()
        {
            TableLayoutPanel card = NewGroup(Word("page.remote.card", "Your Telegram chat"), advancedStack);
            string word = Str(advancedTelegram, "state");
            string state = word == "running" ? Word("page.remote.state.running", "The bot is being read.")
                         : word == "starting" ? Word("page.remote.state.starting", "Reading the bot starts with the watcher's next look.")
                         : word == "no_watcher" ? Word("page.remote.state.no_watcher", "Reading the bot starts with the watcher, which is not running.")
                         : word == "no_token" ? Word("page.remote.state.no_token", "The bot is not read: there is no bot token yet.")
                         : word == "no_chat" ? Word("page.remote.state.no_chat", "The bot is not read until a chat is paired.")
                         : word == "stopped" ? Word("page.remote.state.stopped", "It stopped too often, so it is not started again for now. It is tried again within the hour.")
                         : null;
            if (state != null)
            {
                Label line = HelpText(state);
                line.ForeColor = word == "running" ? Ink : Accent;
                card.Controls.Add(line);
            }
            bool token = Equals(Get(advancedTelegram, "token_saved"), true);
            string chat = Str(advancedTelegram, "chat");
            if (telegramCode != null)
                card.Controls.Add(HelpText(Word("page.courier.pair_code", "Send {code} to your bot within two minutes.", "code", telegramCode)));
            else if (Equals(Get(advancedTelegram, "paired"), true))
                card.Controls.Add(HelpText(string.IsNullOrEmpty(chat)
                    ? Word("page.remote.paired", "A chat is paired. Only that chat is obeyed.")
                    : Word("page.remote.paired_chat", "{chat} is paired. Only that chat is obeyed.", "chat", Mirror.Embed(chat))));
            else
                card.Controls.Add(HelpText(token
                    ? Word("page.remote.not_paired_token", "No chat is paired yet. Pair one with the button below, then send the code to your bot.")
                    : Word("page.remote.not_paired", "No chat is paired yet. Save the bot's token on the notices card, then pair a chat here.")));
            if (token)
                RemoteButton(card, Word("page.courier.pair", "Pair this chat"), "pair telegram", delegate { PairTelegram(); });
            else
                RemoteButton(card, Word("page.remote.open_notices", "Open the notices card"), "open notices", delegate { OpenNoticesCard(); });
            Label caption = Caption(Word("page.remote.commands", "What the chat may send"));
            caption.Margin = Pad(0, 10, 0, 2);
            card.Controls.Add(caption);
            card.Controls.Add(HelpText(Word("page.remote.command.status", "/status: how the watcher and recovery stand")));
            card.Controls.Add(HelpText(Word("page.remote.command.list", "/list: the waiting recoveries as task 1, task 2")));
            card.Controls.Add(HelpText(Word("page.remote.command.cancel", "/cancel task 1: cancel one, from the list last sent")));
            card.Controls.Add(HelpText(Word("page.remote.command.pause", "/pause: pause recovery")));
            if (Equals(Get(advancedTelegram, "continue"), true))
            {
                card.Controls.Add(HelpText(Word("page.remote.command.continue", "/continue task 1: let one held recovery go on")));
                card.Controls.Add(HelpText(Word("page.remote.command.lift_pause", "/recovery-on: lift a pause")));
            }
        }

        /// The push notices card, where the bot's token is kept: its row picked in the list, as a click picks it.
        private void OpenNoticesCard()
        {
            if (advancedList == null) return;
            foreach (ListViewItem item in advancedList.Items)
                if (Str(item.Tag as Dictionary<string, object>, "id") == "push_notices")
                {
                    item.Selected = true;
                    item.Focused = true;
                    item.EnsureVisible();
                    return;
                }
        }

        private void PairTelegram()
        {
            if (busy > 0 || advancedListing == null) return;
            AdvancedCall("advanced-remote-pair-start", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                telegramCode = AdvancedDone(result) ? Str(result, "code") : null;
                ReadTelegram(null);
                if (!AdvancedDone(result)) TellAdvanced(CourierRefusal(Str(result, "refusal")));
            });
        }

        private void NewApiToken(bool replaces)
        {
            if (busy > 0 || advancedListing == null) return;
            if (replaces && !AskAdvanced(Word("page.confirm.api_token", "Make a new token? The old address stops working at once."),
                                         Affirm(Word("page.api.new_token_yes", "New token"))))
                return;
            AdvancedCall("advanced-api-token-new", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                bool made = AdvancedDone(result);
                bool copied = made && PutOnClipboard(Str(result, "copy_url"));
                ReadApi(null);
                if (copied) ResetNote(Word("page.done.api_token", "A new token is kept, and its address is copied."));
                else if (made) ResetNote(Word("page.done.api_token_kept", "A new token is kept. Copy address carries it."));
                else TellAdvanced(CourierRefusal(Str(result, "refusal")));
            });
        }
    }
}

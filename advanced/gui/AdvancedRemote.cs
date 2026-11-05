// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the loopback API's card on the Advanced features page (v0.6.22, plans/v0619-design/D-remote.md).
//
// While Read this PC's status from a browser or a script is on or watched, its column has a card "Address and token": how
// the server stands (running, starting, stopped for this hour, or its port taken), the address without its token, whether
// a token is kept, Copy address - the address carrying the token in its fragment, which a browser never sends - and
// New token..., which asks first once there is one to replace. The port is its Choices card's, as every choice of the page
// is; what widens it (pausing and cancelling, the local network) are rows of their own in the list. The card's requests are
// the bridge's (advanced-api, advanced-api-token-new), the Dashboard's alone; the token is never drawn and never kept here:
// it goes to the clipboard once and is forgotten.
//
// Nothing here draws anything the page does not draw already: the card, its help lines and its buttons are the Settings
// page's, in both themes and both designs, mirrored for Arabic and Hebrew by the page. It opens no window of its own.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string ApiId = "local_api";

        // advanced-api's last answer - never one asked with copy - or null where it was not read or the read failed.
        private Dictionary<string, object> advancedApi;
        // The card's buttons by their Tag ("copy api", "token api"); what a test's run copied instead of the clipboard.
        private readonly List<Button> remoteButtons = new List<Button>();
        private List<string> remoteCopied;

        /// What the card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string RemoteShown(Dictionary<string, object> item)
        {
            string id = Str(item, "id");
            return id == ApiId ? AdvancedWritten(advancedApi) : "";
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
            if (Equals(Get(advancedApi, "lan"), true))
            {
                Label lan = HelpText(Word("page.api.lan", "Open to your local network, without encryption."));
                lan.ForeColor = Accent;
                card.Controls.Add(lan);
            }
            if (kept) RemoteButton(card, Word("page.api.copy", "Copy address"), "copy api", delegate { CopyApiAddress(); });
            RemoteButton(card, Word("page.api.new_token", "New token..."), "token api", delegate { NewApiToken(kept); });
        }

        /// How the server stands, in a line; null while it is off.
        private string ApiStateLine(string state)
        {
            if (state == "running") return Word("page.api.state.running", "The server is running.");
            if (state == "starting") return Word("page.api.state.starting", "The server starts with the watcher's next look.");
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
                Clipboard.SetText(text);
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
            AdvancedCall("advanced-api", "{\"copy\":true}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result) && PutOnClipboard(Str(result, "copy_url")))
                    ResetNote(Word("page.done.api_copied", "Copied. Whoever has this address can read this PC's status."));
                else TellAdvanced(Word("page.refused.api_not_copied", "The address could not be copied."));
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

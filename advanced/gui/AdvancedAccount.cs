// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Codex account card on the Advanced features page (v0.6.20, account_switch).
//
// While account_switch is on or watched, its column has a card under its limits: the account this PC is signed in to -
// "Signed in: Plus · s•••@e•••.com", read by the bridge (advanced-account) with Codex's account/read in the Dashboard's
// process, the address masked there and never stored - or "Not signed in", or that it cannot be read now. Under it,
// how to switch in Codex itself: until MAL has passed on the Codex in force, that is the card's whole offer (the
// narrower route). The card is read when the capability is opened, as keep going's is.
//
// Nothing here draws anything the page does not draw already: the card, its help lines and its rows are the Settings
// page's.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System.Collections.Generic;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string AccountId = "account_switch";

        // advanced-account's last answer, or null where it was not read or the read failed (or the capability is off).
        private Dictionary<string, object> advancedAccount;

        /// What the account card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string AccountShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != AccountId) return "";
            return AdvancedWritten(advancedAccount);
        }

        /// Read advanced-account, keep it, and show it; `done` once it is shown.
        private void ReadAccount(MethodInvoker done)
        {
            AdvancedCall("advanced-account", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedAccount = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        /// The open capability's card, while account_switch is on or watched: the account signed in, then how to switch.
        private void BuildAccount(Dictionary<string, object> item)
        {
            if (Str(item, "id") != AccountId || !Standing(item) || advancedAccount == null) return;
            var card = NewGroup(Word("page.account.title", "Codex account"), advancedStack);
            var line = HelpText(AccountLine(advancedAccount));
            line.ForeColor = Ink;
            line.Margin = Pad(0, 6, 0, 2);
            card.Controls.Add(line);
            card.Controls.Add(HelpText(Word("page.account.guidance",
                "To switch, sign out in Codex (Settings > Account), then sign in there with the other account. Until it has been measured on this Codex that the running app follows a sign-in made from here, this page offers no button for it.")));
        }

        /// The account as the card says it: signed in - with its plan and its masked address where Codex named them - not
        /// signed in, or not known.
        private string AccountLine(Dictionary<string, object> account)
        {
            object present = Get(account, "present");
            if (Equals(present, false)) return Word("page.account.signed_out", "Not signed in. Sign in in Codex.");
            if (!Equals(present, true))
                return Word("page.account.unknown", "Which account is signed in cannot be read right now.");
            var parts = new List<string>();
            string plan = PlanName(Str(account, "plan"));
            if (plan != null) parts.Add(plan);
            string mask = Str(account, "mask");
            if (!string.IsNullOrEmpty(mask)) parts.Add(mask);
            else if (Str(account, "kind") == "apikey") parts.Add(Word("page.account.api_key", "an API key"));
            if (parts.Count == 0) return Word("page.account.signed_in_only", "Signed in");
            return Word("page.account.signed_in", "Signed in: {account}", "account", string.Join(" · ", parts.ToArray()));
        }

        /// A plan word (vocabulary.PlanWord) as its plan is named: ChatGPT's own names, the same in every language, and
        /// "another plan" in the reader's for any other.
        private string PlanName(string plan)
        {
            switch (plan)
            {
                case "free": return "Free";
                case "plus": return "Plus";
                case "pro": return "Pro";
                case "team": return "Team";
                case "business": return "Business";
                case "enterprise": return "Enterprise";
                case "edu": return "Edu";
                case "other": return Word("page.account.plan_other", "another plan");
                default: return null;
            }
        }
    }
}

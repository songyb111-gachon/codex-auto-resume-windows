// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Codex account card on the Advanced features page (v0.6.20, account_switch).
//
// While account_switch is on or watched, its column has a card under its limits: the account this PC is signed in to -
// "Signed in: Plus · s•••@e•••.com", read by the bridge (advanced-account) with Codex's account/read in the Dashboard's
// process, the address masked there and never stored - or "Not signed in", or that it cannot be read now. Under it, once
// MAL has passed on the Codex in force and the capability is on, Sign out and sign in with another account..., which asks
// first and sends advanced-account-switch: the bridge runs Codex's own `codex logout` and `codex login`, the person
// signs in in their browser, and the card reads "Waiting for the sign-in in your browser..." - read again every
// AccountPollMilliseconds - until it says how it ended. Until MAL has passed, the card says how to switch in Codex
// instead (the narrower route). The card is read when the capability is opened, as keep going's is.
//
// Nothing here draws anything the page does not draw already: the card, its help lines, its rows and its button are the
// Settings page's.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System.Collections.Generic;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string AccountId = "account_switch";
        private const int AccountPollMilliseconds = 2000;

        // advanced-account's last answer, or null where it was not read or the read failed (or the capability is off).
        private Dictionary<string, object> advancedAccount;
        // The card's one button, where it is offered, and the timer that reads the card again while a sign-in waits.
        private Button accountSwitch;
        private Timer accountTimer;
        private bool accountPolling;

        /// What the account card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string AccountShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != AccountId) return "";
            return AdvancedWritten(advancedAccount);
        }

        /// Read advanced-account, keep it, and show it; `done` once it is shown. While a sign-in waits, read again on the
        /// timer until it has ended.
        private void ReadAccount(MethodInvoker done)
        {
            AdvancedCall("advanced-account", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedAccount = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                WatchAccount();
                if (done != null) done();
            });
        }

        /// The timer started while a sign-in waits and stopped once it has ended - never in a test's window, which reads the
        /// card itself ({"do": "poll_account"}).
        private void WatchAccount()
        {
            bool waiting = Str(advancedAccount, "switch") == "waiting";
            if (!waiting || advancedScript != null || auditing)
            {
                if (accountTimer != null) accountTimer.Stop();
                return;
            }
            if (accountTimer == null)
            {
                accountTimer = new Timer();
                accountTimer.Interval = AccountPollMilliseconds;
                accountTimer.Tick += delegate { PollAccount(); };
                Disposed += delegate { accountTimer.Dispose(); };
            }
            accountTimer.Start();
        }

        private void PollAccount()
        {
            if (accountPolling || advancedOpen != AccountId) return;
            accountPolling = true;
            ReadAccount(delegate { accountPolling = false; });
        }

        /// The open capability's card, while account_switch is on or watched: the account signed in, then the button or how
        /// to switch in Codex.
        private void BuildAccount(Dictionary<string, object> item)
        {
            accountSwitch = null;
            if (Str(item, "id") != AccountId || !Standing(item) || advancedAccount == null) return;
            var card = NewGroup(Word("page.account.title", "Codex account"), advancedStack);
            string state = Str(advancedAccount, "switch");
            var line = HelpText(state == "waiting"
                ? Word("page.account.waiting", "Waiting for the sign-in in your browser...")
                : AccountLine(advancedAccount));
            line.ForeColor = Ink;
            line.Margin = Pad(0, 6, 0, 2);
            card.Controls.Add(line);
            string ended = AccountOutcome(state);
            if (ended != null) card.Controls.Add(HelpText(ended));
            if (Equals(Get(advancedAccount, "button"), true))
            {
                card.Controls.Add(HelpText(Word("page.account.button_help",
                    "Codex signs out on this PC, then your browser opens Codex's own sign-in page, where you sign in with the account you want. This product never sees your password.")));
                accountSwitch = CardButton(card, Word("page.account.button", "Sign out and sign in with another account..."),
                                           delegate { SwitchAccount(); });
                accountSwitch.Margin = Pad(0, 8, 0, 4);
            }
            else
                card.Controls.Add(HelpText(Word("page.account.guidance",
                    "To switch, sign out in Codex (Settings > Account), then sign in there with the other account. Until it has been measured on this Codex that the running app follows a sign-in made from here, this page offers no button for it.")));
        }

        private void UpdateAccountButtons(bool idle)
        {
            if (accountSwitch != null)
                accountSwitch.Enabled = idle && advancedListing != null && advancedAccount != null &&
                                        Str(advancedAccount, "switch") != "waiting";
        }

        /// Codex's own sign-out and sign-in, after the person said yes to what it does.
        private void SwitchAccount()
        {
            if (busy > 0 || advancedListing == null || accountSwitch == null) return;
            string question = Word("page.confirm.account_switch",
                "Codex will sign out on this PC. Your browser opens Codex's own sign-in page; sign in there. Recoveries waiting for a usage limit will wait for you afterwards.");
            if (!AskAdvanced(question, Affirm(Word("page.account.button", "Sign out and sign in with another account...")))) return;
            AdvancedCall("advanced-account-switch", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (!AdvancedDone(result)) TellAdvanced(AccountRefusal(Str(result, "refusal")));
                ReadAccount(null);
            });
        }

        private string AccountRefusal(string refusal)
        {
            if (refusal == "switch_unmeasured")
                return Word("page.refused.switch_unmeasured",
                    "It has not been measured on this Codex that the running app follows a sign-in made from here. Switch in Codex instead.");
            if (refusal == "switch_running")
                return Word("page.refused.switch_running", "A sign-in is already waiting in your browser.");
            if (refusal == "not_on") return Word("page.refused.not_on", "Turn it on first.");
            return KeptRefusal(refusal);
        }

        /// How the last sign-out and sign-in ended, or null where none has in this Dashboard.
        private string AccountOutcome(string state)
        {
            switch (state)
            {
                case "signed_in": return Word("page.account.result.signed_in", "The sign-in finished.");
                case "cancelled":
                    return Word("page.account.result.cancelled", "Codex is not signed in: the sign-in was cancelled. Sign in in Codex.");
                case "timed_out":
                    return Word("page.account.result.timed_out", "The sign-in did not finish within ten minutes. Sign in in Codex.");
                case "failed":
                    return Word("page.account.result.failed", "The sign-out and sign-in could not be completed. Check Codex's own sign-in.");
                default: return null;
            }
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

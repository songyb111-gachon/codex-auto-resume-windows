// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Codex account card on the Advanced features page (v0.6.20, account_switch).
//
// While account_switch is on or watched, its column has a card under its limits: the account this PC is signed in to -
// "Signed in: Plus · s•••@e•••.com", read by the bridge (advanced-account) with Codex's account/read in the Dashboard's
// process, the address masked there and never stored - or "Not signed in", or that it cannot be read now. Under it, once
// MALR has passed on the Codex in force and the capability is on, Sign out and sign in with another account..., which asks
// first and sends advanced-account-switch: the bridge runs Codex's own `codex logout` and `codex login`, the person
// signs in in their browser, and the card reads "Waiting for the sign-in in your browser..." - read again every
// AccountPollMilliseconds - until it says how it ended. Until MALR has passed, the card says how to switch in Codex
// instead (the narrower route). The card is read when the capability is opened, as keep going's is.
//
// v0.6.20 final (the owner: ask, then restart): the running Codex app does not follow that sign-in until it is
// restarted, so a sign-in that finished leaves the card asking "Restart Codex now so it uses the new account?" with
// Restart Codex and Not now (advanced-account-restart {"now": true|false}). Restart is enabled only while the bridge says
// nothing runs or waits ("busy" empty); otherwise the card says it waits and reads itself again on the timer, and offers
// Restart again once it is clear. Not now leaves "Codex needs a restart to use the new account." with Restart Codex
// still there. While Codex restarts the card reads "Restarting Codex..." until it says how it ended.
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
        // v0.6.20 final: Restart Codex and Not now, where the restart after a sign-in is offered.
        private Button accountRestart;
        private Button accountLater;
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

        /// Whether the card waits on something that will change by itself: a sign-in in the browser, a restart running, or
        /// a restart asked for while Codex is busy.
        private bool AccountWaiting()
        {
            if (Str(advancedAccount, "switch") == "waiting") return true;
            string restart = Str(advancedAccount, "restart");
            if (restart == "restarting") return true;
            return AccountRestartable(restart) && !AccountClear();
        }

        /// The timer started while the card waits (AccountWaiting) and stopped once it does not - never in a test's window,
        /// which reads the card itself ({"do": "poll_account"}).
        private void WatchAccount()
        {
            bool waiting = AccountWaiting();
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
            accountRestart = null;
            accountLater = null;
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
            if (Equals(Get(advancedAccount, "button"), true) && BuildAccountRestart(card)) return;
            if (Equals(Get(advancedAccount, "button"), true))
            {
                card.Controls.Add(HelpText(Word("page.account.button_help",
                    "Codex signs out on this PC, then your browser opens Codex's own sign-in page, where you sign in with the account you want. This product never sees your password. When the sign-in has finished, you are asked whether to restart Codex so it uses the new account.")));
                accountSwitch = CardButton(card, Word("page.account.button", "Sign out and sign in with another account..."),
                                           delegate { SwitchAccount(); });
                accountSwitch.Margin = Pad(0, 8, 0, 4);
            }
            else if (Equals(Get(advancedAccount, "measurement_failed"), true))
                // A part hidden because its measurement failed says so (the owner, 2026-10-31); not "until it is measured".
                card.Controls.Add(HelpText(Word("page.account.guidance_failed",
                    "The sign-out and sign-in button is hidden because its measurement failed on this Codex. To switch, sign out in Codex (Settings > Account), then sign in there with the other account.")));
            else
                card.Controls.Add(HelpText(Word("page.account.guidance",
                    "To switch, sign out in Codex (Settings > Account), then sign in there with the other account. Until it has been measured on this Codex that a sign-in made from here, followed by a restart of Codex, brings Codex up with the new account, this page offers no button for it.")));
        }

        /// The restart after a sign-in, where one is asked, put off, running or just ended: its lines and buttons, and true
        /// where they stand in place of the switch button.
        private bool BuildAccountRestart(TableLayoutPanel card)
        {
            string restart = Str(advancedAccount, "restart");
            if (restart == "restarting")
            {
                card.Controls.Add(HelpText(Word("page.account.restart.restarting", "Restarting Codex...")));
                return true;
            }
            string ended = AccountRestartOutcome(restart);
            if (ended != null) card.Controls.Add(HelpText(ended));
            if (!AccountRestartable(restart)) return false;
            var question = HelpText(restart == "not_now"
                ? Word("page.account.restart.needed", "Codex needs a restart to use the new account.")
                : Word("page.account.restart.ask", "Restart Codex now so it uses the new account?"));
            question.ForeColor = Ink;
            card.Controls.Add(question);
            card.Controls.Add(HelpText(Word("page.account.restart.help",
                "Codex is closed and started again. If it has not closed 30 seconds after Windows asked it to, its process is ended, and anything unsaved in Codex's window may be lost.")));
            if (!AccountClear())
                card.Controls.Add(HelpText(Word("page.account.restart.busy",
                    "Codex is busy: a turn is running, a recovery waits or runs, or a message is queued. Restart is offered again when they are done.")));
            accountRestart = CardButton(card, Word("page.account.restart.button", "Restart Codex"),
                                        delegate { RestartCodex(true); });
            accountRestart.Margin = Pad(0, 8, 0, 4);
            accountRestart.Enabled = AccountClear();
            if (restart != "not_now")
            {
                accountLater = CardButton(card, Word("page.account.restart.not_now", "Not now"),
                                          delegate { RestartCodex(false); });
                accountLater.Margin = Pad(0, 4, 0, 4);
            }
            return true;
        }

        /// Whether Restart may be pressed in this state: asked, put off, or a restart that did not get Codex going again.
        private static bool AccountRestartable(string restart)
        {
            return restart == "ask" || restart == "not_now" || restart == "not_ended" || restart == "not_started" ||
                   restart == "restart_failed";
        }

        /// Whether the bridge said nothing runs or waits now: its "busy" list empty.
        private bool AccountClear()
        {
            List<object> busy = Items(advancedAccount, "busy");
            return busy == null || busy.Count == 0;
        }

        private void UpdateAccountButtons(bool idle)
        {
            if (accountSwitch != null)
                accountSwitch.Enabled = idle && advancedListing != null && advancedAccount != null &&
                                        Str(advancedAccount, "switch") != "waiting";
            if (accountRestart != null)
                accountRestart.Enabled = idle && advancedListing != null && advancedAccount != null && AccountClear();
            if (accountLater != null)
                accountLater.Enabled = idle && advancedListing != null && advancedAccount != null;
        }

        /// Restart Codex - after the person said yes to what it does - or Not now.
        private void RestartCodex(bool now)
        {
            if (busy > 0 || advancedListing == null || accountRestart == null) return;
            if (now)
            {
                string question = Word("page.confirm.account_restart",
                    "Codex will be closed and started again so it uses the new account. Anything unsaved in Codex's window may be lost.");
                if (!AskAdvanced(question, Affirm(Word("page.account.restart.button", "Restart Codex")))) return;
            }
            AdvancedCall("advanced-account-restart", now ? "{\"now\": true}" : "{\"now\": false}", true,
                delegate(Dictionary<string, object> reply)
                {
                    Dictionary<string, object> result = AdvancedResult(reply);
                    if (!AdvancedDone(result)) TellAdvanced(AccountRefusal(Str(result, "refusal")));
                    ReadAccount(null);
                });
        }

        /// How the last restart ended, or null where none has (or it is not over).
        private string AccountRestartOutcome(string restart)
        {
            if (restart == "restarted")
                return Word("page.account.restart.result.restarted", "Codex was restarted and is signed in.");
            if (restart == "restarted_signed_out")
                return Word("page.account.restart.result.signed_out", "Codex was restarted, but no account is signed in. Sign in in Codex.");
            if (restart == "not_running")
                return Word("page.account.restart.result.not_running", "Codex was not running: it uses the new account when you open it.");
            if (restart == "not_ended")
                return Word("page.account.restart.result.not_ended", "Codex could not be closed. Close it completely and open it again so it uses the new account.");
            if (restart == "not_started")
                return Word("page.account.restart.result.not_started", "Codex was closed but did not start again. Open Codex yourself.");
            if (restart == "restart_failed")
                return Word("page.account.restart.result.failed", "Codex could not be restarted. Close it completely and open it again so it uses the new account.");
            return null;
        }

        /// Codex's own sign-out and sign-in, after the person said yes to what it does.
        private void SwitchAccount()
        {
            if (busy > 0 || advancedListing == null || accountSwitch == null) return;
            string question = Word("page.confirm.account_switch",
                "Codex will sign out on this PC. Your browser opens Codex's own sign-in page; sign in there. Recoveries waiting for a usage limit will wait for you afterwards. Codex then needs a restart to use the new account; you are asked first.");
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
                    "It has not been measured on this Codex that a sign-in made from here, followed by a restart of Codex, brings Codex up with the new account. Switch in Codex instead.");
            if (refusal == "switch_running")
                return Word("page.refused.switch_running", "A sign-in is already waiting in your browser.");
            if (refusal == "restart_busy")
                return Word("page.account.restart.busy",
                    "Codex is busy: a turn is running, a recovery waits or runs, or a message is queued. Restart is offered again when they are done.");
            if (refusal == "restart_running")
                return Word("page.refused.restart_running", "Codex is already being restarted.");
            if (refusal == "nothing_to_restart")
                return Word("page.refused.nothing_to_restart", "There is no new sign-in to restart Codex for.");
            if (refusal == "not_on") return Word("page.refused.not_on", "Turn it on first.");
            return KeptRefusal(refusal);
        }

        /// How the last sign-out and sign-in ended, or null where none has in this Dashboard.
        private string AccountOutcome(string state)
        {
            // If-chains, not a string switch: the compiler names a switch's hash table at random (build/normalize_pe.py).
            if (state == "signed_in") return Word("page.account.result.signed_in", "The sign-in finished.");
            if (state == "cancelled")
                return Word("page.account.result.cancelled", "Codex is not signed in: the sign-in was cancelled. Sign in in Codex.");
            if (state == "timed_out")
                return Word("page.account.result.timed_out", "The sign-in did not finish within ten minutes. Sign in in Codex.");
            if (state == "failed")
                return Word("page.account.result.failed", "The sign-out and sign-in could not be completed. Check Codex's own sign-in.");
            return null;
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
            if (plan == "other") return Word("page.account.plan_other", "another plan");
            string[] plans = { "free", "Free", "plus", "Plus", "pro", "Pro", "team", "Team", "business", "Business",
                               "enterprise", "Enterprise", "edu", "Edu" };
            for (int i = 0; i < plans.Length; i += 2)
                if (plans[i] == plan) return plans[i + 1];
            return null;
        }
    }
}

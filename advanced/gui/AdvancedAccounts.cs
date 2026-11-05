// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the saved accounts of the automatic account switch, on the Advanced features page (v0.6.22).
//
// While account_auto_switch is on or watched, its column has a card under its limits: the person's saved Codex accounts,
// each a flat check row (the window's lists stay flat hairline rows, never raised tiles) saying the address masked as the
// account card masks it, the plan and a state word - ready, at its limit, needs a new sign-in, cannot be opened; a line
// when Codex keeps its sign-in outside a file here, so nothing can be switched; Add an account..., which asks first and
// then runs Codex's own sign-in in the browser - the card is read again every AccountsPollMilliseconds while it waits -;
// Save the account in use; Delete for the rows ticked and Delete all, each asking first with Cancel the default.
//
// Each request is the bridge's (control/autoswitch.py): advanced-accounts for the card, advanced-accounts-add,
// advanced-accounts-save and advanced-accounts-delete; the card is read again after each. The address itself never
// reaches the window: the bridge answers it masked. Its words are this edition's catalog's.
//
// Nothing here draws anything the page does not draw already: the card, its help lines, check rows and buttons are the
// Settings page's, in both themes and both designs, mirrored for Arabic and Hebrew by the page.
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
        private const string AccountsId = "account_auto_switch";
        private const int AccountsPollMilliseconds = 2000;

        // advanced-accounts' last answer, or null where it was not read or the read failed.
        private Dictionary<string, object> advancedAccounts;
        // The card's form as it was built: each saved account's row, and its buttons.
        private readonly List<CheckBox> accountsRows = new List<CheckBox>();
        private Button accountsAdd, accountsSave, accountsDelete, accountsDeleteAll;
        private Timer accountsTimer;
        private bool accountsPolling;

        /// What the card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string AccountsShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != AccountsId) return "";
            return AdvancedWritten(advancedAccounts);
        }

        /// Read advanced-accounts, keep it, and show it; `done` once it is shown.
        private void ReadAccounts(MethodInvoker done)
        {
            AdvancedCall("advanced-accounts", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedAccounts = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                WatchAccounts();
                if (done != null) done();
            });
        }

        /// The timer started while an Add an account waits for the browser, and stopped once it does not - never in a test's
        /// window, which reads the card itself.
        private void WatchAccounts()
        {
            bool waiting = Str(advancedAccounts, "add_state") == "waiting";
            if (!waiting || advancedScript != null || auditing)
            {
                if (accountsTimer != null) accountsTimer.Stop();
                return;
            }
            if (accountsTimer == null)
            {
                accountsTimer = new Timer();
                accountsTimer.Interval = AccountsPollMilliseconds;
                accountsTimer.Tick += delegate { PollAccounts(); };
                Disposed += delegate { accountsTimer.Dispose(); };
            }
            accountsTimer.Start();
        }

        private void PollAccounts()
        {
            if (accountsPolling || advancedOpen != AccountsId) return;
            accountsPolling = true;
            ReadAccounts(delegate { accountsPolling = false; });
        }

        private string AccountsState(string state)
        {
            if (state == "ready") return Word("page.accounts.state.ready", "ready");
            if (state == "exhausted") return Word("page.accounts.state.exhausted", "at its limit");
            if (state == "needs_sign_in") return Word("page.accounts.state.needs_sign_in", "needs a new sign-in");
            return Word("page.accounts.state.damaged", "cannot be opened");
        }

        /// One saved account as its row says it: the address masked, the plan, the state word.
        private string AccountsLine(Dictionary<string, object> row)
        {
            var parts = new List<string>();
            string mask = Str(row, "mask");
            parts.Add(string.IsNullOrEmpty(mask) ? Word("page.account.signed_in_only", "Signed in") : mask);
            string plan = PlanName(Str(row, "plan"));
            if (plan != null) parts.Add(plan);
            parts.Add(AccountsState(Str(row, "state")));
            return string.Join(" · ", parts.ToArray());
        }

        /// The open capability's card, while account_auto_switch is on or watched: the saved accounts and their buttons.
        private void BuildAccounts(Dictionary<string, object> item)
        {
            ForgetAccountsCard();
            if (Str(item, "id") != AccountsId || !Standing(item) || advancedAccounts == null) return;
            TableLayoutPanel card = NewGroup(Word("page.accounts.title", "Saved accounts"), advancedStack);
            card.Controls.Add(HelpText(Word("page.accounts.help",
                "Your own other Codex accounts. When a recovery waits for a usage limit, the one with the most room is switched in.")));
            if (Str(advancedAccounts, "store") != "usable")
                card.Controls.Add(HelpText(Word("page.accounts.not_file",
                    "Codex keeps its sign-in outside a file here, so accounts cannot be switched.")));
            foreach (object entry in Items(advancedAccounts, "profiles") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                string id = Str(row, "id");
                if (id == null) continue;
                CheckBox check = NewCheck(AccountsLine(row), false, true);
                check.Tag = id;
                check.CheckedChanged += delegate { UpdateAccountsButtons(busy == 0); };
                card.Controls.Add(check);
                accountsRows.Add(check);
            }
            if (accountsRows.Count == 0)
                card.Controls.Add(HelpText(Word("page.accounts.none", "No account saved yet.")));
            string addState = Str(advancedAccounts, "add_state");
            if (addState == "waiting")
                card.Controls.Add(HelpText(Word("page.account.waiting", "Waiting for the sign-in in your browser...")));
            else if (addState == "added")
                card.Controls.Add(HelpText(Word("page.accounts.added", "The account was saved.")));
            else if (addState == "not_added")
                card.Controls.Add(HelpText(Word("page.accounts.not_added", "No account was saved: the sign-in did not finish.")));
            accountsAdd = CardButton(card, Word("page.accounts.add", "Add an account..."), delegate { AddAccount(); });
            accountsAdd.Margin = Pad(0, 8, 0, 4);
            accountsSave = CardButton(card, Word("page.accounts.save", "Save the account in use"), delegate { SaveAccount(); });
            accountsDelete = CardButton(card, Word("page.accounts.delete", "Delete"), delegate { DeleteAccounts(false); });
            accountsDeleteAll = CardButton(card, Word("page.accounts.delete_all", "Delete all"), delegate { DeleteAccounts(true); });
        }

        private void ForgetAccountsCard()
        {
            accountsRows.Clear();
            accountsAdd = accountsSave = accountsDelete = accountsDeleteAll = null;
        }

        private List<string> AccountsPicked()
        {
            var picked = new List<string>();
            foreach (CheckBox row in accountsRows)
                if (row.Checked && row.Tag is string) picked.Add((string)row.Tag);
            return picked;
        }

        private void UpdateAccountsButtons(bool idle)
        {
            bool listed = idle && advancedListing != null && advancedAccounts != null;
            bool usable = listed && Str(advancedAccounts, "store") == "usable";
            foreach (CheckBox row in accountsRows) row.Enabled = listed;
            if (accountsAdd != null) accountsAdd.Enabled = usable && Str(advancedAccounts, "add_state") != "waiting";
            if (accountsSave != null) accountsSave.Enabled = usable;
            if (accountsDelete != null) accountsDelete.Enabled = listed && AccountsPicked().Count > 0;
            if (accountsDeleteAll != null) accountsDeleteAll.Enabled = listed && accountsRows.Count > 0;
        }

        private void AddAccount()
        {
            if (busy > 0 || advancedAccounts == null) return;
            if (!AskAdvanced(Word("page.confirm.accounts_add",
                    "Your browser opens OpenAI's sign-in page. Sign in there with another account of your own; this product never sees your password."),
                    Affirm(Word("page.accounts.add", "Add an account...")))) return;
            AdvancedCall("advanced-accounts-add", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                ReadAccounts(null);
                if (!AdvancedDone(result)) TellAdvanced(AccountsRefusal(Str(result, "refusal")));
            });
        }

        private void SaveAccount()
        {
            if (busy > 0 || advancedAccounts == null) return;
            AdvancedCall("advanced-accounts-save", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result) && Equals(Get(result, "saved"), true))
                    ResetNote(Word("page.done.accounts_saved", "The account in use was saved."));
                else if (AdvancedDone(result))
                    TellAdvanced(Word("page.refused.accounts_not_saved",
                        "The account in use could not be saved: its sign-in is not in a file, or which account it is cannot be read."));
                else TellAdvanced(AccountsRefusal(Str(result, "refusal")));
                ReadAccounts(null);
            });
        }

        /// Delete the rows ticked, or every saved account; each asks first.
        private void DeleteAccounts(bool all)
        {
            if (busy > 0 || advancedAccounts == null) return;
            List<string> picked = AccountsPicked();
            if (!all && picked.Count == 0) return;
            string question = all
                ? Word("page.confirm.accounts_delete_all", "Delete every saved account? Their copies are removed from this PC.")
                : Word("page.confirm.accounts_delete", "Delete {n} saved accounts? Their copies are removed from this PC.",
                       "n", Mirror.Embed(picked.Count.ToString(CultureInfo.CurrentCulture)));
            if (!AskAdvanced(question, Affirm(Word(all ? "page.accounts.delete_all" : "page.accounts.delete",
                                                   all ? "Delete all" : "Delete")))) return;
            if (all)
            {
                AdvancedCall("advanced-accounts-delete", "{\"all\":true}", true, delegate(Dictionary<string, object> reply)
                {
                    AccountsDeleted(AdvancedResult(reply));
                });
                return;
            }
            DeleteNext(picked, 0);
        }

        /// One ticked account at a time, each its own request, then the card read again.
        private void DeleteNext(List<string> picked, int index)
        {
            if (index >= picked.Count) { ReadAccounts(null); return; }
            AdvancedCall("advanced-accounts-delete", "{\"id\":" + Json.Escape(picked[index]) + "}", true,
                delegate(Dictionary<string, object> reply)
                {
                    Dictionary<string, object> result = AdvancedResult(reply);
                    if (!AdvancedDone(result)) { AccountsDeleted(result); return; }
                    DeleteNext(picked, index + 1);
                });
        }

        private void AccountsDeleted(Dictionary<string, object> result)
        {
            if (AdvancedDone(result)) ResetNote(Word("page.done.accounts_deleted", "Deleted."));
            else TellAdvanced(AccountsRefusal(Str(result, "refusal")));
            ReadAccounts(null);
        }

        private string AccountsRefusal(string refusal)
        {
            if (refusal == "switch_running")
                return Word("page.refused.switch_running", "A sign-in is already waiting in your browser.");
            return ResetRefusal(refusal);
        }
    }
}

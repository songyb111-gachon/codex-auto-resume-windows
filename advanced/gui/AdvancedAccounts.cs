// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the saved accounts of the automatic account switch, on the Advanced features page (v0.6.22).
//
// v0.6.22 after the security review (finding 3): a saved sign-in can be deleted in every state. While account_auto_switch
// is on or watched, its column has the whole card; off with accounts still kept, the card lists them with Delete and
// Delete all only; hidden (registry.WAITING) with accounts kept, that same card stands under account_switch's column.
// The card: the person's saved Codex accounts,
// each a flat check row (the window's lists stay flat hairline rows, never raised tiles) saying the address masked as the
// account card masks it, the plan and a state word - ready, at its limit, needs a new sign-in, cannot be opened; a line
// when Codex keeps its sign-in outside a file here, so nothing can be switched; Add an account..., which asks first and
// then runs Codex's own sign-in in the browser - the card is read again every AccountsPollMilliseconds while it waits -;
// Save the account in use; Delete for the rows ticked and Delete all, each asking first with Cancel the default - Save
// too, since the v0.6.22 final (the reachability audit's M11).
//
// Add an account... signs in on a scratch home of its own, so it works while Codex is signed out here (store "no_file");
// only Save and the switch itself need Codex's own sign-in file. The line under the heading says which is the case: a
// sign-in kept outside a file (nothing can be switched), Codex signed out here (sign in to Codex, or add an account), or
// Codex's settings unreadable (the reachability audit's R4: it said "outside a file" for every one of them).
//
// The usage meters (v0.6.22 final, the owner's mock of 2026-11-08): under each row two grooves, "5-hour" and "7-day", each
// with the share used inside it and "<N>% · in <time>" after it - the bar in the accent, in the warning colour from 90 per
// cent, the groove empty and "not read yet" where no reading was made (AdvancedMeter.cs); the account signed in says "in
// use" in the accent, and a row whose last read broke says "could not be read" and keeps its last reading. Under the rows
// one muted line: when the readings were made and the next switch candidate, or that none has room. Read usage, at the
// card's top right while the capability stands, reads every saved account now - one at a time, in the background, the
// card read again every AccountsPollMilliseconds while it reads ("Reading usage... 1 of 3") - and says, once used, when it
// can be used again: at most once every ten minutes. It sends nothing and switches nothing.
//
// Switch to this account (v0.6.22 final, the owner's 2026-11-08): on each saved account's row but the one in use, and only
// where its state is usable (ready, or at its limit - never needs a new sign-in or cannot be opened) and Codex keeps its
// sign-in in a file here, a button under the row's meters. It asks first, Cancel the default as Save does: the Codex app
// closes, anything not yet sent in its window may be lost, the account in use is saved back first, and Codex starts again
// as the account picked, masked. The bridge then runs the automatic switch's own switch on a thread of its own; the card is
// read again every AccountsPollMilliseconds while it runs ("Switching to ...") and says once how it ended - switched, not
// started again, not finished and undone, not finished and to be put back, or nothing switched - and a refusal says why.
//
// The same saved accounts under both account capabilities (the owner, 2026-11-08): this card stands in account_auto_switch's
// column and in account_switch's, one implementation drawn wherever the open column is one of them - the rows, Read usage,
// Add an account..., Save the account in use, Delete, Delete all and Switch to this account. Add, Save and Read usage while
// the open capability is on or watched; Delete, Delete all and Switch to this account wherever the card shows.
//
// Each request is the bridge's (control/autoswitch.py): advanced-accounts for the card, advanced-accounts-add,
// advanced-accounts-save, advanced-accounts-delete, advanced-accounts-read and advanced-accounts-switch; the card is read
// again after each. The address itself never reaches the window: the bridge answers it masked. Its words are this edition's
// catalog's.
//
// Nothing here draws anything the page does not draw already: the card, its help lines, check rows and buttons are the
// Settings page's, in both themes and both designs, mirrored right to left by the page.
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
        private Button accountsAdd, accountsSave, accountsDelete, accountsDeleteAll, accountsRead;
        // Switch to this account, one for each row that offers it.
        private readonly List<Button> accountsSwitches = new List<Button>();
        // The saved accounts ticked when the card was last taken down: a re-read that changes the list rebuilds it, and
        // the rows it still lists stay ticked.
        private List<string> accountsTicked = new List<string>();
        private Timer accountsTimer;
        private bool accountsPolling;

        /// What the card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string AccountsShown(Dictionary<string, object> item)
        {
            if (item == null || (Str(item, "id") != AccountsId && Str(item, "id") != AccountId)) return "";
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

        /// The timer started while an Add an account waits for the browser, while Read usage reads, and while Read usage
        /// waits to be used again; stopped once none is so - never in a test's window, which reads the card itself.
        private void WatchAccounts()
        {
            bool waiting = AccountsWaiting() || AccountsReadWait() > 0;
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

        /// Whether the card waits on the bridge: an Add an account in the browser, Read usage reading, or a switch.
        private bool AccountsWaiting()
        {
            return Str(advancedAccounts, "add_state") == "waiting" || Str(advancedAccounts, "read_state") == "reading" ||
                   Str(advancedAccounts, "switch_state") == "switching";
        }

        /// Read again while the bridge works; while Read usage only waits to be used again, its button alone is said again.
        private void PollAccounts()
        {
            if (accountsPolling || (advancedOpen != AccountsId && advancedOpen != AccountId)) return;
            if (!AccountsWaiting())
            {
                UpdateAccountsButtons(busy == 0);
                if (AccountsReadWait() <= 0) WatchAccounts();
                return;
            }
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
            if (Equals(Get(row, "unread"), true)) parts.Add(Word("page.accounts.unread", "could not be read"));
            return string.Join(" · ", parts.ToArray());
        }

        /// A meter's words: "<N>% · in <time>" until its reset, "<N>%" without one, "not read yet" without a reading.
        private string AccountsMeterWords(Dictionary<string, object> window)
        {
            if (window == null) return Word("page.accounts.not_read", "not read yet");
            string percent = Word("page.accounts.percent", "{n}%", "n",
                                  Math.Round(Number(window, "used")).ToString(CultureInfo.CurrentCulture));
            double resets = Number(window, "resets_at");
            if (resets <= Now()) return percent;
            return Word("page.accounts.meter", "{percent} · in {time}", "percent", percent)
                .Replace("{time}", Mirror.Embed(AccountsSpan(resets - Now())));
        }

        /// How long until a moment, in the window's own units: days alone from a day, hours and minutes below, at least a
        /// minute.
        private string AccountsSpan(double seconds)
        {
            int total = Math.Max(60, (int)Math.Ceiling(seconds));
            if (total >= 86400) return S("time.days", "{n}d", "n", total / 86400);
            int minutes = (total % 3600) / 60;
            if (total < 3600) return S("time.minutes", "{n}m", "n", Math.Max(1, minutes));
            return S("time.hours", "{n}h", "n", total / 3600) + (minutes == 0 ? "" : " " + S("time.minutes", "{n}m", "n", minutes));
        }

        /// Seconds until Read usage may be used again, or 0 where it may now.
        private double AccountsReadWait()
        {
            double next = Number(advancedAccounts, "read_next_at");
            return next > Now() ? next - Now() : 0;
        }

        /// The muted line under the rows: when the readings were made and the next switch candidate - or null for neither.
        private string AccountsReadLine()
        {
            var parts = new List<string>();
            double at = Number(advancedAccounts, "read_at");
            if (at > 0) parts.Add(Word("page.accounts.read_at", "Read {time}", "time", Age(Now() - at)));
            string candidate = Str(advancedAccounts, "candidate");
            if (Str(advancedAccounts, "candidate_state") == "found" && !string.IsNullOrEmpty(candidate))
                parts.Add(Word("page.accounts.candidate", "Next switch candidate: {account}", "account", candidate));
            else if (Str(advancedAccounts, "candidate_state") == "none_has_room")
                parts.Add(Word("page.accounts.candidate_none", "Next switch candidate: none has room"));
            return parts.Count == 0 ? null : string.Join(" · ", parts.ToArray());
        }

        /// What Read usage's last run says, while it reads or where it stopped short - or null.
        private string AccountsReadState()
        {
            string state = Str(advancedAccounts, "read_state");
            if (state == "reading")
                return Word("page.accounts.reading", "Reading usage... {done} of {of}", "done",
                            Whole(Get(advancedAccounts, "read_done")).ToString(CultureInfo.CurrentCulture))
                    .Replace("{of}", Mirror.Embed(Whole(Get(advancedAccounts, "read_of")).ToString(CultureInfo.CurrentCulture)));
            if (state == "held")
                return Word("page.accounts.read_held", "Reading stopped: a switch began. Read usage again later.");
            if (state == "unknown")
                return Word("page.accounts.read_unknown",
                    "Nothing was read: which account is signed in now could not be told.");
            return null;
        }

        /// Whether any saved account is kept, by advanced-accounts' last answer.
        private bool AccountsKept()
        {
            List<object> kept = Items(advancedAccounts, "profiles");
            return kept != null && kept.Count > 0;
        }

        /// Whether the open column shows the card: either account capability's while it is on or watched, or off with
        /// accounts kept - one store of saved accounts under both (the owner, 2026-11-08).
        private bool AccountsHere(Dictionary<string, object> item)
        {
            if (advancedAccounts == null) return false;
            string id = Str(item, "id");
            return (id == AccountsId || id == AccountId) && (Standing(item) || AccountsKept());
        }

        /// Whether a saved account's row offers Switch to this account: not the account in use, a state that can be
        /// switched to (ready, or at its limit), and the automatic switch's own switch in this edition at all.
        private bool AccountsSwitchable(Dictionary<string, object> row)
        {
            if (Equals(Get(row, "in_use"), true) || !Equals(Get(advancedAccounts, "offered"), true)) return false;
            string state = Str(row, "state");
            return state == "ready" || state == "exhausted";
        }

        /// The open capability's card: the saved accounts and their buttons - Add, Save and Read usage only while the open
        /// capability is on or watched; Delete, Delete all and Switch to this account wherever the card shows.
        private void BuildAccounts(Dictionary<string, object> item)
        {
            ForgetAccountsCard();
            if (!AccountsHere(item)) return;
            bool standing = Standing(item);
            TableLayoutPanel card = NewGroup(Word("page.accounts.title", "Saved accounts"), advancedStack);
            if (standing)
            {
                accountsRead = MakeButton(Word("page.accounts.read", "Read usage"), false, delegate { ReadUsage(); });
                AccountsHeading(card, accountsRead);
            }
            if (Str(item, "id") == AccountsId)
                card.Controls.Add(HelpText(Word("page.accounts.help",
                    "Your own other Codex accounts. When a recovery waits for a usage limit, the one with the most room is switched in.")));
            else
                card.Controls.Add(HelpText(Word("page.accounts.help_switch",
                    "Your own Codex accounts - the same ones as on Switch to another saved account at a usage limit. Switch to this account moves Codex to one now.")));
            // Only while it stands: off or hidden, the bridge reads nothing of Codex's home and "store" is null.
            string why = standing ? AccountsStoreLine(Str(advancedAccounts, "store")) : null;
            if (why != null) card.Controls.Add(HelpText(why));
            foreach (object entry in Items(advancedAccounts, "profiles") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                string id = Str(row, "id");
                if (id == null) continue;
                CheckBox check = NewCheck(AccountsLine(row), accountsTicked.Contains(id), true);
                check.Tag = id;
                check.CheckedChanged += delegate { UpdateAccountsButtons(busy == 0); };
                Button switchTo = null;
                if (AccountsSwitchable(row))
                {
                    string mask = Str(row, "mask");
                    switchTo = MakeButton(Word("page.accounts.switch", "Switch to this account"), false,
                                          delegate { SwitchAccount(id, mask); });
                    switchTo.Tag = id;
                    accountsSwitches.Add(switchTo);
                }
                card.Controls.Add(AccountsRow(check, Equals(Get(row, "in_use"), true)));
                card.Controls.Add(AccountsMeters(row));
                if (switchTo != null) card.Controls.Add(AccountsSwitchLine(switchTo));
                accountsRows.Add(check);
            }
            if (accountsRows.Count == 0)
                card.Controls.Add(HelpText(Word("page.accounts.none", "No account saved yet.")));
            string readLine = AccountsReadLine();
            if (accountsRows.Count > 0 && readLine != null) card.Controls.Add(HelpText(readLine));
            string readState = AccountsReadState();
            if (standing && readState != null) card.Controls.Add(HelpText(readState));
            string switchState = AccountsSwitchState();
            if (switchState != null) card.Controls.Add(HelpText(switchState));
            string addState = Str(advancedAccounts, "add_state");
            if (addState == "waiting")
                card.Controls.Add(HelpText(Word("page.account.waiting", "Waiting for the sign-in in your browser...")));
            else if (addState == "added")
                card.Controls.Add(HelpText(Word("page.accounts.added", "The account was saved.")));
            else if (addState == "not_added")
                card.Controls.Add(HelpText(Word("page.accounts.not_added", "No account was saved: the sign-in did not finish.")));
            if (standing)
            {
                accountsAdd = CardButton(card, Word("page.accounts.add", "Add an account..."), delegate { AddAccount(); });
                accountsAdd.Margin = Pad(0, 8, 0, 4);
                accountsSave = CardButton(card, Word("page.accounts.save", "Save the account in use"), delegate { SaveAccount(); });
            }
            accountsDelete = CardButton(card, Word("page.accounts.delete", "Delete"), delegate { DeleteAccounts(false); });
            if (!standing) accountsDelete.Margin = Pad(0, 8, 0, 4);
            accountsDeleteAll = CardButton(card, Word("page.accounts.delete_all", "Delete all"), delegate { DeleteAccounts(true); });
        }

        private void ForgetAccountsCard()
        {
            // Called twice for a rebuild, the second time with no rows left to read.
            if (accountsRows.Count > 0) accountsTicked = AccountsPicked();
            accountsRows.Clear();
            accountsSwitches.Clear();
            accountsAdd = accountsSave = accountsDelete = accountsDeleteAll = accountsRead = null;
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
            // Adding signs in on a scratch home: Codex signed out here (no_file) stops nothing but Save and a switch.
            bool addable = usable || (listed && Str(advancedAccounts, "store") == "no_file");
            foreach (CheckBox row in accountsRows) row.Enabled = listed;
            if (accountsAdd != null) accountsAdd.Enabled = addable && Str(advancedAccounts, "add_state") != "waiting";
            if (accountsSave != null) accountsSave.Enabled = usable;
            if (accountsDelete != null) accountsDelete.Enabled = listed && AccountsPicked().Count > 0;
            if (accountsDeleteAll != null) accountsDeleteAll.Enabled = listed && accountsRows.Count > 0;
            bool switching = Str(advancedAccounts, "switch_state") == "switching";
            foreach (Button switchTo in accountsSwitches) switchTo.Enabled = usable && !switching;
            if (accountsRead != null)
            {
                double wait = AccountsReadWait();
                accountsRead.Text = wait > 0
                    ? Word("page.accounts.read_wait", "Read again in {time}", "time", AccountsSpan(wait))
                    : Word("page.accounts.read", "Read usage");
                accountsRead.Enabled = listed && wait <= 0 && accountsRows.Count > 0 &&
                                       Str(advancedAccounts, "read_state") != "reading";
            }
        }

        /// Read usage: every saved account's usage read now by the bridge, in the background; the card follows it.
        private void ReadUsage()
        {
            if (busy > 0 || advancedAccounts == null) return;
            AdvancedCall("advanced-accounts-read", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (!AdvancedDone(result)) TellAdvanced(AccountsRefusal(Str(result, "refusal")));
                ReadAccounts(null);
            });
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

        /// The line under the heading for a sign-in this card cannot use as it is - or null where it can (store "usable").
        private string AccountsStoreLine(string store)
        {
            if (store == "usable") return null;
            if (store == "no_file")
                return Word("page.accounts.no_file",
                    "Codex is signed out here, so the account in use cannot be saved and nothing is switched until you sign in to Codex. Add an account... still works.");
            if (store == "unreadable")
                return Word("page.accounts.unreadable",
                    "Codex's settings here cannot be read, so accounts cannot be saved or switched.");
            return Word("page.accounts.not_file", "Codex keeps its sign-in outside a file here, so accounts cannot be switched.");
        }

        /// Save the account in use, after one question: what it keeps, and how (Cancel the default).
        private void SaveAccount()
        {
            if (busy > 0 || advancedAccounts == null) return;
            if (!AskAdvanced(Word("page.confirm.accounts_save",
                    "Save the account Codex is signed in to now? A copy of its sign-in file is kept on this PC, encrypted for your Windows user."),
                Affirm(Word("page.accounts.save", "Save the account in use")))) return;
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

        /// Switch to this account, after one question: what closes, what may be lost, what is saved first and as whom Codex
        /// starts again (Cancel the default).
        private void SwitchAccount(string id, string mask)
        {
            if (busy > 0 || advancedAccounts == null || id == null) return;
            string account = string.IsNullOrEmpty(mask) ? Word("page.account.signed_in_only", "Signed in") : mask;
            if (!AskAdvanced(Word("page.confirm.accounts_switch",
                    "Switch Codex to {account}? The Codex app closes, and anything not yet sent in its window may be lost. The account in use is saved back to its copy first, then Codex starts again as {account}.",
                    "account", account),
                Affirm(Word("page.accounts.switch", "Switch to this account")))) return;
            AdvancedCall("advanced-accounts-switch", "{\"id\":" + Json.Escape(id) + "}", true,
                delegate(Dictionary<string, object> reply)
                {
                    Dictionary<string, object> result = AdvancedResult(reply);
                    if (!AdvancedDone(result)) TellAdvanced(AccountsRefusal(Str(result, "refusal")));
                    ReadAccounts(null);
                });
        }

        /// What the last Switch to this account says, while it runs or once it has ended - or null.
        private string AccountsSwitchState()
        {
            string state = Str(advancedAccounts, "switch_state");
            if (state == null) return null;
            string mask = Str(advancedAccounts, "switch_mask");
            string account = string.IsNullOrEmpty(mask) ? Word("page.account.signed_in_only", "Signed in") : mask;
            if (state == "switching")
                return Word("page.accounts.switching", "Switching to {account}... Codex closes and starts again.", "account", account);
            if (state == "switched")
                return Word("page.accounts.switched", "Switched: Codex started again as {account}.", "account", account);
            if (state == "not_started")
                return Word("page.accounts.switch_not_started",
                    "Switched to {account}, but Codex did not start again. Open Codex yourself.", "account", account);
            if (state == "not_put_back")
                return Word("page.accounts.switch_not_put_back",
                    "The switch to {account} did not finish. The account signed in before is put back as soon as Codex can be restarted.",
                    "account", account);
            if (state == "unverified")
                return Word("page.accounts.switch_unverified",
                    "Switched to {account}, but who is signed in could not be read yet. It is read again in a minute, and the switch is undone only if that account is not signed in.",
                    "account", account);
            if (state == "not_closed" || state == "held" || state == "locked" || state == "not_usable")
                return Word("page.accounts.switch_not_done",
                    "Nothing was switched: Codex could not be closed just now, or the saved accounts were in use. Try again in a moment.");
            return Word("page.accounts.switch_undone",
                "The switch to {account} did not finish and was undone: Codex keeps the account it had.", "account", account);
        }

        private string AccountsRefusal(string refusal)
        {
            if (refusal == "account_in_use")
                return Word("page.refused.account_in_use", "That account is the one in use.");
            if (refusal == "account_not_ready")
                return Word("page.refused.account_not_ready", "That account needs a new sign-in. Delete it and add it again.");
            if (refusal == "sign_in_not_file")
                return Word("page.accounts.not_file", "Codex keeps its sign-in outside a file here, so accounts cannot be switched.");
            if (refusal == "restart_busy")
                return Word("page.refused.accounts_switch_busy",
                    "Not now: a turn is running in Codex, something is queued there, or a recovery is being sent. Try again once it is done.");
            if (refusal == "other_engine")
                return Word("page.refused.other_engine",
                    "Another Codex is running, in a terminal or an editor, so the account cannot be switched now. Close it first.");
            if (refusal == "switch_running")
                return Word("page.refused.switch_running", "A sign-in is already waiting in your browser.");
            if (refusal == "accounts_held")
                return Word("page.refused.accounts_held",
                    "The saved accounts are in use by a switch or a usage read just now. Try again in a moment.");
            return ResetRefusal(refusal);
        }
    }
}

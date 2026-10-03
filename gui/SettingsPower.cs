// Codex Auto Resume - the power action after usage-limit recoveries (v0.6.12): the last card of Settings > General.
//
// Once every usage-limit recovery of a batch has ended and nothing else waits or runs in Codex, the watcher may put
// this PC to sleep, hibernate it or shut it down, after a notice with a countdown and a stop button. It is off by
// default and armed here only, once or always (H14); MCP, the icon and a notice can only turn it off.
//
// Arming is an act, not a setting. None of this card's controls is an editor: they are never in `editors`, so Save,
// EditorValues and the unsaved-changes baseline never see them, and a Save cannot arm again a Once that was spent.
// The card asks the bridge itself - `power-action` for what Windows offers here, `power-arm` after a confirmation
// whose default is Cancel, `power-disarm` with no question, as Pause asks none - and follows the status every read
// brings (`power_action`, only while its file exists).

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // ------------------------------------------------------------------ the power action's card
        /// The words the bridge takes and answers with (domain/power_vocabulary.py), in the order the card offers them.
        internal static readonly string[] PowerActions = { "sleep", "hibernate", "shut_down" };
        internal static readonly string[] PowerAfters = { "all_recovered", "handed_over_too", "any_end" };
        internal static readonly string[] PowerRepeats = { "once", "always" };
        /// How long the notice warns first, in minutes (poweraction.GRACE_MINUTES); five when nothing else was chosen.
        /// Written as words: a constant array of numbers makes the compiler emit a class it names at random, and the
        /// build would no longer be reproducible (build/normalize_pe.py).
        internal static readonly string[] PowerGraceMinutes = { "2", "5", "10", "15", "30" };
        private const string PowerDefaultGrace = "5";

        private TableLayoutPanel powerCard;
        private Label powerState, powerWait, powerUnavailable, powerLast;
        private SoftCombo powerAction, powerAfter, powerRepeat, powerGrace;
        private Button powerButton;
        /// The last `power-action` answer - the view, each action, the administrator's key, an older watcher - or null
        /// until one came. Until then nothing can be turned on: what Windows offers here is not known yet.
        private Dictionary<string, object> powerOptions;
        /// What is armed, shown and how the last batch ended (PowerView): from that answer, and from every status since.
        private Dictionary<string, object> powerView;
        private bool powerWatcherStopped, powerReading;
        /// Whether the card's one button may be pressed, busy aside: SetBusy greys it while any call is in flight.
        private bool powerCanPress;
        /// The actions the Then list holds, so a refresh that offers the same keeps what the person picked.
        private string powerOffered;

        /// Builds the card at the end of `stack` - Settings > General, right after Notifications - in the state it was
        /// last known in, and asks the bridge what Windows offers here only if the card is being shown (B16).
        private void BuildPower(TableLayoutPanel stack)
        {
            powerCard = NewGroup(S("power.title", "When usage-limit recoveries finish"), stack);
            powerState = HelpText("");
            powerState.ForeColor = Ink;
            powerState.Margin = Pad(0, 0, 0, 2);
            powerCard.Controls.Add(powerState);
            powerWait = HelpText("");
            powerCard.Controls.Add(powerWait);

            string then = S("power.field.action", "Then");
            powerAction = PowerCombo(then);
            powerCard.Controls.Add(NewRow(then, powerAction));
            string when = S("power.field.after", "When");
            powerAfter = PowerCombo(when);
            foreach (string after in PowerAfters) powerAfter.Items.Add(new Choice(after, PowerAfterName(after)));
            powerCard.Controls.Add(NewRow(when, powerAfter));
            string often = S("power.field.repeat", "How often");
            powerRepeat = PowerCombo(often);
            foreach (string repeat in PowerRepeats) powerRepeat.Items.Add(new Choice(repeat, PowerRepeatName(repeat)));
            powerCard.Controls.Add(NewRow(often, powerRepeat));
            string warn = S("power.field.grace", "Warn me first for");
            powerGrace = PowerCombo(warn);
            foreach (string minutes in PowerGraceMinutes) powerGrace.Items.Add(new Choice(minutes, PowerMinutes(minutes)));
            powerCard.Controls.Add(NewRow(warn, powerGrace));
            powerAfter.SelectedIndex = 0;
            powerRepeat.SelectedIndex = 0;
            powerGrace.SelectedIndex = Array.IndexOf(PowerGraceMinutes, PowerDefaultGrace);
            FitChoices(powerAfter);
            FitChoices(powerRepeat);
            FitChoices(powerGrace);
            powerOffered = null;

            powerUnavailable = HelpText("");
            powerCard.Controls.Add(powerUnavailable);
            powerButton = MakeButton(S("power.turn_on", "Turn on..."), false, delegate { PowerPressed(); });
            powerButton.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            powerButton.Margin = Pad(0, 6, 0, 6);
            powerCard.Controls.Add(powerButton);
            powerLast = HelpText("");
            powerCard.Controls.Add(powerLast);
            powerCard.Controls.Add(HelpText(S("power.help",
                "Only Codex in this Codex home is checked: other programs, downloads and unsaved work are not. It never sends anything to Codex and changes no Windows setting. It applies at once; Save does not change it.")));
            ShowPower();
            LoadPowerWhereShown();
        }

        /// Asks what Windows offers here - whether this account may shut down, which sleep states the PC has - each time
        /// the card is shown: Settings is the page and General the section. The editors, this card with them, are built
        /// at the first idle after the window opens whatever page it opened on, and that alone asks Windows nothing
        /// (B16). ShowPage and ShowSection ask here as they show it; Turn on and Turn off ask again.
        private void LoadPowerWhereShown()
        {
            if (currentPage != "settings" || currentSection != "general") return;
            LoadPower();
        }

        private SoftCombo PowerCombo(string name)
        {
            var combo = new SoftCombo();
            IgnoreWheel(combo);
            combo.AccessibleName = name;
            return combo;
        }

        /// What Windows offers here, and what is armed: on a worker, as every call is (CallAsync). Never while the
        /// window is being audited, which hands the card its states itself (AuditPower).
        private void LoadPower()
        {
            if (powerCard == null || auditing || powerReading) return;
            powerReading = true;
            CallAsync("power-action", null, delegate(Dictionary<string, object> reply)
            {
                powerReading = false;
                if (Ok(reply)) ApplyPowerOptions(Map(reply, "result"));
                else ShowPower();
            });
        }

        private void ApplyPowerOptions(Dictionary<string, object> options)
        {
            powerOptions = options;
            powerView = Map(options, "view");
            ShowPower();
        }

        /// From a status read (ApplyStatus): what is armed and shown now, and whether the watcher runs to act on it.
        /// `power_action` is there only while the file is, so a status without it says Off.
        private void ApplyPowerStatus(Dictionary<string, object> status)
        {
            if (powerCard == null || status == null) return;
            powerWatcherStopped = Equals(Get(status, "watcher_running"), false);
            powerView = Map(status, "power_action");
            ShowPower();
        }

        /// The card as the options and the view say: its two lines, the rows, why an action is not offered, the
        /// button and the last batch's outcome.
        private void ShowPower()
        {
            if (powerCard == null) return;
            bool managed = Equals(Get(powerOptions, "managed"), true);
            bool upgrade = Equals(Get(powerOptions, "upgrade_pending"), true);
            var armed = Map(powerView, "armed");
            var shown = Map(powerView, "shown");
            var last = Map(powerView, "last");
            string action = armed == null ? null : Known(Str(armed, "action"), PowerActions);

            // The first line: off, on, or counting down.
            double until = Number(shown, "grace_until");
            if (armed == null) powerState.Text = S("power.state.off", "Off");
            else if (Str(shown, "phase") == "grace" && until > 0) powerState.Text = PowerGraceLine(action, ClockTime(until));
            else powerState.Text = PowerOnLine(action);

            // The second line: what keeps it from acting, or why the card cannot be used.
            string wait = "";
            if (managed) wait = S("power.managed", "Your administrator has turned this off.");
            else if (upgrade) wait = S("power.upgrade", "Available once the watcher has upgraded its state.");
            else if (armed != null && powerWatcherStopped) wait = PowerWaitLine("watcher");
            else if (armed != null && Str(shown, "phase") == "waiting") wait = PowerWaitLine(Str(shown, "waiting_for"));
            ShowLine(powerWait, wait);

            // The Then list: the actions Windows will do for this account here. None, when it does not let this
            // account do any of them; all three, greyed with the button, until that is known.
            var offered = new List<string>();
            var reasons = new List<string>();
            bool privilege = false;
            List<object> actions = Items(powerOptions, "actions");
            if (actions == null) offered.AddRange(PowerActions);
            else
            {
                foreach (string name in PowerActions)
                {
                    Dictionary<string, object> choice = null;
                    foreach (object entry in actions)
                    {
                        var offer = entry as Dictionary<string, object>;
                        if (Str(offer, "value") == name) choice = offer;
                    }
                    if (choice != null && Equals(Get(choice, "available"), true)) { offered.Add(name); continue; }
                    string reason = Str(choice, "reason");
                    if (reason == "no_privilege") privilege = true;
                    else reasons.Add(PowerUnavailableLine(name, reason));
                }
            }
            if (privilege) offered.Clear();
            // Armed, the rows show what was armed - even an action Windows no longer offers.
            if (action != null && !offered.Contains(action)) offered.Add(action);
            OfferPowerActions(offered);
            ShowLine(powerUnavailable, privilege
                ? S("power.unavailable.privilege", "Nothing is offered: Windows does not let this account put this PC to sleep or shut it down.")
                : string.Join(Environment.NewLine, reasons.ToArray()));

            if (armed != null)
            {
                Pick(powerAction, action);
                Pick(powerAfter, Known(Str(armed, "after"), PowerAfters));
                Pick(powerRepeat, Known(Str(armed, "repeat"), PowerRepeats));
                string grace = ((int)(Number(armed, "grace_seconds") / 60)).ToString(CultureInfo.InvariantCulture);
                Pick(powerGrace, Known(grace, PowerGraceMinutes));
            }
            bool rows = armed == null && powerOptions != null && !managed && !upgrade && !privilege;
            powerAction.Enabled = rows && powerAction.Items.Count > 0;
            powerAfter.Enabled = powerRepeat.Enabled = powerGrace.Enabled = rows;

            powerButton.Text = armed != null ? S("power.turn_off", "Turn off") : S("power.turn_on", "Turn on...");
            powerCanPress = powerOptions != null && !managed && !upgrade
                         && (armed != null || (!privilege && powerAction.Items.Count > 0));
            powerButton.Enabled = busy == 0 && powerCanPress;
            ShowLine(powerLast, PowerLastLine(last));
            // The whole card greyed while an administrator holds it or an older watcher holds the state (E4).
            powerCard.Enabled = !managed && !upgrade;
        }

        private static void ShowLine(Label label, string text)
        {
            label.Text = text ?? "";
            label.Visible = label.Text.Length > 0;
        }

        /// Fills the Then list with `offered`, only when that changed, so a refresh keeps what the person picked.
        private void OfferPowerActions(List<string> offered)
        {
            string key = string.Join(",", offered.ToArray());
            if (key == powerOffered) return;
            string picked = Chosen(powerAction);
            powerOffered = key;
            powerAction.Items.Clear();
            foreach (string name in offered) powerAction.Items.Add(new Choice(name, PowerActionName(name)));
            FitChoices(powerAction);
            Pick(powerAction, picked);
            if (powerAction.SelectedIndex < 0 && powerAction.Items.Count > 0) powerAction.SelectedIndex = 0;
        }

        private static string Chosen(ComboBox combo)
        {
            var choice = combo.SelectedItem as Choice;
            return choice == null ? null : choice.Value;
        }

        /// The words a row shows for its choice: the card's own labels fill the confirmation, so it needs none of its own.
        private static string ChoiceWords(ComboBox combo)
        {
            return combo.SelectedItem == null ? "" : combo.SelectedItem.ToString();
        }

        private static void Pick(ComboBox combo, string value)
        {
            if (value == null) return;
            for (int index = 0; index < combo.Items.Count; index++)
            {
                var choice = combo.Items[index] as Choice;
                if (choice != null && choice.Value == value) { combo.SelectedIndex = index; return; }
            }
        }

        private static string Known(string word, string[] words)
        {
            return word != null && Array.IndexOf(words, word) >= 0 ? word : null;
        }

        /// Turn on... asks first, with Cancel the default, so a reflex Enter arms nothing; Turn off asks nothing - it
        /// only takes automation away, as Pause does.
        private void PowerPressed()
        {
            if (!powerCanPress || busy > 0) return;
            if (Map(powerView, "armed") != null)
            {
                CallAsync("power-disarm", "{}", delegate(Dictionary<string, object> reply)
                {
                    Report(reply);
                    LoadPower();
                });
                return;
            }
            string action = Chosen(powerAction), after = Chosen(powerAfter), repeat = Chosen(powerRepeat);
            string grace = Chosen(powerGrace);
            if (action == null || after == null || repeat == null || grace == null) return;
            string question = S("power.confirm",
                "Turn this on?\n\nThen: {action}\nWhen: {after}\nHow often: {repeat}\nWarn me first for: {grace}\n\nIt waits until no recovery waits or runs, no turn is running and no input is queued in Codex, and nobody has used this PC for 2 minutes. Then a notice gives you {grace} to stop it. Pausing recovery stops it too. You can turn it off here, from the notification-area icon, from the notice or from Codex.")
                .Replace("{action}", ChoiceWords(powerAction)).Replace("{after}", ChoiceWords(powerAfter))
                .Replace("{repeat}", ChoiceWords(powerRepeat)).Replace("{grace}", ChoiceWords(powerGrace));
            if (action == "shut_down")
                question += "\n\n" + S("power.confirm.shut_down",
                    "Shutting down closes every program, so save your work first. It never shuts down while someone else is signed in.");
            if (!Dialog(question, S("power.confirm.affirm", "Turn on"), S("action.cancel", "Cancel"))) return;
            string argument = "{\"action\":" + Json.Escape(action) + ",\"after\":" + Json.Escape(after)
                            + ",\"repeat\":" + Json.Escape(repeat) + ",\"grace_minutes\":" + grace + "}";
            CallAsync("power-arm", argument, delegate(Dictionary<string, object> reply)
            {
                Report(reply);
                LoadPower();
            });
        }

        // ------------------------------------------------------------------ its words, one key each
        private string PowerActionName(string action)
        {
            switch (action)
            {
                case "hibernate": return S("power.action.hibernate", "Hibernate");
                case "shut_down": return S("power.action.shut_down", "Shut down");
                default: return S("power.action.sleep", "Sleep");
            }
        }

        private string PowerAfterName(string after)
        {
            switch (after)
            {
                case "handed_over_too": return S("power.after.handed_over_too", "Each one succeeded or was handed over to you");
                case "any_end": return S("power.after.any_end", "Each one ended, however it ended");
                default: return S("power.after.all_recovered", "Every recovery succeeded");
            }
        }

        private string PowerRepeatName(string repeat)
        {
            return repeat == "always" ? S("power.repeat.always", "Every time")
                                      : S("power.repeat.once", "Once, for the next usage limit");
        }

        private string PowerMinutes(string minutes)
        {
            return S("time.minutes", "{n}m", "n", minutes);
        }

        private string PowerOnLine(string action)
        {
            switch (action)
            {
                case "hibernate": return S("power.state.on.hibernate", "On: this PC hibernates when they finish.");
                case "shut_down": return S("power.state.on.shut_down", "On: this PC shuts down when they finish.");
                default: return S("power.state.on.sleep", "On: this PC goes to sleep when they finish.");
            }
        }

        private string PowerGraceLine(string action, string time)
        {
            switch (action)
            {
                case "hibernate": return S("power.state.grace.hibernate", "Hibernating at {time} unless you turn it off.", "time", time);
                case "shut_down": return S("power.state.grace.shut_down", "Shutting down at {time} unless you turn it off.", "time", time);
                default: return S("power.state.grace.sleep", "Going to sleep at {time} unless you turn it off.", "time", time);
            }
        }

        /// Why an armed power action waits (PowerWait), one line each; a word this window does not know says nothing.
        private string PowerWaitLine(string word)
        {
            if (word == "no_batch") return S("power.wait.no_batch", "Waiting for a usage limit to be recovered.");
            if (word == "recovery_open") return S("power.wait.recovery_open", "Waiting: a recovery still waits or runs.");
            if (word == "delivery_unknown") return S("power.wait.delivery_unknown", "Waiting: a continuation may still arrive, for up to a day.");
            if (word == "turn_running") return S("power.wait.turn_running", "Waiting: a turn is still running in Codex.");
            if (word == "queued_input") return S("power.wait.queued_input", "Waiting: input is queued in Codex.");
            if (word == "codex_unknown") return S("power.wait.codex_unknown", "Waiting: Codex's state could not be read.");
            if (word == "history_behind") return S("power.wait.history_behind", "Waiting: Codex has not finished recording a conversation.");
            if (word == "other_people") return S("power.wait.other_people", "Waiting: someone else is signed in to this PC.");
            if (word == "person_active") return S("power.wait.person_active", "Waiting until nobody has used this PC for 2 minutes.");
            if (word == "idle_unknown") return S("power.wait.idle_unknown", "Waiting: Windows did not say whether this PC is in use.");
            if (word == "paused") return S("power.wait.paused", "Waiting: recovery is paused.");
            if (word == "watcher") return S("power.wait.watcher", "The watcher is not running, so nothing happens until it runs.");
            return "";
        }

        /// Why Windows will not do `action` here (PowerUnavailable). An account without the privilege is said once, for
        /// all three, by the caller.
        private string PowerUnavailableLine(string action, string reason)
        {
            if (reason == "hibernate_off" || (reason != "no_sleep_state" && action == "hibernate"))
                return S("power.unavailable.hibernate", "Hibernate is not offered: it is off in Windows, and this product does not turn it on.");
            if (reason == "no_sleep_state" || action == "sleep")
                return S("power.unavailable.sleep", "Sleep is not offered: Windows does not let a program start this PC's sleep.");
            return S("power.unavailable.privilege", "Nothing is offered: Windows does not let this account put this PC to sleep or shut it down.");
        }

        /// How the last batch ended (PowerEnd), and when; nothing before the first.
        private string PowerLastLine(Dictionary<string, object> last)
        {
            if (last == null) return "";
            string time = ClockTime(Number(last, "at"));
            string result = Str(last, "result");
            if (result == "done")
            {
                string action = Str(last, "action");
                if (action == "hibernate") return S("power.last.done.hibernate", "Last time: this PC hibernated at {time}.", "time", time);
                if (action == "shut_down") return S("power.last.done.shut_down", "Last time: this PC shut down at {time}.", "time", time);
                return S("power.last.done.sleep", "Last time: this PC went to sleep at {time}.", "time", time);
            }
            if (result == "failed") return S("power.last.failed", "Last time: Windows refused, at {time}. Nothing else changed.", "time", time);
            if (result == "skipped") return S("power.last.skipped", "Last time: you stopped it at {time}.", "time", time);
            if (result == "not_met") return S("power.last.not_met", "Last time: not done, because not every recovery ended as you chose ({time}).", "time", time);
            if (result == "stale") return S("power.last.stale", "Last time: not done, because the recoveries had ended while the watcher was not watching ({time}).", "time", time);
            if (result == "lapsed") return S("power.last.lapsed", "Last time: it turned itself off, because no usage limit came within a day ({time}).", "time", time);
            if (result == "unavailable") return S("power.last.unavailable", "Last time: not done, because Windows could not do it then ({time}).", "time", time);
            return "";
        }
    }
}

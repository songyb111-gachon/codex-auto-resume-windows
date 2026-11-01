// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the power action after tasks a person picked, on the Advanced features page (v0.6.20, Discussion #57).
//
// While power_after_tasks is on or watched, its column has a card under its limits. Unarmed: the person's own conversations
// whose turn runs now, each a flat check row (the window's lists stay flat hairline rows, never raised tiles); Also when a
// task failed and Also when a task was interrupted (completed always counts); Then - the actions Windows offers here, as
// the Settings card's last answer says (powerOptions), all three until it has answered - and Warn me first for, 2 to 30
// minutes, 5 by default; and Turn on..., which asks first with Cancel the default. Armed: each picked task and how it
// stands, what the watcher waits for or the time it counts down to (core's own view, powerView, as the Settings card shows
// it), and Turn off, which is core's power-disarm and asks nothing - it only does less, as everywhere else.
//
// Each request is the bridge's: advanced-power-tasks for the card, advanced-power-tasks-arm with the generation the page
// was read at, and core's power-disarm; the card is read again after each. Its words are this edition's catalog's, and the
// action, warning and wait lines are the Settings card's own (SettingsPower.cs).
//
// Nothing here draws anything the page does not draw already: the card, its captions, help lines, check rows, drop-downs
// and buttons are the Settings page's, in both themes and both designs, mirrored for Arabic and Hebrew by the page.
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
        private const string PowerTasksId = "power_after_tasks";

        // advanced-power-tasks' last answer, or null where it was not read or the read failed.
        private Dictionary<string, object> advancedPowerTasks;
        // The card's form as it was built: each running conversation's row, the two endings, Then, Warn me first for, and
        // its buttons.
        private readonly List<CheckBox> powerTaskRows = new List<CheckBox>();
        private CheckBox powerTaskFailed, powerTaskInterrupted;
        private SoftCombo powerTaskAction, powerTaskGrace;
        private Button powerTaskArm, powerTaskOff;

        /// What the card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string PowerTasksShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != PowerTasksId) return "";
            return AdvancedWritten(advancedPowerTasks) + "|" + AdvancedWritten(Map(powerView, "shown")) + "|" +
                   AdvancedWritten(Items(powerOptions, "actions"));
        }

        /// Read advanced-power-tasks, keep it, and show it; `done` once it is shown.
        private void ReadPowerTasks(MethodInvoker done)
        {
            AdvancedCall("advanced-power-tasks", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedPowerTasks = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        /// A running conversation's name, as the read named it, else as Pending and History name it.
        private string PowerTaskName(string thread)
        {
            foreach (object entry in Items(advancedPowerTasks, "running") ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                if (row != null && Str(row, "thread_id") == thread && !string.IsNullOrEmpty(Str(row, "name")))
                    return Str(row, "name");
            }
            return ConversationOf(thread);
        }

        private string PowerTaskEnd(string end)
        {
            if (end == "running") return Word("page.powertasks.end.running", "running");
            if (end == "completed") return Word("page.powertasks.end.completed", "completed");
            if (end == "failed") return Word("page.powertasks.end.failed", "failed");
            if (end == "interrupted") return Word("page.powertasks.end.interrupted", "interrupted");
            return Word("page.powertasks.end.unknown", "cannot be read");
        }

        /// The open capability's card, while power_after_tasks is on or watched: what it waits for, or the form.
        private void BuildPowerTasks(Dictionary<string, object> item)
        {
            ForgetPowerTasksCard();
            if (Str(item, "id") != PowerTasksId || !Standing(item) || advancedPowerTasks == null) return;
            TableLayoutPanel card = NewGroup(Word("page.powertasks.title", "Tasks to wait for"), advancedStack);
            var armed = Map(advancedPowerTasks, "armed");
            if (armed != null)
            {
                foreach (object entry in Items(armed, "tasks") ?? new List<object>())
                {
                    var task = entry as Dictionary<string, object>;
                    if (task == null) continue;
                    Label line = HelpText(Word("page.powertasks.line", "{conversation} · {end}", "conversation",
                                               PowerTaskName(Str(task, "thread_id")))
                                          .Replace("{end}", PowerTaskEnd(Str(task, "end"))));
                    line.ForeColor = Ink;
                    line.Margin = Pad(0, 4, 0, 2);
                    card.Controls.Add(line);
                }
                var shown = Map(powerView, "shown");
                string action = Known(Str(armed, "action"), PowerActions);
                double until = Number(shown, "grace_until");
                string state = Str(shown, "phase") == "grace" && until > 0 ? PowerGraceLine(action, ClockTime(until))
                             : Str(shown, "phase") == "waiting" ? PowerWaitLine(Str(shown, "waiting_for"))
                             : PowerTasksLine(action);
                if (!string.IsNullOrEmpty(state)) card.Controls.Add(HelpText(state));
                powerTaskOff = CardButton(card, Word("page.powertasks.off", "Turn off"), delegate { PowerTasksOff(); });
                powerTaskOff.Margin = Pad(0, 8, 0, 4);
                return;
            }
            card.Controls.Add(HelpText(Word("page.powertasks.help",
                "Pick the conversations whose turn is running now. Once every one has finished as you chose, and nothing else runs or waits in Codex, this PC does what you picked, after a notice you can stop.")));
            List<object> running = Items(advancedPowerTasks, "running") ?? new List<object>();
            foreach (object entry in running)
            {
                var row = entry as Dictionary<string, object>;
                string thread = Str(row, "thread_id");
                if (thread == null) continue;
                CheckBox check = NewCheck(PowerTaskName(thread), false, true);
                check.Tag = thread;
                check.CheckedChanged += delegate { UpdatePowerTasksButtons(busy == 0); };
                card.Controls.Add(check);
                powerTaskRows.Add(check);
            }
            if (powerTaskRows.Count == 0)
                card.Controls.Add(HelpText(Word("page.powertasks.none", "No conversation of yours has a turn running now.")));
            powerTaskFailed = NewCheck(Word("page.powertasks.failed", "Also when a task failed"), false, false);
            powerTaskInterrupted = NewCheck(Word("page.powertasks.interrupted", "Also when a task was interrupted"), false, false);
            card.Controls.Add(powerTaskFailed);
            card.Controls.Add(powerTaskInterrupted);
            string then = S("power.field.action", "Then");
            powerTaskAction = NewResetCombo(then, 200, "powertasks.action");
            foreach (string name in PowerTasksOffered()) powerTaskAction.Items.Add(new Choice(name, PowerActionName(name)));
            PickDraft(powerTaskAction, "powertasks.action");
            if (powerTaskAction.SelectedItem == null && powerTaskAction.Items.Count > 0) powerTaskAction.SelectedIndex = 0;
            card.Controls.Add(NewRow(then, powerTaskAction));
            string warn = S("power.field.grace", "Warn me first for");
            powerTaskGrace = NewResetCombo(warn, 120, "powertasks.grace");
            foreach (string minutes in PowerGraceMinutes) powerTaskGrace.Items.Add(new Choice(minutes, PowerMinutes(minutes)));
            PickDraft(powerTaskGrace, "powertasks.grace");
            if (powerTaskGrace.SelectedItem == null) Pick(powerTaskGrace, PowerDefaultGrace);
            card.Controls.Add(NewRow(warn, powerTaskGrace));
            powerTaskArm = CardButton(card, Word("page.powertasks.button", "Turn on..."), delegate { ArmPowerTasks(); });
            powerTaskArm.Margin = Pad(0, 8, 0, 4);
        }

        /// The actions Windows offers here, as the Settings card's last power-action answer says; all three before it came.
        private List<string> PowerTasksOffered()
        {
            var offered = new List<string>();
            List<object> actions = Items(powerOptions, "actions");
            foreach (string name in PowerActions)
            {
                if (actions == null) { offered.Add(name); continue; }
                foreach (object entry in actions)
                {
                    var offer = entry as Dictionary<string, object>;
                    if (Str(offer, "value") == name && Equals(Get(offer, "available"), true)) offered.Add(name);
                }
            }
            return offered;
        }

        private void ForgetPowerTasksCard()
        {
            powerTaskRows.Clear();
            powerTaskFailed = powerTaskInterrupted = null;
            powerTaskAction = powerTaskGrace = null;
            powerTaskArm = powerTaskOff = null;
        }

        private List<string> PowerTasksPicked()
        {
            var picked = new List<string>();
            foreach (CheckBox row in powerTaskRows)
                if (row.Checked && row.Tag is string) picked.Add((string)row.Tag);
            return picked;
        }

        private void UpdatePowerTasksButtons(bool idle)
        {
            bool listed = idle && advancedListing != null && advancedPowerTasks != null;
            foreach (CheckBox row in powerTaskRows) row.Enabled = listed;
            if (powerTaskArm != null)
                powerTaskArm.Enabled = listed && PowerTasksPicked().Count > 0 && powerTaskAction != null &&
                                       powerTaskAction.SelectedItem != null && powerTaskGrace != null &&
                                       powerTaskGrace.SelectedItem != null;
            if (powerTaskOff != null) powerTaskOff.Enabled = listed;
        }

        private void ArmPowerTasks()
        {
            if (busy > 0 || advancedListing == null || powerTaskAction == null || powerTaskGrace == null) return;
            List<string> picked = PowerTasksPicked();
            var action = powerTaskAction.SelectedItem as Choice;
            var grace = powerTaskGrace.SelectedItem as Choice;
            if (picked.Count == 0 || action == null || grace == null) return;
            string question = Word("page.confirm.power_after_tasks",
                "Turn this on for {n} tasks?\n\nThen: {action}\nWarn me first for: {grace}\n\nIt waits until every task you picked has finished as you chose, no recovery waits or runs, no turn is running and no input is queued in Codex, and nobody has used this PC for 2 minutes. Then a notice gives you {grace} to stop it. It happens once. You can turn it off here, in Settings, from the notification-area icon or from the notice.",
                "n", Mirror.Embed(picked.Count.ToString(CultureInfo.CurrentCulture)))
                .Replace("{action}", Mirror.Embed(action.ToString())).Replace("{grace}", Mirror.Embed(grace.ToString()));
            if (action.Value == "shut_down")
                question += "\n\n" + S("power.confirm.shut_down",
                    "Shutting down closes every program, so save your work first. It never shuts down while someone else is signed in.");
            if (!AskAdvanced(question, Affirm(Word("page.powertasks.button", "Turn on...")))) return;
            var threads = new List<string>();
            foreach (string thread in picked) threads.Add(Json.Escape(thread));
            string argument = "{\"threads\":[" + string.Join(",", threads.ToArray()) + "],\"action\":" + Json.Escape(action.Value) +
                              ",\"grace_minutes\":" + grace.Value + ",\"failed\":" + (powerTaskFailed.Checked ? "true" : "false") +
                              ",\"interrupted\":" + (powerTaskInterrupted.Checked ? "true" : "false") +
                              ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-power-tasks-arm", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) ResetNote(Word("page.done.power_after_tasks", "It is on. A notice comes before anything happens."));
                ReadPowerTasks(null);
                if (!AdvancedDone(result)) TellAdvanced(PowerTasksRefusal(Str(result, "refusal")));
            });
        }

        /// Turn off: core's power-disarm, as the Settings card's switch asks it - no question, it only does less.
        private void PowerTasksOff()
        {
            if (busy > 0) return;
            CallAsync("power-disarm", "{}", delegate(Dictionary<string, object> reply)
            {
                if (Ok(reply)) ResetNote(Word("page.done.reset_cancelled", "Cancelled."));
                else Report(reply);
                ReadPowerTasks(null);
            });
        }

        private string PowerTasksRefusal(string refusal)
        {
            if (refusal == "no_turn_running")
                return Word("page.refused.power_no_turn", "A conversation you picked has no turn running any more. Nothing was turned on.");
            if (refusal == "power_refused")
                return Word("page.refused.power_refused", "The power action could not be turned on: Windows does not offer it here, your administrator turned it off, or the watcher has not upgraded its state.");
            return ResetRefusal(refusal);
        }
    }
}

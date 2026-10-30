// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the turns run here, on the Advanced features page (v0.6.16-beta.4).
//
// While Run a conversation here while Codex is closed, Compact a full conversation or the model fallback is on or
// watched, its column has a card under its limits: each turn that capability runs here now, a flat line saying for
// which conversation and until when at most, with Stop... under it. Pressing one asks first, and hands the watcher that
// run's Stop (advanced-headless-stop) - the Dashboard's alone, never an MCP tool's; the turn is interrupted at the
// watcher's next look. A Stop already asked reads "Stopping..." until the run ends. The runs are the ones the status the
// window already reads carries (surfaces.runs), never a word of a conversation.
//
// Nothing here draws anything the page does not draw already: the card, the help lines and the buttons are Send now's.
//
// And what Pending and History say of a row this edition had a hand in (CellsWritten): words joined to a cell's own
// line - " · CLI" or " · VS Code" after the conversation of a terminal's or VS Code's (other_sessions), and "Run
// /compact in Codex; it continues after" after the status of a full conversation waiting for it (compact_continue), and
// that a conversation now uses another model after the status of one whose own model Codex would not put back
// (model_fallback), and "continued with no words, proven by its id" after History's outcome of one a turn run here
// started with no words (silent_continuation) - from what the
// status the window already reads carries of each row, by its interruption id (surfaces.rows). No cell, column or
// element of its own: as a second Codex home's alias joins the label line (v0.6.15-beta).
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // The capabilities that run a turn here (registry: HEADLESS_RUN, COMPACT_CONTINUE, MODEL_FALLBACK).
        private static readonly string[] RunningIds = { "headless_run", "compact_continue", "model_fallback" };

        // The runs the last snapshot's status held (surfaces.runs), or null before one or where there are none.
        private List<object> advancedRuns;
        private readonly List<Button> runStops = new List<Button>();

        /// From each snapshot: the turns run here now (SnapshotApplied).
        private void RunsApplied(Dictionary<string, object> reply)
        {
            advancedRuns = Items(Map(Map(reply, "status"), "advanced"), "runs");
        }

        /// The runs of capability `id` the last snapshot held, in its order.
        private List<Dictionary<string, object>> RunRows(string id)
        {
            var rows = new List<Dictionary<string, object>>();
            foreach (object entry in advancedRuns ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                if (row != null && Str(row, "capability") == id && Str(row, "interruption_id") != null) rows.Add(row);
            }
            return rows;
        }

        /// What the open capability's runs card is built from, for ShowAdvancedDetail to compare.
        private string RunsShown(Dictionary<string, object> item)
        {
            string id = item == null ? null : Str(item, "id");
            return Array.IndexOf(RunningIds, id) < 0 ? "" : AdvancedWritten(RunRows(id));
        }

        /// The conversation of a run, as Pending names it - from the pending list the window already holds.
        private string RunConversation(string key)
        {
            foreach (object entry in advancedPending ?? new List<object>())
            {
                var row = entry as Dictionary<string, object>;
                if (row != null && Str(row, "interruption_id") == key) return Conversation(row);
            }
            return Word("page.runs.conversation", "A conversation");
        }

        /// The runs card, while the open capability that runs turns here is on or watched.
        private void BuildRuns(Dictionary<string, object> item)
        {
            runStops.Clear();
            string id = Str(item, "id");
            if (Array.IndexOf(RunningIds, id) < 0 || (Str(item, "stored") ?? StateOff) == StateOff) return;
            TableLayoutPanel card = NewGroup(Word("page.runs.title", "Turns run here now"), advancedStack);
            List<Dictionary<string, object>> rows = RunRows(id);
            if (rows.Count == 0) card.Controls.Add(HelpText(Word("page.runs.none", "No turn is running here.")));
            foreach (Dictionary<string, object> row in rows)
            {
                string key = Str(row, "interruption_id");
                string conversation = RunConversation(key);
                Label line = HelpText(conversation + " · " + Word("page.runs.until", "until {time} at most", "time",
                                                                   ClockTime(Number(row, "ends_by"))));
                line.ForeColor = Ink;
                line.Margin = Pad(0, 6, 0, 2);
                card.Controls.Add(line);
                if (Equals(Get(row, "stopping"), true))
                {
                    card.Controls.Add(HelpText(Word("page.runs.stopping", "Stopping...")));
                    continue;
                }
                Button stop = CardButton(card, Word("page.runs.stop", "Stop..."), delegate { StopRunAdvanced(key); });
                stop.Tag = key;
                stop.AccessibleName = Word("page.runs.stop", "Stop...") + " " + conversation;
                runStops.Add(stop);
            }
        }

        /// What this edition says of one row of Pending (`pending`) or History, joined to its cells' lines: the kind of
        /// conversation after its label, from the status of the snapshot being shown (surfaces.rows).
        partial void CellsWritten(Dictionary<string, object> row, bool pending, string[] cells)
        {
            // v0.6.19: a row of this edition's own on Pending or History (AdvancedSchedule.cs) is written as it was made.
            if (WriteJoinedCells(row, cells)) return;
            string key = Str(row, "interruption_id");
            // v0.6.20: a sample's own, while See an example's view is built (AdvancedExamples.cs).
            Dictionary<string, object> said = exampleSaid ?? Map(Map(snapshot, "status"), "advanced");
            if (key == null || said == null) return;
            string kind = Str(Map(said, "kinds"), key);
            if (kind == "cli") cells[0] += " · " + Word("page.row.kind.cli", "CLI");
            else if (kind == "ide") cells[0] += " · " + Word("page.row.kind.ide", "VS Code");
            // A full conversation waiting for the person's /compact in the Codex app says so in its status (compact_continue).
            if (pending && Listed(said, "compacting", key))
                cells[1] += " · " + Word("page.row.compact", "Run /compact in Codex; it continues after");
            // A model a fallback turn ran on that Codex would not put back, in Pending and History alike (model_fallback).
            if (Listed(said, "model_not_restored", key))
                cells[1] += " · " + Word("page.row.model_not_restored", "This conversation now uses another model; switch it back in Codex");
            // A continuation a turn run here started with no words, in History (silent_continuation).
            if (!pending && Listed(said, "silent", key))
                cells[1] += " · " + Word("page.row.silent", "continued with no words, proven by its id");
        }

        /// Whether the list `name` of what the status says of the rows names `key`.
        private static bool Listed(Dictionary<string, object> said, string name, string key)
        {
            foreach (object entry in Items(said, name) ?? new List<object>())
                if (entry as string == key) return true;
            return false;
        }

        /// What the runs' Stop... buttons may do now: nothing while another action is under way, as every other button of
        /// the page (v0.6.19-beta.3, the controls audit: before, they stayed live and a click was silently ignored).
        private void UpdateRunButtons(bool idle)
        {
            foreach (Button stop in runStops) stop.Enabled = idle;
        }

        /// Ask, then hand the watcher one run's Stop: the turn is interrupted at its next look.
        private void StopRunAdvanced(string key)
        {
            if (busy > 0 || key == null) return;
            if (!AskAdvanced(Word("page.confirm.run_stop", "Stop this turn? Codex interrupts it at the watcher's next look, as Stop in Codex would, and the recovery ends as that turn ends."),
                             Affirm(Word("page.runs.stop", "Stop..."))))
                return;
            AdvancedCall("advanced-headless-stop", "{\"interruption_id\":" + Json.Escape(key) + "}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                    SetNote(advancedNote, Word("page.done.run_stop", "Asked. The watcher stops the turn at its next look."));
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepOnRefusal(result));
            });
        }
    }
}

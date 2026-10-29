// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - See an example (v0.6.20; the owner's decision of 2026-10-29: the before and after of every capability
// in the app itself, drawn by the app - not pictures in the documentation).
//
// The open capability's About this feature card ends with See an example... (one place, the card button every card of the
// page has). It opens the window's own dialog - the canvas, the soft title bar, Close - with two panes, Without it and With
// it, side by side where each has room and one above the other where it does not, and the dialog held to the working area
// of the screen it opens on, as Find a conversation is (AdvancedFind.cs). Each pane is drawn by the window itself from a
// sample snapshot, through the code the pages draw with: a list on History's card (DialogListCard) shaped as History or
// Pending, every cell written by Cells - core's words for a state and a kind, When, Attempts, this edition's CellsWritten
// notes, RuleRow and PromptRow for its own rows - and Next check by CountdownText; what is sent, as the wrap-up card shows
// it ("What is sent, exactly"); and a line made by the window's own functions (UsageLine, Keep going's line). Where nothing
// on screen differs, a pane says the statement's own field, as the page shows it.
//
// The samples are this file's table (Examples): for each capability a Before and an After, of made-up conversations named as
// the tests' fixtures are (example-project, example-service, example-app, example-docs), thread ids of the fixtures' shape,
// times counted in minutes from the moment the example opens. Nothing is read from the machine, nothing is asked of the
// bridge and nothing is sent; no picture is shipped. Two hooks, each read only while an example is being built, let the
// same code take the sample for the live state: exampleSaid (CellsWritten, AdvancedRuns.cs) and exampleNames
// (ConversationOf, AdvancedResets.cs).
//
// advanced/tests/test_advanced_examples.py holds the table to the registry (every capability has one), and
// test_advanced_page_examples*.py drive the view and audit its layout through the hooks at the end of this file.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // ---------------------------------------------------------------- the samples
        // The made-up conversations, named as the tests' fixtures are; each one's thread id of the fixtures' shape.
        private const string ExampleProject = "example-project", ExampleService = "example-service",
                             ExampleApp = "example-app", ExampleDocs = "example-docs";
        // The marker a continuation of the standard edition ends with, of a made-up interruption (ids.short_marker).
        private const string ExampleMarker = "[codex-auto-resume:0a1b2c3d4e5f6a7b]";
        // The least width a pane takes beside the other, in logical pixels; narrower, they stand one above the other.
        private const int ExamplePaneLeast = 320;
        // The widest the dialog is drawn, in logical pixels.
        private const int ExampleWidest = 960;

        /// One part of a scene: rows on a list shaped as History ("history") or Pending ("pending"), what is sent ("sent"),
        /// or a line ("line").
        private sealed class ExamplePart
        {
            internal string Kind;
            internal List<Dictionary<string, object>> Rows;
            internal Func<SettingsForm, string> Text;
        }

        private sealed class ExampleScene
        {
            internal readonly List<ExamplePart> Parts = new List<ExamplePart>();
        }

        /// A capability's example: what the standard edition shows without it, and what it shows with it on.
        private sealed class Example
        {
            internal string Id;
            internal ExampleScene Before, After;
        }

        private static Example Ex(string id, ExampleScene before, ExampleScene after)
        {
            var made = new Example();
            made.Id = id;
            made.Before = before;
            made.After = after;
            return made;
        }

        private static ExampleScene Scene(params ExamplePart[] parts)
        {
            var scene = new ExampleScene();
            scene.Parts.AddRange(parts);
            return scene;
        }

        private static ExamplePart Rows(string kind, Dictionary<string, object>[] rows)
        {
            var part = new ExamplePart();
            part.Kind = kind;
            part.Rows = new List<Dictionary<string, object>>(rows);
            return part;
        }

        private static ExamplePart OnHistory(params Dictionary<string, object>[] rows) { return Rows("history", rows); }

        private static ExamplePart OnPending(params Dictionary<string, object>[] rows) { return Rows("pending", rows); }

        private static ExamplePart Sent(Func<SettingsForm, string> words)
        {
            var part = new ExamplePart();
            part.Kind = "sent";
            part.Text = words;
            return part;
        }

        private static ExamplePart Says(Func<SettingsForm, string> text)
        {
            var part = new ExamplePart();
            part.Kind = "line";
            part.Text = text;
            return part;
        }

        /// A made-up conversation's thread id, of the fixtures' shape; "" for none.
        private static string ExampleThread(string name)
        {
            if (name == null) return "";
            string digit = name == ExampleProject ? "1" : name == ExampleService ? "2" : name == ExampleApp ? "3" : "4";
            return "0a1b2c3d-00e" + digit + "-7000-8000-0000000000e" + digit;
        }

        /// A recovery as the dashboard reply has it: its conversation (null: none named), its state's code and its kind, and
        /// when it was detected and finished, in minutes from the moment the example opens (0: not finished).
        private static Dictionary<string, object> Rec(string name, string code, string category, int detected, int finished)
        {
            var row = new Dictionary<string, object>();
            row["interruption_id"] = "example-" + (name ?? "none") + "-" + code + "-" + detected.ToString(CultureInfo.InvariantCulture);
            row["thread_id"] = ExampleThread(name);
            if (name != null) row["name"] = name;
            row["code"] = code;
            row["category"] = category;
            row["example_detected"] = (double)detected;
            if (finished != 0) row["example_finished"] = (double)finished;
            return row;
        }

        private static Dictionary<string, object> Over(Dictionary<string, object> row, string overlay)
        {
            row["overlays"] = new List<object> { overlay };
            return row;
        }

        /// When its next check is, in minutes from the moment the example opens.
        private static Dictionary<string, object> Due(Dictionary<string, object> row, int minutes)
        {
            row["example_due"] = (double)minutes;
            return row;
        }

        private static Dictionary<string, object> Tries(Dictionary<string, object> row, int used, int limit)
        {
            row["recovery_attempts"] = (double)used;
            row["attempt_limit"] = (double)limit;
            return row;
        }

        /// What this edition says of the row (CellsWritten): "cli", "ide", "compacting", "silent" or "model_not_restored".
        private static Dictionary<string, object> Mark(Dictionary<string, object> row, string said)
        {
            row["example_said"] = said;
            return row;
        }

        /// A message to `name` when the 5-hour limit next resets, as advanced-resets lists the rule.
        private static Dictionary<string, object> ResetRule(string name)
        {
            var rule = new Dictionary<string, object>();
            rule["example_kind"] = "rule";
            rule["rule_id"] = 1.0;
            rule["capability"] = "reset_message";
            rule["thread_id"] = ExampleThread(name);
            rule["minutes"] = 300.0;
            rule["ordinal"] = 1.0;
            rule["state"] = "waiting";
            return rule;
        }

        /// A message queued for `name`, after this turn ("after_turn") or at a time ("at_time", in minutes from the moment
        /// the example opens), as advanced-prompts lists it.
        private static Dictionary<string, object> Queued(string name, string trigger, int due, int id)
        {
            var prompt = new Dictionary<string, object>();
            prompt["example_kind"] = "prompt";
            prompt["prompt_id"] = (double)id;
            prompt["thread_id"] = ExampleThread(name);
            prompt["trigger"] = trigger;
            prompt["while_running"] = trigger == "after_turn" ? "queue" : "wait";
            prompt["state"] = "waiting";
            if (due != 0) prompt["example_due"] = (double)due;
            return prompt;
        }

        // Minutes from the moment the example opens: the limit detected, the reset it waited for, the next check.
        private const int Detected = -410, Reset = -170, Ahead = 210;

        /// Every capability's example, in no order: registry.DEFINITIONS and the ones registry.WAITING holds back each have
        /// one (advanced/tests/test_advanced_examples.py).
        private static Example[] Examples()
        {
            return new[]
            {
                Ex("compat_report",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1),
                                   Rec(ExampleService, "recovered", "server_5xx", -130, -128))),
                   Scene(OnHistory(Rec(null, "recovered", "usage_limit", Detected, Reset + 1),
                                   Rec(null, "recovered", "server_5xx", -130, -128)))),
                Ex("start_with_codex",
                   Scene(OnPending(Due(Over(Rec(ExampleProject, "waiting_reset", "usage_limit", Detected, 0), "engine_unavailable"), Ahead))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1)))),
                Ex("crash_restart",
                   Scene(OnPending(Tries(Due(Over(Rec(ExampleService, "scheduled", "server_5xx", -40, 0), "engine_unavailable"), 15), 1, 4))),
                   Scene(OnHistory(Rec(ExampleService, "recovered", "server_5xx", -40, -14)))),
                Ex("wake_for_reset",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, -15))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset)))),
                Ex("every_conversation",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1),
                                   Rec(ExampleDocs, "recovered", "usage_limit", -390, Reset + 1)))),
                Ex("queue_for_open",
                   Scene(OnPending(Rec(ExampleProject, "waiting_thread", "usage_limit", Detected, 0))),
                   Scene(OnPending(Rec(ExampleProject, "submitted", "usage_limit", Detected, 0)))),
                Ex("open_to_send",
                   Scene(OnPending(Rec(ExampleProject, "waiting_thread", "usage_limit", Detected, 0))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 6)))),
                Ex("headless_run",
                   Scene(OnPending(Rec(ExampleProject, "waiting_thread", "usage_limit", Detected, 0))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1)))),
                Ex("other_sessions",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1),
                                   Mark(Rec(ExampleService, "recovered", "server_5xx", -130, -128), "cli"),
                                   Mark(Rec(ExampleApp, "recovered", "stream_interrupted", -95, -94), "ide")))),
                Ex("marker_free_continuation",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1)),
                         Sent(f => f.ExampleContinuation(true))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1)),
                         Sent(f => f.ExampleContinuation(false)))),
                Ex("silent_continuation",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1)),
                         Sent(f => f.ExampleContinuation(true))),
                   Scene(OnHistory(Mark(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1), "silent")))),
                Ex("reset_credit",
                   Scene(OnPending(Due(Rec(ExampleProject, "waiting_reset", "usage_limit", -30, 0), Ahead))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", -30, -26)))),
                Ex("early_reset",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, -290)))),
                Ex("parallel_dispatch",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1),
                                   Rec(ExampleService, "recovered", "usage_limit", -400, Reset + 1),
                                   Rec(ExampleApp, "recovered", "usage_limit", -395, Reset + 2))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 1),
                                   Rec(ExampleService, "recovered", "usage_limit", -400, Reset + 1),
                                   Rec(ExampleApp, "recovered", "usage_limit", -395, Reset + 1)))),
                Ex("reset_message",
                   Scene(OnPending(Due(Rec(ExampleProject, "waiting_reset", "usage_limit", -30, 0), Ahead))),
                   Scene(OnPending(Due(Rec(ExampleProject, "waiting_reset", "usage_limit", -30, 0), Ahead),
                                   ResetRule(ExampleProject)))),
                Ex("long_reset_message",
                   Scene(Says(f => f.ExampleCount(5200, 2000)),
                         Says(f => f.S("custom.refusal.too_long", "It is longer than {max} characters.", "max", f.ExampleNumber(2000)))),
                   Scene(OnPending(ResetRule(ExampleProject)),
                         Says(f => f.ExampleCount(5200, 8154)))),
                Ex("usage_meter",
                   Scene(Says(f => f.ExampleUsage(260, 62, 0, -1))),
                   Scene(Says(f => f.ExampleUsage(0, 88, 95, 41)))),
                Ex("usage_wrap_up",
                   Scene(OnPending(Due(Rec(ExampleProject, "waiting_reset", "usage_limit", -5, 0), Ahead))),
                   Scene(Says(f => f.ExampleUsage(0, 90, Ahead + 5, -1)),
                         Sent(f => f.Word("continue.wrap_up.standard", "Please finish the current step, then stop.")),
                         OnPending(Due(Rec(ExampleProject, "waiting_reset", "usage_limit", -5, 0), Ahead)))),
                Ex("usage_pause",
                   Scene(Says(f => f.ExampleUsage(0, 100, Ahead, -1)),
                         OnPending(Due(Rec(ExampleProject, "waiting_reset", "usage_limit", -5, 0), Ahead))),
                   Scene(Says(f => f.ExampleUsage(0, 97, Ahead, -1)),
                         OnPending(Due(Rec(ExampleProject, "waiting_reset", "usage_limit", -5, 0), Ahead)))),
                Ex("keep_going",
                   Scene(Says(f => f.ExampleField("keep_going", "instead"))),
                   Scene(Sent(f => f.Word("continue.keep_going", "Carry on with the next step of the plan.")),
                         Says(f => f.ExampleKept()))),
                Ex("prompt_queue",
                   Scene(OnPending()),
                   Scene(OnPending(Queued(ExampleService, "at_time", 120, 1), Queued(ExampleService, "after_turn", 0, 2)))),
                Ex("codex_chat",
                   Scene(Says(f => f.ExampleField("codex_chat", "instead"))),
                   Scene(Says(f => f.Word("page.chat.you", "You") + " · " + f.Word("page.chat.sent", "Sent")),
                         Says(f => f.Word("page.chat.codex", "Codex") + " · " +
                                   f.Word("page.chat.counts", "Ran {commands} commands, changed {files} files", "commands", 3)
                                    .Replace("{files}", f.ExampleNumber(2))))),
                Ex("empty_response",
                   Scene(Says(f => f.ExampleField("empty_response", "instead"))),
                   Scene(Sent(f => f.Word("continue.empty_response",
                                          "The last turn ended without a reply. Please continue from where you stopped.")))),
                Ex("once_more_when_unsure",
                   Scene(OnHistory(Rec(ExampleProject, "submission_unknown", "usage_limit", Detected, Reset + 1))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "usage_limit", Detected, Reset + 20)))),
                Ex("send_now",
                   Scene(OnPending(Tries(Due(Rec(ExampleService, "scheduled", "server_5xx", -10, 0), 35), 1, 4))),
                   Scene(OnHistory(Rec(ExampleService, "recovered", "server_5xx", -10, -9)))),
                Ex("open_codex_button",
                   Scene(Says(f => f.ExampleClick("page.chat.click.page", "Its page in the Dashboard"))),
                   Scene(Says(f => f.ExampleClick("page.chat.click.codex", "Codex, at that conversation")))),
                Ex("capacity_retry",
                   Scene(OnHistory(Rec(ExampleProject, "exhausted", "server_5xx", -130, -65))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "server_5xx", -130, -127)))),
                Ex("compact_continue",
                   Scene(OnHistory(Rec(ExampleProject, "failed_terminal", "terminal_invalid", -60, -60))),
                   Scene(OnPending(Mark(Rec(ExampleProject, "waiting_thread", "terminal_invalid", -60, 0), "compacting")))),
                Ex("model_fallback",
                   Scene(OnHistory(Rec(ExampleProject, "exhausted", "server_5xx", -130, -65))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "server_5xx", -130, -100)))),
                Ex("codex_gave_up",
                   Scene(OnHistory(Rec(ExampleProject, "handed_over", "server_5xx", -60, -59))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "server_5xx", -60, -49)))),
                Ex("goal_continuation",
                   Scene(OnPending(Rec(ExampleProject, "waiting_thread", "usage_limit", Detected, 0))),
                   Scene(OnPending(Rec(ExampleProject, "submitted", "usage_limit", Detected, 0)))),
                Ex("subagent_parent",
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "server_5xx", -130, -128))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "server_5xx", -130, -128)),
                         Sent(f => f.ExampleSubagent()))),
                Ex("sign_in_retry",
                   Scene(OnHistory(Rec(ExampleProject, "handed_over", "terminal_auth", -60, -60))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "terminal_auth", -60, -48)))),
                Ex("unknown_failure_budget",
                   Scene(OnHistory(Rec(ExampleProject, "handed_over", "unknown", -60, -60))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "unknown", -60, -49)))),
                Ex("idle_update_check",
                   Scene(Says(f => f.ExampleField("idle_update_check", "instead"))),
                   Scene(Says(f => f.ExampleField("idle_update_check", "does")))),
                Ex("structured_rules",
                   Scene(OnHistory(Rec(ExampleProject, "handed_over", "unknown", -60, -60))),
                   Scene(OnHistory(Rec(ExampleProject, "recovered", "server_5xx", -60, -44)))),
                Ex("codex_retry_settings",
                   Scene(OnPending(Tries(Rec(ExampleProject, "exhausted", "server_5xx", -130, 0), 4, 4))),
                   Scene(OnPending(Tries(Due(Rec(ExampleProject, "scheduled", "server_5xx", -130, 0), 25), 4, 8)))),
            };
        }

        /// The example of `id`, or null where it has none.
        private static Example ExampleFor(string id)
        {
            foreach (Example each in Examples())
                if (each.Id == id) return each;
            return null;
        }

        // ---------------------------------------------------------------- the words a pane says
        private string ExampleNumber(int n)
        {
            return n.ToString("N0", CultureInfo.CurrentCulture);
        }

        /// Core's continuation for a usage limit, with the marker the standard edition ends it with or without it.
        private string ExampleContinuation(bool marker)
        {
            string words = S("continuation.standard.usage_limit", "The task was interrupted because the usage limit was reached. Please retry.");
            return marker ? words + Environment.NewLine + Environment.NewLine + ExampleMarker : words;
        }

        /// A message's length beside the most it may be, as the reset form counts it.
        private string ExampleCount(int n, int most)
        {
            return Word("page.resets.count", "{n} of {most} characters", "n", ExampleNumber(n)).Replace("{most}", ExampleNumber(most));
        }

        /// The usage line as the Overview says it (UsageLine): read `ago` minutes before, the 5-hour window at `five` % and
        /// resetting `resets` minutes from now (0: not said), the weekly window at `weekly` % (-1: not read).
        private string ExampleUsage(int ago, int five, int resets, int weekly)
        {
            double now = Now();
            var hours = new Dictionary<string, object>();
            hours["window_minutes"] = 300.0;
            hours["used_percent"] = (double)five;
            if (resets != 0) hours["reset_at"] = now + resets * 60.0;
            var windows = new List<object> { hours };
            if (weekly >= 0)
            {
                var week = new Dictionary<string, object>();
                week["window_minutes"] = 10080.0;
                week["used_percent"] = (double)weekly;
                windows.Add(week);
            }
            var reading = new Dictionary<string, object>();
            reading["read_at"] = now - ago * 60.0 - 1;
            reading["windows"] = windows;
            return UsageLine(reading) ?? "";
        }

        /// Keep going's line for example-project: kept going twice of three.
        private string ExampleKept()
        {
            return Word("page.keep.line", "{conversation} · kept going {used} of {allowed}", "conversation", ExampleProject)
                .Replace("{used}", ExampleNumber(2)).Replace("{allowed}", ExampleNumber(3));
        }

        /// Where a click on a notice goes, in the chat card's words.
        private string ExampleClick(string key, string fallback)
        {
            return Word("page.chat.click", "A click on a notice opens") + ": " + Word(key, fallback);
        }

        /// The line a parent is told of a subagent that stopped on a temporary error (continue.subagent.line).
        private string ExampleSubagent()
        {
            return Word("continue.subagent.line", "Subagent {child} stopped: {kind}. Resume or respawn it only if it is still needed.",
                        "child", "0a1b2c3d").Replace("{kind}", Word("continue.subagent.kind.temporary", "temporary error"));
        }

        /// One field of the capability's statement, as the page shows it; its title where the statement was not read.
        private string ExampleField(string id, string name)
        {
            foreach (object entry in Items(AdvancedStatement(id), "fields") ?? new List<object>())
            {
                var field = entry as Dictionary<string, object>;
                if (Str(field, "field") == name && !string.IsNullOrEmpty(Str(field, "text"))) return Str(field, "text");
            }
            return name == "does" ? Word("page.about", "About this feature") : "";
        }

        // ---------------------------------------------------------------- the view
        // The open dialog's parts while it is built - null while none is - and what a test reads of it.
        private Form exampleDialog;
        private Button exampleButton, exampleClose;
        private Label exampleNote;
        private TableLayoutPanel examplePanes;
        private readonly List<Control> examplePaneControls = new List<Control>();
        private readonly List<KeyValuePair<Control, ExamplePart>> exampleParts = new List<KeyValuePair<Control, ExamplePart>>();
        private readonly List<ListView> exampleLists = new List<ListView>();
        private Control exampleBody, exampleButtons;
        // While an example is built: what this edition says of its rows (CellsWritten) and its conversations' names
        // (ConversationOf). Null at every other moment.
        private Dictionary<string, object> exampleSaid;
        private Dictionary<string, string> exampleNames;
        // Null in every window a person opens. In a window the page's audit drives: what answers the dialog, never shown.
        private Action<Form> exampleAnswer;
        // The working area the dialog is held to: the screen's own (empty), or one the audit stands in.
        private Rectangle exampleArea;

        /// See an example... at the end of About this feature, for a capability that has one.
        private void BuildExampleButton(TableLayoutPanel about, string id)
        {
            exampleButton = null;
            if (ExampleFor(id) == null) return;
            exampleButton = CardButton(about, Word("page.example.button", "See an example..."), delegate { OpenExample(id); });
        }

        /// The view of `id`'s example, shown over this window until it is closed.
        private void OpenExample(string id)
        {
            Example example = ExampleFor(id);
            if (example == null) return;
            using (Form dialog = BuildExample(example))
            {
                if (exampleAnswer != null) exampleAnswer(dialog);
                else if (!auditing) dialog.ShowDialog(this);
            }
            ForgetExample();
        }

        private void ForgetExample()
        {
            foreach (ListView list in exampleLists)
            {
                columnWeights.Remove(list);
                cellWidths.Remove(list);
            }
            exampleLists.Clear();
            exampleParts.Clear();
            examplePaneControls.Clear();
            exampleDialog = null;
            exampleClose = null;
            exampleNote = null;
            examplePanes = null;
            exampleBody = exampleButtons = null;
            exampleSaid = null;
            exampleNames = null;
        }

        /// The working area of the screen the dialog opens on, or the one the audit stands in.
        private Rectangle ExampleScreen()
        {
            return exampleArea.IsEmpty ? Screen.GetWorkingArea(this) : exampleArea;
        }

        /// The dialog, built and not shown: the note, the two panes and Close.
        private Form BuildExample(Example example)
        {
            ForgetExample();
            exampleNames = new Dictionary<string, string>();
            foreach (string name in new[] { ExampleProject, ExampleService, ExampleApp, ExampleDocs })
                exampleNames[ExampleThread(name)] = name;
            var dialog = new Form();
            dialog.Text = Word("page.example.title", "{name}: an example", "name", AdvancedName(example.Id));
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.MinimizeBox = false;
            dialog.MaximizeBox = false;
            dialog.ShowInTaskbar = false;
            dialog.ShowIcon = false;
            // As wide as it was drawn for, or what the screen it opens on holds, less its frame and room around it; what is
            // inside takes its width from the dialog, so nothing is cut off at either edge.
            Rectangle area = ExampleScreen();
            dialog.ClientSize = new Size(Px(200), Px(200));
            int frame = dialog.Width - dialog.ClientSize.Width;
            int across = Math.Max(Px(240), Math.Min(Px(ExampleWidest), area.Width - frame - Px(32)));

            var body = new SoftStack();
            body.Dock = DockStyle.Top;
            body.AutoSize = true;
            body.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            body.ColumnCount = 1;
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            body.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            body.Padding = Pad(16, 16, 16, 0);
            body.BackColor = Canvas;
            int inner = across - body.Padding.Horizontal - SystemInformation.VerticalScrollBarWidth;
            exampleNote = HelpText(Word("page.example.note", "Made-up sample data: nothing here is read from this PC or sent anywhere."));
            exampleNote.MaximumSize = new Size(inner, 0);
            body.Controls.Add(exampleNote);

            // Side by side where each pane has its room, else one above the other.
            bool beside = inner / 2 - Px(8) >= Px(ExamplePaneLeast);
            var panes = new SoftStack();
            panes.Name = "example_panes";
            panes.Dock = DockStyle.Fill;
            panes.AutoSize = true;
            panes.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            panes.ColumnCount = beside ? 2 : 1;
            panes.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            panes.Margin = new Padding(0);
            panes.Padding = new Padding(0);
            if (beside)
            {
                panes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
                panes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            }
            else panes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            int paneWidth = beside ? inner / 2 - Px(8) : inner;
            double now = Now();
            Control before = BuildPane(Word("page.example.before", "Without it"), example.Before, paneWidth, now);
            Control after = BuildPane(Word("page.example.after", "With it"), example.After, paneWidth, now);
            before.Margin = beside ? Pad(0, 0, 8, 0) : new Padding(0);
            after.Margin = beside ? Pad(8, 0, 0, 0) : Pad(0, 8, 0, 0);
            panes.Controls.Add(before);
            panes.Controls.Add(after);
            body.Controls.Add(panes);
            examplePanes = panes;

            // On a page of its own that scrolls up and down: at 200% on a screen smaller than it, what does not fit is
            // scrolled to rather than cut off.
            var host = new SoftPage();
            host.Dock = DockStyle.Fill;
            host.Margin = new Padding(0);
            host.Padding = new Padding(0);
            host.BackColor = Canvas;
            host.Controls.Add(body);
            host.Scrolls = true;
            dialog.Controls.Add(host);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(0, 12, 16, 16);
            exampleClose = MakeButton(S("action.close", "Close"), true, delegate { dialog.Close(); });
            buttons.Controls.Add(exampleClose);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = exampleClose;
            dialog.CancelButton = exampleClose;
            dialog.ActiveControl = exampleClose;
            exampleDialog = dialog;
            exampleBody = body;
            exampleButtons = buttons;
            exampleSaid = null;
            dialog.ClientSize = new Size(across, Px(400));
            FitExample(dialog, area);
            return dialog;
        }

        /// The dialog as tall as what it shows, and no taller than the screen lets a window be, less room around it.
        private void FitExample(Form dialog, Rectangle area)
        {
            int width = dialog.ClientSize.Width;
            dialog.PerformLayout();
            exampleBody.Parent.PerformLayout();
            exampleBody.PerformLayout();
            int tall = Math.Max(exampleBody.Height, exampleBody.GetPreferredSize(new Size(width, 0)).Height);
            int buttonsTall = exampleButtons.GetPreferredSize(new Size(width, 0)).Height;
            int frame = dialog.Height - dialog.ClientSize.Height;
            int most = Math.Min(area.Height, SystemInformation.MaxWindowTrackSize.Height) - frame - Px(48);
            int want = Math.Max(Math.Min(Px(240), most), Math.Min(tall + buttonsTall, most));
            if (dialog.ClientSize.Height != want) dialog.ClientSize = new Size(width, want);
        }

        /// One pane: its caption, then each part of `scene` in order, `width` wide.
        private Control BuildPane(string caption, ExampleScene scene, int width, double now)
        {
            var pane = new SoftStack();
            pane.Dock = DockStyle.Fill;
            pane.AutoSize = true;
            pane.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            pane.ColumnCount = 1;
            pane.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            pane.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            pane.Padding = new Padding(0);
            pane.BackColor = Canvas;
            Label title = Caption(caption);
            title.Margin = Pad(0, 6, 0, 0);
            title.MaximumSize = new Size(width, 0);
            pane.Controls.Add(title);
            foreach (ExamplePart part in scene.Parts)
            {
                if (part.Kind == "history" || part.Kind == "pending")
                {
                    Control made = ExampleList(part, width, now);
                    pane.Controls.Add(made);
                    exampleParts.Add(new KeyValuePair<Control, ExamplePart>(made, part));
                    continue;
                }
                string text = part.Text == null ? "" : part.Text(this) ?? "";
                if (part.Kind == "sent")
                {
                    Label heading = Caption(Word("page.preview.title", "What is sent, exactly"));
                    heading.Font = Soft.RoleFont("label");
                    heading.MaximumSize = new Size(width, 0);
                    pane.Controls.Add(heading);
                }
                Label line = HelpText(text);
                line.ForeColor = Ink;
                line.MaximumSize = new Size(width, 0);
                pane.Controls.Add(line);
                exampleParts.Add(new KeyValuePair<Control, ExamplePart>(line, part));
            }
            examplePaneControls.Add(pane);
            return pane;
        }

        /// A part's rows on History's card (DialogListCard), shaped as History or Pending, every cell written by the window's
        /// own Cells; the card exactly as tall as its rows. With no row, the page's own words for an empty list.
        private Control ExampleList(ExamplePart part, int width, double now)
        {
            bool pending = part.Kind == "pending";
            if (part.Rows.Count == 0)
            {
                Label empty = HelpText(pending ? S("pending.empty", "Nothing is waiting") : S("history.empty", "No recoveries yet"));
                empty.MaximumSize = new Size(width, 0);
                return empty;
            }
            ListView list = pending
                ? List(S("nav.pending", "Pending"),
                       Col(S("pending.col_conversation", "Conversation"), 140),
                       Col(S("pending.col_status", "Status"), 190),
                       Col(S("pending.col_category", "Kind"), 110),
                       Col(S("pending.col_next", "Next check"), 84),
                       Col(S("pending.col_attempts", "Attempts"), 70))
                : List(S("nav.history", "History"),
                       Col(S("pending.col_conversation", "Conversation"), 220),
                       Col(S("history.col_outcome", "Outcome"), 200),
                       Col(S("pending.col_category", "Kind"), 130),
                       Col(S("history.col_detected", "Detected"), 130),
                       Col(S("history.col_finished", "Finished"), 130));
            exampleLists.Add(list);
            // What this edition says of these rows, as the status of a snapshot says it (surfaces.rows).
            var said = new Dictionary<string, object>();
            var kinds = new Dictionary<string, object>();
            said["kinds"] = kinds;
            foreach (string name in new[] { "compacting", "silent", "model_not_restored" }) said[name] = new List<object>();
            var rows = new List<Dictionary<string, object>>();
            foreach (Dictionary<string, object> sample in part.Rows)
            {
                Dictionary<string, object> row = ExampleRow(sample, now);
                rows.Add(row);
                string note = Str(sample, "example_said"), key = Str(row, "interruption_id");
                if (note == null || key == null) continue;
                if (note == "cli" || note == "ide") kinds[key] = note;
                else ((List<object>)said[note]).Add(key);
            }
            exampleSaid = said;
            try
            {
                list.BeginUpdate();
                foreach (Dictionary<string, object> row in rows)
                {
                    string[] cells = Cells(row, pending);
                    if (pending && cells[3] == null) cells[3] = CountdownText(row, now);
                    var item = new ListViewItem(cells[0] ?? "");
                    for (int c = 1; c < list.Columns.Count; c++) item.SubItems.Add(cells[c] ?? "");
                    item.Tag = row;
                    list.Items.Add(item);
                }
                list.EndUpdate();
            }
            finally
            {
                exampleSaid = null;
            }
            Control ground = DialogListCard(list);
            ground.Dock = DockStyle.Top;
            ground.Width = width;
            IntPtr made = list.Handle;
            int last = list.Items.Count - 1;
            int listTall = list.GetItemRect(last).Bottom + Px(2);
            var card = ground.Controls.Count > 0 ? ground.Controls[0] : null;
            int cardRoom = card == null ? 0 : card.Padding.Vertical;
            ground.Height = listTall + cardRoom + ground.Padding.Vertical;
            ground.MinimumSize = new Size(0, ground.Height);
            MeasureCells(list);
            return ground;
        }

        /// A sample row as the reads have it: its moments counted from `now`, and this edition's own rows made as Pending
        /// makes them (RuleRow, PromptRow).
        private Dictionary<string, object> ExampleRow(Dictionary<string, object> sample, double now)
        {
            var row = new Dictionary<string, object>(sample);
            object minutes;
            if (row.TryGetValue("example_detected", out minutes)) row["detected_at"] = now + (double)minutes * 60;
            if (row.TryGetValue("example_finished", out minutes)) row["outcome_at"] = now + (double)minutes * 60;
            if (row.TryGetValue("example_due", out minutes))
            {
                row["eligible_at"] = now + (double)minutes * 60;
                row["due_at"] = now + (double)minutes * 60;
            }
            string kind = Str(row, "example_kind");
            if (kind == "rule") return RuleRow(row);
            if (kind == "prompt") return PromptRow(row);
            return row;
        }

        // ---------------------------------------------------------------- the audit's hooks
        /// What the view of the open capability's example shows when See an example... is pressed - built and never shown:
        /// its title, note, panes (each caption, and each part's columns and cells or words, and how much ink each drew) and
        /// its button; "pressed" false where the button was not there to press.
        private Dictionary<string, object> ExampleLook()
        {
            var record = new Dictionary<string, object>();
            record["capability"] = advancedOpen;
            record["pressed"] = false;
            if (exampleButton == null || exampleButton.IsDisposed || !Soft.OwnVisible(exampleButton)) return record;
            record["button"] = exampleButton.Text;
            record["button_in_about"] = exampleButton.Parent != null && exampleButton.Parent.Controls.Count > 0 &&
                                        exampleButton.Parent.Controls[0].Text == Word("page.about", "About this feature");
            record["button_enabled"] = exampleButton.Enabled;
            exampleAnswer = delegate(Form dialog) { LookAtExample(dialog, record); };
            // Its Click raised as a press raises it (Pressed): PerformClick does nothing on a button no one can see.
            try { Pressed.Invoke(exampleButton, new object[] { EventArgs.Empty }); }
            finally { exampleAnswer = null; }
            return record;
        }

        private void LookAtExample(Form dialog, Dictionary<string, object> record)
        {
            record["pressed"] = true;
            record["title"] = dialog.Text;
            record["note"] = exampleNote.Text;
            record["close"] = exampleClose.Text;
            record["accept"] = dialog.AcceptButton == exampleClose && dialog.CancelButton == exampleClose;
            record["beside"] = examplePanes.ColumnCount == 2;
            dialog.TopLevel = false;
            Materialise(dialog);
            dialog.PerformLayout();
            var panes = new List<object>();
            foreach (Control pane in examplePaneControls)
            {
                var seen = new Dictionary<string, object>();
                seen["caption"] = pane.Controls.Count > 0 ? pane.Controls[0].Text : null;
                var parts = new List<object>();
                foreach (KeyValuePair<Control, ExamplePart> pair in exampleParts)
                {
                    if (!IsInside(pair.Key, pane)) continue;
                    var part = new Dictionary<string, object>();
                    part["kind"] = pair.Value.Kind;
                    ListView list = FindList(pair.Key);
                    if (list != null)
                    {
                        var columns = new List<object>();
                        foreach (ColumnHeader column in list.Columns) columns.Add(column.Text);
                        part["columns"] = columns;
                        var rows = new List<object>();
                        foreach (ListViewItem item in list.Items)
                        {
                            var cells = new List<object>();
                            foreach (ListViewItem.ListViewSubItem cell in item.SubItems) cells.Add(cell.Text);
                            rows.Add(cells);
                        }
                        part["rows"] = rows;
                        part["on_card"] = ListOffCard(list) ?? "";
                    }
                    else part["text"] = pair.Key.Text;
                    part["ink"] = (double)InkOf(pair.Key);
                    parts.Add(part);
                }
                seen["parts"] = parts;
                seen["ink"] = (double)InkOf(pane);
                panes.Add(seen);
            }
            record["panes"] = panes;
        }

        private static bool IsInside(Control control, Control parent)
        {
            for (Control at = control; at != null; at = at.Parent)
                if (at == parent) return true;
            return false;
        }

        private static ListView FindList(Control control)
        {
            var list = control as ListView;
            if (list != null) return list;
            foreach (Control child in control.Controls)
            {
                ListView found = FindList(child);
                if (found != null) return found;
            }
            return null;
        }

        /// How many of `control`'s pixels the window drew in ink - the text's colours, the chips' - when it draws itself into
        /// a bitmap, as the render mode draws the window (DrawToBitmap): 0 for a part that drew nothing on its ground.
        private int InkOf(Control control)
        {
            if (control.Width <= 0 || control.Height <= 0) return 0;
            using (var picture = new Bitmap(control.Width, control.Height))
            {
                control.DrawToBitmap(picture, new Rectangle(Point.Empty, control.Size));
                int count = 0;
                for (int y = 0; y < picture.Height; y += 2)
                    for (int x = 0; x < picture.Width; x += 2)
                    {
                        Color seen = picture.GetPixel(x, y);
                        if (Far(seen, Canvas) && Far(seen, Card) && Far(seen, Palette.Inset) && Far(seen, Line)) count++;
                    }
                return count;
            }
        }

        private static bool Far(Color a, Color b)
        {
            return Math.Abs(a.R - b.R) + Math.Abs(a.G - b.G) + Math.Abs(a.B - b.B) > 96;
        }

        /// Every example's view, built and never shown on a working area `width` by `height` px at `scale`, in the language of
        /// `stringsJson` with the page's words `wordsJson` and the statements `statementsJson` ({id: advanced-statement's
        /// answer}), held to the window's audit: nothing cut off, nothing scrolling sideways, every control named, each list on
        /// its card and its columns within it, the panes one above the other where they have no room beside each other, and
        /// the dialog within the working area. One line for each finding; "" for none.
        internal static string AdvancedExamplesAudit(string stringsJson, string wordsJson, string statementsJson, double scale,
                                                     int width, int height)
        {
            var findings = new List<string>();
            AdvancedAudited = 0;
            WithAdvancedWindow(stringsJson, scale, delegate(SettingsForm form)
            {
                form.AdoptAdvancedWords(Json.Parse(wordsJson) as Dictionary<string, object>);
                var statements = Json.Parse(statementsJson) as Dictionary<string, object> ?? new Dictionary<string, object>();
                foreach (KeyValuePair<string, object> pair in statements)
                    form.advancedStatements[pair.Key] = pair.Value as Dictionary<string, object>;
                form.exampleArea = new Rectangle(0, 0, width, height);
                foreach (Example example in Examples())
                {
                    string where = "example/" + example.Id;
                    using (Form dialog = form.BuildExample(example))
                    {
                        AdvancedAudited++;
                        Size outer = dialog.Size;
                        dialog.TopLevel = false;
                        Materialise(dialog);
                        dialog.PerformLayout();
                        form.Walk(dialog, where, findings);
                        AuditSpoken(where, dialog, findings);
                        if (outer.Width > width || outer.Height > height)
                            findings.Add(where + " :: the dialog is " + outer.Width + "x" + outer.Height + " on a working area of " +
                                         width + "x" + height);
                        bool room = (dialog.ClientSize.Width - form.Px(32) - SystemInformation.VerticalScrollBarWidth) / 2 - form.Px(8)
                                    >= form.Px(ExamplePaneLeast);
                        if (form.examplePanes.ColumnCount == 2 && !room)
                            findings.Add(where + " :: the panes stand side by side with no room for them");
                        foreach (ListView list in form.exampleLists)
                        {
                            AuditList(where + "/" + AuditName(list), list, findings);
                            string off = ListOffCard(list);
                            if (off != null) findings.Add(where + " :: its list is not on a card: " + off);
                        }
                    }
                    form.ForgetExample();
                }
                form.exampleArea = Rectangle.Empty;
            });
            return string.Join("\n", findings.ToArray());
        }
    }
}

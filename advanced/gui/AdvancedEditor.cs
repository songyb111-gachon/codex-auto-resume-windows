// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the prompt queue's editor (v0.6.19, issue #50): the one place a message is scheduled or changed.
//
// A child dialog in the Dashboard's design - the window's dialogs' frame (gui/DashboardActions.cs Dialog), one card of the
// Settings page's rows on the canvas - for a new message or, filled, for one still waiting: the conversation (fixed for an
// edit), the words in a box at the reading size (the type scale's figure step, 3 pt over the window's text: never under
// 12 pt at 100%), counted to the bound, when it goes (after this turn, at a time, every day or every week), at which
// hour, how many times for a series, whether it waits for the one before it, and - for a time or a series - what it does
// while a turn is running in that conversation: two named behaviours, as two of the window's choice cards (a choice, not a
// switch), Wait until it ends marked recommended and preselected for a new message. After this turn says it goes into
// Codex's queue by its nature. Two buttons: Save and return (the accent, what Enter presses) and Cancel.
//
// Save and return is the bridge's advanced-prompt-add or advanced-prompt-edit, against the generation the list was read
// at. Taken, the dialog closes, the list is read again and the saved row is the one chosen there; refused, the dialog
// stays with every field as typed and the refusal's words above the buttons.
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
        // The open editor's fields, as it was built - null while none is - for its own reads and the page's audit.
        private Form editorDialog;
        private SoftCombo editorConversation, editorWhen, editorHour, editorTimes, editorDepends;
        private SoftTextArea editorWords;
        private Label editorCount, editorAfterTurn, editorSaid;
        private ChoiceGroup editorMode;
        private Button editorSave, editorCancel;
        private int editorPrompt = -1;
        private bool editorTaken;
        // The prompt the last Save and return saved, for the list read after it to choose; -1 where none waits to be.
        private int editorSaved = -1;
        // Null in every window a person opens. In a window AdvancedPageRun drives: what answers the editor, never shown.
        private Action<Form> editorAnswer;
        // The type scale's figure step (SoftTheme.RoleFont "figure"): the editor's words are read at it.
        private const float ReadingLarger = 3f;

        /// The editor for a new message (`row` null) or for `row`, a prompt still waiting: shown, answered, and - where it
        /// saved - the page and the list read again, the saved row to be chosen there.
        private void OpenEditor(Dictionary<string, object> row)
        {
            if (busy > 0 || advancedListing == null || advancedPrompts == null) return;
            if (row != null && Str(row, "state") != "waiting") return;
            using (Form dialog = BuildEditor(row))
            {
                if (editorAnswer != null) editorAnswer(dialog);
                else if (!auditing) dialog.ShowDialog(this);
            }
            bool taken = editorTaken;
            ForgetEditor();
            if (!taken) return;
            ResetNote(Word("page.done.prompt_saved", "Saved."));
            // The list as the save answered it, the saved row chosen (AdvancedSchedule.cs), then read again.
            FillScheduled();
            ReadAdvanced(null);
            if (advancedOpen != PromptQueueId) ReadPrompts(null);
        }

        private void ForgetEditor()
        {
            editorDialog = null;
            editorConversation = editorWhen = editorHour = editorTimes = editorDepends = null;
            editorWords = null;
            editorCount = editorAfterTurn = editorSaid = null;
            editorMode = null;
            editorSave = editorCancel = null;
            editorPrompt = -1;
            editorTaken = false;
        }

        private int EditorWordsMost()
        {
            int most = Whole(Get(Map(advancedPrompts, "limits"), "words"));
            return most > 0 ? most : 2000;
        }

        /// The dialog, built and not shown: filled from `row`, or empty for a new message.
        private Form BuildEditor(Dictionary<string, object> row)
        {
            ForgetEditor();
            bool editing = row != null;
            editorPrompt = editing ? Whole(Get(row, "prompt_id")) : -1;
            string title = editing ? Word("page.editor.title_edit", "Edit the message")
                                   : Word("page.editor.title_new", "Schedule a message");
            var dialog = new Form();
            dialog.Text = title;
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
            int width = Px(560);

            var body = new SoftStack();
            body.Dock = DockStyle.Top;
            body.AutoSize = true;
            body.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            body.ColumnCount = 1;
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            body.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            body.Padding = Pad(16, 16, 16, 0);
            body.BackColor = Canvas;
            TableLayoutPanel card = MakeCard(title);
            card.Margin = new Padding(0);
            body.Controls.Add(card);

            string conversation = Word("page.resets.field.conversation", "Conversation");
            editorConversation = EditorCombo(conversation, 300);
            foreach (KeyValuePair<string, string> pair in Conversations())
                editorConversation.Items.Add(new Choice(pair.Key, pair.Value));
            string thread = editing ? Str(row, "thread_id") : null;
            if (thread != null && !Conversations().ContainsKey(thread))
                editorConversation.Items.Add(new Choice(thread, ConversationOf(thread)));
            SelectChoice(editorConversation, thread);
            editorConversation.Enabled = !editing;
            card.Controls.Add(NewRow(conversation, editorConversation));
            if (editorConversation.Items.Count == 0)
                card.Controls.Add(HelpText(Word("page.resets.no_conversation",
                    "No conversation is listed yet. One is offered here once Pending or History lists it.")));

            string words = Word("page.resets.field.words", "Message");
            card.Controls.Add(Caption(words));
            editorWords = new SoftTextArea();
            Font reading = Soft.Weighted(Font, Font.SizeInPoints + ReadingLarger, 400);
            editorWords.Font = reading;
            editorWords.Box.Font = reading;
            editorWords.Box.MaxLength = EditorWordsMost();
            editorWords.Box.AccessibleName = words;
            editorWords.Height = Px(150);
            editorWords.Dock = DockStyle.Fill;
            editorWords.Margin = Pad(0, 4, 0, 2);
            if (editing) editorWords.Box.Text = (Str(row, "words") ?? "").Replace("\r\n", "\n").Replace("\n", "\r\n");
            card.Controls.Add(editorWords);
            editorCount = HelpText("");
            card.Controls.Add(editorCount);

            string when = Word("page.queue.when", "When");
            editorWhen = EditorCombo(when, 220);
            editorWhen.Items.Add(new Choice("after_turn", Word("page.queue.when.after_turn", "After this turn")));
            editorWhen.Items.Add(new Choice("at_time", Word("page.queue.when.at_time", "At a time")));
            editorWhen.Items.Add(new Choice("day", Word("page.queue.when.daily", "Every day")));
            editorWhen.Items.Add(new Choice("week", Word("page.queue.when.weekly", "Every week")));
            string trigger = editing ? Str(row, "trigger") : null;
            SelectChoice(editorWhen, trigger == "recurring" ? Str(row, "every") : trigger ?? "after_turn");
            card.Controls.Add(NewRow(when, editorWhen));

            string hour = Word("page.queue.hour", "At");
            editorHour = EditorCombo(hour, 120);
            for (int h = 0; h < 24; h++)
                editorHour.Items.Add(new Choice(h.ToString(CultureInfo.InvariantCulture), h.ToString("00", CultureInfo.InvariantCulture) + ":00"));
            double due = editing && Get(row, "due_at") is double ? (double)Get(row, "due_at") : 0;
            int chosenHour = due > 0 && trigger != "after_turn"
                ? new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(due).ToLocalTime().Hour : 9;
            editorHour.SelectedIndex = chosenHour;
            card.Controls.Add(NewRow(hour, editorHour));

            string times = Word("page.queue.times", "How many times");
            editorTimes = EditorCombo(times, 120);
            for (int n = 1; n <= SeriesMost; n++)
                editorTimes.Items.Add(new Choice(n.ToString(CultureInfo.InvariantCulture), n.ToString(CultureInfo.CurrentCulture)));
            editorTimes.SelectedIndex = Math.Max(0, Math.Min(SeriesMost, editing ? Whole(Get(row, "occurrences")) : 1) - 1);
            card.Controls.Add(NewRow(times, editorTimes));

            string depends = Word("page.queue.depends", "Wait for the one before it to arrive");
            editorDepends = EditorCombo(depends, 120);
            editorDepends.Items.Add(new Choice("no", Word("page.queue.depends.no", "No")));
            editorDepends.Items.Add(new Choice("yes", Word("page.queue.depends.yes", "Yes")));
            editorDepends.SelectedIndex = editing && Equals(Get(row, "depends"), true) ? 1 : 0;
            card.Controls.Add(NewRow(depends, editorDepends));

            // What it does while a turn runs: two named behaviours, the recommended one first and chosen for a new one.
            string mode = Word("page.editor.mode", "When a turn is running in that conversation:");
            card.Controls.Add(Caption(mode));
            editorMode = new ChoiceGroup();
            editorMode.Dock = DockStyle.Fill;
            editorMode.Font = Font;
            editorMode.Margin = Pad(0, 2, 0, 4);
            editorMode.AccessibleName = mode;
            editorMode.Add(new ChoiceCard("wait", Word("page.editor.mode.wait", "Wait until it ends (recommended)"), ""));
            editorMode.Add(new ChoiceCard("queue", Word("page.editor.mode.queue",
                "Add it to Codex's queue now - Codex runs it after that turn"), ""));
            editorMode.Value = editing && Str(row, "while_running") == "queue" ? "queue" : "wait";
            card.Controls.Add(editorMode);
            editorAfterTurn = HelpText(Word("page.editor.mode.after_turn",
                "\"After this turn\" goes into Codex's queue: Codex runs it when the turn now running ends."));
            card.Controls.Add(editorAfterTurn);
            if (Equals(Get(advancedPrompts, "after_turn_unproven"), true))
                card.Controls.Add(HelpText(Word("page.queue.unproven",
                    "After this turn is unproven on this Codex until it has been measured.")));

            // Where a refusal is said, above the buttons.
            editorSaid = HelpText("");
            editorSaid.ForeColor = Palette.Danger;
            body.Controls.Add(editorSaid);
            // On a page of its own that scrolls up and down: at 200% on a screen smaller than it, Windows holds the dialog
            // to the screen, and what does not fit is scrolled to rather than cut off.
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
            editorSave = MakeButton(Word("page.editor.save", "Save and return"), true, delegate { SaveEditor(dialog); });
            editorCancel = MakeButton(S("action.cancel", "Cancel"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(editorSave);
            buttons.Controls.Add(editorCancel);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = editorSave;
            dialog.CancelButton = editorCancel;
            dialog.ActiveControl = editing ? (Control)editorWords.Box : editorConversation;

            editorWords.Box.TextChanged += delegate { ShowEditorState(); };
            editorWhen.SelectionChangeCommitted += delegate { ShowEditorState(); };
            editorConversation.SelectionChangeCommitted += delegate { ShowEditorState(); };
            editorDialog = dialog;
            ShowEditorState();

            // As tall as everything with the longest refusal said: the dialog never grows under a person's hand. Each line
            // that wraps is held to the width it is laid out at - a measure taken at a wider width read Hebrew at 200% short
            // by two lines - and the dialog is laid out once to read how tall it all is.
            editorSaid.Text = PromptRefusal("queue_full");
            editorAfterTurn.Visible = editorMode.Visible = true;
            int inner = width - body.Padding.Horizontal;
            int lines = inner - card.Padding.Horizontal;
            foreach (Control control in card.Controls)
                if (control is WrapLabel) control.MaximumSize = new Size(lines, 0);
            editorSaid.MaximumSize = new Size(inner, 0);
            int buttonsTall = buttons.GetPreferredSize(new Size(width, 0)).Height;
            dialog.ClientSize = new Size(width, Px(400));
            dialog.PerformLayout();
            host.PerformLayout();
            body.PerformLayout();
            int tall = Math.Max(body.Height, body.GetPreferredSize(new Size(width, 0)).Height);
            // As tall as all of it, and never taller than the screen it opens on lets a window be.
            int most = Math.Min(Screen.GetWorkingArea(this).Height, SystemInformation.MaxWindowTrackSize.Height) - Px(96);
            dialog.ClientSize = new Size(width, Math.Max(Px(240), Math.Min(tall + buttonsTall, most)));
            editorSaid.Text = "";
            ShowEditorState();
            return dialog;
        }

        private SoftCombo EditorCombo(string name, int width)
        {
            var combo = new SoftCombo();
            combo.Width = Px(width);
            IgnoreWheel(combo);
            combo.AccessibleName = name;
            return combo;
        }

        private static void SelectChoice(ComboBox combo, string value)
        {
            int index = combo.Items.Count > 0 ? 0 : -1;
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var choice = combo.Items[i] as Choice;
                if (choice != null && choice.Value == value) index = i;
            }
            combo.SelectedIndex = index;
        }

        /// What the fields allow now: the hour for a time or a series, the count for a series, the send mode for a time or a
        /// series (After this turn says what it does instead), Save and return once there is a conversation and words.
        private void ShowEditorState()
        {
            if (editorWhen == null) return;
            var when = editorWhen.SelectedItem as Choice;
            string value = when == null ? "after_turn" : when.Value;
            bool later = value != "after_turn";
            editorHour.Enabled = later;
            editorTimes.Enabled = value == "day" || value == "week";
            editorMode.Visible = later;
            editorAfterTurn.Visible = !later;
            editorCount.Text = Word("page.resets.count", "{n} of {most} characters", "n", editorWords.Box.Text.Length)
                .Replace("{most}", EditorWordsMost().ToString(CultureInfo.CurrentCulture));
            editorSave.Enabled = busy == 0 && editorConversation.SelectedItem != null && editorWords.Box.Text.Trim().Length > 0;
        }

        /// The request Save and return sends, or null where a field it needs has nothing chosen.
        private string EditorArgument()
        {
            var conversation = editorConversation.SelectedItem as Choice;
            var when = editorWhen.SelectedItem as Choice;
            if (conversation == null || when == null) return null;
            var argument = new System.Text.StringBuilder("{");
            if (editorPrompt >= 0) argument.Append("\"prompt\":").Append(editorPrompt.ToString(CultureInfo.InvariantCulture));
            else argument.Append("\"thread_id\":").Append(Json.Escape(conversation.Value));
            argument.Append(",\"words\":").Append(Json.Escape(editorWords.Box.Text.Replace("\r\n", "\n")));
            if (when.Value == "after_turn") argument.Append(",\"trigger\":\"after_turn\",\"while_running\":\"queue\"");
            else
            {
                var hour = editorHour.SelectedItem as Choice;
                if (hour == null) return null;
                double at = NextHour(int.Parse(hour.Value, CultureInfo.InvariantCulture));
                bool series = when.Value == "day" || when.Value == "week";
                argument.Append(",\"trigger\":").Append(Json.Escape(series ? "recurring" : "at_time"))
                        .Append(",\"at\":").Append(at.ToString("0", CultureInfo.InvariantCulture));
                if (series)
                {
                    var times = editorTimes.SelectedItem as Choice;
                    argument.Append(",\"every\":").Append(Json.Escape(when.Value))
                            .Append(",\"occurrences\":").Append(times == null ? "1" : times.Value);
                }
                argument.Append(",\"while_running\":").Append(Json.Escape(editorMode.Value == "queue" ? "queue" : "wait"));
            }
            var depends = editorDepends.SelectedItem as Choice;
            argument.Append(",\"depends\":").Append(depends != null && depends.Value == "yes" ? "true" : "false");
            argument.Append(",\"generation\":").Append(AdvancedGeneration()).Append('}');
            return argument.ToString();
        }

        /// Save and return: the bridge's add or edit. Taken, the dialog closes and the saved row waits to be chosen; refused,
        /// the refusal is said above the buttons and every field stays as typed.
        private void SaveEditor(Form dialog)
        {
            if (busy > 0 || advancedListing == null || editorSave == null || !editorSave.Enabled) return;
            string argument = EditorArgument();
            if (argument == null) return;
            bool editing = editorPrompt >= 0;
            editorSave.Enabled = false;
            editorSaid.Text = "";
            AdvancedCall(editing ? "advanced-prompt-edit" : "advanced-prompt-add", argument, true,
                         delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (dialog.IsDisposed || editorSaid == null) return;
                if (AdvancedDone(result))
                {
                    editorTaken = true;
                    editorSaved = Get(result, "prompt") is double ? Whole(Get(result, "prompt")) : -1;
                    advancedPrompts = result;
                    dialog.DialogResult = DialogResult.OK;
                    if (dialog.Visible) dialog.Close();
                    return;
                }
                string refusal = Str(result, "refusal");
                editorSaid.Text = editing && refusal == "invalid_request"
                    ? Word("page.refused.prompt_moved", "It is no longer waiting, so it can no longer be changed.")
                    : PromptRefusal(refusal);
                ShowEditorState();
            });
        }
    }
}

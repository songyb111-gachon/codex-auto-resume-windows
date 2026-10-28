// Codex Auto Resume - v0.6.11's own Dashboard tools: a task's postponement taken away, a message for one
// conversation, the log searched, who may open the state folder, and Show me what happens - and v0.6.16-beta.3's
// words for this time, added once to one waiting task's next continuation.
//
// Each only asks the bridge, and each acts on exactly what the person chose: a row's own record and
// conversation, or nothing at all. The demo's rows are made up (demo.py) and kept in this window's
// memory only; nothing about them reaches the state, and no action is offered on them.

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
        // ------------------------------------------------------------------- Don't postpone
        /// Whether Don't postpone can take something away: a waiting task a person postponed to a time still
        /// ahead (`postponed_until`, which an objection window's own end never is), and never a made-up one.
        internal static bool CanUnpostpone(Dictionary<string, object> row, bool idle, double now)
        {
            return CanPostpone(row, idle) && !IsDemo(row) && Number(row, "postponed_until") > now;
        }

        /// Takes the person's own postponement off exactly the task the menu was opened on. It goes back only to
        /// what the schedule says, so it asks nothing, as postponing asks nothing.
        private void Unpostpone(Dictionary<string, object> row)
        {
            string key = Str(row, "interruption_id");
            CallAsync("unpostpone", RowArgument(row, null), delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    RefreshAfterChange();
                    return;
                }
                pendingNoteFor = key;
                pendingNoteText = S("result.unpostponed", "No longer postponed. Every safety check still applies.");
                ShowPendingNote();
                RefreshAfterChange();
            });
        }

        // ---------------------------------------------------------- a conversation's own message
        /// This conversation's own message as the status last read the settings, or null.
        internal static string ConversationText(Dictionary<string, object> settings, string thread)
        {
            var held = Map(settings, "custom_message_by_thread");
            return thread == null ? null : Str(held, thread);
        }

        private void EditConversationMessage(Dictionary<string, object> row)
        {
            if (row == null || IsDemo(row) || Str(row, "thread_id") == null) return;
            var settings = snapshot == null ? null : Map(Map(snapshot, "status"), "settings");
            using (Form dialog = BuildConversationMessage(row, ConversationText(settings, Str(row, "thread_id"))))
                dialog.ShowDialog(this);
        }

        /// The dialog for one conversation's own message, built and not shown: its words, sent exactly as written,
        /// with the Preview of what the next continuation there says, and Save, Remove message and Cancel.
        private Form BuildConversationMessage(Dictionary<string, object> row, string current)
        {
            var dialog = new Form();
            dialog.Text = S("conversation.title", "Message for this conversation") + " - " + Conversation(row);
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.MinimizeBox = false;
            dialog.MaximizeBox = false;
            dialog.ShowInTaskbar = false;
            dialog.ShowIcon = false;
            dialog.ClientSize = new Size(Px(600), Px(520));

            var body = new SoftStack();
            body.Dock = DockStyle.Fill;
            body.ColumnCount = 1;
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            body.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            body.Padding = Pad(16, 16, 16, 0);
            body.BackColor = Canvas;
            var help = Value(S("conversation.help",
                "Sent instead of the continuation message each time this conversation is continued, whatever the message style. It is written only here, and sent exactly as you write it."));
            help.ForeColor = Secondary;
            help.MaximumSize = new Size(Px(560), 0);
            body.Controls.Add(help);
            var placeholders = Value(S("custom.placeholders", "You can use {reason}, {category}, {attempt}, {max_attempts} and {reset_time}."));
            placeholders.ForeColor = Secondary;
            placeholders.MaximumSize = new Size(Px(560), 0);
            body.Controls.Add(placeholders);

            var area = new SoftTextArea();
            area.Dock = DockStyle.Fill;
            area.Margin = Pad(0, 6, 0, 2);
            area.Font = Font;
            area.Box.Font = Font;
            area.Box.Text = FromStored(current);
            area.Box.AccessibleName = S("conversation.title", "Message for this conversation");
            area.Height = Px(140);
            body.Controls.Add(area);
            // Its length as the settings layer counts it, as the Settings page shows a Custom message's.
            Label count = CountLabel();
            area.Box.TextChanged += delegate { UpdateCount(area, count); };
            UpdateCount(area, count);
            body.Controls.Add(count);

            var refusal = Value("");
            refusal.ForeColor = Palette.Danger;
            refusal.MaximumSize = new Size(Px(560), 0);
            body.Controls.Add(refusal);
            body.Controls.Add(Caption(S("preview.title", "Preview")));
            var preview = new SoftQuote();
            preview.Dock = DockStyle.Fill;
            preview.Font = Font;
            preview.Margin = Pad(0, 2, 0, 2);
            preview.AccessibleName = S("preview.title", "Preview");
            body.Controls.Add(preview);
            var source = Value("");
            source.ForeColor = Secondary;
            body.Controls.Add(source);
            dialog.Controls.Add(body);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(0, 12, 16, 16);
            string thread = Str(row, "thread_id");
            Button save = MakeButton(S("action.save", "Save"), true, delegate
            {
                string text = (area.Box.Text ?? "").Replace("\r\n", "\n");
                SaveConversationMessage(dialog, thread, text.Trim().Length == 0 ? null : text);
            });
            Button remove = MakeButton(S("conversation.remove", "Remove message"), false,
                                       delegate { SaveConversationMessage(dialog, thread, null); });
            remove.Enabled = current != null;
            Button cancel = MakeButton(S("action.cancel", "Cancel"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(save);
            buttons.Controls.Add(cancel);
            buttons.Controls.Add(remove);
            dialog.Controls.Add(buttons);
            dialog.CancelButton = cancel;
            dialog.ActiveControl = area.Box;

            // What the next continuation in this conversation would say, as the watcher would build it
            // (control/preview.py): asked a moment after the typing stops, from a worker, and never saved.
            var wait = new Timer();
            wait.Interval = 400;
            int token = 0;
            string category = Str(row, "category") ?? "usage_limit";
            EventHandler ask = delegate
            {
                wait.Stop();
                int mine = ++token;
                string text = (area.Box.Text ?? "").Replace("\r\n", "\n");
                string argument = "{\"category\":" + Json.Escape(category) + ",\"thread_id\":" + Json.Escape(thread) +
                                  ",\"changes\":{\"custom_message_by_thread\":" +
                                  (text.Trim().Length == 0 ? "null" : "{" + Json.Escape(thread) + ":" + Json.Escape(text) + "}") + "}}";
                System.Threading.ThreadPool.QueueUserWorkItem(delegate
                {
                    Dictionary<string, object> reply = null;
                    try { reply = bridge.Call("preview-continuation", argument); }
                    catch (Exception) { reply = null; }
                    MethodInvoker apply = delegate
                    {
                        if (mine != token || dialog.IsDisposed) return;
                        var result = Ok(reply) ? Map(reply, "result") : null;
                        preview.Quote = result == null ? S("preview.unavailable", "Preview is not available right now.")
                                                       : Str(result, "text") ?? "";
                        string from = Str(result, "source");
                        source.Text = from == "conversation"
                            ? S("preview.source.conversation", "Using the message for this conversation") : "";
                        refusal.Text = result == null ? "" : RefusalText(result);
                    };
                    try { if (dialog.IsHandleCreated && !dialog.IsDisposed) dialog.BeginInvoke(apply); }
                    catch (Exception) { }
                });
            };
            wait.Tick += ask;
            area.Box.TextChanged += delegate { wait.Stop(); wait.Start(); };
            dialog.Shown += delegate { ask(null, EventArgs.Empty); };
            dialog.FormClosed += delegate { wait.Stop(); wait.Dispose(); };
            dialog.KeyPreview = true;
            dialog.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Escape) { e.Handled = true; dialog.Close(); }
            };
            conversationArea = area;
            return dialog;
        }

        /// Saves (or, for null, removes) one conversation's own message, and closes the dialog once it is stored.
        private void SaveConversationMessage(Form dialog, string thread, string text)
        {
            string argument = "{\"thread_id\":" + Json.Escape(thread) + ",\"text\":" + (text == null ? "null" : Json.Escape(text)) + "}";
            CallAsync("conversation-message", argument, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    return;
                }
                bool set = Equals(Get(Map(reply, "result"), "set"), true);
                var chosen = Selected(pendingList);
                pendingNoteFor = chosen == null ? null : Str(chosen, "interruption_id");
                pendingNoteText = set ? S("conversation.set", "This conversation has a message of its own now.")
                                      : S("conversation.removed", "This conversation uses the message style in Settings again.");
                ShowPendingNote();
                if (!dialog.IsDisposed) dialog.Close();
                RefreshAfterChange();
            });
        }

        // The last conversation dialog's text box, for LayoutAudit.
        private SoftTextArea conversationArea;

        // ------------------------------------------------------------ words for this time (v0.6.16-beta.3)
        /// Whether a row has words for this time, as the listing says: that it has them, never what they say.
        internal static bool HasOnceWords(Dictionary<string, object> row)
        {
            return row != null && Equals(Get(row, "once_words"), true);
        }

        /// Whether words for this time can be added to, or changed on, a row: a waiting task that is not cancelled -
        /// the tasks Postpone is offered for - and never a made-up one.
        internal static bool CanAddOnceWords(Dictionary<string, object> row, bool idle)
        {
            return CanPostpone(row, idle) && !IsDemo(row);
        }

        /// Opens the dialog for the words of exactly the task the menu was opened on, with the words it has now, which
        /// only the bridge reads (the listing says only that there are some).
        private void EditOnceWords(Dictionary<string, object> row)
        {
            if (row == null || IsDemo(row) || Str(row, "interruption_id") == null || Str(row, "thread_id") == null) return;
            string argument = "{\"interruption_id\":" + Json.Escape(Str(row, "interruption_id")) + "}";
            CallAsync("once-words", argument, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    return;
                }
                using (Form dialog = BuildOnceWords(row, Str(Map(reply, "result"), "text")))
                    dialog.ShowDialog(this);
            });
        }

        /// The dialog for one waiting task's words for this time, built and not shown: the words, sent once after the
        /// usual continuation exactly as written, their count, the Custom message's refusal, the Preview of the next
        /// continuation with them, and Save and Cancel.
        private Form BuildOnceWords(Dictionary<string, object> row, string current)
        {
            var dialog = new Form();
            dialog.Text = S("once.title", "Words for this time") + " - " + Conversation(row);
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.MinimizeBox = false;
            dialog.MaximizeBox = false;
            dialog.ShowInTaskbar = false;
            dialog.ShowIcon = false;
            dialog.ClientSize = new Size(Px(600), Px(520));

            var body = new SoftStack();
            body.Dock = DockStyle.Fill;
            body.ColumnCount = 1;
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            body.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            body.Padding = Pad(16, 16, 16, 0);
            body.BackColor = Canvas;
            var help = Value(S("once.help",
                "Sent once, after the usual continuation message, the next time this task is continued. They start, speed up or skip nothing, and are deleted once they are sent or when the task ends without a send. Written only here, and sent exactly as you write them."));
            help.ForeColor = Secondary;
            help.MaximumSize = new Size(Px(560), 0);
            body.Controls.Add(help);
            var placeholders = Value(S("custom.placeholders", "You can use {reason}, {category}, {attempt}, {max_attempts} and {reset_time}."));
            placeholders.ForeColor = Secondary;
            placeholders.MaximumSize = new Size(Px(560), 0);
            body.Controls.Add(placeholders);

            var area = new SoftTextArea();
            area.Dock = DockStyle.Fill;
            area.Margin = Pad(0, 6, 0, 2);
            area.Font = Font;
            area.Box.Font = Font;
            area.Box.Text = FromStored(current);
            area.Box.AccessibleName = S("once.title", "Words for this time");
            area.Height = Px(140);
            body.Controls.Add(area);
            // Their length as the settings layer counts a Custom message's, against the same 2000.
            Label count = CountLabel();
            area.Box.TextChanged += delegate { UpdateCount(area, count); };
            UpdateCount(area, count);
            body.Controls.Add(count);

            var refusal = Value("");
            refusal.ForeColor = Palette.Danger;
            refusal.MaximumSize = new Size(Px(560), 0);
            body.Controls.Add(refusal);
            body.Controls.Add(Caption(S("preview.title", "Preview")));
            var preview = new SoftQuote();
            preview.Dock = DockStyle.Fill;
            preview.Font = Font;
            preview.Margin = Pad(0, 2, 0, 2);
            preview.AccessibleName = S("preview.title", "Preview");
            body.Controls.Add(preview);
            dialog.Controls.Add(body);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(0, 12, 16, 16);
            Button save = MakeButton(S("action.save", "Save"), true, delegate
            {
                string text = (area.Box.Text ?? "").Replace("\r\n", "\n");
                SaveOnceWords(dialog, row, text.Trim().Length == 0 ? null : text);
            });
            Button cancel = MakeButton(S("action.cancel", "Cancel"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(save);
            buttons.Controls.Add(cancel);
            dialog.Controls.Add(buttons);
            dialog.CancelButton = cancel;
            dialog.ActiveControl = area.Box;

            // The next continuation of this task with the words after it, as the watcher would build it
            // (control/preview.py): asked a moment after the typing stops, from a worker the bridge counts while it
            // runs (PersistentBridge.Queue), and never saved.
            var wait = new Timer();
            wait.Interval = 400;
            int token = 0;
            string category = Str(row, "category") ?? "usage_limit";
            string thread = Str(row, "thread_id");
            EventHandler ask = delegate
            {
                wait.Stop();
                int mine = ++token;
                string text = (area.Box.Text ?? "").Replace("\r\n", "\n");
                string argument = "{\"category\":" + Json.Escape(category) + ",\"thread_id\":" + Json.Escape(thread) +
                                  ",\"once_words\":" + (text.Trim().Length == 0 ? "null" : Json.Escape(text)) + "}";
                bridge.Queue(delegate
                {
                    Dictionary<string, object> reply = null;
                    try { reply = bridge.Call("preview-continuation", argument); }
                    catch (Exception) { reply = null; }
                    MethodInvoker apply = delegate
                    {
                        if (mine != token || dialog.IsDisposed) return;
                        var result = Ok(reply) ? Map(reply, "result") : null;
                        preview.Quote = result == null ? S("preview.unavailable", "Preview is not available right now.")
                                                       : Str(result, "text") ?? "";
                        refusal.Text = result == null ? "" : RefusalText(result);
                    };
                    try { if (dialog.IsHandleCreated && !dialog.IsDisposed) dialog.BeginInvoke(apply); }
                    catch (Exception) { }
                });
            };
            wait.Tick += ask;
            area.Box.TextChanged += delegate { wait.Stop(); wait.Start(); };
            dialog.Shown += delegate { ask(null, EventArgs.Empty); };
            dialog.FormClosed += delegate { wait.Stop(); wait.Dispose(); };
            dialog.KeyPreview = true;
            dialog.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Escape) { e.Handled = true; dialog.Close(); }
            };
            onceWordsArea = area;
            return dialog;
        }

        /// Saves (or, for null, takes away) the words of exactly the task the menu was opened on, and closes the dialog
        /// once they are stored. Nothing is sent, and nothing is checked sooner because of them.
        private void SaveOnceWords(Form dialog, Dictionary<string, object> row, string text)
        {
            string key = Str(row, "interruption_id");
            string argument = "{\"interruption_id\":" + Json.Escape(key) + ",\"thread_id\":" + Json.Escape(Str(row, "thread_id")) +
                              ",\"text\":" + (text == null ? "null" : Json.Escape(text)) + "}";
            CallAsync("once-words", argument, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    if (dialog == null) RefreshAfterChange();
                    return;
                }
                bool set = Equals(Get(Map(reply, "result"), "set"), true);
                pendingNoteFor = key;
                pendingNoteText = set ? S("once.set", "Words for this time are added to this task's next continuation.")
                                      : S("once.removed", "This task's next continuation is sent without words of yours.");
                ShowPendingNote();
                if (dialog != null && !dialog.IsDisposed) dialog.Close();
                RefreshAfterChange();
            });
        }

        // The last words-for-this-time dialog's text box, for LayoutAudit.
        private SoftTextArea onceWordsArea;

        /// v0.6.16-beta.3: under a task's checks, that words for this time go with its next continuation - never the words.
        private static string WithOnceWords(Dictionary<string, object> row, string note, string said)
        {
            if (!HasOnceWords(row)) return note;
            return string.IsNullOrEmpty(note) ? said : note + "\n" + said;
        }

        // ------------------------------------------------------------------- the log, searched
        private void OpenLogSearch()
        {
            using (Form dialog = BuildLogs()) dialog.ShowDialog(this);
        }

        /// The Log dialog, built and not shown: a search box, the lines of this product's own log that hold it -
        /// every line for none, newest last - and how many that is. It looks again every five seconds while it is
        /// open, so a line the watcher writes appears; the log is read by the bridge (control/tools.py), never here.
        private Form BuildLogs()
        {
            var dialog = new Form();
            dialog.Text = S("logs.title", "Log");
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.ClientSize = new Size(Px(760), Px(500));
            dialog.MinimizeBox = false;
            dialog.ShowInTaskbar = false;
            // The product's icon in the title bar, as the window has it: without one Windows draws its
            // default form icon there (owner, 2026-10-10).
            dialog.Icon = Icon;

            var top = new SoftStack();
            top.Dock = DockStyle.Top;
            top.AutoSize = true;
            top.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            top.ColumnCount = 2;
            top.RowCount = 1;
            top.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            top.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            top.Padding = Pad(16, 12, 17, 0);
            top.BackColor = Canvas;
            var query = new SoftTextArea();
            query.Dock = DockStyle.Fill;
            query.Font = Font;
            query.Box.Font = Font;
            query.OneLine = true;               // issue #34: the line centred, never cut off
            query.Box.MaxLength = 100;
            query.Box.AccessibleName = S("logs.search", "Search");
            query.Height = Px(Brand.ButtonHeight);
            query.Margin = Pad(0, 0, 0, 0);
            top.Controls.Add(query, 0, 0);
            Button search = MakeButton(S("logs.search", "Search"), true, null);
            top.Controls.Add(search, 1, 0);

            var view = List(S("logs.title", "Log"),
                            Col(S("logs.col_time", "Time"), 150),
                            Col(S("logs.col_entry", "Entry"), 560));
            // On History's card, on the soft scroll bar, as the lists in the window are (DialogListCard).
            Control listGround = DialogListCard(view);

            var footer = new SoftStack();
            footer.Dock = DockStyle.Bottom;
            footer.AutoSize = true;
            footer.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            footer.ColumnCount = 1;
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            footer.Padding = Pad(16, 0, 17, 0);
            footer.BackColor = Canvas;
            var count = Value("");
            footer.Controls.Add(count);
            var note = Value(S("logs.note", "The log holds reason codes, ids and times - never a prompt, a reply or an error's text."));
            note.ForeColor = Secondary;
            note.MaximumSize = new Size(Px(720), 0);
            footer.Controls.Add(note);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(16, 8, 17, 12);
            var close = MakeButton(S("action.close", "Close"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(close);

            dialog.Controls.Add(listGround);
            dialog.Controls.Add(top);
            dialog.Controls.Add(footer);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = search;
            dialog.CancelButton = close;

            int token = 0;
            // v0.6.18: how many looks are on their way. The five-second look waits while one is, so a slow bridge does
            // not gather a worker behind its lock every five seconds; a search goes as ever, and the token drops the
            // older answer.
            int looking = 0;
            // `lookingAgain`: the five-second look, which keeps the list where the person left it (ShowLogLines); a
            // search, or the first look, shows the newest line.
            Action<bool> look = delegate(bool lookingAgain)
            {
                if (lookingAgain && looking > 0) return;
                looking++;
                int mine = ++token;
                string argument = "{\"query\":" + Json.Escape(query.Box.Text ?? "") + "}";
                System.Threading.ThreadPool.QueueUserWorkItem(delegate
                {
                    Dictionary<string, object> reply = null;
                    try { reply = bridge.Call("logs", argument); }
                    catch (Exception) { reply = null; }
                    MethodInvoker apply = delegate
                    {
                        looking = Math.Max(0, looking - 1);
                        if (mine != token || dialog.IsDisposed) return;
                        ShowLogLines(view, count, Ok(reply) ? Map(reply, "result") : null, lookingAgain);
                    };
                    // A dialog closed meanwhile looks no more, so what is left on its way is not counted.
                    try { if (dialog.IsHandleCreated && !dialog.IsDisposed) dialog.BeginInvoke(apply); }
                    catch (Exception) { }
                });
            };
            search.Click += delegate { look(false); };
            var again = new Timer();
            again.Interval = 5000;
            again.Tick += delegate { look(true); };
            dialog.Shown += delegate { look(false); again.Start(); query.Box.Focus(); };
            dialog.FormClosed += delegate { again.Stop(); again.Dispose(); };
            logsList = view;
            return dialog;
        }

        /// One answer of the log search in the list, newest last, and how many lines it is. A search, or the first
        /// look, shows the newest line. The five-second look (`lookingAgain`) keeps the list where the person left it:
        /// the same lines again leave it untouched, scrolled and selected as it was; new lines keep what was selected and
        /// the line at the top, and follow the newest only while the newest was in view.
        private void ShowLogLines(ListView view, Label count, Dictionary<string, object> result, bool lookingAgain)
        {
            count.Text = LogCount(result, S("logs.shown", "{shown} of {matched} matching lines, newest last"),
                                  S("logs.none", "No line matches."), S("preview.unavailable", "Preview is not available right now."));
            var rows = new List<string[]>();
            var said = new StringBuilder();
            foreach (object entry in Items(result, "lines") ?? new List<object>())
            {
                var line = entry as Dictionary<string, object>;
                if (line == null) continue;
                var row = new[] { Str(line, "at") ?? "", Str(line, "text") ?? "" };
                rows.Add(row);
                said.Append(LogKey(row[0], row[1])).Append('\n');
            }
            string shown = said.ToString();
            if (lookingAgain && shown == view.Tag as string) return;
            string top = null;
            var selected = new HashSet<string>();
            bool newest = true;
            if (lookingAgain && view.Items.Count > 0)
            {
                newest = LastInView(view);
                if (view.TopItem != null) top = LogKey(view.TopItem);
                foreach (ListViewItem item in view.SelectedItems) selected.Add(LogKey(item));
            }
            view.BeginUpdate();
            view.Items.Clear();
            ListViewItem keep = null;
            foreach (string[] row in rows)
            {
                var item = new ListViewItem(row[0]);
                item.SubItems.Add(row[1]);
                view.Items.Add(item);
                string key = LogKey(row[0], row[1]);
                if (selected.Contains(key)) item.Selected = true;
                if (keep == null && key == top) keep = item;
            }
            view.EndUpdate();
            view.Tag = shown;
            MeasureCells(view);
            if (view.Items.Count == 0) return;
            if (newest || keep == null)
            {
                view.EnsureVisible(view.Items.Count - 1);
                return;
            }
            try { view.TopItem = keep; }
            catch (Exception) { view.EnsureVisible(keep.Index); }
        }

        /// A line of the log as the list tells it from the others: its time and its text.
        private static string LogKey(string at, string text)
        {
            return at + "\u001f" + text;
        }

        private static string LogKey(ListViewItem item)
        {
            return LogKey(item.Text, item.SubItems.Count > 1 ? item.SubItems[1].Text : "");
        }

        /// Whether the list's newest line was in view, the whole of it, as the person left the list.
        private static bool LastInView(ListView view)
        {
            try
            {
                if (!view.IsHandleCreated || view.Items.Count == 0) return true;
                Rectangle last = view.GetItemRect(view.Items.Count - 1);
                return last.Top >= 0 && last.Bottom <= view.ClientSize.Height;
            }
            catch (Exception)
            {
                return true;
            }
        }

        /// What the count under the log says: how many lines are shown of how many matched, that none did, or -
        /// for an answer that could not be had - `unavailable`.
        internal static string LogCount(Dictionary<string, object> result, string shown, string none, string unavailable)
        {
            if (result == null) return unavailable;
            var lines = Items(result, "lines");
            int matched = (int)Number(result, "matched");
            if (matched == 0) return none;
            return shown.Replace("{shown}", (lines == null ? 0 : lines.Count).ToString(CultureInfo.CurrentCulture))
                        .Replace("{matched}", matched.ToString(CultureInfo.CurrentCulture));
        }

        // The last Log dialog's list, for LayoutAudit.
        private ListView logsList;

        // ------------------------------------------------- why a failure was not taken up (v0.6.16-beta.3)
        private void OpenDetectionCheck()
        {
            using (Form dialog = BuildDetectionCheck()) dialog.ShowDialog(this);
        }

        /// The check's dialog, built and not shown: what the bridge's `detection-check` says (checkup.py) - the
        /// watcher's own decisions asked on the spot, read only, in the Interface language, the most likely reason
        /// first - in a read-only well, with Copy and Close. Asked once, when the dialog opens.
        private Form BuildDetectionCheck()
        {
            var dialog = new Form();
            dialog.Text = S("check.title", "Why a failure was not taken up");
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.ClientSize = new Size(Px(760), Px(520));
            dialog.MinimizeBox = false;
            dialog.ShowInTaskbar = false;
            dialog.Icon = Icon;

            var well = new SoftTextArea();
            well.Dock = DockStyle.Fill;
            well.Font = Font;
            well.Box.Font = Font;
            well.Box.ReadOnly = true;
            well.Box.WordWrap = true;
            well.Box.Text = S("check.running", "Checking...");
            well.Box.AccessibleName = S("check.title", "Why a failure was not taken up");
            var padding = new Panel();
            padding.BackColor = Canvas;
            padding.Dock = DockStyle.Fill;
            padding.Padding = Pad(12, 12, 12, 0);
            padding.Controls.Add(well);

            var footer = new SoftStack();
            footer.Dock = DockStyle.Bottom;
            footer.AutoSize = true;
            footer.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            footer.ColumnCount = 1;
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            footer.Padding = Pad(12, 8, 12, 0);
            footer.BackColor = Canvas;
            var note = Value(S("check.note", "Read only. No conversation's words are read, and conversations are shown as aliases that are valid only in this result. Copy it into an issue if you are asked for it."));
            note.ForeColor = Secondary;
            note.MaximumSize = new Size(Px(720), 0);
            footer.Controls.Add(note);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(12, 8, 12, 12);
            var close = MakeButton(S("action.close", "Close"), false, delegate { dialog.Close(); });
            Button copy = MakeButton(S("check.copy", "Copy"), true, null);
            copy.Enabled = false;
            copy.Click += delegate
            {
                try
                {
                    Clipboard.SetText(well.Box.Text ?? "");
                    copy.Text = S("check.copied", "Copied.");
                }
                catch (Exception) { }
            };
            buttons.Controls.Add(close);
            buttons.Controls.Add(copy);

            dialog.Controls.Add(padding);
            dialog.Controls.Add(footer);
            dialog.Controls.Add(buttons);
            dialog.CancelButton = close;

            dialog.Shown += delegate
            {
                well.Box.Select(0, 0);
                System.Threading.ThreadPool.QueueUserWorkItem(delegate
                {
                    Dictionary<string, object> reply = null;
                    try { reply = bridge.Call("detection-check", null); }
                    catch (Exception) { reply = null; }
                    MethodInvoker apply = delegate
                    {
                        if (dialog.IsDisposed) return;
                        string text = DetectionCheckText(Ok(reply) ? Map(reply, "result") : null,
                                                         S("check.unavailable", "The check could not be run right now."));
                        well.Box.Text = text;
                        well.Box.Select(0, 0);
                        copy.Enabled = Ok(reply);
                    };
                    try { if (dialog.IsHandleCreated && !dialog.IsDisposed) dialog.BeginInvoke(apply); }
                    catch (Exception) { }
                });
            };
            detectionWell = well;
            return dialog;
        }

        /// The check's answer as the well shows it and Copy copies it: its lines, one under another, or - for an
        /// answer that could not be had - `unavailable`.
        internal static string DetectionCheckText(Dictionary<string, object> result, string unavailable)
        {
            var lines = Items(result, "lines");
            if (result == null || lines == null) return unavailable;
            var said = new StringBuilder();
            foreach (object line in lines)
            {
                if (said.Length > 0) said.Append("\r\n");
                said.Append(line as string ?? "");
            }
            return said.ToString();
        }

        // The last check dialog's well, for LayoutAudit.
        private SoftTextArea detectionWell;

        // --------------------------------------------------------- who may open the state folder
        /// Asked with the compatibility view, as the plugin's copy is (LoadPluginCopy): one word, and a sentence
        /// under the Health facts only while other accounts can open the folder.
        private void LoadStateAccess()
        {
            if (diagStateAccess == null) return;
            bridge.Queue(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call("state-access", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate { ApplyStateAccess(Ok(reply) ? Str(Map(reply, "result"), "access") : null); };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { }
            });
        }

        /// The bridge's word for the state folder under Health, and - only while other accounts can open it - what that
        /// means, under the facts. LayoutAudit hands it the longest, "shared". Codex's sandbox group reading the folder
        /// (v0.6.17, win/acl.py) is said on the line itself, naming the group, and is no warning.
        private void ApplyStateAccess(string word)
        {
            if (diagStateAccess == null) return;
            string[] said = StateAccessSaid(word, S("diag.state_access.owner_only", "only your account can open it"),
                S("diag.state_access.shared", "other accounts on this PC can open it"),
                S("diag.state_access.codex_sandbox", "your account; Codex's sandbox (CodexSandboxUsers) can read it - Codex added that"),
                S("diag.state_access.unknown", "not checked"),
                S("diag.state_shared_note", "Other accounts on this PC can open the folder that holds this product's settings, pending tasks and logs. They hold no prompts or replies, but they do hold your conversations' ids. To keep them to yourself, remove the other accounts' access in the folder's Properties > Security > Advanced."));
            diagStateAccess.Text = said[0];
            diagStateNote.Text = said[1];
        }

        /// The line under Health and the sentence under the facts for the bridge's word: the sentence only for "shared".
        /// Pure, for the tests.
        internal static string[] StateAccessSaid(string word, string ownerOnly, string shared, string codexSandbox,
                                                 string unknown, string sharedNote)
        {
            string access = StateAccessWord(word);
            string line = access == "owner_only" ? ownerOnly : access == "shared" ? shared
                        : access == "codex_sandbox" ? codexSandbox : unknown;
            return new[] { line, access == "shared" ? sharedNote : "" };
        }

        /// The bridge's word for the state folder, read as one of the four there are: anything else is unknown.
        internal static string StateAccessWord(string access)
        {
            return access == "owner_only" || access == "shared" || access == "codex_sandbox" ? access : "unknown";
        }

        // --------------------------------------------------------- inside another app
        /// Asked with the state folder (LoadStateAccess): whether the watcher and this window's bridge run inside another
        /// app's private view - an MSIX app such as the Codex app or Claude desktop - and which.
        private void LoadHostApp()
        {
            if (diagHostApp == null) return;
            bridge.Queue(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call("host-app", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate { ApplyHostApp(Ok(reply) ? Map(reply, "result") : null); };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { }
            });
        }

        /// The bridge's answer under Health - one line - and, only while the watcher or this window runs inside another
        /// app, what that means and what to do, under the facts. LayoutAudit hands it the longest: both inside, apart.
        private void ApplyHostApp(Dictionary<string, object> result)
        {
            if (diagHostApp == null) return;
            string[] said = HostAppLines(result, S("diag.no", "no"), S("diag.unknown", "unknown"),
                S("diag.host_app.watcher", "the watcher runs inside {app}"),
                S("diag.host_app.window", "this window runs inside {app}"),
                S("diag.host_app.both", "the watcher and this window run inside {app}"),
                S("diag.host_app.another", "another app"),
                S("diag.host_app_note", "Windows keeps what runs inside {app} in that app's private view, so what is set up from there - starting at sign-in, the entry in Settings > Apps, notifications - stays in that view, and the watcher may stop when that app closes. Stop the watcher, then open Codex Auto Resume from the Start menu and start it there."));
            diagHostApp.Text = said[0];
            diagHostNote.Text = said[1];
        }

        /// The line under Health and the sentence under the facts for a `host-app` answer. Outside is `no`, and says
        /// nothing under the facts; a part not known - Windows would not say, or the watcher's process id is another
        /// process's now - is `unknown`, unless the other part is inside. Pure, for the tests.
        internal static string[] HostAppLines(Dictionary<string, object> result, string no, string unknown, string watcherInside,
                                              string windowInside, string bothInside, string another, string note)
        {
            Dictionary<string, object> watcherPart = Map(result, "watcher"), windowPart = Map(result, "bridge");
            string watcherState = Str(watcherPart, "state"), windowState = Str(windowPart, "state");
            string watcherApp = HostAppName(watcherPart, another), windowApp = HostAppName(windowPart, another);
            bool watcherIn = watcherState == "inside", windowIn = windowState == "inside";
            if (!watcherIn && !windowIn)
            {
                bool known = (watcherState == "outside" || watcherState == "not_running") && windowState == "outside";
                return new[] { known ? no : unknown, "" };
            }
            string line = watcherIn && windowIn && watcherApp == windowApp ? bothInside.Replace("{app}", watcherApp)
                        : watcherIn && windowIn ? watcherInside.Replace("{app}", watcherApp) + Environment.NewLine
                                                  + windowInside.Replace("{app}", windowApp)
                        : watcherIn ? watcherInside.Replace("{app}", watcherApp)
                        : windowInside.Replace("{app}", windowApp);
            return new[] { line, note.Replace("{app}", watcherIn ? watcherApp : windowApp) };
        }

        /// The app's name for a person as the bridge gives it, or `another` where it gives none.
        private static string HostAppName(Dictionary<string, object> hostPart, string another)
        {
            string app = Str(hostPart, "app");
            return string.IsNullOrEmpty(app) ? another : app;
        }

        // ------------------------------------------------------------------ Show me what happens
        // The demo's made-up rows (demo.py), held in this window only: the task on Pending until its countdown
        // ends, and then its entry in History for as long again. Nothing reads them but the two lists.
        private Dictionary<string, object> demoPending, demoHistory;
        private double demoUntil, demoGoneAt;

        /// Whether a row is Show me what happens' made-up one, on which no action is offered.
        internal static bool IsDemo(Dictionary<string, object> made)
        {
            return Equals(Get(made, "demo"), true);
        }

        /// `rows` with the made-up row added - first, for History, which is newest first - or as they are.
        internal static List<object> WithDemo(List<object> rows, Dictionary<string, object> demo, bool first)
        {
            if (demo == null) return rows;
            var shown = new List<object>();
            if (first) shown.Add(demo);
            if (rows != null) shown.AddRange(rows);
            if (!first) shown.Add(demo);
            return shown;
        }

        /// The button: the watcher's icon is asked for a made-up card, and this window plays the made-up task.
        private void StartDemo()
        {
            CallAsync("demo", null, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    return;
                }
                var result = Map(reply, "result");
                var pending = Map(result, "pending");
                var history = Map(result, "history");
                if (pending == null || history == null) return;
                string name = S("demo.conversation", "Example conversation (demo)");
                pending["name"] = name;
                history["name"] = name;
                double seconds = Math.Max(1, Number(result, "seconds"));
                // The countdown on this window's clock, which is the clock the row counts down by.
                double now = Now();
                pending["eligible_at"] = now + seconds;
                history["outcome_at"] = now + seconds;
                demoPending = pending;
                demoHistory = null;
                demoFinished = history;
                demoUntil = now + seconds;
                demoGoneAt = now + 2 * seconds;
                pendingNoteFor = Str(pending, "interruption_id");
                pendingNoteText = S("demo.started", "Demo: a made-up task waits on Pending for a minute, then shows in History. Nothing is sent.") +
                                  (Equals(Get(result, "asked"), true) ? ""
                                   : " " + S("demo.no_card", "The watcher is not running, so there is no demo card. The rest of the demo still plays."));
                if (snapshot != null) ApplySnapshot(snapshot);
                ShowPage("pending");
                SelectRow(pendingList, pendingNoteFor);
                ShowPendingNote();
            });
        }

        // The made-up History entry, waiting for the countdown to end.
        private Dictionary<string, object> demoFinished;

        /// Every second: the made-up task leaves Pending when its countdown ends and its entry shows in History -
        /// where the person is taken if they are still on Pending - and that entry goes a while later.
        private void DemoTick(double now)
        {
            bool changed = false;
            if (demoPending != null && now >= demoUntil)
            {
                demoPending = null;
                demoHistory = demoFinished;
                demoFinished = null;
                changed = true;
                if (currentPage == "pending" && snapshot != null)
                {
                    ApplySnapshot(snapshot);
                    ShowPage("history");
                    SelectRow(historyList, Str(demoHistory, "interruption_id"));
                    changed = false;
                }
            }
            else if (demoHistory != null && now >= demoGoneAt)
            {
                demoHistory = null;
                changed = true;
            }
            if (changed && snapshot != null) ApplySnapshot(snapshot);
        }

        /// Chooses the row of `interruptionId` in `list`, if it is there.
        private static void SelectRow(ListView list, string interruptionId)
        {
            if (list == null || interruptionId == null) return;
            foreach (ListViewItem item in list.Items)
                if (Str(item.Tag as Dictionary<string, object>, "interruption_id") == interruptionId)
                {
                    item.Selected = true;
                    item.Focused = true;
                    item.EnsureVisible();
                    return;
                }
        }
    }
}

// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - Find a conversation (v0.6.20, issue #50).
//
// The pickers of a conversation - the scheduled-message editor's and the reset-message rule's - offer the conversations
// Pending and History list (Conversations, AdvancedResets.cs). Beside each, Find a conversation... opens a small dialog in
// the window's own material (the window's dialogs' frame: the canvas, the soft title bar, flat hairline rows, Use this
// conversation as the accent button and Cancel) that asks the bridge once, advanced-conversations, for the person's own
// conversations with their names - newest first, at most 200, none the person switched off - and shows them in a list
// under a search box. Typing in the box keeps the conversations whose name holds what was typed, whatever the case; Use this
// conversation (or a double click on a row) puts the chosen one into the picker, and it stays offered in the pickers for as
// long as the window lives (foundPicked), so a message to it names it. The pickers' own conversations stay first.
//
// It reads names and ids and nothing a conversation says, sends nothing and changes nothing; the picker's own Save or Add is
// what asks the bridge to do anything, as ever.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // The conversations a person chose by searching, {thread id: name}, for the life of the window: Conversations offers
        // them after Pending's and History's, and ConversationOf names a message to one.
        private readonly Dictionary<string, string> foundPicked = new Dictionary<string, string>();
        // The open dialog's parts, as it was built - null while none is - and what it was last handed.
        private Form findDialog;
        private SoftTextArea findSearch;
        private ListView findList;
        private Label findSaid;
        private Button findUse, findCancel;
        private List<KeyValuePair<string, string>> findRows = new List<KeyValuePair<string, string>>();
        private bool findFailed;
        private string findTaken, findTakenName;
        // The buttons beside the pickers: the reset-message form's, and the editor's.
        private Button resetFind, editorFind;
        // Null in every window a person opens. In a window AdvancedPageRun drives: what answers the dialog, never shown.
        private Action<Form> findAnswer;

        /// The dialog, shown over `owner` (the editor, or this window); a conversation chosen is put into `combo` and offered
        /// there, `after` told so the picker's own state follows (its Add or Save may now be allowed).
        private void FindConversation(Form owner, SoftCombo combo, Action after)
        {
            if (combo == null || combo.IsDisposed || advancedListing == null) return;
            string thread = null, name = null;
            using (Form dialog = BuildFind())
            {
                AdvancedCall("advanced-conversations", "{}", false, delegate(Dictionary<string, object> reply)
                {
                    if (dialog.IsDisposed || dialog != findDialog) return;
                    FoundRead(AdvancedResult(reply));
                });
                if (findAnswer != null) findAnswer(dialog);
                else if (!auditing) dialog.ShowDialog(owner);
                thread = findTaken;
                name = findTakenName;
            }
            ForgetFind();
            if (thread == null || combo.IsDisposed) return;
            foundPicked[thread] = name;
            string label;
            if (!Conversations().TryGetValue(thread, out label)) label = name;
            int at = -1;
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var choice = combo.Items[i] as Choice;
                if (choice != null && choice.Value == thread) at = i;
            }
            if (at < 0)
            {
                combo.Items.Add(new Choice(thread, label));
                at = combo.Items.Count - 1;
            }
            combo.SelectedIndex = at;
            if (after != null) after();
        }

        private void ForgetFind()
        {
            findDialog = null;
            findSearch = null;
            findList = null;
            findSaid = null;
            findUse = findCancel = null;
            findRows = new List<KeyValuePair<string, string>>();
            findFailed = false;
            findTaken = findTakenName = null;
        }

        /// The dialog, built and not shown: a search box, an empty list and Use this conversation greyed until one is chosen.
        private Form BuildFind()
        {
            ForgetFind();
            var dialog = new Form();
            dialog.Text = Word("page.find.title", "Find a conversation");
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
            // As wide and tall as it was drawn for, or what the screen it opens on holds (a small screen at a large scaling):
            // what is inside takes its width from the dialog, so nothing is cut off at either edge.
            Rectangle area = Screen.GetWorkingArea(this);
            int across = Math.Max(240, Math.Min(520, (area.Width - Px(32)) * 520 / Px(520)));
            int tall = Math.Max(Px(240), Math.Min(Px(440), Math.Min(area.Height, SystemInformation.MaxWindowTrackSize.Height) - Px(96)));
            dialog.ClientSize = new Size(Px(across), tall);

            var top = new SoftStack();
            top.Dock = DockStyle.Top;
            top.AutoSize = true;
            top.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            top.ColumnCount = 1;
            top.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            top.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            top.Padding = Pad(16, 16, 16, 0);
            top.BackColor = Canvas;
            findSearch = OneLine(Word("page.find.search", "Search by name"), across - 32, 72);
            findSearch.Dock = DockStyle.Fill;
            findSearch.Margin = Pad(0, 0, 0, 4);
            top.Controls.Add(findSearch);
            findSaid = Value("");
            findSaid.ForeColor = Secondary;
            findSaid.MaximumSize = new Size(Px(across - 32), 0);
            findSaid.Visible = false;
            top.Controls.Add(findSaid);

            // Flat hairline rows, owner-drawn as every list here is (DrawCell): one column, the conversation's name.
            string column = Word("page.resets.field.conversation", "Conversation");
            findList = List(Word("page.find.title", "Find a conversation"), Col(column, across - 32));
            // On History's card, on the soft scroll bar, as the lists in the window are (DialogListCard).
            Control listGround = DialogListCard(findList);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(0, 0, 16, 16);
            findUse = MakeButton(Word("page.find.use", "Use this conversation"), true, delegate { UseFound(dialog); });
            findUse.Enabled = false;
            findCancel = MakeButton(S("action.cancel", "Cancel"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(findUse);
            buttons.Controls.Add(findCancel);

            dialog.Controls.Add(listGround);
            dialog.Controls.Add(top);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = findUse;
            dialog.CancelButton = findCancel;
            dialog.ActiveControl = findSearch.Box;
            findSearch.Box.TextChanged += delegate { ShowFound(); };
            findList.SelectedIndexChanged += delegate { FoundChosen(); };
            findList.DoubleClick += delegate { UseFound(dialog); };
            findDialog = dialog;
            return dialog;
        }

        /// The bridge's answer kept: every conversation with its name, in the order read - or, where it did not answer, none
        /// and a line saying so.
        private void FoundRead(Dictionary<string, object> result)
        {
            findRows = new List<KeyValuePair<string, string>>();
            findFailed = !AdvancedDone(result);
            if (!findFailed)
                foreach (object entry in Items(result, "conversations") ?? new List<object>())
                {
                    var row = entry as Dictionary<string, object>;
                    string thread = Str(row, "thread_id"), name = Str(row, "name");
                    if (thread != null && name != null && name.Length > 0)
                        findRows.Add(new KeyValuePair<string, string>(thread, name));
                }
            ShowFound();
        }

        /// The list as the search box filters it: the conversations whose name holds what was typed, in any case.
        private void ShowFound()
        {
            if (findList == null || findList.IsDisposed || findSearch == null) return;
            string needle = (findSearch.Box.Text ?? "").Trim();
            // A name two conversations share is told apart by the start of each one's id, as the pickers tell them apart.
            var names = new Dictionary<string, int>();
            foreach (KeyValuePair<string, string> row in findRows)
            {
                int seen;
                names[row.Value] = names.TryGetValue(row.Value, out seen) ? seen + 1 : 1;
            }
            findList.BeginUpdate();
            findList.Items.Clear();
            foreach (KeyValuePair<string, string> row in findRows)
            {
                if (needle.Length > 0 && row.Value.IndexOf(needle, StringComparison.CurrentCultureIgnoreCase) < 0) continue;
                string shown = names[row.Value] > 1 && row.Key.Length >= 8 ? row.Value + " (" + row.Key.Substring(0, 8) + ")" : row.Value;
                var item = new ListViewItem(shown);
                item.Tag = new Dictionary<string, object> { { "thread_id", row.Key }, { "name", row.Value } };
                findList.Items.Add(item);
            }
            findList.EndUpdate();
            MeasureCells(findList);
            findSaid.Text = findFailed ? Word("page.find.failed", "The list of conversations could not be read.")
                          : findList.Items.Count == 0 ? Word("page.find.none", "No conversation matches.") : "";
            findSaid.Visible = findSaid.Text.Length > 0;
            FoundChosen();
        }

        private void FoundChosen()
        {
            if (findUse != null && findList != null) findUse.Enabled = findList.SelectedItems.Count > 0;
        }

        /// Use this conversation: the chosen row kept for FindConversation, the dialog closed with OK.
        private void UseFound(Form dialog)
        {
            if (findList == null || findList.SelectedItems.Count == 0) return;
            var row = findList.SelectedItems[0].Tag as Dictionary<string, object>;
            if (row == null) return;
            findTaken = Str(row, "thread_id");
            findTakenName = Str(row, "name");
            dialog.DialogResult = DialogResult.OK;
        }
    }
}

// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - a delivered message followed through (v0.6.20, issue #50; promised there on 2026-10-26).
//
// History says a scheduled message was delivered. Chosen there, a delivered message offers Follow through... under History
// (and a double click on its row does the same): a dialog in the window's own material - the Timeline's frame, its rows on
// History's card (DialogListCard), flat hairline rows - that asks the bridge once, advanced-prompt-follow, and shows what
// the work the message started did after: when it was sent and delivered, the limit that cut its turn off and when, the
// reset its recovery waits for, where that recovery stands in History's own words, every further cut-off of the
// recovery's own turn, and how it ended - still running, finished without a cut-off, waiting, recovered or ended.
//
// One line above the rows says how the turn was tied to the message: exactly (its own mark is in that turn in Codex's
// history), by time (the one cut-off that started between its send and its delivery - and that it may not be its turn),
// or not at all and why. Nothing is claimed beyond what the bridge answered.
//
// Part of the prompt queue: offered only while it stands on, for a delivered message (not one handed over to the person).
// It reads and changes nothing, and sends nothing.
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
        // History's Follow through..., shown for a delivered message while the prompt queue stands on.
        private Button followButton;
        // The open dialog's parts, as it was built - null while none is.
        private Form followDialog;
        private Label followSaid;
        private ListView followList;
        private Button followClose;
        // Null in every window a person opens. In a window AdvancedPageRun drives: what answers the dialog, never shown.
        private Action<Form> followAnswer;

        /// History's buttons: Follow through... after Clear history, hidden until a delivered message is chosen; and a double
        /// click on such a row opens the same.
        partial void HistoryButtonsBuilt(FlowLayoutPanel row)
        {
            followButton = MakeButton(Word("page.follow.button", "Follow through..."), false, delegate { FollowChosen(); });
            followButton.Margin = Pad(0, 0, 9, 0);
            followButton.Visible = false;
            row.Controls.Add(followButton);
            if (historyList == null) return;
            historyList.MouseDoubleClick += delegate(object sender, MouseEventArgs e)
            {
                if (e.Button != MouseButtons.Left) return;
                ListViewHitTestInfo hit = historyList.HitTest(e.Location);
                if (hit.Item != null) FollowOpened(hit.Item.Tag as Dictionary<string, object>);
            };
        }

        /// Whether `row` is a History row this dialog follows: a delivered message, while the prompt queue stands on.
        private bool Followable(Dictionary<string, object> row)
        {
            if (Str(row, RowKindKey) != KindDone || Str(Map(row, RowSourceKey), "reason") != "delivered") return false;
            Dictionary<string, object> queue = advancedListing == null ? null : AdvancedItem(PromptQueueId);
            return queue != null && Standing(queue);
        }

        /// Follow through... shown and offered by the chosen History row (HistoryButtonsUpdated, AdvancedSchedule.cs), in the
        /// words the bridge gave.
        private void UpdateFollowButton(Dictionary<string, object> row, bool idle)
        {
            if (followButton == null) return;
            followButton.Text = Word("page.follow.button", "Follow through...");
            bool offered = Followable(row);
            Show(followButton, offered);
            followButton.Enabled = offered && idle;
        }

        private void FollowChosen()
        {
            if (followButton == null || !followButton.Enabled) return;
            FollowOpened(Selected(historyList));
        }

        /// The dialog for the delivered message `row`, the bridge asked once; nothing for any other row.
        private void FollowOpened(Dictionary<string, object> row)
        {
            if (!Followable(row)) return;
            int prompt = Whole(Get(Map(row, RowSourceKey), "prompt_id"));
            using (Form dialog = BuildFollow(ConversationOf(Str(row, "thread_id"))))
            {
                AdvancedCall("advanced-prompt-follow", "{\"prompt\":" + prompt.ToString(CultureInfo.InvariantCulture) + "}", false,
                             delegate(Dictionary<string, object> reply)
                             {
                                 if (dialog.IsDisposed || dialog != followDialog) return;
                                 ShowFollow(AdvancedResult(reply));
                             });
                if (followAnswer != null) followAnswer(dialog);
                else if (!auditing) dialog.ShowDialog(this);
            }
            ForgetFollow();
        }

        private void ForgetFollow()
        {
            followDialog = null;
            followSaid = null;
            followList = null;
            followClose = null;
        }

        /// The dialog, built and not shown: the line that says how it was linked, the rows empty, Close.
        private Form BuildFollow(string conversation)
        {
            ForgetFollow();
            var dialog = new Form();
            dialog.Text = Word("page.follow.title", "Follow-through") + " - " + conversation;
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
            int across = Math.Max(240, Math.Min(600, (area.Width - Px(32)) * 600 / Px(600)));
            int tall = Math.Max(Px(240), Math.Min(Px(460), Math.Min(area.Height, SystemInformation.MaxWindowTrackSize.Height) - Px(96)));
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
            followSaid = Value("");
            followSaid.ForeColor = Secondary;
            followSaid.MaximumSize = new Size(Px(across - 32), 0);
            top.Controls.Add(followSaid);

            // Flat hairline rows, owner-drawn as every list here is: when, and what happened - the Timeline's own columns.
            followList = List(Word("page.follow.title", "Follow-through"),
                              Col(S("timeline.col_time", "Time"), 150), Col(S("timeline.col_event", "Event"), across - 32 - 150));
            // On History's card, on the soft scroll bar, as the lists in the window are (DialogListCard).
            Control listGround = DialogListCard(followList);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(0, 0, 16, 16);
            followClose = MakeButton(S("action.close", "Close"), true, delegate { dialog.Close(); });
            buttons.Controls.Add(followClose);

            dialog.Controls.Add(listGround);
            dialog.Controls.Add(top);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = followClose;
            dialog.CancelButton = followClose;
            followDialog = dialog;
            return dialog;
        }

        /// The bridge's answer shown: how it was linked above, and the rows - or, where it did not answer, a line saying so.
        private void ShowFollow(Dictionary<string, object> result)
        {
            if (followList == null || followList.IsDisposed) return;
            followList.BeginUpdate();
            followList.Items.Clear();
            if (!AdvancedDone(result))
            {
                followSaid.Text = Word("page.follow.failed", "What came of this message could not be read.");
                followList.EndUpdate();
                MeasureCells(followList);
                return;
            }
            string link = Str(result, "link");
            AddFollow(Number(result, "sent_at"), Word("page.follow.sent", "Sent to Codex"));
            AddFollow(Number(result, "delivered_at"), link == "exact"
                ? Word("page.follow.delivered_turn", "Delivered - it started its turn")
                : Word("page.follow.delivered", "Delivered"));
            foreach (object entry in Items(result, "steps") ?? new List<object>())
            {
                var step = entry as Dictionary<string, object>;
                if (step == null) continue;
                AddFollow(Number(step, "detected_at"), Word("page.follow.cut", "Cut off by {limit}").Replace("{limit}", FollowLimit(step)));
                string stage = Str(step, "stage");
                if (stage == "waiting" && Number(step, "reset_at") > 0)
                    AddFollow(Number(step, "reset_at"), Word("page.follow.reset", "Waits for the limit to reset"));
                string code = Str(step, "code") ?? "";
                AddFollow(Number(step, "outcome_at"), Word("page.follow.recovery", "Its recovery: {state}")
                    .Replace("{state}", S("code." + code, code.Replace('_', ' '))));
            }
            AddFollow(0, FollowEnd(Str(result, "end")));
            followList.EndUpdate();
            MeasureCells(followList);
            followSaid.Text = FollowLink(result);
        }

        private void AddFollow(double at, string what)
        {
            var line = new ListViewItem(at > 0 ? When(at) : "");
            line.SubItems.Add(what);
            followList.Items.Add(line);
        }

        /// The limit that cut a turn off, in words: the 5-hour limit, the weekly limit, one of another length - each of them
        /// where Codex named several - or, where none is named, the kind of interruption as History says it.
        private string FollowLimit(Dictionary<string, object> step)
        {
            var named = new List<string>();
            foreach (string part in (Str(step, "limit_type") ?? "").Split(','))
            {
                int minutes;
                if (part.EndsWith("m") && int.TryParse(part.Substring(0, part.Length - 1), NumberStyles.None,
                                                       CultureInfo.InvariantCulture, out minutes) && minutes > 0)
                    named.Add(WindowWord(minutes));
            }
            if (named.Count > 0) return string.Join(", ", named.ToArray());
            string category = Str(step, "category") ?? "";
            return S("reason." + category, S("field.recover_" + category, category.Replace('_', ' ')));
        }

        /// How the work the message started stands at the end, in one sentence.
        private string FollowEnd(string end)
        {
            if (end == "still_running") return Word("page.follow.end.still_running", "Its turn is still running.");
            if (end == "finished") return Word("page.follow.end.finished", "Its turn finished without a cut-off.");
            if (end == "waiting") return Word("page.follow.end.waiting", "The recovery is still waiting.");
            if (end == "recovering") return Word("page.follow.end.recovering", "The recovery is on its way.");
            if (end == "recovered") return Word("page.follow.end.recovered", "Recovered.");
            if (end == "ended") return Word("page.follow.end.ended", "The recovery ended without recovering.");
            return Word("page.follow.end.unknown", "Where its work ended cannot be told.");
        }

        /// How the turn was tied to the message, never more than the bridge said - and, for a series, that this is its last
        /// occurrence.
        private string FollowLink(Dictionary<string, object> result)
        {
            string link = Str(result, "link"), why = Str(result, "why"), said;
            if (link == "exact")
                said = Word("page.follow.link.exact", "Linked exactly: the message's own mark is in this turn in Codex's history.");
            else if (link == "time")
                said = Word("page.follow.link.time", "Linked by time: the message's own mark could not be found, so this is the one cut-off in that conversation whose turn started between its sending and its delivery. It may not be the message's own turn.");
            else if (why == "ambiguous")
                said = Word("page.follow.link.ambiguous", "Not linked: more than one turn could be the message's, so none is followed.");
            else if (why == "no_record")
                said = Word("page.follow.link.no_record", "Not linked: nothing was kept of its sending.");
            else
                said = Word("page.follow.link.not_found", "Not linked: its turn could not be found in Codex's history, and no cut-off started between its sending and its delivery.");
            int occurrences = Whole(Get(result, "occurrences"));
            if (occurrences > 1)
                said += " " + Word("page.follow.series", "This follows its last occurrence, {n} of {of}.", "n", Whole(Get(result, "occurrence")))
                    .Replace("{of}", occurrences.ToString(CultureInfo.CurrentCulture));
            return said;
        }
    }
}

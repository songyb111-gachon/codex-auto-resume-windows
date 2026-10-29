// Codex Auto Resume - v0.6.19's compatibility report from this PC, on Diagnostics: the bridge's `own-report`
// (ownreport/) written from this PC's own records - every Codex version the product's log names, each counted by the
// project's rule as worked, failed, neither or both - shown whole with its SHA-256 in a read-only well, with Copy
// report, Write again and Close. Nothing here sends anything, and nothing is kept: Export diagnostics puts a copy
// written for the file in the file.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private void OpenOwnReport()
        {
            using (Form dialog = BuildOwnReport()) dialog.ShowDialog(this);
        }

        /// The report's words in the Interface language, as OwnReportText takes them.
        private Dictionary<string, string> OwnReportWords()
        {
            var words = new Dictionary<string, string>();
            words["unavailable"] = S("ownreport.unavailable", "The report could not be written right now.");
            words["refused"] = S("ownreport.refused", "No report could be written: {reason}.");
            words["no_state"] = S("ownreport.refusal.no_state", "the watcher has written no records yet");
            words["no_engine_version"] = S("ownreport.refusal.no_engine_version", "no Codex version is named in this product's log yet");
            words["current"] = S("ownreport.current", "Codex in use now: {version}");
            words["row"] = S("ownreport.row", "{version}: {counted} - {records} records, {delivered} delivered");
            words["too_many"] = S("ownreport.too_many", "{version}: more records than a report holds");
            words["left_out"] = S("ownreport.left_out", "Left out: {hidden} hidden with Clear history, {routed} carried another way, {unknown} whose way cannot be told, {unplaced} not placed on one version.");
            words["sha"] = S("ownreport.sha", "SHA-256: {sha}");
            words["worked"] = S("ownreport.worked", "worked");
            words["failed"] = S("ownreport.failed", "failed");
            words["neither"] = S("ownreport.neither", "neither");
            words["both"] = S("ownreport.both", "worked and failed");
            return words;
        }

        /// The report's dialog, built and not shown: what the bridge's `own-report` says, in a read-only well, with Copy
        /// report (the report's own text, so its SHA-256 holds for what is pasted), Write again and Close. Asked when
        /// the dialog opens and on Write again, on the bridge's worker (bridge.Queue).
        private Form BuildOwnReport()
        {
            var dialog = new Form();
            dialog.Text = S("ownreport.title", "Compatibility report from this PC");
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.ClientSize = new Size(Px(760), Px(560));
            dialog.MinimizeBox = false;
            dialog.ShowInTaskbar = false;
            dialog.Icon = Icon;

            var well = new SoftTextArea();
            well.Dock = DockStyle.Fill;
            well.Font = Font;
            well.Box.Font = Font;
            well.Box.ReadOnly = true;
            well.Box.WordWrap = true;
            well.Box.Text = S("ownreport.running", "Writing the report...");
            well.Box.AccessibleName = S("ownreport.title", "Compatibility report from this PC");
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
            var note = Value(S("ownreport.note", "Read only, and sent nowhere. Written from this PC's own records: counts, states and times, with no conversation text, ids, paths or names. Export diagnostics puts a copy written for the file in the file."));
            note.ForeColor = Secondary;
            note.MaximumSize = new Size(Px(720), 0);
            footer.Controls.Add(note);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(12, 8, 12, 12);
            var close = MakeButton(S("action.close", "Close"), false, delegate { dialog.Close(); });
            Button copy = MakeButton(S("ownreport.copy", "Copy report"), true, null);
            Button again = MakeButton(S("ownreport.again", "Write again"), false, null);
            copy.Enabled = false;
            again.Enabled = false;
            string reportText = null;
            copy.Click += delegate
            {
                try
                {
                    Clipboard.SetText(reportText ?? "");
                    copy.Text = S("check.copied", "Copied.");
                }
                catch (Exception) { }
            };
            buttons.Controls.Add(close);
            buttons.Controls.Add(copy);
            buttons.Controls.Add(again);

            dialog.Controls.Add(padding);
            dialog.Controls.Add(footer);
            dialog.Controls.Add(buttons);
            dialog.CancelButton = close;

            Dictionary<string, string> words = OwnReportWords();
            Action ask = delegate
            {
                copy.Enabled = false;
                again.Enabled = false;
                bridge.Queue(delegate
                {
                    Dictionary<string, object> reply;
                    try { reply = bridge.Call("own-report", null); }
                    catch (Exception) { reply = null; }
                    MethodInvoker apply = delegate
                    {
                        if (dialog.IsDisposed) return;
                        Dictionary<string, object> result = Ok(reply) ? Map(reply, "result") : null;
                        well.Box.Text = OwnReportText(result, words);
                        well.Box.Select(0, 0);
                        reportText = Str(result, "text");
                        copy.Text = S("ownreport.copy", "Copy report");
                        copy.Enabled = reportText != null;
                        again.Enabled = true;
                    };
                    try { if (dialog.IsHandleCreated && !dialog.IsDisposed) dialog.BeginInvoke(apply); }
                    catch (Exception) { }
                });
            };
            again.Click += delegate
            {
                well.Box.Text = S("ownreport.running", "Writing the report...");
                ask();
            };
            dialog.Shown += delegate
            {
                well.Box.Select(0, 0);
                ask();
            };
            return dialog;
        }

        /// The well's text for the bridge's answer: the Codex version in use now, one line per version - its count by
        /// the project's rule, its records and how many were delivered - what was left out, the SHA-256, and under them
        /// the report whole. A refusal is said by its reason; no answer is `unavailable`. Pure, for the tests: `words`
        /// holds the sentences OwnReportWords gives, and a word missing from it is said by its key.
        internal static string OwnReportText(Dictionary<string, object> result, Dictionary<string, string> words)
        {
            Func<string, string> w = delegate(string key)
            {
                string found;
                return words != null && words.TryGetValue(key, out found) && found != null ? found : key;
            };
            if (result == null) return w("unavailable");
            string refusal = Str(result, "refusal");
            if (refusal != null)
            {
                string reason = refusal == "no_state" || refusal == "no_engine_version" ? w(refusal) : refusal;
                return w("refused").Replace("{reason}", reason);
            }
            string text = Str(result, "text");
            var versions = Items(result, "versions");
            if (text == null || versions == null) return w("unavailable");
            var said = new StringBuilder();
            said.Append(w("current").Replace("{version}", Mirror.Embed(Str(Map(result, "engine"), "current") ?? "-")));
            foreach (object item in versions)
            {
                var ownVersion = item as Dictionary<string, object>;
                if (ownVersion == null) continue;
                string version = Str(ownVersion, "codex_version") ?? "-";
                said.Append("\r\n");
                if (Str(ownVersion, "refusal") != null)
                {
                    said.Append(w("too_many").Replace("{version}", Mirror.Embed(version)));
                    continue;
                }
                string counted = Equals(Get(ownVersion, "both"), true) ? w("both")
                               : Equals(Get(ownVersion, "worked"), true) ? w("worked")
                               : Equals(Get(ownVersion, "failed"), true) ? w("failed") : w("neither");
                said.Append(w("row").Replace("{version}", Mirror.Embed(version)).Replace("{counted}", counted)
                                    .Replace("{records}", Count(Number(ownVersion, "records")))
                                    .Replace("{delivered}", Count(Number(ownVersion, "delivered"))));
            }
            var ownLeftOut = Map(result, "left_out");
            double unplaced = 0;
            var ownUnplaced = Map(ownLeftOut, "unplaced");
            if (ownUnplaced != null)
                foreach (object value in ownUnplaced.Values) if (value is double) unplaced += (double)value;
            said.Append("\r\n").Append(w("left_out").Replace("{hidden}", Count(Number(ownLeftOut, "hidden")))
                                                    .Replace("{routed}", Count(Number(ownLeftOut, "another_route")))
                                                    .Replace("{unknown}", Count(Number(ownLeftOut, "beyond_reach")))
                                                    .Replace("{unplaced}", Count(unplaced)));
            said.Append("\r\n").Append(w("sha").Replace("{sha}", Mirror.Embed(Str(result, "sha256") ?? "-")));
            said.Append("\r\n\r\n").Append(text.Replace("\r\n", "\n").Replace("\n", "\r\n"));
            return said.ToString();
        }

    }
}

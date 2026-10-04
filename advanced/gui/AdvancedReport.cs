// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the compatibility report's card on the Advanced features page (advanced/gui/AdvancedPage.cs).
//
// A capability that is an action (the bridge's listing says `kind`) answers at no point and sends nothing to Codex:
// what it does, a person starts here. Its card follows its statement while it is watched or on - write the report
// from this PC's own records, read the whole file with its SHA-256, save it where the person chooses - and, only while
// it is on, ask GitHub through gh what sending would write, show every write, and send once the person has typed the
// word send in its box, exactly. While it is off, the card's controls go and the last check's or send's ending stays.
// The page names no capability: it acts on the open one, by what the listing says it is.
//
// Writing, checking and sending are jobs of the Dashboard's service (report/flow.py): a start answers with the job's
// id at once, and the page reads the job once a second, as a read, until it ends. Each start is an action - every
// other action waits until it is answered - and no longer: Turn off stays live while a send runs. A check or a send
// holds the window's reopen until it ends (HoldReopen, the neutral counter beside `busy`), because the service that
// runs it ends with the window. A send whose start is answered with no job and no refusal of its own - the one-shot
// bridge's "unknown command", a failure - and a job the service no longer holds are both shown as lost, with the way
// to tell what is on GitHub: check again. Nothing here starts a process, opens a browser or touches the clipboard: the
// link, the branch and the file's name are text the person can select.
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
        // ---------------------------------------------------------------- state
        // What a capability is when it answers at no point (vocabulary.CapabilityKind), and the word that sends.
        private const string KindAction = "action";
        private const string SendWord = "send";
        // How often a running job is read.
        private const int ReportPollMilliseconds = 1000;
        // The jobs: what a start began, and what its status is read as.
        private const string JobBuild = "build", JobCheck = "check", JobSend = "send";

        private SoftTextArea reportLogin, reportWord, reportFile;
        private Button reportWrite, reportSave, reportCheck, reportSend;
        // What the person typed, kept while the card is built again.
        private string reportLoginText = "", reportWordText = "";
        // The report written (its `built` status), the last check of it (`checked`, or `web`), and the last check's or
        // send's ending (sent, partial, refused, lost) - kept in this window's memory only, as the service keeps them.
        private Dictionary<string, object> reportBuilt, reportChecked, reportLast;
        // The job being read and what it is; a line saying what the last start or save did.
        private string reportJob, reportJobKind, reportTold;
        private bool reportPolling, reportHolding;
        private Timer reportTimer;
        // The file a test chose in place of the save dialog (AdvancedPageRun).
        private string advancedSaveTo;

        private static bool IsAction(Dictionary<string, object> item)
        {
            return Str(item, "kind") == KindAction;
        }

        /// What the report's card shows, for ShowAdvancedDetail to build it again only when that changed.
        private string ReportShown()
        {
            return (reportBuilt == null ? "" : Str(reportBuilt, "sha256")) + "|" + AdvancedWritten(reportChecked) + "|" +
                   AdvancedWritten(reportLast) + "|" + (reportJobKind ?? "") + "|" + (reportTold ?? "");
        }

        // ---------------------------------------------------------------- the card
        /// The action's card under its statement: everything while it is on, all but checking and sending while it is
        /// watched, and only the last ending while it is off.
        private void BuildReportCard(Dictionary<string, object> item)
        {
            string state = Str(item, "state") ?? StateOff;
            bool on = state == StateArmed, live = on || state == StateShadow;
            if (!live && reportLast == null) return;
            TableLayoutPanel card = NewGroup(Word("page.report.title", "Compatibility report"), advancedStack);
            if (!live)
            {
                Label last = Caption(Word("page.report.last", "The last send:"));
                last.Margin = Pad(0, 0, 0, 4);
                card.Controls.Add(last);
                AddReportEnding(card, reportLast);
                return;
            }
            card.Controls.Add(HelpText(Word("page.report.intro",
                "Write a report of how recovery went with this PC's Codex, read all of it, and send it to the project as a public pull request on GitHub. It holds counts, states and times, never a conversation's text, an id or a path.")));
            if (!on) card.Controls.Add(Accented(Word("page.report.watched", "Watched: the report can be written, read and saved here, and nothing is sent.")));

            reportLogin = OneLine(Word("page.report.login", "Your GitHub login"), reportLoginText, false);
            reportLogin.Box.TextChanged += delegate
            {
                reportLoginText = reportLogin.Box.Text;
                UpdateReportButtons();
            };
            card.Controls.Add(NewRow(Word("page.report.login", "Your GitHub login"), reportLogin));
            reportWrite = CardButton(card, Word("page.report.write", "Write the report"), delegate { WriteReport(); });
            if (reportJobKind == JobBuild) card.Controls.Add(HelpText(Word("page.report.writing", "Writing the report from this PC's own records...")));
            if (reportTold != null) card.Controls.Add(Accented(reportTold));

            if (reportBuilt != null)
            {
                TableLayoutPanel facts = Facts(card);
                Fact(facts, Word("page.report.version", "Codex version")).Text = Str(reportBuilt, "codex_version") ?? "-";
                Fact(facts, Word("page.report.records", "Records")).Text = Whole(Get(reportBuilt, "records")).ToString(CultureInfo.CurrentCulture);
                Fact(facts, Word("page.report.verdict", "Verdict")).Text = Str(reportBuilt, "verdict") ?? "-";
                Fact(facts, Word("page.report.size", "Size in bytes")).Text = Whole(Get(reportBuilt, "bytes")).ToString(CultureInfo.CurrentCulture);
                card.Controls.Add(Caption(Word("page.report.sha256", "SHA-256")));
                card.Controls.Add(ReadOnlyLine(Str(reportBuilt, "sha256"), Word("page.report.sha256", "SHA-256")));
                card.Controls.Add(HelpText(Word("page.report.left_out",
                    "Left out, as codex-compat-reporter leaves them out: records hidden with Clear history, on another Codex version or not placed on one, carried by an advanced feature's own route, or claimed before its spend ledger reaches back.")));
                card.Controls.Add(Caption(Word("page.report.file", "The whole file, exactly as it would be sent")));
                reportFile = new SoftTextArea();
                reportFile.Dock = DockStyle.Fill;
                reportFile.Margin = Pad(0, 2, 0, 6);
                reportFile.Font = Font;
                reportFile.Box.Font = Font;
                reportFile.Box.ReadOnly = true;
                reportFile.Box.WordWrap = false;
                reportFile.Box.Text = (Str(reportBuilt, "text") ?? "").Replace("\n", Environment.NewLine);
                reportFile.Box.AccessibleName = Word("page.report.file", "The whole file, exactly as it would be sent");
                reportFile.Height = Px(220);
                card.Controls.Add(reportFile);
                reportSave = CardButton(card, Word("page.report.save", "Save the file..."), delegate { SaveReport(); });
            }

            if (on && reportBuilt != null)
            {
                reportCheck = CardButton(card, Word("page.report.check", "Check what sending would write"), delegate { CheckReport(); });
                if (reportJobKind == JobCheck) card.Controls.Add(HelpText(Word("page.report.checking", "Asking GitHub through gh. This only reads.")));
                string seen = Str(reportChecked, "status");
                if (seen == "checked") AddReportWrites(card);
                else if (seen == "web") AddReportWeb(card, reportChecked);
                if (reportJobKind == JobSend) card.Controls.Add(Accented(Word("page.report.sending", "Sending. Keep this window open until it is done.")));
            }
            if (reportLast != null)
            {
                card.Controls.Add(Caption(Word("page.report.last", "The last send:")));
                AddReportEnding(card, reportLast);
            }
            UpdateReportButtons();
        }

        /// What a check found sending would write, and the box for the word.
        private void AddReportWrites(TableLayoutPanel card)
        {
            if (Equals(Get(reportChecked, "interrupted"), true))
                card.Controls.Add(Accented(Word("page.report.interrupted", "An earlier send ended part way. What is on GitHub now is below, and sending again is safe.")));
            card.Controls.Add(Caption(Word("page.report.gh", "GitHub CLI")));
            card.Controls.Add(ReadOnlyLine(Str(reportChecked, "gh"), Word("page.report.gh", "GitHub CLI")));
            TableLayoutPanel facts = Facts(card);
            Fact(facts, Word("page.report.signed_in", "Signed in to GitHub as")).Text = Str(reportChecked, "who") ?? "-";
            card.Controls.Add(HeadingText(Word("page.report.writes", "Sending writes to GitHub, as {name}:", "name", Str(reportChecked, "who") ?? "")));
            foreach (object entry in Items(reportChecked, "writes") ?? new List<object>())
            {
                Label line = HelpText("\u2022 " + WriteText(entry as Dictionary<string, object>));
                line.ForeColor = Ink;
                line.Margin = Pad(0, 2, 0, 2);
                card.Controls.Add(line);
            }
            card.Controls.Add(HelpText(Word("page.report.type", "To send it, type send below.")));
            reportWord = OneLine(Word("page.report.type", "To send it, type send below."), reportWordText, false);
            reportWord.Box.TextChanged += delegate
            {
                reportWordText = reportWord.Box.Text;
                UpdateReportButtons();
            };
            card.Controls.Add(NewRow(Word("page.report.send", "Send"), reportWord));
            reportSend = CardButton(card, Word("page.report.send", "Send"), delegate { SendReport(); });
        }

        /// One write sending makes, in words, with its name.
        private string WriteText(Dictionary<string, object> write)
        {
            string kind = Str(write, "kind") ?? "", name = Str(write, "name") ?? "";
            if (kind == "fork_new") return Word("page.report.w.fork_new", "a fork of the project under your account, {name}: public, and kept until you delete it", "name", name);
            if (kind == "fork_kept") return Word("page.report.w.fork_kept", "the fork {name}, which exists already and is not changed otherwise", "name", name);
            if (kind == "branch_new") return Word("page.report.w.branch_new", "the branch {name} on it, made at the project's main", "name", name);
            if (kind == "branch_reset") return Word("page.report.w.branch_reset", "the branch {name} on it, reset to the project's main", "name", name);
            if (kind == "file") return Word("page.report.w.file", "one commit on that branch adding exactly the file above, as {name}", "name", name);
            if (kind == "pr") return Word("page.report.w.pr", "one public pull request on the project; a pull request cannot be unpublished");
            return name;
        }

        /// The web's steps, where gh cannot send it from here, with the names to type as text that can be selected.
        private void AddReportWeb(TableLayoutPanel card, Dictionary<string, object> web)
        {
            string why = Str(web, "why");
            string reason = why == "no_gh"
                ? Word("page.report.web.no_gh", "gh, the GitHub CLI, is not installed here, so the report cannot be sent from this PC.")
                : why == "gh_signed_out"
                ? Word("page.report.web.gh_signed_out", "gh is not signed in to github.com here.")
                : Word("page.report.web.gh_other_login", "gh is signed in here as {name}, not as the login the report is filed under.", "name", Str(web, "who") ?? "-");
            card.Controls.Add(Accented(reason));
            card.Controls.Add(HeadingText(Word("page.report.web.intro", "To send it on the web instead, signed in to GitHub as {name}:", "name", Str(web, "login") ?? "")));
            card.Controls.Add(Step("1. ", Word("page.report.web.1", "Open the project page and choose Fork (a fork you already have will do).")));
            card.Controls.Add(ReadOnlyLine(Str(web, "project_page"), Word("page.report.web.1", "Open the project page and choose Fork (a fork you already have will do).")));
            card.Controls.Add(Step("2. ", Word("page.report.web.2", "In your fork, open the branch list, type this name and choose Create branch:")));
            card.Controls.Add(ReadOnlyLine(Str(web, "branch"), Word("page.report.web.2", "In your fork, open the branch list, type this name and choose Create branch:")));
            card.Controls.Add(Step("3. ", Word("page.report.web.3", "On that branch, choose Add file > Create new file, give it this name, paste the whole report and commit it:")));
            card.Controls.Add(ReadOnlyLine(Str(web, "target"), Word("page.report.web.3", "On that branch, choose Add file > Create new file, give it this name, paste the whole report and commit it:")));
            card.Controls.Add(Step("4. ", Word("page.report.web.4", "Choose Contribute > Open pull request, to the project's main, and create it.")));
        }

        /// How a check or a send ended: sent (now or already), part way, refused, or not known.
        private void AddReportEnding(TableLayoutPanel card, Dictionary<string, object> ending)
        {
            string status = Str(ending, "status");
            if (status == "sent")
            {
                bool already = Equals(Get(ending, "already"), true);
                card.Controls.Add(Inked(HelpText(already ? Word("page.report.already", "It was sent already. The pull request:")
                                                       : Word("page.report.sent", "Sent. The pull request:"))));
                card.Controls.Add(ReadOnlyLine(Str(ending, "url"), Word("page.report.sent", "Sent. The pull request:")));
                card.Controls.Add(HelpText(Word("page.report.after",
                    "The project's check reads it within minutes and files it by itself; the pull request is then closed with one comment saying where the report went, or why it waits. Nothing more is needed from you.")));
                return;
            }
            if (status == "partial")
            {
                card.Controls.Add(Accented(Word("page.report.partial", "Not everything was written. Already on GitHub:")));
                foreach (object entry in Items(ending, "written") ?? new List<object>())
                {
                    Label line = HelpText("\u2022 " + WriteText(entry as Dictionary<string, object>));
                    line.ForeColor = Ink;
                    line.Margin = Pad(0, 2, 0, 2);
                    card.Controls.Add(line);
                }
                card.Controls.Add(HelpText(ReportRefusalText(Str(ending, "refusal"))));
                card.Controls.Add(HelpText(Word("page.report.again", "Sending again is safe: it keeps the fork, resets the branch to the project's main and adds the file again.")));
                return;
            }
            if (status == "refused")
            {
                card.Controls.Add(Accented(ReportRefusalText(Str(ending, "refusal"))));
                return;
            }
            card.Controls.Add(Accented(Word("page.report.lost",
                "Whether the report was sent could not be told: the process sending it ended. Choose Check what sending would write: it reads GitHub and shows what is there.")));
        }

        // ---------------------------------------------------------------- the card's parts
        private Label Accented(string text)
        {
            Label line = HelpText(text);
            line.ForeColor = Accent;
            line.Margin = Pad(0, Brand.SpaceS, 0, Brand.SpaceS);
            return line;
        }

        /// A caption that wraps, as a help line does: one whose words carry a name, and run past a line in some
        /// languages (a Caption keeps to one).
        private Label HeadingText(string text)
        {
            Label label = HelpText(text);
            label.ForeColor = Ink;
            label.Font = Soft.RoleFont("heading");
            label.Margin = Pad(0, 10, 0, 4);
            return label;
        }

        private Label Inked(Label line)
        {
            line.ForeColor = Ink;
            return line;
        }

        private Label Step(string number, string text)
        {
            Label line = HelpText(number + text);
            line.ForeColor = Ink;
            line.Margin = Pad(0, 6, 0, 2);
            return line;
        }

        private Button CardButton(TableLayoutPanel card, string text, EventHandler pressed)
        {
            Button button = MakeButton(text, false, pressed);
            button.Margin = Pad(0, 4, 0, 8);
            button.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            card.Controls.Add(button);
            return button;
        }

        /// A box of one line, in a well, as the log's search is: what the person types, or, read-only, text they can
        /// select - a link, a branch, a file's name - which nothing here opens or copies for them.
        private SoftTextArea OneLine(string name, string text, bool readOnly)
        {
            var box = new SoftTextArea();
            box.Font = Font;
            box.Box.Font = Font;
            box.Box.AcceptsReturn = false;
            box.Box.WordWrap = false;
            box.Box.ReadOnly = readOnly;
            box.Box.MaxLength = readOnly ? 32767 : 64;
            box.Box.Text = text ?? "";
            box.Box.AccessibleName = name;
            box.Height = Px(Brand.ButtonHeight);
            box.Width = Px(280);
            box.Margin = Pad(0, 0, 0, 0);
            return box;
        }

        private SoftTextArea ReadOnlyLine(string text, string name)
        {
            SoftTextArea box = OneLine(name, text, true);
            box.Dock = DockStyle.Fill;
            box.Margin = Pad(0, 2, 0, 6);
            return box;
        }

        /// A refusal in words: an administrator's policy as the page says it, else the report's own.
        private string ReportRefusalText(string refusal)
        {
            if (refusal == "forbidden_by_policy" || refusal == "not_allowed_by_policy" || refusal == "shadow_forced_by_policy")
                return AdvancedRefusal(new Dictionary<string, object> { { "refusal", refusal } });
            string said = refusal == null ? null : Word("page.report.refused." + refusal, null);
            return said ?? Word("page.refused.other", "That request was refused. Nothing was changed.");
        }

        /// What each of the card's buttons may do now: none while another action is under way, and none that starts a
        /// job while one runs; Send only on exactly the word.
        private void UpdateReportButtons()
        {
            bool idle = busy == 0, free = reportJob == null;
            bool on = Str(AdvancedItem(advancedOpen), "state") == StateArmed;
            if (reportWrite != null) reportWrite.Enabled = idle && free;
            if (reportSave != null) reportSave.Enabled = idle && reportBuilt != null;
            if (reportCheck != null) reportCheck.Enabled = idle && free && on && reportBuilt != null;
            if (reportSend != null)
                reportSend.Enabled = idle && free && on && Str(reportChecked, "status") == "checked" &&
                                     string.Equals(reportWordText, SendWord, StringComparison.Ordinal);
        }

        /// The card built again (ShowAdvancedDetail keeps the keyboard where it was among its boxes and buttons).
        private void RefreshReport()
        {
            advancedShown = null;
            ShowAdvancedDetail();
        }

        /// The card's controls forgotten as the cards they were on are disposed.
        private void ForgetReportCard()
        {
            reportLogin = reportWord = reportFile = null;
            reportWrite = reportSave = reportCheck = reportSend = null;
        }

        /// Which of the card's boxes or buttons has the keyboard, or null.
        private string ReportFocus()
        {
            if (reportLogin != null && reportLogin.ContainsFocus) return "login";
            if (reportWord != null && reportWord.ContainsFocus) return "word";
            if (reportFile != null && reportFile.ContainsFocus) return "file";
            if (reportWrite != null && reportWrite.Focused) return "write";
            if (reportSave != null && reportSave.Focused) return "save";
            if (reportCheck != null && reportCheck.Focused) return "check";
            if (reportSend != null && reportSend.Focused) return "send";
            return null;
        }

        /// The keyboard back on the box or button `name` names in the card as built again, where it can take it.
        private bool FocusReport(string name)
        {
            Control target = null;
            if (name == "login" && reportLogin != null) target = reportLogin.Box;
            else if (name == "word" && reportWord != null) target = reportWord.Box;
            else if (name == "file" && reportFile != null) target = reportFile.Box;
            else if (name == "write") target = reportWrite;
            else if (name == "save") target = reportSave;
            else if (name == "check") target = reportCheck;
            else if (name == "send") target = reportSend;
            if (target == null || !target.CanFocus) return false;
            target.Focus();
            return true;
        }

        // ---------------------------------------------------------------- the jobs
        private void WriteReport()
        {
            if (busy > 0 || reportJob != null) return;
            string login = (reportLoginText ?? "").Trim();
            reportTold = null;
            AdvancedCall("advanced-report-build", "{\"login\":" + Json.Escape(login) + "}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                string job = AdvancedDone(result) ? Str(result, "job") : null;
                if (job == null)
                {
                    reportTold = result == null ? Word("page.refused.unavailable", "The advanced features could not be changed right now. Nothing was changed.")
                                                : ReportRefusalText(Str(result, "refusal"));
                    RefreshReport();
                    return;
                }
                StartReportJob(job, JobBuild);
            });
        }

        private void SaveReport()
        {
            if (busy > 0 || reportBuilt == null) return;
            string sha = Str(reportBuilt, "sha256"), name = Str(reportBuilt, "file_name") ?? "codex-compat-report.json";
            string target = AskSavePath(name);
            if (target == null) return;
            reportTold = null;
            AdvancedCall("advanced-report-save", "{\"sha256\":" + Json.Escape(sha) + ",\"path\":" + Json.Escape(target) + "}", true,
                delegate(Dictionary<string, object> reply)
                {
                    Dictionary<string, object> result = AdvancedResult(reply);
                    reportTold = AdvancedDone(result) ? Word("page.report.saved", "Saved.")
                               : result == null ? Word("page.refused.unavailable", "The advanced features could not be changed right now. Nothing was changed.")
                               : ReportRefusalText(Str(result, "refusal"));
                    RefreshReport();
                });
        }

        /// Where to save the file: the person's choice in the save dialog, which never offers to replace a file - the
        /// bridge never writes over one - or the file a test chose.
        private string AskSavePath(string name)
        {
            if (advancedScript != null) return advancedSaveTo;
            using (var save = new SaveFileDialog())
            {
                save.Filter = "JSON (*.json)|*.json";
                save.FileName = name;
                save.OverwritePrompt = false;
                if (save.ShowDialog(this) != DialogResult.OK) return null;
                return save.FileName;
            }
        }

        private void CheckReport()
        {
            if (busy > 0 || reportJob != null || reportBuilt == null) return;
            reportTold = null;
            AdvancedCall("advanced-report-check", "{\"sha256\":" + Json.Escape(Str(reportBuilt, "sha256")) + "}", true,
                delegate(Dictionary<string, object> reply) { Started(AdvancedResult(reply), JobCheck); });
        }

        private void SendReport()
        {
            if (busy > 0 || reportJob != null || reportBuilt == null || Str(reportChecked, "status") != "checked" ||
                !string.Equals(reportWordText, SendWord, StringComparison.Ordinal))
                return;
            // Exactly what the page shows: the file's SHA-256, the writes the check named, and the word typed.
            string argument = "{\"sha256\":" + Json.Escape(Str(reportBuilt, "sha256")) + ",\"writes\":" +
                              Json.Write(Get(reportChecked, "writes")) + ",\"word\":" + Json.Escape(reportWordText) + "}";
            reportTold = null;
            AdvancedCall("advanced-report-send", argument, true,
                delegate(Dictionary<string, object> reply) { Started(AdvancedResult(reply), JobSend); });
        }

        /// A check's or a send's start answered: its job, read from now on; a refusal of its own, said; and anything
        /// else - no answer, or one that is neither - shown as lost, since whether it reached the service is unknown.
        private void Started(Dictionary<string, object> result, string kind)
        {
            string job = AdvancedDone(result) ? Str(result, "job") : null;
            if (job != null)
            {
                if (kind == JobSend) reportWordText = "";
                HoldReport(true);
                StartReportJob(job, kind);
                return;
            }
            string refusal = Str(result, "refusal");
            if (refusal != null) reportTold = ReportRefusalText(refusal);
            else
            {
                reportLast = new Dictionary<string, object> { { "status", "lost" } };
                if (kind == JobCheck) reportChecked = null;
            }
            RefreshReport();
        }

        private void StartReportJob(string job, string kind)
        {
            reportJob = job;
            reportJobKind = kind;
            RefreshReport();
            if (advancedScript != null || auditing) return;            // a test reads the job itself (PollReport)
            if (reportTimer == null)
            {
                reportTimer = new Timer();
                reportTimer.Interval = ReportPollMilliseconds;
                reportTimer.Tick += delegate { PollReport(); };
                Disposed += delegate { reportTimer.Dispose(); };
            }
            reportTimer.Start();
        }

        /// The running job read once, as a read: an answer that is not one leaves it to be read again; any status but
        /// running ends it.
        private void PollReport()
        {
            if (reportJob == null)
            {
                if (reportTimer != null) reportTimer.Stop();
                return;
            }
            if (reportPolling) return;
            reportPolling = true;
            string job = reportJob;
            AdvancedCall("advanced-report-job", "{\"job\":" + Json.Escape(job) + "}", false, delegate(Dictionary<string, object> reply)
            {
                reportPolling = false;
                if (job != reportJob) return;
                Dictionary<string, object> result = AdvancedResult(reply);
                string status = Str(result, "status");
                if (status == null || status == "running") return;
                EndReportJob(result);
            });
        }

        private void EndReportJob(Dictionary<string, object> result)
        {
            string kind = reportJobKind, status = Str(result, "status");
            reportJob = null;
            reportJobKind = null;
            if (reportTimer != null) reportTimer.Stop();
            if (kind == JobBuild)
            {
                if (status == "built")
                {
                    reportBuilt = result;
                    reportChecked = null;
                }
                else reportTold = status == "lost" ? Word("page.report.lost", "Whether the report was sent could not be told: the process sending it ended. Choose Check what sending would write: it reads GitHub and shows what is there.")
                                                   : ReportRefusalText(Str(result, "refusal"));
            }
            else
            {
                HoldReport(false);
                if (kind == JobCheck && (status == "checked" || status == "web")) reportChecked = result;
                else
                {
                    reportChecked = null;
                    reportLast = result;
                }
            }
            RefreshReport();
        }

        /// The window's reopen held while a check or a send runs, and let go when it ends (HoldReopen).
        private void HoldReport(bool on)
        {
            if (on == reportHolding) return;
            reportHolding = on;
            HoldReopen(on);
        }
    }
}

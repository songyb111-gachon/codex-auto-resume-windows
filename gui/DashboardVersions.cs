// Codex Auto Resume - Diagnostics' Install another version... (v0.6.12): this repository's versions, in
// either edition, each offered or refused with its reason, and the one a person picks installed in place of
// the one they have.
//
// Nothing here reaches the network. The installed bootstrap does (scripts/bootstrap.ps1 -Versions, -Pick),
// and only when a person asks: the list when the button is pressed, the install when a row is confirmed. The
// dialog is built in its asking state and starts nothing (BuildVersions); only the button's handler starts
// the listing (OpenVersions, StartVersionsListing), so the window audit, which builds every dialog, never
// asks GitHub for anything. What the bootstrap answers is read through two static parsers that refuse the
// whole answer on a word outside their closed sets (VersionsLines, PickLine), and a refused row stays in the
// list, greyed, with its reason, because the bootstrap - not this window - decides what can be installed.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // The listing reads up to five pages of the list, each with a deadline of its own, inside the bootstrap's
        // budget of 150 seconds; this waits a little longer than that, and never kills it.
        private const int ListMilliseconds = 180000;
        // scripts/bootstrap.ps1's $ExitPickRefused: -Pick refused, said why on its line, and changed nothing.
        private const int PickRefusedCode = 15;

        // The chips of the Kind column, by the code ToneFor colours them by.
        private const string PickRelease = "pick_release";
        private const string PickPrerelease = "pick_prerelease";
        private const string PickInstalled = "pick_installed";
        private const string PickUnavailable = "pick_unavailable";

        private Button versionsButton;
        // The dialog as BuildVersions made it last: its list, the line under it that says what is chosen or how the
        // asking went, the two fixed notes, and Install.
        private ListView versionsList;
        private Label versionsSaid, versionsNotes;
        private Button versionsInstall;
        // What the list shows, a row per item in its order - version, edition, answer, words or reason - and the
        // `versions: listed` line's installed version and edition, newest release, floor and editions' start.
        private List<string[]> versionsRows = new List<string[]>();
        private string[] versionsListed;
        // The row Install... was pressed on, read once the dialog has closed.
        private string[] versionsPicked;
        // Which listing is the latest, so the answer to one whose dialog was closed is dropped.
        private int versionsToken;

        // ------------------------------------------------------------------ the button
        /// The button's one handler: the dialog built, its listing started, the dialog shown; then, for a row a person
        /// pressed Install... on, the confirmation, and on its yes the install.
        private void OpenVersions()
        {
            // An administrator's DisableUpdateCheck greys this button as it greys Check for updates, and nothing is
            // asked however this is reached.
            if (updatesManaged) return;
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string script = Path.Combine(root, "app", "scripts", "bootstrap.ps1");
            if (!File.Exists(script))
            {
                Tell(S("diag.update_incomplete", "Files this installation is made of are missing, so it could not be checked. Install it again from the release archive."));
                return;
            }
            string[] picked = null, listed = null;
            using (Form dialog = BuildVersions())
            {
                StartVersionsListing(dialog, root, script);
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    picked = versionsPicked;
                    listed = versionsListed;
                }
            }
            versionsPicked = null;
            if (picked == null || listed == null || picked[2] != "offered") return;
            if (!ConfirmPick(picked, listed)) return;
            InstallPick(root, script, picked);
        }

        /// The dialog, built in its asking state and not shown: an empty list, the line that says it is asking, Install
        /// greyed. It starts no process and no timer; StartVersionsListing does, from OpenVersions alone.
        private Form BuildVersions()
        {
            var dialog = new Form();
            dialog.Text = S("pick.title", "Install another version");
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.ClientSize = new Size(Px(740), Px(460));
            dialog.MinimizeBox = false;
            dialog.ShowInTaskbar = false;

            // Flat hairline rows, owner-drawn as every list here is (DrawCell): 660 px of columns in the 716 the
            // padding leaves, shared out by FitColumns.
            var view = List(S("pick.title", "Install another version"),
                            Col(S("pick.col_version", "Version"), 120),
                            Col(S("pick.col_kind", "Kind"), 130),
                            Col(S("pick.col_edition", "Edition"), 110),
                            Col(S("pick.col_note", "What it means"), 300));
            var host = new SoftListHost(view);
            host.Dock = DockStyle.Fill;
            var padding = new Panel();
            padding.BackColor = Canvas;
            padding.Dock = DockStyle.Fill;
            padding.Padding = Pad(12, 12, 12, 0);
            padding.Controls.Add(host);

            var footer = new SoftStack();
            footer.Dock = DockStyle.Bottom;
            footer.AutoSize = true;
            footer.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            footer.ColumnCount = 1;
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            footer.Padding = Pad(12, 8, 12, 0);
            footer.BackColor = Canvas;
            var said = Value(S("pick.asking", "Asking GitHub for the list of releases..."));
            said.ForeColor = Secondary;
            said.MaximumSize = new Size(Px(716), 0);
            footer.Controls.Add(said);
            var notes = Value("");
            notes.ForeColor = Secondary;
            notes.MaximumSize = new Size(Px(716), 0);
            footer.Controls.Add(notes);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(12, 8, 12, 12);
            Button install = MakeButton(S("pick.install", "Install..."), true, delegate
            {
                string[] row = ChosenVersion();
                if (row == null || row[2] != "offered") return;
                versionsPicked = row;
                dialog.DialogResult = DialogResult.OK;
            });
            install.Enabled = false;
            var close = MakeButton(S("action.close", "Close"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(install);
            buttons.Controls.Add(close);

            dialog.Controls.Add(padding);
            dialog.Controls.Add(footer);
            dialog.Controls.Add(buttons);
            // No AcceptButton: Enter installs nothing.
            dialog.CancelButton = close;
            dialog.UseWaitCursor = true;
            view.SelectedIndexChanged += delegate { ShowVersionChoice(); };

            versionsList = view;
            versionsSaid = said;
            versionsNotes = notes;
            versionsInstall = install;
            versionsRows = new List<string[]>();
            versionsListed = null;
            versionsPicked = null;
            return dialog;
        }

        /// The listing: the installed bootstrap's -Versions on a worker, its answer shown in `dialog` if it is still
        /// open and still the latest. Closing the dialog does not stop it - it only reads - and its answer is dropped.
        private void StartVersionsListing(Form dialog, string root, string script)
        {
            int mine = ++versionsToken;
            SetBusy(true);
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string printed, errors;
                int code;
                string ran = StartBootstrap(root, script, "-Versions", ListMilliseconds, out printed, out errors, out code);
                List<string[]> rows = new List<string[]>();
                string[] listed = null;
                // Still asking after three minutes is an answer that did not come; nothing the bootstrap did not print
                // is ever read as a list.
                string state = ran == "done" ? VersionsLines(printed, code, out rows, out listed)
                             : ran == "running" ? "unavailable" : "unreadable";
                MethodInvoker apply = delegate
                {
                    SetBusy(false);
                    if (mine != versionsToken || dialog.IsDisposed) return;
                    ShowVersionRows(state, rows, listed);
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { }
            });
        }

        /// One answer of the listing in the dialog BuildVersions made: `state` as VersionsLines read it, its rows and
        /// its `versions: listed` line. The audit fills the dialog through here too (AuditVersions).
        private void ShowVersionRows(string state, List<string[]> rows, string[] listed)
        {
            if (versionsList == null || versionsList.IsDisposed) return;
            Form dialog = versionsList.FindForm();
            if (dialog != null) dialog.UseWaitCursor = false;
            bool shown = state == "listed" && rows != null && listed != null;
            versionsRows = shown ? rows : new List<string[]>();
            versionsListed = shown ? listed : null;
            versionsList.BeginUpdate();
            versionsList.Items.Clear();
            foreach (string[] row in versionsRows)
            {
                var item = new ListViewItem("v" + row[0]);
                item.SubItems.Add(KindText(row));
                item.SubItems.Add(EditionName(row[1]));
                item.SubItems.Add(MeaningOf(row));
                // The chip's colour by its code (ToneFor), and a refused row's words in Secondary (DrawCell).
                item.Tag = new Dictionary<string, object> { { "code", KindCode(row) } };
                versionsList.Items.Add(item);
            }
            versionsList.EndUpdate();
            MeasureCells(versionsList);
            versionsNotes.Text = shown
                ? S("pick.floor", "Versions before {version} are not offered: from them, the Dashboard could not bring you back.", "version", listed[3]) +
                  Environment.NewLine +
                  S("pick.advanced_since", "The advanced edition begins with {version}.", "version", listed[4])
                : "";
            ShowVersionChoice();
            if (state == "unavailable")
                versionsSaid.Text = S("pick.could_not_list", "GitHub could not be asked for the list of releases just now. Nothing was changed.");
            else if (!shown)
                versionsSaid.Text = S("pick.list_failed", "The list of releases could not be read. Nothing was changed.");
        }

        /// The chosen row's reason or note under the list, and Install for an offered row alone.
        private void ShowVersionChoice()
        {
            if (versionsInstall == null || versionsSaid == null) return;
            string[] row = ChosenVersion();
            versionsInstall.Enabled = row != null && row[2] == "offered";
            versionsSaid.Text = row == null ? "" : MeaningOf(row);
        }

        private string[] ChosenVersion()
        {
            if (versionsList == null || versionsList.SelectedIndices.Count != 1) return null;
            int index = versionsList.SelectedIndices[0];
            return index >= 0 && index < versionsRows.Count ? versionsRows[index] : null;
        }

        private static string KindCode(string[] row)
        {
            if (row[2] == "installed") return PickInstalled;
            if (row[2] == "refused") return PickUnavailable;
            return HasWord(row, "prerelease") ? PickPrerelease : PickRelease;
        }

        /// Whether a list row is one Install another version... refused (DrawCell draws its words in Secondary).
        private static bool PickRefusedRow(Dictionary<string, object> row)
        {
            return row != null && Str(row, "code") == PickUnavailable;
        }

        private string KindText(string[] row)
        {
            if (row[2] == "installed") return S("pick.kind.installed", "Installed");
            if (row[2] == "refused") return S("pick.kind.unavailable", "Not available");
            return HasWord(row, "prerelease") ? S("pick.kind.prerelease", "Pre-release") : S("pick.kind.release", "Release");
        }

        private string EditionName(string edition)
        {
            return edition == "advanced" ? S("edition.advanced", "Advanced") : S("edition.standard", "Standard");
        }

        /// What a row means, the first that applies: a refusal's reason, or an offered row's note.
        private string MeaningOf(string[] row)
        {
            if (row[2] == "installed") return S("pick.reason.installed", "The version you have");
            if (row[2] == "refused")
            {
                string reason = row[3];
                if (reason == "no-archive") return S("pick.reason.no_archive", "No archive of this edition was published under this number");
                if (reason == "no-checksum") return S("pick.reason.no_checksum", "Published without a checksum to check it against");
                if (reason == "edition-first") return S("pick.reason.edition_first", "Its installer predates editions: change the edition first");
                if (reason == "managed-policy") return S("pick.reason.managed_policy", "Your administrator's policy is set, and this version does not keep it");
                if (reason == "older-prerelease") return S("pick.reason.older_prerelease", "A pre-release older than yours is not installed");
                return S("pick.reason.not_offered", "Check for updates offers a newer version than this one");
            }
            if (HasWord(row, "edition")) return S("pick.note.edition", "Changes the edition");
            if (HasWord(row, "older") && HasWord(row, "convert3")) return S("pick.note.convert", "Older; your state is converted first");
            if (HasWord(row, "older")) return S("pick.note.older", "Older than yours");
            if (HasWord(row, "latest")) return S("pick.note.latest", "Newest release");
            return S("pick.note.newer", "Newer than yours");
        }

        private static bool HasWord(string[] row, string word)
        {
            return row[2] == "offered" && Array.IndexOf(row[3].Split(','), word) >= 0;
        }

        // ------------------------------------------------------------- the confirmation
        /// What installing the picked row changes, only the paragraphs that apply, asked the careful way: Not now is
        /// what Enter, Escape and the keyboard's first place answer.
        private bool ConfirmPick(string[] row, string[] listed)
        {
            bool older = HasWord(row, "older"), convert = HasWord(row, "convert3");
            var text = new List<string>();
            text.Add(S("pick.confirm.head", "Install {version} ({edition}) in place of the version you have, {installed} ({installed_edition})?", "version", row[0])
                         .Replace("{edition}", EditionName(row[1]))
                         .Replace("{installed_edition}", EditionName(listed[1]))
                         .Replace("{installed}", listed[0]));
            if (HasWord(row, "prerelease"))
                text.Add(S("pick.confirm.prerelease", "It is a pre-release: published before its release is finished, and tested less than a release."));
            if (older)
                text.Add(S("pick.confirm.older", "It is older than the version you have: what came since is not in it, and a setting or a value it does not know reads as its default there and is lost the next time it saves your settings."));
            if (convert)
            {
                text.Add(S("pick.confirm.convert", "Your state is converted for it first, and a copy of it as it is now is kept beside it. A continuation that may already have gone to Codex becomes final there and is never sent again, and a conversation that waited for you, or whose continuation Codex may still deliver, is switched off."));
                if (Equals(Get(Map(snapshot, "status"), "observe_only"), true))
                    text.Add(S("pick.confirm.observe_only", "Observe only becomes a pause there: nothing is sent until you resume recovery in that version."));
            }
            if (HasWord(row, "edition"))
                text.Add(row[1] == "standard"
                    ? S("pick.confirm.to_standard", "The advanced features go, and their code with them.")
                    : S("pick.confirm.to_advanced", "Every advanced feature starts off."));
            if (HasWord(row, "advanced-off"))
                text.Add(S("pick.confirm.advanced_off", "That version cannot read this version's advanced settings: every advanced feature is off there, and the settings are kept for a later version."));
            text.Add(S("pick.confirm.checked", "The download is checked against its pinned digest or its published checksum before anything runs.") + " " +
                     (older ? S("pick.confirm.kept_older", "Every record, your pause and the sign-in choice are kept.")
                            : S("pick.confirm.kept", "Your settings, your pause, everything waiting and the sign-in choice are kept.")));
            if (WayBack(row, listed[0]))
                text.Add(S("pick.confirm.way_back", "To come back, use Check for updates in that version."));
            return Dialog(string.Join(Environment.NewLine + Environment.NewLine, text.ToArray()),
                          S("action.install", "Install"), S("action.not_now", "Not now"));
        }

        /// The first version whose Check for updates offers a pre-release (the bootstrap's Get-NewerPrerelease): v0.6.2
        /// to v0.6.11-beta read releases/latest alone, which never answers with one.
        internal const string PrereleaseOffersSince = "0.6.11-beta.2";

        /// Whether Check for updates in the older version the row names brings this installation back: that check
        /// installs in its own edition, so only without a change of edition, and it offers the newest release from
        /// v0.6.2 on but a pre-release only from PrereleaseOffersSince - so from a pre-release only a version that new.
        internal static bool WayBack(string[] row, string installed)
        {
            if (!HasWord(row, "older") || HasWord(row, "edition")) return false;
            if (installed.IndexOf('-') < 0) return true;
            return CompareVersions(row[0], PrereleaseOffersSince) >= 0;
        }

        /// -1, 0 or 1 by the bootstrap's own rule (Compare-ProductVersion): three integers, then the stage - alpha, beta,
        /// the release - and the stage's number, the plain word its first. A text no version by VersionRule sorts first.
        internal static int CompareVersions(string left, string right)
        {
            int[] a = VersionParts(left), b = VersionParts(right);
            if (a == null || b == null) return a == null ? (b == null ? 0 : -1) : 1;
            for (int i = 0; i < a.Length; i++)
                if (a[i] != b[i]) return a[i] < b[i] ? -1 : 1;
            return 0;
        }

        private static int[] VersionParts(string version)
        {
            var match = VersionRule.Match(version ?? "");
            if (!match.Success) return null;
            int stage = 2, number = 0;
            if (match.Groups[5].Success)
            {
                stage = match.Groups[5].Value == "alpha" ? 0 : 1;
                number = match.Groups[7].Success ? int.Parse(match.Groups[7].Value, CultureInfo.InvariantCulture) : 1;
            }
            return new[] { int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture),
                           int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture),
                           int.Parse(match.Groups[3].Value, CultureInfo.InvariantCulture), stage, number };
        }

        // ------------------------------------------------------------------ the install
        /// The confirmed row installed through the installed bootstrap's -Pick: its version, held to the version rule
        /// before it reaches the command line, its edition, and -Force exactly when the row is older or of the other
        /// edition, which the bootstrap requires then and refuses otherwise.
        private void InstallPick(string root, string script, string[] row)
        {
            if (!VersionRule.IsMatch(row[0]) || (row[1] != "standard" && row[1] != "advanced")) return;
            var words = new List<string>(row[3].Split(','));
            bool force = words.Contains("older") || words.Contains("edition");
            string flag = "-Pick " + row[0] + " -Edition " + (row[1] == "advanced" ? "Advanced" : "Standard") +
                          (force ? " -Force" : "");
            string version = row[0], edition = row[1];
            string before = WatcherIdentity();
            string shown = diagUpdate.Text;
            SetBusy(true);
            diagUpdate.Text = S("diag.update_installing", "installing...");
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string printed, errors, reason, installed;
                int code;
                int[] converted = null;
                string ran = StartBootstrap(root, script, flag, UpdateMilliseconds, out printed, out errors, out code);
                string outcome = ran;
                reason = null;
                installed = null;
                if (ran == "done")
                {
                    outcome = PickLine(printed, code, out reason, out converted, out installed);
                    if (outcome == "installed" && installed != version + " " + edition) outcome = "failed";
                }
                string detail = Tail(printed + "\n" + errors);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    if (outcome == "installed") AfterPick(before, version, converted);
                    else
                    {
                        diagUpdate.Text = shown;
                        ReportPick(outcome, reason, converted, detail);
                    }
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// Installed: said as an update is, with whether the watcher changed hands (the pid and start time WatcherIdentity
        /// reads), what the conversion did where there was one, and that this window still runs the version before.
        private void AfterPick(string before, string version, int[] converted)
        {
            diagUpdate.Text = S("diag.update_installed", "v{version} installed", "version", version);
            CallAsync("status", null, delegate(Dictionary<string, object> reply)
            {
                string handover = "unknown";
                if (Ok(reply))
                {
                    var status = Map(reply, "status");
                    var watcher = Map(status, "watcher");
                    object pid = Get(watcher, "pid");
                    object started = Get(watcher, "started_at");
                    string now = watcher == null || pid == null || started == null ? null
                               : Convert.ToString(pid, CultureInfo.InvariantCulture) + "@" +
                                 Convert.ToString(started, CultureInfo.InvariantCulture);
                    if (now != null) handover = before != null && now == before ? "same" : "restarted";
                }
                var text = new StringBuilder(S("diag.update_done", "Version {version} is installed.", "version", version));
                text.Append(Environment.NewLine).Append(Environment.NewLine).Append(
                    handover == "restarted"
                        ? S("pick.watcher_restarted", "The watcher was restarted and is running version {version}.", "version", version)
                    : handover == "same"
                        ? S("pick.watcher_same", "The watcher that is running is still the one from before, so version {version} is not running yet. Stop it and start it again from this page.", "version", version)
                        : S("diag.update_watcher_unknown", "Whether the watcher restarted could not be confirmed."));
                if (converted != null)
                {
                    text.Append(Environment.NewLine).Append(Environment.NewLine)
                        .Append(S("pick.done_converted", "Your state was converted for it, and a copy of it as it was is kept in the state folder."));
                    AppendConverted(text, converted);
                }
                text.Append(Environment.NewLine).Append(Environment.NewLine)
                    .Append(S("pick.reopen", "Close this window and open it again so it runs version {version}.").Replace("{version}", version));
                Tell(text.ToString());
                RefreshAfterChange();
            });
        }

        /// Every answer of a pick but installed, in words that say what was and was not changed.
        private void ReportPick(string outcome, string reason, int[] converted, string detail)
        {
            if (outcome == "refused")
            {
                if (reason == "busy") Tell(S("diag.repair_busy", "An installation or a repair is already running. Try again once it has finished."));
                else if (reason == "watcher-running")
                    Tell(S("pick.refused.watcher_running", "The watcher did not stop within a minute, so nothing was installed and your state was not converted. It was asked to stop and may still do so; start it again from this page if it has."));
                else if (reason == "state")
                    Tell(S("pick.refused.state", "Your state could not be converted for that version, so nothing was installed and the state is as it was. The watcher was started again."));
                // No installation whose version the bootstrap could read: the files are what is missing.
                else if (reason == "unreadable")
                    Tell(S("diag.update_incomplete", "Files this installation is made of are missing, so it could not be checked. Install it again from the release archive."));
                else
                    Tell(S("pick.refused.changed", "The list of releases changed after it was shown, so nothing was installed and nothing was changed. Open Install another version... again."));
            }
            else if (outcome == "unavailable")
                Tell(S("pick.could_not_ask", "GitHub could not be asked just now, so nothing was installed and nothing was changed."));
            else if (outcome == "running")
                Tell(S("diag.update_running", "It is taking longer than usual and is still working. It carries on in the background; look at this page again in a few minutes."));
            else if (outcome == "incomplete")
                Tell(S("diag.update_incomplete", "Files this installation is made of are missing, so it could not be checked. Install it again from the release archive."));
            else
            {
                var text = new StringBuilder(S("pick.failed", "The installation did not finish. Read what it said below; Repair installation sets up whichever version is there now."));
                if (converted != null)
                {
                    text.Append(Environment.NewLine).Append(Environment.NewLine)
                        .Append(S("pick.failed_converted", "Your state had already been converted for the older version, and it stays converted: this version reads it as it is now and puts none of it back, and the needs-you notices are gone. A copy of it as it was is kept in the state folder."));
                    AppendConverted(text, converted);
                }
                if (!string.IsNullOrEmpty(detail)) text.Append(Environment.NewLine).Append(Environment.NewLine).Append(detail);
                Tell(text.ToString());
            }
            RefreshAfterChange();
        }

        /// The conversion's four lines (cmd_downgrade_state's), each only where its count is above 0 or its flag is 1:
        /// rows, made final, conversations off, unfollowed off, observe only paused, as PickLine read them - integers.
        private void AppendConverted(StringBuilder text, int[] converted)
        {
            if (converted == null || converted.Length != 5) return;
            if (converted[1] > 0)
                text.Append(Environment.NewLine).Append(S("pick.converted.made_final", "{n} continuation(s) that may already have gone to Codex were made final and are never sent again.", "n", converted[1]));
            if (converted[2] > 0)
                text.Append(Environment.NewLine).Append(S("pick.converted.conversations_off", "{n} conversation(s) that waited for you were switched off; switch them back on when you want them to resume.", "n", converted[2]));
            if (converted[3] > 0)
                text.Append(Environment.NewLine).Append(S("pick.converted.unfollowed_off", "{n} conversation(s) whose continuation Codex may still deliver were switched off; switch them back on when you want them to resume.", "n", converted[3]));
            if (converted[4] == 1)
                text.Append(Environment.NewLine).Append(S("pick.converted.observe_paused", "Observe only became a pause: resume recovery when you want it to send."));
        }

        // ------------------------------------------------------------------ the parsers
        /// Any version this product publishes: a release from three integers with no leading zero, or a pre-release by
        /// PrereleaseRule - the rule the bootstrap rebuilds a version by (Get-ChosenVersion), so nothing a command line
        /// reads as more ever reaches one.
        internal static readonly System.Text.RegularExpressions.Regex VersionRule =
            new System.Text.RegularExpressions.Regex(
                @"^(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})(-(alpha|beta)(\.([2-9]|[1-9][0-9]{1,2}))?)?\z",
                System.Text.RegularExpressions.RegexOptions.CultureInvariant);

        private static readonly string[] PickReasons = {
            "no-archive", "no-checksum", "edition-first", "managed-policy", "older-prerelease", "not-offered" };
        private static readonly string[] PickRefusals = {
            "installed", "unreadable", "needs-force", "force-not-needed", "changed", "busy", "watcher-running", "state" };

        /// The -Versions answer: "listed" with its rows (version, edition, answer, words or reason) and its last line's
        /// installed version, edition, newest release or "-", floor and editions' start (both without their `v`);
        /// "unavailable" where GitHub could not be asked (the line, exit 12, no row); otherwise "unreadable", with no
        /// row - a word outside the closed sets, a malformed or repeated line, or a line and a code that disagree.
        internal static string VersionsLines(string printed, int code, out List<string[]> rows, out string[] listed)
        {
            rows = new List<string[]>();
            listed = null;
            var found = new List<string[]>();
            string end = null;
            int ends = 0;
            foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
            {
                string line = raw.Trim();
                if (line.StartsWith("version: ", StringComparison.Ordinal))
                {
                    string[] parts = line.Substring("version: ".Length).Split(' ');
                    if (ends > 0 || parts.Length != 4) return "unreadable";
                    found.Add(parts);
                }
                else if (line.StartsWith("versions:", StringComparison.Ordinal))
                {
                    ends++;
                    end = line;
                }
            }
            if (ends != 1) return "unreadable";
            if (end == "versions: unavailable")
                return code == UpdateUnavailable && found.Count == 0 ? "unavailable" : "unreadable";
            if (code != UpdateCurrent || !end.StartsWith("versions: listed ", StringComparison.Ordinal)) return "unreadable";
            string[] last = end.Substring("versions: listed ".Length).Split(' ');
            if (last.Length != 5 || !VersionRule.IsMatch(last[0]) || !IsEdition(last[1]) ||
                (last[2] != "-" && !VersionRule.IsMatch(last[2])) ||
                !last[3].StartsWith("v", StringComparison.Ordinal) || !VersionRule.IsMatch(last[3].Substring(1)) ||
                !last[4].StartsWith("v", StringComparison.Ordinal) || !VersionRule.IsMatch(last[4].Substring(1)))
                return "unreadable";
            var seen = new HashSet<string>();
            foreach (string[] row in found)
            {
                if (!VersionRule.IsMatch(row[0]) || !IsEdition(row[1]) || !seen.Add(row[0] + " " + row[1])) return "unreadable";
                bool other = row[1] != last[1];
                if (row[2] == "installed")
                {
                    if (row[3] != "-" || row[0] != last[0] || other) return "unreadable";
                }
                else if (row[2] == "refused")
                {
                    if (Array.IndexOf(PickReasons, row[3]) < 0) return "unreadable";
                }
                else if (row[2] != "offered" || !WordsRead(row[3], row[0], row[1], other)) return "unreadable";
            }
            rows = found;
            listed = new[] { last[0], last[1], last[2], last[3].Substring(1), last[4].Substring(1) };
            return "listed";
        }

        /// An offered row's words: each once, exactly one of newer|older|same, release|prerelease and kept|convert3,
        /// and any of latest, edition, advanced-off - and agreeing with the row: prerelease exactly for a version with a
        /// suffix, latest only for a release, edition exactly for the other edition, same only with it, advanced-off
        /// only in the advanced edition.
        private static bool WordsRead(string detail, string version, string edition, bool other)
        {
            var seen = new HashSet<string>();
            int order = 0, kind = 0, schema = 0;
            foreach (string word in detail.Split(','))
            {
                if (!seen.Add(word)) return false;
                if (word == "newer" || word == "older" || word == "same") order++;
                else if (word == "release" || word == "prerelease") kind++;
                else if (word == "kept" || word == "convert3") schema++;
                else if (word != "latest" && word != "edition" && word != "advanced-off") return false;
            }
            if (order != 1 || kind != 1 || schema != 1) return false;
            if (seen.Contains("prerelease") != (version.IndexOf('-') >= 0)) return false;
            if (seen.Contains("latest") && seen.Contains("prerelease")) return false;
            if (seen.Contains("edition") != other) return false;
            if (seen.Contains("same") && !other) return false;
            if (seen.Contains("advanced-off") && edition != "advanced") return false;
            return true;
        }

        private static bool IsEdition(string word)
        {
            return word == "standard" || word == "advanced";
        }

        /// The -Pick answer: "installed" (exit 0 after the `pick: offered` line, with `installed` its version and
        /// edition), "refused" (exit 15, `reason` the word), "unavailable" (exit 12, before any offer), or "failed" -
        /// the installer's own failure, or anything the closed grammar does not hold. `converted` is the `pick: state
        /// converted` line's five integers whenever it was printed and read - rows, made final, conversations off,
        /// unfollowed off, and 0 or 1 for observe only paused - so a failure after the conversion still says it.
        internal static string PickLine(string printed, int code, out string reason, out int[] converted, out string installed)
        {
            reason = null;
            converted = null;
            installed = null;
            bool offered = false, bad = false;
            string end = null;
            int ends = 0;
            foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
            {
                string line = raw.Trim();
                if (!line.StartsWith("pick: ", StringComparison.Ordinal)) continue;
                string rest = line.Substring("pick: ".Length);
                if (rest.StartsWith("offered ", StringComparison.Ordinal))
                {
                    if (offered || ends > 0 || !OfferedWords(rest.Substring("offered ".Length))) bad = true;
                    offered = true;
                }
                else if (rest.StartsWith("state converted ", StringComparison.Ordinal))
                {
                    int[] counts = Counts(rest.Substring("state converted ".Length));
                    if (counts == null || converted != null || !offered || ends > 0) bad = true;
                    if (counts != null && converted == null) converted = counts;
                }
                else if (rest == "unavailable" || rest.StartsWith("refused ", StringComparison.Ordinal) ||
                         rest.StartsWith("installed ", StringComparison.Ordinal))
                {
                    ends++;
                    end = rest;
                }
                else bad = true;
            }
            if (bad || ends != 1) return "failed";
            if (end == "unavailable") return code == UpdateUnavailable && !offered && converted == null ? "unavailable" : "failed";
            if (end.StartsWith("refused ", StringComparison.Ordinal))
            {
                string word = end.Substring("refused ".Length);
                if (code != PickRefusedCode || converted != null || Array.IndexOf(PickRefusals, word) < 0) return "failed";
                reason = word;
                return "refused";
            }
            string[] parts = end.Substring("installed ".Length).Split(' ');
            if (code != 0 || !offered || parts.Length != 2 || !VersionRule.IsMatch(parts[0]) || !IsEdition(parts[1])) return "failed";
            installed = parts[0] + " " + parts[1];
            return "installed";
        }

        /// The `pick: offered` line's words, held to the closed set an offered row's are (WordsRead) without the row.
        private static bool OfferedWords(string detail)
        {
            foreach (string word in detail.Split(','))
                if (Array.IndexOf(new[] { "newer", "older", "same", "release", "prerelease", "kept", "convert3", "latest",
                                          "edition", "advanced-off" }, word) < 0) return false;
            return detail.Length > 0;
        }

        /// Five whole numbers of at most nine digits, the last 0 or 1, or null: never text where a count is said.
        private static int[] Counts(string text)
        {
            string[] parts = text.Split(' ');
            if (parts.Length != 5) return null;
            var counts = new int[5];
            for (int i = 0; i < 5; i++)
            {
                if (parts[i].Length == 0 || parts[i].Length > 9) return null;
                foreach (char digit in parts[i])
                    if (digit < '0' || digit > '9') return null;
                counts[i] = int.Parse(parts[i], NumberStyles.None, CultureInfo.InvariantCulture);
            }
            return counts[4] == 0 || counts[4] == 1 ? counts : null;
        }
    }
}

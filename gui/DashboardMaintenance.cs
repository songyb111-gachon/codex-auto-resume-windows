// Codex Auto Resume - Diagnostics' own actions: export, stop, logs, repair and update.
//
// Each runs a process and reports what it did in words the person can act on, which is why
// they are together, and apart from the page that shows them.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Forms.Automation;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private void ExportDiagnostics()
        {
            string target;
            using (var save = new SaveFileDialog())
            {
                save.Filter = "JSON (*.json)|*.json";
                save.FileName = "codex-auto-resume-diagnostics-" +
                                DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".json";
                // The export never replaces a file, so the dialog does not offer to either.
                save.OverwritePrompt = false;
                if (save.ShowDialog(this) != DialogResult.OK) return;
                target = save.FileName;
            }
            if (File.Exists(target))
            {
                Tell(S("diag.export_exists", "That file already exists; choose a new name."));
                return;
            }
            CallAsync("diagnostics", "{\"path\":" + Json.Escape(target) + "}", delegate(Dictionary<string, object> reply)
            {
                if (Ok(reply))
                    Tell(S("diag.export_done", "Diagnostics saved."));
                else Report(reply);
            });
        }

        private void StopWatcher()
        {
            if (!Confirm(S("confirm.stop_watcher",
                           "Stop the watcher? It finishes the check it is in and then stops. Nothing waiting is lost, and nothing is recovered until it runs again."),
                         S("action.stop_watcher", "Stop watcher"))) return;
            CallAsync("stop-watcher", null, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply)) { Report(reply); RefreshAfterChange(); return; }
                // What the single-instance mutex actually said. "It let go" and "nobody could
                // tell" are different answers, and only one of them means it is safe to
                // replace the files underneath it - so they get different sentences.
                string state = Str(Map(reply, "result"), "state") ?? "unknown";
                string text = state == "stopped" ? S("diag.stop_stopped", "The watcher stopped.")
                            : state == "still-finishing" ? S("diag.stop_finishing", "The watcher is finishing the check it is in, and stops when that is done.")
                            : state == "not-running" ? S("diag.stop_not_running", "The watcher was not running.")
                            : S("diag.stop_unknown", "Whether the watcher stopped could not be told.");
                Tell(text);
                RefreshAfterChange();
            });
        }

        private void OpenLogs()
        {
            string logs = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs");
            if (!Directory.Exists(logs)) return;
            try { Process.Start("explorer.exe", "\"" + logs + "\""); }
            catch (Exception error) { Report(Failure(error)); }
        }

        // Long enough for a setup that is doing real work on a slow machine, and short
        // enough that the window says something before a person gives up on it.
        private const int RepairMilliseconds = 120000;

        /// v0.6.17: this window stayed inside another app's private view of Windows (HostApp.StuckInside), where
        /// Repair, an update and another version would register the installation out of Windows' sight. Says so, and
        /// true: the action does not start.
        private bool RefusedInside()
        {
            if (HostApp.StuckInside == null) return false;
            Tell(S("diag.inside_app",
                   "This Dashboard may have been opened from inside {app}. If so, Windows would keep what this sets up inside that app: the entry in Settings > Apps, the start at sign-in, the notifications' name, the link handler and the Start menu entry. Open the Dashboard from the Start menu and do this there.",
                   "app", HostApp.Name(HostApp.StuckInside)));
            return true;
        }

        private void Repair()
        {
            if (RefusedInside()) return;
            if (!Confirm(S("confirm.repair", "Run setup again to repair the Windows registrations?"),
                         S("action.repair", "Repair installation"))) return;
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string python = Path.Combine(root, "runtime", "python.exe");
            string setup = Path.Combine(root, "app", "scripts", "plugin_setup.py");
            SetBusy(true);
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string outcome, detail;
                RunRepair(root, python, setup, out outcome, out detail);
                bool noEntry = outcome == "done" &&
                               EntryCannotBeWritten(root, Environment.GetEnvironmentVariable("USERPROFILE"));
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    ReportRepair(outcome, detail, noEntry);
                    RefreshAfterChange();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// Runs setup over this installation and says which of five things happened:
        /// done, busy, incomplete, running or failed. They are five different sentences
        /// because they ask for five different things from the person, and one of them -
        /// a setup that is still working - is not a failure at all.
        private static void RunRepair(string root, string python, string setup,
                                      out string outcome, out string detail)
        {
            outcome = "failed";
            detail = "";
            // Nothing to run: this installation is missing the files setup is made of, so
            // saying "setup did not finish" would describe the wrong problem.
            if (!File.Exists(python) || !File.Exists(setup)) { outcome = "incomplete"; return; }
            // The installer holds this while it works, and its own repair branch takes it
            // for the same reason: two processes rewriting the same registrations at once
            // is the one case the lock exists for. An abandoned lock means its holder died,
            // so it is taken rather than read as contention.
            using (var gate = new System.Threading.Mutex(false, "Local\\CodexAutoResume.Install"))
            {
                bool held = false;
                try { held = gate.WaitOne(0); }
                catch (System.Threading.AbandonedMutexException) { held = true; }
                if (!held) { outcome = "busy"; return; }
                try
                {
                    // --keep-state: a repair repairs. It re-registers what is broken and
                    // starts a stopped watcher, and never undoes a pause or adds back a
                    // sign-in start the person switched off - a plain `setup` does both, as
                    // a first install should.
                    var info = new ProcessStartInfo(python, Bridge.NoRemoteDebug + Bridge.Quote(setup) + " setup --keep-state");
                    info.UseShellExecute = false;
                    // The installation this window belongs to. Setup resolves its target from
                    // this variable, so without it Repair would repair whichever installation
                    // the environment happens to point at - not the one being repaired.
                    info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;
                    info.CreateNoWindow = true;
                    info.RedirectStandardOutput = true;
                    info.RedirectStandardError = true;
                    using (Process process = Process.Start(info))
                    {
                        // Both pipes read without blocking on either, so a child that fills
                        // one of them cannot stall the wait - and the wait is what decides
                        // between "still working" and "failed".
                        Task<string> output = process.StandardOutput.ReadToEndAsync();
                        Task<string> failure = process.StandardError.ReadToEndAsync();
                        if (!process.WaitForExit(RepairMilliseconds))
                        {
                            // Left running on purpose: it is still registering things, and
                            // killing it halfway is how an installation ends up half written.
                            // The lock goes back now rather than being held by a thread that
                            // has stopped watching, which the installer's own comment allows
                            // for by treating an abandoned lock as free.
                            outcome = "running";
                            return;
                        }
                        output.Wait(5000);
                        failure.Wait(5000);
                        detail = Tail((output.IsCompleted ? output.Result : "") + "\n" +
                                      (failure.IsCompleted ? failure.Result : ""));
                        // 2 means everything was done but the watcher was not yet seen
                        // running - and it is also what setup exits with when it rejects an
                        // argument it does not know, such as --keep-state on a copy older
                        // than this window. So a 2 counts only with the line setup prints
                        // when it has finished its work.
                        if (process.ExitCode == 0 ||
                            (process.ExitCode == 2 &&
                             output.IsCompleted && output.Result.IndexOf("state: ", StringComparison.Ordinal) >= 0))
                            outcome = "done";
                    }
                }
                catch (Exception error) { detail = error.Message; }
                finally { gate.ReleaseMutex(); }
            }
        }

        /// The last few lines setup printed, which is where it says what went wrong. The
        /// line naming the installation folder is dropped: it is the one line that is a
        /// path rather than a reason.
        private static string Tail(string output)
        {
            var lines = new List<string>();
            foreach (string line in (output ?? "").Replace("\r", "").Split('\n'))
            {
                string trimmed = line.Trim();
                if (trimmed.Length == 0 || trimmed.StartsWith("state: ", StringComparison.Ordinal)) continue;
                lines.Add(trimmed);
            }
            var last = new List<string>();
            for (int i = Math.Max(0, lines.Count - 3); i < lines.Count; i++) last.Add(lines[i]);
            string text = string.Join(Environment.NewLine, last.ToArray());
            return text.Length > 400 ? text.Substring(text.Length - 400) : text;
        }

        // ------------------------------------------------------------------ updates
        // Nothing here runs unless the button is pressed. There is no timer, no check on
        // open and no check on a schedule: an update check is a request to github.com, and
        // a product that makes one without being asked has made the person's machine talk
        // to a server they did not choose to talk to.
        //
        // The four answers and their codes are scripts/bootstrap.ps1's, read back rather
        // than re-derived here. In particular "could not ask" is its own answer: a machine
        // with no network must never be told it is up to date, which is the one wrong thing
        // an update check can say.
        private const int UpdateCurrent = 0;
        private const int UpdateAvailable = 10;
        private const int UpdateLocalNewer = 11;
        private const int UpdateUnavailable = 12;
        // v0.6.16: the person put the update off on its Notes page (the bootstrap's -AskFirst, `update: later`).
        private const int UpdateLater = 16;
        // One request against a redirect. An install downloads a release and runs the
        // installer over it, on whatever connection the machine has.
        private const int CheckMilliseconds = 120000;
        private const int UpdateMilliseconds = 1200000;

        private void CheckForUpdates()
        {
            // v0.6.11: an administrator's DisableUpdateCheck (managed.py) - the button is greyed, and
            // nothing is asked however this is reached.
            if (updatesManaged) return;
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string script = Path.Combine(root, "app", "scripts", "bootstrap.ps1");
            if (!File.Exists(script))
            {
                diagUpdate.Text = S("diag.update_unavailable", "could not be checked");
                ReportUpdate("incomplete", null, null, null, null);
                return;
            }
            SetBusy(true);
            diagUpdate.Text = S("diag.update_asking", "asking...");
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string answer, current, latest, detail, compatibility, prerelease, releases;
                RunBootstrap(root, script, "-CheckOnly", CheckMilliseconds,
                             out answer, out current, out latest, out detail, out compatibility, out prerelease,
                             out releases);
                Dictionary<string, object> live = CheckAfterRefresh(bridge, compatibility);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    diagUpdate.Text = UpdateFact(answer, current, latest);
                    // The check's second request, once github.com had answered: the Codex compatibility data, said on its
                    // card before the update's own answer is.
                    ReportCompatibilityLine(compatibility, live);
                    if (answer == "available") OfferUpdate(root, script, current, latest);
                    // v0.6.11: a pre-release newer than both, offered where there is no release to offer first - and
                    // installed only on a yes. Not now leaves the answer on the card as it stands.
                    else if ((answer == "current" || answer == "newer-local") && prerelease != null)
                        OfferPrerelease(root, script, prerelease);
                    else ReportUpdate(answer, current, latest, detail, releases);
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        private void OfferUpdate(string root, string script, string current, string latest)
        {
            if (!Confirm(S("confirm.update",
                           "Version {latest} has been published. Download and install it? Your settings, your pause and everything waiting are kept.",
                           "latest", latest).Replace("{current}", current ?? ""),
                         S("action.install", "Install")))
            {
                ReportUpdate("available", current, latest, null, null);
                return;
            }
            InstallUpdate(root, script, "-Update", latest);
        }

        /// A pre-release the check found (PrereleaseLine), offered for what it is: which version, that it is a
        /// pre-release and tested less than a release. Not now is the answer Enter gives. A yes runs the bootstrap's
        /// -Version with that version, which installs it only over an older one, in this edition, with its state kept,
        /// and verified by the checksum published beside it.
        private void OfferPrerelease(string root, string script, string prerelease)
        {
            if (!Dialog(S("confirm.prerelease",
                          "Version {version} is a pre-release: published before its release is finished, and tested less than a release. Install it? It is checked against its published checksum before anything runs, it stays in the edition you have, and your settings, your pause, everything waiting and the sign-in choice are all kept.",
                          "version", prerelease),
                        S("action.install_prerelease", "Install pre-release"), S("action.not_now", "Not now"))) return;
            InstallUpdate(root, script, "-Version " + prerelease, prerelease);
        }

        /// Runs the bootstrap to install one version - `-Update` for the release the check found, `-Version <v>` for the
        /// pre-release a person said yes to - and says how it went.
        ///
        /// v0.6.16: in the installer window (InstallerWindow), as a setup program installs: how far it is, from the
        /// lines the bootstrap and the installer print (Heard), then whether it finished, with its code and its log -
        /// and, where it did, "Open the Dashboard", which opens this installation's new Dashboard in place of this one.
        private void InstallUpdate(string root, string script, string flag, string version)
        {
            // The check has said what it found, on the card; the install is what would stay inside another app.
            if (RefusedInside()) return;
            // Who is running now. `code_version` is no use for this: an old watcher reads the
            // version out of the files under it and starts reporting the new one the moment
            // they are replaced, so only a start time that moved says a watcher restarted.
            string before = WatcherIdentity();
            SetBusy(true);
            // The installer's request to close (WatchForUpdate) is not this window's to answer while it runs its own.
            updatingHere = true;
            diagUpdate.Text = S("diag.update_installing", "installing...");
            string answer = "failed", from = null, to = null, detail = "", compatibility = null, prerelease = null,
                   releases = null;
            string app = Path.Combine(root, "app");
            string edition = InstallerFlow.EditionOfSource(Path.Combine(app, "src"));
            var flow = new InstallerFlow(InstallerFlow.Update, root, edition, edition, version);
            // v0.6.16, the owner: an update shows itself - from what to what, and what is new, before it installs.
            flow.From = InstallerFlow.VersionOf(ReadText(Path.Combine(Path.Combine(app, ".codex-plugin"), "plugin.json")));
            var words = new InstallerWords(strings, openedLanguage);
            InstallerWindow window = null;
            window = new InstallerWindow(flow, words, null,
                delegate(InstallerFlow answered, Action<string> line, Action<double> unpacked)
                {
                    Heard = line;
                    // The verified download's changelog, in the person's language where the archive carries it.
                    Asked = delegate(string docs)
                    {
                        string file = InstallerNotes.FileFor(docs, words.Language);
                        return window.Ask(InstallerNotes.Section(ReadText(file), version));
                    };
                    try
                    {
                        RunBootstrap(root, script, flag + " -AskFirst", UpdateMilliseconds,
                                     out answer, out from, out to, out detail, out compatibility, out prerelease,
                                     out releases);
                    }
                    finally { Heard = null; Asked = null; }
                    return answer == "installed" ? 0 : answer == "later" ? InstallerFlow.Later
                         : answer == "running" ? InstallerFlow.StillRunning
                         : answer == "incomplete" ? InstallerFlow.NotStarted : HeardCode == 0 ? 1 : HeardCode;
                }, null, Font);
            window.ShowDialog(this);
            updatingHere = false;
            if (answer == "later")
            {
                // Put off: the release is still there to install, as the check found it.
                SetBusy(false);
                diagUpdate.Text = UpdateFact("available", from, to);
                return;
            }
            // v0.6.16, the owner: what ran before an update runs again on the new version by itself - this Dashboard
            // too. The installer starts the watcher again (install.ps1, --watcher-was-stopped); the new Dashboard is
            // opened here, and this one, the old version's, closes.
            if (answer == "installed" && window.OpenDashboard && OpenNewDashboard(root))
            {
                Close();
                return;
            }
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> live = CheckAfterRefresh(bridge, compatibility);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    ReportCompatibilityLine(compatibility, live);
                    if (answer == "installed") AfterUpdate(before, version, detail);
                    // The window has said what happened, with the log: the card keeps the one-line fact.
                    else diagUpdate.Text = UpdateFact(answer, from, to);
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// The update's lines, for the installer window: told each line StartBootstrap reads while it is set, on the
        /// worker the window runs the update on, and the bootstrap's exit code once it has ended (HeardCode).
        [ThreadStatic] private static Action<string> Heard;
        /// The update's question, with -AskFirst: told the changelog's folder of the verified download, it shows what is
        /// new and answers whether to go on (InstallerWindow.Ask); the answer is written to the bootstrap's input.
        [ThreadStatic] private static Func<string, bool> Asked;

        private static string ReadText(string path)
        {
            try { return path != null && File.Exists(path) ? File.ReadAllText(path, new UTF8Encoding(false)).TrimStart('\uFEFF') : null; }
            catch (Exception) { return null; }
        }
        [ThreadStatic] private static int HeardCode;

        /// This installation's Dashboard, the new version the update has just put in place, started by its full path -
        /// in front, which this window, where Open the Dashboard was just pressed, lets it be (v0.6.17).
        private static bool OpenNewDashboard(string root)
        {
            string exe = Path.Combine(root, "CodexAutoResumeSettings.exe");
            if (!File.Exists(exe)) return false;
            return HostApp.StartInFront(exe, null, root);
        }

        /// The identity of the process holding the watcher's heartbeat, or null where there
        /// is none to read. Two fields, because a pid on its own is reused by Windows.
        private string WatcherIdentity()
        {
            var watcher = Map(Map(snapshot, "status"), "watcher");
            if (watcher == null) return null;
            object pid = Get(watcher, "pid");
            object started = Get(watcher, "started_at");
            if (pid == null || started == null) return null;
            return Convert.ToString(pid, CultureInfo.InvariantCulture) + "@" +
                   Convert.ToString(started, CultureInfo.InvariantCulture);
        }

        /// Says what happened, and then whether the watcher actually changed hands. The
        /// installer asks the old watcher to stop and starts a new one; if the old one is
        /// still there, the files under it are now a different version from the code it is
        /// running, and that is worth saying out loud rather than reporting a clean success.
        private void AfterUpdate(string before, string latest, string detail)
        {
            diagUpdate.Text = S("diag.update_installed", "v{version} installed", "version", latest);
            CallAsync("status", null, delegate(Dictionary<string, object> reply)
            {
                string handover = "unknown";
                if (Ok(reply))
                {
                    var status = Map(reply, "result");
                    if (status == null) status = Map(reply, "status");
                    var watcher = Map(status, "watcher");
                    if (watcher != null)
                    {
                        object pid = Get(watcher, "pid");
                        object started = Get(watcher, "started_at");
                        string now = pid == null || started == null ? null
                                   : Convert.ToString(pid, CultureInfo.InvariantCulture) + "@" +
                                     Convert.ToString(started, CultureInfo.InvariantCulture);
                        if (now != null && before != null) handover = now == before ? "same" : "restarted";
                        else if (now != null && before == null) handover = "restarted";
                    }
                }
                string text = S("diag.update_done", "Version {version} is installed.", "version", latest);
                text += Environment.NewLine + Environment.NewLine +
                        (handover == "restarted"
                            ? S("diag.update_watcher_restarted", "The watcher was restarted and is running the new version.")
                         : handover == "same"
                            ? S("diag.update_watcher_same", "The watcher that is running is still the one from before the update, so it is running the old code. Stop it and start it again from this page.")
                            : S("diag.update_watcher_unknown", "Whether the watcher restarted could not be told."));
                text += Environment.NewLine + Environment.NewLine +
                        S("diag.update_reopen", "Close this window and open it again so it runs the new version.");
                Tell(text);
                RefreshAfterChange();
            });
        }

        /// Runs this installation's scripts/bootstrap.ps1 with `flag` and waits for it at most `milliseconds` - not
        /// counting the time the update's Notes page waits for the person's answer (InstallerClock, v0.6.16):
        /// "done", with what it printed, what it wrote to its error stream and its exit code; "incomplete" where
        /// Windows PowerShell is not there to run it; "running" where it has not finished - never killed, for it
        /// may be part way through replacing an installation, and half an installation is worse than a slow one;
        /// "failed" where it could not be started, with why in `errors`. Every caller of the bootstrap comes
        /// through here (v0.6.12): the update check and its install (RunBootstrap), and Install another
        /// version...'s listing and pick (StartVersionsListing, InstallPick).
        private static string StartBootstrap(string root, string script, string flag, int milliseconds,
                                             out string printed, out string errors, out int code)
        {
            printed = "";
            errors = "";
            code = -1;
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                             "WindowsPowerShell", "v1.0", "powershell.exe");
            // By full path, never by bare name: a `powershell.exe` earlier on PATH is the
            // whole of v0.5.7's system-executable fix, and this is a new caller of one.
            if (!File.Exists(powershell)) return "incomplete";
            try
            {
                var info = new ProcessStartInfo(powershell,
                    "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " +
                    Bridge.Quote(script) + " " + flag);
                info.UseShellExecute = false;
                // The installation this window belongs to, not whichever one the environment
                // happens to name.
                info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;
                // This window, which waits for the bootstrap: the installer leaves it open (install.ps1,
                // Get-OwnedDashboardProcess), and it opens the new version itself.
                info.EnvironmentVariables["CODEX_AUTO_RESUME_UPDATING_DASHBOARD"] =
                    Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture);
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                // How much of each step is done, for the installer window's bar (InstallerProgress.Variable) - only
                // where that window reads the lines; every other caller gets exactly the output it always did.
                if (Heard != null) info.EnvironmentVariables[InstallerProgress.Variable] = "1";
                else info.EnvironmentVariables.Remove(InstallerProgress.Variable);
                // The update's answer goes in on the input (-AskFirst); nothing else reads it.
                if (Asked != null) info.RedirectStandardInput = true;
                // UTF-8, as the script writes it: the setup step's lines may be Korean (issue #33).
                info.StandardOutputEncoding = Encoding.UTF8;
                info.StandardErrorEncoding = Encoding.UTF8;
                using (Process process = Process.Start(info))
                {
                    // Line by line where the installer window is told each one (Heard), whole otherwise.
                    Action<string> heard = Heard;
                    Func<string, bool> asked = Asked;
                    // The time limit, less the time the Notes page waits for the person (InstallerClock).
                    Stopwatch time = Stopwatch.StartNew();
                    var clock = new InstallerClock(milliseconds);
                    Task<string> output = heard == null ? process.StandardOutput.ReadToEndAsync()
                                        : Task.Factory.StartNew<string>(delegate
                                          {
                                              var lines = new StringBuilder();
                                              string line, notes = null;
                                              while ((line = process.StandardOutput.ReadLine()) != null)
                                              {
                                                  // A progress line is the window's alone: read, never kept.
                                                  if (!InstallerProgress.IsProgress(line)) lines.Append(line).Append('\n');
                                                  heard(line);
                                                  if (line.StartsWith("notes: ", StringComparison.Ordinal))
                                                      notes = line.Substring("notes: ".Length).Trim();
                                                  else if (asked != null && line.StartsWith("ask: ", StringComparison.Ordinal))
                                                  {
                                                      clock.Pause(time.ElapsedMilliseconds);
                                                      bool go;
                                                      try { go = asked(notes); }
                                                      finally { clock.Resume(time.ElapsedMilliseconds); }
                                                      process.StandardInput.WriteLine(go ? "install" : "later");
                                                      process.StandardInput.Flush();
                                                  }
                                              }
                                              return lines.ToString();
                                          });
                    Task<string> failure = process.StandardError.ReadToEndAsync();
                    while (!process.WaitForExit(250))
                        if (clock.Over(time.ElapsedMilliseconds)) return "running";
                    output.Wait(5000);
                    failure.Wait(5000);
                    printed = output.IsCompleted ? output.Result : "";
                    errors = failure.IsCompleted ? failure.Result : "";
                    code = process.ExitCode;
                    HeardCode = code;
                    if (heard != null && errors.Length > 0) foreach (string line in errors.Replace("\r", "").Split('\n')) heard(line);
                    return "done";
                }
            }
            catch (Exception error)
            {
                errors = error.Message;
                return "failed";
            }
        }

        /// Runs scripts/bootstrap.ps1 with one switch and reads the line it prints for a
        /// caller - and, since v0.6.5, the `compatibility:` line before it, the answer to the
        /// check's second request (CompatibilityLine; null when it made none), and since v0.6.11
        /// the `prerelease:` line of its question about pre-releases (PrereleaseLine; null when
        /// there is none), and since v0.6.17 the `releases:` line it prints where that question
        /// could not be answered (ReleasesLine; null when it was, or was not asked). The lines are
        /// the contract; the rest of the output is for a person.
        private static void RunBootstrap(string root, string script, string flag, int milliseconds,
                                         out string answer, out string current, out string latest,
                                         out string detail, out string compatibility, out string prerelease,
                                         out string releases)
        {
            answer = "failed";
            current = null;
            latest = null;
            detail = "";
            compatibility = null;
            prerelease = null;
            releases = null;
            string printed, errors;
            int code;
            string ran = StartBootstrap(root, script, flag, milliseconds, out printed, out errors, out code);
            if (ran == "incomplete" || ran == "running") { answer = ran; return; }
            if (ran != "done") { detail = errors; return; }
            detail = Tail(printed + "\n" + errors);
            compatibility = CompatibilityLine(printed);
            prerelease = PrereleaseLine(printed);
            releases = ReleasesLine(printed);
            string line = null;
            foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
            {
                string trimmed = raw.Trim();
                if (trimmed.StartsWith("update: ", StringComparison.Ordinal)) line = trimmed;
            }
            string[] words = line == null ? new string[0]
                           : line.Substring("update: ".Length).Split(' ');
            string said = words.Length > 0 ? words[0] : "";
            if (words.Length > 1) current = words[1];
            if (words.Length > 2) latest = words[2];
            // The code and the line have to agree. Either alone could be an older
            // script, a crash after printing, or an exit code Windows supplied; a
            // disagreement is not an answer and is reported as one that failed.
            if (code == UpdateCurrent && said == "current") answer = "current";
            else if (code == UpdateAvailable && said == "available") answer = "available";
            else if (code == UpdateLocalNewer && said == "newer-local") answer = "newer-local";
            else if (code == UpdateUnavailable && said == "unavailable") answer = "unavailable";
            // An install runs on past the line and exits with the installer's code.
            else if (code == 0 && said == "available") answer = "installed";
            else if (code == UpdateLater && said == "later") answer = "later";
        }

        /// The one-line fact beside "Updates" on the Health card.
        private string UpdateFact(string answer, string current, string latest)
        {
            if (answer == "current")
                return S("diag.update_current", "up to date");
            if (answer == "available")
                return S("diag.update_available", "v{version} available", "version", latest);
            if (answer == "newer-local")
                return S("diag.update_newer_local", "ahead of v{version}", "version", latest);
            if (answer == "installed")
                return S("diag.update_installed", "v{version} installed", "version", latest);
            return S("diag.update_unavailable", "could not be checked");
        }

        private void ReportUpdate(string answer, string current, string latest, string detail, string releases)
        {
            Tell(UpdateWords(answer, current, latest, detail, releases));
        }

        /// What ReportUpdate says. `releases` is the check's `releases:` line (ReleasesLine): where GitHub's list was
        /// asked for and not read, "up to date" and "ahead" are only the answer about releases, so each says that
        /// pre-releases could not be checked, and why where GitHub said (ReleasesWords) - GitHub #41, where a VPN's
        /// spent rate limit was read as "ahead of the newest published release" and nothing more. A list that was read
        /// leaves the words as they were.
        internal string UpdateWords(string answer, string current, string latest, string detail, string releases)
        {
            bool unchecked_ = releases != null && (answer == "current" || answer == "newer-local");
            string text =
                answer == "current" && unchecked_
                    ? S("diag.update_is_current_unchecked", "Version {version} is the newest published release, but pre-releases could not be checked, so a newer pre-release may have been published.", "version", current)
              : answer == "current"
                    ? S("diag.update_is_current", "Version {version} is the newest published release.", "version", current)
              : answer == "available"
                    ? S("diag.update_is_available", "Version {version} has been published.", "version", latest)
              : answer == "newer-local" && unchecked_
                    ? S("diag.update_is_newer_local_unchecked", "This build is newer than the latest release, v{version}, but pre-releases could not be checked, so a newer pre-release may have been published.", "version", latest)
              : answer == "newer-local"
                    // A development build, or a release that was withdrawn. Either way there
                    // is nothing to install, and installing would go backwards.
                    ? S("diag.update_is_newer_local", "This build is ahead of the newest published release, so there is nothing to install.")
              : answer == "unavailable"
                    ? S("diag.update_could_not_ask", "GitHub could not be asked just now. This says nothing about whether an update exists.")
              : answer == "running"
                    ? S("diag.update_running", "It is taking longer than usual and is still working. It carries on in the background; look at this page again in a few minutes.")
              : answer == "incomplete"
                    ? S("diag.update_incomplete", "Files this installation is made of are missing, so it could not be checked. Install it again from the release archive.")
                    : S("diag.update_failed", "The update check did not finish.");
            if ((answer == "failed" || answer == "unavailable") && !string.IsNullOrEmpty(detail))
                text += Environment.NewLine + Environment.NewLine + detail;
            if (unchecked_) text += Environment.NewLine + Environment.NewLine + ReleasesWords(releases);
            return text;
        }

        /// The words on the `releases:` line the bootstrap prints where GitHub's list of this repository's releases was
        /// asked for and not read (scripts/bootstrap.ps1, Write-ReleasesUnread), without its name: "unread", or
        /// "rate-limited " and when GitHub's rate limit resets - Unix seconds, or "unknown". Null when there is no such
        /// line or it says anything else. The last one counts, as the `update:` line's does.
        internal static string ReleasesLine(string printed)
        {
            string line = null;
            foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
            {
                string trimmed = raw.Trim();
                if (trimmed.StartsWith("releases: ", StringComparison.Ordinal)) line = trimmed.Substring("releases: ".Length);
            }
            if (line == "unread" || line == "rate-limited unknown") return line;
            if (line != null && line.StartsWith("rate-limited ", StringComparison.Ordinal))
            {
                string seconds = line.Substring("rate-limited ".Length);
                long value;
                if (seconds.Length >= 9 && seconds.Length <= 11 &&
                    long.TryParse(seconds, NumberStyles.None, CultureInfo.InvariantCulture, out value))
                    return line;
            }
            return null;
        }

        /// Why GitHub's list could not be read, said after the sentence it belongs to (GitHub #41): its rate limit by name,
        /// with when it resets in this PC's time where GitHub said, for "rate-limited"; "try again later" otherwise. Shared
        /// by Check for updates and Install another version..., which ask the same list.
        internal string ReleasesWords(string releases)
        {
            if (releases != null && releases.StartsWith("rate-limited ", StringComparison.Ordinal))
            {
                long seconds;
                if (long.TryParse(releases.Substring("rate-limited ".Length), NumberStyles.None, CultureInfo.InvariantCulture,
                                  out seconds))
                    return S("diag.github_rate_limited", "GitHub refused because this network has used up its limit of requests to GitHub for now (a VPN or a shared connection often does). The limit resets at {time}; try again after that.",
                             "time", ClockTime(seconds));
                return S("diag.github_rate_limited_unknown", "GitHub refused because this network has used up its limit of requests to GitHub for now (a VPN or a shared connection often does). The limit resets within an hour; try again after that.");
            }
            return S("diag.github_try_later", "Try again later.");
        }

        /// The version on the `prerelease:` line an update check prints when GitHub's list of this repository's
        /// releases has a pre-release newer than both the installed version and the newest release
        /// (scripts/bootstrap.ps1), without its `v` - or null when there is none, or the line says anything else.
        /// The last one counts, as the `update:` line's does. A yes puts the version on the bootstrap's command line,
        /// so it is held here to the pre-release rule the bootstrap rebuilds it by: three numbers with no leading
        /// zero, `-alpha` or `-beta`, and a stage's number from 2 to 999 - nothing a command line reads as more.
        internal static string PrereleaseLine(string printed)
        {
            string line = null;
            foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
            {
                string trimmed = raw.Trim();
                if (trimmed.StartsWith("prerelease: ", StringComparison.Ordinal)) line = trimmed.Substring("prerelease: ".Length);
            }
            if (line == null || !line.StartsWith("v", StringComparison.Ordinal)) return null;
            string version = line.Substring(1);
            return PrereleaseRule.IsMatch(version) ? version : null;
        }

        private static readonly System.Text.RegularExpressions.Regex PrereleaseRule =
            new System.Text.RegularExpressions.Regex(
                @"^(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})-(alpha|beta)(\.([2-9]|[1-9][0-9]{1,2}))?\z",
                System.Text.RegularExpressions.RegexOptions.CultureInvariant);

        /// GitHub #43: true when `root` is the ordinary home (.codex-auto-resume in the profile, install.ps1's
        /// Test-DefaultHome) and the uninstaller kept in it for the entry in Settings > Apps is missing - so setup wrote no
        /// entry (addremove.register writes one only where it is), and Repair cannot make one: the installation holds no
        /// other copy of install.ps1 (the archive's install\ folder is removed once it has run, and payload\app carries
        /// none). An update before v0.6.17 started from the Dashboard kept none, and a pick of a version before v0.6.16
        /// removes it. A home placed elsewhere never has one, as documented, and gets no sentence for it. A folder or
        /// file that is a link or a junction counts as missing, as addremove.kept_uninstaller_present reads it.
        internal static bool EntryCannotBeWritten(string root, string profile)
        {
            if (string.IsNullOrWhiteSpace(root) || string.IsNullOrWhiteSpace(profile)) return false;
            try
            {
                string ordinary = Path.GetFullPath(InstallerFlow.HomeFrom(null, profile)).TrimEnd('\\');
                string here = Path.GetFullPath(root).TrimEnd('\\');
                if (!string.Equals(ordinary, here, StringComparison.OrdinalIgnoreCase)) return false;
                string folder = Path.Combine(here, "uninstall");
                string script = Path.Combine(folder, "install.ps1");
                if (!Directory.Exists(folder) || !File.Exists(script)) return true;
                return ((File.GetAttributes(folder) | File.GetAttributes(script)) & FileAttributes.ReparsePoint) != 0;
            }
            catch (Exception) { return false; }
        }

        private void ReportRepair(string outcome, string detail, bool noEntry)
        {
            string text = outcome == "done" ? S("diag.repair_done", "Setup finished.")
                        : outcome == "running" ? S("diag.repair_running", "Setup is taking longer than usual and is still working. It carries on in the background; look at this page again in a minute.")
                        : outcome == "busy" ? S("diag.repair_busy", "An installation or a repair is already running. Try again once it has finished.")
                        : outcome == "incomplete" ? S("diag.repair_incomplete", "Files this installation is made of are missing, so setup could not run. Install it again from the release archive.")
                        : S("diag.repair_failed", "Setup did not finish.");
            // What setup printed, but only where it is the answer: for the outcomes above it
            // would be noise beside a sentence that already says what to do.
            if (outcome == "failed" && !string.IsNullOrEmpty(detail))
                text += Environment.NewLine + Environment.NewLine + detail;
            // Said rather than left out (GitHub #43): a repair that wrote everything else wrote no entry here.
            if (noEntry)
                text += Environment.NewLine + Environment.NewLine +
                        S("diag.repair_no_entry", "Settings > Apps still has no entry for this installation: the copy of the installer its Uninstall button runs is missing, and Repair has no copy to put back. Run this version's Setup program and choose Repair, or install the next update: either one puts the copy and the entry back.");
            Tell(text);
        }
    }
}

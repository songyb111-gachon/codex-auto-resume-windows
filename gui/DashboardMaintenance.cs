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

        private void Repair()
        {
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
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    ReportRepair(outcome, detail);
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
                    var info = new ProcessStartInfo(python, Bridge.Quote(setup) + " setup --keep-state");
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
        // One request against a redirect. An install downloads a release and runs the
        // installer over it, on whatever connection the machine has.
        private const int CheckMilliseconds = 120000;
        private const int UpdateMilliseconds = 1200000;

        private void CheckForUpdates()
        {
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string script = Path.Combine(root, "app", "scripts", "bootstrap.ps1");
            if (!File.Exists(script))
            {
                diagUpdate.Text = S("diag.update_unavailable", "could not be checked");
                ReportUpdate("incomplete", null, null, null);
                return;
            }
            SetBusy(true);
            diagUpdate.Text = S("diag.update_asking", "asking...");
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string answer, current, latest, detail, compatibility;
                RunBootstrap(root, script, "-CheckOnly", CheckMilliseconds,
                             out answer, out current, out latest, out detail, out compatibility);
                Dictionary<string, object> live = CheckAfterRefresh(bridge, compatibility);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    diagUpdate.Text = UpdateFact(answer, current, latest);
                    // The check's second request, once github.com had answered: the Codex compatibility data, said on its
                    // card before the update's own answer is.
                    ReportCompatibilityLine(compatibility, live);
                    if (answer == "available") OfferUpdate(root, script, current, latest);
                    else ReportUpdate(answer, current, latest, detail);
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
                ReportUpdate("available", current, latest, null);
                return;
            }
            // Who is running now. `code_version` is no use for this: an old watcher reads the
            // version out of the files under it and starts reporting the new one the moment
            // they are replaced, so only a start time that moved says a watcher restarted.
            string before = WatcherIdentity();
            SetBusy(true);
            diagUpdate.Text = S("diag.update_installing", "installing...");
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string answer, from, to, detail, compatibility;
                RunBootstrap(root, script, "-Update", UpdateMilliseconds,
                             out answer, out from, out to, out detail, out compatibility);
                Dictionary<string, object> live = CheckAfterRefresh(bridge, compatibility);
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    ReportCompatibilityLine(compatibility, live);
                    if (answer == "installed") AfterUpdate(before, latest, detail);
                    else
                    {
                        diagUpdate.Text = UpdateFact(answer, from, to);
                        ReportUpdate(answer, from, to, detail);
                    }
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
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

        /// Runs scripts/bootstrap.ps1 with one switch and reads the line it prints for a
        /// caller - and, since v0.6.5, the `compatibility:` line before it, the answer to the
        /// check's second request (CompatibilityLine; null when it made none). The lines are
        /// the contract; the rest of the output is for a person.
        private static void RunBootstrap(string root, string script, string flag, int milliseconds,
                                         out string answer, out string current, out string latest,
                                         out string detail, out string compatibility)
        {
            answer = "failed";
            current = null;
            latest = null;
            detail = "";
            compatibility = null;
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                             "WindowsPowerShell", "v1.0", "powershell.exe");
            // By full path, never by bare name: a `powershell.exe` earlier on PATH is the
            // whole of v0.5.7's system-executable fix, and this is a new caller of one.
            if (!File.Exists(powershell)) { answer = "incomplete"; return; }
            try
            {
                var info = new ProcessStartInfo(powershell,
                    "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " +
                    Bridge.Quote(script) + " " + flag);
                info.UseShellExecute = false;
                // The installation this window belongs to, not whichever one the environment
                // happens to name.
                info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                using (Process process = Process.Start(info))
                {
                    Task<string> output = process.StandardOutput.ReadToEndAsync();
                    Task<string> failure = process.StandardError.ReadToEndAsync();
                    if (!process.WaitForExit(milliseconds))
                    {
                        // Not killed: it may be part way through replacing an installation,
                        // and half an installation is worse than a slow one.
                        answer = "running";
                        return;
                    }
                    output.Wait(5000);
                    failure.Wait(5000);
                    string printed = output.IsCompleted ? output.Result : "";
                    detail = Tail(printed + "\n" + (failure.IsCompleted ? failure.Result : ""));
                    compatibility = CompatibilityLine(printed);
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
                    int code = process.ExitCode;
                    // The code and the line have to agree. Either alone could be an older
                    // script, a crash after printing, or an exit code Windows supplied; a
                    // disagreement is not an answer and is reported as one that failed.
                    if (code == UpdateCurrent && said == "current") answer = "current";
                    else if (code == UpdateAvailable && said == "available") answer = "available";
                    else if (code == UpdateLocalNewer && said == "newer-local") answer = "newer-local";
                    else if (code == UpdateUnavailable && said == "unavailable") answer = "unavailable";
                    // An install runs on past the line and exits with the installer's code.
                    else if (code == 0 && said == "available") answer = "installed";
                }
            }
            catch (Exception error) { detail = error.Message; }
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

        private void ReportUpdate(string answer, string current, string latest, string detail)
        {
            string text =
                answer == "current"
                    ? S("diag.update_is_current", "Version {version} is the newest published release.", "version", current)
              : answer == "available"
                    ? S("diag.update_is_available", "Version {version} has been published.", "version", latest)
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
            Tell(text);
        }

        private void ReportRepair(string outcome, string detail)
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
            Tell(text);
        }
    }
}

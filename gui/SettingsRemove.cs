// Codex Auto Resume - removing the installation from Windows' list of installed programs, in the installer window.
//
// The entry in Add or remove programs (src/codex_auto_resume/addremove.py) runs this program with
// `--uninstall <home>\uninstall\install.ps1`: the installer's kept copy of itself, the one Uninstall.cmd runs. The
// window (InstallerWindow) asks whether to delete the settings and the recovery history too (-Purge), runs that
// script's uninstall with -Silent and no window of its own, and shows how far it is, then whether it finished and
// with which code, and its log.
//
// The uninstall removes this very program, and Windows does not let a running program's file be deleted. So the
// program in the installation only copies itself into a folder of its own in the temporary folder, starts that
// copy, and ends; the copy waits for it to have ended before it runs anything, and once its window is closed, asks
// Windows PowerShell - by its full path, with a constant script and the folder in its environment - to remove that
// folder once the copy itself has ended. The copy reads its words, theme and edition from the installation before
// it is removed, and nothing else; the installation's own uninstall decides everything.
//
// The silent entry (QuietUninstallString, winget) still runs the kept script directly with -Silent: no window.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal static class SettingsRemove
    {
        internal const string Asked = "--uninstall";
        internal const string Copied = "--uninstall-from";
        internal const string FolderPrefix = "CodexAutoResume-Uninstall-";

        /// Whether the command line asks for the uninstall window.
        internal static bool IsAsked(string[] argv)
        {
            return argv != null && argv.Length > 0 && (argv[0] == Asked || argv[0] == Copied);
        }

        internal static int Run(string[] argv)
        {
            string self = typeof(SettingsRemove).Assembly.Location;
            string beside = Path.GetDirectoryName(self);
            if (argv[0] == Asked) return argv.Length == 2 ? CopyAndStart(self, argv[1]) : Refuse("", beside);
            int parent;
            if (argv.Length != 3 || !int.TryParse(argv[2], NumberStyles.None, CultureInfo.InvariantCulture, out parent))
                return Refuse("", beside);
            return Removing(self, argv[1], parent);
        }

        internal const string NotItsOwn = "Codex Auto Resume cannot be removed from here: this is not its installation's own uninstaller.";

        /// Says the uninstall cannot run from here in the uninstall's own window, as every question the window asks is
        /// drawn by the window (tests/test_gui_v066_dialog.py): finished before it began, with the reason in its log,
        /// in the words and the look of the installation at `home` where they can be read, and English's where not.
        private static int Refuse(string where, string home)
        {
            try
            {
                Font font = Look(home);
                var flow = new InstallerFlow(InstallerFlow.Uninstall, home, InstallerFlow.InstalledAt(home), null, VersionAt(home));
                var window = new InstallerWindow(flow, Words(home), null, null, null, font);
                window.Finished(InstallerFlow.NotStarted, NotItsOwn + (where.Length > 0 ? "\n" + where : ""));
                Present(window);
                Application.Run(window);
            }
            catch (Exception) { /* nothing to draw it with: the code is all that is left to say it */ }
            return 1;
        }

        /// The theme, design, motion and text size the installation at `home` stores, adopted; the window's font.
        private static Font Look(string home)
        {
            string theme, design;
            bool reduce;
            Theme.Stored(home, out theme, out design, out reduce);
            Soft.ReduceMotionSetting = reduce;
            Palette.AdoptDesign(design);
            Palette.Adopt(Theme.Current(theme));
            // v0.6.18: at the scale of the monitor it opens on - CenterScreen puts it on the pointer's - as the Dashboard
            // is drawn (SettingsForm.AdoptDisplayScale), and as far as that screen holds Windows' text size.
            Rectangle pointer = new Rectangle(Cursor.Position.X, Cursor.Position.Y, 1, 1);
            SettingsForm.AdoptDisplayScale(SettingsForm.ScaleOfMonitor(pointer));
            SettingsForm.ScaleDefaultFont();
            double read = TextScale.Read();
            SettingsForm.AdoptTextSize(read, TextScale.Fitting(read, Screen.FromRectangle(pointer).WorkingArea.Size, SettingsForm.DpiScale));
            return SettingsForm.AtDisplayScale(TextScale.Apply(SystemFonts.MessageBoxFont, read, SettingsForm.TextSize));
        }

        /// The installation's words, in the language its settings store or Windows prefers.
        private static InstallerWords Words(string home)
        {
            string language = InstallerLanguages.Resolve(StoredLanguage(home), InstallerLanguages.Preferred());
            return new InstallerWords(Catalog(Path.Combine(home, "app"), language), language);
        }

        private static string VersionAt(string home)
        {
            return InstallerFlow.VersionOf(Read(Path.Combine(Path.Combine(Path.Combine(home, "app"), ".codex-plugin"), "plugin.json")));
        }

        /// The kept uninstaller of the installation this program is in, or null when `named` is not it.
        internal static string KeptScript(string home, string named)
        {
            try
            {
                string kept = Path.GetFullPath(Path.Combine(Path.Combine(home, "uninstall"), "install.ps1"));
                if (string.IsNullOrEmpty(named) || !string.Equals(Path.GetFullPath(named), kept, StringComparison.OrdinalIgnoreCase))
                    return null;
                return File.Exists(kept) ? kept : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        // In the installation: a copy of this program in a new folder of its own, started, and this one ends.
        private static int CopyAndStart(string self, string named)
        {
            string home = Path.GetDirectoryName(self);
            if (KeptScript(home, named) == null) return Refuse(named, home);
            try
            {
                string folder = Path.Combine(Path.GetTempPath(), FolderPrefix + Guid.NewGuid().ToString("N").Substring(0, 16));
                if (Directory.Exists(folder) || File.Exists(folder)) return Refuse(folder, home);
                Directory.CreateDirectory(folder);
                string copy = Path.Combine(folder, Path.GetFileName(self));
                File.Copy(self, copy, false);
                var start = new ProcessStartInfo(copy);
                start.Arguments = Copied + " " + Bridge.Quote(home) + " " +
                                  Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture);
                start.UseShellExecute = false;
                start.WorkingDirectory = folder;
                using (Process copied = Process.Start(start))
                {
                    // This program was started by a person - Settings > Apps, or the command itself - and may bring a
                    // window to the front; the copy, started by it and opening its window once this has ended, may
                    // not unless it is let (Present).
                    try { AllowSetForegroundWindow(copied.Id); }
                    catch (Exception) { /* the copy's window comes up behind, never minimized (Present) */ }
                }
                return 0;
            }
            catch (Exception error)
            {
                return Refuse(error.Message, home);
            }
        }

        // The copy: the window, over the installation at `home`.
        private static int Removing(string self, string home, int parent)
        {
            string folder = Path.GetDirectoryName(self);
            string kept = KeptScript(home, Path.Combine(Path.Combine(home, "uninstall"), "install.ps1"));
            bool ours = Path.GetFileName(folder).StartsWith(FolderPrefix, StringComparison.Ordinal) &&
                        string.Equals(Path.GetFullPath(Path.GetDirectoryName(folder)).TrimEnd('\\'),
                                      Path.GetFullPath(Path.GetTempPath()).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase);
            if (kept == null || !ours) return Refuse(home, home);
            try
            {
                using (Process before = Process.GetProcessById(parent)) before.WaitForExit(15000);
            }
            catch (ArgumentException) { /* it has already ended */ }

            Font font = Look(home);
            var flow = new InstallerFlow(InstallerFlow.Uninstall, home, InstallerFlow.InstalledAt(home), null, VersionAt(home));
            var window = new InstallerWindow(flow, Words(home), null,
                delegate(InstallerFlow answered, Action<string> heard, Action<double> unpacked)
                {
                    return Uninstall(home, kept, answered.Switches(null), heard);
                }, null, font);
            Present(window);
            Application.Run(window);
            Tidy(folder);
            return window.Code == int.MinValue ? 0 : window.Code;
        }

        [DllImport("user32.dll")]
        private static extern bool AllowSetForegroundWindow(int process);

        /// The uninstall window, shown as a window a person opened: normal and in front. The copy that shows it was
        /// started by another program, which ends first, and its window came up iconic - only on the taskbar - both
        /// from Settings > Apps and run directly (v0.6.16 acceptance). It opens normal, is restored should Windows
        /// still hand it out minimized, and is brought to the front, which the program that started it allowed. The
        /// routine is HostApp's since v0.6.17, where the Dashboard after Finish is brought to the front the same way.
        internal static void Present(Form window)
        {
            HostApp.Present(window);
        }

        private static string Read(string path)
        {
            try { return File.Exists(path) ? File.ReadAllText(path, new UTF8Encoding(false)).TrimStart('\uFEFF') : null; }
            catch (Exception) { return null; }
        }

        // The Interface language the settings store, or null for none (InstallerLanguages.Resolve reads it).
        private static string StoredLanguage(string home)
        {
            var map = InstallerFlow.ParseObject(Read(Path.Combine(Path.Combine(home, "config"), "settings.json")));
            object value;
            return map != null && map.TryGetValue("interface_language", out value) ? value as string : null;
        }

        // The installation's catalog of `language`, read before the uninstall removes it; English's where it has none.
        private static Dictionary<string, object> Catalog(string app, string language)
        {
            string locales = Path.Combine(Path.Combine(Path.Combine(app, "src"), "codex_auto_resume"), "locales");
            var catalog = InstallerFlow.ParseObject(Read(Path.Combine(locales, language + ".json")));
            if (catalog == null && language != "en")
                catalog = InstallerFlow.ParseObject(Read(Path.Combine(locales, "en.json")));
            return catalog;
        }

        // The kept script's uninstall, as Uninstall.cmd runs it, with no window: Windows PowerShell by its full path,
        // the script and the switches as arguments, for the installation at `home` and no other.
        private static int Uninstall(string home, string kept, List<string> switches, Action<string> heard)
        {
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                             "WindowsPowerShell", "v1.0", "powershell.exe");
            var start = new ProcessStartInfo(powershell);
            start.Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Bridge.Quote(kept) +
                              " " + string.Join(" ", switches.ToArray());
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.RedirectStandardInput = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = Encoding.UTF8;
            start.StandardErrorEncoding = Encoding.UTF8;
            start.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = home;
            // How much of each step is done, for the installer window's bar (InstallerProgress.Variable).
            start.EnvironmentVariables[InstallerProgress.Variable] = "1";
            start.WorkingDirectory = Path.GetTempPath();
            using (Process run = Process.Start(start))
            {
                run.StandardInput.Close();
                run.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) heard(e.Data); };
                run.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) heard(e.Data); };
                run.BeginOutputReadLine();
                run.BeginErrorReadLine();
                run.WaitForExit();
                run.WaitForExit(5000);
                return run.ExitCode;
            }
        }

        /// Removes the copy's own folder once the copy has ended: Windows PowerShell, by its full path, with a constant
        /// script that waits for this process and removes only a folder of this name in the temporary folder. The
        /// folder and the process are given in its environment, never in its code.
        internal const string TidyScript =
            "$p = [int]$env:CODEX_AR_UNINSTALL_PID; try { Wait-Process -Id $p -Timeout 120 -ErrorAction Stop } catch { }; " +
            "$f = $env:CODEX_AR_UNINSTALL_FOLDER; $t = [IO.Path]::GetTempPath().TrimEnd('\\'); " +
            "if ((Split-Path -Leaf $f) -like 'CodexAutoResume-Uninstall-*' -and (Split-Path -Parent $f) -eq $t) " +
            "{ Remove-Item -LiteralPath $f -Recurse -Force -ErrorAction SilentlyContinue }";

        private static void Tidy(string folder)
        {
            try
            {
                string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                                 "WindowsPowerShell", "v1.0", "powershell.exe");
                var start = new ProcessStartInfo(powershell);
                start.Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command " + Bridge.Quote(TidyScript);
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.WorkingDirectory = Path.GetTempPath();
                start.EnvironmentVariables["CODEX_AR_UNINSTALL_PID"] = Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture);
                start.EnvironmentVariables["CODEX_AR_UNINSTALL_FOLDER"] = folder.TrimEnd('\\');
                Process.Start(start).Dispose();
            }
            catch (Exception) { /* a copy of this program is left in the temporary folder, which Windows clears */ }
        }
    }
}

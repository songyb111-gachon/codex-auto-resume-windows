// The setup programs' window (v0.6.16): what a double-clicked CodexAutoResume-Setup-v<version>.exe shows instead of
// a console. The window itself is the product's (gui/InstallerWindow.cs, gui/InstallerFlow.cs, drawn with the
// window's [controls] in its [generated] palette - gui/window.sources); this file gives it what a setup program
// has and the settings window would have given it: the archive's edition, version and words, this machine's
// installation, the display's scale and Windows' text size, and the run itself (Setup.cs, InstallFrom).
//
// Nothing here writes anything. It reads the archive it carries, whether and which edition is installed where
// install.ps1 would install (InstallerFlow.InstalledAt), and Windows' theme and text size, as the settings window
// reads them. It starts the installer through Setup.cs alone, and once it has finished, if the person left
// "Open the Dashboard" on, the Dashboard of the installation it has just made, by its full path.
//
// C# 5 only: compiled by the in-box csc with Setup.cs (build/make_setup.py).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using CodexAutoResume;

namespace CodexAutoResumeSetup
{
    internal delegate int Installing(IList<string> switches, Action<string> heard, Action<double> unpacked);

    internal static class SetupWindow
    {
        internal const string Locales = "payload/app/src/codex_auto_resume/locales/";
        internal const string Manifest = "payload/app/.codex-plugin/plugin.json";
        internal const string Docs = "payload/app/docs/";
        internal const string Dashboard = "CodexAutoResumeSettings.exe";

        // A stop said before there is a window: Windows' own message box, in English, as Setup.cs says it.
        internal static void Tell(string text)
        {
            MessageBox.Show(text, "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }

        internal static int Run(byte[] archive, string[] arguments, Installing install)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string home = InstallerFlow.HomeFrom(Environment.GetEnvironmentVariable("CODEX_AUTO_RESUME_PLUGIN_HOME"),
                                                 Environment.GetFolderPath(Environment.SpecialFolder.UserProfile));
            // The Dashboard's look: the theme, design and motion the installation here stores, as the Dashboard and the
            // uninstall window open in them - and where there is none, what the Dashboard does by default.
            string[] look = LookAt(home);
            Soft.ReduceMotionSetting = look[2] == "reduce";
            Palette.AdoptDesign(look[1]);
            Palette.Adopt(Theme.Current(look[0]));
            double read = TextScale.Read();
            SettingsForm.AdoptTextSize(TextScale.Fitting(read, Screen.PrimaryScreen.WorkingArea.Size, SettingsForm.SystemScale));
            Font font = TextScale.Apply(SystemFonts.MessageBoxFont, read, SettingsForm.TextSize);

            Archive carried = new Archive(archive);
            string installed = InstallerFlow.InstalledAt(home);
            string from = installed == null ? "" : InstallerFlow.VersionOf(
                Read(Path.Combine(Path.Combine(Path.Combine(home, "app"), ".codex-plugin"), "plugin.json")));
            var flow = FlowFor(arguments, home, carried.Edition, installed, carried.Version, from);
            string language = InstallerLanguages.FromSystem(InstallerLanguages.Preferred());
            // An update says from what to what, and what is new in the version this program carries (v0.6.16); a repair
            // of the same version has nothing new to say.
            if (flow.Upgrade && flow.Mode == InstallerFlow.Install && !flow.Maintaining) flow.NotesText = carried.Notes(language);
            var window = new InstallerWindow(flow, carried.Words(language), carried.Words,
                delegate(InstallerFlow answered, Action<string> heard, Action<double> unpacked)
                {
                    return install(answered.Switches(arguments), heard, unpacked);
                }, arguments, font);
            // In front when it opens: a window this program relaunched outside another app's view is created by the
            // shell or the WMI service, which do not give it the foreground (HostApp.Relaunch). Not a window
            // build/capture_window.ps1 started, which stays where it opened - the capture refuses a picture whose caption
            // is active (2026-10-20, the install motion's still) - as the Dashboard's reopen does (SettingsApp).
            if (Soft.StillReady == null) HostApp.BringToFront(window);
            Application.Run(window);
            if (window.OpenDashboard) OpenDashboard(flow.Home);
            return window.Code == int.MinValue ? Codes.Cancelled : window.Code;
        }

        /// What the window shows for the command line it was started with: the uninstall with -Uninstall, as Install.cmd
        /// runs it (the switch is the window's answer from then on, so it shows the uninstall rather than dropping it),
        /// and the installation otherwise; -SkipStartup, -AllowEditionChange and -Purge as its first answers. Over its
        /// own version (`from`, the installed one), installed already in its edition, it asks Repair or Remove first,
        /// as an ordinary program's installer does (v0.6.16, the owner); a newer version updates, as before. Pure.
        internal static InstallerFlow FlowFor(string[] arguments, string home, string edition, string installed, string version,
                                              string from)
        {
            string mode = InstallerFlow.Has(arguments, "-Uninstall") ? InstallerFlow.Uninstall : InstallerFlow.Install;
            var flow = new InstallerFlow(mode, home, edition, installed, version);
            flow.StartAtSignIn = !InstallerFlow.Has(arguments, "-SkipStartup");
            flow.ChangeEdition = InstallerFlow.Has(arguments, "-AllowEditionChange");
            flow.Purge = InstallerFlow.Has(arguments, "-Purge");
            flow.From = from ?? "";
            flow.Maintaining = mode == InstallerFlow.Install && flow.Upgrade && !flow.EditionChange &&
                               flow.From.Length > 0 && flow.From == flow.Version;
            return flow;
        }

        /// The look the window opens in over the installation at `home`: its stored Theme preference, design and "reduce"
        /// or "" for its motion (Theme.Stored, as the Dashboard and the uninstall window read them) - or, with nothing
        /// stored, the Dashboard's own defaults, "system" and Soft. The acceptance's setup window opened dark, Windows'
        /// app mode, while the installation it updated was set to light. Pure but for the one file it reads.
        internal static string[] LookAt(string home)
        {
            string theme, design;
            bool reduce;
            Theme.Stored(home, out theme, out design, out reduce);
            return new[] { theme, design, reduce ? "reduce" : "" };
        }

        private static string Read(string path)
        {
            try { return File.Exists(path) ? File.ReadAllText(path, new UTF8Encoding(false)).TrimStart('\uFEFF') : null; }
            catch (Exception) { return null; }
        }

        // The Dashboard of the installation just made: its own program, by its full path, which is a window and
        // has no console - in front (v0.6.17): this program's window has just closed on Finish, and the Dashboard it
        // started opened behind the windows already there until this program let it come forward (HostApp). Where it
        // cannot be started, it is installed all the same, and the Start menu opens it.
        private static void OpenDashboard(string home)
        {
            string exe = Path.Combine(home, Dashboard);
            if (!File.Exists(exe)) return;
            HostApp.StartInFront(exe, null, home);
        }

        /// What the window reads from the archive it carries: its entries' names, its version and the catalogs.
        internal sealed class Archive
        {
            private readonly byte[] archive;
            private readonly Dictionary<string, InstallerWords> spoken = new Dictionary<string, InstallerWords>();
            internal readonly string Edition;
            internal readonly string Version;

            internal Archive(byte[] archive)
            {
                this.archive = archive;
                var names = new List<string>();
                using (ZipArchive zip = Open())
                    foreach (ZipArchiveEntry entry in zip.Entries) names.Add(entry.FullName);
                Edition = InstallerFlow.EditionOfEntries(names);
                Version = InstallerFlow.VersionOf(Text(Manifest));
            }

            private ZipArchive Open()
            {
                return new ZipArchive(new MemoryStream(archive, false), ZipArchiveMode.Read);
            }

            private string Text(string name)
            {
                try
                {
                    using (ZipArchive zip = Open())
                    {
                        ZipArchiveEntry entry = zip.GetEntry(name);
                        if (entry == null) return null;
                        using (var reader = new StreamReader(entry.Open(), new UTF8Encoding(false)))
                            return reader.ReadToEnd().TrimStart('\uFEFF');
                    }
                }
                catch (Exception)
                {
                    return null;
                }
            }

            /// What is new in the version it carries: its section of the changelog in the archive, the language's own
            /// where the archive has one (InstallerNotes).
            internal string Notes(string language)
            {
                string own = language == "en" ? null : Text(Docs + "CHANGELOG." + language + ".md");
                return InstallerNotes.Section(own ?? Text(Docs + "CHANGELOG.md"), Version);
            }

            /// The words of `language`, from the catalog the archive carries; English's where it has none.
            internal InstallerWords Words(string language)
            {
                InstallerWords words;
                if (spoken.TryGetValue(language, out words)) return words;
                var catalog = InstallerFlow.ParseObject(Text(Locales + language + ".json"));
                words = catalog == null && language != "en" ? Words("en") : new InstallerWords(catalog, language);
                spoken[language] = words;
                return words;
            }
        }
    }
}

namespace CodexAutoResume
{
    /// The setup program's stand-in for the settings window's scale (SettingsForm.DpiScale in gui/SettingsApp.cs),
    /// which the window's controls are drawn at: the display's, measured as the settings window measures it, times
    /// the text size the window is drawn at. The setup program has no settings window, so this is the whole of it.
    internal sealed partial class SettingsForm
    {
        [DllImport("user32.dll")]
        private static extern int GetDpiForSystem();

        internal static readonly double SystemScale = MeasureDpiScale();
        private static double scale = SystemScale;
        internal static double TextSize = 1.0;

        internal static double DpiScale { get { return scale; } }

        internal static void AdoptTextSize(double drawn)
        {
            TextSize = Math.Max(1.0, drawn);
            scale = SystemScale * TextSize;
        }

        /// Stands another scaling in, for the layout audit (InstallerAudit).
        internal static void StandIn(double displayScale, double text)
        {
            TextSize = Math.Max(1.0, text);
            scale = displayScale * TextSize;
        }

        private static double MeasureDpiScale()
        {
            try
            {
                int dpi = GetDpiForSystem();
                if (dpi >= 96) return dpi / 96.0;
            }
            catch (Exception) { /* before Windows 10 1607 */ }
            return 1.0;
        }
    }

    /// The installer window checking its own layout, as the settings window's LayoutAudit does: every page of every
    /// way it is shown, in one language at one scaling and text size, built and never shown. One line for each
    /// thing cut off or out of place; nothing when there is none. tests/test_installer_window.py runs it in every
    /// language at every scaling and text size.
    internal static class InstallerAudit
    {
        internal static string LayoutAudit(string catalogJson, string language, double displayScale, double text)
        {
            var findings = new List<string>();
            Font baseBefore = Soft.BaseFont;
            try
            {
                SettingsForm.StandIn(displayScale, text);
                Font box = TextScale.Apply(SystemFonts.MessageBoxFont, 1.0, text);
                var font = new Font(box.FontFamily, (float)(box.SizeInPoints * displayScale / SettingsForm.SystemScale),
                                    box.Style, GraphicsUnit.Point);
                var words = new InstallerWords(Json.Parse(catalogJson) as Dictionary<string, object>, language);
                string home = @"C:\Users\ExampleUser\.codex-auto-resume";
                var cases = new List<KeyValuePair<string, InstallerFlow>>();
                cases.Add(Case("first", new InstallerFlow(InstallerFlow.Install, home, InstallerFlow.Standard, null, "0.6.16")));
                cases.Add(Case("update", new InstallerFlow(InstallerFlow.Install, home, InstallerFlow.Advanced, InstallerFlow.Advanced, "0.6.16")));
                cases.Add(Case("edition", new InstallerFlow(InstallerFlow.Install, home, InstallerFlow.Standard, InstallerFlow.Advanced, "0.6.16")));
                cases.Add(Case("edition-advanced", new InstallerFlow(InstallerFlow.Install, home, InstallerFlow.Advanced, InstallerFlow.Standard, "0.6.16")));
                var repair = new InstallerFlow(InstallerFlow.Install, home, InstallerFlow.Standard, InstallerFlow.Standard, "0.6.16");
                repair.Maintaining = true;
                cases.Add(Case("repair", repair));
                var remove = new InstallerFlow(InstallerFlow.Install, home, InstallerFlow.Standard, InstallerFlow.Standard, "0.6.16");
                remove.Maintaining = true;
                remove.Choose(true);
                cases.Add(Case("repair-remove", remove));
                cases.Add(Case("dashboard-update", new InstallerFlow(InstallerFlow.Update, home, InstallerFlow.Standard, InstallerFlow.Standard, "0.6.16")));
                // Install another version... (v0.6.18): an older version of the other edition, run as the update is.
                var pick = new InstallerFlow(InstallerFlow.Update, home, InstallerFlow.Advanced, InstallerFlow.Standard, "0.6.11-beta.2");
                pick.Another = true;
                cases.Add(Case("dashboard-pick", pick));
                cases.Add(Case("uninstall", new InstallerFlow(InstallerFlow.Uninstall, home, InstallerFlow.Standard, InstallerFlow.Standard, "0.6.16")));
                foreach (KeyValuePair<string, InstallerFlow> each in cases)
                {
                    // An update's pages carry what is new: a changelog section, its lines as long as the real ones.
                    // A pick prints no notes (scripts/bootstrap.ps1: -AskFirst is the update's alone): none to carry.
                    if (each.Value.Another) each.Value.From = "0.6.16";
                    else if (each.Value.Upgrade && !each.Value.EditionChange || each.Value.Mode == InstallerFlow.Update)
                    {
                        each.Value.From = "0.6.15";
                        each.Value.NotesText = SampleNotes;
                    }
                    foreach (int ended in Endings())
                    {
                        using (var window = new InstallerWindow(each.Value, words, delegate(string other) { return words; },
                                                                delegate { return 0; }, null, font))
                        {
                            string where = each.Key + "/" + (ended == int.MinValue ? "pages" : "finish " + ended);
                            if (ended == int.MinValue)
                            {
                                foreach (string page in each.Value.Pages())
                                {
                                    window.ShowPage(page);
                                    Check(window, where + "/" + page, findings);
                                }
                                continue;
                            }
                            window.Finished(ended, ended == 0
                                ? "The watcher could not be confirmed running, so nothing is being watched yet.\n" +
                                  "The previous version of the watcher was asked to stop and is still finishing"
                                : "  [x]  Something did not work.");
                            Check(window, where, findings);
                        }
                    }
                }
            }
            catch (Exception error)
            {
                findings.Add("the audit itself failed: " + error);
            }
            finally
            {
                Soft.BaseFont = baseBefore;
            }
            return string.Join("\n", findings);
        }

        // The pages, then a finish of each kind. Added one by one: a constant array would give the program a class
        // with a random name (build/normalize_pe.py).
        private static List<int> Endings()
        {
            var endings = new List<int>();
            endings.Add(int.MinValue);
            endings.Add(0);
            endings.Add(1);
            endings.Add(InstallerFlow.EditionChangeRefused);
            endings.Add(InstallerFlow.StillRunning);
            return endings;
        }

        private const string SampleNotes =
            "v0.6.16 - The installer has a window of its own, and an update shows what is new before it installs\n\n" +
            "**Both editions.** The setup programs, the Dashboard's update and the uninstall in Settings > Apps show " +
            "the installer window, in the Dashboard's design and the person's language, at every text size.\n" +
            "- After an update everything that ran before runs again, on the new version, by itself.\n" +
            "- A watcher the person had stopped is left stopped.\n";

        private static KeyValuePair<string, InstallerFlow> Case(string name, InstallerFlow flow)
        {
            return new KeyValuePair<string, InstallerFlow>(name, flow);
        }

        /// The page on show: every row inside the card and as wide as its words need at most, every button inside
        /// the window and clear of the others, the header's two lines whole, and every control a person can act on
        /// with a name a screen reader says.
        private static void Check(InstallerWindow window, string where, List<string> findings)
        {
            window.PerformLayout();
            Control body = window.Body;
            int width = body.Parent.Width - body.Parent.Padding.Horizontal;
            int height = body.Parent.Height - body.Parent.Padding.Vertical;
            int used = window.Arrange(width);
            if (used > height) findings.Add(where + " :: the page needs " + used + " px and its card holds " + height);
            foreach (Control control in window.ShownRows())
            {
                string name = control.GetType().Name + "'" + Short(control.Text) + "'";
                if (control.Right > width) findings.Add(where + " :: " + name + " reaches past the card by " + (control.Right - width) + " px");
                Size wanted = control.GetPreferredSize(new Size(control.Width, 0));
                if ((control is WrapLabel || control is SoftCheck || control is SoftCallout) && wanted.Width > control.Width)
                    findings.Add(where + " :: " + name + " needs " + wanted.Width + " px and has " + control.Width);
                if ((control is WrapLabel || control is SoftCheck || control is SoftCallout) && wanted.Height > control.Height)
                    findings.Add(where + " :: " + name + " needs " + wanted.Height + " px high and has " + control.Height);
                if (control is LinkLabel)
                {
                    Size line = TextRenderer.MeasureText(control.Text, control.Font, new Size(int.MaxValue, 0), TextFormatFlags.NoPrefix);
                    if (line.Width > control.Width && line.Height >= control.Height)
                        findings.Add(where + " :: " + name + " needs " + line.Width + " px and has " + control.Width);
                }
                if (control is SoftCombo && control.Height != SoftCombo.FieldHeight)
                    findings.Add(where + " :: the language picker is " + control.Height + " px high, not " + SoftCombo.FieldHeight);
                if ((control is SoftCheck || control is SoftCombo || control is LinkLabel) &&
                    string.IsNullOrEmpty(control.AccessibleName) && string.IsNullOrEmpty(control.Text))
                    findings.Add(where + " :: " + name + " has no name a screen reader says");
            }
            int left = int.MaxValue;
            foreach (Control button in window.Buttons())
            {
                Size wanted = button.GetPreferredSize(Size.Empty);
                if (wanted.Width > button.Width) findings.Add(where + " :: button '" + button.Text + "' needs " + wanted.Width + " px and has " + button.Width);
                if (button.Left < Soft.Px(16)) findings.Add(where + " :: button '" + Short(button.Text) + "' runs past the window's left side");
                if (button.Right > left) findings.Add(where + " :: button '" + button.Text + "' overlaps the one beside it");
                left = Math.Min(left, button.Left);
                if (button.Bottom > window.ClientSize.Height) findings.Add(where + " :: button '" + button.Text + "' is below the window");
            }
            foreach (Label line in window.HeaderLines())
            {
                Size needed = TextRenderer.MeasureText(line.Text, line.Font, new Size(int.MaxValue, 0), TextFormatFlags.NoPrefix);
                if (needed.Width > line.Width) findings.Add(where + " :: the header's '" + Short(line.Text) + "' needs " + needed.Width + " px and has " + line.Width);
                if (needed.Height > line.Height) findings.Add(where + " :: the header's '" + Short(line.Text) + "' needs " + needed.Height + " px high and has " + line.Height);
            }
        }

        private static string Short(string text)
        {
            text = (text ?? "").Replace("\r", " ").Replace("\n", " ");
            return text.Length > 40 ? text.Substring(0, 40) : text;
        }
    }
}

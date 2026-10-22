// Codex Auto Resume - the installer window's steps and choices, apart from any window.
//
// The setup programs (build/setup/Setup.cs), the Dashboard's update and the entry in Add or remove programs
// all show one window (InstallerWindow). What it asks, which switches each answer becomes, how far along the
// installer is and what its exit code means are decided here, with no control in sight, so each rule can be
// checked without a window (tests/test_installer_window.py).
//
// It asks only what the installer really has a choice about. install.ps1 decides everything else itself -
// where it installs, that it adds the plugin to Codex, that an update keeps the settings and the sign-in
// choice - and the window says those as facts. The answers become the installer's own switches: -SkipStartup,
// -AllowEditionChange and, for an uninstall, -Purge. -Silent is always passed, because the window is the one
// asking and nothing may wait for a key in a console nobody sees.
//
// C# 5 only: the setup programs are compiled by the in-box csc (build/make_setup.py), as the window is.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace CodexAutoResume
{
    internal sealed class InstallerFlow
    {
        internal const string Install = "install";
        internal const string Update = "update";
        internal const string Uninstall = "uninstall";

        internal const string Welcome = "welcome";
        internal const string Options = "options";
        internal const string Confirm = "confirm";
        internal const string Progress = "progress";
        internal const string Finish = "finish";
        /// The update's own page (v0.6.16): the version it goes to and what is new in it, before anything is installed.
        internal const string Notes = "notes";
        /// A setup program's first page where its own version is installed already (v0.6.16, the owner): Repair or
        /// Remove, as an ordinary program's installer offers.
        internal const string Maintain = "maintain";

        internal const string Standard = "standard";
        internal const string Advanced = "advanced";

        /// install.ps1's code for an archive of the other edition when no change was asked for: nothing changed.
        internal const int EditionChangeRefused = 14;
        /// The window's own code for a run that has not finished in the time it was given (the Dashboard's update):
        /// never ended by force, for it may be part way through replacing an installation.
        internal const int StillRunning = -2;
        /// The window's own code for an installer that could not be started at all.
        internal const int NotStarted = -1;
        /// The window's own code for an update the person put off on the Notes page: nothing was installed.
        internal const int Later = -3;

        /// The package whose presence makes a tree the advanced edition (src/codex_auto_resume/edition.py).
        internal const string AdvancedPackage = "codex_auto_resume_advanced";

        /// Install, Update or Uninstall. Remove on the Maintain page makes an installation the uninstall (Choose).
        internal string Mode;
        /// Where the installation is or will be: install.ps1's $InstallHome.
        internal readonly string Home;
        /// The edition this archive installs, or the installation's own for an update or an uninstall.
        internal readonly string Edition;
        /// The edition installed in Home now, or null where nothing is.
        internal readonly string Installed;
        internal readonly string Version;

        /// Run at Windows sign-in, on a first installation: off is -SkipStartup.
        internal bool StartAtSignIn = true;
        /// Replace the other edition, which is installed: -AllowEditionChange. Off until it is asked for.
        internal bool ChangeEdition;
        /// Delete the settings and the recovery history too, on an uninstall: -Purge. Off until it is asked for.
        internal bool Purge;
        /// Open the Dashboard once it is done.
        internal bool OpenDashboard = true;
        /// The version installed now, for "vX -> vY" ("" where none is, or it cannot be read).
        internal string From = "";
        /// A setup program run over its own version, installed already in its edition: the window asks Repair or
        /// Remove first (Maintain). Never with -Silent, which shows no window and asks nothing.
        internal bool Maintaining;
        /// What is new in Version: its section of the changelog the archive carries, or null where there is none.
        internal string NotesText;
        /// The Dashboard's Install another version... (v0.6.18 acceptance): run as an update is - the bootstrap's lines
        /// on the bar, the Dashboard's own rules after it - but named for what it is, for an older version or the other
        /// edition is not an update. The bootstrap prints no notes for a pick, so it has no Notes page.
        internal bool Another;

        internal InstallerFlow(string mode, string home, string edition, string installed, string version)
        {
            Mode = mode == Update || mode == Uninstall ? mode : Install;
            Home = home ?? "";
            Edition = edition == Advanced ? Advanced : Standard;
            Installed = installed == Advanced || installed == Standard ? installed : null;
            Version = version ?? "";
        }

        /// Whether there is an installation here already: then this is an update or a repair, and install.ps1 keeps
        /// the settings, everything waiting and the sign-in choice (--keep-state) - there is nothing to ask about them.
        internal bool Upgrade { get { return Installed != null; } }

        /// Whether the other edition is installed here: then installing is a change of edition, asked for or refused.
        internal bool EditionChange { get { return Installed != null && Installed != Edition; } }

        /// The pages the window goes through, in order.
        internal string[] Pages()
        {
            // Repair runs from the first page; Remove goes on to the uninstall's own (Choose).
            if (Maintaining) return new[] { Maintain, Confirm, Progress, Finish };
            // The Notes page comes between the download and the install (InstallerWindow.Ask).
            if (Mode == Update && Another) return new[] { Progress, Finish };
            if (Mode == Update) return new[] { Progress, Notes, Finish };
            if (Mode == Uninstall) return new[] { Confirm, Progress, Finish };
            return new[] { Welcome, Options, Progress, Finish };
        }

        /// The Maintain page's answer: Remove makes this the uninstall, with its own question about the settings;
        /// Repair keeps it the installation, which install.ps1 runs over the same version in place.
        internal void Choose(bool remove)
        {
            if (Maintaining) Mode = remove ? Uninstall : Install;
        }

        /// Whether this run repairs the installation: the Maintain page's Repair.
        internal bool Repair { get { return Maintaining && Mode == Install; } }

        /// The status light for each phase the window shows, in one place (the owner, 2026-10-20: the light is the state
        /// that is true there, in every phase). Only the Dashboard's own states, by its rule (DashboardActions.HeaderLight):
        /// grey "idle" for a watcher not known to be running, a lit state only for one that is.
        ///   - the pages before the run (Welcome, Options with the edition change, Maintain, Confirm, Notes): the window
        ///     has not looked at the watcher, so it is not known to be running - idle;
        ///   - the run, and a run still working in the background (StillRunning): the product is being changed - the
        ///     working light, "checking";
        ///   - an uninstall that finished: the product is gone and nothing watches - idle;
        ///   - a run that failed or could not start: what runs now is not known - idle, as the Dashboard has it;
        ///   - an install, update or repair whose watcher was not confirmed running - idle;
        ///   - an update whose previous watcher is still finishing and the new one waits to be started: a watcher runs
        ///     and wants the person - "attention";
        ///   - an install, update or repair whose watcher was confirmed running - "monitoring".
        /// Comparisons, not a switch (build/normalize_pe.py).
        internal static string Light(string mode, string page, int code, bool unconfirmed, bool previousRunning)
        {
            if (page == Progress) return "checking";
            if (page != Finish) return "idle";
            if (code == StillRunning) return "checking";
            if (code != 0) return "idle";
            if (mode == Uninstall) return "idle";
            if (unconfirmed) return "idle";
            if (previousRunning) return "attention";
            return "monitoring";
        }

        /// Whether the page that starts the run may start it: an edition change only once it is asked for.
        internal bool CanStart()
        {
            return Mode != Install || !EditionChange || ChangeEdition;
        }

        /// The switches the installer is given for the answers: Install.cmd's and install.ps1's own words. `given`
        /// are the ones the setup program itself was started with, which a window still passes on.
        internal List<string> Switches(IEnumerable<string> given)
        {
            var switches = new List<string>();
            if (Mode == Uninstall)
            {
                switches.Add("-Uninstall");
                if (Purge) switches.Add("-Purge");
            }
            else if (Mode == Install)
            {
                // A first installation's choice only: on an update install.ps1 keeps the sign-in entry as it is.
                if (!Upgrade && !StartAtSignIn) switches.Add("-SkipStartup");
                if (EditionChange && ChangeEdition) switches.Add("-AllowEditionChange");
            }
            if (given != null)
            {
                foreach (string word in given)
                {
                    if (Has(switches, word) || IsAnswered(word)) continue;
                    switches.Add(word);
                }
            }
            switches.Add("-Silent");
            return switches;
        }

        // The switches the answers above decide, which a setup program's own command line only presets.
        private static bool IsAnswered(string word)
        {
            foreach (string answered in new[] { "-SkipStartup", "-AllowEditionChange", "-Silent", "-Uninstall", "-Purge" })
                if (string.Equals(word, answered, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        internal static bool Has(IEnumerable<string> words, string word)
        {
            if (words == null) return false;
            foreach (string each in words)
                if (string.Equals(each, word, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        /// install.ps1's $InstallHome: CODEX_AUTO_RESUME_PLUGIN_HOME where it is set, else .codex-auto-resume in the
        /// profile. Pure.
        internal static string HomeFrom(string pluginHome, string profile)
        {
            if (!string.IsNullOrWhiteSpace(pluginHome)) return pluginHome;
            return Path.Combine(profile ?? "", ".codex-auto-resume");
        }

        /// The edition of the tree whose `src` folder this is, by install.ps1's own rule (Get-Edition): the advanced
        /// package's folder, in exactly that case, with an __init__.py in it. A tree that is not there is null.
        internal static string EditionOfSource(string src)
        {
            try
            {
                if (string.IsNullOrEmpty(src) || !Directory.Exists(src)) return null;
                foreach (string folder in Directory.GetDirectories(src))
                {
                    if (!string.Equals(Path.GetFileName(folder), AdvancedPackage, StringComparison.Ordinal)) continue;
                    if (File.Exists(Path.Combine(folder, "__init__.py"))) return Advanced;
                }
                return Standard;
            }
            catch (Exception)
            {
                return Standard;
            }
        }

        /// The edition installed at `home`, as install.ps1 reads it before it moves anything: none where there is
        /// no app folder (a first installation), else the edition of app\src.
        internal static string InstalledAt(string home)
        {
            try
            {
                string app = Path.Combine(home ?? "", "app");
                if (!Directory.Exists(app)) return null;
                return EditionOfSource(Path.Combine(app, "src")) ?? Standard;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// The edition an archive installs, from its entries' names: the same rule, read inside the ZIP.
        /// The entry's name is taken apart rather than compared whole: a whole one is a literal of the advanced
        /// package's path, which the edition audit refuses in a standard setup program (build/edition_audit.py, (h)).
        internal static string EditionOfEntries(IEnumerable<string> names)
        {
            foreach (string name in names)
            {
                string[] parts = name.Split('/');
                if (parts.Length == 5 && parts[0] == "payload" && parts[1] == "app" && parts[2] == "src" &&
                    string.Equals(parts[3], AdvancedPackage, StringComparison.Ordinal) && parts[4] == "__init__.py")
                    return Advanced;
            }
            return Standard;
        }

        /// A JSON object read from `text`, or null where there is no text or it is not one.
        internal static Dictionary<string, object> ParseObject(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            try { return Json.Parse(text) as Dictionary<string, object>; }
            catch (Exception) { return null; }
        }

        /// The version a plugin.json names, or "" where it names none.
        internal static string VersionOf(string pluginJson)
        {
            var manifest = ParseObject(pluginJson);
            object version;
            return manifest != null && manifest.TryGetValue("version", out version) && version is string ? (string)version : "";
        }
    }

    /// What is new in a version (v0.6.16): its section of the changelog an archive carries, docs\CHANGELOG.md - or the
    /// person's language's, CHANGELOG.<language>.md, where the archive carries one. Pure but for FileFor.
    internal static class InstallerNotes
    {
        /// The changelog to read in `docs`: the language's own where it is there, else the English one.
        internal static string FileFor(string docs, string language)
        {
            try
            {
                string own = Path.Combine(docs ?? "", "CHANGELOG." + (language ?? "en") + ".md");
                if (language != null && language != "en" && File.Exists(own)) return own;
                return Path.Combine(docs ?? "", "CHANGELOG.md");
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// `version`'s section of `changelog`: from its "## v<version>" heading, without the "## ", to the next
        /// section's heading; null where there is none.
        internal static string Section(string changelog, string version)
        {
            if (string.IsNullOrEmpty(changelog) || string.IsNullOrEmpty(version)) return null;
            string[] lines = changelog.Replace("\r\n", "\n").Split('\n');
            string heading = "## v" + version;
            var found = new StringBuilder();
            bool inside = false;
            foreach (string line in lines)
            {
                if (line.StartsWith("## ", StringComparison.Ordinal))
                {
                    if (inside) break;
                    inside = line == heading || line.StartsWith(heading + " ", StringComparison.Ordinal);
                    if (inside) found.Append(line.Substring(3)).Append('\n');
                    continue;
                }
                if (inside) found.Append(line).Append('\n');
            }
            return found.Length > 0 ? found.ToString().Trim() : null;
        }

        /// The kinds of block a section is read into (Blocks).
        private const char Heading = 'h', Item = 'i', Paragraph = 'p';

        /// A section as plain text to read (v0.6.16 acceptance: the notes page showed the changelog's Markdown as it is
        /// written, and ran the words of two wrapped lines together, "*Check for updates*offers", for a text box breaks
        /// a line only at CR LF). Each heading is a line of its own words; each paragraph and each list item is one
        /// line, its wrapped lines joined with a space, an item set off by a bullet; a blank line before a heading
        /// and between paragraphs; a link is its text, and no **, * or ` is left - but what is between backticks is
        /// kept as it is written. Lines end in CR LF. Pure.
        internal static string Readable(string section)
        {
            if (string.IsNullOrEmpty(section)) return "";
            var text = new StringBuilder();
            char last = ' ';
            foreach (KeyValuePair<char, string> block in Blocks(section))
            {
                if (text.Length > 0)
                {
                    text.Append("\r\n");
                    // Items in a list follow one another; anything else is set off by a blank line.
                    if (!(block.Key == Item && last == Item)) text.Append("\r\n");
                }
                text.Append(block.Key == Item ? "• " + block.Value : block.Value);
                last = block.Key;
            }
            return text.ToString();
        }

        /// The first `count` blocks of a section worth reading on their own, for the Finish page: its title, then its
        /// paragraphs and items - no other heading, nothing that was only a link - each cut at a word near `Room`
        /// letters, one to a line.
        internal static string Brief(string section, int count)
        {
            if (string.IsNullOrEmpty(section)) return "";
            var kept = new List<string>();
            foreach (KeyValuePair<char, string> block in Blocks(section))
            {
                if (block.Key == Heading && kept.Count > 0) continue;
                kept.Add(Cut(block.Value, Room));
                if (kept.Count >= count) break;
            }
            return string.Join(Environment.NewLine, kept.ToArray());
        }

        /// How many letters a line of the Finish page's brief keeps.
        internal const int Room = 160;

        private static string Cut(string line, int room)
        {
            if (line.Length <= room) return line;
            int space = line.LastIndexOf(' ', room);
            return line.Substring(0, space > room / 2 ? space : room).TrimEnd(',', ';', ':', ' ') + "…";
        }

        /// The section's blocks in order - a heading, a list item or a paragraph, each with its words read as plain
        /// text (Plain) and its wrapped lines joined - leaving out each line that was only a link.
        private static List<KeyValuePair<char, string>> Blocks(string section)
        {
            var blocks = new List<KeyValuePair<char, string>>();
            char kind = ' ';
            var words = new StringBuilder();
            Action close = delegate
            {
                string said = Plain(words.ToString().Trim());
                if (said.Length > 0) blocks.Add(new KeyValuePair<char, string>(kind, said));
                words.Length = 0;
                kind = ' ';
            };
            foreach (string raw in section.Replace("\r\n", "\n").Split('\n'))
            {
                string line = raw.Trim();
                int indent = raw.Length - raw.TrimStart().Length;
                if (line.Length == 0) { close(); continue; }
                int marks = 0;
                while (marks < line.Length && line[marks] == '#') marks++;
                if (marks > 0 && marks < line.Length && line[marks] == ' ')
                {
                    close();
                    kind = Heading;
                    words.Append(line.TrimStart('#').Trim());
                    close();
                    continue;
                }
                string item = indent <= 3 ? ItemText(line) : null;
                if (item != null)
                {
                    close();
                    kind = Item;
                    words.Append(item);
                    continue;
                }
                if (IsOnlyALink(line) && words.Length == 0) continue;
                if (kind == ' ') kind = Paragraph;
                if (words.Length > 0) words.Append(' ');
                words.Append(line);
            }
            close();
            return blocks;
        }

        // Where the section is a list item: its words after the mark ("- ", "* ", "+ " or "1. "), else null.
        private static string ItemText(string line)
        {
            if (line.Length > 2 && (line[0] == '-' || line[0] == '*' || line[0] == '+') && line[1] == ' ')
                return line.Substring(2).Trim();
            int digits = 0;
            while (digits < line.Length && char.IsDigit(line[digits])) digits++;
            if (digits > 0 && digits + 1 < line.Length && line[digits] == '.' && line[digits + 1] == ' ')
                return line.Substring(digits + 2).Trim();
            return null;
        }

        /// Words as they read: [text](link) as its text, and the marks of ** and * and ` taken out - but what is
        /// between backticks is kept as written, *.old-* and all. A line that was only a link is nothing.
        internal static string Plain(string line)
        {
            if (IsOnlyALink(line)) return "";
            var text = new StringBuilder();
            int i = 0;
            while (i < line.Length)
            {
                char c = line[i];
                if (c == '`')
                {
                    int shut = line.IndexOf('`', i + 1);
                    if (shut > i)
                    {
                        text.Append(line, i + 1, shut - i - 1);
                        i = shut + 1;
                        continue;
                    }
                    i++;
                    continue;
                }
                int close = c == '[' ? line.IndexOf("](", i, StringComparison.Ordinal) : -1;
                int end = close > 0 ? line.IndexOf(')', close) : -1;
                if (close > 0 && end > 0)
                {
                    // The link's text, read again: it may hold emphasis or code of its own.
                    text.Append(Plain(line.Substring(i + 1, close - i - 1)));
                    i = end + 1;
                    continue;
                }
                if (c == '*') { i++; continue; }
                text.Append(c);
                i++;
            }
            return text.ToString().Trim();
        }

        private static bool IsOnlyALink(string line)
        {
            return line.StartsWith("[", StringComparison.Ordinal) && line.EndsWith(")", StringComparison.Ordinal) &&
                   line.IndexOf("](", StringComparison.Ordinal) == line.LastIndexOf("](", StringComparison.Ordinal);
        }
    }

    /// An update's time limit, which the Notes page does not count against (v0.6.16): the time a person spends reading
    /// what is new is theirs, not the installer's, so a long read never ends as "still running" with nothing installed.
    /// Told the time in milliseconds, never reading a clock itself, so the rule can be checked without waiting.
    internal sealed class InstallerClock
    {
        private readonly long limit;
        private readonly object gate = new object();
        private long paused;
        private long since = -1;

        internal InstallerClock(long limit)
        {
            this.limit = limit;
        }

        /// The question is shown at `now`: the wait from here on is the person's.
        internal void Pause(long now)
        {
            lock (gate) if (since < 0) since = now;
        }

        /// The question is answered at `now`: the installer's time runs again.
        internal void Resume(long now)
        {
            lock (gate)
            {
                if (since < 0) return;
                paused += Math.Max(0, now - since);
                since = -1;
            }
        }

        /// Whether the installer has had its whole time at `now`, less every wait on the question - never while one is
        /// being asked.
        internal bool Over(long now)
        {
            lock (gate)
            {
                if (since >= 0) return false;
                return now - paused >= limit;
            }
        }
    }

    /// How far along the installer is: read from the lines install.ps1 and the bootstrap print, never from a timer.
    ///
    /// Each line a step of theirs begins with moves the bar to that step's place and names the step; a line it does
    /// not know leaves both as they were, and the bar never goes back. The lines are the scripts' own English ones,
    /// which they print in every language - the words the setup step prints in the person's language are never
    /// read. The setup program's own two steps, checking its archive and unpacking it, come first (Unpacked).
    ///
    /// Inside a step the bar moves only as far as the work really is: where the step counts what it does - the files
    /// copied or removed, the plugin's commands, setup's own steps, the health check's checks - it says so on a
    /// progress line (Variable), and the bar takes that share of the way to the next milestone (Within). Nothing
    /// moves it with time: a step that counts nothing, or an older installer that prints no progress line, leaves the
    /// bar at its milestone until the next one. What the bar draws glides up to that place (Glide), never past it.
    internal static class InstallerProgress
    {
        internal struct Milestone
        {
            internal readonly string Starts;
            internal readonly double At;
            internal readonly string Step;

            internal Milestone(string starts, double at, string step)
            {
                Starts = starts;
                At = at;
                Step = step;
            }
        }

        /// Where unpacking ends and install.ps1 begins, for a setup program.
        internal const double UnpackedAt = 0.25;

        // install.ps1, in the order it prints them (build/install/install.ps1).
        private static readonly Milestone[] Installing =
        {
            new Milestone("edition: ", 0.27, "codex"),
            // Codex found, the folder claimed and the old payload set aside: a step of its own, so "Copying the program
            // files" names only the copy (v0.6.18 acceptance: the label showed twice, the watcher and Dashboard between).
            new Milestone("[ok] Found Codex", 0.30, "prepare"),
            new Milestone("Installing program files", 0.33, "prepare"),
            new Milestone("Updating program files", 0.33, "prepare"),
            new Milestone("Stopping the running watcher", 0.40, "watcher"),
            // The Dashboard's close and the copy itself have their own lines (v0.6.16 acceptance: the step stayed on
            // the watcher through both, while the log went on).
            new Milestone("Closing the Dashboard", 0.45, "dashboard"),
            new Milestone("Copying the program files into place", 0.50, "files"),
            new Milestone("[ok] Bundled Python", 0.60, "plugin"),
            new Milestone("Registering the Codex plugin", 0.62, "plugin"),
            new Milestone("Setting up the watcher", 0.78, "setup"),
            new Milestone("Checking the installation", 0.92, "check"),
        };

        // scripts/bootstrap.ps1 -Update, then the install.ps1 it runs. The bootstrap prints `edition:` before it
        // downloads anything, so that line is not a step here.
        private static readonly Milestone[] Updating =
        {
            new Milestone("Asking github.com which release is newest", 0.05, "ask"),
            new Milestone("Asking api.github.com for this repository's list of releases", 0.05, "ask"),
            // Install another version...'s -Pick, which asks for the whole list again before it downloads.
            new Milestone("Asking api.github.com for this repository's whole list of releases", 0.05, "ask"),
            new Milestone("Downloading v", 0.10, "download"),
            new Milestone("SHA-256 ", 0.25, "verify"),
            new Milestone("[ok] SHA-256", 0.25, "verify"),
            new Milestone("[ok] Archive contents verified", 0.30, "verify"),
            new Milestone("Installing", 0.35, "prepare"),
            new Milestone("[ok] Found Codex", 0.40, "prepare"),
            new Milestone("Updating program files", 0.45, "prepare"),
            new Milestone("Installing program files", 0.45, "prepare"),
            new Milestone("Stopping the running watcher", 0.50, "watcher"),
            new Milestone("Closing the Dashboard", 0.53, "dashboard"),
            new Milestone("Copying the program files into place", 0.57, "files"),
            new Milestone("[ok] Bundled Python", 0.65, "plugin"),
            new Milestone("Registering the Codex plugin", 0.68, "plugin"),
            new Milestone("Setting up the watcher", 0.80, "setup"),
            new Milestone("Checking the installation", 0.92, "check"),
        };

        // install.ps1 -Uninstall.
        private static readonly Milestone[] Removing =
        {
            new Milestone("Closing the Dashboard", 0.05, "dashboard"),
            new Milestone("Removing the watcher, autostart", 0.15, "unregister"),
            new Milestone("Removing the Codex plugin", 0.40, "remove_plugin"),
            new Milestone("The Codex plugin is not installed", 0.40, "remove_plugin"),
            new Milestone("Removing the marketplace", 0.50, "remove_plugin"),
            new Milestone("Removing program files", 0.60, "remove_files"),
            new Milestone("Releasing the files", 0.70, "remove_files"),
            new Milestone("Removed", 0.95, "finishing"),
        };

        internal static Milestone[] Of(string mode)
        {
            return mode == InstallerFlow.Update ? Updating : mode == InstallerFlow.Uninstall ? Removing : Installing;
        }

        /// The bar's place and step after `line`, from where they were: forward only, and only on a known step.
        /// True when the line moved either. Pure.
        internal static bool Advance(string mode, string line, ref double at, ref string step)
        {
            string said = (line ?? "").Trim();
            if (said.Length == 0) return false;
            foreach (Milestone milestone in Of(mode))
            {
                if (!said.StartsWith(milestone.Starts, StringComparison.Ordinal)) continue;
                if (milestone.At <= at) return false;
                at = milestone.At;
                step = milestone.Step;
                return true;
            }
            return false;
        }

        /// The bar's place while a setup program unpacks entry `done` of `total`: from nothing to UnpackedAt.
        internal static double Unpacked(int done, int total)
        {
            if (total <= 0) return 0.0;
            return UnpackedAt * Math.Min(1.0, Math.Max(0.0, (double)done / total));
        }

        // ------------------------------------------------------------------ how much of a step is done

        /// The variable this window sets for the installer it starts, and for no one else: with it, install.ps1 and the
        /// setup step it runs say how much of a step is done, as `progress: <step> <done>/<total>` lines of their own.
        /// Without it - Install.cmd's console, the CI logs, an older caller - they print exactly what they always did.
        internal const string Variable = "CODEX_AUTO_RESUME_PROGRESS_LINES";

        internal const string ProgressPrefix = "progress: ";

        /// The most a step's own count moves the bar to: the whole bar is the finish's alone (InstallerBar.Finish).
        internal const double Ceiling = 0.99;

        /// Reads a progress line: its step, and how many of how many are done. False for any other line, and for one
        /// whose count is not whole numbers with 0 <= done <= total and total > 0. Pure.
        internal static bool ParseProgress(string line, out string step, out int done, out int total)
        {
            step = null;
            done = total = 0;
            string said = (line ?? "").Trim();
            if (!said.StartsWith(ProgressPrefix, StringComparison.Ordinal)) return false;
            string[] parts = said.Substring(ProgressPrefix.Length).Split(' ');
            if (parts.Length != 2 || parts[0].Length == 0) return false;
            foreach (char c in parts[0]) if (!(c >= 'a' && c <= 'z') && c != '_') return false;
            string[] count = parts[1].Split('/');
            if (count.Length != 2) return false;
            int d, t;
            var invariant = System.Globalization.CultureInfo.InvariantCulture;
            if (!int.TryParse(count[0], System.Globalization.NumberStyles.None, invariant, out d) ||
                !int.TryParse(count[1], System.Globalization.NumberStyles.None, invariant, out t)) return false;
            if (t <= 0 || d > t) return false;
            step = parts[0];
            done = d;
            total = t;
            return true;
        }

        /// Whether `line` is one of the window's own progress lines, which are read for the bar and kept out of the log.
        internal static bool IsProgress(string line)
        {
            string step;
            int done, total;
            return ParseProgress(line, out step, out done, out total);
        }

        /// The place of the milestone after the one at `place` in `mode`'s table: the nearest place beyond it, or the
        /// whole bar after the last. Pure.
        internal static double NextPlace(string mode, double place)
        {
            double next = 1.0;
            foreach (Milestone milestone in Of(mode))
                if (milestone.At > place && milestone.At < next) next = milestone.At;
            return next;
        }

        /// The bar's place with `done` of `total` of the step that began at the milestone `place`: that share of the gap
        /// to the next milestone, never past it, and never the whole bar (Ceiling). Pure.
        internal static double Within(string mode, double place, int done, int total)
        {
            if (total <= 0) return place;
            double share = Math.Min(1.0, Math.Max(0.0, (double)done / total));
            double next = NextPlace(mode, place);
            return Math.Min(place + (next - place) * share, Math.Max(place, Ceiling));
        }

        /// The bar's place after `line`, where it is a progress line of the step under way (`step`, begun at the
        /// milestone `place`): forward only. A line of another step, or no progress line, leaves it. True when it
        /// moved. Pure.
        internal static bool Progressed(string mode, string line, double place, string step, ref double at)
        {
            string said;
            int done, total;
            if (!ParseProgress(line, out said, out done, out total) || said != step) return false;
            double next = Within(mode, place, done, total);
            if (next <= at) return false;
            at = next;
            return true;
        }

        // ------------------------------------------------------------------ the bar's glide

        /// How fast the bar closes on where the work is: most of a gap within this many seconds (an exponential ease),
        /// and never slower than MinimumSpeed, so a new milestone is reached well within half a second.
        internal const double GlideSeconds = 0.08;
        internal const double MinimumSpeed = 0.4;

        /// The longest the glide to the whole bar may hold the Finish page back, in seconds.
        internal const double FinishSeconds = 0.4;

        /// What the bar shows `seconds` after it showed `shown`, gliding toward `target`: closer, never past it, never
        /// back. Pure.
        internal static double Glide(double shown, double target, double seconds)
        {
            if (target <= shown) return shown;
            if (seconds <= 0) return shown;
            double gap = target - shown;
            double step = Math.Max(gap * (1.0 - Math.Exp(-seconds / GlideSeconds)), MinimumSpeed * seconds);
            return step >= gap - 0.0005 ? target : shown + step;
        }
    }

    /// The installer's words, from the product's own catalog - the strings of the language the window speaks - with
    /// the English beside each key for a catalog that lacks it. A catalog is what the bridge answers, or one of the
    /// product's locales\<language>.json, read from the archive a setup program carries or from the installation.
    internal sealed class InstallerWords
    {
        private readonly Dictionary<string, object> catalog;
        internal readonly string Language;

        internal InstallerWords(Dictionary<string, object> catalog, string language)
        {
            this.catalog = catalog ?? new Dictionary<string, object>();
            Language = string.IsNullOrEmpty(language) ? "en" : language;
        }

        internal Dictionary<string, object> Catalog { get { return catalog; } }

        /// The words of `key` in the catalog, else `english`, with each `{name}` in `pairs` (name, value, ...) put in.
        internal string Say(string key, string english, params string[] pairs)
        {
            object found;
            string text = catalog.TryGetValue(key, out found) && found is string && ((string)found).Length > 0
                        ? (string)found : english ?? key;
            for (int i = 0; i + 1 < pairs.Length; i += 2) text = text.Replace("{" + pairs[i] + "}", pairs[i + 1] ?? "");
            return text;
        }

        /// The word of an edition: the catalog's edition.standard or edition.advanced.
        internal string EditionWord(string edition)
        {
            return edition == InstallerFlow.Advanced ? Say("edition.advanced", "Advanced") : Say("edition.standard", "Standard");
        }

        // Each step's key and its English, in no order that matters. A table rather than a switch: the in-box
        // compiler gives a long string switch a class with a random name, and the setup programs are reproducible
        // (build/normalize_pe.py refuses it).
        private static readonly string[] Steps =
        {
            "verify_setup", "Checking the setup program",
            "unpack", "Unpacking the files",
            "codex", "Looking for Codex",
            "prepare", "Preparing the program files",
            "files", "Copying the program files",
            "watcher", "Stopping the watcher that is running",
            "dashboard", "Closing the Dashboard",
            "plugin", "Adding the plugin to Codex",
            "setup", "Setting up the watcher",
            "check", "Checking the installation",
            "ask", "Asking GitHub for the newest release",
            "download", "Downloading",
            "verify", "Verifying the download",
            "unregister", "Removing the watcher and what it registered",
            "remove_plugin", "Removing the plugin from Codex",
            "remove_files", "Removing the program files",
            "finishing", "Finishing",
        };

        /// The steps' keys, for the tests: each is installer.step.<key> in the catalogs.
        internal static List<string> StepKeys()
        {
            var keys = new List<string> { "starting" };
            for (int i = 0; i < Steps.Length; i += 2) keys.Add(Steps[i]);
            return keys;
        }

        /// What a step is called while it runs.
        internal string Step(string step)
        {
            for (int i = 0; i < Steps.Length; i += 2)
                if (Steps[i] == step) return Say("installer.step." + step, Steps[i + 1]);
            return Say("installer.step.starting", "Starting");
        }

        /// The headline of a finished run: what was done, or that it did not finish and with which code.
        internal string Outcome(string mode, int code)
        {
            if (code == 0)
            {
                if (mode == InstallerFlow.Uninstall) return Say("installer.done.removed", "Codex Auto Resume is removed.");
                if (mode == InstallerFlow.Update) return Say("installer.done.updated", "Codex Auto Resume is updated.");
                return Say("installer.done.installed", "Codex Auto Resume is installed.");
            }
            if (code == InstallerFlow.StillRunning)
                return Say("installer.done.still_running", "It is taking longer than usual and is still working in the background. Look at the Dashboard again in a few minutes.");
            if (code == InstallerFlow.NotStarted)
                return Say("installer.done.not_started", "The installer could not be started.");
            return Say("installer.done.failed", "It did not finish (exit code {code}).", "code",
                       code.ToString(CultureInfo.InvariantCulture));
        }

        /// What a failure's code says beyond the headline, or null for the codes that say nothing more.
        internal string Explain(int code)
        {
            if (code == InstallerFlow.EditionChangeRefused)
                return Say("installer.done.edition_kept", "The other edition is installed here, and it was not changed.");
            if (code >= 40 && code <= 46)
                return Say("installer.done.setup_stopped", "The setup program stopped before the installer ran. The log says why.");
            return null;
        }
    }

    /// The languages the window speaks and how the first one is chosen: src/codex_auto_resume/l10n.py's rules
    /// (normalize, from_system), and its endonyms, which the language picker shows and nothing beside them.
    internal static class InstallerLanguages
    {
        /// Every catalog, English first, as l10n.LOCALES. ar and he are held (l10n.HELD): laid out and audited, never
        /// offered, never reached from Windows.
        internal static readonly string[] All =
        {
            "en", "ko", "ja", "zh-CN", "zh-TW", "es", "de", "fr", "pt-BR", "ru", "it", "tr", "pl", "uk", "vi", "id",
            "ar", "he",
        };

        internal static readonly string[] Held = { "ar", "he" };

        // The languages whose subtag is their catalog's name (l10n._LANGUAGE_HOME, the rest of it is in Normalize).
        private static readonly string[] Own =
        {
            "en", "ko", "ja", "es", "de", "fr", "ru", "it", "tr", "pl", "uk", "vi", "id", "ar", "he",
        };

        internal static readonly Dictionary<string, string> Endonyms = MakeEndonyms();

        private static Dictionary<string, string> MakeEndonyms()
        {
            var names = new Dictionary<string, string>();
            names["en"] = "English";
            names["ko"] = "한국어";
            names["ja"] = "日本語";
            names["zh-CN"] = "简体中文";
            names["zh-TW"] = "繁體中文";
            names["es"] = "Español";
            names["de"] = "Deutsch";
            names["fr"] = "Français";
            names["pt-BR"] = "Português (Brasil)";
            names["ru"] = "Русский";
            names["it"] = "Italiano";
            names["tr"] = "Türkçe";
            names["pl"] = "Polski";
            names["uk"] = "Українська";
            names["vi"] = "Tiếng Việt";
            names["id"] = "Bahasa Indonesia";
            names["ar"] = "العربية";
            names["he"] = "עברית";
            return names;
        }

        /// The languages a person can pick: every catalog but the held ones.
        internal static List<string> Offered()
        {
            var offered = new List<string>();
            foreach (string locale in All)
                if (Array.IndexOf(Held, locale) < 0) offered.Add(locale);
            return offered;
        }

        /// The offered language a tag belongs to, or null: l10n.normalize. Pure.
        internal static string Normalize(string tag)
        {
            if (tag == null) return null;
            var parts = new List<string>();
            foreach (string part in tag.Trim().Replace('_', '-').Split('-'))
                if (part.Length > 0) parts.Add(part.ToLowerInvariant());
            if (parts.Count == 0) return null;
            string language = parts[0];
            if (language == "zh")
            {
                for (int i = 1; i < parts.Count; i++)
                {
                    string part = parts[i];
                    if (part == "hant" || part == "tw" || part == "hk" || part == "mo") return "zh-TW";
                    if (part == "hans") return "zh-CN";
                }
                return "zh-CN";
            }
            string home = Array.IndexOf(Own, language) >= 0 ? language
                        : language == "pt" ? "pt-BR" : language == "in" ? "id" : language == "iw" ? "he" : null;
            if (home == null) return null;
            return Array.IndexOf(Held, home) >= 0 ? null : home;
        }

        /// The language Windows asks for, or English: only the most preferred one counts (l10n.from_system). Pure.
        internal static string FromSystem(IList<string> preferred)
        {
            if (preferred != null && preferred.Count > 0)
            {
                string found = Normalize(preferred[0]);
                if (found != null) return found;
            }
            return "en";
        }

        /// The language a stored Interface language names (l10n.resolve): an offered one as it is, `system` or
        /// anything unknown as Windows has it, and a stored one this build does not offer as English. Pure.
        internal static string Resolve(string stored, IList<string> preferred)
        {
            string chosen = (stored ?? "").Trim();
            if (chosen.Length > 0 && chosen != "system")
            {
                if (Offered().Contains(chosen)) return chosen;
                return Normalize(chosen) ?? "en";
            }
            return FromSystem(preferred);
        }

        /// The person's own override, then Windows' preferred UI languages, most preferred first (l10n.preferred_languages).
        internal static List<string> Preferred()
        {
            var found = new List<string>();
            string own = Environment.GetEnvironmentVariable("CODEX_AUTO_RESUME_LANG");
            if (!string.IsNullOrWhiteSpace(own))
            {
                found.Add(own.Trim());
                return found;
            }
            try
            {
                int count, size = 0;
                if (GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, out count, null, ref size) && size > 0)
                {
                    var buffer = new char[size];
                    if (GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, out count, buffer, ref size))
                        foreach (string tag in new string(buffer, 0, Math.Min(size, buffer.Length)).Split('\0'))
                            if (tag.Length > 0) found.Add(tag);
                }
            }
            catch (Exception) { /* Windows could not be asked: English */ }
            return found;
        }

        private const int MUI_LANGUAGE_NAME = 0x8;

        [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern bool GetUserPreferredUILanguages(int flags, out int count, char[] buffer, ref int size);

        /// Whether a language is written right to left.
        internal static bool RightToLeft(string locale)
        {
            return locale == "ar" || locale == "he";
        }
    }
}

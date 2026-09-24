// Codex Auto Resume - reopening: what the window is told to come back as.
//
// A window speaks one language and draws one theme. Its words are resolved and its colours
// decided as it opens, into hundreds of controls, and changing either in place would mean
// building every page again under a person looking at it. So when the Interface language or
// the theme it draws changes, the window closes and opens again in the new one, where it was:
// the same page and Settings section, the same bounds, maximized or not.
//
// It notices a change in three ways: a Save here; the settings changing anywhere else while it
// is open - the panel in Codex, Codex itself through MCP, another window - which it finds by
// looking at the settings file every two seconds and reading the settings through the bridge
// when it moved (WatchSettings); and, while the Theme is "system", Windows' app mode or High
// Contrast changing (WM_SETTINGCHANGE). It never reopens under unsaved edits: then a note in
// the save card says it will, and it does as soon as they are saved or put back. Nor while
// minimized, while an action is on its way, or under a dialog - it waits for those.
//
// The new window is a new process, started before this one closes. The window has no
// single-instance rule of its own - the notification-area icon and the Start menu start one
// each time - so nothing refuses it, and this one stays until the new one is on screen. Its
// command line carries only checked values (ParseArguments), and a window it opens never
// reopens again for what it reads as it opens more than once in a row (ReopenDecision), so a
// disagreement between what it was started with and what it reads cannot become a loop. If the
// new process ends before it shows anything, this window stays and goes on as it was, and does
// not try again for that language and theme (FinishReopen).
//
// It opens where this one was: by the frame one sees, not the bounds, which reach past it by the
// resize border Windows keeps invisible (InvisibleFrame) - a window snapped or flush against an
// edge came back that border's width in from the edge. And the keyboard is where it was: on Save,
// after a save (FocusName).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using System.Windows.Forms.Automation;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        internal const int KeepWindow = 0;
        internal const int ReopenWindow = 1;
        internal const int ReopenOnceSaved = 2;
        internal const int AdoptWhatWasRead = 3;
        /// How many reopens in a row may follow from what a window reads as it opens.
        internal const int MaxGeneration = 2;

        private const int WM_SETTINGCHANGE = 0x001A;
        private const int SPI_SETHIGHCONTRAST = 0x0043;
        // DWMWA_EXTENDED_FRAME_BOUNDS: the frame the desktop draws of a window.
        private const int ExtendedFrameBounds = 9;
        /// The widest an invisible resize border is taken to be, in device pixels: it is a few pixels at any scaling.
        internal const int MaxFrame = 99;

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool EnableWindow(IntPtr window, bool enable);

        [System.Runtime.InteropServices.DllImport("dwmapi.dll")]
        private static extern int DwmGetWindowAttribute(IntPtr window, int attribute,
                                                        [System.Runtime.InteropServices.Out] int[] rectangle, int size);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool IsWindowEnabled(IntPtr window);

        /// What a window that shows `openedLanguage` and `openedTheme` does once it knows the stored
        /// Interface language is `language` and the theme it would now draw is `theme` ("light", "dark"
        /// or "contrast"). Pure, so the rule can be checked without a window.
        ///   * Nothing differs, or either side is not known: KeepWindow.
        ///   * Something differs and there are unsaved edits: ReopenOnceSaved.
        ///   * Something differs in the first read since it opened, and it was itself opened by
        ///     MaxGeneration reopens in a row: AdoptWhatWasRead - it stays, and compares with what it
        ///     read from then on. Two windows in a row that each read something other than what they
        ///     were started with is a disagreement a third would only repeat.
        ///   * Otherwise: ReopenWindow.
        internal static int ReopenDecision(string openedLanguage, string openedTheme, string language, string theme,
                                           bool dirty, bool firstRead, int generation)
        {
            bool changed = (openedLanguage != null && language != null && openedLanguage != language) ||
                           (openedTheme != null && theme != null && openedTheme != theme);
            if (!changed) return KeepWindow;
            if (dirty) return ReopenOnceSaved;
            if (firstRead && generation >= MaxGeneration) return AdoptWhatWasRead;
            return ReopenWindow;
        }

        /// The generation a reopen passes on: one more than this window's when what it read as it opened
        /// was the reason, and 1 for a change it saw afterwards - a new change, which starts a new count.
        internal static int NextGeneration(bool firstRead, int generation)
        {
            return firstRead ? Math.Max(1, Math.Min(9, generation + 1)) : 1;
        }

        /// Whether a true-or-false setting picks which items of a list apply - which kinds of
        /// interruption may be recovered, which events notify - and so is a check box. Anything else
        /// turns something that runs on or off - the notifications, the notification-area icon, reduced
        /// motion, running at sign-in - and is a switch. The same setting is the same kind on the popup
        /// and on the panel in Codex.
        internal static bool IsListItem(string name)
        {
            return name != null && (name.StartsWith("recover_", StringComparison.Ordinal) ||
                                    name.StartsWith("notify_", StringComparison.Ordinal));
        }

        /// The window's command line, checked. `--page=`, `--section=` and `--theme=` must name a page,
        /// a section or a Theme there is; `--bounds=` is four whole numbers, a position in the virtual
        /// screen's range and a size from 1 to 32767; `--frame=` is four whole numbers from 0 to MaxFrame;
        /// `--focus=` is a name IsFocusName accepts; `--reopened=` is one digit from 1 to 9;
        /// `--maximized` and `--settings` are flags. Anything else, including a value that fails its
        /// check, is ignored, as an unknown argument always was.
        internal static OpenRequest ParseArguments(string[] arguments)
        {
            var request = new OpenRequest();
            if (arguments == null) return request;
            foreach (string argument in arguments)
            {
                if (string.IsNullOrEmpty(argument)) continue;
                string value;
                Rectangle bounds;
                if (argument == "--settings") request.Page = "settings";
                else if (argument == "--maximized") request.Maximized = true;
                else if ((value = After(argument, "--page=")) != null)
                {
                    if (Array.IndexOf(PageOrder, value) >= 0) request.Page = value;
                }
                else if ((value = After(argument, "--section=")) != null)
                {
                    if (Array.IndexOf(SectionOrder, value) >= 0) request.Section = value;
                }
                else if ((value = After(argument, "--theme=")) != null)
                {
                    if (value == Theme.System || value == Theme.Light || value == Theme.Dark) request.Theme = value;
                }
                else if ((value = After(argument, "--bounds=")) != null)
                {
                    if (ParseBounds(value, out bounds))
                    {
                        request.Bounds = bounds;
                        request.HasBounds = true;
                    }
                }
                else if ((value = After(argument, "--reopened=")) != null)
                {
                    if (value.Length == 1 && value[0] >= '1' && value[0] <= '9') request.Generation = value[0] - '0';
                }
                else if ((value = After(argument, "--frame=")) != null)
                {
                    Padding inset;
                    if (ParseFrame(value, out inset)) request.Frame = inset;
                }
                else if ((value = After(argument, "--focus=")) != null)
                {
                    if (IsFocusName(value)) request.Focus = value;
                }
            }
            return request;
        }

        /// Four whole numbers from 0 to MaxFrame, one or two digits each: an invisible resize border.
        private static bool ParseFrame(string text, out Padding inset)
        {
            inset = Padding.Empty;
            string[] parts = text.Split(',');
            if (parts.Length != 4) return false;
            var numbers = new int[4];
            for (int i = 0; i < parts.Length; i++)
            {
                string part = parts[i];
                if (part.Length < 1 || part.Length > 2) return false;
                for (int c = 0; c < part.Length; c++)
                    if (part[c] < '0' || part[c] > '9') return false;
                numbers[i] = int.Parse(part, NumberStyles.None, CultureInfo.InvariantCulture);
                if (numbers[i] > MaxFrame) return false;
            }
            inset = new Padding(numbers[0], numbers[1], numbers[2], numbers[3]);
            return true;
        }

        /// Whether `name` is a place FocusName gives: "save", "restore", "close" or "start"; "page." and a page;
        /// "section." and a Settings section; or "setting." and a setting's name - lower-case letters, digits
        /// and underscores, 64 at most.
        internal static bool IsFocusName(string name)
        {
            if (name == null) return false;
            if (name == "save" || name == "restore" || name == "close" || name == "start") return true;
            string rest = After(name, "page.");
            if (rest != null) return Array.IndexOf(PageOrder, rest) >= 0;
            rest = After(name, "section.");
            if (rest != null) return Array.IndexOf(SectionOrder, rest) >= 0;
            rest = After(name, "setting.");
            if (rest == null || rest.Length < 1 || rest.Length > 64) return false;
            foreach (char c in rest)
                if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_')) return false;
            return true;
        }

        private static string After(string argument, string prefix)
        {
            return argument.StartsWith(prefix, StringComparison.Ordinal) ? argument.Substring(prefix.Length) : null;
        }

        private static bool ParseBounds(string text, out Rectangle bounds)
        {
            bounds = Rectangle.Empty;
            string[] parts = text.Split(',');
            if (parts.Length != 4) return false;
            var numbers = new int[4];
            for (int i = 0; i < parts.Length; i++)
            {
                string part = parts[i];
                int start = part.StartsWith("-", StringComparison.Ordinal) ? 1 : 0;
                if (part.Length <= start || part.Length > 6) return false;
                for (int c = start; c < part.Length; c++)
                    if (part[c] < '0' || part[c] > '9') return false;
                numbers[i] = int.Parse(part, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture);
            }
            if (numbers[0] < -32768 || numbers[0] > 32767 || numbers[1] < -32768 || numbers[1] > 32767) return false;
            if (numbers[2] < 1 || numbers[2] > 32767 || numbers[3] < 1 || numbers[3] > 32767) return false;
            bounds = new Rectangle(numbers[0], numbers[1], numbers[2], numbers[3]);
            return true;
        }

        /// The command line a window that reopens itself starts the new one with: where it is - with the
        /// invisible border around its bounds, `frame` - the Theme preference stored, the generation
        /// (NextGeneration) and where the keyboard is (`focus`). Only what ParseArguments accepts is written,
        /// so every value reaches the new window as it was meant.
        internal static string ReopenArguments(string page, string section, Rectangle bounds, bool maximized,
                                               string theme, int generation, Padding frame, string focus)
        {
            var arguments = new List<string>();
            if (page != null && Array.IndexOf(PageOrder, page) >= 0) arguments.Add("--page=" + page);
            if (section != null && Array.IndexOf(SectionOrder, section) >= 0) arguments.Add("--section=" + section);
            string text = string.Format(CultureInfo.InvariantCulture, "{0},{1},{2},{3}", bounds.X, bounds.Y, bounds.Width, bounds.Height);
            Rectangle checkedBounds;
            if (ParseBounds(text, out checkedBounds)) arguments.Add("--bounds=" + text);
            if (maximized) arguments.Add("--maximized");
            string inset = string.Format(CultureInfo.InvariantCulture, "{0},{1},{2},{3}", frame.Left, frame.Top, frame.Right, frame.Bottom);
            Padding checkedFrame;
            if (frame != Padding.Empty && ParseFrame(inset, out checkedFrame)) arguments.Add("--frame=" + inset);
            arguments.Add("--theme=" + Theme.Preference(theme));
            arguments.Add("--reopened=" + Math.Max(1, Math.Min(9, generation)).ToString(CultureInfo.InvariantCulture));
            if (IsFocusName(focus)) arguments.Add("--focus=" + focus);
            return string.Join(" ", arguments.ToArray());
        }

        /// Where a window asked to open at `wanted` goes, on a screen whose working area is `area`. The window
        /// is placed by the frame one sees: `wanted` less `frame`, the resize border Windows keeps invisible
        /// on its left, right and bottom, which may reach past the area as it does around a window snapped to
        /// it. That frame is as large as it was, but no larger than the area and no smaller than `minimum`, the
        /// bounds', allows, and moved only as far as it takes to be wholly on the screen. Pure.
        internal static Rectangle PlaceOnScreen(Rectangle wanted, Rectangle area, Size minimum, Padding frame)
        {
            int width = Math.Min(area.Width, Math.Max(minimum.Width - frame.Horizontal, wanted.Width - frame.Horizontal));
            int height = Math.Min(area.Height, Math.Max(minimum.Height - frame.Vertical, wanted.Height - frame.Vertical));
            int x = Math.Max(area.Left, Math.Min(wanted.X + frame.Left, area.Right - width));
            int y = Math.Max(area.Top, Math.Min(wanted.Y + frame.Top, area.Bottom - height));
            return new Rectangle(x - frame.Left, y - frame.Top, width + frame.Horizontal, height + frame.Vertical);
        }

        /// How far this window's bounds reach past the frame one sees: the resize border Windows 10 and 11 keep
        /// invisible on the left, right and bottom of a window (9 px at 150%, where it was measured), taken from
        /// the frame the desktop draws. Padding.Empty while it cannot be measured: not on screen, maximized or
        /// minimized, or an answer no border could be.
        private Padding InvisibleFrame()
        {
            if (!IsHandleCreated || !Visible || WindowState != FormWindowState.Normal) return Padding.Empty;
            try
            {
                var drawn = new int[4];
                if (DwmGetWindowAttribute(Handle, ExtendedFrameBounds, drawn, 4 * sizeof(int)) != 0) return Padding.Empty;
                Rectangle bounds = Bounds;
                int left = drawn[0] - bounds.Left, top = drawn[1] - bounds.Top;
                int right = bounds.Right - drawn[2], bottom = bounds.Bottom - drawn[3];
                bool border = left >= 0 && top >= 0 && right >= 0 && bottom >= 0 &&
                              left <= MaxFrame && top <= MaxFrame && right <= MaxFrame && bottom <= MaxFrame;
                return border ? new Padding(left, top, right, bottom) : Padding.Empty;
            }
            catch (Exception)
            {
                return Padding.Empty;
            }
        }

        /// Settings read through the bridge: what is stored now, compared with what the window shows.
        private void Observe(Dictionary<string, object> current, bool firstRead)
        {
            Remember(current);
            FollowPanelTheme(current);
            // Words that did not come from a reply - the bridge could not be asked, and the window speaks
            // its English fallback - are no language to reopen from.
            if (openedLanguage == null) openedLanguage = storedLanguage;
            CheckReopen(firstRead);
        }

        /// The panel's own theme, as it is stored now, in the drop-down that shows it. The window is not
        /// drawn in it, so a change made in the panel or by Codex reopens nothing, as a change of language
        /// or Theme does - but left alone the drop-down would go on showing the old choice, and because a
        /// Save leaves out a value still equal to the page's baseline (ChangesJson), the window could not
        /// even write the choice it showed. So the baseline and the drop-down both follow what is stored,
        /// the baseline first, so nothing measuring unsaved edits sees the two disagree. A choice the person
        /// has made here and not saved yet is theirs, and is left where it is.
        private void FollowPanelTheme(Dictionary<string, object> current)
        {
            Control editor;
            string was, stored = Str(current, "panel_theme");
            var combo = stored != null && editors.TryGetValue("panel_theme", out editor) ? editor as ComboBox : null;
            if (combo == null || baseline == null || !baseline.TryGetValue("panel_theme", out was)) return;
            var shown = combo.SelectedItem as Choice;
            if (Json.Escape(shown == null ? null : shown.Value) != was) return;
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var item = combo.Items[i] as Choice;
                if (item == null || item.Value != stored) continue;
                baseline["panel_theme"] = Json.Escape(stored);
                if (combo.SelectedIndex != i) combo.SelectedIndex = i;
                return;
            }
        }

        private void Remember(Dictionary<string, object> current)
        {
            storedLanguage = Str(current, "interface_language") ?? "system";
            storedTheme = Theme.Preference(Get(current, "theme"));
        }

        /// Decides, and does, what a change of language or theme asks of the window (ReopenDecision).
        private void CheckReopen(bool firstRead)
        {
            if (auditing || reopening || IsDisposed || !settingsRead) return;
            string theme = Theme.Current(storedTheme);
            int decision = ReopenDecision(openedLanguage, openedTheme, storedLanguage, theme, Dirty(), firstRead,
                                          request.Generation);
            // Not again for the language and theme a new window was started for and never showed (FinishReopen).
            if (decision != KeepWindow && storedLanguage == declinedLanguage && theme == declinedTheme)
                decision = KeepWindow;
            recheck = false;
            if (decision == AdoptWhatWasRead)
            {
                openedLanguage = storedLanguage;
                openedTheme = theme;
                decision = KeepWindow;
            }
            ShowReopenNote(decision == ReopenOnceSaved);
            // Unsaved edits are looked at again every second (StartClock), so putting them back reopens it.
            if (decision == ReopenOnceSaved) recheck = true;
            if (decision != ReopenWindow) return;
            // Not while it is minimized, an action is on its way, or a dialog is open over it: then once
            // that is over.
            if (WindowState == FormWindowState.Minimized || busy > 0 || !IsHandleCreated || !IsWindowEnabled(Handle))
            {
                recheck = true;
                return;
            }
            Reopen(firstRead);
        }

        private void ShowReopenNote(bool show)
        {
            if (reopenNote == null) return;
            SetNote(reopenNote, show ? S("note.reopen_pending",
                "The window will reopen in the new language or theme once you save or discard your changes.") : "");
            reopenNote.Visible = show;
            // The save card as tall as the note needs, and back.
            if (reopenNoteShown == show) return;
            reopenNoteShown = show;
            if (fitFooter != null) fitFooter(this, EventArgs.Empty);
        }

        /// Whether the page holds edits that are not saved: an editor's value that is not what the page
        /// was built with or last saved, or a sign-in switch that is not what Windows has.
        private bool Dirty()
        {
            if (baseline == null) return false;
            foreach (KeyValuePair<string, string> pair in EditorValues())
            {
                string was;
                if (!baseline.TryGetValue(pair.Key, out was) || was != pair.Value) return true;
            }
            var startup = editors.ContainsKey("__startup") ? editors["__startup"] as CheckBox : null;
            return startup != null && startup.Checked != startupBaseline;
        }

        /// Every editor's value as the JSON a Save sends for it.
        private Dictionary<string, string> EditorValues()
        {
            var values = new Dictionary<string, string>();
            foreach (KeyValuePair<string, Control> pair in editors)
            {
                if (pair.Key == "__startup") continue;
                var check = pair.Value as CheckBox;
                var spin = pair.Value as NumericUpDown;
                var combo = pair.Value as ComboBox;
                if (check != null) values[pair.Key] = check.Checked ? "true" : "false";
                else if (spin != null) values[pair.Key] = ((int)spin.Value).ToString(CultureInfo.InvariantCulture);
                else if (combo != null)
                {
                    var chosen = combo.SelectedItem as Choice;
                    values[pair.Key] = Json.Escape(chosen == null ? null : chosen.Value);
                }
            }
            foreach (KeyValuePair<string, Func<string>> pair in jsonValues)
                values[pair.Key] = pair.Value();
            return values;
        }

        /// The changes a Save sends: every value on the page, except the Interface language and the two
        /// themes while they are still what the page was built with - so saving something else never puts
        /// back a language or theme chosen somewhere else meanwhile. The window reopens in a new language
        /// or Theme; the panel's own theme it follows in place (FollowPanelTheme).
        private string ChangesJson(Dictionary<string, string> values)
        {
            var changes = new StringBuilder("{");
            bool first = true;
            foreach (KeyValuePair<string, string> pair in values)
            {
                string was;
                if ((pair.Key == "interface_language" || pair.Key == "theme" || pair.Key == "panel_theme") &&
                    baseline != null &&
                    baseline.TryGetValue(pair.Key, out was) && was == pair.Value) continue;
                if (!first) changes.Append(',');
                first = false;
                changes.Append(Json.Escape(pair.Key)).Append(':').Append(pair.Value);
            }
            return changes.Append('}').ToString();
        }

        /// The settings file's time and size, or 0 when there is none: what WatchSettings compares.
        private long SettingsStamp()
        {
            try
            {
                var file = new FileInfo(Path.Combine(Path.Combine(installRoot ?? "", "config"), "settings.json"));
                return file.Exists ? file.LastWriteTimeUtc.Ticks * 31 + file.Length : 0;
            }
            catch (Exception)
            {
                return 0;
            }
        }

        /// Called every two seconds by the clock: when the settings file moved, the settings are read on a
        /// worker and compared with what the window shows (Observe). Not while this window's own action is
        /// on its way - a Save looks for itself - and one read at a time.
        private void WatchSettings()
        {
            if (auditing || reopening || readingSettings || busy > 0 || !settingsRead) return;
            long stamp = SettingsStamp();
            if (stamp == settingsStamp) return;
            settingsStamp = stamp;
            readingSettings = true;
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply = null;
                try { reply = bridge.Call("settings", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    readingSettings = false;
                    var current = Ok(reply) ? Map(reply, "settings") : null;
                    if (current != null) Observe(current, false);
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { readingSettings = false; }
            });
        }

        /// Windows' app mode or High Contrast changed: the theme the window would draw may have.
        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (m.Msg != WM_SETTINGCHANGE || auditing || !IsHandleCreated) return;
            bool colours = m.WParam.ToInt64() == SPI_SETHIGHCONTRAST;
            if (!colours && m.LParam != IntPtr.Zero)
            {
                try { colours = System.Runtime.InteropServices.Marshal.PtrToStringUni(m.LParam) == "ImmersiveColorSet"; }
                catch (Exception) { }
            }
            if (colours) BeginInvoke(new MethodInvoker(delegate { CheckReopen(false); }));
        }

        /// Starts this window again in what is stored, where it is, and closes this one once the new one
        /// is on screen - or after ten seconds, whatever it is doing. If the new one cannot be started,
        /// this one stays as it is: the old words and colours are better than no window.
        private void Reopen(bool firstRead)
        {
            if (reopening || auditing) return;
            bool normal = WindowState == FormWindowState.Normal;
            Rectangle bounds = normal ? Bounds : RestoreBounds;
            // The invisible border as it is now; maximized, as it was last measured on screen, or as the window this
            // one replaced measured it.
            Padding measured = normal ? InvisibleFrame() : Padding.Empty;
            if (measured != Padding.Empty) invisibleFrame = measured;
            string arguments = ReopenArguments(currentPage ?? firstPage, currentSection, bounds,
                                               WindowState == FormWindowState.Maximized, storedTheme,
                                               NextGeneration(firstRead, request.Generation), invisibleFrame,
                                               reopenFocus ?? FocusName());
            Process started;
            try
            {
                var info = new ProcessStartInfo(typeof(SettingsForm).Assembly.Location, arguments);
                info.UseShellExecute = false;
                info.WorkingDirectory = installRoot;
                started = Process.Start(info);
            }
            catch (Exception)
            {
                return;
            }
            if (started == null) return;
            reopening = true;
            reopenLanguage = storedLanguage;
            reopenTheme = Theme.Current(storedTheme);
            recheck = false;
            ShowReopenNote(false);
            StopClock();
            // No more input here: anything typed now would be lost with this window.
            try { EnableWindow(Handle, false); }
            catch (Exception) { }
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                bool shown = true;
                try
                {
                    shown = AwaitWindow(delegate { started.Refresh(); return started.MainWindowHandle != IntPtr.Zero; },
                                        delegate { return started.HasExited; }, 10000, 50);
                }
                catch (Exception) { }
                finally { started.Dispose(); }
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(new MethodInvoker(delegate { FinishReopen(shown); })); }
                catch (Exception) { }
            });
        }

        /// Waits for the window a reopen started: true once `hasWindow` says there is one, or once `milliseconds`
        /// have passed, whatever it is doing; false when `hasExited` says the process ended first. A window is
        /// looked for before an ending. Pure but for the wait, so both endings are checked without a process.
        internal static bool AwaitWindow(Func<bool> hasWindow, Func<bool> hasExited, int milliseconds, int step)
        {
            var waited = Stopwatch.StartNew();
            while (true)
            {
                if (hasWindow()) return true;
                if (hasExited()) return false;
                if (waited.ElapsedMilliseconds >= milliseconds) return true;
                System.Threading.Thread.Sleep(Math.Max(1, step));
            }
        }

        /// The end of a reopen. The new window came up (`shown`): this one closes. The new process ended before
        /// it showed anything: this one stays as it was - taking input again, its clock running - and does what
        /// a read or a save held back for the reopen (HoldForReopen), so the page follows the settings and a save
        /// still says it saved. It does not try again for the language and theme it could not reopen in, or a
        /// window that cannot start would be started over and over; a different change reopens it as ever.
        private void FinishReopen(bool shown)
        {
            if (shown)
            {
                Close();
                return;
            }
            reopening = false;
            declinedLanguage = reopenLanguage;
            declinedTheme = reopenTheme;
            try { if (IsHandleCreated) EnableWindow(Handle, true); }
            catch (Exception) { }
            StartClock();
            MethodInvoker held = heldForReopen;
            heldForReopen = null;
            if (held != null) held();
        }

        /// Does `work` now or, while the window is reopening, once it is known to stay (FinishReopen): a window
        /// about to close has no page to fill and no save to confirm.
        private void HoldForReopen(MethodInvoker work)
        {
            if (reopening) heldForReopen += work;
            else work();
        }

        /// The control the keyboard is on, inside whichever containers hold it - a number field's own edit.
        private Control FocusedControl()
        {
            Control active = ActiveControl;
            for (var container = active as ContainerControl; container != null && container.ActiveControl != null;
                 container = container.ActiveControl as ContainerControl)
                active = container.ActiveControl;
            return active;
        }

        /// Where the keyboard is in this window, as a name a reopen passes on (`--focus=`, IsFocusName): a button of
        /// the save card, the header's Start button, a page's or a Settings section's tab, or a setting's editor.
        /// Anywhere else, the tab of the Settings section or page on screen, so a screen reader starts again at
        /// the page the person is on rather than at the first button of the window.
        internal string FocusName()
        {
            for (Control control = FocusedControl(); control != null && control != this; control = control.Parent)
            {
                if (control == saveButton) return "save";
                if (control == restoreButton) return "restore";
                if (control == closeButton) return "close";
                if (control == startButton) return "start";
                foreach (KeyValuePair<string, NavButton> pair in navButtons)
                    if (pair.Value == control) return "page." + pair.Key;
                foreach (KeyValuePair<string, NavButton> pair in sectionButtons)
                    if (pair.Value == control) return "section." + pair.Key;
                foreach (KeyValuePair<string, Control> pair in editors)
                    if (pair.Value == control && IsFocusName("setting." + pair.Key)) return "setting." + pair.Key;
            }
            string page = currentPage ?? firstPage;
            return page == "settings" ? "section." + currentSection : "page." + page;
        }

        /// The control a FocusName names in this window, or null when there is none.
        internal Control FocusTarget(string name)
        {
            if (!IsFocusName(name)) return null;
            if (name == "save") return saveButton;
            if (name == "restore") return restoreButton;
            if (name == "close") return closeButton;
            if (name == "start") return startButton;
            NavButton tab;
            Control editor;
            string rest = After(name, "page.");
            if (rest != null) return navButtons.TryGetValue(rest, out tab) ? tab : null;
            rest = After(name, "section.");
            if (rest != null) return sectionButtons.TryGetValue(rest, out tab) ? tab : null;
            rest = After(name, "setting.");
            return editors.TryGetValue(rest, out editor) ? editor : null;
        }

        /// As a window that replaces another opens: the keyboard on the tab of the page it opens on, which is
        /// there already, until the control the old window had it on is built (FocusPending). A window a person
        /// opened keeps Windows' first control, as it always did.
        private void FocusInterim()
        {
            pendingFocus = request.Focus;
            NavButton tab;
            if (pendingFocus != null && navButtons.TryGetValue(currentPage ?? firstPage, out tab)) ActiveControl = tab;
        }

        /// Once the settings are read and the page built: the keyboard where the window this one replaces had it -
        /// unless the person has moved it since, or that control cannot take it, out of sight or unable to act.
        private void FocusPending()
        {
            string name = pendingFocus;
            pendingFocus = null;
            NavButton tab;
            if (name == null || !navButtons.TryGetValue(currentPage ?? firstPage, out tab) || FocusedControl() != tab) return;
            Control target = FocusTarget(name);
            if (target == null || target == tab) return;
            Control control = target;
            for (; control != null && control != this; control = control.Parent)
                if (!OwnVisible(control) || !control.Enabled) return;
            if (control == this) ActiveControl = target;
        }

        /// Called every second by the clock.
        private void TickReopen()
        {
            if (ticks % 2 == 0) WatchSettings();
            if (recheck) CheckReopen(false);
        }
    }
}

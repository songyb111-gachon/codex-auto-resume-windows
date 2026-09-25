// Codex Auto Resume - standalone Windows settings window.
//
// This exists so the product stays configurable exactly when the thing it recovers is
// not: with Codex closed, the plugin unloaded, the MCP server unavailable or the
// watcher stopped. It talks only to our own local control bridge.
//
// It deliberately owns no configuration of its own. Every read and write goes through
// the same validated Python control layer the command line, the Codex skill and the
// MCP server use, so a value set here is identical to a value set anywhere else. The
// window renders itself from the schema that layer publishes, which is why adding a
// setting there makes it appear here without touching this file.
//
// Layout notes, each of which came from looking at the result rather than the code:
//   * Sizes come from AutoSize containers, never fixed pixels. Above 100% scaling a
//     hardcoded row is shorter than its own text and clips the descenders.
//   * Groups sit in a TableLayoutPanel, not a FlowLayoutPanel: flow hands a child its
//     preferred width, so an AutoSize group collapses to the width of its content.
//   * The Settings page is a list of sections beside one section's cards. Everything on
//     one scrolling page stopped fitting a laptop screen once languages and the
//     Continuation message joined it, and a setting is found faster under the name of
//     what it is for.
//   * Status leads. What the watcher is doing is the reason the window gets opened, so
//     it sits at the top in the largest type here, and the settings follow it.
//   * Every status fact is its own label in its own cell, never one concatenated string.
//     A single label wraps or truncates as the window narrows, and what disappears first
//     is the version - the part people are asked for when reporting a problem.
//   * Colours come from gui/Brand.cs, which is generated from the palette in
//     src/codex_auto_resume/brand.py, through Palette, which holds the theme the window opened
//     in. Do not write a literal colour in this file, nor one of Brand's light fields.
//   * A window speaks one language and draws one theme, both decided as it opens. When either
//     changes - saved here, or anywhere else, or Windows' own app mode under "system" - the
//     window reopens itself where it was (see Reopen), never while somebody has edits unsaved.
//
// Built with the in-box C# compiler against .NET Framework 4.8, which ships on every
// supported Windows, so the release carries no extra runtime for the interface.
//
// The window is one `partial class SettingsForm`, written across several files since
// v0.6.10-alpha. This one is the process and the window as a window: `Program.Main`, the
// `Bridge` it calls the control layer through, and the form's scale, columns, section list,
// header and footer. Beside it: gui/SettingsPage.cs is the Settings page itself - its cards,
// its rows, its editors and Save - gui/WindowJson.cs the JSON reader and the words cache,
// gui/WindowReopen.cs the reopening, and gui/WindowAudit.cs the layout audit the tests run.
// The Dashboard's half is gui/Dashboard.cs and the five files beside it, and
// `gui/window.sources` is the list of them all.

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
    /// A panel that paints into a back buffer, so a repaint never shows it erased.
    ///
    /// The status dot is drawn in a Paint handler on an ordinary Panel, which Windows
    /// erases to the background colour first and paints second. Anything that looks in
    /// between - a screenshot, or the eye during a status refresh - sees no dot at all:
    /// the Korean window screenshot published with v0.5.7 has a white square where the
    /// dot belongs.
    internal sealed class BufferedPanel : Panel
    {
        internal BufferedPanel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        }
    }

    /// The same, for a table that draws its own card border and accent rail.
    ///
    /// The third instance of one bug: after the dot and the header rule, a capture of the
    /// Korean window came out with the Windows card's border and rail missing. Every
    /// control in this file that has a Paint handler is now one of these two classes,
    /// and tests/test_gui_layout.py holds it to that.
    internal sealed class BufferedTable : TableLayoutPanel
    {
        internal BufferedTable()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        }
    }

    /// What the window was asked to open with, from its command line (SettingsForm.ParseArguments).
    /// Every value has been checked against what it may be; what was not given, or not valid, is
    /// null, false or zero, and the window opens as it always did.
    internal sealed class OpenRequest
    {
        /// A page of the window: `--page=<name>`, or `--settings`, the older spelling.
        internal string Page;
        /// A Settings section: `--section=<name>`.
        internal string Section;
        /// A Theme preference - "system", "light" or "dark" - that the window opens in instead of the
        /// stored one: `--theme=<name>`, which a window that reopens itself passes on (see Reopen).
        internal string Theme;
        /// Where the window goes, in device pixels: `--bounds=<x>,<y>,<width>,<height>`.
        internal bool HasBounds;
        internal Rectangle Bounds;
        /// `--maximized`.
        internal bool Maximized;
        /// How many reopens in a row led to this window, 1 to 9: `--reopened=<n>`. 0 when a person
        /// opened it.
        internal int Generation;
        /// How far the bounds reach past the frame one sees - the resize border Windows keeps invisible -
        /// as the window this one replaces measured it: `--frame=<left>,<top>,<right>,<bottom>`. Empty
        /// when not given.
        internal Padding Frame;
        /// Where the keyboard was in the window this one replaces (SettingsForm.FocusName): `--focus=<name>`.
        internal string Focus;
    }

    /// A drop-down entry whose stored value and displayed label differ.
    internal sealed class Choice
    {
        internal readonly string Value;
        private readonly string label;

        internal Choice(string value, string label) { Value = value; this.label = label; }

        public override string ToString() { return label; }
    }

    internal sealed class Bridge
    {
        private readonly string python;
        private readonly string appSrc;

        internal Bridge(string root)
        {
            python = Path.Combine(root, "runtime", "python.exe");
            appSrc = Path.Combine(root, "app", "src");
        }

        internal bool Available { get { return File.Exists(python) && Directory.Exists(appSrc); } }

        internal Dictionary<string, object> Call(string command, string argument)
        {
            var info = new ProcessStartInfo();
            info.FileName = python;
            // The module path is passed as an argument, not embedded in the code: a
            // Windows path inside a Python literal inside a quoted command line has to
            // survive two different escaping rules, and getting either wrong is silent.
            string code = "import sys;sys.path.insert(0,sys.argv[1]);" +
                          "from codex_auto_resume.controlcli import main;" +
                          "sys.exit(main(sys.argv[2:]))";
            var arguments = new StringBuilder();
            arguments.Append("-c ").Append(Quote(code)).Append(' ').Append(Quote(appSrc));
            arguments.Append(' ').Append(command);
            // The argument goes in on stdin, never on the command line: "-" tells the bridge to
            // read it there. This call answers whenever the long-lived process has failed, and
            // then carries every Custom message on the page - on each pause in typing, for the
            // Preview. A command line can be read by any process this user runs and is what
            // process auditing keeps, and it stops at 32767 characters, which a Save could pass.
            bool hasArgument = !string.IsNullOrEmpty(argument);
            if (hasArgument) arguments.Append(" -");
            info.Arguments = arguments.ToString();
            info.UseShellExecute = false;
            info.RedirectStandardInput = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.CreateNoWindow = true;
            info.StandardOutputEncoding = Encoding.UTF8;

            using (Process process = Process.Start(info))
            {
                // UTF-8 written by hand, as the long-lived bridge writes its requests: .NET
                // Framework encodes a redirected stdin with the console code page. Closed with or
                // without an argument, so the child never waits on a stdin nobody writes to.
                if (hasArgument)
                {
                    byte[] bytes = new UTF8Encoding(false).GetBytes(argument);
                    process.StandardInput.BaseStream.Write(bytes, 0, bytes.Length);
                }
                process.StandardInput.Close();
                string output = process.StandardOutput.ReadToEnd();
                process.StandardError.ReadToEnd();
                process.WaitForExit(30000);
                if (string.IsNullOrEmpty(output))
                    throw new InvalidOperationException("No response from the local service.");
                return (Dictionary<string, object>)Json.Parse(output);
            }
        }

        // Windows command-line quoting, by the documented CommandLineToArgvW rules: a
        // run of backslashes is only special immediately before a quote, where 2n means
        // n literal backslashes and a delimiter, and 2n+1 means n and a literal quote.
        // Doubling every backslash instead - the obvious-looking version - turns a path
        // into one with doubled separators. Windows tolerates that, so it works right up
        // until something compares two paths for equality.
        internal static string Quote(string value)
        {
            var builder = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value ?? string.Empty)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '\"') builder.Append('\\', slashes * 2 + 1).Append('\"');
                else builder.Append('\\', slashes).Append(c);
                slashes = 0;
            }
            return builder.Append('\\', slashes * 2).Append('\"').ToString();
        }
    }

    internal sealed partial class SettingsForm : Form
    {
        // The palette lives in src/codex_auto_resume/brand.py and is generated into
        // gui/Brand.cs, so the window, the Codex panel, the icon and the plugin card
        // cannot disagree about what colour this product is. The window reads it through
        // Palette, which holds the one theme it opened in: light, dark, or High Contrast,
        // where the person has chosen their colours for a reason and every colour is a
        // system one.
        private static bool Contrast { get { return Palette.Contrast; } }
        private static Color Ink { get { return Palette.Ink; } }
        private static Color Muted { get { return Palette.Muted; } }
        // Secondary text that is still live. In High Contrast mode GrayText means
        // "disabled", so there it is the ordinary text colour, and weight and position
        // carry the hierarchy instead. Muted stays for what really is disabled.
        private static Color Secondary { get { return Palette.Secondary; } }
        private static Color Line { get { return Palette.Line; } }
        // A card's own ground: what everything opaque inside a card is filled with.
        private static Color Card { get { return Palette.Card; } }
        private static Color Canvas { get { return Palette.Canvas; } }
        private static Color Accent { get { return Palette.Accent; } }
        private static Color OnAccent { get { return Palette.OnAccent; } }
        private static Color Active { get { return Palette.Active; } }

        private readonly PersistentBridge bridge;
        private readonly Dictionary<string, Control> editors = new Dictionary<string, Control>();

        private readonly TableLayoutPanel columns = new SoftStack();
        // The Settings page's sections, in the order the section list shows them. Each is a
        // single column of cards; one is on screen at a time.
        private static readonly string[] SectionOrder = { "general", "recovery", "continuation", "appearance", "advanced" };
        private readonly Dictionary<string, TableLayoutPanel> sections = new Dictionary<string, TableLayoutPanel>();
        private readonly Dictionary<string, NavButton> sectionButtons = new Dictionary<string, NavButton>();
        private readonly SoftPage sectionScroll = new SoftPage();
        private string currentSection = "general";
        // The schema and settings as read, until the Settings editors are built from them
        // (BuildEditorsLater); null once they have been.
        private List<object> pendingSchema;
        private Dictionary<string, object> pendingSettings;
        private bool shown, buildQueued;
        // Set by LayoutAudit: the window is measured, so nothing is read and nothing is scheduled.
        private bool auditing;
        // Editors whose value is not a check box, a number or a drop-down, as the JSON each
        // contributes to a save.
        private readonly Dictionary<string, Func<string>> jsonValues = new Dictionary<string, Func<string>>();
        // The Continuation message editors, kept so the Preview and the visibility rules can
        // read what is on screen without asking anything.
        private ChoiceGroup styleGroup;
        private SoftCombo modeCombo, interfaceCombo, continuationCombo, previewReason, perReasonCombo;
        private TableLayoutPanel customCard, perReasonPanel;
        private SoftTextArea globalText, perReasonText;
        private Label globalCount, perReasonCount, customRefusal, previewSource;
        private SoftQuote previewText;
        private readonly Dictionary<string, string> perReasonValues = new Dictionary<string, string>();
        private readonly List<string> reasonOrder = new List<string>();
        private string perReasonShown;
        private Timer previewTimer;
        private int previewToken;
        private string loadedInterfaceLanguage = "system";
        // What the window was opened with (see OpenRequest), and the installation it belongs to.
        private readonly OpenRequest request;
        private readonly string installRoot;
        // Reopening (see Reopen). What this window shows - the Interface language its words were
        // resolved for, and the theme it draws - against what is stored: the Interface language and
        // Theme preference as last read or saved.
        private string openedLanguage, openedTheme, storedLanguage, storedTheme;
        private bool settingsRead, readingSettings, reopening, recheck;
        private long settingsStamp;
        // The language and theme a reopen on its way is for; and the pair a new window was last started for
        // that never showed, which this window does not try again (CheckReopen, FinishReopen).
        private string reopenLanguage, reopenTheme, declinedLanguage, declinedTheme;
        // What a read or a save leaves undone while the window reopens, done after all if it stays.
        private MethodInvoker heldForReopen;
        // Where the keyboard was as a save that may reopen the window began (Save); and where a window that
        // replaces another still has to put it once the page is built (FocusPending).
        private string reopenFocus, pendingFocus;
        // The resize border Windows keeps invisible around this window, as last measured (InvisibleFrame).
        private Padding invisibleFrame;
        // Whether the reopen note is showing, which the save card's height follows (BuildFooter).
        private bool reopenNoteShown;
        private EventHandler fitFooter;
        // The editors' values as the page was built or last saved, which is what "unsaved edits" is
        // measured from, and the sign-in switch as the status last said.
        private Dictionary<string, string> baseline;
        private bool startupBaseline;
        private NoteLabel reopenNote;
        // The same limit the settings layer enforces. Shown, never enforced here: text past it
        // is refused when saved rather than cut off while it is typed.
        private const int MaxCustomLength = 2000;
        // The header and the footer are cards on the canvas, as the panel's hero and its save bar
        // are: each strip is a ground (see Ground) and its card is lifted on it. Grounds are
        // double-buffered, because the header is invalidated on every status refresh, and an
        // unbuffered strip was erased and repainted a moment later - a capture taken in that
        // moment, one in four measured, showed the header with half of it missing.
        private readonly Panel header = new SoftPage();
        private readonly Panel footer = new SoftPage();
        private readonly SoftCard hero = new SoftCard();
        private readonly SoftCard savebar = new SoftCard();
        private readonly Label headline = new Label();
        private readonly Label detail = new Label();
        private readonly Label versionText = new Label();
        private readonly HaloDot stateDot = new HaloDot();
        // v0.6.5: the notification-area icon's motion on the taskbar button (TaskbarMark), told the icon's state for what
        // the window read wherever stateDot is told its own (TellTaskbar); null in a window LayoutAudit builds, and
        // without the product's own icon.
        private TaskbarMark taskbar;
        private Button startButton, closeButton;

        // The interface vocabulary, in the language the engine resolved. Fetched once,
        // over the same bridge every other read goes through.
        //
        // The window does not decide the language and carries no Korean of its own. It
        // used to carry English of its own, which is why a machine whose Windows is
        // Korean, whose notifications were Korean and whose setup output was Korean still
        // opened an English settings window. `S` falls back to the English literal at each
        // call site, so a bridge that cannot answer degrades to what this file used to be
        // rather than to blank labels.
        private Dictionary<string, object> strings = new Dictionary<string, object>();
        // Each language named in itself, and the language Windows asks for, for the two
        // language drop-downs. Neither is translated.
        private Dictionary<string, object> endonyms = new Dictionary<string, object>();
        private string systemLanguage = "en";

        private string S(string key, string fallback)
        {
            object value;
            if (strings.TryGetValue(key, out value) && value is string && ((string)value).Length > 0)
                return (string)value;
            return fallback;
        }

        private string S(string key, string fallback, string token, object replacement)
        {
            return S(key, fallback).Replace("{" + token + "}", Convert.ToString(replacement,
                                                                               CultureInfo.InvariantCulture));
        }

        /// The bridge's strings reply, or null when it could not be had.
        private Dictionary<string, object> AskStrings()
        {
            try
            {
                return bridge.Call("strings", null);
            }
            catch (Exception)
            {
                // English, then. A settings window that will not open because it could
                // not fetch its own labels is worse than one in the wrong language.
                return null;
            }
        }

        /// Takes the words, the language names and Windows' language from a strings reply.
        private void AdoptStrings(Dictionary<string, object> reply)
        {
            if (!Ok(reply) || !(Get(reply, "strings") is Dictionary<string, object>)) return;
            strings = (Dictionary<string, object>)reply["strings"];
            // The Interface language these words were resolved for, as the settings stored it.
            openedLanguage = Get(reply, "preference") as string;
            object names, system;
            if (reply.TryGetValue("endonyms", out names) && names is Dictionary<string, object>)
                endonyms = (Dictionary<string, object>)names;
            if (reply.TryGetValue("system_language", out system) && system is string)
                systemLanguage = (string)system;
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern int GetDpiForSystem();

        private static readonly double SystemScale = MeasureDpiScale();
        private static double dpiScale = SystemScale;

        /// The window's opening client size, in logical pixels.
        ///
        /// The height is the Overview's (v0.6.5). Its cards hold what they hold with the button each leads to at
        /// its bottom left, in a row of its own under the last line (Lead), and FitOverview gives the rows what the
        /// tallest needs, a little more, and under the last row the page's own padding, as every page has under its
        /// last card. What the rows need, with the most the Overview ever shows - three lines under Waiting, four
        /// finished conversations, four facts in Right now - is the same in all nine languages (every line is one
        /// line, whatever it says), and per scaling a window of 626 px at 100%, 631 at 125%, 629 at 150%, 635 at 175%
        /// and 624 at 200% (measured built and never shown, text drawn as this window draws it;
        /// tests/test_gui_layout.py holds the page to it). 664 is that at 100% with 38 px more, shared by the two
        /// rows: every card a little taller than what it holds at every scaling - 14 px at 175%, 19 at 100% - never
        /// past comfort (OverviewComfort), and at none a band. Chosen from renders at 632, 648 and 664, side by side.
        ///
        /// Taller than the 632 of v0.6.4, which was the tallest window that fits a 1920 by 1080 screen at 150%
        /// with the taskbar (a work area of 1008 device pixels, less a frame of 56: 952, or 634 logical). There
        /// KeepOnScreen gives the window the work area's height, and the Overview still fits - its rows need 629 -
        /// with the space under them going first. A shorter screen still - KeepOnScreen gives 601 px on a 1920 by
        /// 1200 screen at 175% - scrolls the Overview on the soft bar, where v0.6.4's buttons beside the facts
        /// fitted: a button in a row of its own costs its row a button and a gap.
        ///
        /// The width is where the Pending list draws "waiting for the usage reset" and "Usage limit"
        /// whole beside "Why it is waiting" at its full 256 px: 933 to 946 in English, 813 to 817 in
        /// Korean.
        internal const int OpeningWidth = 1000;
        internal const int OpeningHeight = 664;

        /// The display's scale. Read-only to the window; only LayoutAudit stands another
        /// scale in, to measure a layout at a scaling this machine is not set to.
        internal static double DpiScale
        {
            get { return dpiScale; }
        }

        // Every fixed number in this file is written at 96 DPI and scaled here.
        //
        // Windows Forms scales the *font* with the display and leaves explicit pixel
        // sizes exactly as written, so at 200% the text is twice the size inside a
        // window that is still 780 units wide: the second column's labels clip, the
        // spin boxes crowd the card edge and the last row falls off the bottom. It
        // looked right at 100% and at 150% and was only found by opening it on a
        // 192-DPI display.
        //
        // The DPI has to come from Windows, not from `DeviceDpi`. This assembly's
        // manifest declares per-monitor awareness, but .NET Framework's WinForms only
        // honours that with an app.config opt-in this product does not ship - so
        // `DeviceDpi` answers 96 on a 192-DPI screen, which is exactly the value that
        // makes the bug invisible to a fix written against it. Measured, twice: once
        // when the window came out a third of its intended width, and again when
        // scaling by DeviceDpi changed nothing at all.
        private static double MeasureDpiScale()
        {
            try
            {
                int dpi = GetDpiForSystem();
                if (dpi >= 96) return dpi / 96.0;
            }
            catch (Exception) { /* pre-1607 Windows: fall through */ }
            try
            {
                using (var graphics = Graphics.FromHwnd(IntPtr.Zero))
                    if (graphics.DpiX >= 96f) return graphics.DpiX / 96.0;
            }
            catch (Exception) { }
            return 1.0;
        }

        private int Px(int atNinetySix)
        {
            return (int)Math.Round(atNinetySix * DpiScale);
        }

        private Padding Pad(int left, int top, int right, int bottom)
        {
            return new Padding(Px(left), Px(top), Px(right), Px(bottom));
        }

        internal SettingsForm(PersistentBridge bridge) : this(bridge, null, null)
        {
        }

        /// `catalog` and `windowFont` stand in a strings reply and the window's font, for
        /// LayoutAudit; the window itself passes neither.
        private SettingsForm(PersistentBridge bridge, Dictionary<string, object> catalog, Font windowFont)
        {
            this.bridge = bridge;
            // What it was asked to open with. A window LayoutAudit builds is asked for nothing.
            request = catalog != null ? new OpenRequest() : ParseArguments(Environment.GetCommandLineArgs());
            // The theme it draws was adopted before this (Program.Main), from the same request.
            openedTheme = Palette.Theme;
            storedTheme = Theme.Opened;
            invisibleFrame = request.Frame;
            // Before anything is built: every label below asks the catalog for its text.
            //
            // From the cache when it was written for exactly this installation, this Interface
            // language and this Windows language (see StringsCache); otherwise asked for on a
            // worker, while the fonts and the icon are made. The window used to wait 260-400 ms for
            // the interpreter to start, and then spend 130-260 ms more on the first font.
            string root = AppDomain.CurrentDomain.BaseDirectory;
            installRoot = root;
            string cacheKey = null;
            System.Threading.Tasks.Task<Dictionary<string, object>> asking = null;
            if (catalog != null) AdoptStrings(catalog);
            else
            {
                cacheKey = StringsCache.Key(root);
                Dictionary<string, object> cached = StringsCache.Read(root, cacheKey);
                if (cached != null)
                {
                    AdoptStrings(cached);
                    // The interpreter every later read needs starts now, and if its answer differs
                    // from what was cached, the cache is what changes: this window keeps the words it
                    // opened with, as it does after a language is saved.
                    string key = cacheKey;
                    System.Threading.ThreadPool.QueueUserWorkItem(delegate { StringsCache.Refresh(root, key, cached, AskStrings()); });
                }
                else asking = System.Threading.Tasks.Task.Factory.StartNew<Dictionary<string, object>>(AskStrings);
            }
            Text = "Codex Auto Resume";
            Font = windowFont ?? SystemFonts.MessageBoxFont;
            // The type roles (Soft.RoleFont) are variants of the window's own font.
            Soft.BaseFont = Font;
            ForeColor = Ink;
            BackColor = Canvas;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Font;
            // The page the window opens on, the Overview, is whole at this size without scrolling, in
            // every language at every scaling and with the most it ever shows - tests/test_gui_layout.py
            // measures it - its cards a little taller than what they hold and the page's rhythm under
            // them; on a 1920 by 1080 screen at 150% KeepOnScreen makes it shorter, and it still fits.
            // A Settings section taller than the page scrolls. v0.6.3 grew the window to its tallest
            // section instead, which cost a second layout of everything before the first screen was
            // painted. See OpeningWidth.
            ClientSize = new Size(Px(OpeningWidth), Px(OpeningHeight));
            // Wide enough that the two columns always hold their content. Allowing a
            // narrower window buys nothing: the labels start truncating mid-word, which
            // looks broken rather than compact.
            MinimumSize = new Size(Px(800), Px(420));
            try
            {
                string icon = Path.Combine(root, "codex-auto-resume.ico");
                if (File.Exists(icon))
                {
                    Icon = new Icon(icon);
                    // With our own mark, and never in a window LayoutAudit builds: the taskbar button moves as the
                    // notification-area icon does while the window is open (TaskbarMark).
                    if (catalog == null) taskbar = new TaskbarMark(this);
                }
            }
            catch (Exception) { /* an icon is decoration; never fail the window over it */ }
            if (asking != null)
            {
                Dictionary<string, object> reply = asking.Result;
                AdoptStrings(reply);
                string key = cacheKey;
                // Kept only if it answers for the settings the key was taken of (StringsCache.Write).
                System.Threading.ThreadPool.QueueUserWorkItem(delegate { StringsCache.Write(root, key, reply); });
            }

            BuildFooter();
            BuildHeader();
            BuildColumns();
            BuildDashboard();
            KeepOnScreen();
            if (request.HasBounds)
            {
                // Reopened where the window it replaces was, on the screen that window was on: the frame one
                // sees where that one's was, with the invisible border that window measured around it.
                StartPosition = FormStartPosition.Manual;
                Bounds = PlaceOnScreen(request.Bounds, Screen.FromRectangle(request.Bounds).WorkingArea, MinimumSize, request.Frame);
            }
            if (request.Maximized) WindowState = FormWindowState.Maximized;
            // A dark title bar over a dark window.
            Soft.TitleBar(this);

            // The fill control is added first so the docked strips keep their edges:
            // docking is resolved from the last-added control inward, so whatever is
            // added first ends up with what is left. The page host holds whichever page
            // is showing; the settings columns are one of those pages.
            Controls.Add(pageHost);
            Controls.Add(footer);
            Controls.Add(nav);
            Controls.Add(header);
            // The keyboard follows the screen, not the order docking needs: without these the
            // Tab key went through the page, the footer and the page tabs before it reached
            // the header's Start button - the one control that matters when the watcher is off.
            header.TabIndex = 0;
            nav.TabIndex = 1;
            pageHost.TabIndex = 2;
            footer.TabIndex = 3;

            Load += delegate
            {
                if (auditing) return;
                Reload();
                ShowPage(firstPage);
                // A window that replaces another puts the keyboard where that one had it (FocusName).
                FocusInterim();
                StartClock();
            };
            Shown += delegate
            {
                shown = true;
                // Measured once it is on screen, for a reopen from this window maximized (Reopen).
                Padding measured = InvisibleFrame();
                if (measured != Padding.Empty) invisibleFrame = measured;
                BuildEditorsLater();
            };
            FormClosed += delegate { StopClock(); bridge.Stop(); };
        }

        /// The window within the screen it opens on. Its sizes are scaled, so on a small screen at
        /// a large scaling factor it can be asked to be larger than the display - and a window
        /// whose controls sit past the edge of the screen cannot be reached at all, where a
        /// scrolling one can. Settled here, before it is shown, so it never jumps once it is.
        private void KeepOnScreen()
        {
            Rectangle screen = Screen.FromControl(this).WorkingArea;
            int frameWidth = Width - ClientSize.Width, frameHeight = Height - ClientSize.Height;
            if (MinimumSize.Width > screen.Width || MinimumSize.Height > screen.Height)
                MinimumSize = new Size(Math.Min(MinimumSize.Width, screen.Width), Math.Min(MinimumSize.Height, screen.Height));
            ClientSize = new Size(Math.Max(Px(340), Math.Min(ClientSize.Width, screen.Width - frameWidth)),
                                  Math.Max(Px(340), Math.Min(ClientSize.Height, screen.Height - frameHeight)));
        }

        // ------------------------------------------------------------------- chrome
        private void BuildColumns()
        {
            // The Settings page: the section list on the left and one section's cards on the
            // right, scrolling on their own if a section is taller than the window.
            columns.Dock = DockStyle.Fill;
            // The editors are built before ShowPage first shows this page, and an unparented
            // control inherits Control.DefaultFont rather than the window's.
            columns.Font = Font;
            columns.ColumnCount = 2;
            columns.RowCount = 1;
            // Wide enough for "Automatische Wiederherstellung" and its peers at every scaling.
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(244)));
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            columns.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            columns.Padding = Pad(12, 0, 0, 0);

            var list = new SoftFlow();
            list.Dock = DockStyle.Fill;
            list.FlowDirection = FlowDirection.TopDown;
            list.WrapContents = false;
            list.Margin = Pad(0, 10, 2, 0);
            list.AccessibleRole = AccessibleRole.PageTabList;
            list.AccessibleName = S("nav.settings", "Settings");
            foreach (string name in SectionOrder)
            {
                var button = new NavButton();
                button.Vertical = true;
                button.Text = SectionTitle(name);
                button.Font = Soft.RoleFont("nav");
                button.AutoSize = false;
                button.Size = new Size(Px(230), Px(40));
                button.Margin = Pad(0, 0, 0, 2);
                string target = name;
                button.Click += delegate { ShowSection(target); };
                sectionButtons[name] = button;
                list.Controls.Add(button);

                var stack = new SoftStack();
                // Not docked, and as wide as the page less a scroll bar whether or not one is
                // showing (FitSections). Docked, a section took the page's width with the bar or
                // without it, and Continuation - the one section tall enough to scroll - was laid out
                // again at a new width every time it was shown.
                stack.Location = Point.Empty;
                stack.Anchor = AnchorStyles.Top | AnchorStyles.Left;
                stack.ColumnCount = 1;
                stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
                stack.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
                stack.AutoSize = true;
                stack.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                stack.Font = Font;
                // The cards' lift is kept inside the scrolling page, which is its edge (see Ground).
                // Each card already keeps a gap below it.
                Padding room = CardRoom();
                stack.Padding = new Padding(room.Left, room.Top, room.Right, Math.Max(0, room.Bottom - Px(Brand.PageGap)));
                // Every section stays on the page and only the one shown is visible (ShowSection).
                stack.Visible = false;
                sections[name] = stack;
                sectionScroll.Controls.Add(stack);
            }

            sectionScroll.Dock = DockStyle.Fill;
            // On the soft scroll bar (see SoftPage), which keeps the section's own cards' material.
            sectionScroll.Scrolls = true;
            sectionScroll.Margin = new Padding(0);
            sectionScroll.SizeChanged += delegate { FitSections(); };
            columns.Controls.Add(list, 0, 0);
            columns.Controls.Add(sectionScroll, 1, 0);
            FitSections();
        }

        /// Every section as wide as the page less the scroll bar's gutter, whether or not the bar is
        /// showing, so a section's width changes only when the window's does.
        ///
        /// Docked, a section took whatever width the page had, and the page had less of it whenever
        /// the section was tall enough to scroll. Continuation, which is, was resized twice and laid
        /// out again at each new width on every switch to it; holding the width took that switch
        /// from 290 to 225 ms (measured, 150%), and ShowSection the rest of the way. Before the page
        /// has been laid out its width is worked out from the window's, as the table will give it.
        private void FitSections()
        {
            int page = sectionScroll.Width > 0 ? sectionScroll.Width
                     : ClientSize.Width - columns.Padding.Horizontal - Px(244);
            int width = page - SoftBar.Gutter;
            if (width <= Px(160)) return;
            foreach (TableLayoutPanel stack in sections.Values)
            {
                if (stack.MinimumSize.Width == width && stack.MaximumSize.Width == width) continue;
                // In the order that never has the minimum above the maximum.
                if (width < stack.MinimumSize.Width)
                {
                    stack.MinimumSize = new Size(width, 0);
                    stack.MaximumSize = new Size(width, 0);
                }
                else
                {
                    stack.MaximumSize = new Size(width, 0);
                    stack.MinimumSize = new Size(width, 0);
                }
            }
        }

        /// The room a page keeps around its cards for their lift: as far as the panel's card shadow
        /// still changes the canvas by a colour level, at any scaling - 16 px up and to the left,
        /// where the light is, and 17 down and to the right (brand.shadow_alpha). A page that is
        /// scrolling is the edge of every shadow on it (see Ground), and at 14 px the cut was a
        /// line one could see along the top of the Continuation section.
        private Padding CardRoom()
        {
            return Pad(16, 16, 17, 17);
        }

        private string SectionTitle(string name)
        {
            switch (name)
            {
                case "general": return S("group.general", "General");
                case "recovery": return S("group.recovery", "Automatic recovery");
                case "continuation": return S("group.continuation", "Continuation message");
                case "appearance": return S("group.appearance", "Appearance");
                default: return S("group.advanced", "Advanced");
            }
        }

        private void ShowSection(string name)
        {
            if (!sections.ContainsKey(name)) name = "general";
            currentSection = name;
            // Painting stops while one section is hidden and the next shown, so the section is
            // painted once, finished (see Redraw).
            bool paused = Redraw(sectionScroll, false);
            try
            {
                // Every section stays on the page and only this one is visible. Taking a section
                // off the page and putting the next one on moved each of its native fields to
                // Windows' parking window and back: about 120 ms to take Continuation off and 160 ms
                // to put it back, at 150% (measured).
                sectionScroll.SuspendLayout();
                foreach (var pair in sections)
                    if (pair.Key != name) pair.Value.Visible = false;
                // Held while it becomes visible, and laid out once after. Each control in a section
                // that sizes itself asks the section to lay out again when it is shown: Continuation
                // was laid out thirteen times on the way to the screen, and a switch to it took
                // 225 ms; held, it is laid out once, and the switch takes 80 (measured, 150%).
                TableLayoutPanel section = sections[name];
                section.SuspendLayout();
                section.Visible = true;
                section.ResumeLayout(true);
                sectionScroll.ResumeLayout(false);
                sectionScroll.PerformLayout();
                sectionScroll.ScrollTo(0, false);
            }
            finally
            {
                if (paused) Redraw(sectionScroll, true);
            }
            foreach (var pair in sectionButtons)
            {
                pair.Value.Current = pair.Key == name;
                // Cached: a switch used to create a font for every item in the list.
                pair.Value.Font = Soft.RoleFont(pair.Key == name ? "nav_current" : "nav");
            }
        }

        private const int WM_SETREDRAW = 0x000B;
        private const int RDW_INVALIDATE = 0x0001;
        private const int RDW_ERASE = 0x0004;
        private const int RDW_ALLCHILDREN = 0x0080;
        private const int RDW_FRAME = 0x0400;

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool RedrawWindow(IntPtr window, IntPtr rectangle, IntPtr region, int flags);

        /// Stops painting `control` while what it shows is swapped, or starts it again and has
        /// the whole of it painted once. Returns whether it stopped it: a window that is not on
        /// screen is left alone, because turning painting back on also makes a window visible.
        ///
        /// A page switch otherwise painted every control it moved on the way, once for each move.
        private static bool Redraw(Control control, bool on)
        {
            if (!on && (!control.IsHandleCreated || !control.Visible)) return false;
            SendMessage(control.Handle, WM_SETREDRAW, on ? (IntPtr)1 : IntPtr.Zero, IntPtr.Zero);
            if (on) RedrawWindow(control.Handle, IntPtr.Zero, IntPtr.Zero, RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_FRAME);
            return true;
        }

        private void BuildHeader()
        {
            // What the watcher is doing belongs at the top, in the window's largest
            // type. It used to be a muted sentence in a strip along the bottom, under
            // sixteen checkboxes - which put the one thing a person opens this window to
            // check below everything they did not come for.
            //
            // A card on the canvas, as the panel's hero is. The card is the grid.
            header.Dock = DockStyle.Top;
            header.Padding = Pad(14, 12, 14, 2);
            hero.Dock = DockStyle.Fill;
            hero.Margin = new Padding(0);
            hero.Padding = Pad(Brand.HeroPadLeft, Brand.HeroPadTop, Brand.HeroPadRight, Brand.HeroPadBottom);
            hero.ColumnCount = 3;
            hero.RowCount = 2;
            // The state's light, and the gap to its words: as wide as PlaceLight makes it.
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(28)));
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what it is doing
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // the way out
            hero.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));
            hero.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));

            // Drawn rather than a glyph so the dot stays round and vertically centred at
            // any scaling, and it carries the same state as the words beside it. It stands
            // on the headline's line, in the first row, as the panel's and the popup's light
            // stands on its word's (v0.6.10); until then it spanned both rows and stood
            // between the two lines. Its glow is the one thing in the window that moves, and
            // only while there is something to show moving (see HaloDot); with motion reduced
            // it holds still.
            var dot = stateDot;
            dot.Dock = DockStyle.Fill;
            dot.BackColor = Card;
            dot.Margin = new Padding(0);

            // The words start where the light's column ends, both lines alike.
            headline.Dock = DockStyle.Fill;
            headline.TextAlign = ContentAlignment.BottomLeft;
            headline.ForeColor = Ink;
            headline.Font = Soft.RoleFont("display");
            headline.AutoEllipsis = true;
            headline.Margin = new Padding(0);
            headline.Text = "Loading...";

            detail.Dock = DockStyle.Fill;
            detail.TextAlign = ContentAlignment.TopLeft;
            detail.ForeColor = Secondary;
            detail.AutoEllipsis = true;   // narrow gracefully instead of wrapping
            detail.Margin = Pad(0, 2, 0, 0);

            // Shown only while the watcher is stopped. Nothing is recovered then, so a
            // window that reports the fact and offers no way out is a dead end - and the
            // watcher is the part nobody should have to think about. It sits beside the
            // sentence that explains why it is there rather than down among Save and
            // Close, which are about settings and not about the watcher.
            startButton = MakeButton(S("action.start", "Start watcher"), true, delegate { StartWatcher(); });
            startButton.Visible = false;
            // Pinned to the card's bottom right, beside the sentence under the headline (v0.6.4), as
            // every button at the right of a card is. Its column is its own, so neither line of the
            // headline ever runs under it.
            startButton.Anchor = AnchorStyles.Right | AnchorStyles.Bottom;
            startButton.Margin = Pad(16, 0, 0, 0);
            Pinned(startButton, hero);

            hero.Controls.Add(dot, 0, 0);
            hero.Controls.Add(headline, 1, 0);
            hero.Controls.Add(detail, 1, 1);
            hero.Controls.Add(startButton, 2, 0);
            hero.SetRowSpan(startButton, 2);
            header.Controls.Add(hero);
            // Measured, not a formula of the font: two lines of the taller of the two, each row
            // half the card, a line never less than the light's glow needs - the light stands in
            // the first - and the pair never less than the Start button needs. Again whenever the
            // window's font changes, and the light placed again with it.
            EventHandler fit = delegate
            {
                PlaceLight();
                int line = Math.Max(headline.PreferredSize.Height, detail.PreferredSize.Height + detail.Margin.Vertical);
                line = Math.Max(line, 2 * HaloDot.Extent + Px(2));
                int body = Math.Max(2 * line, startButton.PreferredSize.Height + startButton.Margin.Vertical);
                header.Height = body + hero.Padding.Vertical + header.Padding.Vertical;
            };
            fit(this, EventArgs.Empty);
            FontChanged += fit;
        }

        /// The header's light where every header stands it (v0.6.10): Brand.LightInset from the card's content to
        /// the dot, and Brand.LightGap from the dot to the first glyph of the headline. A label draws its glyphs a
        /// padding in from its edge (TextInset), so the light's column is that much narrower than the gap, and the
        /// line under the headline is moved in by the difference between the two fonts' paddings, so both lines'
        /// glyphs start at one x. The dot is centred in a box of its own, which keeps the glow's room on each side of
        /// it at any scaling - an absolute 22 once held a 24-pixel dot at 200% and sliced a third of it off - and the
        /// rest of the column is the box's right margin. Until v0.6.10 the column was 28, the headline's glyphs about
        /// 17 px from the dot, and the line under it started 3 px to its left.
        private void PlaceLight()
        {
            int box = 2 * (int)Math.Round(Soft.PxF(Brand.LightInset + Brand.StatusDotRadius));
            int headlineInset = TextInset(headline.Font), detailInset = TextInset(detail.Font);
            int column = Math.Max(box, (int)Math.Round(Soft.PxF(Brand.LightInset + 2 * Brand.StatusDotRadius + Brand.LightGap))
                                       - headlineInset);
            if (hero.ColumnStyles.Count > 0 && hero.ColumnStyles[0].Width != column) hero.ColumnStyles[0].Width = column;
            var beside = new Padding(0, 0, column - box, 0);
            if (stateDot.Margin != beside) stateDot.Margin = beside;
            var under = new Padding(Math.Max(0, headlineInset - detailInset), detail.Margin.Top, 0, detail.Margin.Bottom);
            if (detail.Margin != under) detail.Margin = under;
        }

        /// How far in from its left edge a label draws its first glyph: the padding TextRenderer keeps on each side
        /// of a line for glyphs that overhang it (GlyphOverhangPadding), a sixth of the font's height rounded up,
        /// which Label's drawing asks for and MeasureText does not count. Measured: a label draws a W 4 px in at a
        /// 21-pixel font and 6 px in at a 31-pixel one.
        internal static int TextInset(Font font)
        {
            return (int)Math.Ceiling(font.Height / 6.0);
        }

        private void BuildFooter()
        {
            // The save bar: a card on the canvas at the foot of the window, as the panel's is. The
            // card is the grid.
            footer.Dock = DockStyle.Bottom;
            footer.Padding = Pad(14, 10, 14, 12);
            savebar.Dock = DockStyle.Fill;
            savebar.Margin = new Padding(0);
            savebar.Padding = Pad(Brand.SavebarPadLeft + 6, Brand.SavebarPadTop, Brand.SavebarPadRight, Brand.SavebarPadBottom);
            savebar.ColumnCount = 3;
            savebar.RowCount = 1;
            savebar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // version
            savebar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what happens once edits are saved
            savebar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // buttons
            // A Dock=Fill child of an implicit AutoSize row measures to nothing, and the
            // strip then renders empty. Say what the row is.
            savebar.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

            // In its own column, as wide as it is, so narrowing the window shortens nothing
            // that matters and never takes away the one field people are asked for in a bug
            // report.
            versionText.AutoSize = true;
            versionText.Anchor = AnchorStyles.Left;
            versionText.TextAlign = ContentAlignment.MiddleLeft;
            // Secondary text, which it is. The idle fill it was drawn in is a colour for a status light, 2.41:1
            // on the card in light and 3.10:1 in dark: too faint for the one field people are asked to read out.
            versionText.ForeColor = Secondary;

            // Said only while a language or theme changed and there are edits to keep: the window
            // reopens in the new one once they are saved or discarded (see CheckReopen). The card grows to
            // hold all of it beside the buttons (fit, below) - five lines of French at the window's narrowest -
            // and only past NoteLines does it end in an ellipsis; a screen reader has it whole.
            reopenNote = new NoteLabel();
            reopenNote.AutoSize = false;
            reopenNote.Dock = DockStyle.Fill;
            reopenNote.TextAlign = ContentAlignment.MiddleLeft;
            reopenNote.AutoEllipsis = true;
            reopenNote.UseMnemonic = false;
            reopenNote.ForeColor = Secondary;
            reopenNote.LiveSetting = AutomationLiveSetting.Polite;
            reopenNote.Margin = Pad(16, 0, 8, 0);
            reopenNote.Visible = false;

            var row = new SoftFlow();
            row.BackColor = Card;
            // At the right of its cell and in the middle of it, beside a note taller than the buttons.
            row.Anchor = AnchorStyles.Right;
            row.FlowDirection = FlowDirection.RightToLeft;
            row.WrapContents = false;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            // Explicit, because the default is 3px on every side and does not scale. Those
            // six pixels were the whole bug: the strip's height was computed from a text
            // measurement plus a constant, the row needed six more than the arithmetic
            // allowed for, and every button lost the last two rows of its own border.
            row.Margin = new Padding(0);
            closeButton = MakeButton(S("action.close", "Close"), false, delegate { Close(); });
            row.Controls.Add(closeButton);
            // Only the Settings page has anything to save.
            saveButton = MakeButton(S("action.save", "Save"), true, delegate { Save(); });
            restoreButton = MakeButton(S("action.restore", "Restore defaults"), false, delegate { RestoreDefaults(); });
            row.Controls.Add(saveButton);
            row.Controls.Add(restoreButton);

            versionText.Margin = new Padding(0);
            savebar.Controls.Add(versionText, 0, 0);
            savebar.Controls.Add(reopenNote, 1, 0);
            savebar.Controls.Add(row, 2, 0);
            footer.Controls.Add(savebar);
            // Measured, not derived. A strip sized by a formula cannot know how tall an
            // AutoSize button becomes once the font is applied, and being two pixels short
            // looks exactly like a drawing bug. Again whenever the window's font changes, the
            // reopen note is shown or hidden, and - while it shows - the room beside it changes.
            bool fitting = false;
            EventHandler fit = delegate
            {
                // Laying the card out again below raises what calls this, so the height is worked out once.
                if (fitting) return;
                fitting = true;
                try
                {
                    int content = Math.Max(savebar.PreferredSize.Height, row.PreferredSize.Height + savebar.Padding.Vertical);
                    if (reopenNoteShown) content = Math.Max(content, NoteHeight(row) + savebar.Padding.Vertical);
                    int height = content + footer.Padding.Vertical;
                    if (footer.Height != height) footer.Height = height;
                    // A height given to the strip while the window is being laid out reaches the strip and not
                    // the card in it: the layout that is running has already placed the card, and the layout the
                    // new height asks for is dropped when that one ends (Control.PerformLayout). The card would
                    // then keep the height it was given before the note was shown - which is what left it two
                    // lines short of the note on the CI runner (v0.6.4, measured). So the card is held to the
                    // strip here, and the window laid out around a strip whose height changed; both are asked
                    // for again from the window's own Resize, which is raised after that layout is over.
                    if (savebar.Height != footer.ClientSize.Height - footer.Padding.Vertical)
                    {
                        PerformLayout();
                        footer.PerformLayout();
                    }
                }
                finally { fitting = false; }
            };
            fit(this, EventArgs.Empty);
            FontChanged += fit;
            fitFooter = fit;
            EventHandler follow = delegate { if (reopenNoteShown) fit(this, EventArgs.Empty); };
            savebar.SizeChanged += follow;
            row.SizeChanged += follow;
            versionText.SizeChanged += follow;
            // The window's own size last of all: its Resize is raised once it has been laid out, which is the
            // one place a card left short by a layout that was already running can be given its height.
            Resize += follow;
        }

    }

    internal static class Program
    {
        [DllImport("shell32.dll", PreserveSig = false)]
        private static extern void SetCurrentProcessExplicitAppUserModelID([MarshalAs(UnmanagedType.LPWStr)] string id);

        /// The identity Windows files this window's taskbar button under, and why it is the window's own.
        ///
        /// v0.6.5 moved the mark on the taskbar button by setting the window's big icon frame by frame, and it
        /// was captured doing so - from a build in a scratch folder. Installed, it never moved. Measured on this
        /// machine: the same executable, byte for byte, moved the button from a scratch folder and did not move
        /// it from the installed one, where an instrumented build showed the window setting frame after frame
        /// into a button that stayed pixel-identical for twenty-four seconds. What decides it is the location:
        /// Windows files an installed window under the application registered there and paints its button from
        /// that application's icon, which no window can change. (A Start Menu shortcut alone does not do it: one
        /// written for a scratch folder, with the same identity and icon, left the button moving.)
        ///
        /// So the window claims an identity of its own, which no shortcut registers, and Windows falls back to
        /// the icon the window itself carries. The notification identity is untouched: toasts are raised by the
        /// watcher process under the watcher's AUMID, and this call changes only this process. Called before any
        /// window exists, which is the only time Windows accepts it.
        internal static void TakeOwnTaskbarIdentity()
        {
            try { SetCurrentProcessExplicitAppUserModelID("CodexAutoResume.Settings"); }
            catch (Exception) { }           // an older shell, or a shell that refuses: the button simply stays still
        }

        [STAThread]
        internal static int Main(string[] argv)
        {
            // The accessibility improvements .NET 4.8 ships but leaves off for an assembly
            // with no target-framework attribute, which is what the in-box compiler builds.
            // Without them a live region never reaches a screen reader.
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures", false);
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures.2", false);
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures.3", false);
            TakeOwnTaskbarIdentity();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            var bridge = new Bridge(root);
            if (!bridge.Available)
            {
                // The one message box left, and deliberately Windows' own: there is no window yet, no
                // theme has been read and no catalog has been loaded, so the window's dialog would
                // have neither its material nor its language. This says, in English, that there is
                // nothing here to run, and nothing here can say it any better.
                MessageBox.Show("Codex Auto Resume is not installed in this location." +
                                Environment.NewLine + Environment.NewLine + root,
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            // The theme, decided before the first control is made: the one a reopening window passed on,
            // or the one stored, as Windows and High Contrast have it now (Theme). Every colour below
            // comes from it.
            OpenRequest request = SettingsForm.ParseArguments(argv);
            Theme.Opened = request.Theme ?? Theme.Stored(root);
            Palette.Adopt(Theme.Current(Theme.Opened));
            Application.Run(new SettingsForm(new PersistentBridge(root, bridge)));
            return 0;
        }
    }
}

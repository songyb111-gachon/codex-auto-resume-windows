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
//     src/codex_auto_resume/brand.py. Do not write a literal colour in this file.
//
// Built with the in-box C# compiler against .NET Framework 4.8, which ships on every
// supported Windows, so the release carries no extra runtime for the interface.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal static class Json
    {
        // A minimal reader for the control bridge's own output. Not a general parser:
        // it accepts exactly the shapes we emit, and anything else raises.
        // The bridge's deepest real output is four levels. A limit well above that turns
        // pathological input into a FormatException, which every caller catches, instead of
        // a StackOverflowException, which .NET cannot catch and which ends the process -
        // measured at about 6,000 levels with no limit.
        private const int MaxDepth = 64;

        internal static object Parse(string text)
        {
            int index = 0;
            int depth = 0;
            try
            {
                return ParseValue(text, ref index, ref depth);
            }
            catch (IndexOutOfRangeException)
            {
                // Truncated input ran off the end of the string: say so as a format error.
                throw new FormatException("unexpected end of JSON");
            }
            catch (ArgumentOutOfRangeException)
            {
                throw new FormatException("unexpected end of JSON");
            }
        }

        private static void SkipWhitespace(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
        }

        private static object ParseValue(string s, ref int i, ref int depth)
        {
            SkipWhitespace(s, ref i);
            if (i >= s.Length) throw new FormatException("unexpected end of JSON");
            char c = s[i];
            if (c == '{' || c == '[')
            {
                if (++depth > MaxDepth) throw new FormatException("JSON nested too deeply");
                object nested = c == '{' ? (object)ParseObject(s, ref i, ref depth)
                                         : (object)ParseArray(s, ref i, ref depth);
                depth--;
                return nested;
            }
            if (c == '"') return ParseString(s, ref i);
            if (s.Length - i >= 4 && s.Substring(i, 4) == "true") { i += 4; return true; }
            if (s.Length - i >= 5 && s.Substring(i, 5) == "false") { i += 5; return false; }
            if (s.Length - i >= 4 && s.Substring(i, 4) == "null") { i += 4; return null; }
            return ParseNumber(s, ref i);
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i, ref int depth)
        {
            var result = new Dictionary<string, object>();
            i++;
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return result; }
            while (true)
            {
                SkipWhitespace(s, ref i);
                string key = ParseString(s, ref i);
                SkipWhitespace(s, ref i);
                if (s[i] != ':') throw new FormatException("expected :");
                i++;
                result[key] = ParseValue(s, ref i, ref depth);
                SkipWhitespace(s, ref i);
                if (s[i] == ',') { i++; continue; }
                if (s[i] == '}') { i++; return result; }
                throw new FormatException("expected , or }");
            }
        }

        private static List<object> ParseArray(string s, ref int i, ref int depth)
        {
            var result = new List<object>();
            i++;
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return result; }
            while (true)
            {
                result.Add(ParseValue(s, ref i, ref depth));
                SkipWhitespace(s, ref i);
                if (s[i] == ',') { i++; continue; }
                if (s[i] == ']') { i++; return result; }
                throw new FormatException("expected , or ]");
            }
        }

        private static string ParseString(string s, ref int i)
        {
            if (s[i] != '"') throw new FormatException("expected string");
            i++;
            var builder = new StringBuilder();
            while (s[i] != '"')
            {
                if (s[i] == '\\')
                {
                    i++;
                    char e = s[i];
                    if (e == 'n') builder.Append('\n');
                    else if (e == 't') builder.Append('\t');
                    else if (e == 'r') builder.Append('\r');
                    else if (e == 'b') builder.Append('\b');
                    else if (e == 'f') builder.Append('\f');
                    else if (e == 'u')
                    {
                        builder.Append((char)Convert.ToInt32(s.Substring(i + 1, 4), 16));
                        i += 4;
                    }
                    else builder.Append(e);
                }
                else builder.Append(s[i]);
                i++;
            }
            i++;
            return builder.ToString();
        }

        private static object ParseNumber(string s, ref int i)
        {
            int start = i;
            while (i < s.Length && (char.IsDigit(s[i]) || s[i] == '-' || s[i] == '+' ||
                                    s[i] == '.' || s[i] == 'e' || s[i] == 'E')) i++;
            return double.Parse(s.Substring(start, i - start), CultureInfo.InvariantCulture);
        }

        internal static string Escape(string value)
        {
            var builder = new StringBuilder("\"");
            foreach (char c in value ?? string.Empty)
            {
                if (c == '"' || c == '\\') builder.Append('\\').Append(c);
                else if (c < 32) builder.Append("\\u").Append(((int)c).ToString("x4"));
                else builder.Append(c);
            }
            return builder.Append('"').ToString();
        }

        /// The shapes Parse returns, written back as JSON: for the window's own strings cache,
        /// which keeps a bridge reply as it was parsed.
        internal static string Write(object value)
        {
            var builder = new StringBuilder();
            WriteValue(builder, value, 0);
            return builder.ToString();
        }

        private static void WriteValue(StringBuilder builder, object value, int depth)
        {
            if (depth > MaxDepth) throw new FormatException("JSON nested too deeply");
            var map = value as Dictionary<string, object>;
            var list = value as List<object>;
            if (value == null) builder.Append("null");
            else if (value is bool) builder.Append((bool)value ? "true" : "false");
            else if (value is string) builder.Append(Escape((string)value));
            else if (value is double) builder.Append(((double)value).ToString("R", CultureInfo.InvariantCulture));
            else if (map != null)
            {
                builder.Append('{');
                bool first = true;
                foreach (KeyValuePair<string, object> pair in map)
                {
                    if (!first) builder.Append(',');
                    first = false;
                    builder.Append(Escape(pair.Key)).Append(':');
                    WriteValue(builder, pair.Value, depth + 1);
                }
                builder.Append('}');
            }
            else if (list != null)
            {
                builder.Append('[');
                for (int i = 0; i < list.Count; i++)
                {
                    if (i > 0) builder.Append(',');
                    WriteValue(builder, list[i], depth + 1);
                }
                builder.Append(']');
            }
            else throw new FormatException("not a JSON value");
        }
    }

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
        // cannot disagree about what colour this product is.
        //
        // Except in High Contrast mode, where the person has chosen their colours for a
        // reason and a brand palette would override it: then every colour is a system one.
        private static readonly bool Contrast = SystemInformation.HighContrast;
        private static readonly Color Ink     = Contrast ? SystemColors.WindowText : Brand.Ink;
        private static readonly Color Muted   = Contrast ? SystemColors.GrayText : Brand.Muted;
        // Secondary text that is still live. In High Contrast mode GrayText means
        // "disabled", so there it is the ordinary text colour, and weight and position
        // carry the hierarchy instead. Muted stays for what really is disabled.
        private static readonly Color Secondary = Contrast ? SystemColors.WindowText : Brand.Muted;
        private static readonly Color Line    = Contrast ? SystemColors.WindowFrame : Brand.Line;
        private static readonly Color Surface = Contrast ? SystemColors.Window : Brand.Surface;
        private static readonly Color Canvas  = Contrast ? SystemColors.Control : Brand.Canvas;
        private static readonly Color Accent  = Contrast ? SystemColors.Highlight : Brand.Accent;
        private static readonly Color OnAccent = Contrast ? SystemColors.HighlightText : Brand.OnAccent;
        private static readonly Color Active  = Contrast ? SystemColors.Highlight : Brand.Active;
        private static readonly Color Idle    = Contrast ? SystemColors.GrayText : Brand.Idle;

        private readonly PersistentBridge bridge;
        private readonly Dictionary<string, Control> editors = new Dictionary<string, Control>();

        private readonly TableLayoutPanel columns = new SoftStack();
        // The Settings page's sections, in the order the section list shows them. Each is a
        // single column of cards; one is on screen at a time.
        private static readonly string[] SectionOrder = { "general", "recovery", "continuation", "appearance", "advanced" };
        private readonly Dictionary<string, TableLayoutPanel> sections = new Dictionary<string, TableLayoutPanel>();
        private readonly Dictionary<string, NavButton> sectionButtons = new Dictionary<string, NavButton>();
        private readonly Panel sectionScroll = new SoftPage();
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
        private Button startButton;

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
            // Before anything is built: every label below asks the catalog for its text.
            //
            // From the cache when it was written for exactly this installation, this Interface
            // language and this Windows language (see StringsCache); otherwise asked for on a
            // worker, while the fonts and the icon are made. The window used to wait 260-400 ms for
            // the interpreter to start, and then spend 130-260 ms more on the first font.
            string root = AppDomain.CurrentDomain.BaseDirectory;
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
            // The proportions of v0.6.2. Every page is laid out to fit this at every scaling and in
            // every language - tests/test_gui_layout.py measures it - and a Settings section taller
            // than the page scrolls. v0.6.3 grew the window to its tallest section instead, which
            // cost a second layout of everything before the first screen was painted.
            ClientSize = new Size(Px(860), Px(600));
            // Wide enough that the two columns always hold their content. Allowing a
            // narrower window buys nothing: the labels start truncating mid-word, which
            // looks broken rather than compact.
            MinimumSize = new Size(Px(800), Px(420));
            try
            {
                string icon = Path.Combine(root, "codex-auto-resume.ico");
                if (File.Exists(icon)) Icon = new Icon(icon);
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
                StartClock();
            };
            Shown += delegate { shown = true; BuildEditorsLater(); };
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
            sectionScroll.AutoScroll = true;
            sectionScroll.Margin = new Padding(0);
            sectionScroll.SizeChanged += delegate { FitSections(); };
            columns.Controls.Add(list, 0, 0);
            columns.Controls.Add(sectionScroll, 1, 0);
            FitSections();
        }

        /// Every section as wide as the page less a vertical scroll bar, whether or not one is
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
            int width = page - SystemInformation.VerticalScrollBarWidth;
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
                sectionScroll.AutoScrollPosition = new Point(0, 0);
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
            // Wide enough for the dot and its glow at any scaling: an absolute 22 held a 24-pixel
            // dot at 200% and sliced a third of it off.
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(28)));   // state dot and its glow
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what it is doing
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // the way out
            hero.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));
            hero.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));

            // Drawn rather than a glyph so the dot stays round and vertically centred at
            // any scaling, and it carries the same state as the words beside it. It
            // spans both rows because it describes the pair, not the first line. Its glow is
            // the one thing in the window that moves, and only while there is something to
            // show moving (see HaloDot); with motion reduced it holds still.
            var dot = stateDot;
            dot.Dock = DockStyle.Fill;
            dot.BackColor = Surface;
            dot.Margin = new Padding(0);

            headline.Dock = DockStyle.Fill;
            headline.TextAlign = ContentAlignment.BottomLeft;
            headline.ForeColor = Ink;
            headline.Font = Soft.RoleFont("display");
            headline.AutoEllipsis = true;
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
            startButton.Anchor = AnchorStyles.Right;
            startButton.Margin = Pad(16, 0, 0, 0);

            hero.Controls.Add(dot, 0, 0);
            hero.SetRowSpan(dot, 2);
            hero.Controls.Add(headline, 1, 0);
            hero.Controls.Add(detail, 1, 1);
            hero.Controls.Add(startButton, 2, 0);
            hero.SetRowSpan(startButton, 2);
            header.Controls.Add(hero);
            // Measured, not a formula of the font: two lines of the taller of the two, each row
            // half the card so the pair stays centred on the dot, and never less than the dot's
            // glow or the Start button need. Again whenever the window's font changes.
            EventHandler fit = delegate
            {
                int line = Math.Max(headline.PreferredSize.Height, detail.PreferredSize.Height + detail.Margin.Vertical);
                int body = Math.Max(2 * line, Math.Max(2 * HaloDot.Extent + Px(2),
                                                      startButton.PreferredSize.Height + startButton.Margin.Vertical));
                header.Height = body + hero.Padding.Vertical + header.Padding.Vertical;
            };
            fit(this, EventArgs.Empty);
            FontChanged += fit;
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
            savebar.ColumnCount = 2;
            savebar.RowCount = 1;
            savebar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // version
            savebar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // buttons
            // A Dock=Fill child of an implicit AutoSize row measures to nothing, and the
            // strip then renders empty. Say what the row is.
            savebar.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

            // In its own column, so narrowing the window shortens nothing that matters
            // and never takes away the one field people are asked for in a bug report.
            versionText.Dock = DockStyle.Fill;
            versionText.TextAlign = ContentAlignment.MiddleLeft;
            versionText.ForeColor = Idle;
            versionText.AutoEllipsis = true;

            var row = new SoftFlow();
            row.BackColor = Surface;
            row.Dock = DockStyle.Fill;
            row.FlowDirection = FlowDirection.RightToLeft;
            row.WrapContents = false;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            // Explicit, because the default is 3px on every side and does not scale. Those
            // six pixels were the whole bug: the strip's height was computed from a text
            // measurement plus a constant, the row needed six more than the arithmetic
            // allowed for, and every button lost the last two rows of its own border.
            row.Margin = new Padding(0);
            row.Controls.Add(MakeButton(S("action.close", "Close"), false, delegate { Close(); }));
            // Only the Settings page has anything to save.
            saveButton = MakeButton(S("action.save", "Save"), true, delegate { Save(); });
            restoreButton = MakeButton(S("action.restore", "Restore defaults"), false, delegate { RestoreDefaults(); });
            row.Controls.Add(saveButton);
            row.Controls.Add(restoreButton);

            versionText.Margin = new Padding(0);
            savebar.Controls.Add(versionText, 0, 0);
            savebar.Controls.Add(row, 1, 0);
            footer.Controls.Add(savebar);
            // Measured, not derived. A strip sized by a formula cannot know how tall an
            // AutoSize button becomes once the font is applied, and being two pixels short
            // looks exactly like a drawing bug. Again whenever the window's font changes.
            EventHandler fit = delegate
            {
                footer.Height = Math.Max(savebar.PreferredSize.Height, row.PreferredSize.Height + savebar.Padding.Vertical)
                              + footer.Padding.Vertical;
            };
            fit(this, EventArgs.Empty);
            FontChanged += fit;
        }

        private Button MakeButton(string text, bool primary, EventHandler onClick)
        {
            // Raised on its card, or filled with the accent when it is the page's one primary
            // action. A disabled button of either kind looks like every other that cannot be
            // pressed (see SoftButton), so the accent never marks a dead control.
            var button = new SoftButton(primary);
            button.Text = text;
            button.AutoSize = true;
            button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            // The panel's button height. Its body is the whole control now, where the old one kept
            // three pixels of a 38-pixel control on every side for its own shadow.
            button.MinimumSize = new Size(Px(112), Px(Brand.ButtonHeight));
            button.Padding = Pad(Brand.ButtonPadLeft, 0, Brand.ButtonPadRight, 0);
            button.Margin = Pad(9, 0, 0, 0);
            button.Click += onClick;
            return button;
        }

        private const int EM_SETMARGINS = 0x00D3;
        private const int EC_LEFTMARGIN = 0x0001;

        // Logical pixels at 96 DPI, picked by looking at 0, 3, 4, 5, 6 and 8 side by side
        // and then measuring the finished window: the edit already inches its text off the
        // border by about a pixel, so four here puts the digit a little over five logical
        // pixels in - between the ComboBox below it, which is tighter, and the point where
        // the number starts to look indented rather than placed.
        private const int INSET = 4;

        [System.Runtime.InteropServices.DllImport("user32.dll", CharSet =
            System.Runtime.InteropServices.CharSet.Auto)]
        private static extern IntPtr SendMessage(IntPtr handle, int message,
                                                 IntPtr wParam, IntPtr lParam);

        private void GiveTextRoom(NumericUpDown spin)
        {
            // A few pixels between the box's left edge and its digit.
            //
            // A NumericUpDown draws its number hard against the border, which reads as a
            // value that has been pushed up against the frame rather than placed in it -
            // and it is the one control here that looks unlike the rest of the window.
            // WinForms exposes no inner padding for it, so the margin goes to the native
            // Edit underneath, through the message the Edit control has always had for
            // exactly this. The alternative - padding the text with spaces - would change
            // the value the control parses and round-trips, which is not a cosmetic change
            // at all.
            //
            // The box does not grow: the margin comes out of the text area inside the
            // border it already has. Alignment, selection, typing and the spinner are
            // untouched, and the inset scales with the display like every other size here.
            foreach (Control child in spin.Controls)
            {
                var edit = child as TextBox;
                if (edit == null) continue;
                // The edit's own handle, not the spinner's: the spinner has one before
                // its child does, and a message sent then goes nowhere quietly. Hooked
                // rather than sent once, because a margin lives on the handle and a
                // handle can be recreated underneath it.
                EventHandler apply = delegate
                {
                    SendMessage(edit.Handle, EM_SETMARGINS, (IntPtr)EC_LEFTMARGIN,
                                (IntPtr)Px(INSET));
                    edit.Invalidate();
                };
                edit.HandleCreated += apply;
                if (edit.IsHandleCreated) apply(edit, EventArgs.Empty);
            }
        }

        private static void IgnoreWheel(Control control)
        {
            // Scrolling the page with the pointer over a spin box or a drop-down would
            // otherwise change the setting under the cursor - silently, and usually all
            // the way to a limit. The wheel belongs to the page, not to the editor.
            control.MouseWheel += delegate(object sender, MouseEventArgs e)
            {
                var handled = e as HandledMouseEventArgs;
                if (handled != null) handled.Handled = true;
            };
        }

        // -------------------------------------------------------------------- cards
        private TableLayoutPanel NewGroup(string title, TableLayoutPanel stack)
        {
            TableLayoutPanel card = MakeCard(title);
            stack.Controls.Add(card);
            stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            return card;
        }

        private TableLayoutPanel MakeCard(string title)
        {
            // The card IS the layout panel rather than a Panel wrapping one. A Panel
            // measures AutoSize from anchored children only, so a docked AutoSize child
            // reports nothing: the panel keeps its default height and the last row of
            // every group is sliced off, bottom border and all.
            //
            // Its body is the whole control; the ground it stands on draws its lift (see
            // SoftCard). The panel's card padding, and the panel's gap below it.
            var card = new SoftCard();
            card.Dock = DockStyle.Fill;
            card.ColumnCount = 1;
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            card.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            card.AutoSize = true;
            card.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            card.Margin = Pad(0, 0, 0, Brand.PageGap);
            card.Padding = Pad(Brand.CardPadLeft, Brand.CardPadTop, Brand.CardPadRight, Brand.CardPadBottom);

            var heading = new Label();
            heading.Text = title;
            heading.AutoSize = true;
            heading.ForeColor = Ink;
            // The card heading's size as it has always been; the weight is the panel's.
            heading.Font = Soft.RoleFont("title");
            heading.Margin = Pad(0, 0, 0, 10);
            card.Controls.Add(heading);
            return card;
        }

        private CheckBox NewCheck(string text, bool value)
        {
            var check = new SoftCheck();
            check.Text = text;
            check.AutoSize = true;
            check.Margin = Pad(0, 3, 0, 3);
            check.Checked = value;
            return check;
        }

        private Label HelpText(string text)
        {
            var label = new Label();
            label.AutoSize = true;
            label.MaximumSize = new Size(Px(600), 0);
            // Stretched across its card, so it wraps at the card's width: the window is narrower
            // than the line length the maximum allows for.
            label.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;
            label.Text = text;
            label.ForeColor = Secondary;
            label.Margin = Pad(0, 2, 0, 8);
            return label;
        }

        private Label Caption(string text)
        {
            var label = new Label();
            label.AutoSize = true;
            label.Text = text;
            label.ForeColor = Ink;
            label.Font = Soft.RoleFont("heading");
            label.Margin = Pad(0, 10, 0, 4);
            return label;
        }

        private Control NewRow(string text, Control editor)
        {
            var row = new TableLayoutPanel();
            row.ColumnCount = 2;
            row.RowCount = 1;
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.Dock = DockStyle.Fill;
            row.Margin = Pad(0, 6, 0, 6);
            // Opaque, in the card's own colour. See-through, every repaint of the row and of its
            // label asked the card behind it to paint its background again, shadow and all - 540
            // card backgrounds, 11 seconds, in one measured session of v0.6.3.
            row.BackColor = Surface;

            var label = new Label();
            label.Text = text;
            label.AutoSize = true;
            label.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            label.TextAlign = ContentAlignment.MiddleLeft;
            label.AutoEllipsis = true;
            // The label's margins are what reserve the editor's height.
            //
            // TableLayoutPanel measures this row from the label's cell: the editor below is
            // anchored to the top of its cell and does not size the row. So the row is as tall as
            // the label plus its margins and nothing else, and if that is less than the editor
            // really is, the editor's bottom edge is cut away - a child window is clipped to its
            // parent.
            //
            // Both heights change after this method returns, so the margins are worked out again
            // whenever the editor's height or either font changes. Here, before the row has a
            // parent, everything is measured in Control.DefaultFont (Gulim 9pt on a Korean
            // Windows), not the window's font. The window's font arrives when the row joins its
            // card, and a drop-down then takes its real height. v0.6.3 measured once, here: its
            // drop-downs grew past a row sized in the default font, and their bottom edges were
            // cut off by 5 to 10 pixels at every scaling and in every language. The editor's real
            // Height is read as well as its PreferredSize, which for a native drop-down answered
            // 33 for a 42-pixel field.
            //
            // The row ends up the editor's height plus a little, and the leftover is split above
            // and below the label, so its text sits on the editor's centre line.
            Action fit = delegate
            {
                int editorHeight = Math.Max(editor.Height, editor.PreferredSize.Height) + Px(2);
                int labelHeight = label.PreferredSize.Height;
                int lift = Math.Max(0, (editorHeight - labelHeight) / 2);
                var wanted = new Padding(0, lift, Px(12), Math.Max(0, editorHeight - labelHeight - lift));
                // Set only when it changes: the setter lays out the row and its card again.
                if (label.Margin != wanted) label.Margin = wanted;
            };
            fit();
            editor.SizeChanged += delegate { fit(); };
            editor.FontChanged += delegate { fit(); };
            label.FontChanged += delegate { fit(); };

            // Top, not just Right. A Right-only anchor centres the editor vertically in a row
            // that was measured before the editor had its real height, and the editor then hangs
            // below the row's bottom edge. Pinned to the top it starts where the row does, and
            // the margins above keep the row taller than it. A margin on the editor itself does
            // not help: the row is measured from the label's cell, so it would only push the
            // editor further down inside a row that did not grow.
            editor.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            editor.Margin = new Padding(0);
            row.Controls.Add(label, 0, 0);
            row.Controls.Add(editor, 1, 0);
            return row;
        }

        private string Humanise(string name)
        {
            // The catalog is keyed by the setting's own schema name, so adding a setting
            // needs one line in interface.py and nothing here. The English fallback below
            // is what this whole method used to be: a second copy of the vocabulary, in a
            // second language, which is exactly what stopped the window being translated.
            string known = S("field." + name, null);
            if (known != null) return known;
            string text = name;
            if (text.StartsWith("recover_")) text = text.Substring(8);
            else if (text.StartsWith("notify_")) text = text.Substring(7);
            text = text.Replace('_', ' ');
            return char.ToUpper(text[0]) + text.Substring(1);
        }

        // ------------------------------------------------------------------ loading
        private void Reload()
        {
            // Both reads on a worker, one after the other. The Dashboard's clock takes the
            // bridge lock from a pool thread every five seconds, so reading the schema on
            // this thread stops the window repainting until that read has finished too.
            CallAsync("describe", null, delegate(Dictionary<string, object> described)
            {
                if (!Ok(described)) { ReloadFailed(described); return; }
                CallAsync("settings", null, delegate(Dictionary<string, object> settings)
                {
                    if (!Ok(settings)) { ReloadFailed(settings); return; }
                    var schema = described["schema"] as List<object>;
                    var current = settings["settings"] as Dictionary<string, object>;
                    if (schema == null || current == null) { ReloadFailed(null); return; }
                    AdoptSettings(current);
                    pendingSchema = schema;
                    pendingSettings = current;
                    if (currentPage == "settings") BuildPendingEditors();
                    else BuildEditorsLater();
                });
            });
        }

        private void ReloadFailed(Dictionary<string, object> reply)
        {
            headline.Text = S("settings.load_failed", "Could not read the local settings");
            detail.Text = Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture);
            header.Invalidate(true);
        }

        /// What the window takes from the settings before any editor exists: whether motion is
        /// reduced, and the Interface language as it is stored.
        private void AdoptSettings(Dictionary<string, object> current)
        {
            Soft.ReduceMotionSetting = Equals(Get(current, "reduce_motion"), true);
            stateDot.Sync();
            loadedInterfaceLanguage = Str(current, "interface_language") ?? "system";
        }

        /// Builds the Settings editors once the first screen is up, when the window did not open on
        /// Settings. They took 0.7-1.2 s of the window's own thread before its first paint, for a
        /// page nobody had asked to see yet; now the header and the first page are painted first,
        /// and the editors are built the next time nothing else is waiting. Switching to Settings
        /// before then builds them at once (ShowPage).
        private void BuildEditorsLater()
        {
            if (pendingSchema == null || !shown || buildQueued || auditing) return;
            buildQueued = true;
            EventHandler idle = null;
            idle = delegate
            {
                Application.Idle -= idle;
                buildQueued = false;
                if (!IsDisposed) BuildPendingEditors();
            };
            Application.Idle += idle;
        }

        private void BuildPendingEditors()
        {
            if (pendingSchema == null) return;
            BuildEditors(pendingSchema, pendingSettings);
        }

        private void BuildEditors(List<object> schema, Dictionary<string, object> current)
        {
            // Whatever was waiting to be built is this, or older than this.
            pendingSchema = null;
            pendingSettings = null;
            if (schema == null || current == null) { ReloadFailed(null); return; }
            columns.SuspendLayout();
            foreach (TableLayoutPanel stack in sections.Values)
            {
                stack.Controls.Clear();
                stack.RowStyles.Clear();
            }
            editors.Clear();
            jsonValues.Clear();
            reasonOrder.Clear();
            perReasonValues.Clear();
            perReasonShown = null;

            AdoptSettings(current);

            var fields = new Dictionary<string, Dictionary<string, object>>();
            foreach (object entry in schema)
            {
                var field = entry as Dictionary<string, object>;
                string name = Str(field, "name");
                if (name == null) continue;
                fields[name] = field;
                if (name.StartsWith("custom_message_", StringComparison.Ordinal) && Str(field, "category") != null)
                    reasonOrder.Add(Str(field, "category"));
            }

            // General: the language this window speaks, what Windows does, what it tells you.
            TableLayoutPanel language = NewGroup(S("field.interface_language", "Interface language"), sections["general"]);
            interfaceCombo = LanguageCombo(fields, "interface_language", current);
            interfaceCombo.Anchor = AnchorStyles.Left;
            interfaceCombo.Margin = Pad(0, 0, 0, 6);
            language.Controls.Add(interfaceCombo);
            language.Controls.Add(HelpText(S("help.interface_language",
                "Used by this window, the notification-area popup, notifications and the panel in Codex.")));
            editors["interface_language"] = interfaceCombo;
            TableLayoutPanel windows = NewGroup(S("group.windows", "Windows"), sections["general"]);
            // First in its card, above the Windows preferences the schema adds.
            CheckBox startup = NewCheck(S("field.startup", "Run at Windows sign-in"), false);
            windows.Controls.Add(startup);
            editors["__startup"] = startup;
            TableLayoutPanel notifications = NewGroup(S("group.notifications", "Notifications"), sections["general"]);

            // Automatic recovery: which kinds of interruption may be recovered at all.
            TableLayoutPanel recovery = NewGroup(S("group.recovery", "Automatic recovery"), sections["recovery"]);
            recovery.Controls.Add(HelpText(S("help.recovery",
                "Only kinds of failure the product can recognize are ever recovered. Turning one off stops it; turning one on cannot make an unknown failure recoverable.")));

            // Continuation message: its language and style, the Custom text, and the Preview.
            TableLayoutPanel words = NewGroup(S("group.continuation", "Continuation message"), sections["continuation"]);
            customCard = NewGroup(S("choice.style.custom", "Custom"), sections["continuation"]);
            TableLayoutPanel preview = NewGroup(S("preview.title", "Preview"), sections["continuation"]);

            // Appearance, and the limits nobody needs to change to get started.
            TableLayoutPanel look = NewGroup(S("group.appearance", "Appearance"), sections["appearance"]);
            var theme = new Label();
            theme.AutoSize = true;
            theme.Text = S("choice.theme.light", "Light");
            theme.ForeColor = Ink;
            look.Controls.Add(NewRow(S("field.theme", "Theme"), theme));
            look.Controls.Add(HelpText(S("help.theme",
                "This window always uses the light theme. The panel in Codex follows Codex's own light or dark theme.")));
            TableLayoutPanel limits = NewGroup(S("group.limits", "Limits"), sections["advanced"]);
            limits.Controls.Add(HelpText(S("help.limits", "Sets how hard recovery tries before it stops and leaves the task to you.")));

            CheckBox master = null;
            var subordinate = new List<CheckBox>();
            foreach (object entry in schema)
            {
                var field = entry as Dictionary<string, object>;
                string name = Str(field, "name");
                if (name == null) continue;
                string group = Str(field, "group") ?? "advanced";
                TableLayoutPanel host = group == "recovery" ? recovery
                                      : group == "limits" ? limits
                                      : group == "notifications" ? notifications
                                      : group == "windows" ? windows
                                      : group == "appearance" ? look : null;
                // General and Continuation are laid out by hand; the "advanced" fields - which
                // engine binary to run, how far back to look - stay out of the window.
                if (host == null) continue;

                string type = Str(field, "type");
                if (type == "boolean")
                {
                    CheckBox check = NewCheck(Humanise(name), Equals(Get(current, name), true));
                    if (Equals(Get(field, "master"), true))
                    {
                        // The heading role, which is built from the family rather than
                        // `new Font(check.Font, Bold)`: that overload can land on a substituted face
                        // and the row then renders in a different typeface from the rest of the window.
                        check.Font = Soft.RoleFont("heading");
                        check.Margin = Pad(0, 2, 0, 6);
                        master = check;
                    }
                    else if (host == notifications)
                    {
                        check.Margin = Pad(22, 2, 0, 2);   // subordinate to the master
                        subordinate.Add(check);
                    }
                    host.Controls.Add(check);
                    editors[name] = check;
                    if (name == "reduce_motion")
                        host.Controls.Add(HelpText(S("help.reduce_motion",
                            "Stops the breathing and pulsing status animations in this window and the notification-area popup. Windows' own Animation effects setting is always honored as well.")));
                }
                else if (type == "integer")
                {
                    // A number in a well, as the panel's number field is. Everything is still read
                    // from and written to the NumericUpDown inside it.
                    var number = new SoftNumber();
                    NumericUpDown spin = number.Spin;
                    GiveTextRoom(spin);
                    spin.Minimum = field.ContainsKey("min") ? (decimal)(double)field["min"] : 0;
                    spin.Maximum = field.ContainsKey("max") ? (decimal)(double)field["max"] : 100;
                    decimal value = current.ContainsKey(name) ? (decimal)(double)current[name] : spin.Minimum;
                    spin.Value = Math.Min(spin.Maximum, Math.Max(spin.Minimum, value));
                    IgnoreWheel(spin);
                    host.Controls.Add(NewRow(Humanise(name), number));
                    editors[name] = spin;
                }
                else if (type == "string" && field.ContainsKey("choices"))
                {
                    // Displayed translated, stored untranslated. `Choice` keeps the two
                    // apart, so Save writes "normal" whatever the label says - a settings
                    // file that changes meaning with the display language would be a bug
                    // the user could not see until the watcher read it back.
                    SoftCombo combo = ChoiceCombo(field, current, "choice.");
                    host.Controls.Add(NewRow(Humanise(name), combo));
                    editors[name] = combo;
                }
            }
            if (master != null)
            {
                // Progressive disclosure for notifications: the individual events only matter
                // while notifications are on, so they are live only then.
                CheckBox governing = master;
                EventHandler follow = delegate { foreach (CheckBox sub in subordinate) sub.Enabled = governing.Checked; };
                governing.CheckedChanged += follow;
                follow(governing, EventArgs.Empty);
            }

            BuildContinuation(fields, current, words, preview);

            columns.ResumeLayout(true);
            ShowSection(currentSection);
            if (!auditing) RefreshStatusAsync(null);
        }

        private void BuildContinuation(Dictionary<string, Dictionary<string, object>> fields,
                                       Dictionary<string, object> current, TableLayoutPanel words,
                                       TableLayoutPanel preview)
        {
            continuationCombo = LanguageCombo(fields, "continuation_language", current);
            words.Controls.Add(NewRow(S("field.continuation_language", "Continuation language"), continuationCombo));
            words.Controls.Add(HelpText(S("help.continuation_language",
                "The language of the message sent to Codex. Unless it follows the interface, changing the interface language leaves it as it is.")));
            editors["continuation_language"] = continuationCombo;

            words.Controls.Add(Caption(S("field.continuation_style", "Message style")));
            styleGroup = new ChoiceGroup();
            styleGroup.Dock = DockStyle.Fill;
            styleGroup.Font = Font;
            styleGroup.Margin = Pad(0, 2, 0, 4);
            styleGroup.AccessibleName = S("field.continuation_style", "Message style");
            Dictionary<string, object> styleField;
            List<object> styles = fields.TryGetValue("continuation_style", out styleField) ? Items(styleField, "choices") : null;
            if (styles == null) styles = new List<object> { "minimal", "standard", "detailed", "custom" };
            foreach (object choice in styles)
            {
                string style = Convert.ToString(choice, CultureInfo.InvariantCulture);
                styleGroup.Add(new ChoiceCard(style, S("choice.style." + style, style), S("help.style." + style, "")));
            }
            styleGroup.Value = Str(current, "continuation_style") ?? "standard";
            if (styleGroup.Value == null) styleGroup.Value = "standard";
            words.Controls.Add(styleGroup);
            ChoiceGroup chosenStyle = styleGroup;
            jsonValues["continuation_style"] = delegate { return Json.Escape(chosenStyle.Value ?? "standard"); };

            // Custom: shown only while Custom is the style. Its text is sent exactly as it is
            // typed; the only change made is the one the text box makes itself - Windows line
            // breaks are stored as plain ones.
            Dictionary<string, object> modeField;
            modeCombo = ChoiceCombo(fields.TryGetValue("custom_message_mode", out modeField) ? modeField : null,
                                    current, "choice.custom_mode.");
            modeCombo.Width = Px(300);
            customCard.Controls.Add(NewRow(S("field.custom_message_mode", "Use the message for"), modeCombo));
            editors["custom_message_mode"] = modeCombo;

            customCard.Controls.Add(Caption(S("custom.global_title", "Message for every interruption")));
            globalText = TextArea(FromStored(Str(current, "custom_message")),
                                  S("custom.global_title", "Message for every interruption"));
            customCard.Controls.Add(globalText);
            globalCount = CountLabel();
            customCard.Controls.Add(TextFooter(globalText, globalCount));
            SoftTextArea global = globalText;
            jsonValues["custom_message"] = delegate { return TextJson(global.Box.Text); };

            // A ground in the card's colour: the Clear button in it is lifted on it (see Ground).
            perReasonPanel = new SoftStack();
            perReasonPanel.ColumnCount = 1;
            perReasonPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            perReasonPanel.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            perReasonPanel.AutoSize = true;
            perReasonPanel.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            perReasonPanel.Dock = DockStyle.Fill;
            perReasonPanel.Margin = new Padding(0);
            perReasonPanel.BackColor = Surface;
            perReasonPanel.Controls.Add(Caption(S("custom.per_reason_title", "Message for one kind of interruption")));
            perReasonCombo = new SoftCombo();
            perReasonCombo.Width = Px(260);
            IgnoreWheel(perReasonCombo);
            foreach (string category in reasonOrder)
            {
                perReasonCombo.Items.Add(new Choice(category, S("reason." + category, category)));
                perReasonValues[category] = FromStored(Str(current, "custom_message_" + category));
                string key = category;
                jsonValues["custom_message_" + key] = delegate { return TextJson(PerReasonValue(key)); };
            }
            perReasonPanel.Controls.Add(NewRow(S("custom.edit_for", "Message for"), perReasonCombo));
            perReasonText = TextArea("", S("custom.per_reason_title", "Message for one kind of interruption"));
            perReasonPanel.Controls.Add(perReasonText);
            perReasonCount = CountLabel();
            perReasonPanel.Controls.Add(TextFooter(perReasonText, perReasonCount));
            customCard.Controls.Add(perReasonPanel);
            perReasonCombo.SelectedIndexChanged += delegate { SwitchPerReason(); SchedulePreview(); };
            if (perReasonCombo.Items.Count > 0) perReasonCombo.SelectedIndex = 0;

            customRefusal = HelpText("");
            customRefusal.ForeColor = Palette.Danger;
            customCard.Controls.Add(customRefusal);
            customCard.Controls.Add(HelpText(S("custom.placeholders", "You can use {reason}, {category}, {attempt}, {max_attempts} and {reset_time}.")));
            customCard.Controls.Add(HelpText(S("custom.verbatim",
                "Sent exactly as written. It is never translated or reworded, and changing either language leaves it as it is.")));
            customCard.Controls.Add(HelpText(S("custom.fallback",
                "An empty message falls back to the message for every interruption, and then to the Standard message.")));

            // Preview: the exact text, from the same function the watcher sends with.
            previewReason = new SoftCombo();
            previewReason.Width = Px(260);
            IgnoreWheel(previewReason);
            foreach (string category in reasonOrder)
                previewReason.Items.Add(new Choice(category, S("reason." + category, category)));
            if (previewReason.Items.Count > 0) previewReason.SelectedIndex = 0;
            preview.Controls.Add(NewRow(S("preview.for", "Preview for"), previewReason));
            previewText = new SoftQuote();
            previewText.Dock = DockStyle.Fill;
            previewText.Font = Font;
            previewText.Margin = Pad(0, 6, 0, 4);
            previewText.AccessibleName = S("preview.title", "Preview");
            preview.Controls.Add(previewText);
            previewSource = HelpText("");
            preview.Controls.Add(previewSource);
            preview.Controls.Add(HelpText(S("preview.note",
                "This is the text that will be sent. The watcher adds one line after it to recognise the exact turn it starts.")));

            interfaceCombo.SelectedIndexChanged += delegate { RelabelFollow(); SchedulePreview(); };
            continuationCombo.SelectedIndexChanged += delegate { SchedulePreview(); };
            styleGroup.ValueChanged += delegate { UpdateContinuationVisibility(); SchedulePreview(); };
            modeCombo.SelectedIndexChanged += delegate { UpdateContinuationVisibility(); SchedulePreview(); };
            previewReason.SelectedIndexChanged += delegate { SchedulePreview(); };
            RelabelFollow();
            UpdateContinuationVisibility();
            SchedulePreview();
        }

        private SoftCombo LanguageCombo(Dictionary<string, Dictionary<string, object>> fields, string name,
                                        Dictionary<string, object> current)
        {
            var combo = new SoftCombo();
            combo.Width = Px(300);
            IgnoreWheel(combo);
            Dictionary<string, object> field;
            List<object> choices = fields.TryGetValue(name, out field) ? Items(field, "choices") : null;
            if (choices == null) choices = new List<object>();
            string value = Str(current, name);
            int index = 0;
            foreach (object choice in choices)
            {
                string locale = Convert.ToString(choice, CultureInfo.InvariantCulture);
                if (locale == value) index = combo.Items.Count;
                combo.Items.Add(new Choice(locale, LanguageLabel(locale)));
            }
            if (combo.Items.Count > 0) combo.SelectedIndex = index;
            combo.AccessibleName = S("field." + name, name);
            return combo;
        }

        private string LanguageLabel(string locale)
        {
            if (locale == "system")
                return S("choice.language.system", "System ({language})", "language", Endonym(systemLanguage));
            if (locale == "follow")
                return S("choice.continuation_language.follow", "Same as the interface ({language})", "language",
                         Endonym(InterfaceLocale()));
            return Endonym(locale);
        }

        private string Endonym(string locale)
        {
            object name;
            return locale != null && endonyms.TryGetValue(locale, out name) && name is string ? (string)name : locale;
        }

        /// The interface language as currently chosen on this page, resolved.
        private string InterfaceLocale()
        {
            var chosen = interfaceCombo == null ? null : interfaceCombo.SelectedItem as Choice;
            string value = chosen == null ? loadedInterfaceLanguage : chosen.Value;
            return string.IsNullOrEmpty(value) || value == "system" ? systemLanguage : value;
        }

        /// "Same as the interface (...)" names the interface language, so it follows that choice.
        private void RelabelFollow()
        {
            if (continuationCombo == null || continuationCombo.Items.Count == 0) return;
            var first = continuationCombo.Items[0] as Choice;
            if (first == null || first.Value != "follow") return;
            int keep = continuationCombo.SelectedIndex;
            continuationCombo.Items[0] = new Choice("follow", LanguageLabel("follow"));
            continuationCombo.SelectedIndex = keep;
        }

        private SoftCombo ChoiceCombo(Dictionary<string, object> field, Dictionary<string, object> current, string prefix)
        {
            var combo = new SoftCombo();
            combo.Width = Px(150);
            IgnoreWheel(combo);
            string name = Str(field, "name");
            List<object> choices = Items(field, "choices") ?? new List<object>();
            string value = name == null ? null : Str(current, name);
            int index = 0;
            foreach (object choice in choices)
            {
                string text = Convert.ToString(choice, CultureInfo.InvariantCulture);
                if (text == value) index = combo.Items.Count;
                combo.Items.Add(new Choice(text, S(prefix + text, text)));
            }
            if (combo.Items.Count > 0) combo.SelectedIndex = index;
            return combo;
        }

        private SoftTextArea TextArea(string text, string name)
        {
            var area = new SoftTextArea();
            area.Dock = DockStyle.Fill;
            area.Margin = Pad(0, 2, 0, 2);
            area.Font = Font;
            area.Box.Font = Font;
            area.Box.Text = text ?? "";
            area.Box.AccessibleName = name;
            area.Box.TextChanged += delegate { SchedulePreview(); };
            return area;
        }

        private Label CountLabel()
        {
            var label = new Label();
            label.AutoSize = true;
            label.ForeColor = Secondary;
            label.Margin = Pad(2, 6, 0, 0);
            return label;
        }

        private Control TextFooter(SoftTextArea area, Label count)
        {
            // A ground in the card's colour, for the Clear button's lift (see Ground).
            var row = new SoftStack();
            row.ColumnCount = 2;
            row.RowCount = 1;
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            row.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.Dock = DockStyle.Fill;
            row.Margin = Pad(0, 0, 0, 4);
            row.BackColor = Surface;
            count.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            Button clear = MakeButton(S("custom.clear", "Clear"), false, delegate { area.Box.Clear(); area.Box.Focus(); });
            clear.MinimumSize = new Size(Px(88), Px(34));
            clear.Anchor = AnchorStyles.Right | AnchorStyles.Top;
            clear.Margin = new Padding(0);
            row.Controls.Add(count, 0, 0);
            row.Controls.Add(clear, 1, 0);
            area.Box.TextChanged += delegate { UpdateCount(area, count); };
            UpdateCount(area, count);
            return row;
        }

        private void UpdateCount(SoftTextArea area, Label count)
        {
            int length = CustomLength(area.Box.Text);
            count.Text = length.ToString(CultureInfo.CurrentCulture) + " / " +
                         MaxCustomLength.ToString(CultureInfo.CurrentCulture);
            count.ForeColor = length > MaxCustomLength ? Palette.Danger : Secondary;
        }

        /// A message's length as the settings layer counts it: Python's len(), in code points,
        /// of the text as it is stored, with Windows line breaks as plain ones. string.Length
        /// counts UTF-16 units, so every emoji counted twice, and 1200 of them showed a red
        /// "2400 / 2000" over a message Save accepts. An unpaired surrogate is one character,
        /// as the U+FFFD it is sent as.
        internal static int CustomLength(string text)
        {
            string stored = (text ?? "").Replace("\r\n", "\n");
            int length = 0;
            for (int i = 0; i < stored.Length; i++)
                if (i == 0 || !char.IsSurrogatePair(stored[i - 1], stored[i])) length++;
            return length;
        }

        /// A message as the settings file stores it: Windows line breaks as plain ones, and an
        /// empty or blank box as "not set", which falls back rather than sending nothing.
        private static string TextJson(string text)
        {
            string plain = (text ?? "").Replace("\r\n", "\n");
            return plain.Trim().Length == 0 ? "null" : Json.Escape(plain);
        }

        private static string FromStored(string text)
        {
            return text == null ? "" : text.Replace("\r\n", "\n").Replace("\n", "\r\n");
        }

        private void SwitchPerReason()
        {
            if (perReasonShown != null) perReasonValues[perReasonShown] = perReasonText.Box.Text;
            var chosen = perReasonCombo.SelectedItem as Choice;
            perReasonShown = chosen == null ? null : chosen.Value;
            string text;
            perReasonText.Box.Text = perReasonShown != null && perReasonValues.TryGetValue(perReasonShown, out text)
                                   ? text : "";
        }

        private string PerReasonValue(string category)
        {
            if (category == perReasonShown && perReasonText != null) return perReasonText.Box.Text;
            string text;
            return perReasonValues.TryGetValue(category, out text) ? text : "";
        }

        private void UpdateContinuationVisibility()
        {
            // Set every time, never only when `Visible` differs: it answers false for anything in a
            // hidden section or page, and the editors are built while theirs is hidden - on idle, or
            // while General is shown. A card told to hide there was left showing under Standard.
            bool custom = styleGroup != null && styleGroup.Value == "custom";
            if (customCard != null) customCard.Visible = custom;
            var mode = modeCombo == null ? null : modeCombo.SelectedItem as Choice;
            bool perReason = custom && mode != null && mode.Value == "per_reason";
            if (perReasonPanel != null) perReasonPanel.Visible = perReason;
        }

        private static string ComboJson(ComboBox combo)
        {
            var chosen = combo == null ? null : combo.SelectedItem as Choice;
            return chosen == null ? "null" : Json.Escape(chosen.Value);
        }

        /// The Preview follows what is on screen, a moment after it stops changing.
        private void SchedulePreview()
        {
            if (previewText == null || auditing) return;
            if (previewTimer == null)
            {
                previewTimer = new Timer();
                previewTimer.Interval = 350;
                previewTimer.Tick += delegate { previewTimer.Stop(); RunPreview(); };
            }
            previewTimer.Stop();
            previewTimer.Start();
        }

        private void RunPreview()
        {
            var reason = previewReason == null ? null : previewReason.SelectedItem as Choice;
            if (reason == null || previewText == null || styleGroup == null) return;
            var payload = new StringBuilder("{\"category\":").Append(Json.Escape(reason.Value)).Append(",\"changes\":{");
            payload.Append("\"interface_language\":").Append(ComboJson(interfaceCombo));
            payload.Append(",\"continuation_language\":").Append(ComboJson(continuationCombo));
            payload.Append(",\"continuation_style\":").Append(Json.Escape(styleGroup.Value ?? "standard"));
            payload.Append(",\"custom_message_mode\":").Append(ComboJson(modeCombo));
            payload.Append(",\"custom_message\":").Append(TextJson(globalText == null ? "" : globalText.Box.Text));
            foreach (string category in reasonOrder)
                payload.Append(',').Append(Json.Escape("custom_message_" + category)).Append(':')
                       .Append(TextJson(PerReasonValue(category)));
            payload.Append("}}");
            int token = ++previewToken;
            string argument = payload.ToString();
            // Not CallAsync: a Preview is not an action, so it neither waits for one nor makes
            // the window's buttons wait for it.
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply = null;
                try { reply = bridge.Call("preview-continuation", argument); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    if (token != previewToken) return;     // a newer Preview is on its way
                    var result = Ok(reply) ? Map(reply, "result") : null;
                    if (result == null)
                    {
                        previewText.Quote = S("preview.unavailable", "Preview is not available right now.");
                        previewSource.Text = "";
                        previewSource.Visible = false;
                        customRefusal.Text = "";
                        customRefusal.Visible = false;
                        return;
                    }
                    previewText.Quote = Str(result, "text") ?? "";
                    string source = Str(result, "source");
                    previewSource.Text = source == null ? "" : S("preview.source." + source, "");
                    previewSource.Visible = previewSource.Text.Length > 0;
                    customRefusal.Text = RefusalText(result);
                    customRefusal.Visible = customRefusal.Text.Length > 0;
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { }
            });
        }

        /// Why a Custom message would be refused, in the window's language.
        private string RefusalText(Dictionary<string, object> result)
        {
            string english = Str(result, "refusal");
            if (english == null) return "";
            string code = Str(result, "refusal_code");
            string reason = code == null ? english
                : S("custom.refusal." + code, english)
                      .Replace("{placeholder}", Str(result, "refusal_detail") ?? "")
                      .Replace("{max}", MaxCustomLength.ToString(CultureInfo.CurrentCulture));
            return S("custom.refused", "Not saved: {reason}", "reason", reason);
        }

        /// Minimizing stops the halo's timer, and a restore changes neither the dot's state nor
        /// its visibility, the only other things that start it again - so a watcher that was
        /// breathing came back from the taskbar looking stuck. Both raise Resize.
        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            stateDot.Sync();
        }

        private void StatusUnavailable()
        {
            stateDot.State = "idle";
            headline.Text = S("status.unavailable", "Status unavailable");
            detail.Text = S("status.unavailable_detail", "Settings can still be changed and saved");
            // The version is deliberately left as it was: a failed status read is no
            // reason to drop the one field people are asked for when reporting a bug.
            header.Invalidate(true);
        }

        /// The status line, read on a worker. `after` runs on the window's thread once the
        /// line has been written, so a caller with something more specific to say gets the
        /// last word instead of racing the read for it.
        private void RefreshStatusAsync(Action after)
        {
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply = null;
                try { reply = bridge.Call("status", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    var status = Ok(reply) ? reply["status"] as Dictionary<string, object> : null;
                    if (status != null)
                        ApplyStatus(status, editors.ContainsKey("__startup") ? editors["__startup"] as CheckBox : null);
                    else StatusUnavailable();
                    if (after != null) after();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { }
            });
        }

        private void ApplyStatus(Dictionary<string, object> status, CheckBox startup)
        {
            object running = status["watcher_running"];
            bool enabled = Equals(status["enabled"], true);
            double pending = status.ContainsKey("pending") ? (double)status["pending"] : 0;
            if (startup != null) startup.Checked = Equals(status["startup_enabled"], true);

            // The coarse state, from the status alone, until the Dashboard has a snapshot. From
            // then on UpdateCountdowns is the one place the dot is decided, from the pending list
            // as well - recovering, due to be checked. Deciding it here too put the coarse state
            // and then the refined one on the dot in the same refresh, and every change restarts
            // the halo: an alarm pulsed again every five seconds, and an arc jumped to its start.
            // A watcher that is not running, or not known to be, is a light that is off - grey, as
            // it was until v0.6.3; the headline beside it says what is wrong (see Activity).
            if (snapshot == null)
                stateDot.State = !Equals(running, true) ? "idle"
                               : !enabled ? "paused" : pending > 0 ? "waiting" : "monitoring";
            headline.Text = running == null ? S("status.unknown", "Watcher status unknown")
                          : !Equals(running, true) ? S("status.not_running", "Watcher not running")
                          : enabled ? S("status.watching", "Watching for interruptions")
                          : S("status.paused", "Automatic recovery paused");
            int count = (int)pending;
            string tail = count == 0 ? S("status.pending_none", "Nothing pending")
                        : count == 1 ? S("status.pending_one", "1 recovery pending")
                        : S("status.pending_many", "{n} recoveries pending", "n", (int)count);
            // Two facts, most consequential first: whether recovery can happen at
            // all, and then what is waiting on it.
            string recovery = !Equals(running, true)
                              ? S("status.recovery_idle", "Nothing will be recovered until it is running")
                            : enabled ? S("status.recovery_on", "Automatic recovery is on")
                            : S("status.recovery_paused", "Automatic recovery is paused");
            detail.Text = recovery + "   ·   " + tail;
            versionText.Text = "v" + status["version"];
            if (startButton != null) startButton.Visible = Equals(running, false);
            header.Invalidate(true);
        }

        // ------------------------------------------------------------------ actions
        private void StartWatcher()
        {
            // Off the UI thread, because the wait is now real.
            //
            // `bridge.Call` starts python.exe and blocks reading its output until it
            // exits, and the engine behind it waits up to six seconds for the watcher to
            // become visible. Run on the click handler, that is six seconds in which this
            // window pumps no messages: Windows paints a grey ghost copy and retitles it
            // "Not Responding" after five. The "Starting the watcher..." headline set
            // just above would never even appear, because the WM_PAINT it queues is not
            // dispatched until the call returns.
            //
            // So the call goes to a worker and the answer comes back through BeginInvoke,
            // which is the only way to touch these controls from off the UI thread.
            startButton.Enabled = false;
            headline.Text = S("start.working", "Starting the watcher...");
            detail.Text = S("start.waiting", "Waiting for it to report in");
            header.Invalidate(true);

            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> response = null;
                Exception failure = null;
                try { response = bridge.Call("start-watcher", null); }
                catch (Exception error) { failure = error; }

                MethodInvoker finish = delegate { StartWatcherFinished(response, failure); };
                try
                {
                    if (IsHandleCreated) BeginInvoke(finish);
                }
                catch (Exception)
                {
                    // The window closed while the watcher was starting. The watcher is
                    // unaffected - it is a detached process - and there is nothing left
                    // to report to.
                }
            });
        }

        private void StartWatcherFinished(Dictionary<string, object> response, Exception failure)
        {
            try
            {
                if (failure != null) throw failure;
                if (!Equals(response["ok"], true))
                    throw new InvalidOperationException((string)response["error"]);
                // No fixed wait any more. The engine waits for the same single-instance
                // mutex probe the status line reads and reports what it saw, so the
                // answer is already known by the time this returns. The old 1200 ms sleep
                // was both slower than an ordinary start - measured at 0.16-0.30 s - and
                // shorter than a slow one, in which case the window showed "not running"
                // for a watcher that was starting perfectly well.
                var result = response.ContainsKey("result")
                           ? response["result"] as Dictionary<string, object> : null;
                string state = result != null && result.ContainsKey("state")
                             ? result["state"] as string : null;
                RefreshStatusAsync(delegate
                {
                    if (state == "running" || state == "already-running") return;
                    // The status line has just been written from the probe, so this
                    // replaces it rather than racing it: the watcher is not running, and
                    // the reason it is not is worth more than the reason a stopped
                    // watcher is normally not running.
                    detail.Text = state == "exited"
                        ? S("start.exited", "It started and stopped again. See the logs in the installation folder.")
                        : S("start.unconfirmed", "Started, but not confirmed running yet");
                    header.Invalidate(true);
                });
            }
            catch (Exception error)
            {
                RefreshStatusAsync(null);
                MessageBox.Show(this, S("start.failed", "Could not start the watcher.") + Environment.NewLine +
                                Environment.NewLine + error.Message,
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            startButton.Enabled = true;
        }

        private void Save()
        {
            var changes = new StringBuilder("{");
            bool first = true;
            foreach (KeyValuePair<string, Control> pair in editors)
            {
                if (pair.Key == "__startup") continue;
                if (!first) changes.Append(',');
                first = false;
                changes.Append(Json.Escape(pair.Key)).Append(':');
                var check = pair.Value as CheckBox;
                var spin = pair.Value as NumericUpDown;
                var combo = pair.Value as ComboBox;
                if (check != null) changes.Append(check.Checked ? "true" : "false");
                else if (spin != null) changes.Append(((int)spin.Value).ToString(CultureInfo.InvariantCulture));
                else if (combo != null)
                {
                    var chosen = combo.SelectedItem as Choice;
                    changes.Append(Json.Escape(chosen == null ? null : chosen.Value));
                }
            }
            foreach (KeyValuePair<string, Func<string>> pair in jsonValues)
            {
                if (!first) changes.Append(',');
                first = false;
                changes.Append(Json.Escape(pair.Key)).Append(':').Append(pair.Value());
            }
            changes.Append('}');

            var chosenLanguage = interfaceCombo == null ? null : interfaceCombo.SelectedItem as Choice;
            string language = chosenLanguage == null ? loadedInterfaceLanguage : chosenLanguage.Value;
            bool languageChanged = language != loadedInterfaceLanguage;
            var motion = editors.ContainsKey("reduce_motion") ? editors["reduce_motion"] as CheckBox : null;

            // The two writes on a worker, in order: the settings, then the sign-in entry.
            // Neither is started until the one before it has been answered, so a failure
            // stops the rest rather than reporting a save that half happened.
            var startup = editors.ContainsKey("__startup") ? editors["__startup"] as CheckBox : null;
            bool startAtSignIn = startup != null && startup.Checked;
            CallAsync("update", changes.ToString(), delegate(Dictionary<string, object> updated)
            {
                if (!Ok(updated)) { SaveFailed(updated); return; }
                loadedInterfaceLanguage = language;
                if (motion != null)
                {
                    Soft.ReduceMotionSetting = motion.Checked;
                    stateDot.Sync();
                }
                CallAsync("startup", "{\"enabled\":" + (startAtSignIn ? "true" : "false") + "}",
                          delegate(Dictionary<string, object> registered)
                {
                    if (!Ok(registered)) { SaveFailed(registered); return; }
                    RefreshStatusAsync(delegate
                    {
                        // A new interface language reaches this window the next time it opens;
                        // saying so is better than a window that half changes under the reader.
                        detail.Text = languageChanged
                            ? S("settings.language_changed", "Language changed. Anything already open changes the next time it opens.")
                            : S("settings.saved", "Saved. The watcher uses these from its next check.");
                        header.Invalidate(true);
                    });
                });
            });
        }

        private void SaveFailed(Dictionary<string, object> reply)
        {
            MessageBox.Show(this, S("settings.save_failed", "Could not save.") + Environment.NewLine + Environment.NewLine +
                            Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture),
                            "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        private void RestoreDefaults()
        {
            if (MessageBox.Show(this, S("settings.confirm_restore", "Reset every setting to its recommended value?"),
                                "Codex Auto Resume", MessageBoxButtons.YesNo,
                                MessageBoxIcon.Question) != DialogResult.Yes) return;
            CallAsync("defaults", null, delegate(Dictionary<string, object> reply)
            {
                if (Ok(reply)) { Reload(); return; }
                MessageBox.Show(this, S("settings.restore_failed", "Could not restore defaults.") + Environment.NewLine +
                                Environment.NewLine + Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture),
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            });
        }
    }

    internal sealed partial class SettingsForm
    {
        // ------------------------------------------------------------------ layout audit
        private static readonly System.Reflection.MethodInfo OwnState =
            typeof(Control).GetMethod("GetState", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        /// Every place the window's layout cuts something off, at `scale` and in the language of
        /// `stringsJson`: one line each, and an empty string when there is none.
        ///
        /// The window is built as it opens, at its opening size, with the Custom message and its
        /// per-kind editor showing, and every page and every Settings section is laid out in turn.
        /// It is never shown - it is not even a top-level window - and nothing is sent to it.
        /// Another scaling is stood in for this machine's by scaling DpiScale and the fonts
        /// together, which matched a real 144-DPI window to the pixel when the v0.6.4 clipping was
        /// measured. Reported are:
        ///   * a control that reaches past a container that does not scroll;
        ///   * a page that would scroll sideways;
        ///   * a drop-down that is not one field high;
        ///   * text, a list's columns or other content that needs more room than it is drawn in,
        ///     and a status light too small for its glow.
        /// tests/test_gui_layout.py runs it in every language at five scalings.
        internal static string LayoutAudit(string schemaJson, string settingsJson, string stringsJson, double scale)
        {
            var findings = new List<string>();
            System.Reflection.FieldInfo fallback = typeof(Control).GetField("defaultFont",
                System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
            Font defaultBefore = Control.DefaultFont;
            Font baseBefore = Soft.BaseFont;
            try
            {
                dpiScale = scale;
                float factor = (float)(scale / SystemScale);
                Font box = SystemFonts.MessageBoxFont;
                var windowFont = new Font(box.FontFamily, box.SizeInPoints * factor, box.Style, GraphicsUnit.Point);
                // An unparented control measures in Control.DefaultFont, which follows the display too.
                if (fallback != null)
                    fallback.SetValue(null, new Font(defaultBefore.FontFamily, defaultBefore.SizeInPoints * factor,
                                                     defaultBefore.Style, GraphicsUnit.Point));
                var catalog = Json.Parse(stringsJson) as Dictionary<string, object>;
                var schema = Json.Parse(schemaJson) as List<object>;
                var current = Json.Parse(settingsJson) as Dictionary<string, object>;
                // A bridge rooted where nothing is: anything that still asked it would fail at once.
                string nowhere = Path.Combine(Path.GetTempPath(), "codex-auto-resume-layout-audit-" + Guid.NewGuid().ToString("N"));
                using (var form = new SettingsForm(new PersistentBridge(nowhere, new Bridge(nowhere)), catalog, windowFont))
                {
                    form.auditing = true;
                    // A child of Windows' parking window rather than a window of its own, so the
                    // screen it would open on neither clamps its size nor ever shows it.
                    form.TopLevel = false;
                    form.MinimumSize = Size.Empty;
                    form.ClientSize = new Size(form.Px(860), form.Px(600));
                    form.BuildEditors(schema, current);
                    foreach (string page in PageOrder)
                    {
                        form.ShowPage(page);
                        if (page != "settings")
                        {
                            form.Audit(page, findings);
                            continue;
                        }
                        foreach (string section in SectionOrder)
                        {
                            form.ShowSection(section);
                            form.Audit("settings/" + section, findings);
                        }
                    }
                }
            }
            finally
            {
                dpiScale = SystemScale;
                if (fallback != null) fallback.SetValue(null, defaultBefore);
                Soft.BaseFont = baseBefore;
            }
            return string.Join("\n", findings.ToArray());
        }

        /// Lays out what is on screen as showing the window would, and adds what does not fit.
        private void Audit(string where, List<string> findings)
        {
            // A drop-down takes its real height only once it has a window, so everything on screen
            // is given one, parents first.
            Materialise(this);
            PerformLayout();
            Walk(this, where, findings);
        }

        /// Whether a control itself is visible, whatever its parents are.
        private static bool OwnVisible(Control control)
        {
            return OwnState == null ? control.Visible : (bool)OwnState.Invoke(control, new object[] { 2 });
        }

        private static void Materialise(Control parent)
        {
            foreach (Control child in parent.Controls)
            {
                if (!OwnVisible(child) || child.Handle == IntPtr.Zero) continue;
                Materialise(child);
            }
        }

        private void Walk(Control parent, string path, List<string> findings)
        {
            var scroller = parent as ScrollableControl;
            bool scrolls = scroller != null && scroller.AutoScroll;
            if (scrolls && scroller.HorizontalScroll.Visible)
                findings.Add(path + " :: scrolls sideways, " + scroller.DisplayRectangle.Width + " wide in " + scroller.ClientSize.Width);
            foreach (Control child in parent.Controls)
            {
                if (!OwnVisible(child)) continue;
                string place = path + "/" + AuditName(child);
                if (!scrolls && parent != this)
                {
                    Size client = parent.ClientSize;
                    if (child.Left < 0 || child.Top < 0 || child.Right > client.Width || child.Bottom > client.Height)
                        findings.Add(place + " :: is cut off, " + child.Bounds + " in " + client);
                }
                var combo = child as SoftCombo;
                if (combo != null && combo.Height != SoftCombo.FieldHeight)
                    findings.Add(place + " :: is " + combo.Height + " high, not a field's " + SoftCombo.FieldHeight);
                string fit = Fits(child, scrolls);
                if (fit != null) findings.Add(place + " :: " + fit);
                Walk(child, place, findings);
            }
        }

        /// What a control needs and does not have, or null.
        private static string Fits(Control c, bool inScroller)
        {
            if (c.Width <= 0 || c.Height <= 0) return null;
            if (c is HaloDot)
                return 2 * HaloDot.Extent > Math.Min(c.Width, c.Height)
                     ? "is " + c.Size + ", too small for a glow " + 2 * HaloDot.Extent + " across" : null;
            var card = c as ChoiceCard;
            if (card != null) return Needs(card.HeightFor(c.Width), c.Height);
            var quote = c as SoftQuote;
            if (quote != null) return Needs(quote.GetPreferredSize(new Size(c.Width, 0)).Height, c.Height);
            var gates = c as GateList;
            if (gates != null) return inScroller ? null : Needs(gates.GetPreferredSize(new Size(c.Width, 0)).Height, c.Height);
            var list = c as ListView;
            if (list != null) return ColumnsFit(list);
            if (string.IsNullOrEmpty(c.Text) || c is TextBoxBase || c is ComboBox || c is UpDownBase) return null;
            var label = c as Label;
            if (label != null)
            {
                if (label.AutoSize)
                {
                    // A label stretched across its cell wraps at the cell's width; any other keeps
                    // the size it asks for.
                    bool stretched = label.Dock != DockStyle.None ||
                                     (label.Anchor & (AnchorStyles.Left | AnchorStyles.Right)) == (AnchorStyles.Left | AnchorStyles.Right);
                    Size wanted = label.GetPreferredSize(stretched ? new Size(label.Width, 0) : Size.Empty);
                    if (wanted.Height > label.Height) return "needs " + wanted.Height + " high, has " + label.Height;
                    if (wanted.Width > label.Width + 1) return "needs " + wanted.Width + " wide, has " + label.Width;
                    return null;
                }
                Size line = TextRenderer.MeasureText(label.Text, label.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine);
                if (line.Height > label.ClientSize.Height) return "needs " + line.Height + " high, has " + label.ClientSize.Height;
                // One that ends in an ellipsis narrows by design; one that does not is cut.
                if (!label.AutoEllipsis && line.Width > label.ClientSize.Width) return "needs " + line.Width + " wide, has " + label.ClientSize.Width;
                return null;
            }
            Size text = TextRenderer.MeasureText(c.Text, c.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine);
            var nav = c as NavButton;
            if (nav != null) return Inside(text, nav.TextBounds.Size);
            if (c is SoftButton) return Inside(text, c.ClientSize);
            var check = c as SoftCheck;
            if (check != null)
            {
                Size wanted = check.GetPreferredSize(Size.Empty);
                return wanted.Width > c.Width || wanted.Height > c.Height ? "needs " + wanted + ", has " + c.Size : null;
            }
            return null;
        }

        private static string Needs(int height, int has)
        {
            return height > has ? "needs " + height + " high, has " + has : null;
        }

        private static string Inside(Size text, Size room)
        {
            if (text.Height > room.Height) return "text needs " + text.Height + " high, has " + room.Height;
            return text.Width > room.Width ? "text needs " + text.Width + " wide, has " + room.Width : null;
        }

        /// A list's columns within its width, each heading whole in its column.
        private static string ColumnsFit(ListView list)
        {
            int total = 0;
            var cut = new List<string>();
            foreach (ColumnHeader column in list.Columns)
            {
                total += column.Width;
                // DrawHeader's inset: 10 before the heading, 4 after it.
                int room = column.Width - Soft.Px(14);
                int needed = TextRenderer.MeasureText(column.Text, list.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine).Width;
                if (needed > room) cut.Add("'" + column.Text + "' needs " + needed + ", has " + room);
            }
            if (total > list.ClientSize.Width) return "columns are " + total + " wide in " + list.ClientSize.Width;
            return cut.Count == 0 ? null : "column headings cut: " + string.Join("; ", cut.ToArray());
        }

        private static string AuditName(Control control)
        {
            string text = (control.Text ?? "").Replace("\r", " ").Replace("\n", " ");
            if (text.Length > 32) text = text.Substring(0, 32);
            if (text.Length == 0 && !string.IsNullOrEmpty(control.AccessibleName)) text = control.AccessibleName;
            return control.GetType().Name + (text.Length > 0 ? "'" + text + "'" : "");
        }
    }

    /// The last strings reply, kept so the window can label itself before the interpreter that
    /// answers has started.
    ///
    /// Opening the window waited 260-400 ms for Python to start and import, to be told the words
    /// it was told last time. A strings reply depends on three things, and a cached one is used
    /// only while all three are exactly what they were when it was written:
    ///   * the product and its catalogs: the window's version, and a digest of every file the
    ///     words and the language rules are read from. Not their length and time: a release
    ///     archive gives every file one fixed time, which extracting and copying keep, so a word
    ///     corrected to one of the same length changed neither;
    ///   * the Interface language stored in settings: a digest of the settings file, so any save
    ///     at all makes the next opening ask again, and the language read from those same bytes,
    ///     which a reply has to name as its own ("preference") to be kept or used;
    ///   * the language Windows asks for: the preferred UI languages, and the environment
    ///     variables Python reads before them.
    /// Anything else - no cache, one that cannot be read, a key that differs - is a miss, and a miss
    /// asks the bridge before the first label, as the window always did.
    ///
    /// The bridge reads the settings when it answers, after the key was taken. So a reply is kept
    /// only if the key still describes the installation just before the file is put in place: a
    /// language saved in between was otherwise kept under the old key, and opened a later window
    /// once the language had been set back. So a language that has just changed never opens in
    /// the old one.
    ///
    /// The file (config\strings-cache.json in the installation) is the window's own, beside the
    /// settings: config\ and logs\ are the only folders the product writes, and uninstalling with
    /// -Purge removes it with config\. Nothing else reads it, and deleting it only makes the next
    /// opening ask.
    internal static class StringsCache
    {
        [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern bool GetUserPreferredUILanguages(int flags, out int count, char[] buffer, ref int size);

        private const int MUI_LANGUAGE_NAME = 0x8;

        // Where a key names the Interface language it was made from (PreferenceIn).
        private const string PreferencePart = "|interface_language ";

        private static string PathIn(string root)
        {
            return Path.Combine(Path.Combine(root, "config"), "strings-cache.json");
        }

        /// This installation's key as it is now, or null when it cannot be told.
        internal static string Key(string root)
        {
            try
            {
                var key = new StringBuilder("2");
                key.Append("|window ").Append(typeof(StringsCache).Assembly.GetName().Version);
                key.Append("|root ").Append(Path.GetFullPath(root));
                using (var sha = System.Security.Cryptography.SHA256.Create())
                {
                    string app = Path.Combine(root, "app");
                    Stamp(key, sha, Path.Combine(Path.Combine(app, ".codex-plugin"), "plugin.json"));
                    string package = Path.Combine(Path.Combine(app, "src"), "codex_auto_resume");
                    foreach (string name in new[] { "interface.py", "l10n.py", "settings.py", "config.py", "controlcli.py" })
                        Stamp(key, sha, Path.Combine(package, name));
                    string locales = Path.Combine(package, "locales");
                    string[] catalogs = Directory.Exists(locales) ? Directory.GetFiles(locales, "*.json") : new string[0];
                    Array.Sort(catalogs, StringComparer.OrdinalIgnoreCase);
                    foreach (string catalog in catalogs) Stamp(key, sha, catalog);
                    // Read once, so the language is taken from the very bytes the digest is of.
                    string settings = Path.Combine(Path.Combine(root, "config"), "settings.json");
                    byte[] stored = File.Exists(settings) ? File.ReadAllBytes(settings) : null;
                    string preference = StoredPreference(stored);
                    if (preference == null) return null;
                    key.Append("|settings ").Append(stored == null ? "-" : Convert.ToBase64String(sha.ComputeHash(stored)));
                    key.Append(PreferencePart).Append(preference);
                }
                foreach (string name in new[] { "CODEX_AUTO_RESUME_LANG", "LC_ALL", "LC_MESSAGES", "LANG" })
                    key.Append('|').Append(name).Append(' ').Append(Environment.GetEnvironmentVariable(name) ?? "");
                key.Append("|windows ").Append(PreferredLanguages());
                return key.ToString();
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static void Stamp(StringBuilder key, System.Security.Cryptography.HashAlgorithm sha, string path)
        {
            key.Append('|').Append(Path.GetFileName(path)).Append(' ');
            key.Append(File.Exists(path) ? Convert.ToBase64String(sha.ComputeHash(File.ReadAllBytes(path))) : "-");
        }

        /// The Interface language `settings` stores, as the bridge takes it - `system` when there is
        /// no settings file or it names none - or null when the file cannot be read as settings.
        /// Wherever the bridge takes the file otherwise (a value it does not know is `system` to
        /// it), its reply names another language and is not kept, which is only a miss.
        private static string StoredPreference(byte[] settings)
        {
            if (settings == null) return "system";
            var map = Json.Parse(new UTF8Encoding(false).GetString(settings).TrimStart('﻿')) as Dictionary<string, object>;
            if (map == null) return null;
            object value;
            return map.TryGetValue("interface_language", out value) && value is string ? (string)value : "system";
        }

        /// The Interface language `key` was made from. Nothing before it in a key can hold a '|'.
        private static string PreferenceIn(string key)
        {
            int start = key.IndexOf(PreferencePart, StringComparison.Ordinal);
            if (start < 0) return null;
            start += PreferencePart.Length;
            int end = key.IndexOf('|', start);
            return end < 0 ? key.Substring(start) : key.Substring(start, end - start);
        }

        /// Whether `reply` is the answer for the Interface language `key` was made from.
        private static bool AnswersFor(Dictionary<string, object> reply, string key)
        {
            object preference;
            string wanted = PreferenceIn(key);
            return wanted != null && reply.TryGetValue("preference", out preference) &&
                   preference is string && (string)preference == wanted;
        }

        private static string PreferredLanguages()
        {
            int count, size = 0;
            if (!GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, out count, null, ref size) || size <= 0) return "-";
            var buffer = new char[size];
            if (!GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, out count, buffer, ref size)) return "-";
            return new string(buffer, 0, Math.Min(size, buffer.Length)).TrimEnd('\0').Replace('\0', ',');
        }

        private static bool Usable(Dictionary<string, object> reply)
        {
            object ok, words;
            return reply != null && reply.TryGetValue("ok", out ok) && Equals(ok, true) &&
                   reply.TryGetValue("strings", out words) && words is Dictionary<string, object>;
        }

        /// The reply cached for exactly `key`, and for the Interface language it was made from, or null.
        internal static Dictionary<string, object> Read(string root, string key)
        {
            if (key == null) return null;
            try
            {
                string path = PathIn(root);
                if (!File.Exists(path)) return null;
                var entry = Json.Parse(File.ReadAllText(path, Encoding.UTF8)) as Dictionary<string, object>;
                object stored, reply;
                if (entry == null || !entry.TryGetValue("key", out stored) || !(stored is string) || (string)stored != key) return null;
                if (!entry.TryGetValue("reply", out reply)) return null;
                var map = reply as Dictionary<string, object>;
                return Usable(map) && AnswersFor(map, key) ? map : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// Keeps `reply` under `key`: a reply for the Interface language the key was made from, and
        /// only while the key still describes this installation, checked again just before the file
        /// is put in place. Written beside the old file and moved over it, so nothing ever reads half
        /// of one; a failure leaves no cache, which is only a miss.
        internal static void Write(string root, string key, Dictionary<string, object> reply)
        {
            if (key == null || !Usable(reply) || !AnswersFor(reply, key)) return;
            string temporary = null;
            try
            {
                var entry = new Dictionary<string, object>();
                entry["key"] = key;
                entry["reply"] = reply;
                string path = PathIn(root);
                string folder = Path.GetDirectoryName(path);
                // The installation's own config\, never a folder made for the cache.
                if (!Directory.Exists(folder)) return;
                // Short, and this process's own: .NET Framework refuses a path of 260 characters, and
                // a GUID in the name took an installation in a deep folder past that - every write
                // failed there, silently, and the cache was never used.
                temporary = Path.Combine(folder,
                                         "strings-cache." + Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture) + ".tmp");
                File.WriteAllText(temporary, Json.Write(entry), new UTF8Encoding(false));
                if (Key(root) != key) return;
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
                temporary = null;
            }
            catch (Exception) { }
            finally
            {
                try { if (temporary != null && File.Exists(temporary)) File.Delete(temporary); }
                catch (Exception) { }
            }
        }

        /// Replaces the cache when a fresh reply says something other than the cached one - kept as
        /// Write keeps any reply, so only while `key` still describes this installation.
        internal static void Refresh(string root, string key, Dictionary<string, object> cached, Dictionary<string, object> fresh)
        {
            try
            {
                if (!Usable(fresh) || Json.Write(fresh) == Json.Write(cached)) return;
                Write(root, key, fresh);
            }
            catch (Exception) { }
        }
    }

    internal static class Program
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
            // The accessibility improvements .NET 4.8 ships but leaves off for an assembly
            // with no target-framework attribute, which is what the in-box compiler builds.
            // Without them a live region never reaches a screen reader.
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures", false);
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures.2", false);
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures.3", false);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            var bridge = new Bridge(root);
            if (!bridge.Available)
            {
                MessageBox.Show("Codex Auto Resume is not installed in this location." +
                                Environment.NewLine + Environment.NewLine + root,
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            Application.Run(new SettingsForm(new PersistentBridge(root, bridge)));
            return 0;
        }
    }
}

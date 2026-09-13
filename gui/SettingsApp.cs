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

        private readonly TableLayoutPanel columns = new TableLayoutPanel();
        // The Settings page's sections, in the order the section list shows them. Each is a
        // single column of cards; one is on screen at a time.
        private static readonly string[] SectionOrder = { "general", "recovery", "continuation", "appearance", "advanced" };
        private readonly Dictionary<string, TableLayoutPanel> sections = new Dictionary<string, TableLayoutPanel>();
        private readonly Dictionary<string, NavButton> sectionButtons = new Dictionary<string, NavButton>();
        private readonly Panel sectionScroll = new Panel();
        private string currentSection = "general";
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
        // Buffered for the same reason as the status dot: both strips draw a hairline in a
        // Paint handler, and the header is invalidated on every status refresh. Unbuffered,
        // it was erased to white and repainted a moment later, and a capture taken in that
        // moment - one in four, measured - showed the header with no rule under it.
        private readonly Panel header = new BufferedPanel();
        private readonly Panel footer = new BufferedPanel();
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

        private void LoadStrings()
        {
            try
            {
                var reply = bridge.Call("strings", null);
                if (Equals(reply["ok"], true) && reply.ContainsKey("strings"))
                {
                    strings = (Dictionary<string, object>)reply["strings"];
                    object names, system;
                    if (reply.TryGetValue("endonyms", out names) && names is Dictionary<string, object>)
                        endonyms = (Dictionary<string, object>)names;
                    if (reply.TryGetValue("system_language", out system) && system is string)
                        systemLanguage = (string)system;
                }
            }
            catch (Exception)
            {
                // English, then. A settings window that will not open because it could
                // not fetch its own labels is worse than one in the wrong language.
            }
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern int GetDpiForSystem();

        internal static readonly double DpiScale = MeasureDpiScale();

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

        internal SettingsForm(PersistentBridge bridge)
        {
            this.bridge = bridge;
            // Before anything is built: every label below asks the catalog for its text.
            LoadStrings();
            Text = "Codex Auto Resume";
            Font = SystemFonts.MessageBoxFont;
            ForeColor = Ink;
            BackColor = Canvas;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Font;
            ClientSize = new Size(Px(1040), Px(640));
            // Wide enough that the two columns always hold their content. Allowing a
            // narrower window buys nothing: the labels start truncating mid-word, which
            // looks broken rather than compact.
            MinimumSize = new Size(Px(820), Px(460));
            try
            {
                string icon = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "codex-auto-resume.ico");
                if (File.Exists(icon)) Icon = new Icon(icon);
            }
            catch (Exception) { /* an icon is decoration; never fail the window over it */ }

            BuildFooter();
            BuildHeader();
            BuildColumns();
            BuildDashboard();

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

            Load += delegate { Reload(); ShowPage(firstPage); StartClock(); };
            FormClosed += delegate { StopClock(); bridge.Stop(); };
        }

        // ------------------------------------------------------------------- chrome
        private void BuildColumns()
        {
            // The Settings page: the section list on the left and one section's cards on the
            // right, scrolling on their own if a section is taller than the window.
            columns.Dock = DockStyle.Fill;
            // FitToContent measures the sections before ShowPage first parents this page, and an
            // unparented control inherits Control.DefaultFont rather than the window's.
            columns.Font = Font;
            columns.BackColor = Canvas;
            columns.ColumnCount = 2;
            columns.RowCount = 1;
            // Wide enough for "Automatische Wiederherstellung" and its peers at every scaling.
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(244)));
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            columns.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            columns.Padding = Pad(12, 12, 8, 4);

            var list = new FlowLayoutPanel();
            list.Dock = DockStyle.Fill;
            list.FlowDirection = FlowDirection.TopDown;
            list.WrapContents = false;
            list.BackColor = Canvas;
            list.Margin = Pad(0, 8, 8, 0);
            list.AccessibleRole = AccessibleRole.PageTabList;
            list.AccessibleName = S("nav.settings", "Settings");
            foreach (string name in SectionOrder)
            {
                var button = new NavButton();
                button.Vertical = true;
                button.Text = SectionTitle(name);
                button.Font = Font;
                button.AutoSize = false;
                button.Size = new Size(Px(230), Px(40));
                button.Margin = Pad(0, 0, 0, 4);
                string target = name;
                button.Click += delegate { ShowSection(target); };
                sectionButtons[name] = button;
                list.Controls.Add(button);

                var stack = new TableLayoutPanel();
                stack.Dock = DockStyle.Top;
                stack.ColumnCount = 1;
                stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
                stack.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
                stack.AutoSize = true;
                stack.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                stack.BackColor = Canvas;
                stack.Font = Font;
                sections[name] = stack;
            }

            sectionScroll.Dock = DockStyle.Fill;
            sectionScroll.AutoScroll = true;
            sectionScroll.BackColor = Canvas;
            sectionScroll.Margin = new Padding(0);
            columns.Controls.Add(list, 0, 0);
            columns.Controls.Add(sectionScroll, 1, 0);
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
            sectionScroll.SuspendLayout();
            sectionScroll.Controls.Clear();
            sectionScroll.Controls.Add(sections[name]);
            sectionScroll.ResumeLayout(true);
            sectionScroll.AutoScrollPosition = new Point(0, 0);
            foreach (var pair in sectionButtons)
            {
                pair.Value.Current = pair.Key == name;
                pair.Value.Font = new Font(Font, pair.Key == name ? FontStyle.Bold : FontStyle.Regular);
            }
        }

        private void BuildHeader()
        {
            // What the watcher is doing belongs at the top, in the window's largest
            // type. It used to be a muted sentence in a strip along the bottom, under
            // sixteen checkboxes - which put the one thing a person opens this window to
            // check below everything they did not come for.
            header.Dock = DockStyle.Top;
            header.BackColor = Surface;
            header.Padding = Pad(22, 14, 18, 14);
            header.Height = TextRenderer.MeasureText("Ag", Font).Height * 2 + Px(44);

            var grid = new TableLayoutPanel();
            grid.Dock = DockStyle.Fill;
            grid.ColumnCount = 3;
            grid.RowCount = 2;
            // Wide enough for the dot at any scaling: an absolute 22 held a 24-pixel dot
            // at 200% and sliced a third of it off.
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(28)));   // state dot and its halo
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what it is doing
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // the way out
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));
            grid.BackColor = Surface;

            // Drawn rather than a glyph so the dot stays round and vertically centred at
            // any scaling, and it carries the same state as the words beside it. It
            // spans both rows because it describes the pair, not the first line. Its halo is
            // the one thing in the window that moves, and only while there is something to
            // show moving (see HaloDot); with motion reduced it holds still.
            var dot = stateDot;
            dot.Dock = DockStyle.Fill;
            dot.BackColor = Surface;

            headline.Dock = DockStyle.Fill;
            headline.TextAlign = ContentAlignment.BottomLeft;
            headline.ForeColor = Ink;
            headline.Font = new Font(Font.FontFamily, Font.Size + 2.5f, FontStyle.Bold);
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

            grid.Controls.Add(dot, 0, 0);
            grid.SetRowSpan(dot, 2);
            grid.Controls.Add(headline, 1, 0);
            grid.Controls.Add(detail, 1, 1);
            grid.Controls.Add(startButton, 2, 0);
            grid.SetRowSpan(startButton, 2);
            header.Controls.Add(grid);
            header.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (var pen = new Pen(Line))
                    e.Graphics.DrawLine(pen, 0, header.Height - 1, header.Width, header.Height - 1);
            };
        }

        private void BuildFooter()
        {
            footer.Dock = DockStyle.Bottom;
            footer.BackColor = Surface;
            footer.Padding = Pad(18, 14, 18, 16);

            var grid = new TableLayoutPanel();
            grid.Dock = DockStyle.Fill;
            grid.ColumnCount = 2;
            grid.RowCount = 1;
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // version
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // buttons
            // A Dock=Fill child of an implicit AutoSize row measures to nothing, and the
            // strip then renders empty. Say what the row is.
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            grid.BackColor = Surface;

            // In its own column, so narrowing the window shortens nothing that matters
            // and never takes away the one field people are asked for in a bug report.
            versionText.Dock = DockStyle.Fill;
            versionText.TextAlign = ContentAlignment.MiddleLeft;
            versionText.ForeColor = Idle;
            versionText.AutoEllipsis = true;

            var row = new FlowLayoutPanel();
            row.Dock = DockStyle.Fill;
            row.FlowDirection = FlowDirection.RightToLeft;
            row.WrapContents = false;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.BackColor = Surface;
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
            grid.Controls.Add(versionText, 0, 0);
            grid.Controls.Add(row, 1, 0);
            footer.Controls.Add(grid);
            // Measured, not derived. A strip sized by a formula cannot know how tall an
            // AutoSize button becomes once the font is applied, and being two pixels short
            // looks exactly like a drawing bug.
            footer.Height = Math.Max(grid.PreferredSize.Height, row.PreferredSize.Height)
                          + footer.Padding.Vertical;
            footer.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (var pen = new Pen(Line)) e.Graphics.DrawLine(pen, 0, 0, footer.Width, 0);
            };
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
            button.MinimumSize = new Size(Px(112), Px(38));
            button.Padding = Pad(12, 0, 12, 0);
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
            // It paints its own lifted body inside a band it keeps for the shadow, so the
            // padding starts outside that band (see SoftCard).
            var card = new SoftCard();
            card.Dock = DockStyle.Fill;
            card.ColumnCount = 1;
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            card.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            card.AutoSize = true;
            card.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            card.Margin = Pad(0, 0, 0, 2);
            int room = SoftCard.Room;
            card.Padding = new Padding(room + Px(18), room / 2 + Px(14), room + Px(16), room + room / 2 + Px(12));

            var heading = new Label();
            heading.Text = title;
            heading.AutoSize = true;
            heading.ForeColor = Ink;
            heading.Font = new Font(Font.FontFamily, Font.Size + 1.5f, FontStyle.Bold);
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
            label.Font = new Font(Font.FontFamily, Font.Size, FontStyle.Bold);
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
            row.BackColor = Color.Transparent;

            var label = new Label();
            label.Text = text;
            label.AutoSize = true;
            label.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            label.TextAlign = ContentAlignment.MiddleLeft;
            label.AutoEllipsis = true;
            // The label's margins are what reserve the editor's height.
            //
            // TableLayoutPanel measures this row from the label's cell, because a
            // ComboBox under-reports its height until it has been shown - that is the
            // whole reason the editor below is anchored to the top. So the row is as
            // tall as the label plus its margins and nothing else, and if that is less
            // than the editor really needs, the editor's bottom border is clipped away.
            //
            // Sizing the margins from both preferred heights does two jobs at once: the
            // row ends up the editor's height plus a little, so nothing can be clipped,
            // and the leftover is split above and below the label, so its text sits on
            // the editor's centre line. Both hold at every scaling and in every font,
            // including the Korean UI font, whose line height differs from the English
            // one - which a fixed margin could not do.
            int editorHeight = editor.PreferredSize.Height + Px(2);
            int labelHeight = label.PreferredSize.Height;
            int lift = Math.Max(0, (editorHeight - labelHeight) / 2);
            label.Margin = new Padding(0, lift, Px(12), Math.Max(0, editorHeight - labelHeight - lift));

            // Top, not just Right. A Right-only anchor centres the control vertically,
            // and TableLayoutPanel computes that centre from the size the control
            // reported *before* it was shown. A ComboBox then re-sizes itself to fit the
            // font, keeps the offset it was given, and hangs one to nine pixels past the
            // bottom of the row - where its own bottom border is clipped away. It looks
            // like a drawing bug and is a measurement one. Measured at 100/125/150/175/
            // 200/250%: correct only at 100%, and worse the higher the scaling.
            //
            // Anchoring to the top removes the dependence on that stale measurement
            // entirely. The row is always taller than the editor, so pinning it to the
            // top cannot clip at any scale, and both editor kinds then start on the same
            // line as each other. A margin does not work here for the same reason the
            // bug exists: the row's own AutoSize measures the stale height too, so the
            // margin does not make it grow.
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
                    BuildEditors(described["schema"] as List<object>,
                                 settings["settings"] as Dictionary<string, object>);
                });
            });
        }

        private void ReloadFailed(Dictionary<string, object> reply)
        {
            headline.Text = S("settings.load_failed", "Could not read the local settings");
            detail.Text = Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture);
            header.Invalidate(true);
        }

        private void BuildEditors(List<object> schema, Dictionary<string, object> current)
        {
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

            Soft.ReduceMotionSetting = Equals(Get(current, "reduce_motion"), true);
            stateDot.Sync();
            loadedInterfaceLanguage = Str(current, "interface_language") ?? "system";

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
                        // Built from the family rather than `new Font(check.Font, Bold)`:
                        // that overload can land on a substituted face and the row then
                        // renders in a different typeface from the rest of the window.
                        check.Font = new Font(Font.FontFamily, Font.Size, FontStyle.Bold);
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
                    var spin = new NumericUpDown();
                    spin.Width = Px(74);
                    spin.BorderStyle = BorderStyle.FixedSingle;
                    spin.BackColor = Palette.Raised;
                    GiveTextRoom(spin);
                    spin.Minimum = field.ContainsKey("min") ? (decimal)(double)field["min"] : 0;
                    spin.Maximum = field.ContainsKey("max") ? (decimal)(double)field["max"] : 100;
                    decimal value = current.ContainsKey(name) ? (decimal)(double)current[name] : spin.Minimum;
                    spin.Value = Math.Min(spin.Maximum, Math.Max(spin.Minimum, value));
                    IgnoreWheel(spin);
                    host.Controls.Add(NewRow(Humanise(name), spin));
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
            RefreshStatusAsync(null);
            FitToContent();
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

            perReasonPanel = new TableLayoutPanel();
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
            var row = new TableLayoutPanel();
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
            bool custom = styleGroup != null && styleGroup.Value == "custom";
            if (customCard != null && customCard.Visible != custom) customCard.Visible = custom;
            var mode = modeCombo == null ? null : modeCombo.SelectedItem as Choice;
            bool perReason = custom && mode != null && mode.Value == "per_reason";
            if (perReasonPanel != null && perReasonPanel.Visible != perReason) perReasonPanel.Visible = perReason;
        }

        private static string ComboJson(ComboBox combo)
        {
            var chosen = combo == null ? null : combo.SelectedItem as Choice;
            return chosen == null ? "null" : Json.Escape(chosen.Value);
        }

        /// The Preview follows what is on screen, a moment after it stops changing.
        private void SchedulePreview()
        {
            if (previewText == null) return;
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

        private void FitToContent()
        {
            // A settings window should show its settings. Grow to fit the tallest section,
            // and fall back to scrolling only when the screen genuinely cannot hold it.
            int tallest = 0;
            foreach (TableLayoutPanel stack in sections.Values)
                tallest = Math.Max(tallest, stack.PreferredSize.Height);
            int wanted = tallest + columns.Padding.Vertical + header.Height + footer.Height + nav.Height;
            Rectangle screen = Screen.FromControl(this).WorkingArea;
            int maximum = screen.Height - (Height - ClientSize.Height) - 80;
            // The width is scaled, so on a small screen at a large scaling factor the
            // window can be asked to be wider than the display. Widths are clamped to the
            // working area for the same reason heights are - a window whose controls sit
            // past the edge of the screen cannot be reached at all, where a scrollable one
            // can.
            int widest = screen.Width - (Width - ClientSize.Width);
            int across = Math.Min(ClientSize.Width, Math.Max(Px(340), widest));
            if (MinimumSize.Width > screen.Width)
                MinimumSize = new Size(Math.Max(Px(340), widest), MinimumSize.Height);
            ClientSize = new Size(across, Math.Max(Px(460), Math.Min(Math.Max(wanted, Px(640)), maximum)));
            Left = Math.Max(screen.Left, screen.Left + (screen.Width - Width) / 2);
            Top = Math.Max(screen.Top, screen.Top + (screen.Height - Height) / 2);
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
            if (snapshot == null)
                stateDot.State = running == null ? "idle" : !Equals(running, true) ? "attention"
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

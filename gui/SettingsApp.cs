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
//   * Two columns, because one column does not fit a laptop screen, and a settings
//     window that has to be scrolled to reveal settings is a poor settings window.
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
            if (!string.IsNullOrEmpty(argument)) arguments.Append(' ').Append(Quote(argument));
            info.Arguments = arguments.ToString();
            info.UseShellExecute = false;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.CreateNoWindow = true;
            info.StandardOutputEncoding = Encoding.UTF8;

            using (Process process = Process.Start(info))
            {
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
        private readonly TableLayoutPanel leftStack = new TableLayoutPanel();
        private readonly TableLayoutPanel rightStack = new TableLayoutPanel();
        // Buffered for the same reason as the status dot: both strips draw a hairline in a
        // Paint handler, and the header is invalidated on every status refresh. Unbuffered,
        // it was erased to white and repainted a moment later, and a capture taken in that
        // moment - one in four, measured - showed the header with no rule under it.
        private readonly Panel header = new BufferedPanel();
        private readonly Panel footer = new BufferedPanel();
        private readonly Label headline = new Label();
        private readonly Label detail = new Label();
        private readonly Label versionText = new Label();
        private Color dotColor = Idle;
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
                    strings = (Dictionary<string, object>)reply["strings"];
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
            ClientSize = new Size(Px(860), Px(600));
            // Wide enough that the two columns always hold their content. Allowing a
            // narrower window buys nothing: the labels start truncating mid-word, which
            // looks broken rather than compact.
            MinimumSize = new Size(Px(800), Px(420));
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
            columns.Dock = DockStyle.Fill;
            // FitToContent measures this page before ShowPage first parents it, and an
            // unparented control inherits Control.DefaultFont rather than the window's -
            // which measured the settings 40 pixels shorter than they are.
            columns.Font = Font;
            columns.BackColor = Canvas;
            columns.ColumnCount = 2;
            columns.RowCount = 1;
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            columns.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            columns.Padding = Pad(18, 18, 18, 4);
            columns.AutoScroll = true;

            foreach (TableLayoutPanel stack in new TableLayoutPanel[] { leftStack, rightStack })
            {
                stack.Dock = DockStyle.Top;
                stack.ColumnCount = 1;
                stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
                stack.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
                stack.AutoSize = true;
                stack.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                stack.BackColor = Canvas;
            }
            leftStack.Margin = Pad(0, 0, 9, 0);
            rightStack.Margin = Pad(9, 0, 0, 0);
            columns.Controls.Add(leftStack, 0, 0);
            columns.Controls.Add(rightStack, 1, 0);
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
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(22)));   // state dot
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what it is doing
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // the way out
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));
            grid.BackColor = Surface;

            // Drawn rather than a glyph so the dot stays round and vertically centred at
            // any scaling, and it carries the same state as the words beside it. It
            // spans both rows because it describes the pair, not the first line.
            var dot = new BufferedPanel();
            dot.Dock = DockStyle.Fill;
            dot.BackColor = Surface;
            dot.Paint += delegate(object sender, PaintEventArgs e)
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                int size = Px(12);
                using (var brush = new SolidBrush(dotColor))
                    e.Graphics.FillEllipse(brush, 0, (dot.Height - size) / 2, size, size);
            };

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
            var button = new Button();
            button.Text = text;
            button.AutoSize = true;
            button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            button.MinimumSize = new Size(Px(112), Px(32));
            button.Padding = Pad(10, 0, 10, 0);
            button.Margin = Pad(9, 0, 0, 0);
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 1;
            button.FlatAppearance.BorderColor = primary ? Accent : Line;
            button.BackColor = primary ? Accent : Surface;
            button.ForeColor = primary ? OnAccent : Ink;
            button.UseVisualStyleBackColor = false;
            button.Cursor = Cursors.Hand;
            button.Click += onClick;
            if (primary)
            {
                // A disabled flat button keeps its fill and greys only its text, which on the
                // accent reads as a live button with a rendering fault. So a primary button
                // that cannot be pressed looks like any other that cannot.
                button.EnabledChanged += delegate
                {
                    button.BackColor = button.Enabled ? Accent : Surface;
                    button.FlatAppearance.BorderColor = button.Enabled ? Accent : Line;
                    button.ForeColor = button.Enabled ? OnAccent : Muted;
                };
            }
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
            var card = new BufferedTable();
            card.Dock = DockStyle.Fill;
            card.ColumnCount = 1;
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            card.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            card.AutoSize = true;
            card.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            card.BackColor = Surface;
            card.Margin = Pad(0, 0, 0, 14);
            card.Padding = Pad(20, 15, 16, 16);
            card.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (var pen = new Pen(Line))
                    e.Graphics.DrawRectangle(pen, 0, 0, card.Width - 1, card.Height - 1);
                using (var brush = new SolidBrush(Accent))
                    e.Graphics.FillRectangle(brush, 1, 1, 3, card.Height - 2);
            };

            var heading = new Label();
            heading.Text = title;
            heading.AutoSize = true;
            heading.ForeColor = Ink;
            heading.Font = new Font(Font.FontFamily, Font.Size + 0.5f, FontStyle.Bold);
            heading.Margin = Pad(0, 0, 0, 10);
            card.Controls.Add(heading);
            return card;
        }

        private CheckBox NewCheck(string text, bool value)
        {
            var check = new CheckBox();
            check.Text = text;
            check.AutoSize = true;
            check.Margin = Pad(0, 5, 0, 5);
            check.Checked = value;
            check.Cursor = Cursors.Hand;
            return check;
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
            foreach (TableLayoutPanel stack in new TableLayoutPanel[] { leftStack, rightStack })
            {
                stack.Controls.Clear();
                stack.RowStyles.Clear();
            }
            editors.Clear();

            // Order is the argument the window makes: what may be recovered, then how
            // hard it will try, then what it will tell you, then when it starts. Reading
            // a two-column page means going down the left and then down the right, so
            // that is the order the cards are added in.
            //
            // The split is two cards each rather than one and three. One and three was
            // tried and looked unfinished: the left column ran out after six rows while
            // the right ran to fifteen, leaving a third of the window blank.
            TableLayoutPanel recovery = NewGroup(S("group.recovery", "Automatic recovery"), leftStack);
            TableLayoutPanel limits = NewGroup(S("group.limits", "Limits"), leftStack);
            TableLayoutPanel notifications = NewGroup(S("group.notifications", "Notifications"), rightStack);
            TableLayoutPanel windows = NewGroup(S("group.windows", "Windows"), rightStack);
            // First in its card, above the Windows preferences the schema adds.
            CheckBox startup = NewCheck(S("field.startup", "Run at Windows sign-in"), false);
            windows.Controls.Add(startup);
            editors["__startup"] = startup;

            foreach (object entry in schema)
            {
                var field = (Dictionary<string, object>)entry;
                string name = (string)field["name"];
                string group = field.ContainsKey("group") ? (string)field["group"] : "advanced";
                TableLayoutPanel host = group == "recovery" ? recovery
                                      : group == "limits" ? limits
                                      : group == "notifications" ? notifications
                                      : group == "windows" ? windows : null;
                if (host == null) continue;      // advanced fields stay out of the window

                string type = (string)field["type"];
                if (type == "boolean")
                {
                    bool value = current.ContainsKey(name) && Equals(current[name], true);
                    CheckBox check = NewCheck(Humanise(name), value);
                    if (field.ContainsKey("master") && Equals(field["master"], true))
                    {
                        // Built from the family rather than `new Font(check.Font, Bold)`:
                        // that overload can land on a substituted face and the row then
                        // renders in a different typeface from the rest of the window.
                        check.Font = new Font(Font.FontFamily, Font.Size, FontStyle.Bold);
                        check.Margin = Pad(0, 4, 0, 10);
                    }
                    else if (host == notifications)
                    {
                        check.Margin = Pad(16, 5, 0, 5);   // subordinate to the master
                    }
                    host.Controls.Add(check);
                    editors[name] = check;
                }
                else if (type == "integer")
                {
                    var spin = new NumericUpDown();
                    spin.Width = Px(74);
                    spin.BorderStyle = BorderStyle.FixedSingle;
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
                    var combo = new ComboBox();
                    combo.Width = Px(132);
                    combo.DropDownStyle = ComboBoxStyle.DropDownList;
                    // Displayed translated, stored untranslated. `Choice` keeps the two
                    // apart, so Save writes "normal" whatever the label says - a settings
                    // file that changes meaning with the display language would be a bug
                    // the user could not see until the watcher read it back.
                    var values = new List<string>();
                    foreach (object choice in (List<object>)field["choices"])
                    {
                        values.Add((string)choice);
                        combo.Items.Add(new Choice((string)choice,
                                                   S("choice." + (string)choice, (string)choice)));
                    }
                    string value = current.ContainsKey(name) ? current[name] as string : null;
                    combo.SelectedIndex = Math.Max(0, values.IndexOf(value));
                    IgnoreWheel(combo);
                    host.Controls.Add(NewRow(Humanise(name), combo));
                    editors[name] = combo;
                }
            }

            columns.ResumeLayout(true);
            RefreshStatusAsync(null);
            FitToContent();
        }

        private void FitToContent()
        {
            // A settings window should show its settings. Grow to fit both columns, and
            // fall back to scrolling only when the screen genuinely cannot hold them.
            int tallest = Math.Max(leftStack.PreferredSize.Height, rightStack.PreferredSize.Height);
            int wanted = tallest + columns.Padding.Vertical + header.Height + footer.Height + nav.Height;
            Rectangle screen = Screen.FromControl(this).WorkingArea;
            int maximum = screen.Height - (Height - ClientSize.Height) - 80;
            // The width is scaled, so on a small screen at a large scaling factor the
            // window can be asked to be wider than the display: 780 units at 250% is
            // 1950 pixels, and a 1920-wide laptop cannot show that. Widths are clamped to
            // the working area for the same reason heights are - a window whose controls
            // sit past the edge of the screen cannot be reached at all, where a scrollable
            // one can.
            int widest = screen.Width - (Width - ClientSize.Width);
            int across = Math.Min(ClientSize.Width, Math.Max(Px(340), widest));
            if (MinimumSize.Width > screen.Width)
                MinimumSize = new Size(Math.Max(Px(340), widest), MinimumSize.Height);
            ClientSize = new Size(across, Math.Max(Px(340), Math.Min(wanted, maximum)));
            Left = Math.Max(screen.Left, screen.Left + (screen.Width - Width) / 2);
            Top = Math.Max(screen.Top, screen.Top + (screen.Height - Height) / 2);
        }

        private void StatusUnavailable()
        {
            dotColor = Idle;
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

            dotColor = Equals(running, true) && enabled ? Active : Idle;
            headline.Text = running == null ? S("status.unknown", "Watcher status unknown")
                          : !Equals(running, true) ? S("status.not_running", "Watcher not running")
                          : enabled ? S("status.watching", "Watching for interruptions")
                          : S("status.paused", "Watching paused");
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
                        ? S("start.exited", "It started and stopped again - see logs in the installation folder")
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
            changes.Append('}');

            // The two writes on a worker, in order: the settings, then the sign-in entry.
            // Neither is started until the one before it has been answered, so a failure
            // stops the rest rather than reporting a save that half happened.
            var startup = editors.ContainsKey("__startup") ? editors["__startup"] as CheckBox : null;
            bool startAtSignIn = startup != null && startup.Checked;
            CallAsync("update", changes.ToString(), delegate(Dictionary<string, object> updated)
            {
                if (!Ok(updated)) { SaveFailed(updated); return; }
                CallAsync("startup", "{\"enabled\":" + (startAtSignIn ? "true" : "false") + "}",
                          delegate(Dictionary<string, object> registered)
                {
                    if (!Ok(registered)) { SaveFailed(registered); return; }
                    RefreshStatusAsync(delegate
                    {
                        detail.Text = S("settings.saved", "Saved - the watcher uses these from its next check");
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

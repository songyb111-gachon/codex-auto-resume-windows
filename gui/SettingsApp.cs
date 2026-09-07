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
//   * The status line is separate labels in separate cells, not one string. A single
//     label wraps or truncates as the window narrows, and the version - the part people
//     are asked for when reporting a problem - is exactly the part that disappears.
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
        internal static object Parse(string text)
        {
            int index = 0;
            return ParseValue(text, ref index);
        }

        private static void SkipWhitespace(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
        }

        private static object ParseValue(string s, ref int i)
        {
            SkipWhitespace(s, ref i);
            if (i >= s.Length) throw new FormatException("unexpected end of JSON");
            char c = s[i];
            if (c == '{') return ParseObject(s, ref i);
            if (c == '[') return ParseArray(s, ref i);
            if (c == '"') return ParseString(s, ref i);
            if (s.Length - i >= 4 && s.Substring(i, 4) == "true") { i += 4; return true; }
            if (s.Length - i >= 5 && s.Substring(i, 5) == "false") { i += 5; return false; }
            if (s.Length - i >= 4 && s.Substring(i, 4) == "null") { i += 4; return null; }
            return ParseNumber(s, ref i);
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i)
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
                result[key] = ParseValue(s, ref i);
                SkipWhitespace(s, ref i);
                if (s[i] == ',') { i++; continue; }
                if (s[i] == '}') { i++; return result; }
                throw new FormatException("expected , or }");
            }
        }

        private static List<object> ParseArray(string s, ref int i)
        {
            var result = new List<object>();
            i++;
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return result; }
            while (true)
            {
                result.Add(ParseValue(s, ref i));
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
        private static string Quote(string value)
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

    internal sealed class SettingsForm : Form
    {
        private static readonly Color Ink     = Color.FromArgb(0x1F, 0x24, 0x28);
        private static readonly Color Muted   = Color.FromArgb(0x5E, 0x69, 0x6E);
        private static readonly Color Line    = Color.FromArgb(0xE2, 0xE6, 0xE9);
        private static readonly Color Surface = Color.White;
        private static readonly Color Canvas  = Color.FromArgb(0xF5, 0xF6, 0xF7);
        private static readonly Color Accent  = Color.FromArgb(0x2F, 0x6F, 0x4E);
        private static readonly Color Good    = Color.FromArgb(0x2F, 0x8F, 0x5E);
        private static readonly Color Idle    = Color.FromArgb(0x9A, 0xA3, 0xA8);

        private readonly Bridge bridge;
        private readonly Dictionary<string, Control> editors = new Dictionary<string, Control>();

        private readonly TableLayoutPanel columns = new TableLayoutPanel();
        private readonly TableLayoutPanel leftStack = new TableLayoutPanel();
        private readonly TableLayoutPanel rightStack = new TableLayoutPanel();
        private readonly Panel statusStrip = new Panel();
        private readonly Panel footer = new Panel();
        private readonly Label statusText = new Label();
        private readonly Label versionText = new Label();
        private Color dotColor = Idle;

        internal SettingsForm(Bridge bridge)
        {
            this.bridge = bridge;
            Text = "Codex Auto Resume";
            Font = SystemFonts.MessageBoxFont;
            ForeColor = Ink;
            BackColor = Canvas;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Font;
            ClientSize = new Size(780, 560);
            // Wide enough that the two columns always hold their content. Allowing a
            // narrower window buys nothing: the labels start truncating mid-word, which
            // looks broken rather than compact.
            MinimumSize = new Size(800, 420);
            try
            {
                string icon = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "codex-auto-resume.ico");
                if (File.Exists(icon)) Icon = new Icon(icon);
            }
            catch (Exception) { /* an icon is decoration; never fail the window over it */ }

            BuildFooter();
            BuildStatus();
            BuildColumns();

            // The fill control is added first so the docked strips keep the bottom.
            Controls.Add(columns);
            Controls.Add(statusStrip);
            Controls.Add(footer);

            Load += delegate { Reload(); };
        }

        // ------------------------------------------------------------------- chrome
        private void BuildColumns()
        {
            columns.Dock = DockStyle.Fill;
            columns.BackColor = Canvas;
            columns.ColumnCount = 2;
            columns.RowCount = 1;
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            columns.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            columns.Padding = new Padding(18, 18, 18, 4);
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
            leftStack.Margin = new Padding(0, 0, 9, 0);
            rightStack.Margin = new Padding(9, 0, 0, 0);
            columns.Controls.Add(leftStack, 0, 0);
            columns.Controls.Add(rightStack, 1, 0);
        }

        private void BuildStatus()
        {
            statusStrip.Dock = DockStyle.Bottom;
            statusStrip.BackColor = Canvas;
            statusStrip.Padding = new Padding(22, 9, 22, 9);
            statusStrip.Height = TextRenderer.MeasureText("Ag", Font).Height + 20;

            var grid = new TableLayoutPanel();
            grid.Dock = DockStyle.Fill;
            grid.ColumnCount = 3;
            grid.RowCount = 1;
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 16f));   // state dot
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what it is doing
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // version
            // Without an explicit row the implicit one is AutoSize, and a Dock=Fill
            // child of an AutoSize row measures to nothing: the strip renders empty.
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            grid.BackColor = Canvas;

            // Drawn rather than a glyph so the dot stays round and vertically centred at
            // any scaling, and it carries the same state as the words beside it.
            var dot = new Panel();
            dot.Dock = DockStyle.Fill;
            dot.BackColor = Canvas;
            dot.Paint += delegate(object sender, PaintEventArgs e)
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                int size = 9;
                using (var brush = new SolidBrush(dotColor))
                    e.Graphics.FillEllipse(brush, 0, (dot.Height - size) / 2, size, size);
            };

            statusText.Dock = DockStyle.Fill;
            statusText.TextAlign = ContentAlignment.MiddleLeft;
            statusText.ForeColor = Muted;
            statusText.AutoEllipsis = true;   // narrow gracefully instead of wrapping
            statusText.Text = "Loading...";

            // Its own AutoSize column, so narrowing the window shortens the sentence on
            // the left and never takes the version away.
            versionText.AutoSize = true;
            versionText.Anchor = AnchorStyles.Right;
            versionText.TextAlign = ContentAlignment.MiddleRight;
            versionText.ForeColor = Idle;
            versionText.Margin = new Padding(14, 0, 0, 0);

            grid.Controls.Add(dot, 0, 0);
            grid.Controls.Add(statusText, 1, 0);
            grid.Controls.Add(versionText, 2, 0);
            statusStrip.Controls.Add(grid);
            statusStrip.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (var pen = new Pen(Line)) e.Graphics.DrawLine(pen, 0, 0, statusStrip.Width, 0);
            };
        }

        private void BuildFooter()
        {
            footer.Dock = DockStyle.Bottom;
            footer.BackColor = Surface;
            footer.Padding = new Padding(18, 13, 18, 15);
            footer.Height = TextRenderer.MeasureText("Ag", Font).Height + 46;

            var row = new FlowLayoutPanel();
            row.Dock = DockStyle.Fill;
            row.FlowDirection = FlowDirection.RightToLeft;
            row.WrapContents = false;
            row.BackColor = Surface;
            row.Controls.Add(MakeButton("Close", false, delegate { Close(); }));
            row.Controls.Add(MakeButton("Save", true, delegate { Save(); }));
            row.Controls.Add(MakeButton("Restore defaults", false, delegate { RestoreDefaults(); }));

            footer.Controls.Add(row);
            footer.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (var pen = new Pen(Line)) e.Graphics.DrawLine(pen, 0, 0, footer.Width, 0);
            };
        }

        private static Button MakeButton(string text, bool primary, EventHandler onClick)
        {
            var button = new Button();
            button.Text = text;
            button.AutoSize = true;
            button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            button.MinimumSize = new Size(112, 32);
            button.Padding = new Padding(10, 0, 10, 0);
            button.Margin = new Padding(9, 0, 0, 0);
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 1;
            button.FlatAppearance.BorderColor = primary ? Accent : Line;
            button.BackColor = primary ? Accent : Surface;
            button.ForeColor = primary ? Color.White : Ink;
            button.UseVisualStyleBackColor = false;
            button.Cursor = Cursors.Hand;
            button.Click += onClick;
            return button;
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
            // The card IS the layout panel rather than a Panel wrapping one. A Panel
            // measures AutoSize from anchored children only, so a docked AutoSize child
            // reports nothing: the panel keeps its default height and the last row of
            // every group is sliced off, bottom border and all.
            var card = new TableLayoutPanel();
            card.Dock = DockStyle.Fill;
            card.ColumnCount = 1;
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            card.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            card.AutoSize = true;
            card.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            card.BackColor = Surface;
            card.Margin = new Padding(0, 0, 0, 14);
            card.Padding = new Padding(20, 15, 16, 16);
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
            heading.Margin = new Padding(0, 0, 0, 10);
            card.Controls.Add(heading);

            stack.Controls.Add(card);
            stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            return card;
        }

        private static CheckBox NewCheck(string text, bool value)
        {
            var check = new CheckBox();
            check.Text = text;
            check.AutoSize = true;
            check.Margin = new Padding(0, 5, 0, 5);
            check.Checked = value;
            check.Cursor = Cursors.Hand;
            return check;
        }

        private static Control NewRow(string text, Control editor)
        {
            var row = new TableLayoutPanel();
            row.ColumnCount = 2;
            row.RowCount = 1;
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.Dock = DockStyle.Fill;
            row.Margin = new Padding(0, 6, 0, 6);
            row.BackColor = Color.Transparent;

            var label = new Label();
            label.Text = text;
            label.AutoSize = true;
            label.Anchor = AnchorStyles.Left;
            label.TextAlign = ContentAlignment.MiddleLeft;
            label.AutoEllipsis = true;
            label.Margin = new Padding(0, 5, 12, 0);

            editor.Anchor = AnchorStyles.Right;
            editor.Margin = new Padding(0);
            row.Controls.Add(label, 0, 0);
            row.Controls.Add(editor, 1, 0);
            return row;
        }

        private static string Humanise(string name)
        {
            string text = name;
            if (text.StartsWith("recover_")) text = text.Substring(8);
            else if (text.StartsWith("notify_")) text = text.Substring(7);
            text = text.Replace('_', ' ');
            var map = new Dictionary<string, string>();
            map["usage limit"] = "Usage limits";
            map["network transient"] = "Network failures";
            map["timeout"] = "Timeouts";
            map["rate limit transient"] = "Temporary rate limits";
            map["server 5xx"] = "Server errors";
            map["stream interrupted"] = "Stream interruptions";
            map["interruption"] = "Interruption detected";
            map["starting"] = "Recovery starting";
            map["result"] = "Recovery result";
            map["stopped"] = "Stopped or out of attempts";
            map["max recovery attempts"] = "Attempts per interruption";
            map["max no progress"] = "Stop after no progress";
            map["retry timing"] = "Retry timing";
            map["notifications"] = "Show notifications";
            if (map.ContainsKey(text)) return map[text];
            return char.ToUpper(text[0]) + text.Substring(1);
        }

        // ------------------------------------------------------------------ loading
        private void Reload()
        {
            List<object> schema;
            Dictionary<string, object> current;
            try
            {
                schema = (List<object>)bridge.Call("describe", null)["schema"];
                current = (Dictionary<string, object>)bridge.Call("settings", null)["settings"];
            }
            catch (Exception error)
            {
                statusText.Text = "Could not read the local settings: " + error.Message;
                return;
            }

            columns.SuspendLayout();
            foreach (TableLayoutPanel stack in new TableLayoutPanel[] { leftStack, rightStack })
            {
                stack.Controls.Clear();
                stack.RowStyles.Clear();
            }
            editors.Clear();

            // The long list goes on the left and the two short ones on the right, so the
            // columns end up close in height instead of one towering over the other.
            TableLayoutPanel recovery = NewGroup("Automatic recovery", leftStack);
            TableLayoutPanel windows = NewGroup("Windows", leftStack);
            TableLayoutPanel limits = NewGroup("Limits", rightStack);
            TableLayoutPanel notifications = NewGroup("Notifications", rightStack);

            foreach (object entry in schema)
            {
                var field = (Dictionary<string, object>)entry;
                string name = (string)field["name"];
                string group = field.ContainsKey("group") ? (string)field["group"] : "advanced";
                TableLayoutPanel host = group == "recovery" ? recovery
                                      : group == "limits" ? limits
                                      : group == "notifications" ? notifications : null;
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
                        check.Margin = new Padding(0, 4, 0, 10);
                    }
                    else if (host == notifications)
                    {
                        check.Margin = new Padding(16, 5, 0, 5);   // subordinate to the master
                    }
                    host.Controls.Add(check);
                    editors[name] = check;
                }
                else if (type == "integer")
                {
                    var spin = new NumericUpDown();
                    spin.Width = 74;
                    spin.BorderStyle = BorderStyle.FixedSingle;
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
                    combo.Width = 132;
                    combo.DropDownStyle = ComboBoxStyle.DropDownList;
                    foreach (object choice in (List<object>)field["choices"]) combo.Items.Add((string)choice);
                    string value = current.ContainsKey(name) ? current[name] as string : null;
                    combo.SelectedIndex = Math.Max(0, combo.Items.IndexOf(value));
                    IgnoreWheel(combo);
                    host.Controls.Add(NewRow(Humanise(name), combo));
                    editors[name] = combo;
                }
            }

            CheckBox startup = NewCheck("Run at Windows sign-in", false);
            windows.Controls.Add(startup);
            editors["__startup"] = startup;

            columns.ResumeLayout(true);
            RefreshStatus(startup);
            FitToContent();
        }

        private void FitToContent()
        {
            // A settings window should show its settings. Grow to fit both columns, and
            // fall back to scrolling only when the screen genuinely cannot hold them.
            int tallest = Math.Max(leftStack.PreferredSize.Height, rightStack.PreferredSize.Height);
            int wanted = tallest + columns.Padding.Vertical + statusStrip.Height + footer.Height;
            Rectangle screen = Screen.FromControl(this).WorkingArea;
            int maximum = screen.Height - (Height - ClientSize.Height) - 80;
            ClientSize = new Size(ClientSize.Width, Math.Max(340, Math.Min(wanted, maximum)));
            Top = Math.Max(screen.Top, screen.Top + (screen.Height - Height) / 2);
        }

        private void RefreshStatus(CheckBox startup)
        {
            try
            {
                var status = (Dictionary<string, object>)bridge.Call("status", null)["status"];
                object running = status["watcher_running"];
                bool enabled = Equals(status["enabled"], true);
                double pending = status.ContainsKey("pending") ? (double)status["pending"] : 0;
                if (startup != null) startup.Checked = Equals(status["startup_enabled"], true);

                dotColor = Equals(running, true) && enabled ? Good : Idle;
                string headline = running == null ? "Watcher status unknown"
                                : !Equals(running, true) ? "Watcher not running"
                                : enabled ? "Watching for interruptions"
                                : "Watching paused";
                int count = (int)pending;
                string tail = count == 0 ? "nothing pending"
                            : count == 1 ? "1 pending recovery"
                            : count.ToString(CultureInfo.InvariantCulture) + " pending recoveries";
                statusText.Text = headline + "   ·   " + tail;
                versionText.Text = "v" + status["version"];
            }
            catch (Exception)
            {
                dotColor = Idle;
                statusText.Text = "Status unavailable - settings can still be changed";
                // The version is deliberately left as it was: a failed status read is no
                // reason to drop the one field people are asked for when reporting a bug.
            }
            statusStrip.Invalidate(true);
        }

        // ------------------------------------------------------------------ actions
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
                else if (combo != null) changes.Append(Json.Escape(combo.SelectedItem as string));
            }
            changes.Append('}');

            try
            {
                var response = bridge.Call("update", changes.ToString());
                if (!Equals(response["ok"], true))
                    throw new InvalidOperationException((string)response["error"]);
                var startup = editors["__startup"] as CheckBox;
                bridge.Call("startup", "{\"enabled\":" + (startup.Checked ? "true" : "false") + "}");
                RefreshStatus(startup);
                statusText.Text = "Saved - the watcher uses these from its next check";
            }
            catch (Exception error)
            {
                MessageBox.Show(this, "Could not save." + Environment.NewLine + Environment.NewLine + error.Message,
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        private void RestoreDefaults()
        {
            if (MessageBox.Show(this, "Reset every setting to its recommended value?",
                                "Codex Auto Resume", MessageBoxButtons.YesNo,
                                MessageBoxIcon.Question) != DialogResult.Yes) return;
            try
            {
                bridge.Call("defaults", null);
                Reload();
            }
            catch (Exception error)
            {
                MessageBox.Show(this, "Could not restore defaults." + Environment.NewLine + Environment.NewLine + error.Message,
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
    }

    internal static class Program
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
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
            Application.Run(new SettingsForm(bridge));
            return 0;
        }
    }
}

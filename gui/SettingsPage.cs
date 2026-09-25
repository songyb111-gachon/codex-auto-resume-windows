// Codex Auto Resume - the Settings page: its cards, its rows, its editors, and Save.
//
// Every editor is built from the schema the watcher hands over, so a setting added there
// appears here without an edit. Continuation's own three - the style, the global message and
// the per-reason ones - are the exception, and are written out.

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
        /// The most lines the reopen note takes in the save card before it ends in an ellipsis.
        private const int NoteLines = 6;
        private const TextFormatFlags NoteFormat = TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl |
                                                   TextFormatFlags.NoPrefix;

        /// The width the reopen note's column is given: the save card's, less the version and `row`, the
        /// buttons, which are as wide as they ask - and the card is as wide as the window, less what the
        /// strip it fills keeps around it.
        ///
        /// From the window's own width, never from the card's, which is the width the card was last laid
        /// out at. The card's height is worked out when the note is shown, and a window that has just been
        /// made narrower has not always laid the card out at its new width by then: measured at the width
        /// the card still had, the note was given the room two lines of it need where four fit in the width
        /// it really gets. That is what the card came out two lines short of on the CI runner - Spanish,
        /// German and French from 150% up, in its fonts - while every window on the machine the layout was
        /// written on laid the card out first and measured the same note right (v0.6.4, measured: the audit
        /// holds the card to both orders now, AuditReopenNote).
        private int NoteWidth(Control row)
        {
            // What a card filling the strip is given: the width docked children are laid out in, less the
            // strip's padding. The strip is docked across the window, so nothing else takes from it.
            return DisplayRectangle.Width - footer.Padding.Horizontal - savebar.Padding.Horizontal
                 - (versionText.PreferredSize.Width + versionText.Margin.Horizontal)
                 - (row.PreferredSize.Width + row.Margin.Horizontal)
                 - reopenNote.Margin.Horizontal - reopenNote.Padding.Horizontal;
        }

        /// How tall the reopen note has to be to show all of it - up to NoteLines lines - in the width its
        /// column has (NoteWidth).
        private int NoteHeight(Control row)
        {
            int width = NoteWidth(row);
            if (width <= 0 || string.IsNullOrEmpty(reopenNote.Text)) return 0;
            // In the lines it is drawn in: Korean between its words (WrapLabel).
            int text = TextRenderer.MeasureText(reopenNote.Lines(width), reopenNote.Font, new Size(width, int.MaxValue), NoteFormat).Height;
            int line = TextRenderer.MeasureText("Ag", reopenNote.Font, new Size(int.MaxValue, int.MaxValue),
                                                TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix).Height;
            return Math.Min(text, NoteLines * line) + reopenNote.Padding.Vertical;
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
            // the way to a limit. The wheel belongs to the page, not to the editor, so the
            // turn is handed to the page (a turn marked handled goes no further by itself).
            control.MouseWheel += delegate(object sender, MouseEventArgs e)
            {
                var handled = e as HandledMouseEventArgs;
                if (handled != null) handled.Handled = true;
                Soft.PassWheel(sender as Control, e.Delta);
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

        private CheckBox NewCheck(string text, bool value, bool box)
        {
            var check = new SoftCheck();
            check.Box = box;
            check.Text = text;
            check.AutoSize = true;
            check.Margin = Pad(0, 3, 0, 3);
            check.Checked = value;
            return check;
        }

        private Label HelpText(string text)
        {
            // Korean broken between its words, as the popup and the panel break it (WrapLabel).
            var label = new WrapLabel();
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
            row.BackColor = Card;

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
            // Taken before the read, so a change made while it is on its way is looked at again.
            settingsStamp = SettingsStamp();
            CallAsync("describe", null, delegate(Dictionary<string, object> described)
            {
                if (!Ok(described)) { ReloadFailed(described); return; }
                CallAsync("settings", null, delegate(Dictionary<string, object> settings)
                {
                    if (!Ok(settings)) { ReloadFailed(settings); return; }
                    var schema = described["schema"] as List<object>;
                    var current = settings["settings"] as Dictionary<string, object>;
                    if (schema == null || current == null) { ReloadFailed(null); return; }
                    // The first read since the window opened confirms the language and theme it opened
                    // in; a later one - after Restore defaults - may have changed them.
                    bool first = !settingsRead;
                    settingsRead = true;
                    Observe(current, first);
                    // Not in a window that is reopening - and done after all if it stays (FinishReopen), or the
                    // page would go on showing what the settings were, and a Save would write that back.
                    HoldForReopen(delegate
                    {
                        AdoptSettings(current);
                        pendingSchema = schema;
                        pendingSettings = current;
                        if (currentPage == "settings") BuildPendingEditors();
                        else BuildEditorsLater();
                        // The keyboard where the window this one replaces had it, now that it is there.
                        FocusPending();
                    });
                });
            });
        }

        private void ReloadFailed(Dictionary<string, object> reply)
        {
            heroHeld = true;                // until the next read (ApplyStatus), not the next second (Hero)
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
            ForgetPins();
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
            // A switch: it turns something that runs on or off (see IsListItem).
            CheckBox startup = NewCheck(S("field.startup", "Run at Windows sign-in"), false, false);
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
                    // A check box for an item of a list, a switch for anything that runs (IsListItem).
                    CheckBox check = NewCheck(Humanise(name), Equals(Get(current, name), true), IsListItem(name));
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
                        // Subordinate to the master, its words starting where the master switch's do:
                        // 21 + a box of 18 + its gap of 10 is the switch's 40 + its gap of 9.
                        check.Margin = Pad(21, 2, 0, 2);
                        subordinate.Add(check);
                    }
                    host.Controls.Add(check);
                    editors[name] = check;
                    if (name == "reduce_motion")
                        host.Controls.Add(HelpText(S("help.reduce_motion",
                            "Stops the breathing and pulsing status animations in this window and the notification-area popup. Windows' own Animation effects setting is always honored as well.")));
                    // When the card gives way to Windows' own notification - Do not disturb, full screen, a screen
                    // reader, a locked or remote session - is said under its switch, never left to be found out.
                    if (name == "notification_card")
                        host.Controls.Add(HelpText(S("help.notification_card",
                            "Notifications appear as a card beside the notification area and are also kept in Windows' notification center. When this is off - or while Do not disturb is on, an app is full screen, a screen reader is running, or the session is locked or remote - Windows shows its own notification instead.")));
                    // v0.6.9: when the watcher starts, said under its switch - beside sign-in, not instead of it.
                    if (name == "start_with_codex")
                        host.Controls.Add(HelpText(S("help.start_with_codex",
                            "Codex starts this plugin whenever it opens, and the watcher starts with it if it is not already running. This is separate from starting at sign-in: either or both can be on. It changes nothing about what is recovered.")));
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
                    // Each theme's labels are its own: the Theme's "Use system setting", the panel
                    // theme's "Same as Theme" and "Codex's theme", and both themes' Light and Dark.
                    bool themed = name == "theme" || name == "panel_theme";
                    SoftCombo combo = ChoiceCombo(field, current, themed ? "choice." + name + "." : "choice.");
                    host.Controls.Add(NewRow(Humanise(name), combo));
                    editors[name] = combo;
                    if (name == "theme")
                        host.Controls.Add(HelpText(S("help.theme",
                            "Light or dark for this window, the notification-area popup and the notification card, and for the panel in Codex while Theme in Codex is Same as Theme. Use system setting follows Windows here and Codex's own theme in Codex.")));
                    if (name == "panel_theme")
                        host.Controls.Add(HelpText(S("help.panel_theme",
                            "Light or dark for the panel in Codex alone. Same as Theme uses the choice above; Codex's theme follows Codex whatever the Theme is.")));
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
            // What unsaved edits are measured from: the page as it was built.
            baseline = EditorValues();
            CheckBox startupCheck = editors.ContainsKey("__startup") ? editors["__startup"] as CheckBox : null;
            startupBaseline = startupCheck != null && startupCheck.Checked;
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
            perReasonPanel.BackColor = Card;
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
            IgnoreWheel(combo);
            string name = Str(field, "name");
            List<object> choices = Items(field, "choices") ?? new List<object>();
            string value = name == null ? null : Str(current, name);
            int index = 0, widest = 0;
            foreach (object choice in choices)
            {
                string text = Convert.ToString(choice, CultureInfo.InvariantCulture);
                string label = S(prefix + text, text);
                if (text == value) index = combo.Items.Count;
                combo.Items.Add(new Choice(text, label));
                widest = Math.Max(widest, TextRenderer.MeasureText(label, Font).Width);
            }
            // As wide as its longest choice in the well's padding, beside the chevron: "Use system
            // setting" is longer than any choice a drop-down here had before, in every language.
            combo.Width = Math.Max(Px(150), Math.Min(Px(300), widest + Px(Brand.SelectPadLeft + Brand.SelectPadRight + 4)));
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
            row.BackColor = Card;
            count.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            Button clear = MakeButton(S("custom.clear", "Clear"), false, delegate { area.Box.Clear(); area.Box.Focus(); });
            clear.MinimumSize = new Size(Px(88), Px(34));
            // At the bottom right of its row, as every button at the right of a row is (v0.6.4). The
            // count beside it is one line, shorter than the button, so the row is the button's height.
            clear.Anchor = AnchorStyles.Right | AnchorStyles.Bottom;
            clear.Margin = new Padding(0);
            Pinned(clear, row);
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
            // Held until the next read (ApplyStatus): the clock's Hero would otherwise put an older snapshot's
            // word back within a second, beside words that say the state cannot be read.
            heroHeld = true;
            stateDot.State = "idle";
            TellTaskbar(null, null, 0);
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
            if (startup != null)
            {
                startup.Checked = Equals(status["startup_enabled"], true);
                // What Windows has is not an edit.
                startupBaseline = startup.Checked;
            }

            // The header (Hero). A read rewrites it, as it always has, over a note or a hold written since the
            // last one. From the status alone until the Dashboard has a snapshot, and from a status read after
            // it (Start watcher, a save), which is newer, until the next one; otherwise UpdateCountdowns is the
            // one place it is decided, from the pending list as well - recovering, due to be checked. Deciding it
            // here too put the coarse state and then the refined one on the dot in the same refresh, and every
            // change restarts the halo: an alarm pulsed again every five seconds, and an arc jumped to its start.
            heroHeld = false;
            heroHead = heroDetail = null;
            heroStatus = snapshot != null && ReferenceEquals(status, Map(snapshot, "status")) ? null : status;
            if (heroStatus != null) Hero(status, null, Now());
            // The taskbar button likewise, by the notification-area icon's rule (TrayActivity).
            if (snapshot == null) TellTaskbar(status, null, Now());
            versionText.Text = "v" + status["version"];
            if (startButton != null) startButton.Visible = Equals(running, false);
            header.Invalidate(true);
        }

        // The header as Hero last wrote it, and what decides it (ApplyStatus).
        private string heroHead, heroDetail;
        private Dictionary<string, object> heroStatus;
        private bool heroHeld;

        /// The header's light, word and facts, set together from one reading (v0.6.10). Until v0.6.10 the dot came
        /// from Activity and the headline from the status alone, set in two places, so the two could disagree, and
        /// the window said in its own words - "Watching for interruptions", "Watcher not running" - what the panel
        /// and the popup said in theirs. Now the word is the one rule every header keeps (ActivityWord), in the
        /// catalog's activity.<word>, the light is its light (HeaderLight: grey for a watcher not known to be
        /// running, beside the word that asks for attention), and the facts under it are the panel's (HeroFacts).
        ///
        /// Called every second by UpdateCountdowns, so it writes only what changed: a note written under the
        /// headline since the last read ("Saved.", "It started and stopped again") stays until the next read
        /// rewrites it, as it always did, and a hold (heroHeld: status unavailable, starting the watcher, settings
        /// that could not be read) keeps the whole header until then.
        private void Hero(Dictionary<string, object> status, List<object> pending, double now)
        {
            if (heroHeld) return;
            string word = ActivityWord(status, pending, now);
            stateDot.State = HeaderLight(status, pending, word);
            string head = S("activity." + word, word);
            string facts = string.Join("   ·   ", HeroFacts(strings, status, pending, word).ToArray());
            if (head == heroHead && facts == heroDetail) return;
            if (head != heroHead) headline.Text = heroHead = head;
            if (facts != heroDetail) detail.Text = heroDetail = facts;
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
            heroHeld = true;                // until the answer is read (ApplyStatus)
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
                Tell(S("start.failed", "Could not start the watcher.") + Environment.NewLine +
                     Environment.NewLine + error.Message);
            }
            startButton.Enabled = true;
        }

        private void Save()
        {
            Dictionary<string, string> values = EditorValues();
            string changes = ChangesJson(values);
            // Where the keyboard is - on Save, as a rule - before the save takes the buttons away while it runs
            // and Windows moves the keyboard on: where a window this save reopens puts it again.
            string focus = FocusName();

            var chosenLanguage = interfaceCombo == null ? null : interfaceCombo.SelectedItem as Choice;
            string language = chosenLanguage == null ? loadedInterfaceLanguage : chosenLanguage.Value;
            bool languageChanged = language != loadedInterfaceLanguage;
            var motion = editors.ContainsKey("reduce_motion") ? editors["reduce_motion"] as CheckBox : null;

            // The two writes on a worker, in order: the settings, then the sign-in entry.
            // Neither is started until the one before it has been answered, so a failure
            // stops the rest rather than reporting a save that half happened.
            var startup = editors.ContainsKey("__startup") ? editors["__startup"] as CheckBox : null;
            bool startAtSignIn = startup != null && startup.Checked;
            CallAsync("update", changes, delegate(Dictionary<string, object> updated)
            {
                if (!Ok(updated)) { SaveFailed(updated); return; }
                // What is on the page is what is saved, so nothing is left unsaved.
                baseline = values;
                var stored = Map(updated, "settings");
                if (stored != null)
                {
                    AdoptSettings(stored);
                    Remember(stored);
                }
                else
                {
                    loadedInterfaceLanguage = language;
                    if (motion != null)
                    {
                        Soft.ReduceMotionSetting = motion.Checked;
                        stateDot.Sync();
                    }
                }
                // This window's own write is not a change made somewhere else.
                settingsStamp = SettingsStamp();
                CallAsync("startup", "{\"enabled\":" + (startAtSignIn ? "true" : "false") + "}",
                          delegate(Dictionary<string, object> registered)
                {
                    if (!Ok(registered)) { SaveFailed(registered); return; }
                    startupBaseline = startAtSignIn;
                    // A new Interface language or theme: the window reopens in it, where it is.
                    reopenFocus = focus;
                    CheckReopen(false);
                    reopenFocus = null;
                    // Said by this window only if it stays.
                    HoldForReopen(delegate
                    {
                        RefreshStatusAsync(delegate
                        {
                            // A new interface language this window could not reopen in reaches it the next
                            // time it opens; saying so is better than a window that half changes.
                            detail.Text = languageChanged
                                ? S("settings.language_changed", "Language changed. Anything already open changes the next time it opens.")
                                : S("settings.saved", "Saved. The watcher uses these from its next check.");
                            header.Invalidate(true);
                        });
                    });
                });
            });
        }

        private void SaveFailed(Dictionary<string, object> reply)
        {
            Tell(S("settings.save_failed", "Could not save.") + Environment.NewLine + Environment.NewLine +
                 Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture));
        }

        private void RestoreDefaults()
        {
            if (!Confirm(S("settings.confirm_restore", "Reset every setting to its recommended value?"),
                         S("action.restore", "Restore defaults"))) return;
            CallAsync("defaults", null, delegate(Dictionary<string, object> reply)
            {
                if (Ok(reply)) { Reload(); return; }
                Tell(S("settings.restore_failed", "Could not restore defaults.") + Environment.NewLine +
                     Environment.NewLine + Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture));
            });
        }
    }
}

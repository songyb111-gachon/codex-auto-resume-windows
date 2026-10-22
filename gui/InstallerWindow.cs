// Codex Auto Resume - the installer window: a setup program's wizard, the Dashboard's update and the uninstall
// Add or remove programs runs, in the product's own material.
//
// One window, in the Dashboard's design - its cards on its ground, its buttons, switches and boxes, its light,
// its colours, type, corners and depth (Palette, Soft, the [controls]) - and none of its own. What it asks and
// what each answer becomes are InstallerFlow's; it only shows them and runs the installer the way it is given
// (Runner), on a worker, reading each line the installer prints for the bar, the step and the log.
//
// The layout is worked out here, not by a table: every page is a column of rows, each as tall as its words need
// at the card's width (Arrange), and the window as tall as its tallest page needs, so no page scrolls or cuts
// anything off in any language at any text size (build/setup/SetupWindow.cs audits it; tests/test_installer_window.py
// runs that audit in every language at every scaling and text size).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed class InstallerWindow : Form
    {
        /// Runs the installer: on a worker thread, telling `line` each line it prints and `unpacked` how far a setup
        /// program's own unpacking is (0 to 1); returns its exit code, or InstallerFlow.StillRunning or NotStarted.
        internal delegate int Runner(InstallerFlow flow, Action<string> line, Action<double> unpacked);

        /// The words in another language, for the language picker; null where the window speaks one language only.
        internal delegate InstallerWords Speaker(string language);

        internal const int OpeningWidth = 600;

        private readonly InstallerFlow flow;
        private readonly Runner runner;
        private readonly Speaker speaker;
        private readonly IEnumerable<string> given;
        private readonly Font baseFont;
        private InstallerWords words;

        private readonly Panel ground = new InstallerSheet(false);
        private readonly SoftCard header = new SoftCard();
        private readonly SoftCard body = new SoftCard();
        private readonly InstallerSheet sheet = new InstallerSheet(true);
        private readonly HaloDot light = new HaloDot();
        private readonly Label title = new Label();
        private readonly VersionLabel version = new VersionLabel();
        private readonly SoftButton forward = new SoftButton(true);
        private readonly SoftButton back = new SoftButton(false);
        private readonly SoftButton cancel = new SoftButton(false);
        private readonly InstallerBar bar = new InstallerBar();
        private readonly SoftTextArea logArea = new SoftTextArea();
        // What is new in the version an update goes to (v0.6.16): the Notes page, and an update's Options page.
        private readonly SoftTextArea notesArea = new SoftTextArea();
        // The Notes page's answer, which the run waits for on its worker (Ask).
        private readonly System.Threading.ManualResetEvent answered = new System.Threading.ManualResetEvent(false);
        private bool go;
        private readonly StringBuilder log = new StringBuilder();
        private readonly List<KeyValuePair<Control, int>> rows = new List<KeyValuePair<Control, int>>();

        private string page;
        private bool running, logShown, unconfirmed, previousRunning, closingAsked;
        // The installer opened again the Dashboard that was open before it (install.ps1): there is none to offer.
        private bool reopened;
        // Which buttons the page has. Kept here, not read back from Visible: a control answers false there until its
        // window is on screen, and the window is measured and audited before it is (Fit, InstallerAudit).
        private bool backShown, cancelShown, forwardShown;
        private int code = int.MinValue;
        // Where the work is (at), and the place of the milestone that began the step under way (reached), which a
        // progress line's share is measured from (InstallerProgress.Within).
        private double at, reached;
        private string step = "starting";
        private WrapLabel stepLabel, busyNote;

        /// The exit code of the run, or int.MinValue where none ran (the window was closed before it started).
        internal int Code { get { return code; } }

        /// Whether the person left "Open the Dashboard" on, for a run that succeeded.
        /// An update opens the new Dashboard by itself: the Dashboard it was started from ran before it (v0.6.16).
        internal bool OpenDashboard
        {
            get
            {
                return code == 0 && flow.Mode != InstallerFlow.Uninstall && !reopened &&
                       (flow.Mode == InstallerFlow.Update || flow.OpenDashboard);
            }
        }

        internal InstallerFlow Flow { get { return flow; } }

        /// The whole log, as the installer printed it.
        internal string Log { get { return log.ToString(); } }

        internal InstallerWindow(InstallerFlow flow, InstallerWords words, Speaker speaker, Runner runner,
                                 IEnumerable<string> given, Font font)
        {
            this.flow = flow;
            this.words = words;
            this.speaker = speaker;
            this.runner = runner;
            this.given = given;
            baseFont = font ?? SystemFonts.MessageBoxFont;
            Text = "Codex Auto Resume";
            BackColor = Palette.Canvas;
            ForeColor = Palette.Ink;
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.None;
            Soft.TitleBar(this);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch (Exception) { /* the window's own default icon */ }

            ground.Dock = DockStyle.Fill;
            Controls.Add(ground);
            foreach (SoftCard card in new[] { header, body })
            {
                card.ColumnCount = 1;
                card.RowCount = 1;
                card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
                card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
                card.Padding = Pad(16, 16, 16, 16);
                ground.Controls.Add(card);
            }
            var head = new InstallerSheet(true);
            head.Dock = DockStyle.Fill;
            head.Margin = new Padding(0);
            header.Controls.Add(head, 0, 0);
            // The light spans the two lines it describes, in its own column, as the Dashboard's header has it.
            light.BackColor = Palette.Card;
            light.AccessibleName = "Codex Auto Resume";
            title.Text = "Codex Auto Resume";
            title.ForeColor = Palette.Ink;
            title.BackColor = Palette.Card;
            title.UseMnemonic = false;
            version.ForeColor = Palette.Secondary;
            version.BackColor = Palette.Card;
            head.Controls.Add(light);
            head.Controls.Add(title);
            head.Controls.Add(version);
            head.Layout += delegate { ArrangeHeader(head); };

            sheet.Dock = DockStyle.Fill;
            sheet.Margin = new Padding(0);
            body.Controls.Add(sheet, 0, 0);

            back.Click += delegate { Go(-1); };
            forward.Click += delegate { Forward(); };
            cancel.Click += delegate { if (page == InstallerFlow.Notes) Answer(false); else Close(); };
            foreach (SoftButton button in new[] { cancel, back, forward })
            {
                button.AutoSize = true;
                button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                button.MinimumSize = new Size(Soft.Px(112), Soft.Px(Brand.ButtonHeight));
                button.Padding = Pad(Brand.ButtonPadLeft, 0, Brand.ButtonPadRight, 0);
                ground.Controls.Add(button);
            }
            AcceptButton = forward;

            // Word-wrapped, with the well's own scroll bar (SoftTextArea) and no other: a horizontal bar is Windows'
            // own, white on a dark window, never the product's (v0.6.16 acceptance, the owner: "not our design").
            logArea.Box.ReadOnly = true;
            notesArea.Box.ReadOnly = true;
            notesArea.Box.WordWrap = true;

            Adopt(words);
            page = flow.Pages()[0];
            ShowPage(page);
            if (flow.Mode == InstallerFlow.Update) Shown += delegate { Start(); };
        }

        private static int Px(int atNinetySix) { return Soft.Px(atNinetySix); }

        private static Padding Pad(int left, int top, int right, int bottom)
        {
            return new Padding(Px(left), Px(top), Px(right), Px(bottom));
        }

        // ------------------------------------------------------------------ words and size

        /// Speaks `next` from here on: its words, the face its letters need (Typeface.For) and a window as tall as
        /// its tallest page.
        private void Adopt(InstallerWords next)
        {
            words = next;
            Font = Typeface.ForLanguage(baseFont, words.Catalog, words.Language);
            Soft.BaseFont = Font;
            title.Font = Soft.RoleFont("display");
            version.Font = Font;
            version.Set(string.IsNullOrEmpty(flow.Version) ? "" : "v" + flow.Version, words.EditionWord(flow.Edition));
            logArea.Font = Font;
            logArea.Box.Font = Font;
            notesArea.Font = Font;
            notesArea.Box.Font = Font;
            notesArea.Box.AccessibleName = words.Say("installer.update.whats_new", "What's new");
            logArea.Box.AccessibleName = words.Say("installer.log.name", "Log");
            cancel.Text = words.Say("action.cancel", "Cancel");
            back.Text = words.Say("installer.back", "Back");
            Fit();
        }

        /// The window's size: Width wide, and as tall as the tallest of its pages needs at that width.
        private void Fit()
        {
            int width = Px(OpeningWidth);
            int inner = Inner(width);
            int tallest = 0;
            string showing = page;
            foreach (string each in flow.Pages())
            {
                // Each page measured as it is shown: what a page holds can depend on which page is showing (WhatsNew,
                // and the notes' own height on the Notes page).
                page = each;
                Build(each);
                tallest = Math.Max(tallest, Arrange(inner));
            }
            page = showing;
            ClientSize = new Size(width, Px(16) + HeaderHeight() + Px(16) + tallest + Px(32) + Px(16) +
                                         Px(Brand.ButtonHeight) + Px(16));
            if (showing != null) ShowPage(showing);
        }

        private static int Inner(int width) { return width - Px(16) * 2 - Px(16) * 2; }

        private int HeaderHeight()
        {
            int lines = LineHeight(title) + LineHeight(version) + Px(2);
            return Math.Max(lines, Px(28)) + Px(32);
        }

        // One line of a header label, as GDI draws it: Font.Height is short of that by a pixel at larger sizes.
        private static int LineHeight(Label line)
        {
            return Math.Max(line.Font.Height, TextRenderer.MeasureText(string.IsNullOrEmpty(line.Text) ? "Ag" : line.Text,
                                                                       line.Font, new Size(int.MaxValue, 0),
                                                                       TextFormatFlags.NoPrefix).Height);
        }

        private void ArrangeHeader(Control head)
        {
            int column = Math.Max(Px(28), 2 * HaloDot.Extent + Px(12));
            int lineOne = LineHeight(title), lineTwo = LineHeight(version) + Px(2);
            int top = Math.Max(0, (head.Height - lineOne - lineTwo) / 2);
            light.SetBounds(0, 0, column, head.Height);
            title.SetBounds(column + Px(8), top, Math.Max(1, head.Width - column - Px(8)), lineOne);
            version.SetBounds(column + Px(8), top + lineOne + Px(2), Math.Max(1, head.Width - column - Px(8)), lineTwo - Px(2));
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int width = ClientSize.Width, pad = Px(16);
            int headerHeight = HeaderHeight();
            header.SetBounds(pad, pad, width - 2 * pad, headerHeight);
            int buttonsTop = ClientSize.Height - pad - Px(Brand.ButtonHeight);
            body.SetBounds(pad, pad + headerHeight + pad, width - 2 * pad, Math.Max(1, buttonsTop - pad - (pad + headerHeight + pad)));
            int right = width - pad;
            foreach (SoftButton button in new[] { forward, back, cancel })
            {
                if (!Has(button)) continue;
                Size size = button.GetPreferredSize(Size.Empty);
                size = new Size(Math.Max(size.Width, button.MinimumSize.Width), Math.Max(size.Height, button.MinimumSize.Height));
                button.SetBounds(right - size.Width, buttonsTop, size.Width, size.Height);
                right -= size.Width + Px(9);
            }
        }

        // ------------------------------------------------------------------ pages

        private void Go(int by)
        {
            string[] pages = flow.Pages();
            int index = Array.IndexOf(pages, page) + by;
            if (index < 0 || index >= pages.Length) return;
            ShowPage(pages[index]);
        }

        private void Forward()
        {
            if (page == InstallerFlow.Finish) { Close(); return; }
            if (page == InstallerFlow.Notes) { Answer(true); return; }
            // Repair starts here; Remove goes on to the uninstall's question.
            if (page == InstallerFlow.Maintain && flow.Mode != InstallerFlow.Uninstall) { Start(); return; }
            if (page == InstallerFlow.Options || page == InstallerFlow.Confirm) { Start(); return; }
            Go(1);
        }

        internal string Page { get { return page; } }

        /// Builds `name` and shows it, with the buttons it has.
        internal void ShowPage(string name)
        {
            page = name;
            Build(name);
            Arrange(Inner(ClientSize.Width > 0 ? ClientSize.Width : Px(OpeningWidth)));
            string[] pages = flow.Pages();
            int index = Array.IndexOf(pages, name);
            back.Visible = backShown = index > 0 && name != InstallerFlow.Progress && name != InstallerFlow.Finish &&
                                      name != InstallerFlow.Notes;
            cancel.Visible = cancelShown = name != InstallerFlow.Finish;
            cancel.Enabled = name != InstallerFlow.Progress;
            forward.Visible = forwardShown = name != InstallerFlow.Progress;
            forward.Enabled = name != InstallerFlow.Options || flow.CanStart();
            cancel.Text = name == InstallerFlow.Notes ? words.Say("action.not_now", "Not now")
                        : words.Say("action.cancel", "Cancel");
            forward.Text = name == InstallerFlow.Finish && flow.Mode == InstallerFlow.Update && code == 0
                           ? words.Say("installer.done.open", "Open the Dashboard")
                         : name == InstallerFlow.Notes ? words.Say("installer.update", "Update")
                         : name == InstallerFlow.Finish ? words.Say("installer.finish", "Finish")
                         : name == InstallerFlow.Confirm ? words.Say("installer.remove", "Remove")
                         : name == InstallerFlow.Maintain ? (flow.Mode == InstallerFlow.Uninstall
                                                             ? words.Say("installer.next", "Next")
                                                             : words.Say("installer.maintain.repair", "Repair"))
                         : name == InstallerFlow.Options ? (flow.Upgrade && !flow.EditionChange
                                                            ? words.Say("installer.update", "Update")
                                                            : words.Say("action.install", "Install"))
                         : words.Say("installer.next", "Next");
            light.State = InstallerFlow.Light(flow.Mode, name, code, unconfirmed, previousRunning);
            PerformLayout();
            if (forwardShown && forward.Enabled) ActiveControl = forward;
        }

        private void Build(string name)
        {
            sheet.SuspendLayout();
            sheet.Controls.Clear();
            rows.Clear();
            stepLabel = null;
            busyNote = null;
            // Not a seventh case: a string switch that long is compiled to a class named at random (build/normalize_pe.py).
            if (name == InstallerFlow.Maintain) BuildMaintain();
            else switch (name)
            {
                case InstallerFlow.Welcome: BuildWelcome(); break;
                case InstallerFlow.Options: BuildOptions(); break;
                case InstallerFlow.Confirm: BuildConfirm(); break;
                case InstallerFlow.Progress: BuildProgress(); break;
                case InstallerFlow.Notes: BuildNotes(); break;
                default: BuildFinish(); break;
            }
            foreach (KeyValuePair<Control, int> row in rows) sheet.Controls.Add(row.Key);
            sheet.ResumeLayout(false);
        }

        private void Row(Control control, int gap)
        {
            rows.Add(new KeyValuePair<Control, int>(control, Px(gap)));
        }

        private WrapLabel Words(string text, string role, Color ink)
        {
            var label = new WrapLabel();
            label.Text = text ?? "";
            label.UseMnemonic = false;
            label.ForeColor = ink;
            label.BackColor = Palette.Card;
            label.Font = role == null ? Font : Soft.RoleFont(role);
            return label;
        }

        private SoftCheck Choice(string text, bool on, bool box, Action<bool> changed)
        {
            var check = new SoftCheck();
            check.Box = box;
            check.Wraps = true;
            check.Text = text;
            check.Checked = on;
            check.Font = Font;
            check.ForeColor = Palette.Ink;
            check.BackColor = Palette.Card;
            check.UseMnemonic = false;
            check.CheckedChanged += delegate { changed(check.Checked); };
            return check;
        }

        private void BuildWelcome()
        {
            Row(Words(words.Say("installer.welcome.heading", "Welcome"), "title", Palette.Ink), 0);
            Row(Words(words.Say("installer.welcome.what", "When a Codex conversation stops at a usage limit or a dropped connection, Codex Auto Resume carries it on by itself once it can."), null, Palette.Ink), 8);
            var guide = new LinkLabel();
            guide.Text = words.Say("installer.welcome.guide", "Read the guide");
            guide.UseMnemonic = false;
            guide.AutoSize = false;
            guide.BackColor = Palette.Card;
            guide.LinkColor = Palette.Accent;
            guide.ActiveLinkColor = Palette.AccentPressed;
            guide.VisitedLinkColor = Palette.Accent;
            guide.Font = Font;
            guide.LinkClicked += delegate { OpenGuide(); };
            Row(guide, 8);
            if (speaker == null) return;
            Row(Words(words.Say("installer.language", "Language"), "label", Palette.Secondary), 20);
            var picker = new SoftCombo();
            picker.Font = Font;
            picker.AccessibleName = words.Say("installer.language", "Language");
            foreach (string locale in InstallerLanguages.Offered())
            {
                int index = picker.Items.Add(new LanguageItem(locale));
                if (locale == words.Language) picker.SelectedIndex = index;
            }
            picker.SelectedIndexChanged += delegate
            {
                var item = picker.SelectedItem as LanguageItem;
                if (item == null || item.Locale == words.Language) return;
                InstallerWords next = speaker(item.Locale);
                if (next != null) BeginInvoke((MethodInvoker)delegate { Adopt(next); });
            };
            Row(picker, 6);
        }

        /// The guide, in the person's browser: a link they follow, not a request this program makes.
        internal const string Guide = "https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/GUIDE.md";

        private static void OpenGuide()
        {
            try
            {
                var start = new ProcessStartInfo(Guide);
                start.UseShellExecute = true;
                Process.Start(start);
            }
            catch (Exception) { /* no browser: nothing to open it in */ }
        }

        private void BuildOptions()
        {
            Row(Words(words.Say("installer.options.heading", "Before it installs"), "title", Palette.Ink), 0);
            Row(Words(words.Say("installer.options.location", "Installed in"), "label", Palette.Secondary), 8);
            Row(Words(flow.Home, null, Palette.Ink), 2);
            if (flow.EditionChange)
            {
                string from = words.EditionWord(flow.Installed), to = words.EditionWord(flow.Edition);
                string change = words.Say("installer.options.edition_change", "The {from} edition is installed here, and this is the {to} edition.",
                                          "from", from, "to", to) + " " +
                                (flow.Edition == InstallerFlow.Advanced
                                 ? words.Say("installer.options.to_advanced", "Changing it keeps the settings and pending recoveries; every advanced feature starts off.")
                                 : words.Say("installer.options.to_standard", "Changing it keeps the settings and pending recoveries; the advanced features go, and their code with them."));
                Row(new SoftCallout(change), 16);
                Row(Choice(words.Say("installer.options.edition_confirm", "Change the edition"), flow.ChangeEdition, true,
                           delegate(bool on) { flow.ChangeEdition = on; forward.Enabled = flow.CanStart(); }), 10);
            }
            else if (flow.Upgrade)
                Row(Words(words.Say("installer.options.kept", "This updates the installation here. Your settings, everything waiting and your sign-in choice are kept."), null, Palette.Ink), 16);
            if (!flow.Upgrade)
                Row(Choice(words.Say("field.startup", "Run at Windows sign-in"), flow.StartAtSignIn, false,
                           delegate(bool on) { flow.StartAtSignIn = on; }), 16);
            Row(Words(words.Say("installer.options.plugin", "The plugin - its panel and its skill - is added to Codex as part of every installation."), null, Palette.Secondary), 16);
            // An update says what it updates to, as the Dashboard's does (BuildNotes).
            if (flow.Upgrade && !flow.EditionChange && flow.NotesText != null) WhatsNew(16);
            InsideNote(16);
        }

        /// v0.6.17: a setup program that could not get out of another app's private view of Windows
        /// (HostApp.StuckInside) says, before it installs or removes anything, what Windows would keep inside that app.
        private void InsideNote(int gap)
        {
            if (HostApp.StuckInside == null) return;
            Row(new SoftCallout(words.Say("installer.inside_app",
                "This may have been started from inside {app}. If so, Windows would keep what it sets up or removes inside that app: the entry in Settings > Apps, the start at sign-in, the notifications' name, the link handler and the Start menu entry. If Settings > Apps lacks the entry afterwards, open the Dashboard from the Start menu and choose Repair installation.",
                "app", HostApp.Name(HostApp.StuckInside))), gap);
        }

        /// A setup program over its own version, installed already (v0.6.16, the owner): Repair - install it again in
        /// place, everything kept - or Remove, which goes on to the uninstall's own question. Repair is the default.
        private void BuildMaintain()
        {
            Row(Words(words.Say("installer.maintain.heading", "Version {version} is already installed", "version", flow.Version),
                      "title", Palette.Ink), 0);
            Row(Words(words.Say("installer.options.location", "Installed in"), "label", Palette.Secondary), 8);
            Row(Words(flow.Home, null, Palette.Ink), 2);
            Row(Way(false, words.Say("installer.maintain.repair", "Repair"),
                    words.Say("installer.maintain.repair_help", "Installs this version again in place. Your settings, everything waiting and your sign-in choice are kept.")), 16);
            Row(Way(true, words.Say("installer.remove", "Remove"),
                    words.Say("installer.maintain.remove_help", "Removes Codex Auto Resume from this PC. Next, you choose whether the settings and the recovery history go too.")), 8);
            InsideNote(16);
        }

        /// One of the Maintain page's two ways, chosen when it is the flow's own.
        private ChoiceCard Way(bool remove, string title, string help)
        {
            var way = new ChoiceCard(remove ? InstallerFlow.Uninstall : InstallerFlow.Install, title, help);
            way.Font = Font;
            way.ForeColor = Palette.Ink;
            way.BackColor = Palette.Card;
            way.UseMnemonic = false;
            way.Checked = (flow.Mode == InstallerFlow.Uninstall) == remove;
            way.CheckedChanged += delegate
            {
                if (!way.Checked) return;
                flow.Choose(remove);
                forward.Text = remove ? words.Say("installer.next", "Next") : words.Say("installer.maintain.repair", "Repair");
                PerformLayout();
            };
            return way;
        }

        private void BuildConfirm()
        {
            Row(Words(words.Say("installer.uninstall.heading", "Remove Codex Auto Resume"), "title", Palette.Ink), 0);
            Row(Words(words.Say("installer.uninstall.what", "The watcher, its sign-in start, its Start menu entry and the plugin in Codex are removed. Your Codex conversations are not touched."), null, Palette.Ink), 8);
            Row(Words(words.Say("installer.options.location", "Installed in"), "label", Palette.Secondary), 16);
            Row(Words(flow.Home, null, Palette.Ink), 2);
            Row(Choice(words.Say("installer.uninstall.purge", "Also delete the settings and the recovery history"), flow.Purge, true,
                       delegate(bool on) { flow.Purge = on; }), 16);
            InsideNote(16);
        }

        private void BuildProgress()
        {
            string heading = flow.Mode == InstallerFlow.Uninstall ? words.Say("installer.progress.removing", "Removing")
                           : flow.Repair ? words.Say("installer.progress.repairing", "Repairing")
                           : flow.Another ? words.Say("installer.progress.another", "Installing another version")
                           : flow.Mode == InstallerFlow.Update ? words.Say("installer.progress.updating", "Updating")
                           : words.Say("installer.progress.installing", "Installing");
            Row(Words(heading, "title", Palette.Ink), 0);
            stepLabel = Words(words.Step(step), null, Palette.Ink);
            Row(stepLabel, 8);
            bar.Value = at;
            bar.AccessibleName = heading;
            Row(bar, 10);
            busyNote = Words(words.Say("installer.progress.busy", "It is still working. Closing now could leave half an installation, so the window stays until it has finished."), null, Palette.Secondary);
            busyNote.Visible = closingAsked;
            Row(busyNote, 10);
            Row(LogToggle(), 12);
            Row(logArea, 6);
        }

        /// The update's own page (v0.6.16, the owner: an update should show itself): the version it goes from and to,
        /// and what is new in it, read from the archive it has downloaded and checked - before anything is installed.
        /// Update goes on; Later installs nothing.
        private void BuildNotes()
        {
            Row(Words(Versions(), "title", Palette.Ink), 0);
            WhatsNew(8);
        }

        private string Versions()
        {
            return string.IsNullOrEmpty(flow.From)
                ? "v" + flow.Version
                : words.Say("installer.update.heading", "v{from} \u2192 v{to}", "from", flow.From, "to", flow.Version);
        }

        private void WhatsNew(int gap)
        {
            if (page != InstallerFlow.Notes) Row(Words(Versions(), "label", Palette.Ink), gap);
            Row(Words(words.Say("installer.update.whats_new", "What's new"), "label", Palette.Secondary), page == InstallerFlow.Notes ? gap : 6);
            // As plain text to read, never the changelog's Markdown (InstallerNotes.Readable).
            notesArea.Box.Text = flow.NotesText != null ? InstallerNotes.Readable(flow.NotesText) : words.Say("installer.update.no_notes", "What is new in this version could not be read from the download.");
            Row(notesArea, 6);
        }

        /// The Notes page's answer, from its buttons or the window's close: Update goes on with the install, Later and
        /// a close end the run with nothing installed.
        private void Answer(bool update)
        {
            go = update;
            answered.Set();
            if (update) ShowPage(InstallerFlow.Progress);
            else forward.Enabled = cancel.Enabled = false;
        }

        /// Shows the Notes page with what is new, and waits for the person's answer: on the run's worker, never on the
        /// window's own thread. False when the window is gone.
        internal bool Ask(string notes)
        {
            Post(delegate
            {
                flow.NotesText = notes;
                ShowPage(InstallerFlow.Notes);
            });
            answered.WaitOne();
            return go;
        }

        private void BuildFinish()
        {
            Row(Words(flow.Another && code == 0
                      ? words.Say("installer.done.installed_version", "Installed v{version}", "version", flow.Version)
                      : flow.Mode == InstallerFlow.Update && code == 0
                      ? words.Say("installer.done.updated_to", "Updated to v{version}", "version", flow.Version)
                      : flow.Repair && code == 0 ? words.Say("installer.done.repaired", "Codex Auto Resume is repaired.")
                      : words.Outcome(flow.Mode, code), "title", Palette.Ink), 0);
            // The exit code, as the changelog promises it: a failure's headline says it already (Outcome), so it is a
            // line of its own after a success. The window's own codes - not started, still running - are none.
            if (code == 0) Row(Words(ExitCode(), null, Palette.Secondary), 8);
            if (flow.Mode == InstallerFlow.Update && code == 0 && !string.IsNullOrEmpty(flow.NotesText))
                Row(Words(InstallerNotes.Brief(flow.NotesText, 4), null, Palette.Secondary), 8);
            string more = code == 0 ? null : words.Explain(code);
            if (more != null) Row(Words(more, null, Palette.Ink), 8);
            if (code == 0 && unconfirmed)
                Row(new SoftCallout(words.Say("installer.done.unconfirmed", "The watcher could not be confirmed running, so nothing is being watched yet. Start it from the Dashboard.")), 12);
            if (code == 0 && previousRunning)
                Row(new SoftCallout(words.Say("installer.done.previous_running", "The previous watcher is still finishing what it was doing. Once it has stopped, start the watcher from the Dashboard.")), 12);
            if (code != 0 && code != InstallerFlow.StillRunning)
                Row(Words(words.Say("installer.done.read_log", "The log below is what the installer said."), null, Palette.Secondary), 8);
            // An update's Dashboard comes back by itself (OpenDashboard); a first installation asks.
            if (code == 0 && flow.Mode == InstallerFlow.Install && !reopened)
                Row(Choice(words.Say("installer.done.open", "Open the Dashboard"), flow.OpenDashboard, true,
                           delegate(bool on) { flow.OpenDashboard = on; }), 16);
            if (code == 0) Row(LogToggle(), 16);
            else logShown = true;
            Row(logArea, 6);
        }

        private Control LogToggle()
        {
            var toggle = new LinkLabel();
            toggle.Text = logShown ? words.Say("installer.log.hide", "Hide the log") : words.Say("installer.log.show", "Show the log");
            toggle.UseMnemonic = false;
            toggle.AutoSize = false;
            toggle.BackColor = Palette.Card;
            toggle.LinkColor = Palette.Accent;
            toggle.ActiveLinkColor = Palette.AccentPressed;
            toggle.VisitedLinkColor = Palette.Accent;
            toggle.Font = Font;
            toggle.LinkClicked += delegate
            {
                logShown = !logShown;
                toggle.Text = logShown ? words.Say("installer.log.hide", "Hide the log") : words.Say("installer.log.show", "Show the log");
                logArea.Visible = logShown;
                Arrange(Inner(ClientSize.Width));
            };
            return toggle;
        }

        /// Lays the page's rows out down the card at `width`; the height they take. The log is the one row whose
        /// height is fixed, and a row that is hidden takes none - a page is measured with the log and the note
        /// showing, so it fits when they are shown.
        internal int Arrange(int width)
        {
            int y = 0;
            foreach (KeyValuePair<Control, int> row in rows)
            {
                Control control = row.Key;
                control.Visible = Wanted(control);
                y += row.Value;
                int height = HeightAt(control, width);
                control.SetBounds(0, y, control is SoftCombo ? Math.Min(width, Px(260)) : width, height);
                y += height;
            }
            return y;
        }

        private int HeightAt(Control control, int width)
        {
            if (control == logArea) return Px(150);
            if (control == notesArea) return Px(page == InstallerFlow.Notes ? 220 : 140);
            if (control == bar) return Px(10);
            if (control is SoftCombo) return SoftCombo.FieldHeight;
            if (control is ChoiceCard) return ((ChoiceCard)control).HeightFor(width);
            if (control is LinkLabel)
                return TextRenderer.MeasureText(control.Text, control.Font, new Size(width, 0),
                                                TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix).Height;
            return control.GetPreferredSize(new Size(width, 0)).Height;
        }

        // ------------------------------------------------------------------ the run

        /// Runs the installer on a worker and shows its progress; the Finish page once it has ended.
        private void Start()
        {
            if (running || code != int.MinValue) return;
            running = true;
            ShowPage(InstallerFlow.Progress);
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                int ended;
                try
                {
                    ended = runner(flow,
                                   delegate(string line) { Post(delegate { Heard(line); }); },
                                   delegate(double share) { Post(delegate { Unpacking(share); }); });
                }
                catch (Exception error)
                {
                    Post(delegate { Heard(error.Message); });
                    ended = InstallerFlow.NotStarted;
                }
                Post(delegate { Ended(ended); });
            });
        }

        private void Post(MethodInvoker action)
        {
            // Without a handle - between two showings of the window (SettingsForm.InstallPick shows it again after
            // WinForms ended its modal loop) - what the run says is kept and told once it has one again: the run's
            // end is never lost (v0.6.18 acceptance, B2).
            lock (waiting)
            {
                if (!IsHandleCreated && !IsDisposed)
                {
                    waiting.Add(action);
                    return;
                }
            }
            try { if (IsHandleCreated && !IsDisposed) BeginInvoke(action); }
            catch (Exception) { /* the window is gone */ }
        }

        private readonly List<MethodInvoker> waiting = new List<MethodInvoker>();

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            MethodInvoker[] told;
            lock (waiting)
            {
                told = waiting.ToArray();
                waiting.Clear();
            }
            foreach (MethodInvoker action in told) BeginInvoke(action);
        }

        /// Whether the installer is still running: the window stays, and is shown again, until it is not.
        internal bool Running { get { return running; } }

        private const int WM_SHOWWINDOW = 0x0018;
        private const int SW_PARENTCLOSING = 1;

        /// The Dashboard minimized under the window - by a person's Show desktop, or by another program - hides the
        /// windows it owns (WM_SHOWWINDOW, SW_PARENTCLOSING), and WinForms ends a modal window's loop once it is
        /// hidden, with no close asked: the run went on unseen (v0.6.18 acceptance, B2). While it runs, the window
        /// stays where it is instead.
        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_SHOWWINDOW && running && m.WParam == IntPtr.Zero && m.LParam.ToInt64() == SW_PARENTCLOSING)
            {
                m.Result = IntPtr.Zero;
                return;
            }
            base.WndProc(ref m);
        }

        /// One line the installer printed: into the log, and onto the bar where it begins a step. A progress line
        /// (InstallerProgress.Variable) moves the bar within the step under way and is kept out of the log: it is the
        /// window's, not the person's to read.
        internal void Heard(string line)
        {
            if (InstallerProgress.IsProgress(line))
            {
                if (InstallerProgress.Progressed(flow.Mode, line, reached, step, ref at)) bar.Value = at;
                return;
            }
            log.AppendLine(line ?? "");
            logArea.Box.AppendText((line ?? "") + Environment.NewLine);
            string said = (line ?? "").Trim();
            if (said.StartsWith("The watcher could not be confirmed running", StringComparison.Ordinal)) unconfirmed = true;
            if (said.StartsWith("The previous version of the watcher was asked to stop", StringComparison.Ordinal)) previousRunning = true;
            if (said.StartsWith("[ok] The Dashboard was opened again on the new version", StringComparison.Ordinal)) reopened = true;
            // Measured from the milestone, not from where a progress line took the bar: a step counted to its end stands
            // at the next milestone's place, and that milestone's line still begins its step.
            double place = reached;
            if (InstallerProgress.Advance(flow.Mode, line, ref place, ref step))
            {
                reached = place;
                at = Math.Max(at, place);
                ShowStep();
            }
        }

        private void Unpacking(double share)
        {
            double place = InstallerProgress.Unpacked((int)Math.Round(share * 1000), 1000);
            if (place <= at) return;
            at = reached = place;
            step = share >= 1.0 ? "unpack" : share <= 0 ? "verify_setup" : "unpack";
            ShowStep();
        }

        private void ShowStep()
        {
            bar.Value = at;
            if (stepLabel == null) return;
            stepLabel.Text = words.Step(step);
            Arrange(Inner(ClientSize.Width));
        }

        private void Ended(int ended)
        {
            if (ended == InstallerFlow.Later)
            {
                // Put off on the Notes page: nothing was installed, and there is nothing more to say.
                running = false;
                code = ended;
                Close();
                return;
            }
            running = false;
            code = ended;
            // The log ends with the code the installer ended with, where it ended with one of its own.
            if (HasExitCode(ended))
            {
                log.AppendLine(ExitCode());
                logArea.Box.AppendText(ExitCode() + Environment.NewLine);
            }
            logShown = ended != 0;
            // A run that ended well fills the bar - a short glide where it may move, at once where it may not - and
            // the Finish page follows; any other ending leaves the bar where the work stopped.
            if (ended == 0)
            {
                at = 1.0;
                bar.Finish(ShowFinish);
            }
            else ShowFinish();
        }

        // The Finish page is measured again for what the run left it saying - a notice about the watcher, the failure's
        // own lines - so the window is as tall as it now needs.
        private void ShowFinish()
        {
            if (IsDisposed) return;
            page = InstallerFlow.Finish;
            Fit();
        }

        /// Whether `ended` is a code the installer ended with, rather than one of the window's own (not started, still
        /// running, put off).
        private static bool HasExitCode(int ended)
        {
            return ended != InstallerFlow.NotStarted && ended != InstallerFlow.StillRunning &&
                   ended != InstallerFlow.Later && ended != int.MinValue;
        }

        private string ExitCode()
        {
            return words.Say("installer.done.exit_code", "Exit code: {code}", "code",
                             code.ToString(System.Globalization.CultureInfo.InvariantCulture));
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // Never while the installer runs: half an installation is worse than a slow one. Windows signing out or
            // shutting down is not asked, and ends the installer with it.
            if (running && e.CloseReason == CloseReason.UserClosing && page == InstallerFlow.Notes)
            {
                // Closing the Notes page is Later: the run ends with nothing installed, and the window with it.
                e.Cancel = true;
                if (forward.Enabled) Answer(false);
                return;
            }
            // Any other close while it runs is refused the same way, Windows ending the session alone excepted: a raw
            // WM_CLOSE from another program arrives as TaskManagerClosing, and the Dashboard's own closing as
            // FormOwnerClosing. v0.6.18 acceptance: an older installer, run by Install another version..., closed the
            // pick's window part-way that way - the run went on unseen and the pick said it had failed.
            if (running && e.CloseReason != CloseReason.WindowsShutDown)
            {
                e.Cancel = true;
                closingAsked = true;
                if (busyNote != null) Arrange(Inner(ClientSize.Width));
                return;
            }
            base.OnFormClosing(e);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            answered.Set();
            base.OnFormClosed(e);
        }

        /// A window build/capture_window.ps1 started is never made the foreground window, as the Dashboard's is not
        /// (SettingsForm.ShowWithoutActivation): the capture reads the caption back and refuses an active one. A
        /// person's window is never given a capture's event, and opens as always.
        protected override bool ShowWithoutActivation
        {
            get { return Soft.StillReady != null || base.ShowWithoutActivation; }
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams created = base.CreateParams;
                if (Soft.StillReady != null) created.ExStyle |= 0x08000000;          // WS_EX_NOACTIVATE
                return created;
            }
        }

        /// Every control on the page that is shown, for the layout audit.
        internal IEnumerable<Control> ShownRows()
        {
            foreach (KeyValuePair<Control, int> row in rows) if (Wanted(row.Key)) yield return row.Key;
        }

        // Whether a row is shown: every row but the log, while it is folded away, and the note that the window stays
        // open, until someone has tried to close it. Those two keep their room, so showing them moves nothing else.
        private bool Wanted(Control control)
        {
            if (control == logArea) return logShown;
            if (control == busyNote) return closingAsked;
            return true;
        }

        private bool Has(Control button)
        {
            return button == forward ? forwardShown : button == back ? backShown : button == cancel && cancelShown;
        }

        internal IEnumerable<Label> HeaderLines() { return new Label[] { title, version }; }

        internal Control Body { get { return sheet; } }
        internal IEnumerable<Control> Buttons()
        {
            foreach (Control button in new Control[] { forward, back, cancel }) if (Has(button)) yield return button;
        }

        /// Stands in a finished run, for the layout audit: its code and the log it would have.
        internal void Finished(int ended, string lines)
        {
            foreach (string line in (lines ?? "").Split('\n')) Heard(line.TrimEnd('\r'));
            Ended(ended);
        }

        private sealed class LanguageItem
        {
            internal readonly string Locale;
            internal LanguageItem(string locale) { Locale = locale; }
            public override string ToString()
            {
                string name;
                return InstallerLanguages.Endonyms.TryGetValue(Locale, out name) ? name : Locale;
            }
        }
    }

    /// A ground in the window's material: the canvas behind the cards, or a card's own colour inside one, seen
    /// through to the card (Ground).
    internal sealed class InstallerSheet : Panel, ISoftGround
    {
        internal InstallerSheet(bool onCard)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = onCard ? Palette.Card : Palette.Canvas;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// The installer's progress: a well, as a field is, filled with the accent as far as the installer has come.
    ///
    /// Two values: Value, where the work is, and Shown, what is drawn. Shown glides up to Value on a timer
    /// (InstallerProgress.Glide) and stops it once there; neither ever goes back. Nothing glides under a capture
    /// (Soft.StillReady: the pictures and the install motion stay exact) or where it cannot be seen; with motion
    /// reduced the bar jumps, and redraws at most about once a second.
    internal sealed class InstallerBar : Control
    {
        private double value, shown;
        private int said = -1;
        private readonly Timer timer = new Timer();
        private readonly Stopwatch clock = new Stopwatch();
        private long lastDrawn = -ReducedInterval;
        private MethodInvoker finished;
        private long finishStarted;

        /// The frame of the glide, in milliseconds (about 60 a second), and the redraw of a bar with motion reduced.
        internal const int GlideInterval = 16;
        internal const int ReducedInterval = 1000;

        internal InstallerBar()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            TabStop = false;
            AccessibleRole = AccessibleRole.ProgressBar;
            BackColor = Palette.Card;
            timer.Tick += delegate { Tick(); };
            clock.Start();
        }

        /// Where the work is, from 0 to 1: forward only.
        internal double Value
        {
            get { return value; }
            set
            {
                double next = Math.Max(0.0, Math.Min(1.0, value));
                if (next <= this.value + 0.0001) return;
                this.value = next;
                Follow();
            }
        }

        /// What the bar draws now, from 0 to 1.
        internal double Shown { get { return shown; } }

        /// Whether the bar's timer runs: only while what it draws has somewhere left to go.
        internal bool Moving { get { return timer.Enabled; } }

        /// The run ended well: the bar goes to the whole of it - a short glide, at most FinishSeconds, where it may
        /// move - and then `then` runs, at once where it may not.
        internal void Finish(MethodInvoker then)
        {
            value = 1.0;
            if (Mode() != Moves.Glide)
            {
                Show(1.0);
                Halt();
                if (then != null) then();
                return;
            }
            finished = then;
            finishStarted = clock.ElapsedMilliseconds;
            Run(GlideInterval);
        }

        internal enum Moves { None, Glide, Reduced }

        /// How the bar may move: not at all under a capture (the pictures stay exact) or where it is not seen, by
        /// jumps with motion reduced, gliding otherwise. Pure.
        internal static Moves MotionFor(bool capture, bool seen, bool reduced)
        {
            if (capture || !seen) return Moves.None;
            return reduced ? Moves.Reduced : Moves.Glide;
        }

        // How the bar may move now.
        private Moves Mode()
        {
            Form form = FindForm();
            bool seen = IsHandleCreated && Visible && Soft.Shown(this) &&
                        (form == null || (form.Visible && form.WindowState != FormWindowState.Minimized));
            return MotionFor(Soft.StillReady != null, seen, seen && Soft.ReduceMotion);
        }

        private void Follow()
        {
            switch (Mode())
            {
                case Moves.Glide:
                    Run(GlideInterval);
                    break;
                case Moves.Reduced:
                    if (clock.ElapsedMilliseconds - lastDrawn >= ReducedInterval) { Show(value); Halt(); }
                    else Run(ReducedInterval);
                    break;
                default:
                    Halt();
                    Show(value);
                    break;
            }
        }

        private long lastTick;

        private void Run(int interval)
        {
            if (timer.Enabled && timer.Interval == interval) return;
            timer.Interval = interval;
            lastTick = clock.ElapsedMilliseconds;
            timer.Start();
        }

        private void Halt()
        {
            timer.Stop();
        }

        private void Tick()
        {
            long now = clock.ElapsedMilliseconds;
            Moves mode = Mode();
            if (mode == Moves.Glide && !(finished != null && now - finishStarted >= (long)(InstallerProgress.FinishSeconds * 1000)))
                Show(InstallerProgress.Glide(shown, value, (now - lastTick) / 1000.0));
            else
                Show(value);
            lastTick = now;
            if (shown < value) return;
            Halt();
            MethodInvoker then = finished;
            finished = null;
            if (then != null) then();
        }

        // Draws `next`, forward only; the percent read out changes only when its whole number does.
        private void Show(double next)
        {
            if (next <= shown) return;
            shown = Math.Min(next, value);
            lastDrawn = clock.ElapsedMilliseconds;
            int percent = (int)Math.Round(shown * 100);
            if (percent != said)
            {
                said = percent;
                AccessibleDescription = percent.ToString(System.Globalization.CultureInfo.InvariantCulture) + "%";
                // v0.6.18: and said: a screen reader is told the bar moved, or it never hears the progress.
                if (IsHandleCreated)
                {
                    AccessibilityNotifyClients(AccessibleEvents.DescriptionChange, -1);
                    AccessibilityNotifyClients(AccessibleEvents.ValueChange, -1);
                }
            }
            Invalidate();
        }

        // Off the page, or the window going: no timer runs, and the bar shows where the work is.
        protected override void OnVisibleChanged(EventArgs e)
        {
            base.OnVisibleChanged(e);
            if (!Visible && timer.Enabled && finished == null) { Halt(); Show(value); }
        }

        protected override void OnParentChanged(EventArgs e)
        {
            base.OnParentChanged(e);
            if (Parent == null && timer.Enabled && finished == null) { Halt(); Show(value); }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                finished = null;
                timer.Stop();
                timer.Dispose();
            }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Ground.PaintArea(this, g, ClientRectangle);
            Rectangle track = ClientRectangle;
            float radius = track.Height / 2f;
            Soft.InsetWell(g, track, radius, false);
            int filled = (int)Math.Round(track.Width * shown);
            if (filled <= 0) return;
            var face = new Rectangle(track.X, track.Y, Math.Max(track.Height, filled), track.Height);
            var smoothing = g.SmoothingMode;
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            using (System.Drawing.Drawing2D.GraphicsPath shape = Soft.Rounded(face, radius))
                g.FillPath(Soft.Fill(Palette.Accent), shape);
            g.SmoothingMode = smoothing;
        }
    }
}

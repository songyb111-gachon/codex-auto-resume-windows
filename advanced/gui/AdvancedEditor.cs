// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the prompt queue's editor (v0.6.19, issue #50): the one place a message is scheduled or changed.
//
// A child dialog in the Dashboard's design - the window's dialogs' frame (gui/DashboardActions.cs Dialog), one card of the
// Settings page's rows on the canvas - for a new message or, filled, for one still waiting: the conversation (fixed for an
// edit), the words in a box at the reading size (the type scale's figure step, 3 pt over the window's text: never under
// 12 pt at 100%), counted to the bound, when it goes (after this turn, at a time, every day or every week), at which
// hour, how many times for a series, whether it waits for the one before it, and - for a time or a series - what it does
// while a turn is running in that conversation: two named behaviours, as two of the window's choice cards (a choice, not a
// switch), Wait until it ends marked recommended and preselected for a new message. After this turn says it goes into
// Codex's queue by its nature. Two buttons: Save and return (the accent, what Enter presses) and Cancel.
//
// Save and return is the bridge's advanced-prompt-add or advanced-prompt-edit, against the generation the list was read
// at. Taken, the dialog closes, the list is read again and the saved row is the one chosen there; refused, the dialog
// stays with every field as typed and the refusal's words above the buttons.
//
// v0.6.20 (issue #50, steer_send): for a new message, while Steer the running turn stands on, When offers a fifth
// choice - Now, into the turn that is running (steer). Chosen, the hour, the count and the wait for the one before are
// not asked, the two while-running cards and the after-this-turn line give way to the steer's warning in the danger
// colour (the Codex app does not show a steered line - only History does), and the accent button reads Steer now and
// sends the bridge's advanced-steer instead; the watcher alone writes it, and History shows what came of it.
//
// v0.6.20 (#50 item 1): pictures under the words - pasted (Ctrl+V of a picture, or of picture files copied in Explorer),
// chosen (Add a picture..., an open-file dialog of pictures only) or dropped on the dialog - up to four, each checked by
// its bytes and size before it is shown, as a row of thumbnails with a Remove under each. The request names each new
// one by its file - a paste by a PNG the window writes to %TEMP% and deletes once the dialog has closed - and each one a
// message already had by its copy's id; the bridge keeps the product's own copies (images.py).
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // The open editor's fields, as it was built - null while none is - for its own reads and the page's audit.
        private Form editorDialog;
        private SoftCombo editorConversation, editorWhen, editorHour, editorTimes, editorDepends;
        private SoftTextArea editorWords;
        private Label editorCount, editorAfterTurn, editorSaid;
        // v0.6.20: the steer's warning, shown while When is the steer; and whether the last save was a steer.
        private Label editorSteerWarning;
        private bool editorSteered;
        private ChoiceGroup editorMode;
        private Button editorSave, editorCancel;
        // What FitEditor measures - the fields' stack and the buttons under it - and what it last fitted the dialog to.
        private Control editorBody, editorButtons;
        private string editorFitFor;
        private int editorPrompt = -1;
        private bool editorTaken;
        // The prompt the last Save and return saved, for the list read after it to choose; -1 where none waits to be.
        private int editorSaved = -1;
        // Null in every window a person opens. In a window AdvancedPageRun drives: what answers the editor, never shown.
        private Action<Form> editorAnswer;
        // The type scale's figure step (SoftTheme.RoleFont "figure"): the editor's words are read at it.
        private const float ReadingLarger = 3f;
        // v0.6.20 (#50 item 1): the message's pictures - each a file to copy (Path) or a copy it already has (Id) - their
        // row of thumbnails, Add a picture..., and the PNGs written for a paste, deleted once the dialog has closed.
        private sealed class EditorImage
        {
            public string Path, Id;
            public Image Thumb;
        }
        private List<EditorImage> editorImages = new List<EditorImage>();
        private List<string> editorTemps = new List<string>();
        private FlowLayoutPanel editorThumbs;
        private Button editorAddImage;
        private bool editorHadImages;
        // Null in every window a person opens. In a window AdvancedPageRun drives: the files Add a picture... chooses, so
        // no file dialog is ever shown there.
        private Func<string[]> editorChoose;
        // As the bridge holds them (images.py): four a message, 5 MB each.
        private const int ImagesMost = 4;
        private const long ImageBytesMost = 5L * 1024 * 1024;
        private const int ThumbSide = 64;

        /// The editor for a new message (`row` null) or for `row`, a prompt still waiting: shown, answered, and - where it
        /// saved - the page and the list read again, the saved row to be chosen there.
        private void OpenEditor(Dictionary<string, object> row)
        {
            if (busy > 0 || advancedListing == null || advancedPrompts == null) return;
            if (row != null && Str(row, "state") != "waiting") return;
            using (Form dialog = BuildEditor(row))
            {
                if (editorAnswer != null) editorAnswer(dialog);
                else if (!auditing) dialog.ShowDialog(this);
            }
            bool taken = editorTaken, steered = editorSteered;
            ForgetEditor();
            ForgetPasted();
            if (!taken) return;
            ResetNote(steered ? Word("page.done.steer_sent", "Handed to the watcher. History shows what came of it.")
                              : Word("page.done.prompt_saved", "Saved."));
            // The list as the save answered it, the saved row chosen (AdvancedSchedule.cs), then read again.
            FillScheduled();
            ReadAdvanced(null);
            if (advancedOpen != PromptQueueId) ReadPrompts(null);
        }

        private void ForgetEditor()
        {
            editorDialog = null;
            editorConversation = editorWhen = editorHour = editorTimes = editorDepends = null;
            editorFind = null;
            editorWords = null;
            editorCount = editorAfterTurn = editorSaid = null;
            editorSteerWarning = null;
            editorSteered = false;
            editorMode = null;
            editorSave = editorCancel = null;
            editorBody = editorButtons = null;
            editorFitFor = null;
            editorPrompt = -1;
            editorTaken = false;
            foreach (EditorImage image in editorImages)
                if (image.Thumb != null) image.Thumb.Dispose();
            editorImages = new List<EditorImage>();
            editorThumbs = null;
            editorAddImage = null;
            editorHadImages = false;
        }

        /// The PNGs written for a paste, deleted: the bridge has made its own copies of those it saved.
        private void ForgetPasted()
        {
            foreach (string path in editorTemps)
                try { File.Delete(path); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            editorTemps = new List<string>();
        }

        private int EditorWordsMost()
        {
            int most = Whole(Get(Map(advancedPrompts, "limits"), "words"));
            return most > 0 ? most : 2000;
        }

        /// The dialog, built and not shown: filled from `row`, or empty for a new message.
        private Form BuildEditor(Dictionary<string, object> row)
        {
            ForgetEditor();
            bool editing = row != null;
            editorPrompt = editing ? Whole(Get(row, "prompt_id")) : -1;
            string title = editing ? Word("page.editor.title_edit", "Edit the message")
                                   : Word("page.editor.title_new", "Schedule a message");
            var dialog = new Form();
            dialog.Text = title;
            dialog.Font = Font;
            dialog.BackColor = Canvas;
            dialog.ForeColor = Ink;
            Soft.TitleBar(dialog);
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.MinimizeBox = false;
            dialog.MaximizeBox = false;
            dialog.ShowInTaskbar = false;
            dialog.ShowIcon = false;
            int width = Px(560);

            var body = new SoftStack();
            body.Dock = DockStyle.Top;
            body.AutoSize = true;
            body.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            body.ColumnCount = 1;
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            body.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
            body.Padding = Pad(16, 16, 16, 0);
            body.BackColor = Canvas;
            TableLayoutPanel card = MakeCard(title);
            card.Margin = new Padding(0);
            body.Controls.Add(card);

            string conversation = Word("page.resets.field.conversation", "Conversation");
            editorConversation = EditorCombo(conversation, 300);
            foreach (KeyValuePair<string, string> pair in Conversations())
                editorConversation.Items.Add(new Choice(pair.Key, pair.Value));
            string thread = editing ? Str(row, "thread_id") : null;
            if (thread != null && !Conversations().ContainsKey(thread))
                editorConversation.Items.Add(new Choice(thread, ConversationOf(thread)));
            SelectChoice(editorConversation, thread);
            editorConversation.Enabled = !editing;
            card.Controls.Add(NewRow(conversation, editorConversation));
            // Beside the picker, for a new message (the conversation of one waiting is fixed): the person's own conversations
            // beyond the ones Pending and History list, with a search (AdvancedFind.cs).
            if (!editing)
                editorFind = CardButton(card, Word("page.find.button", "Find a conversation..."), delegate
                {
                    FindConversation(dialog, editorConversation, ShowEditorState);
                });
            if (editorConversation.Items.Count == 0)
                card.Controls.Add(HelpText(Word("page.resets.no_conversation",
                    "No conversation is listed yet. One is offered here once Pending or History lists it.")));

            string words = Word("page.resets.field.words", "Message");
            card.Controls.Add(Caption(words));
            editorWords = new SoftTextArea();
            Font reading = Soft.Weighted(Font, Font.SizeInPoints + ReadingLarger, 400);
            editorWords.Font = reading;
            editorWords.Box.Font = reading;
            editorWords.Box.MaxLength = EditorWordsMost();
            editorWords.Box.AccessibleName = words;
            editorWords.Height = Px(150);
            editorWords.Dock = DockStyle.Fill;
            editorWords.Margin = Pad(0, 4, 0, 2);
            if (editing) editorWords.Box.Text = (Str(row, "words") ?? "").Replace("\r\n", "\n").Replace("\n", "\r\n");
            card.Controls.Add(editorWords);
            editorCount = HelpText("");
            card.Controls.Add(editorCount);

            // Its pictures: a caption, what it takes, the thumbnails, and Add a picture... (v0.6.20, #50 item 1).
            card.Controls.Add(Caption(Word("page.editor.images", "Pictures")));
            card.Controls.Add(HelpText(Word("page.editor.images.help",
                "Paste with Ctrl+V, drop files here or add them: up to 4 pictures, PNG, JPEG, GIF or WebP, 5 MB each. Each is kept as a copy until the message is delivered.")));
            editorThumbs = new FlowLayoutPanel();
            editorThumbs.AutoSize = true;
            editorThumbs.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            editorThumbs.WrapContents = true;
            editorThumbs.FlowDirection = FlowDirection.LeftToRight;
            editorThumbs.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            editorThumbs.Margin = Pad(0, 0, 0, 0);
            editorThumbs.BackColor = Card;
            editorThumbs.AccessibleName = Word("page.editor.images", "Pictures");
            card.Controls.Add(editorThumbs);
            editorAddImage = CardButton(card, Word("page.editor.images.add", "Add a picture..."), delegate { ChooseImages(); });
            if (editing)
                foreach (object listed in Items(row, "images") ?? new List<object>())
                {
                    string id = Str(listed as Dictionary<string, object>, "id");
                    string copy = Str(listed as Dictionary<string, object>, "path");
                    if (id == null) continue;
                    var image = new EditorImage();
                    image.Id = id;
                    image.Thumb = copy == null ? null : Thumbnail(copy);
                    editorImages.Add(image);
                    editorHadImages = true;
                }
            ShowThumbs();

            string when = Word("page.queue.when", "When");
            editorWhen = EditorCombo(when, 220);
            editorWhen.Items.Add(new Choice("after_turn", Word("page.queue.when.after_turn", "After this turn")));
            editorWhen.Items.Add(new Choice("at_time", Word("page.queue.when.at_time", "At a time")));
            editorWhen.Items.Add(new Choice("day", Word("page.queue.when.daily", "Every day")));
            editorWhen.Items.Add(new Choice("week", Word("page.queue.when.weekly", "Every week")));
            // v0.6.20: the steer, for a new message while Steer the running turn stands on.
            if (!editing && SteerOn())
                editorWhen.Items.Add(new Choice("steer", Word("page.editor.when.steer", "Now, into the turn that is running (steer)")));
            string trigger = editing ? Str(row, "trigger") : null;
            SelectChoice(editorWhen, trigger == "recurring" ? Str(row, "every") : trigger ?? "after_turn");
            card.Controls.Add(NewRow(when, editorWhen));

            string hour = Word("page.queue.hour", "At");
            editorHour = EditorCombo(hour, 120);
            for (int h = 0; h < 24; h++)
                editorHour.Items.Add(new Choice(h.ToString(CultureInfo.InvariantCulture), h.ToString("00", CultureInfo.InvariantCulture) + ":00"));
            double due = editing && Get(row, "due_at") is double ? (double)Get(row, "due_at") : 0;
            int chosenHour = due > 0 && trigger != "after_turn"
                ? new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(due).ToLocalTime().Hour : 9;
            editorHour.SelectedIndex = chosenHour;
            card.Controls.Add(NewRow(hour, editorHour));

            string times = Word("page.queue.times", "How many times");
            editorTimes = EditorCombo(times, 120);
            for (int n = 1; n <= SeriesMost; n++)
                editorTimes.Items.Add(new Choice(n.ToString(CultureInfo.InvariantCulture), n.ToString(CultureInfo.CurrentCulture)));
            editorTimes.SelectedIndex = Math.Max(0, Math.Min(SeriesMost, editing ? Whole(Get(row, "occurrences")) : 1) - 1);
            card.Controls.Add(NewRow(times, editorTimes));

            string depends = Word("page.queue.depends", "Wait for the one before it to arrive");
            editorDepends = EditorCombo(depends, 120);
            editorDepends.Items.Add(new Choice("no", Word("page.queue.depends.no", "No")));
            editorDepends.Items.Add(new Choice("yes", Word("page.queue.depends.yes", "Yes")));
            editorDepends.SelectedIndex = editing && Equals(Get(row, "depends"), true) ? 1 : 0;
            card.Controls.Add(NewRow(depends, editorDepends));

            // What it does while a turn runs: two named behaviours, the recommended one first and chosen for a new one.
            string mode = Word("page.editor.mode", "When a turn is running in that conversation:");
            card.Controls.Add(Caption(mode));
            editorMode = new ChoiceGroup();
            editorMode.Dock = DockStyle.Fill;
            editorMode.Font = Font;
            editorMode.Margin = Pad(0, 2, 0, 4);
            editorMode.AccessibleName = mode;
            editorMode.Add(new ChoiceCard("wait", Word("page.editor.mode.wait", "Wait until it ends (recommended)"), ""));
            editorMode.Add(new ChoiceCard("queue", Word("page.editor.mode.queue",
                "Add it to Codex's queue now - Codex runs it after that turn"), ""));
            editorMode.Value = editing && Str(row, "while_running") == "queue" ? "queue" : "wait";
            card.Controls.Add(editorMode);
            editorAfterTurn = HelpText(Word("page.editor.mode.after_turn",
                "\"After this turn\" goes into Codex's queue: Codex runs it when the turn now running ends."));
            card.Controls.Add(editorAfterTurn);
            editorSteerWarning = HelpText(Word("page.editor.steer.warning",
                "A steer goes into the turn running now, through the Codex app's own connection. The Codex app does not show the steered line anywhere - only History here shows what was sent."));
            editorSteerWarning.ForeColor = Palette.Danger;
            editorSteerWarning.Visible = false;
            card.Controls.Add(editorSteerWarning);
            if (Equals(Get(advancedPrompts, "after_turn_unproven"), true))
                card.Controls.Add(HelpText(Word("page.queue.unproven",
                    "After this turn is unproven on this Codex until it has been measured.")));

            // Where a refusal is said, above the buttons.
            editorSaid = HelpText("");
            editorSaid.ForeColor = Palette.Danger;
            body.Controls.Add(editorSaid);
            // On a page of its own that scrolls up and down: at 200% on a screen smaller than it, Windows holds the dialog
            // to the screen, and what does not fit is scrolled to rather than cut off.
            var host = new SoftPage();
            host.Dock = DockStyle.Fill;
            host.Margin = new Padding(0);
            host.Padding = new Padding(0);
            host.BackColor = Canvas;
            host.Controls.Add(body);
            host.Scrolls = true;
            dialog.Controls.Add(host);

            FlowLayoutPanel buttons = ButtonRow();
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.Padding = Pad(0, 12, 16, 16);
            editorSave = MakeButton(Word("page.editor.save", "Save and return"), true, delegate { SaveEditor(dialog); });
            editorCancel = MakeButton(S("action.cancel", "Cancel"), false, delegate { dialog.Close(); });
            buttons.Controls.Add(editorSave);
            buttons.Controls.Add(editorCancel);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = editorSave;
            dialog.CancelButton = editorCancel;
            dialog.ActiveControl = editing ? (Control)editorWords.Box : editorConversation;

            editorWords.Box.TextChanged += delegate { ShowEditorState(); };
            editorWhen.SelectionChangeCommitted += delegate { ShowEditorState(); };
            editorConversation.SelectionChangeCommitted += delegate { ShowEditorState(); };
            // A picture pasted anywhere in the dialog, or files dropped on it (v0.6.20): Ctrl+V of text still pastes text.
            dialog.KeyPreview = true;
            dialog.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.Control && e.KeyCode == Keys.V && PasteImages()) e.SuppressKeyPress = true;
            };
            TakeDrops(dialog);
            editorDialog = dialog;
            ShowEditorState();

            // Each line that wraps is held to the width it is laid out at - a measure taken at a wider width read Hebrew at
            // 200% short by two lines - and the dialog is as tall as what it shows (FitEditor).
            int inner = width - body.Padding.Horizontal;
            int lines = inner - card.Padding.Horizontal;
            foreach (Control control in card.Controls)
                if (control is WrapLabel) control.MaximumSize = new Size(lines, 0);
            editorThumbs.MaximumSize = new Size(lines, 0);
            editorSaid.MaximumSize = new Size(inner, 0);
            dialog.ClientSize = new Size(width, Px(400));
            editorBody = body;
            editorButtons = buttons;
            ShowEditorState();
            return dialog;
        }

        /// The dialog as tall as what it shows now - the send mode's two choices for a time, or the line on after this
        /// turn, and a refusal once one is said - and never taller than the screen it opens on lets a window be, where
        /// what does not fit is scrolled to. Measured again only when one of those changes, never at a keystroke. Up to
        /// v0.6.19-beta.3 it stood as tall as all of them at once, and what was not showing was an empty band above the
        /// buttons (the owner, 2026-10-25).
        private void FitEditor()
        {
            if (editorDialog == null || editorBody == null || editorButtons == null) return;
            string showing = Soft.OwnVisible(editorMode) + "|" + Soft.OwnVisible(editorAfterTurn) + "|" +
                             Soft.OwnVisible(editorSteerWarning) + "|" + editorSaid.Text
                           + "|" + editorImages.Count.ToString(CultureInfo.InvariantCulture);
            if (showing == editorFitFor) return;
            editorFitFor = showing;
            int width = editorDialog.ClientSize.Width;
            editorDialog.PerformLayout();
            editorBody.Parent.PerformLayout();
            editorBody.PerformLayout();
            int tall = Math.Max(editorBody.Height, editorBody.GetPreferredSize(new Size(width, 0)).Height);
            int buttonsTall = editorButtons.GetPreferredSize(new Size(width, 0)).Height;
            int want = Math.Max(Px(240), Math.Min(tall + buttonsTall, EditorMost()));
            if (editorDialog.ClientSize.Height != want) editorDialog.ClientSize = new Size(width, want);
        }

        /// The tallest the editor may stand: what the screen it opens on lets a window be, less room around it.
        private int EditorMost()
        {
            return Math.Min(Screen.GetWorkingArea(this).Height, SystemInformation.MaxWindowTrackSize.Height) - Px(96);
        }

        private SoftCombo EditorCombo(string name, int width)
        {
            var combo = new SoftCombo();
            combo.Width = Px(width);
            IgnoreWheel(combo);
            combo.AccessibleName = name;
            return combo;
        }

        private static void SelectChoice(ComboBox combo, string value)
        {
            int index = combo.Items.Count > 0 ? 0 : -1;
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var choice = combo.Items[i] as Choice;
                if (choice != null && choice.Value == value) index = i;
            }
            combo.SelectedIndex = index;
        }

        /// What the fields allow now: the hour for a time or a series, the count for a series, the send mode for a time or a
        /// series (After this turn says what it does instead), Save and return once there is a conversation and words.
        private void ShowEditorState()
        {
            if (editorWhen == null) return;
            var when = editorWhen.SelectedItem as Choice;
            string value = when == null ? "after_turn" : when.Value;
            bool steer = value == "steer";
            bool later = value != "after_turn" && !steer;
            editorHour.Enabled = later;
            editorTimes.Enabled = value == "day" || value == "week";
            editorDepends.Enabled = !steer;
            editorMode.Visible = later;
            editorAfterTurn.Visible = value == "after_turn";
            editorSteerWarning.Visible = steer;
            string save = steer ? Word("page.editor.steer.send", "Steer now") : Word("page.editor.save", "Save and return");
            if (editorSave.Text != save) editorSave.Text = save;
            editorCount.Text = Word("page.resets.count", "{n} of {most} characters", "n", editorWords.Box.Text.Length)
                .Replace("{most}", Mirror.Embed(EditorWordsMost().ToString(CultureInfo.CurrentCulture)));
            editorSave.Enabled = busy == 0 && editorConversation.SelectedItem != null && editorWords.Box.Text.Trim().Length > 0;
            if (editorAddImage != null) editorAddImage.Enabled = busy == 0 && editorImages.Count < ImagesMost;
            FitEditor();
        }

        // ---------------------------------------------------------------- pictures (v0.6.20, #50 item 1)
        /// Add a picture...: the files chosen in an open-file dialog of pictures only - or, in a window AdvancedPageRun
        /// drives, the files it names, never a dialog shown.
        private void ChooseImages()
        {
            string[] chosen = null;
            if (editorChoose != null) chosen = editorChoose();
            else if (!auditing)
                using (var open = new OpenFileDialog())
                {
                    open.Title = Word("page.editor.images.add", "Add a picture...").TrimEnd('.');
                    open.Filter = Word("page.editor.images", "Pictures") + "|*.png;*.jpg;*.jpeg;*.gif;*.webp";
                    open.Multiselect = true;
                    open.CheckFileExists = true;
                    if (open.ShowDialog(editorDialog) == DialogResult.OK) chosen = open.FileNames;
                }
            if (chosen != null) AddImages(chosen);
        }

        /// Ctrl+V: a picture on the clipboard, written as a PNG of the window's own in %TEMP%, or picture files copied in
        /// Explorer. False where the clipboard holds neither, so the words box pastes its text as it always did.
        private bool PasteImages()
        {
            try
            {
                if (Clipboard.ContainsFileDropList())
                {
                    var files = new List<string>();
                    foreach (string file in Clipboard.GetFileDropList()) files.Add(file);
                    if (files.Count == 0 || ImageKind(files[0]) == null) return false;
                    AddImages(files.ToArray());
                    return true;
                }
                if (!Clipboard.ContainsImage()) return false;
                using (Image pasted = Clipboard.GetImage())
                {
                    if (pasted == null) return false;
                    string path = System.IO.Path.Combine(System.IO.Path.GetTempPath(),
                                                         "codex-auto-resume-paste-" + Guid.NewGuid().ToString("N") + ".png");
                    pasted.Save(path, System.Drawing.Imaging.ImageFormat.Png);
                    editorTemps.Add(path);
                    AddImages(new[] { path });
                }
                return true;
            }
            catch (System.Runtime.InteropServices.ExternalException) { return false; }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
        }

        /// Files dropped anywhere on the dialog but the words box, which keeps its own dragging of text.
        private void TakeDrops(Control control)
        {
            if (editorWords != null && control == editorWords.Box) return;
            control.AllowDrop = true;
            control.DragEnter += delegate(object sender, DragEventArgs e)
            {
                e.Effect = e.Data != null && e.Data.GetDataPresent(DataFormats.FileDrop) ? DragDropEffects.Copy : DragDropEffects.None;
            };
            control.DragDrop += delegate(object sender, DragEventArgs e)
            {
                var files = e.Data == null ? null : e.Data.GetData(DataFormats.FileDrop) as string[];
                if (files != null) AddImages(files);
            };
            foreach (Control child in control.Controls) TakeDrops(child);
        }

        /// The pictures `paths` added after those there, each checked as the bridge checks it - its bytes a PNG, JPEG, GIF
        /// or WebP, 5 MB at most, four in all - and the first refusal said above the buttons.
        private void AddImages(string[] paths)
        {
            if (editorThumbs == null || paths == null) return;
            string refused = null;
            foreach (string path in paths)
            {
                if (editorImages.Count >= ImagesMost) { refused = refused ?? "images_full"; break; }
                string problem = ImageProblem(path);
                if (problem != null) { refused = refused ?? problem; continue; }
                var image = new EditorImage();
                image.Path = path;
                image.Thumb = Thumbnail(path);
                editorImages.Add(image);
            }
            editorSaid.Text = refused == null ? "" : PromptRefusal(refused);
            ShowThumbs();
            ShowEditorState();
        }

        /// Why the file at `path` is no picture the bridge takes - image_refused or image_too_large - or null.
        private static string ImageProblem(string path)
        {
            try
            {
                if (string.IsNullOrEmpty(path) || !File.Exists(path)) return "image_refused";
                if (new FileInfo(path).Length > ImageBytesMost) return "image_too_large";
                return ImageKind(path) == null ? "image_refused" : null;
            }
            catch (Exception) { return "image_refused"; }   // unreadable, or no path Windows takes
        }

        /// The kind a file's first bytes say - png, jpg, gif or webp - or null: never its name (images.py's kind).
        private static string ImageKind(string path)
        {
            var head = new byte[12];
            int read;
            try
            {
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                    read = stream.Read(head, 0, head.Length);
            }
            catch (Exception) { return null; }              // unreadable, or no path Windows takes
            if (read >= 8 && head[0] == 0x89 && head[1] == 0x50 && head[2] == 0x4E && head[3] == 0x47
                && head[4] == 0x0D && head[5] == 0x0A && head[6] == 0x1A && head[7] == 0x0A) return "png";
            if (read >= 3 && head[0] == 0xFF && head[1] == 0xD8 && head[2] == 0xFF) return "jpg";
            if (read >= 6 && head[0] == 'G' && head[1] == 'I' && head[2] == 'F' && head[3] == '8'
                && (head[4] == '7' || head[4] == '9') && head[5] == 'a') return "gif";
            if (read >= 12 && head[0] == 'R' && head[1] == 'I' && head[2] == 'F' && head[3] == 'F'
                && head[8] == 'W' && head[9] == 'E' && head[10] == 'B' && head[11] == 'P') return "webp";
            return null;
        }

        /// A thumbnail of the picture at `path`, ThumbSide square at most with its shape kept, read into memory so the file
        /// is never held open - or null where Windows cannot draw it (a WebP on a Windows without its codec): its tile is
        /// then the canvas's inset alone.
        private Image Thumbnail(string path)
        {
            try
            {
                byte[] data = File.ReadAllBytes(path);
                using (var stream = new MemoryStream(data))
                using (Image found = Image.FromStream(stream))
                {
                    int side = Px(ThumbSide);
                    double scale = Math.Min((double)side / Math.Max(1, found.Width), (double)side / Math.Max(1, found.Height));
                    int width = Math.Max(1, (int)Math.Round(found.Width * Math.Min(1.0, scale)));
                    int height = Math.Max(1, (int)Math.Round(found.Height * Math.Min(1.0, scale)));
                    return new Bitmap(found, new Size(width, height));
                }
            }
            catch (ArgumentException) { return null; }
            catch (IOException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
            catch (OutOfMemoryException) { return null; }
            catch (System.Runtime.InteropServices.ExternalException) { return null; }
        }

        /// The thumbnails as the pictures stand: one tile each - the picture on the canvas's inset, a hairline round it -
        /// and its Remove under it.
        private void ShowThumbs()
        {
            if (editorThumbs == null) return;
            editorThumbs.SuspendLayout();
            var shown = new List<Control>();
            foreach (Control tile in editorThumbs.Controls) shown.Add(tile);
            foreach (Control old in shown) { editorThumbs.Controls.Remove(old); old.Dispose(); }
            for (int i = 0; i < editorImages.Count; i++)
            {
                EditorImage image = editorImages[i];
                string name = Word("page.editor.images.picture", "Picture {n}", "n", i + 1);
                var tile = new FlowLayoutPanel();
                tile.FlowDirection = FlowDirection.TopDown;
                tile.WrapContents = false;
                tile.AutoSize = true;
                tile.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                tile.Margin = Pad(0, 2, 12, 6);
                tile.BackColor = Card;
                var picture = new PictureBox();
                picture.Size = new Size(Px(ThumbSide), Px(ThumbSide));
                picture.SizeMode = PictureBoxSizeMode.CenterImage;
                picture.BackColor = Palette.Inset;
                picture.Image = image.Thumb;
                picture.AccessibleName = name;
                picture.AccessibleRole = AccessibleRole.Graphic;
                picture.Margin = new Padding(0);
                picture.Paint += delegate(object sender, PaintEventArgs e)
                {
                    var box = (PictureBox)sender;
                    using (var pen = new Pen(Palette.Line))
                        e.Graphics.DrawRectangle(pen, 0, 0, box.Width - 1, box.Height - 1);
                };
                tile.Controls.Add(picture);
                int index = i;
                Button remove = MakeButton(Word("page.editor.images.remove", "Remove"), false, delegate { RemoveImage(index); });
                remove.AccessibleName = Word("page.editor.images.remove", "Remove") + " " + name;
                remove.Margin = Pad(0, 4, 0, 0);
                tile.Controls.Add(remove);
                editorThumbs.Controls.Add(tile);
                if (editorDialog != null) TakeDrops(tile);
            }
            editorThumbs.Visible = editorImages.Count > 0;
            editorThumbs.ResumeLayout(true);
        }

        /// Remove under a thumbnail: that picture taken off the message (its copy, if it had one, goes when it is saved).
        private void RemoveImage(int index)
        {
            if (index < 0 || index >= editorImages.Count) return;
            EditorImage image = editorImages[index];
            editorImages.RemoveAt(index);
            if (image.Thumb != null) image.Thumb.Dispose();
            editorSaid.Text = "";
            ShowThumbs();
            ShowEditorState();
        }

        /// The request's pictures - each new one by its file, each kept one by its copy's id - or null where it names none
        /// and the message had none, so the request is the one it was before pictures.
        private string ImagesArgument()
        {
            if (editorImages.Count == 0 && !editorHadImages) return null;
            var argument = new System.Text.StringBuilder("[");
            for (int i = 0; i < editorImages.Count; i++)
            {
                if (i > 0) argument.Append(',');
                EditorImage image = editorImages[i];
                if (image.Id != null) argument.Append("{\"id\":").Append(Json.Escape(image.Id)).Append('}');
                else argument.Append("{\"path\":").Append(Json.Escape(image.Path)).Append('}');
            }
            return argument.Append(']').ToString();
        }

        /// The request Save and return sends, or null where a field it needs has nothing chosen.
        private string EditorArgument()
        {
            var conversation = editorConversation.SelectedItem as Choice;
            var when = editorWhen.SelectedItem as Choice;
            if (conversation == null || when == null) return null;
            var argument = new System.Text.StringBuilder("{");
            // v0.6.20: a steer names its conversation and its words alone; it goes now, or not at all.
            if (when.Value == "steer")
                return argument.Append("\"thread_id\":").Append(Json.Escape(conversation.Value))
                               .Append(",\"words\":").Append(Json.Escape(editorWords.Box.Text.Replace("\r\n", "\n")))
                               .Append(",\"generation\":").Append(AdvancedGeneration()).Append('}').ToString();
            if (editorPrompt >= 0) argument.Append("\"prompt\":").Append(editorPrompt.ToString(CultureInfo.InvariantCulture));
            else argument.Append("\"thread_id\":").Append(Json.Escape(conversation.Value));
            argument.Append(",\"words\":").Append(Json.Escape(editorWords.Box.Text.Replace("\r\n", "\n")));
            if (when.Value == "after_turn") argument.Append(",\"trigger\":\"after_turn\",\"while_running\":\"queue\"");
            else
            {
                var hour = editorHour.SelectedItem as Choice;
                if (hour == null) return null;
                double at = NextHour(int.Parse(hour.Value, CultureInfo.InvariantCulture));
                bool series = when.Value == "day" || when.Value == "week";
                argument.Append(",\"trigger\":").Append(Json.Escape(series ? "recurring" : "at_time"))
                        .Append(",\"at\":").Append(at.ToString("0", CultureInfo.InvariantCulture));
                if (series)
                {
                    var times = editorTimes.SelectedItem as Choice;
                    argument.Append(",\"every\":").Append(Json.Escape(when.Value))
                            .Append(",\"occurrences\":").Append(times == null ? "1" : times.Value);
                }
                argument.Append(",\"while_running\":").Append(Json.Escape(editorMode.Value == "queue" ? "queue" : "wait"));
            }
            var depends = editorDepends.SelectedItem as Choice;
            argument.Append(",\"depends\":").Append(depends != null && depends.Value == "yes" ? "true" : "false");
            string pictures = ImagesArgument();
            if (pictures != null) argument.Append(",\"images\":").Append(pictures);
            argument.Append(",\"generation\":").Append(AdvancedGeneration()).Append('}');
            return argument.ToString();
        }

        /// Save and return: the bridge's add or edit. Taken, the dialog closes and the saved row waits to be chosen; refused,
        /// the refusal is said above the buttons and every field stays as typed.
        private void SaveEditor(Form dialog)
        {
            if (busy > 0 || advancedListing == null || editorSave == null || !editorSave.Enabled) return;
            string argument = EditorArgument();
            if (argument == null) return;
            bool editing = editorPrompt >= 0;
            var chosen = editorWhen.SelectedItem as Choice;
            bool steer = !editing && chosen != null && chosen.Value == "steer";
            editorSave.Enabled = false;
            editorSaid.Text = "";
            AdvancedCall(steer ? "advanced-steer" : editing ? "advanced-prompt-edit" : "advanced-prompt-add", argument, true,
                         delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (dialog.IsDisposed || editorSaid == null) return;
                if (AdvancedDone(result))
                {
                    editorTaken = true;
                    editorSteered = steer;
                    editorSaved = !steer && Get(result, "prompt") is double ? Whole(Get(result, "prompt")) : -1;
                    advancedPrompts = result;
                    dialog.DialogResult = DialogResult.OK;
                    if (dialog.Visible) dialog.Close();
                    return;
                }
                string refusal = Str(result, "refusal");
                editorSaid.Text = steer ? SteerRefusal(refusal)
                    : editing && refusal == "invalid_request"
                    ? Word("page.refused.prompt_moved", "It is no longer waiting, so it can no longer be changed.")
                    : PromptRefusal(refusal);
                ShowEditorState();
            });
        }

        // ---------------------------------------------------------------- the steer (v0.6.20)
        private const string SteerId = "steer_send";

        /// Whether Steer the running turn stands on now - on, not watched: a watched steer would never be sent.
        private bool SteerOn()
        {
            Dictionary<string, object> steer = advancedListing == null ? null : AdvancedItem(SteerId);
            return steer != null && Str(steer, "state") == StateArmed;
        }

        /// What a refused steer says above the buttons: no turn running, one still waiting there, its caps - else as a
        /// message's refusal says it.
        private string SteerRefusal(string refusal)
        {
            if (refusal == "no_turn_running")
                return Word("page.refused.no_turn_running", "No turn is running in that conversation, so there is nothing to steer. Nothing was sent.");
            if (refusal == "being_sent")
                return Word("page.refused.steer_waiting", "A steer for that conversation still waits to go. Wait until History shows what came of it.");
            if (refusal == "queue_full")
                return Word("page.refused.steer_full", "As many steers were asked for as may: 30 in a conversation and 60 in all in a day.");
            return PromptRefusal(refusal);
        }
    }
}

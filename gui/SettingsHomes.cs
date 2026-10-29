// Codex Auto Resume - the Codex homes watched (v0.6.15-beta): a card of Settings > Advanced, after the limits.
//
// The default Codex home is always watched. Up to three more can be added here and only here - MCP refuses the
// setting by name, and no generated editor draws it - each a folder and an alias of 1 to 32 characters, which
// Pending and History show beside a record of that home when there are several. Like the power action's card it
// is no editor: Add, Rename and Remove write at once through the bridge's `update`, which checks every folder
// against this PC (homes.strict) and answers a refusal in words a person can act on; Save does not change it.
// What the watcher found of each home - watched, another watcher has it, unavailable, the Codex app on another
// home, the same folder as another, being removed - comes with every status read (`codex_homes`).
//
// v0.6.18: a Codex home this PC's Codex uses that is not watched yet is suggested on the card - "Codex also uses
// <folder>. Watch it too?" with Add, which adds it as Add a Codex home... does, and Not now, which sets it aside for
// good - asked of the bridge (`home-suggestion`, homefind.py) each time the card is shown and after each change of
// the homes; never added on its own. A switch under it turns the looking off.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        /// At most this many homes beside the default one (homes.MAX_EXTRA), and an alias at most this long.
        internal const int HomesMax = 3;
        internal const int HomeAliasMax = 32;

        private TableLayoutPanel homesCard, homesRows;
        private Label homesWarning, homesRefusal;
        private Button homesAdd;
        /// The homes as the last status said them: `codex_homes.homes`, each {alias, path, state}, the default first.
        private List<Dictionary<string, object>> homesShown = new List<Dictionary<string, object>>();
        private string homesSignature;
        /// v0.6.18: the suggestion - its line, its Add and Not now, and the switch that turns the looking off.
        private Label homesSuggestLine;
        private FlowLayoutPanel homesSuggestActions;
        private Button homesSuggestAdd;
        private CheckBox homesSuggestSwitch;
        private string homesSuggested;
        private bool homesSuggestReading, homesSuggestSetting;

        /// Builds the card at the end of `stack` - Settings > Advanced, after the limits.
        private void BuildHomes(TableLayoutPanel stack)
        {
            homesCard = NewGroup(S("homes.title", "Codex homes"), stack);
            homesCard.Controls[0].Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;
            homesCard.Controls.Add(HelpText(S("homes.help",
                "Your default Codex home is always watched. Add up to three more; a conversation in one is resumed only while the Codex app was started on that home (CODEX_HOME set before it starts). It applies at once; Save does not change it.")));
            homesRows = new TableLayoutPanel();
            homesRows.AutoSize = true;
            homesRows.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            homesRows.ColumnCount = 1;
            homesRows.Dock = DockStyle.Top;
            homesRows.Margin = Pad(0, 2, 0, 2);
            // On the card's own ground, as everything else on a card is (issue #34: a plain table drew a grey band).
            homesRows.BackColor = Palette.Card;
            homesCard.Controls.Add(homesRows);
            homesWarning = HelpText("");
            homesCard.Controls.Add(homesWarning);
            homesRefusal = HelpText("");
            homesRefusal.ForeColor = Palette.Danger;
            homesCard.Controls.Add(homesRefusal);
            // An empty line takes no room until it has something to say (issue #34: a tall gap).
            ShowLine(homesWarning, "");
            ShowLine(homesRefusal, "");
            // On the card itself, as the Tools card's buttons are, not in a page's button row.
            homesAdd = MakeButton(S("homes.add", "Add a Codex home..."), false, delegate { AddHome(); });
            homesAdd.Anchor = AnchorStyles.Left | AnchorStyles.Top;
            homesAdd.Margin = Pad(0, 6, 0, 0);
            homesCard.Controls.Add(homesAdd);
            BuildHomeSuggestion();
            ShowHomes();
        }

        /// v0.6.18: the suggestion's line and its two buttons, hidden until there is one, and its switch with what it
        /// looks at - at the card's foot, after Add a Codex home...
        private void BuildHomeSuggestion()
        {
            homesSuggestLine = HelpText("");
            homesSuggestLine.ForeColor = Ink;
            homesSuggestLine.Margin = Pad(0, 10, 0, 2);
            homesCard.Controls.Add(homesSuggestLine);
            homesSuggestActions = ButtonRow();
            homesSuggestActions.BackColor = Palette.Card;   // the card's ground (issue #34)
            homesSuggestActions.Dock = DockStyle.None;
            homesSuggestActions.Padding = Pad(0, 2, 0, 6);
            homesSuggestAdd = MakeButton(S("homes.suggest.add", "Add"), false, delegate { AddSuggestedHome(); });
            homesSuggestActions.Controls.Add(homesSuggestAdd);
            homesSuggestActions.Controls.Add(MakeButton(S("action.not_now", "Not now"), false, delegate { DismissSuggestedHome(); }));
            homesCard.Controls.Add(homesSuggestActions);
            ShowLine(homesSuggestLine, "");
            homesSuggestActions.Visible = false;
            homesSuggestSwitch = NewCheck(S("homes.suggest.switch", "Suggest Codex homes found on this PC"), true, false);
            homesSuggestSwitch.Margin = Pad(0, 10, 0, 2);
            homesSuggestSwitch.CheckedChanged += delegate { if (!homesSuggestSetting) WriteSuggestSwitch(homesSuggestSwitch.Checked); };
            homesCard.Controls.Add(homesSuggestSwitch);
            homesCard.Controls.Add(HelpText(S("homes.suggest.help",
                "Looks only at the CODEX_HOME variable of your Windows account and at the Codex app's own list of where it has run. Nothing is added until you choose Add.")));
        }

        /// Asks for the suggestion each time the card is shown: Settings is the page and Advanced the section.
        private void LoadHomeSuggestionWhereShown()
        {
            if (currentPage != "settings" || currentSection != "advanced") return;
            LoadHomeSuggestion();
        }

        /// On a worker, as every call is (CallAsync). Never while the window is being audited.
        private void LoadHomeSuggestion()
        {
            if (homesCard == null || auditing || homesSuggestReading) return;
            homesSuggestReading = true;
            CallAsync("home-suggestion", null, delegate(Dictionary<string, object> reply)
            {
                homesSuggestReading = false;
                if (Ok(reply)) ApplyHomeSuggestion(Map(reply, "result"));
            });
        }

        /// The line as the bridge says it: the folder offered with Add and Not now, or - every home added - that it
        /// cannot be added, with Not now alone; nothing when there is none or the switch is off.
        private void ApplyHomeSuggestion(Dictionary<string, object> suggestion)
        {
            if (homesSuggestLine == null || suggestion == null) return;
            homesSuggested = Equals(Get(suggestion, "on"), true) ? Str(suggestion, "path") : null;
            bool full = Equals(Get(suggestion, "full"), true);
            if (string.IsNullOrEmpty(homesSuggested))
            {
                homesSuggested = null;
                ShowLine(homesSuggestLine, "");
                homesSuggestActions.Visible = false;
                return;
            }
            ShowLine(homesSuggestLine, full
                ? S("homes.suggest.full", "Codex also uses {path}, but three Codex homes are already added. Remove one to watch it.", "path", homesSuggested)
                : S("homes.suggest.line", "Codex also uses {path}. Watch it too?", "path", homesSuggested));
            homesSuggestAdd.Visible = !full;
            homesSuggestActions.Visible = true;
        }

        /// Add: the folder offered, named as Add a Codex home... names one, through the same write (WriteHomes).
        private void AddSuggestedHome()
        {
            string path = homesSuggested;
            if (path == null || Extras().Count >= HomesMax) return;
            string name = Path.GetFileName(path.TrimEnd('\\', '/'));
            string alias = AskAlias(string.IsNullOrEmpty(name) ? path : name);
            if (alias == null) return;
            var homes = Extras();
            var entry = new Dictionary<string, object>();
            entry["path"] = path;
            entry["alias"] = alias;
            homes.Add(entry);
            WriteHomes(homes);
        }

        /// Not now: the folder is set aside for good, and whatever is offered next is shown.
        private void DismissSuggestedHome()
        {
            string path = homesSuggested;
            if (path == null) return;
            var argument = new Dictionary<string, object>();
            argument["path"] = path;
            CallAsync("home-dismiss", Json.Write(argument), delegate(Dictionary<string, object> reply)
            {
                if (Ok(reply)) ApplyHomeSuggestion(Map(reply, "result"));
                else ShowLine(homesRefusal, S("homes.refused", "Not saved: {reason}", "reason", Str(reply, "error") ?? ""));
            });
        }

        /// The switch written at once, as the card's other changes are, and the suggestion asked again.
        private void WriteSuggestSwitch(bool on)
        {
            var changes = new Dictionary<string, object>();
            changes["home_suggestions"] = on;
            CallAsync("update", Json.Write(changes), delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    ShowLine(homesRefusal, S("homes.refused", "Not saved: {reason}", "reason", Str(reply, "error") ?? ""));
                    return;
                }
                LoadHomeSuggestion();
            });
        }

        /// From a status read (ApplyStatus): the homes and what the watcher found of each, and whether watching a
        /// second home is unproven on the Codex in force (MH, measured up to 0.162).
        private void ApplyHomesStatus(Dictionary<string, object> status)
        {
            if (homesCard == null || status == null) return;
            var view = Map(status, "codex_homes");
            var shown = new List<Dictionary<string, object>>();
            foreach (object entry in Items(view, "homes") ?? new List<object>())
            {
                var home = entry as Dictionary<string, object>;
                if (home != null) shown.Add(home);
            }
            homesShown = shown;
            // v0.6.18: the switch as the settings hold it, set without writing it back.
            bool suggesting = !Equals(Get(Map(status, "settings"), "home_suggestions"), false);
            if (homesSuggestSwitch != null && homesSuggestSwitch.Checked != suggesting)
            {
                homesSuggestSetting = true;
                homesSuggestSwitch.Checked = suggesting;
                homesSuggestSetting = false;
            }
            ShowLine(homesWarning, Equals(Get(view, "unmeasured"), true)
                ? S("homes.unmeasured", "Watching a second Codex home was proven on Codex 0.162; on this Codex it is unproven.")
                : "");
            ShowHomes();
        }

        /// The rows: one line per home - its alias, its folder and what the watcher found - with Rename and Remove for
        /// each one added here. Rebuilt only when what it shows changed.
        private void ShowHomes()
        {
            if (homesRows == null) return;
            var signature = new System.Text.StringBuilder();
            foreach (var home in homesShown)
                signature.Append(Str(home, "alias")).Append('|').Append(Str(home, "path")).Append('|')
                         .Append(Str(home, "state")).Append('\n');
            string key = signature.ToString();
            homesAdd.Enabled = Extras().Count < HomesMax;
            if (key == homesSignature) return;
            homesSignature = key;
            homesRows.SuspendLayout();
            homesRows.Controls.Clear();
            foreach (var home in homesShown)
            {
                bool extra = Str(home, "key") != "";
                var line = HelpText(HomeLine(extra ? Str(home, "alias") : S("homes.default", "Default"), Str(home, "path"),
                                             HomeStateName(Str(home, "state"))));
                line.ForeColor = Ink;
                homesRows.Controls.Add(line);
                if (!extra) continue;
                FlowLayoutPanel actions = ButtonRow();
                actions.BackColor = Palette.Card;   // the card's ground (issue #34)
                actions.Dock = DockStyle.None;
                actions.Padding = Pad(0, 2, 0, 6);
                string path = Str(home, "path");
                actions.Controls.Add(MakeButton(S("homes.rename", "Rename..."), false, delegate { RenameHome(path); }));
                actions.Controls.Add(MakeButton(S("homes.remove", "Remove"), false, delegate { RemoveHome(path); }));
                homesRows.Controls.Add(actions);
            }
            homesRows.ResumeLayout();
        }

        /// A home's line: the parts that have text, joined - never "Default ·  · Watched" for a home whose folder the
        /// status does not name (issue #34).
        internal static string HomeLine(params string[] parts)
        {
            var kept = new List<string>();
            foreach (string part in parts)
                // v0.6.20: each part one run in a line written right to left - a folder's path above all (Mirror.Embed).
                if (!string.IsNullOrEmpty(part) && part.Trim().Length > 0) kept.Add(Mirror.Embed(part));
            return string.Join(" · ", kept.ToArray());
        }

        /// What the watcher found of a home, in words (HomeState). Written as tests, not a switch: a switch of this many
        /// strings makes the compiler emit a class it names at random (build/normalize_pe.py).
        private string HomeStateName(string state)
        {
            if (state == "watched") return S("homes.state.watched", "Watched");
            if (state == "lock_busy") return S("homes.state.lock_busy", "Another watcher has it");
            if (state == "unavailable") return S("homes.state.unavailable", "Folder unavailable");
            if (state == "other_home") return S("homes.state.other_home", "The Codex app runs on another home");
            if (state == "duplicate") return S("homes.state.duplicate", "The same folder as another home");
            if (state == "retiring") return S("homes.state.retiring", "Removing: waiting for what was sent there to settle");
            return S("homes.state.waiting", "Not looked at yet");
        }

        /// The homes added here, as the setting holds them: {path, alias}, in their order.
        private List<Dictionary<string, object>> Extras()
        {
            var found = new List<Dictionary<string, object>>();
            foreach (var home in homesShown)
            {
                if (Str(home, "key") == "" || Str(home, "path") == null) continue;
                var entry = new Dictionary<string, object>();
                entry["path"] = Str(home, "path");
                entry["alias"] = Str(home, "alias") ?? "";
                found.Add(entry);
            }
            return found;
        }

        private void AddHome()
        {
            if (Extras().Count >= HomesMax) return;
            string path;
            using (var picker = new FolderBrowserDialog())
            {
                picker.Description = S("homes.pick", "Choose a Codex home: a folder with Codex's state in it");
                picker.ShowNewFolderButton = false;
                if (picker.ShowDialog(this) != DialogResult.OK || string.IsNullOrEmpty(picker.SelectedPath)) return;
                path = picker.SelectedPath;
            }
            string name = Path.GetFileName(path.TrimEnd('\\', '/'));
            string alias = AskAlias(string.IsNullOrEmpty(name) ? path : name);
            if (alias == null) return;
            var homes = Extras();
            var entry = new Dictionary<string, object>();
            entry["path"] = path;
            entry["alias"] = alias;
            homes.Add(entry);
            WriteHomes(homes);
        }

        private void RenameHome(string path)
        {
            var homes = Extras();
            foreach (var home in homes)
            {
                if (Str(home, "path") != path) continue;
                string alias = AskAlias(Str(home, "alias"));
                if (alias == null) return;
                home["alias"] = alias;
                WriteHomes(homes);
                return;
            }
        }

        private void RemoveHome(string path)
        {
            var homes = Extras();
            homes.RemoveAll(delegate(Dictionary<string, object> home) { return Str(home, "path") == path; });
            WriteHomes(homes);
        }

        /// The homes written at once (`update`), and the card redrawn from the next status. A refusal is shown under
        /// the rows in the settings layer's own words, and nothing changed.
        private void WriteHomes(List<Dictionary<string, object>> homes)
        {
            var list = new List<object>();
            foreach (var home in homes) list.Add(home);
            var changes = new Dictionary<string, object>();
            changes["codex_homes"] = list;
            ShowLine(homesRefusal, "");
            CallAsync("update", Json.Write(changes), delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    ShowLine(homesRefusal, S("homes.refused", "Not saved: {reason}", "reason", Str(reply, "error") ?? ""));
                    return;
                }
                homesSignature = null;
                RefreshNow();
                LoadHomeSuggestion();
            });
        }

        /// An alias for a home, asked in a small dialog: 1 to 32 characters on one line. Null when cancelled.
        private string AskAlias(string current)
        {
            using (var dialog = new Form())
            {
                dialog.Text = S("homes.alias", "Name for this Codex home");
                dialog.Font = Font;
                dialog.BackColor = Canvas;
                dialog.ForeColor = Ink;
                Soft.TitleBar(dialog);
                dialog.StartPosition = FormStartPosition.CenterParent;
                dialog.MinimizeBox = false;
                dialog.MaximizeBox = false;
                dialog.ShowInTaskbar = false;
                dialog.ShowIcon = false;
                dialog.ClientSize = new Size(Px(420), Px(170));
                var body = new SoftStack();
                body.Dock = DockStyle.Fill;
                body.ColumnCount = 1;
                body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
                body.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
                body.Padding = Pad(16, 16, 16, 0);
                body.BackColor = Canvas;
                var area = new SoftTextArea();
                area.Dock = DockStyle.Fill;
                area.Margin = Pad(0, 6, 0, 2);
                area.Font = Font;
                area.Box.Font = Font;
                area.OneLine = true;            // issue #34: the line centred, never cut off
                area.Box.MaxLength = HomeAliasMax;
                string start = current ?? "";
                area.Box.Text = start.Length > HomeAliasMax ? start.Substring(0, HomeAliasMax) : start;
                area.Box.AccessibleName = S("homes.alias", "Name for this Codex home");
                area.Height = Px(38);
                body.Controls.Add(area);
                dialog.Controls.Add(body);
                string chosen = null;
                FlowLayoutPanel buttons = ButtonRow();
                buttons.FlowDirection = FlowDirection.RightToLeft;
                buttons.Padding = Pad(0, 12, 16, 16);
                Button save = MakeButton(S("action.save", "Save"), true, delegate
                {
                    string text = (area.Box.Text ?? "").Trim();
                    if (text.Length == 0) return;
                    chosen = text;
                    dialog.Close();
                });
                Button cancel = MakeButton(S("action.cancel", "Cancel"), false, delegate { dialog.Close(); });
                buttons.Controls.Add(save);
                buttons.Controls.Add(cancel);
                buttons.Dock = DockStyle.Bottom;
                dialog.Controls.Add(buttons);
                dialog.AcceptButton = save;
                dialog.CancelButton = cancel;
                dialog.ShowDialog(this);
                return chosen;
            }
        }
    }
}

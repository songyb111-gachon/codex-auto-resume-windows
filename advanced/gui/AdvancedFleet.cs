// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - See your other PCs: the Overview's Other PCs list, and the card this PC's name and folder are chosen on
// (v0.6.22, plans/v0619-design/D-remote.md).
//
// While the capability is on, the Overview gains a card under its two rows of cards: flat hairline rows, one for each other
// PC whose file is in the folder - its name, what it said, how many wait, its next check and when it wrote - and a line saying
// how the folder stands where it waits on something. A file older than a week is greyed, "not seen since", and one written
// ahead of this PC's clock says so instead of a time. There is nothing to press on a row: no action on a peer exists. Off,
// there is no card and the Overview is the standard window's. The rows are the bridge's checked words and bounded numbers
// (control/fleet.py); a synced file's text never reaches this window unchecked.
//
// While it is on or watched, its column on the Advanced features page has a card: this PC's name, the folder (chosen in
// Windows' own folder dialog, never typed) and Save. Off, with a folder saved, the card says only that this PC's file stays
// there. advanced-fleet is read once a minute at most, from the snapshots, and never by a window that is being audited.
//
// Nothing here draws anything the window does not draw already: the card, its heading, the list and its rows (DrawCell, a
// greyed row as Install another version greys one), the help lines, the box and the buttons are the window's own, in both
// themes and both designs, mirrored for Arabic and Hebrew by the window. It opens no window of its own.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string FleetId = "fleet_view";
        private const int FleetReadMilliseconds = 60000;
        // How many rows the list shows before it scrolls on its own bar, and each row's and the heading's height.
        private const int FleetRowsShown = 6;
        private const int FleetRowHeight = 34;

        // advanced-fleet's last answer, or null; whether the status says the capability is on; when it was last asked.
        private Dictionary<string, object> advancedFleet;
        private bool fleetOn, fleetReading, fleetEverRead;
        private int fleetReadAt;
        private string fleetShown;
        // The Overview's card, made the first time there is something to show.
        private TableLayoutPanel fleetCard;
        private ListView fleetList;
        private Control fleetHost;
        private Label fleetSaid;
        // The Advanced page's card as it was built.
        private SoftTextArea fleetAlias;
        private Label fleetFolderLine;
        private Button fleetPick, fleetSave;

        // ---------------------------------------------------------------- the Overview
        /// From each snapshot: whether the capability is on (surfaces.fleet_view), and the list read again once a minute.
        private void FleetApplied(Dictionary<string, object> reply)
        {
            fleetOn = Equals(Get(Map(Map(reply, "status"), "advanced"), "fleet_on"), true);
            if (!fleetOn)
            {
                ShowFleet();
                return;
            }
            if (fleetReading || (auditing && advancedScript == null)) { ShowFleet(); return; }
            if (fleetEverRead && unchecked(Environment.TickCount - fleetReadAt) < FleetReadMilliseconds) { ShowFleet(); return; }
            fleetReading = true;
            ReadFleet(delegate { fleetReading = false; });
        }

        /// Read advanced-fleet, keep it, and show it; `done` once it is shown.
        private void ReadFleet(MethodInvoker done)
        {
            fleetEverRead = true;
            fleetReadAt = Environment.TickCount;
            AdvancedCall("advanced-fleet", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedFleet = AdvancedDone(result) ? result : null;
                ShowFleet();
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        /// The card shown as the last answer says, or hidden while the capability is off.
        private void ShowFleet()
        {
            if (!fleetOn || advancedFleet == null)
            {
                if (fleetCard != null && OwnVisible(fleetCard))
                {
                    fleetCard.Visible = false;
                    fleetShown = null;
                    OverviewFitAgain();
                }
                return;
            }
            if (overviewGrid == null) return;
            if (fleetCard == null) BuildFleetCard();
            string written = AdvancedWritten(advancedFleet);
            if (written == fleetShown && OwnVisible(fleetCard)) return;
            fleetShown = written;
            List<object> peers = Items(advancedFleet, "peers") ?? new List<object>();
            fleetList.BeginUpdate();
            fleetList.Items.Clear();
            foreach (object entry in peers)
            {
                var peer = entry as Dictionary<string, object>;
                if (peer != null) fleetList.Items.Add(FleetRow(peer));
            }
            fleetList.EndUpdate();
            MeasureCells(fleetList);
            int rows = Math.Min(fleetList.Items.Count, FleetRowsShown);
            fleetHost.Visible = rows > 0;
            fleetHost.Height = Px(FleetRowHeight) * (rows + 1) + Px(4);
            string said = FleetSaid();
            fleetSaid.Text = said;
            fleetSaid.Visible = said.Length > 0;
            fleetCard.Visible = true;
            OverviewFitAgain();
        }

        private void OverviewFitAgain()
        {
            if (overviewGrid != null && overviewGrid.Parent != null) overviewGrid.Parent.PerformLayout();
        }

        /// How much the Overview keeps under its two rows of cards (FitOverview): the card, while it shows.
        partial void OverviewRoomAsked(ref int under)
        {
            if (fleetCard == null || !OwnVisible(fleetCard) || overviewGrid == null) return;
            int across = Math.Max(1, overviewGrid.DisplayRectangle.Width - fleetCard.Margin.Horizontal);
            under += fleetCard.GetPreferredSize(new Size(across, 0)).Height + fleetCard.Margin.Vertical;
        }

        private void BuildFleetCard()
        {
            fleetCard = MakeCard(Word("page.fleet.title", "Other PCs"));
            fleetCard.Dock = DockStyle.None;
            fleetCard.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;
            fleetCard.Margin = Pad(0, Brand.PageGap, 0, 0);
            fleetSaid = HelpText("");
            fleetSaid.Visible = false;
            fleetCard.Controls.Add(fleetSaid);
            // Flat hairline rows, owner-drawn as every list here is (DrawCell), on the soft scroll bar.
            fleetList = List(Word("page.fleet.title", "Other PCs"),
                             Col(Word("page.fleet.col.pc", "PC"), 190), Col(Word("page.fleet.col.state", "State"), 150),
                             Col(Word("page.fleet.col.waiting", "Waiting"), 80), Col(Word("page.fleet.col.next", "Next check"), 140),
                             Col(Word("page.fleet.col.written", "Written"), 150));
            // The window's one list host, out of the card ListCard gives it: this card is the list's card, never a tile in a tile.
            Control made = ListCard(fleetList);
            Control host = made.Controls[0];
            made.Controls.Remove(host);
            made.Dispose();
            host.Dock = DockStyle.None;
            host.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;
            host.Margin = Pad(0, 2, 0, 0);
            fleetHost = host;
            fleetCard.Controls.Add(host);
            fleetCard.Visible = false;
            overviewGrid.Controls.Add(fleetCard, 0, OverviewRows);
            overviewGrid.SetColumnSpan(fleetCard, 2);
        }

        private ListViewItem FleetRow(Dictionary<string, object> peer)
        {
            string seen = Str(peer, "seen");
            double written = Number(peer, "written_at"), due = Number(peer, "next_check_at");
            var row = new ListViewItem(Str(peer, "alias") ?? "");
            bool old = seen == "old";
            row.SubItems.Add(old ? Word("page.fleet.state.not_seen", "not seen since") : FleetState(peer));
            row.SubItems.Add(old ? "" : Whole(Get(peer, "pending")).ToString(CultureInfo.CurrentCulture));
            row.SubItems.Add(due > 0 ? ClockTime(due) : "");
            row.SubItems.Add(seen == "clock" ? Word("page.fleet.state.clock", "its clock differs from this PC's")
                             : old ? When(written) : ClockTime(written));
            // A row whose PC has not been seen for a week: its words quiet and its state a grey chip, as a refused row (DrawCell).
            if (old) row.Tag = new Dictionary<string, object> { { "code", PickUnavailable } };
            return row;
        }

        private string FleetState(Dictionary<string, object> peer)
        {
            if (Str(peer, "watcher") == "stopped") return Word("page.fleet.state.stopped", "stopped");
            string recovery = Str(peer, "recovery");
            if (recovery == "paused") return Word("page.fleet.state.paused", "paused");
            if (recovery == "observe_only") return Word("page.fleet.state.observing", "observing");
            return Word("page.fleet.state.running", "running");
        }

        /// What the card says over its rows: how the folder stands, and what was ignored - nothing while all is well.
        private string FleetSaid()
        {
            var said = new List<string>();
            string stand = FleetStand(Str(advancedFleet, "stand"));
            if (stand != null) said.Add(stand);
            else if ((Items(advancedFleet, "peers") ?? new List<object>()).Count == 0)
                said.Add(Word("page.fleet.stand.none", "No other PC has written here yet."));
            int ignored = Whole(Get(advancedFleet, "ignored"));
            if (ignored > 0)
                said.Add(Word("page.fleet.ignored", "{n} files here were ignored: too large, a link, or not what this program writes.",
                              "n", Mirror.Embed(ignored.ToString(CultureInfo.CurrentCulture))));
            return string.Join(" ", said.ToArray());
        }

        /// The folder's stand in words, or null where it is well.
        private string FleetStand(string stand)
        {
            if (stand == "unset")
                return Word("page.fleet.stand.unset", "Give this PC a name and choose a folder on the Advanced features page.");
            if (stand == "missing")
                return Word("page.fleet.stand.missing", "The folder cannot be found. It waits, and tries again in 5 minutes.");
            if (stand == "held")
                return Word("page.fleet.stand.held", "A file in the folder is held, perhaps by your sync tool. It waits, and tries again in 5 minutes.");
            if (stand == "not_ours")
                return Word("page.fleet.stand.not_ours", "A file with this PC's name is there that this PC did not write, so it was left alone. Give each PC its own name.");
            if (stand == "inside" || stand == "link" || stand == "network" || stand == "invalid")
                return Word("page.fleet.stand.refused", "This folder cannot be used: it is inside this program's or Codex's folder, it is a link or a network path, or it is not a folder.");
            return null;
        }

        // ---------------------------------------------------------------- the Advanced features page
        /// What the card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string FleetCardShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != FleetId) return "";
            return AdvancedWritten(advancedFleet);
        }

        private void ForgetFleetCard()
        {
            fleetAlias = null;
            fleetFolderLine = null;
            fleetPick = fleetSave = null;
        }

        private string FleetDraft(string key, string saved)
        {
            string draft;
            return resetDrafts.TryGetValue(key, out draft) ? draft : saved ?? "";
        }

        /// The open capability's card: this PC's name and the folder - or, off with a folder saved, that its file stays there.
        private void BuildFleet(Dictionary<string, object> item)
        {
            ForgetFleetCard();
            if (Str(item, "id") != FleetId || advancedFleet == null) return;
            string title = Word("page.fleet.card", "This PC in the shared folder");
            if (!Standing(item))
            {
                if (string.IsNullOrEmpty(Str(advancedFleet, "folder"))) return;
                TableLayoutPanel left = NewGroup(title, advancedStack);
                left.Controls.Add(HelpText(Word("page.fleet.off_note",
                    "Off, this PC's file stays in the folder, and the other PCs show it greyed once it is a week old. Delete it there if you want it gone.")));
                return;
            }
            TableLayoutPanel card = NewGroup(title, advancedStack);
            card.Controls.Add(HelpText(Word("page.fleet.help",
                "Choose a folder your own sync tool keeps the same on your PCs. This PC writes its status there and reads the others'. This program never contacts another PC.")));
            string name = Word("page.fleet.alias", "This PC's name");
            card.Controls.Add(Caption(name));
            fleetAlias = OneLine(name, 260, 32);
            fleetAlias.Box.Text = FleetDraft("fleet.alias", Str(advancedFleet, "alias"));
            fleetAlias.Box.TextChanged += delegate
            {
                resetDrafts["fleet.alias"] = fleetAlias.Box.Text;
                UpdateFleetButtons(busy == 0);
            };
            card.Controls.Add(fleetAlias);
            card.Controls.Add(HelpText(Word("page.fleet.alias_help", "1 to 32 letters, digits, spaces or hyphens. Give each PC its own.")));
            card.Controls.Add(Caption(Word("page.fleet.folder", "Folder")));
            string folder = FleetDraft("fleet.folder", Str(advancedFleet, "folder"));
            fleetFolderLine = HelpText(folder.Length > 0 ? folder : Word("page.fleet.no_folder", "No folder chosen yet."));
            fleetFolderLine.ForeColor = Ink;
            card.Controls.Add(fleetFolderLine);
            fleetPick = CardButton(card, Word("page.fleet.pick", "Choose a folder..."), delegate { PickFleetFolder(); });
            fleetPick.Margin = Pad(0, 6, 0, 4);
            fleetSave = CardButton(card, Word("page.fleet.save", "Save"), delegate { SaveFleet(); });
            fleetSave.Margin = Pad(0, 4, 0, 4);
            string stand = Str(advancedFleet, "stand") == "unset" ? null : FleetStand(Str(advancedFleet, "stand"));
            if (stand != null) card.Controls.Add(HelpText(stand));
        }

        private void UpdateFleetButtons(bool idle)
        {
            if (fleetPick != null) fleetPick.Enabled = idle && advancedListing != null;
            if (fleetSave != null)
                fleetSave.Enabled = idle && advancedListing != null && fleetAlias != null && fleetAlias.Box.Text.Trim().Length > 0 &&
                                    FleetDraft("fleet.folder", Str(advancedFleet, "folder")).Length > 0;
        }

        /// Windows' own folder dialog: the folder is chosen, never typed.
        private void PickFleetFolder()
        {
            if (busy > 0) return;
            using (var picker = new FolderBrowserDialog())
            {
                picker.Description = Word("page.fleet.pick", "Choose a folder...");
                if (picker.ShowDialog(this) != DialogResult.OK || string.IsNullOrEmpty(picker.SelectedPath)) return;
                ChooseFleetFolder(picker.SelectedPath);
            }
        }

        private void ChooseFleetFolder(string path)
        {
            resetDrafts["fleet.folder"] = path;
            if (fleetFolderLine != null) fleetFolderLine.Text = path;
            UpdateFleetButtons(busy == 0);
        }

        private void SaveFleet()
        {
            if (busy > 0 || advancedListing == null || fleetAlias == null) return;
            string argument = "{\"alias\":" + Json.Escape(fleetAlias.Box.Text) + ",\"folder\":" +
                              Json.Escape(FleetDraft("fleet.folder", Str(advancedFleet, "folder"))) +
                              ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-fleet-save", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                {
                    resetDrafts.Remove("fleet.alias");
                    resetDrafts.Remove("fleet.folder");
                    ResetNote(Word("page.fleet.saved", "Saved. This PC writes its file at the next check."));
                }
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(FleetRefusal(result));
            });
        }

        private string FleetRefusal(Dictionary<string, object> result)
        {
            string problem = Str(result, "problem");
            if (problem == "alias")
                return Word("page.fleet.refused_alias", "That name cannot be used. Use 1 to 32 letters, digits, spaces or hyphens.");
            return FleetStand(problem) ?? ResetRefusal(Str(result, "refusal"));
        }
    }
}

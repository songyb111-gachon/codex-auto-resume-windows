// Codex Auto Resume - the layout audit: the window checking its own layout, on demand.
//
// Run by tests/test_gui_layout.py in every language at every scaling, and never by the window
// a person opens. It reports what overlaps, what is clipped and what is off its card, in the
// window's own measurements rather than a screenshot's.

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
        // ------------------------------------------------------------------ layout audit
        private static readonly System.Reflection.MethodInfo OwnState =
            typeof(Control).GetMethod("GetState", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        /// Every place the window's layout cuts something off, at `scale` and in the language of
        /// `stringsJson`: one line each, and an empty string when there is none.
        ///
        /// The window is built as it opens, at its opening size, with the Custom message and its
        /// per-kind editor showing, and every page and every Settings section is laid out in turn -
        /// filled from `snapshotJson`, a dashboard reply, when one is given, and the Diagnostics
        /// page's Codex compatibility card from the registry view the reply carries under
        /// `compatibility`, with the longest answer a refresh gives beside its button. It is never shown - it
        /// is not even a top-level window - and nothing is sent to it. Another scaling is stood in
        /// for this machine's by scaling DpiScale and the fonts together, which matched a real
        /// 144-DPI window to the pixel when the v0.6.4 clipping was measured. Reported are:
        ///   * a control that reaches past a container that does not scroll, or past the side of a
        ///     page that scrolls up and down;
        ///   * a page that would scroll sideways;
        ///   * the Overview, Pending or History scrolling at all (AuditScrolling);
        ///   * the Overview's rows against what FitOverview gives them (AuditRows): under the last row anything but the
        ///     page's own padding, as every page keeps under its last card - cards reaching into it, or a dead band over
        ///     it - rows of different heights where the page has room for them alike, cards in a row of different
        ///     heights, and a card taller than its content sits comfortably in;
        ///   * a name of Right now that wraps (AuditNames): its card has room for them whole;
        ///   * the Overview in the shortest window its rows' own tallest cards fit (AuditShortest) scrolling, leaving
        ///     space under its rows, cutting a card or its content off or putting a button out of its corner or over
        ///     text - or a window a pixel shorter not scrolling;
        ///   * a button an Overview card leads to (Lead) that is not within a pixel of its card's inner bottom-LEFT
        ///     corner, or that covers a line of text or has one within the scale's medium step above it (AuditLead);
        ///   * a button pinned to the bottom right of a block - the header's Start button, shown for it since the
        ///     watcher in a dashboard reply is running, and the Custom messages' Clear buttons - that is not within a
        ///     pixel of that corner, or that covers a line of text in its block (AuditPin);
        ///   * a list - Pending, History, and the Timeline dialog's - whose columns are wider than it is, which is what
        ///     shows a horizontal scroll bar, with the rows of the reply and with none (AuditLists): at the opening size
        ///     its columns share its width;
        ///   * a drop-down that is not one field high;
        ///   * text, a list's columns or other content that needs more room than it is drawn in,
        ///     and a status light too small for its glow.
        /// tests/test_gui_layout.py runs it in every language at five scalings.
        internal static string LayoutAudit(string schemaJson, string settingsJson, string stringsJson, string snapshotJson, double scale)
        {
            var findings = new List<string>();
            AuditedPins = 0;
            AuditedLists = 0;
            AuditedNotes = 0;
            AuditedShortest = 0;
            AuditedAlike = 0;
            AuditedWraps = 0;
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
                var snapshot = string.IsNullOrEmpty(snapshotJson) ? null : Json.Parse(snapshotJson) as Dictionary<string, object>;
                // A bridge rooted where nothing is: anything that still asked it would fail at once.
                string nowhere = Path.Combine(Path.GetTempPath(), "codex-auto-resume-layout-audit-" + Guid.NewGuid().ToString("N"));
                using (var form = new SettingsForm(new PersistentBridge(nowhere, new Bridge(nowhere)), catalog, windowFont))
                {
                    form.auditing = true;
                    // A child of Windows' parking window rather than a window of its own, so the
                    // screen it would open on neither clamps its size nor ever shows it.
                    form.TopLevel = false;
                    form.MinimumSize = Size.Empty;
                    form.ClientSize = new Size(form.Px(OpeningWidth), form.Px(OpeningHeight));
                    form.BuildEditors(schema, current);
                    // Held by the window, so each page is filled from it as the page is built (PageFor).
                    if (snapshot != null) form.ApplySnapshot(snapshot);
                    // The Diagnostics page's Codex compatibility card with the most it shows: the view the reply carries
                    // beside the dashboard's own parts, when it carries one (the bridge answers it on its own, so the card
                    // keeps it for when it is built), and beside its button the longest answer a refresh can give.
                    var compatibility = snapshot == null ? null : Map(snapshot, "compatibility");
                    if (compatibility != null) form.ApplyCompatibility(compatibility, false);
                    string longest = "";
                    foreach (string outcome in new[] { "refreshed", "refused", "unavailable", "incomplete", "failed", "busy" })
                    {
                        string said = form.CompatibilitySaid(outcome, "1234", "unevidenced_verified");
                        if (said.Length > longest.Length) longest = said;
                    }
                    form.SetCompatNote(longest);
                    foreach (string page in PageOrder)
                    {
                        form.ShowPage(page);
                        if (page != "settings")
                        {
                            form.Audit(page, findings);
                            form.AuditScrolling(page, findings);
                            if (page == "overview")
                            {
                                form.AuditRows(page, true, findings);
                                form.AuditNames(page, findings);
                            }
                            form.AuditPins(page, findings);
                            if (page == "overview") form.AuditShortest(findings);
                            if (page == "pending" || page == "history") form.AuditLists(page, findings);
                            continue;
                        }
                        foreach (string section in SectionOrder)
                        {
                            form.ShowSection(section);
                            form.Audit("settings/" + section, findings);
                            form.AuditPins("settings/" + section, findings);
                        }
                    }
                    // The lists again with no rows at all, as a first installation or an unreadable store shows them: the
                    // columns then share the list's width by their headings alone - the person saw v0.6.4's empty Pending
                    // list with Windows' white bar under it (AuditLists). Then the Timeline dialog's list, built and never
                    // shown.
                    if (snapshot != null)
                    {
                        form.ApplySnapshot(WithoutRows(snapshot));
                        foreach (string page in new[] { "pending", "history" })
                        {
                            form.ShowPage(page);
                            form.Audit(page + " with no rows", findings);
                            form.AuditLists(page + " with no rows", findings);
                        }
                        form.ApplySnapshot(snapshot);
                        form.AuditTimeline(snapshot, findings);
                    }
                    // The Start button shows only while the watcher is stopped: shown for this, and hidden again.
                    form.startButton.Visible = true;
                    Materialise(form);
                    form.PerformLayout();
                    form.AuditPins("header", findings);
                    form.startButton.Visible = false;
                    // The reopen note, beside every button of the Settings page's save card, at the opening width
                    // and at the narrowest the window goes: 800 wide, less a sizable frame's 8 px on each side -
                    // each in both orders a window comes to a width in (AuditReopenNote).
                    form.AuditReopenNote(form.Px(OpeningWidth), findings);
                    form.AuditReopenNote(form.Px(800) - form.Px(16), findings);
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

        /// Every way the Overview gives way as the watcher's state changes under it, at `scale` and in the
        /// language of `stringsJson`: one line each, and an empty string when there is none (v0.6.4).
        ///
        /// `statesJson` is a list of [name, dashboard reply] pairs. The window is built as LayoutAudit builds it,
        /// the Overview from the first reply - as a window opens on a watcher already in that state - and each
        /// reply after it is applied to the page already laid out, as a refresh does. Last, the window is made
        /// shorter than the page needs, so the soft bar shows, and given its opening height back. Reported are, at
        /// the opening size after every step:
        ///   * the Overview scrolling;
        ///   * the Overview's rows not as FitOverview gives them - anything but the page's own padding under the last
        ///     row, rows of different heights, a card that floats (AuditRows) - as a first installation shows it too;
        ///   * a name of Right now that wraps (AuditNames);
        ///   * an Overview button (Lead) out of its card's bottom-left corner, over its text or crowding it;
        ///   * Right now laid out differently from the first step - its size, or the height it needs at its width,
        ///     which is what shows a line that moved while its row kept its share of the page. In v0.6.4 the audit found
        ///     German and French scrolling in states LayoutAudit's reply never shows;
        ///   * a shorter window that did not scroll, which would leave the last step proving nothing.
        /// tests/test_gui_layout.py runs it in every language at five scalings.
        internal static string OverviewStatesAudit(string stringsJson, string statesJson, double scale)
        {
            var findings = new List<string>();
            AuditedStates = 0;
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
                if (fallback != null)
                    fallback.SetValue(null, new Font(defaultBefore.FontFamily, defaultBefore.SizeInPoints * factor,
                                                     defaultBefore.Style, GraphicsUnit.Point));
                var catalog = Json.Parse(stringsJson) as Dictionary<string, object>;
                var states = Json.Parse(statesJson) as List<object>;
                string nowhere = Path.Combine(Path.GetTempPath(), "codex-auto-resume-layout-audit-" + Guid.NewGuid().ToString("N"));
                using (var form = new SettingsForm(new PersistentBridge(nowhere, new Bridge(nowhere)), catalog, windowFont))
                {
                    form.auditing = true;
                    form.TopLevel = false;
                    form.MinimumSize = Size.Empty;
                    var opening = new Size(form.Px(OpeningWidth), form.Px(OpeningHeight));
                    form.ClientSize = opening;
                    Size planned = Size.Empty;
                    int needs = 0;
                    string first = null, last = null;
                    foreach (object item in states ?? new List<object>())
                    {
                        var pair = item as List<object>;
                        if (pair == null || pair.Count != 2) continue;
                        last = Convert.ToString(pair[0], CultureInfo.InvariantCulture);
                        var reply = pair[1] as Dictionary<string, object>;
                        if (reply != null) form.ApplySnapshot(reply);
                        if (first == null)
                        {
                            form.ShowPage("overview");
                            first = last;
                        }
                        form.AuditState(last, first, ref planned, ref needs, findings);
                    }
                    if (first == null) return "no states :: nothing was audited";
                    // 40 px shorter than the page needs: at the opening size its rows and the space under them take
                    // whatever the page has past that (FitOverview), so 40 px off the window alone may still fit.
                    var page = form.pages["overview"] as SoftPage;
                    int spare = page == null ? 0 : Math.Max(0, page.ClientSize.Height - page.Extent);
                    form.ClientSize = new Size(opening.Width, opening.Height - spare - form.Px(40));
                    Materialise(form);
                    form.PerformLayout();
                    if (page == null || !page.Overflowing)
                        findings.Add("overview :: a window 40 px shorter than the page needs did not scroll, so its round trip proves nothing");
                    form.ClientSize = opening;
                    form.AuditState(last + ", after the window was made shorter and taller again", first, ref planned, ref needs, findings);
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

        /// How many steps the last OverviewStatesAudit measured, so that a quiet report is known to have looked.
        internal static int AuditedStates;

        /// The Overview laid out as it is now, against what OverviewStatesAudit holds it to.
        private void AuditState(string state, string first, ref Size planned, ref int needs, List<string> findings)
        {
            Materialise(this);
            PerformLayout();
            AuditedStates++;
            string where = "overview (" + state + ")";
            var page = pages["overview"] as SoftPage;
            if (page != null && page.Overflowing)
                findings.Add(where + " :: the page scrolls, " + page.Extent + " high in " + page.ClientSize.Height);
            foreach (KeyValuePair<Control, Control> pair in led)
                if (Showing(pair.Key)) AuditLead(where, pair.Key, pair.Value, Px(LeadGap), findings);
            AuditRows(where, true, findings);
            AuditNames(where, findings);
            Control block = toggleButton.Parent;
            if (block == null) return;
            int needed = block.GetPreferredSize(new Size(block.Width, 0)).Height;
            if (planned.IsEmpty)
            {
                planned = block.Size;
                needs = needed;
            }
            else if (block.Size != planned || needed != needs)
                findings.Add(where + " :: Right now is laid out " + block.Size + ", needing " + needed + ", where it was " + planned +
                             ", needing " + needs + ", for " + first);
        }

        /// How far the Overview's rows and the space under them may be from what FitOverview gives them, for the pixel a
        /// table's shares round away: logical pixels.
        internal const int BandTolerance = 3;

        /// The Overview's cards against the page they stand on (FitOverview), unless the page scrolls, which
        /// AuditScrolling reports:
        ///   * a card shorter or taller than another in its row;
        ///   * a card that floats: taller than the tallest row needs and OverviewComfort, what it holds hanging in space
        ///     above its button;
        ///   * at the opening size (`opening`): under the last row anything but the page's own padding - the mirror of
        ///     the padding over the first row, and what every page keeps under its last card - cards reaching into it,
        ///     or a dead band over it (the review found 41 px above the footer where Pending and History leave 27, and 87
        ///     on a first installation). What is left once the rows are as tall as comfort allows is space by design
        ///     (OverviewHeights). And rows of different heights where the page has room for them alike;
        ///   * in a window only as tall as the rows need (not `opening`): space under the last row, which the rows
        ///     should have had.
        private void AuditRows(string where, bool opening, List<string> findings)
        {
            Control built;
            var page = pages.TryGetValue("overview", out built) ? built as SoftPage : null;
            if (page == null || page.Overflowing) return;
            TableLayoutPanel table = OverviewGrid(page);
            if (table == null)
            {
                findings.Add(where + " :: holds no grid of cards");
                return;
            }
            int bottom = 0, tolerance = Px(BandTolerance), comfort = Px(OverviewComfort), rest = page.Padding.Bottom;
            var tallest = new Dictionary<int, int>();
            var shortest = new Dictionary<int, int>();
            var needs = new Dictionary<int, int>();
            foreach (Control card in table.Controls)
            {
                if (!OwnVisible(card)) continue;
                bottom = Math.Max(bottom, table.Top + card.Bottom);
                int row = table.GetPositionFromControl(card).Row;
                int seen, need = card.GetPreferredSize(new Size(card.Width, 0)).Height;
                tallest[row] = tallest.TryGetValue(row, out seen) ? Math.Max(seen, card.Height) : card.Height;
                shortest[row] = shortest.TryGetValue(row, out seen) ? Math.Min(seen, card.Height) : card.Height;
                needs[row] = needs.TryGetValue(row, out seen) ? Math.Max(seen, need) : need;
            }
            int most = 0;
            foreach (int need in needs.Values) most = Math.Max(most, need);
            bool capped = false;
            foreach (Control card in table.Controls)
            {
                if (!OwnVisible(card)) continue;
                if (card.Height > most + comfort + tolerance)
                    findings.Add(where + "/" + AuditName(card) + " :: floats: " + card.Height + " high where the tallest row needs " + most +
                                 " and comfort allows " + comfort + " more");
                if (card.Height >= most + comfort - tolerance) capped = true;
            }
            // Past the page's own padding, which is what the page keeps under its last card.
            int band = page.ClientSize.Height - page.Padding.Bottom - bottom;
            if (opening)
            {
                if (band < -tolerance)
                    findings.Add(where + " :: leaves only " + (band + rest) + " px under its last row, where the page's rhythm is " + rest +
                                 ": its cards end at " + bottom + " in a page " + page.ClientSize.Height + " high");
                else if (band > tolerance && !capped)
                    findings.Add(where + " :: leaves an empty band " + (band + rest) + " px high under its last row, where the page's rhythm is " +
                                 rest + " and its cards could be taller: they end at " + bottom + " in a page " + page.ClientSize.Height + " high");
            }
            else if (band > tolerance)
                findings.Add(where + " :: leaves " + band + " px under its last row, which its rows need: its cards end at " + bottom +
                             " in a page " + page.ClientSize.Height + " high");
            int lowest = int.MaxValue, highest = 0, free = Math.Max(0, band);
            foreach (KeyValuePair<int, int> row in tallest)
            {
                if (shortest[row.Key] != row.Value)
                    findings.Add(where + " :: row " + row.Key + " holds cards " + shortest[row.Key] + " and " + row.Value + " high");
                lowest = Math.Min(lowest, row.Value);
                highest = Math.Max(highest, row.Value);
                free += row.Value;
            }
            if (opening && tallest.Count > 1 && highest - lowest > 1 && free >= tallest.Count * most)
                findings.Add(where + " :: its rows' cards are " + lowest + " and " + highest + " high, where the page has room for all of them " +
                             most + " high");
        }

        /// The Overview's grid of cards, or null.
        private static TableLayoutPanel OverviewGrid(SoftPage page)
        {
            TableLayoutPanel grid = null;
            if (page != null)
                foreach (Control child in page.Controls)
                    if (OwnVisible(child) && child is TableLayoutPanel) grid = (TableLayoutPanel)child;
            return grid;
        }

        /// Every name of Right now's facts that wraps. The button stands under the facts (Lead), so they have the card's
        /// whole width in every language and state, at the opening size and in the shortest window the Overview fits.
        private void AuditNames(string where, List<string> findings)
        {
            foreach (KeyValuePair<Label, int> name in WrappedNames())
                findings.Add(where + "/" + AuditName(name.Key) + " :: wraps, " + name.Key.Height + " high where its words on one line are " +
                             name.Value + ", though its card has room for it whole");
        }

        /// The names of Right now's facts taller than their words on one line, each with that height.
        private List<KeyValuePair<Label, int>> WrappedNames()
        {
            var wrapped = new List<KeyValuePair<Label, int>>();
            TableLayoutPanel facts = nowFacts;
            if (facts == null) return wrapped;
            bool isName = true;
            using (var twin = new Label())
            {
                twin.AutoSize = true;
                foreach (Control cell in facts.Controls)
                {
                    if (!OwnVisible(cell)) continue;
                    var label = cell as Label;
                    if (isName && label != null && !string.IsNullOrEmpty(label.Text))
                    {
                        twin.Font = label.Font;
                        twin.Padding = label.Padding;
                        twin.UseMnemonic = label.UseMnemonic;
                        twin.Text = label.Text;
                        int line = twin.GetPreferredSize(Size.Empty).Height;
                        if (label.Height > line) wrapped.Add(new KeyValuePair<Label, int>(label, line));
                    }
                    isName = !isName;
                }
            }
            return wrapped;
        }

        /// The client heights, in device pixels, the last LayoutAudit measured the Overview at in AuditShortest: the
        /// shortest window its rows' own tallest cards fit (AuditedShortest), and the one every row as tall as the
        /// tallest card would need (AuditedAlike); and how many of Right now's names wrapped in the shortest
        /// (AuditedWraps). So a quiet report is known to have measured the shortest window, and tests/test_gui_layout.py
        /// can hold it to the screens it must fit.
        internal static int AuditedShortest, AuditedAlike, AuditedWraps;

        /// The Overview in the shortest window it fits without scrolling: as tall as each row's own tallest card,
        /// measured from the cards themselves at the opening width, with no space under the rows. KeepOnScreen gives the
        /// window a height like that on a screen with less room than the opening size - 601 px on a 1920 by 1200 screen
        /// at 175% - and there the rows keep what they need and the space under them goes first (OverviewHeights).
        /// Reported, in that window: the page scrolling; space under the rows; a card shorter than it needs; a button
        /// out of its corner, over text or crowding it; anything cut off (Walk); and a window a pixel shorter that does
        /// not scroll, which would leave the height measured proving nothing. The window then has its size back.
        private void AuditShortest(List<string> findings)
        {
            Control built;
            var page = pages.TryGetValue("overview", out built) ? built as SoftPage : null;
            TableLayoutPanel grid = OverviewGrid(page);
            if (grid == null || page.Overflowing) return;
            int narrowest = int.MaxValue;
            foreach (Control card in grid.Controls)
                if (OwnVisible(card)) narrowest = Math.Min(narrowest, card.Width);
            if (narrowest == int.MaxValue) return;
            var rows = new Dictionary<int, int>();
            int tallest = 0;
            foreach (Control card in grid.Controls)
            {
                if (!OwnVisible(card)) continue;
                int row = grid.GetPositionFromControl(card).Row;
                int need = card.GetPreferredSize(new Size(narrowest, 0)).Height + card.Margin.Vertical;
                int seen;
                rows[row] = rows.TryGetValue(row, out seen) ? Math.Max(seen, need) : need;
                tallest = Math.Max(tallest, need);
            }
            Size opening = ClientSize;
            // The window around the page - header, tabs, footer - and the page's own padding. Not the grid's: that is the
            // space FitOverview keeps under the rows, which a window this short does not have.
            int around = opening.Height - page.ClientSize.Height + page.Padding.Vertical;
            int height = around;
            foreach (int need in rows.Values) height += need;
            AuditedShortest = height;
            AuditedAlike = around + tallest * rows.Count;
            string where = "overview in the shortest window, " + height + " px high";
            try
            {
                ClientSize = new Size(opening.Width, height);
                Materialise(this);
                PerformLayout();
                if (page.Overflowing)
                {
                    findings.Add(where + " :: the page scrolls, " + page.Extent + " high in " + page.ClientSize.Height +
                                 ", though its rows' own tallest cards fit");
                }
                else
                {
                    AuditRows(where, false, findings);
                    foreach (Control card in grid.Controls)
                    {
                        if (!OwnVisible(card)) continue;
                        int needs = card.GetPreferredSize(new Size(card.Width, 0)).Height;
                        if (card.Height < needs)
                            findings.Add(where + "/" + AuditName(card) + " :: is " + card.Height + " high and needs " + needs);
                    }
                    foreach (KeyValuePair<Control, Control> pair in led)
                        if (Showing(pair.Key)) AuditLead(where, pair.Key, pair.Value, Px(LeadGap), findings);
                    Walk(page, where, findings);
                    AuditedWraps = WrappedNames().Count;
                }
                ClientSize = new Size(opening.Width, height - 1);
                Materialise(this);
                PerformLayout();
                if (!page.Overflowing)
                    findings.Add(where + " :: a window a pixel shorter does not scroll, so this is not the shortest window it fits");
            }
            finally
            {
                ClientSize = opening;
                Materialise(this);
                PerformLayout();
            }
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

        /// Shows the reopen note with the window `width` wide, and adds it if any of what it says is cut off - it is
        /// hidden everywhere else the audit looks, and ends in an ellipsis where it does not fit.
        ///
        /// Twice, in both orders the window can come to that width in: laid out at it before the note is shown, and
        /// shown while the layout that narrows the card is still to come - which is the order a window being resized
        /// does it in, and the order the CI runner's did it in, where the card kept the height two lines of the note
        /// needed and the four lines it takes in the width it really gets were cut (v0.6.4). Each starts from the
        /// other width the audit measures, so the card is always laid out at a width that is not the one measured.
        private void AuditReopenNote(int width, List<string> findings)
        {
            AuditReopenNote(width, false, findings);
            AuditReopenNote(width, true, findings);
        }

        private void AuditReopenNote(int width, bool beforeTheLayout, List<string> findings)
        {
            int other = width == Px(OpeningWidth) ? Px(800) - Px(16) : Px(OpeningWidth);
            ClientSize = new Size(other, ClientSize.Height);
            Materialise(this);
            PerformLayout();
            // Held back, so the note is shown while the card is still as wide as it was at `other`: the height
            // the card is given must be the one the note needs at `width`, not at the width the card has now.
            if (beforeTheLayout) SuspendLayout();
            ClientSize = new Size(width, ClientSize.Height);
            if (beforeTheLayout) ResumeLayout(false);
            ShowReopenNote(true);
            Materialise(this);
            PerformLayout();
            Size room = reopenNote.ClientSize;
            int inside = Math.Max(1, room.Width - reopenNote.Padding.Horizontal);
            int needed = TextRenderer.MeasureText(reopenNote.Lines(inside), reopenNote.Font, new Size(inside, int.MaxValue),
                                                  NoteFormat).Height;
            if (room.Width <= 0 || needed > room.Height - reopenNote.Padding.Vertical)
                findings.Add("footer/reopen note at " + width + (beforeTheLayout ? ", shown before the window was laid out" : "") +
                             " :: needs " + needed + " high, has " + room);
            ShowReopenNote(false);
            AuditedNotes++;
        }

        /// How many times the last LayoutAudit measured the reopen note in its save card - two widths in both
        /// orders - so that a quiet report is known to have looked at each of them.
        internal static int AuditedNotes;

        /// How many pinned and led controls the last LayoutAudit held to their corners, so that a quiet report is
        /// known to have looked at them.
        internal static int AuditedPins;

        private readonly HashSet<Control> auditedPins = new HashSet<Control>();

        /// Every pinned control on screen that is not in its corner or covers text (AuditPin), and every button an
        /// Overview card leads to that is not in its card's bottom-left corner, covers text or crowds it (AuditLead), each
        /// where it first shows.
        private void AuditPins(string where, List<string> findings)
        {
            foreach (KeyValuePair<Control, Control> pair in pinned)
            {
                if (!Showing(pair.Key) || auditedPins.Contains(pair.Key)) continue;
                auditedPins.Add(pair.Key);
                AuditedPins++;
                AuditPin(where, pair.Key, pair.Value, findings);
            }
            foreach (KeyValuePair<Control, Control> pair in led)
            {
                if (!Showing(pair.Key) || auditedPins.Contains(pair.Key)) continue;
                auditedPins.Add(pair.Key);
                AuditedPins++;
                AuditLead(where, pair.Key, pair.Value, Px(LeadGap), findings);
            }
        }

        /// Whether a control, and everything it is in up to the window, is told to be visible.
        private bool Showing(Control control)
        {
            for (Control c = control; c != null; c = c.Parent)
            {
                if (c == this) return true;
                if (!OwnVisible(c)) return false;
            }
            return false;
        }

        /// A control pinned to the bottom right of `block` that is more than a pixel from that corner of the
        /// block inside its padding, or that lies over the text of anything else in the block.
        internal static void AuditPin(string where, Control control, Control block, List<string> findings)
        {
            string place = where + "/" + AuditName(control);
            var inner = new Rectangle(block.Padding.Left, block.Padding.Top, block.ClientSize.Width - block.Padding.Horizontal,
                                      block.ClientSize.Height - block.Padding.Vertical);
            var bounds = new Rectangle(Point.Empty, control.Size);
            for (Control c = control; c != null && c != block; c = c.Parent) bounds.Offset(c.Left, c.Top);
            if (Math.Abs(bounds.Right - inner.Right) > 1 || Math.Abs(bounds.Bottom - inner.Bottom) > 1)
                findings.Add(place + " :: is not at the bottom right of its " + AuditName(block) + ", " + bounds + " in " + inner);
            Covered(place, control, block, Point.Empty, bounds, findings);
        }

        /// A button an Overview card leads to (Lead) that is more than a pixel from the card's inner bottom-LEFT
        /// corner, that lies over the text of anything else in the card, or that has a line of text less than `gap`
        /// above it - the clear space around it (v0.6.5).
        internal static void AuditLead(string where, Control control, Control block, int gap, List<string> findings)
        {
            string place = where + "/" + AuditName(control);
            var inner = new Rectangle(block.Padding.Left, block.Padding.Top, block.ClientSize.Width - block.Padding.Horizontal,
                                      block.ClientSize.Height - block.Padding.Vertical);
            var bounds = new Rectangle(Point.Empty, control.Size);
            for (Control c = control; c != null && c != block; c = c.Parent) bounds.Offset(c.Left, c.Top);
            if (Math.Abs(bounds.Left - inner.Left) > 1 || Math.Abs(bounds.Bottom - inner.Bottom) > 1)
                findings.Add(place + " :: is not at the bottom left of its " + AuditName(block) + ", " + bounds + " in " + inner);
            Covered(place, control, block, Point.Empty, bounds, findings);
            // The band above it, across the card: no line of text ends in it.
            var above = new Rectangle(inner.Left, bounds.Top - gap, inner.Width, gap);
            var crowding = new List<string>();
            Covered(place, control, block, Point.Empty, above, crowding);
            foreach (string line in crowding)
                findings.Add(line.Replace(" :: covers ", " :: has less than " + gap + " px above it to "));
        }

        private static void Covered(string place, Control pinnedControl, Control container, Point offset, Rectangle bounds,
                                    List<string> findings)
        {
            foreach (Control child in container.Controls)
            {
                if (child == pinnedControl || !OwnVisible(child)) continue;
                var at = new Point(offset.X + child.Left, offset.Y + child.Top);
                Rectangle text = TextBox(child, at);
                if (!text.IsEmpty && text.IntersectsWith(bounds))
                    findings.Add(place + " :: covers " + AuditName(child) + ", " + text + " under " + bounds);
                Covered(place, pinnedControl, child, at, bounds, findings);
            }
        }

        /// Where a label or a button draws its text, with its top left at `at`; empty for anything else. A
        /// label's text is measured as it wraps in the label and placed as the label aligns it, so a label
        /// stretched across a cell is held to its words and not to the cell.
        private static Rectangle TextBox(Control control, Point at)
        {
            if (string.IsNullOrEmpty(control.Text) || !(control is Label || control is ButtonBase)) return Rectangle.Empty;
            var bounds = new Rectangle(at, control.Size);
            var label = control as Label;
            if (label == null) return bounds;
            TextFormatFlags format = TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl;
            if (!label.UseMnemonic) format |= TextFormatFlags.NoPrefix;
            int room = Math.Max(1, label.ClientSize.Width - label.Padding.Horizontal);
            // In the lines it is drawn in (WrapLabel: Korean between its words).
            var wrap = label as WrapLabel;
            Size text = TextRenderer.MeasureText(wrap != null ? wrap.Lines(room) : label.Text, label.Font, new Size(room, int.MaxValue), format);
            int width = Math.Min(text.Width + label.Padding.Horizontal, bounds.Width);
            int height = Math.Min(text.Height + label.Padding.Vertical, bounds.Height);
            int x = bounds.X, y = bounds.Y;
            ContentAlignment align = label.TextAlign;
            if ((align & (ContentAlignment.TopCenter | ContentAlignment.MiddleCenter | ContentAlignment.BottomCenter)) != 0)
                x += (bounds.Width - width) / 2;
            else if ((align & (ContentAlignment.TopRight | ContentAlignment.MiddleRight | ContentAlignment.BottomRight)) != 0)
                x = bounds.Right - width;
            if ((align & (ContentAlignment.MiddleLeft | ContentAlignment.MiddleCenter | ContentAlignment.MiddleRight)) != 0)
                y += (bounds.Height - height) / 2;
            else if ((align & (ContentAlignment.BottomLeft | ContentAlignment.BottomCenter | ContentAlignment.BottomRight)) != 0)
                y = bounds.Bottom - height;
            return new Rectangle(x, y, width, height);
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

        /// The pages that never scroll at the opening size: the Overview, which the window opens on, and
        /// the two lists, whose cards give way to the window's height instead of the page.
        private void AuditScrolling(string page, List<string> findings)
        {
            if (page != "overview" && page != "pending" && page != "history") return;
            Control built;
            var scroller = pages.TryGetValue(page, out built) ? built as SoftPage : null;
            if (scroller != null && scroller.Overflowing)
                findings.Add(page + " :: the page scrolls, " + scroller.Extent + " high in " + scroller.ClientSize.Height);
        }

        private void Walk(Control parent, string path, List<string> findings)
        {
            var scroller = parent as ScrollableControl;
            var page = parent as SoftPage;
            bool native = scroller != null && scroller.AutoScroll;
            // A list's clip is narrower than the list by the list's own scroll bar, on purpose (SoftListHost).
            bool scrolls = native || (page != null && page.Scrolls) || parent is ListClip;
            if (native && scroller.HorizontalScroll.Visible)
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
                else if (page != null && page.Scrolls)
                {
                    // Up and down it scrolls; sideways it must hold what it holds, clear of the bar.
                    Rectangle room = page.DisplayRectangle;
                    if (child.Left < room.Left || child.Right > room.Right)
                        findings.Add(place + " :: reaches past the side of its page, " + child.Bounds + " in " + room);
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

        /// How many lists the last LayoutAudit held to their width (AuditLists, AuditTimeline), so that a quiet report is
        /// known to have looked at them.
        internal static int AuditedLists;

        /// The list on `page` - Pending's or History's - whose columns are wider than it is at the opening size, where
        /// they share its width (FitColumns): v0.6.4's white bar under the Pending list.
        private void AuditLists(string where, List<string> findings)
        {
            ListView list = where.StartsWith("pending", StringComparison.Ordinal) ? pendingList
                          : where.StartsWith("history", StringComparison.Ordinal) ? historyList : null;
            if (list == null || !Showing(list)) return;
            AuditList(where + "/" + AuditName(list), list, findings);
        }

        /// A list whose columns are wider than it is, which is what makes Windows show its horizontal bar - under the
        /// clip, with the soft one drawn in its place (SoftListHost). Measured rather than read from the list's style:
        /// the list takes its bar away only once the window has had its messages, a list that has just grown its
        /// vertical bar is set right by its host after one (SoftListHost.Sync), and the audit never pumps them - pumped,
        /// they gave the window it measures the size of the screen the audit runs on.
        private static void AuditList(string place, ListView list, List<string> findings)
        {
            AuditedLists++;
            int total = 0;
            foreach (ColumnHeader column in list.Columns) total += column.Width;
            if (total > list.ClientSize.Width)
                findings.Add(place + " :: scrolls sideways at the opening size, its columns " + total + " wide in " + list.ClientSize.Width);
        }

        /// The Timeline dialog's list, built for the reply's first waiting recovery and a history of events with long
        /// words, laid out at the dialog's opening size and never shown (AuditList).
        private void AuditTimeline(Dictionary<string, object> snapshot, List<string> findings)
        {
            var rows = snapshot == null ? null : snapshot.ContainsKey("pending") ? snapshot["pending"] as List<object> : null;
            var row = rows != null && rows.Count > 0 ? rows[0] as Dictionary<string, object> : null;
            if (row == null) row = new Dictionary<string, object>();
            var events = new List<object>();
            string[] codes = { "detected", "state", "claim", "submitted", "correlated", "retry_now", "release_claim",
                               "continuation_after_user_turn", "dispatched_while_paused", "state" };
            string[] states = { "waiting_reset", "scheduled", "submission_claimed", "submitted", "turn_running", "scheduled",
                                "outcome_unverified", "no_progress", "submission_unknown", "recovered" };
            double at = 1.8e9;
            for (int i = 0; i < codes.Length; i++)
            {
                var entry = new Dictionary<string, object>();
                entry["at"] = at + 3600.0 * i;
                entry["code"] = codes[i];
                entry["to_code"] = states[i];
                events.Add(entry);
            }
            using (Form dialog = BuildTimeline(row, events))
            {
                dialog.TopLevel = false;
                Materialise(dialog);
                dialog.PerformLayout();
                if (timelineList != null) AuditList("timeline/" + AuditName(timelineList), timelineList, findings);
            }
        }

        /// A dashboard reply with no waiting and no finished recoveries in it.
        private static Dictionary<string, object> WithoutRows(Dictionary<string, object> reply)
        {
            var empty = new Dictionary<string, object>(reply);
            empty["pending"] = new List<object>();
            empty["history"] = new List<object>();
            return empty;
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
            return cut.Count == 0 ? null : "column headings cut: " + string.Join("; ", cut.ToArray()) + " (columns " + total + " wide in " +
                                           list.ClientSize.Width + ")";
        }

        private static string AuditName(Control control)
        {
            string text = (control.Text ?? "").Replace("\r", " ").Replace("\n", " ");
            if (text.Length > 32) text = text.Substring(0, 32);
            if (text.Length == 0 && !string.IsNullOrEmpty(control.AccessibleName)) text = control.AccessibleName;
            return control.GetType().Name + (text.Length > 0 ? "'" + text + "'" : "");
        }
    }
}

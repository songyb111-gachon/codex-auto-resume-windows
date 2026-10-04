// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Advanced features page checking itself, on demand (advanced/gui/AdvancedPage.cs).
//
// Two entry points, as the standard window has LayoutAudit (gui/WindowAudit.cs), and run by
// advanced/tests/test_advanced_page.py, never by the window a person opens:
//
//   * AdvancedLayoutAudit lays the page out in one language at one scaling, each capability open in turn, and
//     reports what is cut off, what has no name a screen reader can say and a list that would scroll sideways, in
//     the window's own measurements - the standard audit's own checks (Audit, AuditSpoken, AuditPins, AuditList);
//   * AdvancedPageRun drives the page as a person would - a snapshot arriving, the tab pressed, a row chosen, a
//     button pressed, the dialog answered - with the bridge's replies and the dialog's answers given by the test, and
//     says what the page showed, what it sent, what it asked and what it told.
//
// The window is built as LayoutAudit builds it: never shown, not even a top-level window, and on a bridge rooted where
// nothing is, so nothing it does can reach a process. Its requests are answered from the test's replies instead
// (advancedScript), and its dialog is answered from the test's answers (AskAdvanced, TellAdvanced).
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // ---------------------------------------------------------------- the tests' replies
        // Null in every window a person opens. In a window AdvancedPageRun drives: the replies the page's requests are
        // answered with, by command - or by "<command> <capability>" where a request names one - each list answered in
        // order and its last answer kept; the dialog's answers in order, none left being Cancel; and every request
        // made, question asked and notice told, written down.
        private Dictionary<string, List<object>> advancedScript;
        private readonly List<bool> advancedAnswers = new List<bool>();
        private readonly List<string> advancedSent = new List<string>();
        private readonly List<string> advancedAsked = new List<string>();
        private readonly List<string> advancedTold = new List<string>();

        /// The test's reply to one request of the page's, and the request written down as "<command> <argument>".
        private Dictionary<string, object> AdvancedScripted(string command, string argument)
        {
            advancedSent.Add(command + " " + argument);
            string capability = null;
            try { capability = Str(Json.Parse(argument) as Dictionary<string, object>, "capability"); }
            catch (FormatException) { }
            List<object> replies;
            if (!(capability != null && advancedScript.TryGetValue(command + " " + capability, out replies)) &&
                !advancedScript.TryGetValue(command, out replies))
                return null;
            if (replies.Count == 0) return null;
            object reply = replies[0];
            if (replies.Count > 1) replies.RemoveAt(0);
            return reply as Dictionary<string, object>;
        }

        // ---------------------------------------------------------------- a window no one sees
        /// A window as LayoutAudit builds one, in the language of `stringsJson` at `scale`, handed to `use` and closed.
        private static void WithAdvancedWindow(string stringsJson, double scale, Action<SettingsForm> use)
        {
            System.Reflection.FieldInfo fallback = typeof(Control).GetField("defaultFont",
                System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
            Font defaultBefore = Control.DefaultFont;
            Font baseBefore = Soft.BaseFont;
            try
            {
                dpiScale = scale;
                float factor = (float)(scale / SystemScale);
                double read = TextScale.Read();
                Font box = TextScale.Apply(SystemFonts.MessageBoxFont, read, 1.0);
                var windowFont = new Font(box.FontFamily, box.SizeInPoints * factor, box.Style, GraphicsUnit.Point);
                Font fallen = TextScale.Apply(defaultBefore, read, 1.0);
                if (fallback != null)
                    fallback.SetValue(null, new Font(fallen.FontFamily, fallen.SizeInPoints * factor, fallen.Style, GraphicsUnit.Point));
                var catalog = Json.Parse(stringsJson) as Dictionary<string, object>;
                string nowhere = Path.Combine(Path.GetTempPath(), "codex-auto-resume-layout-audit-" + Guid.NewGuid().ToString("N"));
                using (var form = new SettingsForm(new PersistentBridge(nowhere, new Bridge(nowhere)), catalog, windowFont))
                {
                    form.auditing = true;
                    form.TopLevel = false;
                    form.MinimumSize = Size.Empty;
                    form.ClientSize = new Size(form.Px(OpeningWidth), form.Px(OpeningHeight));
                    // On a screen as wide as anything needs, whatever this machine's is: the window holds its tabs on one
                    // row (HoldTabs), and the narrow screen is one the audit stands in on purpose (AuditNarrowestOn).
                    form.advancedScreen = int.MaxValue;
                    use(form);
                }
            }
            finally
            {
                dpiScale = SystemScale;
                if (fallback != null) fallback.SetValue(null, defaultBefore);
                Soft.BaseFont = baseBefore;
            }
        }

        // ---------------------------------------------------------------- the layout audit
        /// How many times the last AdvancedLayoutAudit laid the page out and looked, so that a quiet report is known to
        /// have looked at every capability.
        internal static int AdvancedAudited;

        /// Every place the page cuts something off, in the language of `stringsJson` and the page's words `wordsJson`
        /// (advanced-words' `words`) at `scale`: one line each, and an empty string when there is none.
        ///
        /// The list is `listingJson` (advanced-list's answer) and the statements `statementsJson`, {id: advanced-
        /// statement's answer}; what the capabilities keep is `keptJson`, {"advanced-rules": its answer, "advanced-samples":
        /// its answer}, shown on the cards of the capabilities that have them. The page is laid out at the window's opening size with each capability open in turn -
        /// with what a policy refuses of it and every warning its statement carries - then with a list that could not
        /// be read. At each: the standard audit's Walk (anything cut off, a page that would scroll sideways, a field
        /// that is not a field high), a control with no name a screen reader can say, a pinned control out of its
        /// corner, and the list's columns wider than it is. Last, the narrowest window there is, held to its tabs and its
        /// list (AuditNarrowest), on two screens that do not depend on this machine's: one as wide as anything needs,
        /// where the window is 800 wide less a sizable frame's 8 px each side, as the standard audit's narrowest
        /// (AuditReopenNote), or as wide as the tabs, this page's among them, where they need more (HoldTabs); and the
        /// narrowest screen the window opens on at this scaling, TextScale.NarrowestWidth wide - the text size is fitted
        /// so that one holds the standard window - where the tabs take a second row rather than be cut off.
        internal static string AdvancedLayoutAudit(string stringsJson, string wordsJson, string listingJson, string statementsJson,
                                                   string keptJson, double scale)
        {
            var findings = new List<string>();
            AdvancedAudited = 0;
            WithAdvancedWindow(stringsJson, scale, delegate(SettingsForm form)
            {
                var listing = Json.Parse(listingJson) as Dictionary<string, object>;
                var statements = Json.Parse(statementsJson) as Dictionary<string, object> ?? new Dictionary<string, object>();
                var kept = Json.Parse(keptJson) as Dictionary<string, object>;
                form.advancedRules = Map(kept, "advanced-rules");
                form.advancedSamples = Map(kept, "advanced-samples");
                form.AdoptAdvancedWords(Json.Parse(wordsJson) as Dictionary<string, object>);
                form.ShowAdvancedList(listing);
                foreach (KeyValuePair<string, object> pair in statements)
                    form.ShowAdvancedStatement(pair.Key, pair.Value as Dictionary<string, object>);
                form.ShowAdvanced();
                var ids = new List<string>();
                foreach (object entry in Items(listing, "capabilities") ?? new List<object>())
                {
                    string id = Str(entry as Dictionary<string, object>, "id");
                    if (id != null) ids.Add(id);
                }
                foreach (string id in ids)
                {
                    form.OpenAdvanced(id);
                    form.FillAdvancedList();
                    form.AuditAdvanced("advanced/" + id, findings);
                }
                form.ShowAdvancedList(null);
                form.AuditAdvanced("advanced unread", findings);
                if (ids.Count > 0)
                {
                    form.ShowAdvancedList(listing);
                    form.OpenAdvanced(ids[0]);
                    form.AuditNarrowestOn(int.MaxValue, "advanced/" + ids[0] + " at the narrowest", findings);
                    form.AuditNarrowestOn(form.Px(TextScale.NarrowestWidth),
                                          "advanced/" + ids[0] + " at the narrowest on the narrowest screen", findings);
                }
            });
            return string.Join("\n", findings.ToArray());
        }

        /// The window as narrow as it goes on a screen `screen` px wide (HoldTabs), audited there (AuditNarrowest).
        ///
        /// Held from a window wider than any Windows allows here (SystemInformation.MaxWindowTrackSize), whose Width
        /// Windows has held to that while its client area is the one asked for - the state the larger scalings reach
        /// on a screen smaller than they are, which a window measuring its frame from the two read as a frame of
        /// -184 px at 200% on a screen 1440 wide (FrameWidth). So every scaling is held from it on every machine, not
        /// only those whose screen is smaller than the window, and the window is then made as wide as HoldTabs held it
        /// - not its MinimumSize read back, which Windows keeps within this machine's own screen.
        private void AuditNarrowestOn(int screen, string where, List<string> findings)
        {
            advancedScreen = screen;
            MinimumSize = Size.Empty;
            ClientSize = new Size(SystemInformation.MaxWindowTrackSize.Width + Px(100), ClientSize.Height);
            int least = HoldTabs();
            ClientSize = new Size(Math.Max(Px(800) - Px(16), least - FrameWidth), ClientSize.Height);
            FitTabs();
            AuditNarrowest(where, findings);
        }

        /// The narrowest window, held to what it must never give up: every tab whole in the strip (the Walk of the
        /// strip), and the list's columns within it. The standard audit measures the pages at the opening size and the
        /// narrowest window only for the footer's note (AuditReopenNote); there, as on the standard pages, a row's label
        /// ends in an ellipsis and a line wraps.
        private void AuditNarrowest(string where, List<string> findings)
        {
            AdvancedAudited++;
            Materialise(this);
            PerformLayout();
            Walk(nav, where + "/" + AuditName(nav), findings);
            if (advancedList != null) AuditList(where + "/" + AuditName(advancedList), advancedList, findings);
        }

        private void AuditAdvanced(string where, List<string> findings)
        {
            AdvancedAudited++;
            if (currentPage != AdvancedPageName || advancedPage == null || !OwnVisible(advancedPage))
                findings.Add(where + " :: the page is not the one showing");
            if (advancedTab == null || !OwnVisible(advancedTab))
                findings.Add(where + " :: the page's tab is not showing");
            Audit(where, findings);
            AuditSpoken(where, this, findings);
            AuditPins(where, findings);
            if (advancedList != null) AuditList(where + "/" + AuditName(advancedList), advancedList, findings);
        }

        // ---------------------------------------------------------------- driving the page
        /// The page driven as a person would, from `scenarioJson`: {"answers": [the dialog's answers], "script": {command
        /// or "<command> <capability>": [replies, as the bridge gives them]}, "steps": [...]}. A step is one of
        ///   {"do": "snapshot", "reply": a dashboard reply}   read, as the window's clock reads one (ApplySnapshot)
        ///   {"do": "unavailable"}                             a read that failed (MarkUnavailable)
        ///   {"do": "show"}                                    the tab pressed
        ///   {"do": "page", "name": ...}                       another page's tab pressed
        ///   {"do": "choose", "id": ...}                       that capability's row chosen in the list
        ///   {"do": "press", "button": on|watch|off|all_off}   a button pressed, if it can be
        ///   {"do": "hourly", "value": n}                      the hourly limit chosen, and the pause after it over
        ///   {"do": "set_option", "key": ..., "value": n}      a choice made in that choice's drop-down
        ///   {"do": "rule", "tag": ..., "sampled": ...,        a new rule's fields filled - its code typed, or taken from the
        ///    "from": ..., "to": ..., "kind": ...}             samples' drop-down - and Add rule pressed, if it can be
        ///   {"do": "remove", "rule": n}                       that rule's Remove pressed, if it can be
        ///   {"do": "ctrl-tab", "shift": bool}                 Ctrl+Tab, or Ctrl+Shift+Tab
        ///   {"do": "reply", "key": ..., "with": [...]}        what the bridge answers from now on
        ///   {"do": "answer", "with": [...]}                   what the person answers the next questions
        ///   {"do": "look"}                                    what the page shows now, into "looks"
        ///   {"do": "reopen"}                                  the arguments a reopen would start the next window with,
        ///                                                     here (ReopenArguments), into "reopened"
        ///   {"do": "open", "arguments": "..."}                a window opened with these arguments: read as Main and
        ///                                                     BuildDashboard read them, and its first page shown as Load
        ///                                                     shows it
        /// What it returns is the page as it was left (Look), with every look taken, every request sent ("<command>
        /// <argument>"), every question asked, every notice told, and each press of a button that could not be
        /// pressed.
        internal static string AdvancedPageRun(string stringsJson, string scenarioJson)
        {
            var result = new Dictionary<string, object>();
            WithAdvancedWindow(stringsJson, SystemScale, delegate(SettingsForm form)
            {
                var scenario = Json.Parse(scenarioJson) as Dictionary<string, object> ?? new Dictionary<string, object>();
                form.advancedScript = new Dictionary<string, List<object>>();
                foreach (KeyValuePair<string, object> pair in Map(scenario, "script") ?? new Dictionary<string, object>())
                    form.advancedScript[pair.Key] = new List<object>(pair.Value as List<object> ?? new List<object>());
                foreach (object answer in Items(scenario, "answers") ?? new List<object>()) form.advancedAnswers.Add(Equals(answer, true));
                var looks = new List<object>();
                var disabled = new List<object>();
                var reopened = new List<object>();
                foreach (object entry in Items(scenario, "steps") ?? new List<object>())
                {
                    var step = entry as Dictionary<string, object>;
                    string what = Str(step, "do");
                    if (what == "snapshot") form.ApplySnapshot(Map(step, "reply"));
                    else if (what == "unavailable") form.MarkUnavailable();
                    else if (what == "show")
                    {
                        form.ShowAdvanced();
                        Materialise(form);
                        form.PerformLayout();
                    }
                    else if (what == "page") form.ShowPage(Str(step, "name"));
                    else if (what == "choose") form.ChooseAdvanced(Str(step, "id"));
                    else if (what == "press")
                    {
                        string name = Str(step, "button");
                        Button button = name == "on" ? form.advancedOn : name == "watch" ? form.advancedWatch
                                      : name == "off" ? form.advancedOff : name == "all_off" ? form.advancedAllOff : null;
                        if (button == null || !button.Enabled || !OwnVisible(button)) disabled.Add(name);
                        else Pressed.Invoke(button, new object[] { EventArgs.Empty });
                    }
                    else if (what == "hourly")
                    {
                        if (form.advancedHourly == null || !form.advancedHourly.Enabled) disabled.Add("hourly");
                        else
                        {
                            form.advancedHourly.Spin.Value = Whole(Get(step, "value"));
                            if (form.hourlyTimer != null) form.hourlyTimer.Stop();
                            form.SetHourly(form.hourlyChosen);
                        }
                    }
                    else if (what == "set_option")
                    {
                        SoftCombo combo = form.advancedChoices.Find(delegate(SoftCombo each) { return Equals(each.Tag, Str(step, "key")); });
                        if (combo == null || !combo.Enabled) disabled.Add("set_option");
                        else
                        {
                            Choose(combo, Convert.ToString(Whole(Get(step, "value")), System.Globalization.CultureInfo.InvariantCulture));
                            Committed.Invoke(combo, new object[] { EventArgs.Empty });
                        }
                    }
                    else if (what == "rule")
                    {
                        if (form.ruleAdd == null || !form.ruleAdd.Enabled) disabled.Add("rule");
                        else
                        {
                            if (Str(step, "sampled") != null && form.ruleSampled != null)
                            {
                                Choose(form.ruleSampled, Str(step, "sampled"));
                                Committed.Invoke(form.ruleSampled, new object[] { EventArgs.Empty });
                            }
                            if (Str(step, "tag") != null) form.ruleTag.Box.Text = Str(step, "tag");
                            form.ruleFrom.Box.Text = Str(step, "from") ?? "";
                            form.ruleTo.Box.Text = Str(step, "to") ?? "";
                            if (Str(step, "kind") != null) Choose(form.ruleKind, Str(step, "kind"));
                            Pressed.Invoke(form.ruleAdd, new object[] { EventArgs.Empty });
                        }
                    }
                    else if (what == "remove")
                    {
                        Button remove = form.ruleRemoves.Find(delegate(Button each) { return Equals(each.Tag, Get(step, "rule")); });
                        if (remove == null || !remove.Enabled) disabled.Add("remove");
                        else Pressed.Invoke(remove, new object[] { EventArgs.Empty });
                    }
                    else if (what == "ctrl-tab")
                    {
                        Keys keys = Keys.Control | Keys.Tab | (Equals(Get(step, "shift"), true) ? Keys.Shift : Keys.None);
                        var message = new Message();
                        // As a key reaches the window: its command keys first, then the key preview (BuildDashboard).
                        if (!form.ProcessCmdKey(ref message, keys)) form.OnKeyDown(new KeyEventArgs(keys));
                    }
                    else if (what == "reply")
                        form.advancedScript[Str(step, "key") ?? ""] = new List<object>(Items(step, "with") ?? new List<object>());
                    else if (what == "answer")
                        foreach (object answer in Items(step, "with") ?? new List<object>()) form.advancedAnswers.Add(Equals(answer, true));
                    else if (what == "look") looks.Add(form.Look());
                    else if (what == "reopen")
                        reopened.Add(ReopenArguments(form.currentPage ?? form.firstPage, form.currentSection,
                                                     new Rectangle(100, 100, 1000, 700), false, "system", "soft", 1,
                                                     Padding.Empty, form.FocusName()));
                    else if (what == "open")
                    {
                        OpenRequest parsed = ParseArguments((Str(step, "arguments") ?? "").Split(' '));
                        form.request.Page = parsed.Page;
                        form.request.Focus = parsed.Focus;
                        // BuildDashboard's first page, and the page's note of it (DashboardBuilt); then Load's ShowPage.
                        if (parsed.Page != null) form.firstPage = parsed.Page;
                        form.advancedReturning = form.firstPage == AdvancedPageName;
                        form.ShowPage(form.firstPage);
                    }
                }
                foreach (KeyValuePair<string, object> pair in form.Look()) result[pair.Key] = pair.Value;
                result["looks"] = looks;
                result["sent"] = new List<object>(form.advancedSent.ToArray());
                result["asked"] = new List<object>(form.advancedAsked.ToArray());
                result["told"] = new List<object>(form.advancedTold.ToArray());
                result["disabled"] = disabled;
                result["reopened"] = reopened;
            });
            return Json.Write(result);
        }

        // Control.OnClick, which raises Click as a press of the button does.
        private static readonly System.Reflection.MethodInfo Pressed =
            typeof(Control).GetMethod("OnClick", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
        // ComboBox.OnSelectionChangeCommitted, which a choice taken from the list raises.
        private static readonly System.Reflection.MethodInfo Committed =
            typeof(ComboBox).GetMethod("OnSelectionChangeCommitted", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        /// The item of `combo` whose value is `value` chosen, as a choice from its list chooses it.
        private static void Choose(ComboBox combo, string value)
        {
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var choice = combo.Items[i] as Choice;
                if (choice != null && choice.Value == value) combo.SelectedIndex = i;
            }
        }

        private static List<object> ItemsOf(ComboBox combo)
        {
            var items = new List<object>();
            if (combo != null) foreach (object item in combo.Items) items.Add(item.ToString());
            return items;
        }

        /// The row for `id` chosen in the list, as a click on it chooses it.
        private void ChooseAdvanced(string id)
        {
            if (advancedList == null) return;
            foreach (ListViewItem item in advancedList.Items)
                if (Str(item.Tag as Dictionary<string, object>, "id") == id)
                {
                    item.Selected = true;
                    item.Focused = true;
                }
        }

        /// What the page shows: its tab, the page on screen, each row's name and state as the list draws them, the
        /// capability open, the text of each of its cards in order - its heading first - what each button may do, the
        /// note beside them, the number of requests made so far and the hourly limit's choices.
        private Dictionary<string, object> Look()
        {
            var look = new Dictionary<string, object>();
            look["tab"] = advancedTab == null ? null : advancedTab.Text;
            look["tab_visible"] = advancedTab != null && OwnVisible(advancedTab);
            look["page"] = currentPage;
            // Where a reopen would say the keyboard is (FocusName): on a window never shown, the tab of the page on screen.
            look["focus"] = FocusName();
            var rows = new List<object>();
            if (advancedList != null)
                foreach (ListViewItem item in advancedList.Items)
                {
                    var row = new List<object>();
                    // By index: the cell's type is named nowhere in the standard window's sources, and a name of this
                    // window's that the standard executable holds - as it holds that type's - is one build/edition_audit.py
                    // finds there (check d).
                    for (int cell = 0; cell < item.SubItems.Count; cell++) row.Add(item.SubItems[cell].Text);
                    row.Add(item.Selected);
                    rows.Add(row);
                }
            look["rows"] = rows;
            look["open"] = advancedOpen;
            var cards = new List<object>();
            if (advancedStack != null)
                foreach (Control card in advancedStack.Controls)
                {
                    var texts = new List<object>();
                    Texts(card, texts);
                    cards.Add(texts);
                }
            look["cards"] = cards;
            var buttons = new Dictionary<string, object>();
            if (advancedOn != null)
            {
                buttons["on"] = advancedOn.Enabled;
                buttons["watch"] = advancedWatch.Enabled;
                buttons["off"] = advancedOff.Enabled;
                buttons["all_off"] = advancedAllOff.Enabled;
            }
            look["buttons"] = buttons;
            look["note"] = advancedNote == null ? null : advancedNote.Text;
            // How many requests the page had made by then, so a test can tell which step made which.
            look["requests"] = (double)advancedSent.Count;
            if (advancedHourly != null)
            {
                // A number in a well, as every limit on the Settings page is (SoftNumber): its least, its most, its value.
                var hourly = new Dictionary<string, object>();
                hourly["minimum"] = (double)advancedHourly.Spin.Minimum;
                hourly["maximum"] = (double)advancedHourly.Spin.Maximum;
                hourly["value"] = (double)advancedHourly.Spin.Value;
                look["hourly"] = hourly;
            }
            else look["hourly"] = null;
            // The open capability's choices - each one's drop-down, what it offers and what it shows - and the rules'
            // editor: what each rule's Remove names, the kinds and the samples' codes offered, and whether Add can be pressed.
            var choices = new List<object>();
            foreach (SoftCombo combo in advancedChoices)
            {
                var choice = new Dictionary<string, object>();
                choice["key"] = combo.Tag as string;
                choice["items"] = ItemsOf(combo);
                choice["value"] = combo.SelectedItem == null ? null : combo.SelectedItem.ToString();
                choice["enabled"] = combo.Enabled;
                choices.Add(choice);
            }
            look["choices"] = choices;
            if (ruleRemoves.Count > 0 || ruleAdd != null)
            {
                var editor = new Dictionary<string, object>();
                var removes = new List<object>();
                foreach (Button remove in ruleRemoves) removes.Add(remove.Tag);
                editor["removes"] = removes;
                editor["add"] = ruleAdd == null ? (object)null : ruleAdd.Enabled;
                editor["kinds"] = ItemsOf(ruleKind);
                editor["sampled"] = ItemsOf(ruleSampled);
                look["rules"] = editor;
            }
            else look["rules"] = null;
            return look;
        }

        /// The words a control shows, and those of everything in it, in order: a label's text, a callout's notice.
        private static void Texts(Control control, List<object> into)
        {
            var callout = control as SoftCallout;
            if (callout != null) into.Add(callout.Notice);
            else if (control is Label && !string.IsNullOrEmpty(control.Text)) into.Add(control.Text);
            foreach (Control child in control.Controls) Texts(child, into);
        }
    }
}

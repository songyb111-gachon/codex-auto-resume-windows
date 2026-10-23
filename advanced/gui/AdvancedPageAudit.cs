// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Advanced features page checking itself, on demand (advanced/gui/AdvancedPage.cs).
//
// Two entry points, as the standard window has LayoutAudit (gui/WindowAudit.cs), and run by
// advanced/tests/test_advanced_page_*.py (their shared harness is advanced/tests/pagecase.py), never by the window a
// person opens:
//
//   * AdvancedLayoutAudit lays the page out in one language at one scaling, each capability open in turn - the
//     report's card in every state a report can be in, and Pending with the reset rules scheduled - and reports
//     what is cut off, what has no name a screen
//     reader can say and a list that would scroll sideways, in the window's own measurements - the standard
//     audit's own checks (Audit, AuditSpoken, AuditPins, AuditList);
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
        /// its answer, "advanced-watch-log": one answer every capability shows, "pending": the snapshot's pending list,
        /// "advanced-resets": its answer, "snapshot": the dashboard reply whose conversations the reset forms offer},
        /// shown on the cards of the capabilities that have them - and, where there are reset rules, on Pending. The
        /// page is laid out at the window's opening size with each capability open in turn - with what a policy refuses of
        /// it and every warning its statement carries - then each action open with its card in each of `reportsJson`'s
        /// states ([{"state", "built", "checked", "last", "told", "job", "login", "word"}], AdoptReportState), then with a
        /// list that could not be read. At each: the standard audit's Walk (anything cut off, a page that would scroll sideways, a field
        /// that is not a field high), a control with no name a screen reader can say, a pinned control out of its
        /// corner, and the list's columns wider than it is - and (v0.6.16 final) each Custom... dialog its choices open, as
        /// the Settings page's are audited (AuditOwnDialog). Last, the narrowest window there is, held to its tabs and its
        /// list (AuditNarrowest), on two screens that do not depend on this machine's: one as wide as anything needs,
        /// where the window is 800 wide less a sizable frame's 8 px each side, as the standard audit's narrowest
        /// (AuditReopenNote), or as wide as the tabs, this page's among them, where they need more (HoldTabs); and the
        /// narrowest screen the window opens on at this scaling, TextScale.NarrowestWidth wide - the text size is fitted
        /// so that one holds the standard window - where the tabs take a second row rather than be cut off.
        internal static string AdvancedLayoutAudit(string stringsJson, string wordsJson, string listingJson, string statementsJson,
                                                   string keptJson, string reportsJson, double scale)
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
                form.advancedPending = Items(kept, "pending");
                form.advancedResets = Map(kept, "advanced-resets");
                Dictionary<string, object> shot = Map(kept, "snapshot");
                form.AdoptAdvancedWords(Json.Parse(wordsJson) as Dictionary<string, object>);
                // The conversations the reset forms offer, and Pending's list, are the snapshot's.
                if (shot != null) form.ApplySnapshot(shot);
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
                // What each would have done while watched, at its fullest: one line for every answer the log names.
                foreach (string id in ids) form.advancedWatchLog[id] = Map(kept, "advanced-watch-log");
                // v0.6.16 final: and each customizable choice's Custom... dialog, once for each range and unit.
                var dialogsSeen = new HashSet<string>();
                foreach (string id in ids)
                {
                    form.OpenAdvanced(id);
                    form.FillAdvancedList();
                    form.AuditAdvanced("advanced/" + id, findings);
                    form.AuditCustomValues("advanced/" + id, dialogsSeen, findings);
                }
                var reports = Json.Parse(reportsJson) as List<object> ?? new List<object>();
                foreach (string id in ids)
                {
                    Dictionary<string, object> item = form.AdvancedItem(id);
                    if (!IsReport(item)) continue;
                    form.OpenAdvanced(id);
                    for (int n = 0; n < reports.Count; n++)
                    {
                        form.AdoptReportState(item, reports[n] as Dictionary<string, object>);
                        form.FillAdvancedList();
                        form.RefreshReport();
                        form.AuditAdvanced("advanced/" + id + "/report " + n, findings);
                    }
                    form.AdoptReportState(item, null);
                }
                // Pending's Scheduled tab (AdvancedSchedule.cs, v0.6.19), with every reset rule still to act and every queued
                // message as rows, and the Done section at its fullest.
                if (form.advancedResets != null)
                {
                    form.advancedPrompts = Map(kept, "advanced-prompts");
                    form.ShowPage("pending");
                    form.FillScheduled();
                    form.ChooseSchedule(true);
                    form.AuditScheduled("pending/scheduled", findings);
                    form.ChooseSchedule(false);
                    form.ShowAdvanced();
                }
                // v0.6.19 (#50): the prompt queue's editor, built and never shown - for a time (its send mode showing), for
                // after this turn, and with the longest refusal said above its buttons.
                form.AuditEditor("editor", findings);
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

        /// The prompt queue's editor (AdvancedEditor.cs), built and never shown, held to the standard audit's checks: nothing
        /// cut off, nothing scrolling sideways, every control named - for a time, for after this turn, and refused.
        private void AuditEditor(string where, List<string> findings)
        {
            foreach (string when in new[] { "at_time", "after_turn" })
            {
                using (Form dialog = BuildEditor(null))
                {
                    dialog.TopLevel = false;
                    SelectChoice(editorWhen, when);
                    ShowEditorState();
                    if (when == "after_turn") editorSaid.Text = PromptRefusal("queue_full");
                    Materialise(dialog);
                    dialog.PerformLayout();
                    Walk(dialog, where + "/" + when, findings);
                    AuditSpoken(where + "/" + when, dialog, findings);
                    if (editorWords.Box.Font.SizeInPoints < Font.SizeInPoints + ReadingLarger - 0.01f)
                        findings.Add(where + " :: the words are not at the reading size");
                }
                ForgetEditor();
            }
        }

        /// Pending on its Scheduled tab: the standard audit's checks, on a page that is not this one - and each list's columns
        /// within it.
        private void AuditScheduled(string where, List<string> findings)
        {
            AdvancedAudited++;
            if (currentPage != "pending" || scheduleTabs == null || !OwnVisible(scheduleTabs) || !OwnVisible(scheduleView))
                findings.Add(where + " :: the Scheduled tab is not showing");
            if (scheduledList != null) AuditList(where + "/" + AuditName(scheduledList), scheduledList, findings);
            if (doneList != null && OwnVisible(doneHolder)) AuditList(where + "/" + AuditName(doneList), doneList, findings);
            Audit(where, findings);
            AuditSpoken(where, this, findings);
            AuditPins(where, findings);
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

        /// The report's card as `state` has it - on, watched or off, with what was written, checked, ended and said -
        /// or as nothing was ever done, for null: what the layout audit lays out (AdvancedLayoutAudit).
        private void AdoptReportState(Dictionary<string, object> item, Dictionary<string, object> state)
        {
            if (item != null)
            {
                string standing = Str(state, "state") ?? StateArmed;
                item["state"] = standing;
                item["stored"] = standing;
            }
            reportBuilt = Map(state, "built");
            reportChecked = Map(state, "checked");
            reportLast = Map(state, "last");
            reportTold = Str(state, "told");
            reportJobKind = Str(state, "job");
            reportJob = reportJobKind == null ? null : "audit";
            reportLoginText = Str(state, "login") ?? "";
            reportWordText = Str(state, "word") ?? "";
        }

        // ---------------------------------------------------------------- driving the page
        /// The page driven as a person would, from `scenarioJson`: {"answers": [the dialog's answers], "script": {command
        /// or "<command> <capability>": [replies, as the bridge gives them]}, "steps": [...]}. A step is one of
        ///   {"do": "snapshot", "reply": a dashboard reply}   read, as the window's clock reads one (ApplySnapshot)
        ///   {"do": "unavailable"}                             a read that failed (MarkUnavailable)
        ///   {"do": "show"}                                    the tab pressed
        ///   {"do": "page", "name": ...}                       another page's tab pressed
        ///   {"do": "choose", "id": ...}                       that capability's row chosen in the list
        ///   {"do": "press", "button": on|watch|off|all_off|   a button pressed, if it can be: the page's, Keep it on's
        ///    keep_on|send_again|let_go|report_write|          or the report card's
        ///    report_save|report_check|report_send}
        ///   {"do": "type", "into": login|word, "text": ...}  text typed into one of the report's boxes, whole
        ///   {"do": "poll"}                                    the running report job read, as the page's clock reads it
        ///   {"do": "save_to", "path": ...}                    the file the save dialog would answer with
        ///   {"do": "hourly", "value": n}                      the hourly limit chosen, and the pause after it over
        ///   {"do": "set_option", "key": ..., "value": n}      a choice made in that choice's drop-down
        ///   {"do": "rule", "tag": ..., "sampled": ...,        a new rule's fields filled - its code typed, or taken from the
        ///    "from": ..., "to": ..., "kind": ...}             samples' drop-down - and Add rule pressed, if it can be
        ///   {"do": "remove", "rule": n}                       that rule's Remove pressed, if it can be
        ///   {"do": "wording", "key": ..., "text": ...}         a wrap-up wording box filled and its Save words pressed
        ///   {"do": "custom_option", "key": ...,               Custom... chosen in that choice's drop-down, and its dialog -
        ///    "value": n | "cancel": true}                     built, never shown - given n and Use this value pressed, or
        ///                                                     Cancel pressed; what it said into "dialogs"
        ///   {"do": "send_now", "id": ...}                     that waiting recovery's Send now pressed, if it can be
        ///   {"do": "reset_add", "family": "bucket minutes",   a reset form filled - its window chosen first, then which
        ///    "ordinal": ..., "repeat": once|every,            one, how often and whether it asks, or the conversation and
        ///    "ask": own|ask, "thread": ..., "words": ...}     the words - and Add pressed, if it can be
        ///   {"do": "reset_cancel"|"reset_go_on"|              that rule's Cancel or Go on counting pressed on the page, or
        ///    "scheduled_cancel"|"scheduled_go_on", "rule": n} in Pending's scheduled group, if it can be
        ///   {"do": "credit_now", "rule": n | "family": ...}   a Use a reset credit now... pressed, if it can be
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
        /// <argument>"), every question asked, every notice told, each press of a button that could not be
        /// pressed, and each Custom... dialog opened (v0.6.16 final): its title, what it said above its number on
        /// opening and after Use this value, the number it opened with, its buttons, and what the Settings page's audit
        /// of its dialogs finds in it.
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
                var dialogs = new List<object>();
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
                                      : name == "off" ? form.advancedOff : name == "all_off" ? form.advancedAllOff
                                      : name == "keep_on" ? form.keepOnButton : name == "send_again" ? form.sendAgainButton
                                      : name == "let_go" ? form.letGoButton
                                      : name == "report_write" ? form.reportWrite : name == "report_save" ? form.reportSave
                                      : name == "report_check" ? form.reportCheck : name == "report_send" ? form.reportSend
                                      : name == "queue_go" ? form.queueAdd : null;
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
                    else if (what == "set_option" && form.advancedSwitches.Exists(delegate(SoftCheck each) { return Equals(each.Tag, Str(step, "key")); }))
                    {
                        // An on/off choice (v0.6.16 final): its switch pressed where the value asked for is not the one it
                        // shows - as UI Automation presses it, its default action, or with "by": "keyboard" as Space does -
                        // and nothing sent where it is.
                        SoftCheck toggle = form.advancedSwitches.Find(delegate(SoftCheck each) { return Equals(each.Tag, Str(step, "key")); });
                        if (!toggle.Enabled) disabled.Add("set_option");
                        else if ((Whole(Get(step, "value")) == SwitchOn) != toggle.Checked)
                        {
                            if (Str(step, "by") == "keyboard")
                            {
                                KeyGoesDown.Invoke(toggle, new object[] { new KeyEventArgs(Keys.Space) });
                                KeyComesUp.Invoke(toggle, new object[] { new KeyEventArgs(Keys.Space) });
                            }
                            else toggle.AccessibilityObject.DoDefaultAction();
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
                    else if (what == "custom_option")
                    {
                        string key = Str(step, "key") ?? "";
                        SoftCombo combo = form.advancedChoices.Find(delegate(SoftCombo each) { return Equals(each.Tag, key); });
                        if (combo == null || !combo.Enabled || !form.customPicks.ContainsKey(key)) disabled.Add("custom_option");
                        else
                        {
                            var record = new Dictionary<string, object>();
                            record["key"] = key;
                            var found = new List<string>();
                            form.AuditCustomValues("custom_option", new HashSet<string>(), found);
                            record["findings"] = new List<object>(found.ToArray());
                            Dictionary<string, object> answer = step;
                            form.customAnswer = delegate(Form dialog) { form.AnswerCustom(dialog, answer, record); };
                            try
                            {
                                Choose(combo, CustomChoice);
                                Committed.Invoke(combo, new object[] { EventArgs.Empty });
                            }
                            finally
                            {
                                form.customAnswer = null;
                            }
                            dialogs.Add(record);
                        }
                    }
                    else if (what == "wording")
                    {
                        SoftTextArea box;
                        Button save;
                        if (!form.wordingBoxes.TryGetValue(Str(step, "key") ?? "", out box) ||
                            !form.wordingSaves.TryGetValue(Str(step, "key") ?? "", out save) || !save.Enabled)
                            disabled.Add("wording");
                        else
                        {
                            box.Box.Text = Str(step, "text") ?? "";
                            Pressed.Invoke(save, new object[] { EventArgs.Empty });
                        }
                    }
                    else if (what == "send_now")
                    {
                        Button send = form.sendNowButtons.Find(delegate(Button each) { return Equals(each.Tag, Str(step, "id")); });
                        if (send == null || !send.Enabled) disabled.Add("send_now");
                        else Pressed.Invoke(send, new object[] { EventArgs.Empty });
                    }
                    else if (what == "reset_add")
                    {
                        if (form.resetAdd == null || form.resetFamily == null) disabled.Add("reset_add");
                        else
                        {
                            if (Str(step, "family") != null)
                            {
                                Choose(form.resetFamily, Str(step, "family"));
                                Committed.Invoke(form.resetFamily, new object[] { EventArgs.Empty });
                            }
                            foreach (KeyValuePair<string, SoftCombo> field in new Dictionary<string, SoftCombo> {
                                         { "ordinal", form.resetOrdinal }, { "repeat", form.resetRepeat }, { "ask", form.resetAsk },
                                         { "thread", form.resetConversation } })
                                if (Str(step, field.Key) != null && field.Value != null)
                                {
                                    Choose(field.Value, Str(step, field.Key));
                                    Committed.Invoke(field.Value, new object[] { EventArgs.Empty });
                                }
                            if (Str(step, "words") != null && form.resetWords != null) form.resetWords.Box.Text = Str(step, "words");
                            if (!form.resetAdd.Enabled) disabled.Add("reset_add");
                            else Pressed.Invoke(form.resetAdd, new object[] { EventArgs.Empty });
                        }
                    }
                    else if (what == "scheduled_cancel" || what == "scheduled_go_on")
                    {
                        // v0.6.19: the rule's row chosen on Pending's Scheduled tab, then its Cancel or Go on pressed.
                        form.ChooseScheduledRow("rule " + Whole(Get(step, "rule")).ToString(System.Globalization.CultureInfo.InvariantCulture));
                        Button button = what == "scheduled_cancel" ? form.scheduleCancelButton : form.scheduleGoOnButton;
                        if (button == null || !button.Enabled) disabled.Add(what);
                        else Pressed.Invoke(button, new object[] { EventArgs.Empty });
                    }
                    else if (what == "tab") form.ChooseSchedule(Str(step, "name") == "scheduled");
                    else if (what == "scheduled_choose") form.ChooseScheduledRow(Str(step, "key"));
                    else if (what == "scheduled_press")
                    {
                        // v0.6.19 (#50): one of the Scheduled tab's buttons pressed, if it can be - the editor it opens
                        // answered as "editor" says, never shown; what it showed into "dialogs".
                        string name = Str(step, "button");
                        Button button = name == "add" ? form.scheduleAddButton : name == "edit" ? form.scheduleEditButton
                                      : name == "cancel" ? form.scheduleCancelButton : name == "go_on" ? form.scheduleGoOnButton
                                      : name == "clear" ? form.clearDoneButton : null;
                        if (button == null || !button.Enabled) disabled.Add("scheduled_press " + name);
                        else
                        {
                            var record = new Dictionary<string, object>();
                            Dictionary<string, object> answer = Map(step, "editor");
                            if (answer == null)
                            {
                                answer = new Dictionary<string, object>();
                                answer["press"] = "cancel";
                            }
                            form.editorAnswer = delegate(Form dialog) { form.AnswerEditor(dialog, answer, record); };
                            try
                            {
                                Pressed.Invoke(button, new object[] { EventArgs.Empty });
                            }
                            finally
                            {
                                form.editorAnswer = null;
                            }
                            if (record.Count > 0)
                            {
                                record["saved"] = (double)form.editorSaved;
                                dialogs.Add(record);
                            }
                        }
                    }
                    else if (what == "reset_cancel" || what == "reset_go_on" || what == "credit_now")
                    {
                        List<Button> buttons = what == "reset_cancel" ? form.resetCancels : what == "reset_go_on" ? form.resetGoOns
                                             : form.creditNowButtons;
                        object key = Get(step, "rule") ?? Get(step, "family");
                        Button found = buttons.Find(delegate(Button each) { return Equals(each.Tag, key); });
                        if (found == null || !found.Enabled) disabled.Add(what);
                        else Pressed.Invoke(found, new object[] { EventArgs.Empty });
                    }
                    else if (what == "editor")
                    {
                        // v0.6.19 (#50): the editor opened - for a new message, or for the prompt `prompt` - filled and
                        // answered as `step` says, never shown; what it showed and said into "editors".
                        var record = new Dictionary<string, object>();
                        Dictionary<string, object> answer = step;
                        Dictionary<string, object> row = null;
                        if (Get(step, "prompt") != null)
                            foreach (object listed in Items(form.advancedPrompts, "prompts") ?? new List<object>())
                                if (Equals(Get(listed as Dictionary<string, object>, "prompt_id"), Get(step, "prompt")))
                                    row = listed as Dictionary<string, object>;
                        form.editorAnswer = delegate(Form dialog) { form.AnswerEditor(dialog, answer, record); };
                        try
                        {
                            form.OpenEditor(row);
                        }
                        finally
                        {
                            form.editorAnswer = null;
                        }
                        record["saved"] = (double)form.editorSaved;
                        dialogs.Add(record);
                    }
                    else if (what == "run_stop")
                    {
                        Button stop = form.runStops.Find(delegate(Button each) { return Equals(each.Tag, Str(step, "key")); });
                        if (stop == null || !stop.Enabled) disabled.Add("run_stop");
                        else Pressed.Invoke(stop, new object[] { EventArgs.Empty });
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
                    else if (what == "type")
                    {
                        SoftTextArea box = Str(step, "into") == "word" ? form.reportWord : form.reportLogin;
                        if (box == null || !OwnVisible(box)) disabled.Add("type " + Str(step, "into"));
                        else box.Box.Text = Str(step, "text") ?? "";
                    }
                    else if (what == "poll") form.PollReport();
                    else if (what == "save_to") form.advancedSaveTo = Str(step, "path");
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
                result["dialogs"] = dialogs;
            });
            return Json.Write(result);
        }

        /// A Custom... dialog (AdvancedUsage.cs AskCustom), built and never shown, answered as `step` says - its number set
        /// and Use this value pressed, or Cancel pressed - and what it said written into `record`.
        private void AnswerCustom(Form dialog, Dictionary<string, object> step, Dictionary<string, object> record)
        {
            NumericUpDown spin = ((SoftNumber)((SoftFlow)ownEditor).Controls[0]).Spin;
            var use = (Button)dialog.AcceptButton;
            var cancel = (Button)dialog.CancelButton;
            record["title"] = dialog.Text;
            record["hint"] = ownHint.Text;
            record["opened"] = (double)spin.Value;
            record["buttons"] = new List<object> { use.Text, cancel.Text };
            if (Equals(Get(step, "cancel"), true))
            {
                Pressed.Invoke(cancel, new object[] { EventArgs.Empty });
                return;
            }
            spin.Value = Whole(Get(step, "value"));
            Pressed.Invoke(use, new object[] { EventArgs.Empty });
            // Still open where the number was refused: what it says then, above the number.
            record["after"] = dialog.IsDisposed ? null : ownHint.Text;
        }

        /// The editor (AdvancedEditor.cs), built and never shown: what it opened with written into `record`, its fields filled
        /// as `step` says - "thread", "words", "when", "hour", "times", "depends", "mode" - and "press" save or cancel; then
        /// what it said, and whether it saved.
        private void AnswerEditor(Form dialog, Dictionary<string, object> step, Dictionary<string, object> record)
        {
            record["title"] = dialog.Text;
            record["conversations"] = ItemsOf(editorConversation);
            record["conversation_enabled"] = editorConversation.Enabled;
            record["words"] = editorWords.Box.Text;
            record["reading_points"] = (double)editorWords.Box.Font.SizeInPoints;
            record["window_points"] = (double)Font.SizeInPoints;
            record["when"] = ((Choice)editorWhen.SelectedItem).Value;
            record["mode"] = editorMode.Value;
            var modes = new List<object>();
            foreach (Control card in editorMode.Controls) modes.Add(card.Text);
            record["modes"] = modes;
            record["buttons"] = new List<object> { editorSave.Text, editorCancel.Text };
            record["accept"] = dialog.AcceptButton == editorSave;
            foreach (KeyValuePair<string, SoftCombo> field in new Dictionary<string, SoftCombo> {
                         { "thread", editorConversation }, { "when", editorWhen }, { "hour", editorHour }, { "times", editorTimes },
                         { "depends", editorDepends } })
                if (Str(step, field.Key) != null)
                {
                    Choose(field.Value, Str(step, field.Key));
                    Committed.Invoke(field.Value, new object[] { EventArgs.Empty });
                }
            if (Str(step, "words") != null) editorWords.Box.Text = Str(step, "words");
            if (Str(step, "mode") != null) editorMode.Value = Str(step, "mode");
            record["mode_shown"] = OwnVisible(editorMode);
            record["after_turn_shown"] = OwnVisible(editorAfterTurn);
            if (Str(step, "press") == "save")
            {
                if (!editorSave.Enabled) record["save_disabled"] = true;
                else Pressed.Invoke(editorSave, new object[] { EventArgs.Empty });
            }
            else Pressed.Invoke(editorCancel, new object[] { EventArgs.Empty });
            record["taken"] = dialog.DialogResult == DialogResult.OK;
            record["said"] = editorSaid.Text;
            record["words_after"] = editorWords.Box.Text;
        }

        // Control.OnClick, which raises Click as a press of the button does.
        private static readonly System.Reflection.MethodInfo Pressed =
            typeof(Control).GetMethod("OnClick", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
        // Control.OnKeyDown and OnKeyUp, which a key pressed and let go on the focused control raises: Space on a switch.
        private static readonly System.Reflection.MethodInfo KeyGoesDown =
            typeof(Control).GetMethod("OnKeyDown", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
        private static readonly System.Reflection.MethodInfo KeyComesUp =
            typeof(Control).GetMethod("OnKeyUp", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
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
            // How many times the list's cells had been measured by then (FillAdvancedList).
            look["measures"] = (double)advancedMeasures;
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
            // Its on/off choices (v0.6.16 final), each a switch: on or off as drawn, whether it can be pressed, and what a
            // screen reader is told - its name and its role.
            var switches = new List<object>();
            foreach (SoftCheck toggle in advancedSwitches)
            {
                var each = new Dictionary<string, object>();
                each["key"] = toggle.Tag as string;
                each["on"] = toggle.Checked;
                each["enabled"] = toggle.Enabled;
                each["name"] = toggle.AccessibleName;
                each["role"] = toggle.AccessibilityObject.Role.ToString();
                switches.Add(each);
            }
            look["switches"] = switches;
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
            // Keep it on's buttons - whether each can be pressed, or null where it is not shown - and the waiting
            // recoveries Send now offers, by their interruption ids.
            var kept = new Dictionary<string, object>();
            kept["keep_on"] = keepOnButton == null ? (object)null : keepOnButton.Enabled;
            kept["send_again"] = sendAgainButton == null ? (object)null : sendAgainButton.Enabled;
            kept["let_go"] = letGoButton == null ? (object)null : letGoButton.Enabled;
            look["kept"] = kept;
            // v0.6.16-beta.4: the wrap-up's wording boxes, by key, with what each holds now.
            var wordings = new Dictionary<string, object>();
            foreach (KeyValuePair<string, SoftTextArea> box in wordingBoxes) wordings[box.Key] = box.Value.Box.Text;
            look["wordings"] = wordings;
            var previewed = new List<object>();
            foreach (Label line in previewLines) previewed.Add(line.Text);
            look["previews"] = previewed;
            var waiting = new List<object>();
            foreach (Button send in sendNowButtons) waiting.Add(send.Tag);
            look["send_now"] = waiting;
            // The turns run here: what each Stop... names (v0.6.16-beta.4); and Pending's and History's rows as the
            // lists draw them - each cell's text - where those pages are built.
            look["run_stops"] = Tags(runStops);
            look["pending_rows"] = ListCells(pendingList);
            look["history_rows"] = ListCells(historyList);
            // The open reset action's form - what each drop-down offers and holds, the count of the words, whether Add can
            // be pressed - and the rules its Cancel, Go on counting and Use a reset credit now... buttons name; and
            // Pending's scheduled group: whether it shows, its lines and what its Cancel buttons name.
            if (resetAdd != null)
            {
                var resets = new Dictionary<string, object>();
                foreach (KeyValuePair<string, SoftCombo> field in new Dictionary<string, SoftCombo> {
                             { "families", resetFamily }, { "ordinals", resetOrdinal }, { "repeat", resetRepeat }, { "ask", resetAsk },
                             { "conversations", resetConversation } })
                {
                    resets[field.Key] = field.Value == null ? null : ItemsOf(field.Value);
                    resets[field.Key + "_chosen"] = field.Value == null || field.Value.SelectedItem == null ? null
                                                    : field.Value.SelectedItem.ToString();
                }
                resets["words"] = resetWords == null ? null : resetWords.Box.Text;
                resets["most"] = resetWords == null ? (object)null : (double)resetWords.Box.MaxLength;
                resets["count"] = resetCount == null ? null : resetCount.Text;
                resets["add"] = resetAdd.Enabled;
                resets["cancels"] = Tags(resetCancels);
                resets["go_ons"] = Tags(resetGoOns);
                resets["now"] = Tags(creditNowButtons);
                look["resets"] = resets;
            }
            else look["resets"] = null;
            // v0.6.19 (#50): Pending's tabs and its Scheduled tab - whether the strip shows and which is chosen, each tab's
            // words, each row as the list draws it with the key it stands for and whether it is chosen, the Done section's
            // rows, what each button may do, Delete completed's words, and the note beside the buttons.
            var scheduled = new Dictionary<string, object>();
            scheduled["tabs_shown"] = scheduleTabs != null && OwnVisible(scheduleTabs);
            scheduled["chosen"] = scheduleChosen ? "scheduled" : "recoveries";
            var tabs = new List<object>();
            if (scheduleTabs != null)
            {
                tabs.Add(recoveriesTab.Text);
                tabs.Add(scheduledTab.Text);
            }
            scheduled["tabs"] = tabs;
            scheduled["rows"] = ListCells(scheduledList);
            var keys = new List<object>();
            var chosenKeys = new List<object>();
            if (scheduledList != null)
                foreach (ListViewItem item in scheduledList.Items)
                {
                    keys.Add(RowKey(item.Tag as Dictionary<string, object>));
                    if (item.Selected) chosenKeys.Add(RowKey(item.Tag as Dictionary<string, object>));
                }
            scheduled["keys"] = keys;
            scheduled["selected"] = chosenKeys;
            scheduled["done"] = ListCells(doneList);
            scheduled["done_shown"] = doneHolder != null && OwnVisible(doneHolder);
            var scheduleButtons = new Dictionary<string, object>();
            if (scheduleAddButton != null)
            {
                scheduleButtons["add"] = scheduleAddButton.Enabled;
                scheduleButtons["edit"] = scheduleEditButton.Enabled;
                scheduleButtons["cancel"] = scheduleCancelButton.Enabled;
                scheduleButtons["go_on"] = scheduleGoOnButton.Enabled;
                scheduleButtons["clear"] = clearDoneButton.Enabled;
                scheduled["clear_text"] = clearDoneButton.Text;
            }
            scheduled["buttons"] = scheduleButtons;
            scheduled["note"] = scheduledNote == null ? null : scheduledNote.Text;
            look["scheduled"] = scheduled;
            // v0.6.19 (#50): the prompt queue's card - its one line and Go to Scheduled.
            var queue = new Dictionary<string, object>();
            queue["go"] = queueAdd == null ? (object)null : (object)queueAdd.Enabled;
            look["queue"] = queue;
            // The report's card: what its boxes hold, what each of its buttons may do (null where there is none), the
            // job it is reading, what it said and how the last check or send ended, the text it shows in boxes that can
            // be selected (a link, a SHA-256), and how many holds on the window's reopen there are.
            var report = new Dictionary<string, object>();
            report["login"] = reportLogin == null ? null : reportLogin.Box.Text;
            report["word"] = reportWord == null ? null : reportWord.Box.Text;
            report["file"] = reportFile == null ? null : reportFile.Box.Text;
            var pressable = new Dictionary<string, object>();
            pressable["write"] = reportWrite == null ? null : (object)reportWrite.Enabled;
            pressable["save"] = reportSave == null ? null : (object)reportSave.Enabled;
            pressable["check"] = reportCheck == null ? null : (object)reportCheck.Enabled;
            pressable["send"] = reportSend == null ? null : (object)reportSend.Enabled;
            report["buttons"] = pressable;
            report["job"] = reportJob;
            report["kind"] = reportJobKind;
            report["told"] = reportTold;
            report["checked"] = Str(reportChecked, "status");
            report["last"] = Str(reportLast, "status");
            var boxes = new List<object>();
            if (advancedStack != null) Boxes(advancedStack, boxes);
            report["boxes"] = boxes;
            report["holds"] = (double)reopenHolds;
            look["report"] = report;
            return look;
        }

        private static List<object> ListCells(ListView list)
        {
            var rows = new List<object>();
            if (list != null)
                foreach (ListViewItem item in list.Items)
                {
                    var row = new List<object>();
                    for (int cell = 0; cell < item.SubItems.Count; cell++) row.Add(item.SubItems[cell].Text);
                    rows.Add(row);
                }
            return rows;
        }

        private static List<object> Tags(List<Button> buttons)
        {
            var tags = new List<object>();
            foreach (Button button in buttons) tags.Add(button.Tag);
            return tags;
        }

        /// The text of every read-only box in `control`, in order: what the page shows that a person can select.
        private static void Boxes(Control control, List<object> into)
        {
            var area = control as SoftTextArea;
            if (area != null && area.Box.ReadOnly) into.Add(area.Box.Text);
            foreach (Control child in control.Controls) Boxes(child, into);
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

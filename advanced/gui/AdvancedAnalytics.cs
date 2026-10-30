// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the usage and token analytics on the Advanced features page (v0.6.20).
//
// While usage_analytics is on or watched, its column has two cards under its limits. Pace: for each window the usage
// meter reads (the five-hour and the weekly), how full it is, the change over the last hour and - with enough readings
// and only before the window resets - around when it would be full at that pace, beside the reset; never a promise.
// Tokens: a flat list, one line a project (Codex's project name, else its folder's name, resolved by the bridge now and
// never stored), input, cached input, output, reasoning and turns over the days chosen (the capability's own choice,
// 7, 30 or 90), a total line, and each project's conversations under it on demand. Where MTOK failed on the Codex in
// force the list holds lifetime totals alone, and says so. Save as CSV... asks where in the save dialog - which asks
// itself before it replaces a file - and the bridge writes the file there (advanced-analytics-csv).
//
// Nothing here draws anything the page does not draw already: the cards, help lines and buttons are the Settings page's,
// and the list's lines stay flat hairline rows (memory window-lists-stay-flat).
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string AnalyticsId = "usage_analytics";

        // advanced-analytics' last answer, or null where it was not read or the read failed.
        private Dictionary<string, object> advancedAnalytics;
        // The projects whose conversations are shown, by key ("" for the one with none).
        private readonly HashSet<string> analyticsOpen = new HashSet<string>();
        // The card's buttons as they were built.
        private Button analyticsSave;
        private readonly List<Button> analyticsToggles = new List<Button>();
        // What the last save said, under its button.
        private string analyticsTold;

        /// What the analytics cards are built from, for ShowAdvancedDetail to build them again only when it changed.
        private string AnalyticsShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != AnalyticsId) return "";
            var open = new List<string>(analyticsOpen);
            open.Sort(StringComparer.Ordinal);
            return AdvancedWritten(advancedAnalytics) + "|" + string.Join(",", open.ToArray()) + "|" + (analyticsTold ?? "");
        }

        /// Read advanced-analytics (the days the capability's own choice says), keep it, and show it; `done` once shown.
        private void ReadAnalytics(MethodInvoker done)
        {
            AdvancedCall("advanced-analytics", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedAnalytics = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                if (done != null) done();
            });
        }

        private void ForgetAnalyticsCard()
        {
            analyticsSave = null;
            analyticsToggles.Clear();
        }

        private static string AnalyticsCount(object value)
        {
            return ((long)Math.Round(value is double ? (double)value : 0)).ToString("N0", CultureInfo.CurrentCulture);
        }

        private static string AnalyticsShare(object value)
        {
            return (value is double ? (double)value : 0).ToString("0.#", CultureInfo.CurrentCulture);
        }

        /// The pace and the tokens, while usage_analytics is on or watched and its numbers were read.
        private void BuildAnalytics(Dictionary<string, object> item)
        {
            ForgetAnalyticsCard();
            if (Str(item, "id") != AnalyticsId || !Standing(item) || advancedAnalytics == null) return;
            TableLayoutPanel pace = NewGroup(Word("page.analytics.pace", "Pace"), advancedStack);
            int windows = 0;
            foreach (object entry in Items(advancedAnalytics, "paces") ?? new List<object>())
            {
                var window = entry as Dictionary<string, object>;
                if (window == null || !(Get(window, "used") is double)) continue;
                windows++;
                string line = Word("page.analytics.used", "{window}: {percent}% used", "window", WindowName(Get(window, "minutes")))
                              .Replace("{percent}", AnalyticsShare(Get(window, "used")));
                if (Get(window, "change_hour") is double)
                    line += " · " + Word("page.analytics.change", "{change} in the last hour", "change",
                                         ((double)Get(window, "change_hour") >= 0 ? "+" : "") + AnalyticsShare(Get(window, "change_hour")));
                Label used = HelpText(line);
                used.ForeColor = Ink;
                used.Margin = Pad(0, 6, 0, 0);
                pace.Controls.Add(used);
                double eta = Get(window, "eta") is double ? (double)Get(window, "eta") : 0;
                double reset = Get(window, "reset_at") is double ? (double)Get(window, "reset_at") : 0;
                string more = eta > 0
                    ? Word("page.analytics.eta", "At this pace, full around {time}.", "time", ClockTime(eta))
                    : Word("page.analytics.not_enough", "Not enough readings yet for a pace.");
                if (reset > 0) more += " " + Word("page.analytics.resets", "It resets at {time}.", "time", ClockTime(reset));
                pace.Controls.Add(HelpText(more));
            }
            if (windows == 0)
                pace.Controls.Add(HelpText(Word("page.analytics.no_reading", "The usage meter has not read usage yet.")));

            int days = Whole(Get(advancedAnalytics, "days"));
            TableLayoutPanel card = NewGroup(Word("page.analytics.tokens", "Tokens in the last {n} days", "n", days), advancedStack);
            bool lifetime = Str(advancedAnalytics, "route") == "lifetime";
            if (lifetime)
                card.Controls.Add(HelpText(Word("page.analytics.lifetime_only",
                    "These counts were not measured to work on this Codex, so each conversation's lifetime total is shown instead.")));
            if (Equals(Get(advancedAnalytics, "behind"), true))
                card.Controls.Add(HelpText(Word("page.analytics.behind", "Still reading older conversations.")));
            int shown = 0;
            foreach (object entry in Items(advancedAnalytics, "projects") ?? new List<object>())
            {
                var project = entry as Dictionary<string, object>;
                if (project == null) continue;
                shown++;
                string key = Str(project, "key") ?? "";
                string name = Str(project, "label") ?? Word("page.analytics.other", "Other");
                Label line = HelpText(TokensLine(name, project));
                line.ForeColor = Ink;
                line.Margin = Pad(0, 6, 0, 2);
                card.Controls.Add(line);
                bool open = analyticsOpen.Contains(key);
                if (open)
                    foreach (object each in Items(project, "conversations") ?? new List<object>())
                    {
                        var conversation = each as Dictionary<string, object>;
                        if (conversation == null) continue;
                        string label = Str(conversation, "label") ?? ConversationOf(Str(conversation, "thread_id"));
                        Label row = HelpText(TokensLine(label, conversation));
                        row.Margin = Pad(Px(16), 2, 0, 0);
                        card.Controls.Add(row);
                    }
                string text = open ? Word("page.analytics.hide", "Hide conversations")
                                   : Word("page.analytics.show", "Show conversations");
                string chosen = key;
                Button toggle = CardButton(card, text, delegate { ToggleAnalytics(chosen); });
                toggle.Tag = key;
                toggle.AccessibleName = text + " " + name;
                analyticsToggles.Add(toggle);
            }
            if (shown == 0)
                card.Controls.Add(HelpText(Word("page.analytics.none", "No tokens are counted yet.")));
            else
            {
                Label total = HelpText(TokensLine(Word("page.analytics.total", "Total"), Map(advancedAnalytics, "total")));
                total.ForeColor = Ink;
                total.Margin = Pad(0, 8, 0, 2);
                card.Controls.Add(total);
            }
            analyticsSave = CardButton(card, Word("page.analytics.save", "Save as CSV..."), delegate { SaveAnalytics(); });
            analyticsSave.Margin = Pad(0, 8, 0, 4);
            if (!string.IsNullOrEmpty(analyticsTold)) card.Controls.Add(HelpText(analyticsTold));
        }

        /// One flat line of numbers: a project's, a conversation's or the total's - the five counts where the rollouts gave
        /// them, and the lifetime total where only that is known.
        private string TokensLine(string name, Dictionary<string, object> numbers)
        {
            string line = name;
            double input = Get(numbers, "input") is double ? (double)Get(numbers, "input") : 0;
            double output = Get(numbers, "output") is double ? (double)Get(numbers, "output") : 0;
            double turns = Get(numbers, "turns") is double ? (double)Get(numbers, "turns") : 0;
            if (input > 0 || output > 0 || turns > 0)
                line += " · " + Word("page.analytics.numbers",
                    "input {input} · cached {cached} · output {output} · reasoning {reasoning} · {turns} turns",
                    "input", AnalyticsCount(Get(numbers, "input")))
                    .Replace("{cached}", Mirror.Embed(AnalyticsCount(Get(numbers, "cached"))))
                    .Replace("{output}", Mirror.Embed(AnalyticsCount(Get(numbers, "output"))))
                    .Replace("{reasoning}", Mirror.Embed(AnalyticsCount(Get(numbers, "reasoning"))))
                    .Replace("{turns}", Mirror.Embed(AnalyticsCount(Get(numbers, "turns"))));
            if (Get(numbers, "lifetime") is double)
                line += " · " + Word("page.analytics.lifetime", "lifetime {n}", "n", AnalyticsCount(Get(numbers, "lifetime")));
            return line;
        }

        private void ToggleAnalytics(string key)
        {
            if (key == null) return;
            if (!analyticsOpen.Remove(key)) analyticsOpen.Add(key);
            ShowAdvancedDetail();
        }

        private void UpdateAnalyticsButtons(bool idle)
        {
            bool listed = idle && advancedListing != null && advancedAnalytics != null;
            if (analyticsSave != null) analyticsSave.Enabled = listed;
            foreach (Button toggle in analyticsToggles) toggle.Enabled = advancedAnalytics != null;
        }

        /// Where to save the CSV: the person's choice in the save dialog, which asks before it replaces a file (`replace`
        /// tells the bridge that it asked) - or the file a test chose, which is never one there already.
        private string AskCsvPath(out bool replace)
        {
            replace = false;
            if (advancedScript != null) return advancedSaveTo;
            using (var save = new SaveFileDialog())
            {
                save.Filter = "CSV (*.csv)|*.csv";
                save.FileName = "codex-usage.csv";
                save.OverwritePrompt = true;
                if (save.ShowDialog(this) != DialogResult.OK) return null;
                replace = File.Exists(save.FileName);
                return save.FileName;
            }
        }

        private void SaveAnalytics()
        {
            if (busy > 0 || advancedAnalytics == null) return;
            bool replace;
            string target = AskCsvPath(out replace);
            if (target == null) return;
            string argument = "{\"days\":" + Whole(Get(advancedAnalytics, "days")).ToString(CultureInfo.InvariantCulture) +
                              ",\"path\":" + Json.Escape(target) + ",\"replace\":" + (replace ? "true" : "false") + "}";
            AdvancedCall("advanced-analytics-csv", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                analyticsTold = AdvancedDone(result) ? Word("page.report.saved", "Saved.")
                              : result == null ? Word("page.refused.unavailable", "The advanced features could not be changed right now. Nothing was changed.")
                              : ReportRefusalText(Str(result, "refusal"));
                ShowAdvancedDetail();
            });
        }
    }
}

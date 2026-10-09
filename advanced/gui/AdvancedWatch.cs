// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Advanced features page's watch log (v0.6.14): what the open capability would have done while
// it was watched.
//
// While a capability is watched ("Watch first") it is asked wherever it would act, and none of its answers is taken: each
// is counted instead, once for each recovery and answer (advanced/src/codex_auto_resume_advanced/watchlog.py). This is
// where a person reads that count: a card, last in the open capability's column after its samples, so it moves none of
// the cards above it - its title; since when it is watched, where it is; one line for each answer, as each sample is a
// line - the answer in words, how many times and the last minute; that it has been asked nothing yet, where it is watched
// with nothing counted; from when it counts, where the bound let older answers go; and that watching does nothing. It
// shows only where the bridge's advanced-watch-log answered and the capability is watched or has answers counted in the
// 30 days; never for an action, which is never asked anything, so its log would always be empty.
//
// The page reads it after the rules and the samples (ReadAdvancedKept), and again at every read, so the card keeps up with
// each snapshot as the rest of the page does, with no timer of its own. Times are the window's own (When), so a picture
// with a pinned clock prints the same ones.
//
// Nothing here draws anything the page does not draw already: the card, its caption and its lines are the Settings
// page's, and each answer's line is styled as a sample's is.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // What each capability would have done while watched, as the last read of it answered (advanced-watch-log), or
        // null where that read failed: the card is built only from what was read. (`advancedWatch` is Watch first's
        // button.) The page and its audit fill it.
        private readonly Dictionary<string, Dictionary<string, object>> advancedWatchLog =
            new Dictionary<string, Dictionary<string, object>>();

        // The words the log names (watchlog.WORDS), each with its English, should the page's words lack it. An answer
        // outside them reads as "Something else".
        private static readonly Dictionary<string, string> WatchAnswers = new Dictionary<string, string>
        {
            { "hold", "Kept it waiting" }, { "client_id", "Sent it without a marker" }, { "admit", "Took the failure up" },
            { "as_network_transient", "Took it up as a network failure" }, { "as_timeout", "Took it up as a timeout" },
            { "as_rate_limit_transient", "Took it up as a rate limit" }, { "as_server_5xx", "Took it up as a server error" },
            { "as_stream_interrupted", "Took it up as a broken stream" }, { "capacity", "Retried a capacity error sooner" },
            { "early", "Looked before the reset time" }, { "resend", "Sent it once more" }, { "send_now", "Sent it now" },
            { "text", "Wrote its own words" }, { "sender", "Sent it its own way" }, { "tick", "Acted between looks" },
            { "start_route", "Started the watcher its own way" }, { "unloaded", "Opened the conversation itself" },
        };

        /// The open capability's watch log as last read, for ShowAdvancedDetail to compare; "" where there is none.
        private string WatchShown(string id)
        {
            Dictionary<string, object> log;
            return id != null && advancedWatchLog.TryGetValue(id, out log) ? AdvancedWritten(log) : "";
        }

        /// The request that reads `id`'s watch log, quoted as the statement's request quotes it.
        private static string WatchArgument(string id)
        {
            return "{\"capability\":" + Json.Escape(id) + "}";
        }

        /// The card of what `id` would have done while watched, last in its column - only where its log was read, it is
        /// not an action, and it is watched or has answers counted.
        private void BuildAdvancedWatch(Dictionary<string, object> item)
        {
            string id = Str(item, "id");
            Dictionary<string, object> log;
            if (id == null || IsAction(item) || !advancedWatchLog.TryGetValue(id, out log) || log == null || !AdvancedDone(log))
                return;
            object since = Get(log, "watched_since"), from = Get(log, "from");
            List<object> entries = Items(log, "entries") ?? new List<object>();
            bool watched = since is double;
            if (!watched && entries.Count == 0) return;
            TableLayoutPanel card = NewGroup(Word("page.watchlog", "What it would have done while watched, last 30 days"), advancedStack);
            if (watched)
            {
                Label line = HelpText(Word("page.watchlog.since", "Watched since {time}.", "time", When((double)since)));
                line.ForeColor = Ink;
                card.Controls.Add(line);
            }
            foreach (object entry in entries)
            {
                var answer = entry as Dictionary<string, object>;
                if (answer == null) continue;
                object last = Get(answer, "last");
                string text = WatchAnswer(Str(answer, "answer")) +
                              " · " + Word("page.watchlog.times", "Times") + ": " +
                              Whole(Get(answer, "count")).ToString(CultureInfo.CurrentCulture) +
                              " · " + Word("page.watchlog.last", "Last") + ": " + (last is double ? When((double)last) : "-");
                Label line = HelpText(text);
                line.ForeColor = Ink;
                line.Margin = Pad(0, 2, 0, 4);
                card.Controls.Add(line);
            }
            if (watched && entries.Count == 0)
                card.Controls.Add(HelpText(Word("page.watchlog.none", "Nothing yet: it has not been asked anything it would have acted on.")));
            if (Equals(Get(log, "full"), true) && from is double)
                card.Controls.Add(HelpText(Word("page.watchlog.from", "Counted from {time}: older answers were let go.", "time",
                                                When((double)from))));
            card.Controls.Add(HelpText(Word("page.watchlog.note",
                "Watching does nothing: each answer is only counted here, once for each recovery.")));
        }

        /// An answer in the person's words: one the log names, or "Something else".
        private string WatchAnswer(string answer)
        {
            string english;
            if (answer == null || !WatchAnswers.TryGetValue(answer, out english))
                return Word("page.watchlog.answer.other", "Something else");
            return Word("page.watchlog.answer." + answer, english);
        }
    }
}

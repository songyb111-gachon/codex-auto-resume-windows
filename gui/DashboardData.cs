// Codex Auto Resume - the clock, the snapshot, and everything read out of a reply.
//
// One refresh at a time and one snapshot applied at a time, with the small readers that turn
// a reply's numbers into the words a row shows.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Forms.Automation;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // ------------------------------------------------------------------ clock
        private void StartClock()
        {
            // Started again, the same clock: after a reopen whose new window never came up (FinishReopen).
            if (clock != null)
            {
                clock.Start();
                return;
            }
            clock = new Timer();
            clock.Interval = 1000;
            clock.Tick += delegate
            {
                ticks++;
                UpdateCountdowns();
                // The taskbar button asks again whether it may move - a Reduce motion saved, Windows' animation
                // effects, High Contrast or battery saver turned on or off - within a second of it (TaskbarMark.Sync).
                if (taskbar != null) taskbar.Sync();
                // Every second too, so a usage reset that passes while a row stays selected
                // makes Retry now available without waiting for the next read.
                UpdatePendingButtons();
                // The data every five seconds, the countdown every second. Nothing on the
                // Settings page is refreshed under a person who is editing it.
                if (ticks % 5 == 0 && currentPage != "settings")
                {
                    RefreshNow();
                    if (currentPage == "statistics") LoadStatistics();
                    // The watcher's report, read as the rest of the page is. Never the refresh: that is a request to
                    // GitHub, and only its button makes one.
                    if (currentPage == "diagnostics") LoadCompatibility();
                }
                // On the Settings page nothing is read under the person editing it, but a failure still is: from the
                // status alone, for the taskbar button and for seeing it (RefreshFailure, v0.6.8).
                else if (ticks % 5 == 0) RefreshFailure();
                // A language or theme changed elsewhere, or edits put back under a pending reopen.
                TickReopen();
            };
            clock.Start();
        }

        private void StopClock()
        {
            if (clock != null) clock.Stop();
        }

        // A read for its own sake: the clock, a page switch, F5.
        private void RefreshNow()
        {
            Reread(false);
        }

        // A read after this window changed something. If a read is already in flight it may
        // have started before that change, so its answer is thrown away and a new read made.
        private void RefreshAfterChange()
        {
            Reread(true);
        }

        private void Reread(bool afterChange)
        {
            if (refreshing)
            {
                if (afterChange) refreshAgain = true;
                return;
            }
            refreshing = true;
            refreshAgain = false;
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply = null;
                try { reply = bridge.Call("dashboard", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    refreshing = false;
                    if (refreshAgain)
                    {
                        refreshAgain = false;
                        Reread(false);
                        return;
                    }
                    if (Ok(reply))
                    {
                        snapshotAge.Restart();
                        ApplySnapshot(reply);
                    }
                    else MarkUnavailable();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { refreshing = false; refreshAgain = false; }
            });
        }

        // -------------------------------------------------------------- json access
        // Every read of a reply goes through these: a key the local service did not send is
        // an absent value here, never a KeyNotFoundException in a paint or a timer.
        private static object Get(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        private static bool Ok(Dictionary<string, object> reply)
        {
            return reply != null && Equals(Get(reply, "ok"), true);
        }

        private static double Number(Dictionary<string, object> map, string key)
        {
            object value = Get(map, key);
            return value is double ? (double)value : 0;
        }

        private static int Whole(object value)
        {
            return value is double ? (int)(double)value : 0;
        }

        private static string Str(Dictionary<string, object> map, string key)
        {
            return Get(map, key) as string;
        }

        private static List<object> Items(Dictionary<string, object> map, string key)
        {
            return Get(map, key) as List<object>;
        }

        private static Dictionary<string, object> Map(Dictionary<string, object> map, string key)
        {
            return Get(map, key) as Dictionary<string, object>;
        }

        private static double Now()
        {
            if (Soft.StillNow > 0) return Soft.StillNow;        // held still for a picture
            return (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        }

        // -------------------------------------------------------------------- words
        private string Countdown(double seconds)
        {
            int total = Math.Max(0, (int)seconds);
            int hours = total / 3600, minutes = (total % 3600) / 60, secs = total % 60;
            if (hours > 0) return string.Format(CultureInfo.InvariantCulture, "{0}:{1:00}:{2:00}", hours, minutes, secs);
            if (minutes > 0) return string.Format(CultureInfo.InvariantCulture, "{0}:{1:00}", minutes, secs);
            return S("time.seconds", "{n}s", "n", secs);
        }

        private string Duration(double seconds)
        {
            // How long something took: "9m 20s", not the "9:20" a countdown would show,
            // which reads as a time of day.
            int total = Math.Max(0, (int)Math.Round(seconds));
            if (total < 60) return S("time.seconds", "{n}s", "n", total);
            if (total < 3600)
                return S("time.minutes", "{n}m", "n", total / 60) +
                       (total % 60 == 0 ? "" : " " + S("time.seconds", "{n}s", "n", total % 60));
            return S("time.hours", "{n}h", "n", total / 3600) +
                   ((total % 3600) / 60 == 0 ? "" : " " + S("time.minutes", "{n}m", "n", (total % 3600) / 60));
        }

        private string Age(double seconds)
        {
            // How long ago, in the largest unit that is not zero. A countdown is read to
            // the second; an age of "26:04:11" is not read at all.
            int total = Math.Max(0, (int)seconds);
            if (total < 5) return S("time.just_now", "just now");
            if (total < 60) return S("time.ago", "{time} ago", "time", S("time.seconds", "{n}s", "n", total));
            if (total < 3600) return S("time.ago", "{time} ago", "time", S("time.minutes", "{n}m", "n", total / 60));
            if (total < 86400) return S("time.ago", "{time} ago", "time", S("time.hours", "{n}h", "n", total / 3600));
            return S("time.ago", "{time} ago", "time", S("time.days", "{n}d", "n", total / 86400));
        }

        private static string When(double stamp)
        {
            if (stamp <= 0) return "";
            DateTime local = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(stamp).ToLocalTime();
            return local.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
        }

        private string Ago(double stamp)
        {
            if (stamp <= 0) return S("time.never", "never");
            return Age(Now() - stamp);
        }

        private string Conversation(Dictionary<string, object> row)
        {
            string name = Str(row, "name") ?? Str(row, "project") ?? Str(row, "cwd_basename");
            string thread = Str(row, "thread_id") ?? "";
            return name ?? (thread.Length >= 8 ? thread.Substring(0, 8) : thread);
        }

        private string CodeLabel(Dictionary<string, object> row)
        {
            string code = Str(row, "code") ?? Str(row, "state") ?? "";
            var parts = new List<string>();
            parts.Add(S("code." + code, code.Replace('_', ' ')));
            var overlays = Items(row, "overlays");
            if (overlays != null)
                foreach (object overlay in overlays)
                    parts.Add(S("overlay." + overlay, Convert.ToString(overlay).Replace('_', ' ')));
            return string.Join(" · ", parts.ToArray());
        }

        private string KindLabel(Dictionary<string, object> row)
        {
            // The reason's own name, as the notifications and the popup say it.
            string category = Str(row, "category") ?? "";
            return S("reason." + category, S("field.recover_" + category, category.Replace('_', ' ')));
        }

        private static bool HasOverlay(Dictionary<string, object> row, string name)
        {
            var overlays = Items(row, "overlays");
            if (overlays != null)
                foreach (object overlay in overlays)
                    if (Convert.ToString(overlay) == name) return true;
            return false;
        }

        private static bool ThreadOn(Dictionary<string, object> row)
        {
            object value = Get(row, "thread_enabled");
            return value == null || Equals(value, true);
        }

        // ------------------------------------------------------------ snapshot use
        private void ApplySnapshot(Dictionary<string, object> reply)
        {
            snapshot = reply;
            var status = Map(reply, "status");
            // Only the pages built so far have anything to write to. A page built later is handed
            // this same snapshot when it is (PageFor), so every part below checks for its page.
            if (status != null)
            {
                ApplyStatus(status, null);
                var watcher = Map(status, "watcher");
                bool enabled = Equals(Get(status, "enabled"), true);
                shownEnabled = enabled;
                bool upgrade = Equals(Get(status, "upgrade_pending"), true);
                string recovery = enabled ? S("overview.on", "on") : S("overview.off", "paused");
                object running = Get(status, "watcher_running");
                string watcherText = running == null ? S("diag.unknown", "unknown")
                                   : !Equals(running, true) ? S("diag.not_running", "not running")
                                   : Equals(Get(watcher, "ticking"), false) ? S("diag.not_responding", "not responding")
                                   : S("diag.running", "running");
                string engine = Str(watcher, "engine_state") ?? "unknown";
                string engineText = S("engine." + engine, engine);
                double last = Number(watcher, "last_tick_at");
                if (nowRecovery != null)
                {
                    nowRecovery.Text = recovery;
                    nowWatcher.Text = watcherText;
                    nowEngine.Text = engineText;
                    nowLastCheck.Text = Ago(last);
                }
                if (diagVersion != null)
                {
                    diagVersion.Text = "v" + Convert.ToString(Get(status, "version"), CultureInfo.InvariantCulture);
                    diagWatcher.Text = watcherText;
                    diagEngine.Text = engineText;
                    diagLastCheck.Text = Ago(last);
                    diagRecovery.Text = recovery;
                    diagStartup.Text = Equals(Get(status, "startup_enabled"), true) ? S("diag.yes", "yes") : S("diag.no", "no");
                    diagUpgrade.Text = upgrade ? S("diag.upgrade_pending", "An older watcher still owns the state") : "";
                }
            }
            UpdateToggle();

            // A part that could not be read is shown as unreadable, never as empty. "Nothing
            // is waiting" over a list that could not be read is the one wrong answer this page
            // must not give - recoveries may well be waiting, and an older watcher may still
            // be sending them.
            string unreadable = UnreadableReason(status);
            var week = Map(reply, "week");
            if (weekDetected != null)
            {
                if (week != null)
                {
                    var outcomes = Map(week, "outcomes");
                    weekDetected.Text = ((int)Number(week, "interruptions_detected")).ToString(CultureInfo.CurrentCulture);
                    weekSent.Text = ((int)Number(week, "continuations_submitted")).ToString(CultureInfo.CurrentCulture);
                    weekRecovered.Text = ((int)Number(outcomes, "recovered")).ToString(CultureInfo.CurrentCulture);
                    weekSuccess.Text = Rate(week);
                }
                else
                {
                    weekDetected.Text = weekSent.Text = weekRecovered.Text = weekSuccess.Text = "-";
                }
            }
            if (pendingList != null)
            {
                if (Unreadable(reply, "pending")) ShowUnreadableList(pendingList, pendingEmpty, unreadable);
                else
                {
                    FillList(pendingList, Items(reply, "pending"), true);
                    pendingEmpty.Text = S("pending.empty", "Nothing is waiting");
                    pendingEmpty.Visible = pendingList.Items.Count == 0;
                }
            }
            bool historyUnreadable = Unreadable(reply, "history");
            if (historyList != null)
            {
                if (historyUnreadable) ShowUnreadableList(historyList, historyEmpty, unreadable);
                else
                {
                    FillList(historyList, Items(reply, "history"), false);
                    historyEmpty.Text = S("history.empty", "No recoveries yet");
                    historyEmpty.Visible = historyList.Items.Count == 0;
                }
            }
            if (recentGrid != null)
            {
                if (historyUnreadable) ClearRecent(unreadable);
                else FillRecent(Items(reply, "history"));
            }
            // A Retry now note belongs to one record; once that record has left Pending -
            // sent, finished or cancelled - the note no longer describes anything on screen.
            if (pendingNoteFor != null && pendingNoteFor != BulkNote && pendingList != null && !Contains(pendingList, pendingNoteFor))
                pendingNoteFor = null;
            ShowPendingNote();
            ShowExplain();
            UpdateCountdowns();
            UpdatePendingButtons();
            UpdateHistoryButtons();
        }

        /// Whether one part of a snapshot came back as an error rather than as data.
        ///
        /// Each part of the Overview is read on its own and fails on its own, which is the
        /// point: a history query that cannot run should not cost the pending list. The
        /// distinction that matters is between "there is nothing" and "this could not be
        /// read", because the first is an answer and the second is not - and showing the
        /// first when the second is true tells somebody nothing is waiting while recoveries
        /// wait, which is the one wrong thing this page can say.
        internal static bool Unreadable(Dictionary<string, object> reply, string part)
        {
            return reply != null && reply.ContainsKey(part + "_error");
        }

        private static void ShowUnreadable(ListView list, Label empty, string reason)
        {
            list.Items.Clear();
            empty.Text = reason;
            empty.Visible = true;
        }

        /// The same, and the columns fitted again: with no rows there are no cells to keep room for, and the columns
        /// share the list's width by their headings (FitColumns).
        private void ShowUnreadableList(ListView list, Label empty, string reason)
        {
            filled.Remove(list);            // it no longer holds the records the signature describes
            ShowUnreadable(list, empty, reason);
            MeasureCells(list);
            if (list == pendingList) FollowResumeSwitches();
        }

        private void MarkUnavailable()
        {
            // The same unavailable state the header shows when the status cannot be read,
            // and nothing drawn from data that is no longer being read: no countdown, and no
            // list whose rows an action could be taken on. Keeping the last good snapshot on
            // screen said "watching, recovery on" for as long as the reads kept failing.
            snapshot = null;
            shownEnabled = null;
            stateDot.State = "idle";
            TellTaskbar(null, null, 0);
            headline.Text = S("status.unavailable", "Status unavailable");
            detail.Text = S("status.unavailable_detail", "Settings can still be changed and saved");
            header.Invalidate(true);
            // Only the pages built so far have labels; a page built later starts from its own
            // placeholders, which say no more than these do.
            string unknown = S("diag.unknown", "unknown");
            foreach (Label label in new[] { nowRecovery, nowWatcher, nowEngine, nowLastCheck,
                                            diagWatcher, diagEngine, diagLastCheck, diagRecovery })
                if (label != null) label.Text = unknown;
            string unreadable = S("pending.unavailable", "This cannot be read right now");
            if (pendingList != null) ShowUnreadableList(pendingList, pendingEmpty, unreadable);
            if (historyList != null) ShowUnreadableList(historyList, historyEmpty, unreadable);
            if (recentGrid != null) ClearRecent(unreadable);
            if (waitingLine != null)
            {
                waitingLine.Text = unreadable;
                nextLine.Text = "";
                runningLine.Text = "";
            }
            // The week's figures and the Statistics page are read the same way and have
            // failed the same way; left as they were, they would be the last good answer
            // under a header that says the state cannot be read.
            if (weekDetected != null) weekDetected.Text = weekSent.Text = weekRecovered.Text = weekSuccess.Text = "-";
            MarkStatisticsUnavailable();
            pendingNoteFor = null;
            if (pendingNote != null) SetNote(pendingNote, "");
            ShowExplain();
            UpdatePendingButtons();
            UpdateHistoryButtons();
            UpdateToggle();
        }

        /// Why a part of a snapshot says nothing: an older watcher still owns the state, or the
        /// part could not be read.
        private string UnreadableReason(Dictionary<string, object> status)
        {
            return Equals(Get(status, "upgrade_pending"), true)
                 ? S("diag.upgrade_pending", "An older watcher still owns the state")
                 : S("pending.unavailable", "This cannot be read right now");
        }

        private string Rate(Dictionary<string, object> stats)
        {
            object rate = Get(stats, "success_rate");
            if (rate is double)
                return ((int)Math.Round((double)rate * 100)).ToString(CultureInfo.CurrentCulture) + "%";
            return S("overview.not_enough", "not enough data yet");
        }

        private static bool Contains(ListView list, string interruptionId)
        {
            foreach (ListViewItem item in list.Items)
                if (Str(item.Tag as Dictionary<string, object>, "interruption_id") == interruptionId) return true;
            return false;
        }

        // The cells of one row. Null where a cell is written elsewhere: the countdown column
        // is kept by the clock.
        private string[] Cells(Dictionary<string, object> row, bool pending)
        {
            return pending
                ? new[] { Conversation(row), CodeLabel(row), KindLabel(row), null,
                          ((int)Number(row, "recovery_attempts")).ToString(CultureInfo.CurrentCulture), "" }
                : new[] { Conversation(row), CodeLabel(row), KindLabel(row),
                          When(Number(row, "detected_at")), When(Number(row, "outcome_at")) };
        }

        // What a filled list is made of, per list: every row's cells and the three things a row is
        // drawn from besides its text - its state's colour, its overlays and its Auto-resume switch.
        // The snapshot arrives every five seconds whether or not anything moved, and filling used to
        // rewrite every cell, invalidate the list and re-measure every cell of up to 200 rows in both
        // lists, on the window's own thread, for rows that were byte for byte the ones already there.
        private readonly Dictionary<ListView, string> filled = new Dictionary<ListView, string>();

        // How many times a list has actually been filled, and a gate list actually rebuilt. Diagnostic
        // only - nothing reads them but tests/test_gui_v069_idle.py, which is how "an unchanged snapshot
        // costs nothing" is held to being true rather than remembered.
        internal static int ListFills;

        private string ListSignature(List<Dictionary<string, object>> fresh, bool pending)
        {
            var parts = new List<string>();
            foreach (var row in fresh)
            {
                parts.Add(Str(row, "interruption_id") ?? "");
                foreach (string cell in Cells(row, pending)) parts.Add(cell ?? "");
                parts.Add(ToneFor(row).ToArgb().ToString(CultureInfo.InvariantCulture));
                parts.Add(ThreadOn(row) ? "1" : "0");
            }
            return string.Join("\u001f", parts.ToArray());
        }

        private void FillList(ListView list, List<object> rows, bool pending)
        {
            var fresh = new List<Dictionary<string, object>>();
            if (rows != null)
                foreach (object entry in rows)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row != null) fresh.Add(row);
                }

            string signature = ListSignature(fresh, pending);
            string before;
            // A glide is mid-flight: the switch it draws is not in the records, so let the fill run.
            if (filled.TryGetValue(list, out before) && before == signature &&
                list.Items.Count == fresh.Count && resumeGlides.Count == 0)
                return;
            filled[list] = signature;
            ListFills++;

            filling = true;
            try
            {
                // The same records in the same order: only the cells that changed are
                // rewritten, so the scroll position, the focus and the selection stay where
                // the person left them. Rebuilding every five seconds sent a long history back
                // to the top and a keyboard user back to its first row.
                bool same = list.Items.Count == fresh.Count;
                for (int i = 0; same && i < fresh.Count; i++)
                    same = Str(list.Items[i].Tag as Dictionary<string, object>, "interruption_id") ==
                           Str(fresh[i], "interruption_id");
                if (same)
                {
                    for (int i = 0; i < fresh.Count; i++)
                    {
                        ListViewItem item = list.Items[i];
                        item.Tag = fresh[i];
                        string[] cells = Cells(fresh[i], pending);
                        for (int c = 0; c < cells.Length; c++)
                            if (cells[c] != null && item.SubItems[c].Text != cells[c]) item.SubItems[c].Text = cells[c];
                    }
                    // A row is drawn from its record as well as its text - the state chip's
                    // colour, the Auto-resume box - so a record that changed repaints.
                    list.Invalidate();
                }
                else
                {
                    var chosen = Selected(list);
                    string selectedId = chosen == null ? null : Str(chosen, "interruption_id");
                    string focusedId = list.FocusedItem == null ? null
                                     : Str(list.FocusedItem.Tag as Dictionary<string, object>, "interruption_id");
                    string topId = list.TopItem == null ? null
                                 : Str(list.TopItem.Tag as Dictionary<string, object>, "interruption_id");
                    ListViewItem top = null;
                    list.BeginUpdate();
                    list.Items.Clear();
                    foreach (var row in fresh)
                    {
                        string[] cells = Cells(row, pending);
                        var item = new ListViewItem(cells[0]);
                        for (int c = 1; c < cells.Length; c++) item.SubItems.Add(cells[c] ?? "");
                        item.Tag = row;
                        list.Items.Add(item);
                        string id = Str(row, "interruption_id");
                        // Kept only while that record is still here. When the chosen record has
                        // left the list nothing is selected: an action must never move onto a
                        // conversation the person did not choose.
                        if (id != null && id == selectedId) item.Selected = true;
                        if (id != null && id == focusedId) item.Focused = true;
                        if (id != null && id == topId) top = item;
                    }
                    list.EndUpdate();
                    if (top != null)
                    {
                        try { list.TopItem = top; }
                        catch (Exception) { }
                    }
                }
                Preselect(list);
                MeasureCells(list);
                if (list == pendingList) FollowResumeSwitches();
            }
            finally
            {
                filling = false;
            }
        }

        private void Preselect(ListView list)
        {
            // The first time a list has rows its first row starts selected, so the actions
            // under it say what they would do instead of sitting greyed out. Only that once:
            // after that the selection is the person's, including having none. Selecting sends
            // nothing, and every action still asks, naming the conversation it acts on.
            if (preselected.ContainsKey(list) || list.Items.Count == 0) return;
            preselected[list] = true;
            if (list.SelectedItems.Count == 0)
            {
                list.Items[0].Selected = true;
                list.Items[0].Focused = true;
            }
        }

        private void UpdateCountdowns()
        {
            if (snapshot == null) return;
            double now = Now();
            var status = Map(snapshot, "status");
            bool unreadable = snapshot.ContainsKey("pending_error");
            var pending = unreadable ? null : Items(snapshot, "pending");
            // The one place a snapshot decides the header - its light, its word and the facts under it (Hero;
            // ApplyStatus leaves it alone once there is one) - and every second, so a task that has just come due
            // shows the watcher checking. A status read since the snapshot is newer and decides it alone until the
            // next one (ApplyStatus). Before an unreadable list returns, which leaves Hero the status alone.
            if (heroStatus != null) Hero(heroStatus, null, now);
            else Hero(status, pending, now);
            TellTaskbar(status, pending, now);
            if (unreadable)
            {
                if (waitingLine != null)
                {
                    waitingLine.Text = UnreadableReason(status);
                    nextLine.Text = "";
                    runningLine.Text = "";
                }
                return;
            }
            int waiting = 0, running = 0;
            double next = 0;
            if (pending != null)
            {
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row == null) continue;
                    double eligible = Number(row, "eligible_at");
                    if (eligible > 0)
                    {
                        waiting++;
                        if (next == 0 || eligible < next) next = eligible;
                    }
                    else running++;
                }
            }
            bool enabled = Equals(Get(status, "enabled"), true);
            if (waitingLine != null)
            {
                waitingLine.Text = waiting == 0 && running == 0 ? S("overview.none_waiting", "Nothing is waiting to be recovered")
                                 : S("overview.waiting_count", "{n} waiting", "n", waiting);
                nextLine.Text = !(waiting > 0 && enabled && next > 0) ? ""
                    : next <= now ? S("overview.due", "Due to be checked now")
                    : S("overview.next", "Next check in {time}", "time", Countdown(next - now));
                runningLine.Text = running > 0 ? S("overview.running_count", "{n} running in Codex", "n", running) : "";
            }
            // Every second, and only where a person can see it: writing a sub-item is a message to the
            // native list, and a countdown changes every tick, so a hidden Pending page was sending one
            // per waiting row per second for nobody. ShowPage writes them once when it comes back.
            if (pendingList == null || currentPage != "pending") return;
            WriteCountdowns(now);
        }

        /// Each waiting row's Next check, written only where it differs from what the row already shows.
        private void WriteCountdowns(double now)
        {
            if (pendingList == null) return;
            foreach (ListViewItem item in pendingList.Items)
            {
                string text = CountdownText(item.Tag as Dictionary<string, object>, now);
                if (item.SubItems[CountdownColumn].Text != text) item.SubItems[CountdownColumn].Text = text;
            }
        }

        /// What a waiting row's Next check says at `now`: how long until it is checked, that it is due, or nothing for a
        /// row that is not waiting.
        private string CountdownText(Dictionary<string, object> row, double now)
        {
            double eligible = Number(row, "eligible_at");
            return eligible <= 0 ? "" : eligible <= now ? S("pending.due", "due now") : Countdown(eligible - now);
        }

        private static Dictionary<string, object> Selected(ListView list)
        {
            if (list == null || list.SelectedItems.Count == 0) return null;
            return list.SelectedItems[0].Tag as Dictionary<string, object>;
        }

        // The note says what the last Retry now did, and it says it without naming the
        // conversation - so it is shown only while that record is the chosen one. The
        // selection can move between the click and the reply, and a sentence about one
        // conversation read under another is a sentence about the other one.
        private void ShowPendingNote()
        {
            if (pendingNote == null) return;
            var chosen = Selected(pendingList);
            bool mine = pendingNoteFor == BulkNote || (pendingNoteFor != null && chosen != null &&
                        Str(chosen, "interruption_id") == pendingNoteFor);
            SetNote(pendingNote, mine ? pendingNoteText : "");
        }

        /// Whether Retry now is worth offering for this record.
        ///
        /// Lifted out of the button handler so something can drive it: this is a decision
        /// about a record, and a decision that only exists inside a method that reads a
        /// ListView control is a decision nothing can check. It is not the authority - the
        /// engine re-evaluates everything when the request arrives, and refuses there too -
        /// but a button that is certain to be refused is not an action, and one that is
        /// missing where it would have worked is a person concluding the product is stuck.
        internal static bool CanRetryNow(Dictionary<string, object> row, bool idle, double now)
        {
            if (row == null || !idle) return false;
            string code = Str(row, "code");
            bool waiting = code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" ||
                           code == "scheduled" || code == "failed_retryable";
            if (!waiting) return false;
            if (Equals(Get(row, "cancel_requested"), true)) return false;
            // Retry now brings the check forward. It never moves past a usage reset that is
            // still ahead, and never past a pause or a conversation that is switched off; where
            // it could do none of that it is not offered. A reset that has passed, or one that
            // is unknown, is exactly where it helps.
            if (Number(row, "reset_at") > now) return false;
            if (HasOverlay(row, "paused") || HasOverlay(row, "thread_disabled")) return false;
            return true;
        }

        /// Whether giving this record its attempts back could succeed. The store allows it a
        /// limited number of times; past that the button would always be refused.
        internal static bool CanGiveAttemptsBack(Dictionary<string, object> row, bool idle)
        {
            if (row == null || !idle) return false;
            if (Str(row, "code") != "exhausted") return false;
            if (Equals(Get(row, "cancel_requested"), true)) return false;
            return Number(row, "budget_resets_left") > 0;
        }

        private void UpdatePendingButtons()
        {
            if (pendingList == null) return;
            var row = Selected(pendingList);
            bool idle = busy == 0;
            bool cancelled = Equals(Get(row, "cancel_requested"), true);
            retryButton.Enabled = CanRetryNow(row, idle, Now());
            cancelButton.Enabled = idle && row != null && !cancelled;
            timelineButton.Enabled = idle && row != null;
            threadButton.Enabled = idle && row != null;
            string text = ThreadOn(row) ? S("action.thread_off", "Turn off for this conversation")
                                        : S("action.thread_on", "Turn on for this conversation");
            if (threadButton.Text != text) threadButton.Text = text;
            if (cancelAllButton != null) cancelAllButton.Enabled = idle && pendingList.Items.Count > 0;
        }

        private void UpdateHistoryButtons()
        {
            if (historyList == null) return;
            var row = Selected(historyList);
            bool idle = busy == 0;
            historyTimeline.Enabled = idle && row != null;
            bool exhausted = Str(row, "code") == "exhausted" && !Equals(Get(row, "cancel_requested"), true);
            bool resetsLeft = Number(row, "budget_resets_left") > 0;
            historyReset.Enabled = CanGiveAttemptsBack(row, idle);
            SetNote(historyNote, exhausted && !resetsLeft
                ? S("history.reset_limit", "Its attempts were already given back as many times as allowed; continue this task in Codex yourself.")
                : "");
            bool off = row != null && !ThreadOn(row);
            // Set every time. While History is not the page on screen `Visible` answers false
            // whatever the button was told, and a write skipped for that left it offered beside a
            // row whose conversation is on.
            historyThread.Visible = off;
            historyThread.Enabled = idle && off;
            historyClear.Enabled = idle && historyList.Items.Count > 0;
        }

        private void UpdateToggle()
        {
            if (toggleButton == null) return;
            toggleButton.Enabled = busy == 0;
            string text = shownEnabled == false ? S("action.resume", "Resume recovery") : S("action.pause", "Pause recovery");
            if (toggleButton.Text != text) toggleButton.Text = text;
        }

        // ---------------------------------------------------------------- actions
        private void SetBusy(bool on)
        {
            busy = Math.Max(0, busy + (on ? 1 : -1));
            // While an action is in flight every other action waits its turn, visibly. A second
            // click on a button whose first click has not been answered yet is how a person
            // ends up acting twice, or on the row that happened to be selected by then.
            UseWaitCursor = busy > 0;
            UpdatePendingButtons();
            UpdateHistoryButtons();
            UpdateToggle();
            if (exportButton != null) exportButton.Enabled = busy == 0;
            if (repairButton != null) repairButton.Enabled = busy == 0;
            if (updateButton != null) updateButton.Enabled = busy == 0;
            if (stopButton != null) stopButton.Enabled = busy == 0;
            if (compatButton != null) compatButton.Enabled = busy == 0;
            if (saveButton != null) saveButton.Enabled = busy == 0;
            if (restoreButton != null) restoreButton.Enabled = busy == 0;
        }

        /// Runs one bridge command on a worker and hands its reply back on this thread.
        /// Confirmation and file dialogs stay on this thread, before the call starts.
        private void CallAsync(string command, string argument, Action<Dictionary<string, object>> done)
        {
            SetBusy(true);
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call(command, argument); }
                catch (Exception error) { reply = Failure(error); }
                MethodInvoker finish = delegate
                {
                    SetBusy(false);
                    done(reply);
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        private void Send(string command, string argument)
        {
            CallAsync(command, argument, delegate(Dictionary<string, object> reply)
            {
                Report(reply);
                RefreshAfterChange();
            });
        }

        private bool Confirm(string question, string affirm)
        {
            return question == null || Say(question, affirm);
        }

        /// A notice: one sentence and one button that closes it.
        private void Tell(string text)
        {
            Say(text, null);
        }
    }
}

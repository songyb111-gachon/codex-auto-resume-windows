// Codex Auto Resume - what a button on the Dashboard does, and what the taskbar is told.
//
// Retry now, cancel, give attempts back, follow the thread, pause; the failure the window
// acknowledges; the statistics it loads and the timeline a row opens.

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
        // ---------------------------------------------------------------- the window's own message box
        /// What Windows' message box was, in the material the rest of this window is made of.
        ///
        /// It was the last native piece here. Windows' box is a square grey sheet with a system font and
        /// a title bar that ignores the theme - in dark it is a white card in the middle of a dark window
        /// - and its buttons say "Yes" and "No", which name nothing. This one says what will happen: the
        /// words of the button that was pressed to ask. The panel settled that pattern first (confirmOff:
        /// the action's own label beside `action.cancel`), so both halves of the product ask the same way.
        ///
        /// No new words were needed for it. A notice closes with `action.close`; a question affirms with
        /// the label its caller already has and dismisses with `action.cancel` - or with `action.close`
        /// where those two would be the same word, as they are for the Pending page's own Cancel.
        private bool Say(string text, string affirm)
        {
            using (var dialog = new Form())
            {
                dialog.Text = "Codex Auto Resume";
                dialog.Font = Font;
                dialog.BackColor = Canvas;
                dialog.ForeColor = Ink;
                // In the window's theme, title bar and all.
                Soft.TitleBar(dialog);
                dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
                dialog.StartPosition = FormStartPosition.CenterParent;
                dialog.MinimizeBox = false;
                dialog.MaximizeBox = false;
                dialog.ShowInTaskbar = false;
                dialog.ShowIcon = false;

                // A measure a sentence is read at, not a box stretched to whatever it holds: the words
                // wrap inside it, and a short one still gets a dialog wide enough to look deliberate.
                int pad = Px(16);
                Size measured = TextRenderer.MeasureText(text ?? "", Font, new Size(Px(420), 0),
                                                         TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix);
                int width = Math.Max(Px(300), measured.Width);
                // And a height a dialog can be. A refusal carries the local service's own sentence
                // under the translated one, and that sentence is whatever was raised - a path, a stack,
                // a page of it. Past this the words go in a well and scroll there, on the window's own
                // bar, rather than making a dialog taller than the screen it opens on.
                int tallest = Px(240);
                bool scrolls = measured.Height > tallest;
                int room = scrolls ? tallest : measured.Height;

                var padding = new Panel();
                padding.BackColor = Canvas;
                padding.Dock = DockStyle.Fill;
                padding.Padding = Pad(16, 16, 16, 0);
                if (scrolls)
                {
                    var well = new SoftTextArea();
                    well.Dock = DockStyle.Fill;
                    well.Font = Font;
                    well.Box.Font = Font;
                    well.Box.ReadOnly = true;
                    well.Box.Text = text ?? "";
                    // Read from the top, unselected. A text box takes the focus a dialog hands its first
                    // control and answers it by selecting everything it holds, which reads as a page of
                    // highlighted text nobody asked to highlight - and leaves the well wearing the focus
                    // ring while the button that closes it has none.
                    dialog.Shown += delegate { well.Box.Select(0, 0); };
                    well.Box.AccessibleName = "Codex Auto Resume";
                    padding.Controls.Add(well);
                }
                else
                {
                    var words = new Label();
                    words.Text = text ?? "";
                    words.ForeColor = Ink;
                    words.BackColor = Canvas;
                    words.UseMnemonic = false;     // an ampersand in a conversation's name is a letter
                    words.AutoSize = false;
                    words.Dock = DockStyle.Fill;
                    padding.Controls.Add(words);
                }
                dialog.Controls.Add(padding);

                bool said = false;
                FlowLayoutPanel buttons = ButtonRow();
                buttons.FlowDirection = FlowDirection.RightToLeft;
                // A right-to-left flow lays its first control out from its own width less both sides
                // of its padding, so what stands between the rightmost button and the edge is the two
                // added together. All of it is put on the right, where it is the gap, and the row is
                // then inset by the same 16 as the sentence above it.
                buttons.Padding = Pad(0, 12, 16, 16);
                Button accept, dismiss;
                if (affirm == null)
                {
                    accept = dismiss = MakeButton(S("action.close", "Close"), true, delegate { dialog.Close(); });
                    buttons.Controls.Add(accept);
                }
                else
                {
                    accept = MakeButton(affirm, true, delegate { said = true; dialog.Close(); });
                    string away = S("action.cancel", "Cancel");
                    if (string.Equals(away, affirm, StringComparison.CurrentCultureIgnoreCase))
                        away = S("action.close", "Close");
                    dismiss = MakeButton(away, false, delegate { dialog.Close(); });
                    // Right to left, so the button that does the thing is the rightmost.
                    buttons.Controls.Add(accept);
                    buttons.Controls.Add(dismiss);
                }
                dialog.Controls.Add(buttons);
                dialog.AcceptButton = accept;
                dialog.CancelButton = dismiss;     // which is also what Escape presses
                // The keyboard starts on the button that acts, not on the words: a dialog hands the
                // focus to its first control, and where the words are in a well that is the well.
                dialog.ActiveControl = accept;

                dialog.ClientSize = new Size(width + 2 * pad, room + pad + buttons.PreferredSize.Height);
                dialog.ShowDialog(this);
                return said;
            }
        }

        // A confirmation that names the conversation it acts on. The row is the one read at
        // the click, and so is the id the action is sent with: what the person agrees to and
        // what is done are the same record, whatever a refresh does to the list meanwhile.
        private string Named(string key, string fallback, Dictionary<string, object> row)
        {
            return S(key, fallback, "name", Conversation(row));
        }

        private void Report(Dictionary<string, object> reply)
        {
            if (Ok(reply)) return;
            // Every refusal carries a code from a closed set, and the catalog has that code's
            // sentence in the language this window is speaking. The English sentence beside it
            // comes from the local service and stays underneath, because it is what a bug
            // report needs - except where it would only repeat the line above it.
            string code = Str(reply, "error_code");
            string english = Convert.ToString(Get(reply, "error"), CultureInfo.InvariantCulture);
            // The generic code is the exception: it is what a refusal carries when the
            // sentence beside it is the informative half - a setting naming the bounds it
            // refused, say - so translating it would replace the only useful words with
            // "the request could not be completed".
            string said = string.IsNullOrEmpty(code) || code == "request_failed"
                        ? null : S("error." + code, null);
            string lead = said ?? S("action.failed", "That could not be done.");
            Tell(lead + (said != null || string.IsNullOrEmpty(english)
                         ? "" : Environment.NewLine + Environment.NewLine + english));
        }

        private static Dictionary<string, object> Failure(Exception error)
        {
            var reply = new Dictionary<string, object>();
            reply["ok"] = false;
            reply["error"] = error.Message;
            return reply;
        }

        private static string IdArgument(Dictionary<string, object> row)
        {
            return "{\"interruption_id\":" + Json.Escape(Str(row, "interruption_id")) + "}";
        }

        private void RetryNow()
        {
            var row = Selected(pendingList);
            if (row == null) return;
            string key = Str(row, "interruption_id");
            CallAsync("retry-now", IdArgument(row), delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    RefreshAfterChange();
                    return;
                }
                var result = Map(reply, "result");
                pendingNoteFor = key;
                pendingNoteText = Number(result, "eligible_at") > Now() + 1
                    ? S("retry.later", "The usage reset is later; the watcher checks then.")
                    : Equals(Get(result, "woke"), true)
                    ? S("retry.checking", "Checking now. Every safety check still applies.")
                    : S("retry.next_poll", "The watcher checks at its next poll. Every safety check still applies.");
                ShowPendingNote();
                RefreshAfterChange();
            });
        }

        private void CancelSelected()
        {
            var row = Selected(pendingList);
            if (row == null) return;
            if (!Confirm(Named("confirm.cancel",
                               "Stop recovering \"{name}\"? A continuation already running in Codex is not stopped.", row),
                         S("action.cancel", "Cancel")))
                return;
            Send("cancel", IdArgument(row));
        }

        private void ResetSelected()
        {
            var row = Selected(historyList);
            if (row == null) return;
            if (!Confirm(Named("confirm.reset",
                               "Give \"{name}\" its attempts back? It waits and is checked again; nothing is sent now.", row),
                         S("action.reset_budget", "Give attempts back")))
                return;
            CallAsync("reset-budget", IdArgument(row), delegate(Dictionary<string, object> reply)
            {
                Report(reply);
                string notice = BudgetResetNotice(reply,
                    S("history.reset_done", "Attempts restored. Nothing was sent."),
                    S("history.reset_thread_off", "Automatic recovery is off for this conversation; switch it on before recovery can run."));
                if (notice != null)
                    Tell(notice);
                RefreshAfterChange();
            });
        }

        internal static string BudgetResetNotice(Dictionary<string, object> reply, string restored, string threadOff)
        {
            if (!Ok(reply)) return null;
            var result = Map(reply, "result");
            if (result == null) return null;
            return restored + (string.IsNullOrEmpty(Str(result, "note")) ? ""
                              : Environment.NewLine + Environment.NewLine + threadOff);
        }

        private void ToggleThread(ListView list)
        {
            var row = Selected(list);
            if (row == null) return;
            bool on = ThreadOn(row);
            if (!Confirm(on ? Named("confirm.thread_off",
                                    "Turn automatic recovery off for \"{name}\"? Its waiting recoveries are cancelled.", row)
                            : Named("confirm.thread_on",
                                    "Turn automatic recovery back on for \"{name}\"? Nothing is sent now; every check still applies.", row),
                         on ? S("action.thread_off", "Turn off for this conversation")
                            : S("action.thread_on", "Turn on for this conversation")))
                return;
            string thread = Json.Escape(Str(row, "thread_id"));
            if (on) Send("cancel-thread", "{\"thread_id\":" + thread + "}");
            else Send("thread-enabled", "{\"thread_id\":" + thread + ",\"enabled\":true}");
        }

        /// The Auto-resume box on one row: automatic recovery on or off for that exact task.
        private void ToggleAutoResume(Dictionary<string, object> row)
        {
            if (row == null || busy > 0) return;
            string id = Str(row, "interruption_id"), thread = Str(row, "thread_id");
            if (id == null || thread == null) return;
            bool enable = !ThreadOn(row);
            // Off only ever reduces what runs, so it happens at once. On asks first, naming the
            // conversation, exactly as the button beside the list does.
            if (enable && !Confirm(Named("confirm.thread_on",
                                         "Turn automatic recovery back on for \"{name}\"? Nothing is sent now; every check still applies.", row),
                                   S("action.thread_on", "Turn on for this conversation")))
                return;
            Send("interruption-recovery", "{\"interruption_id\":" + Json.Escape(id) + ",\"thread_id\":" +
                 Json.Escape(thread) + ",\"enabled\":" + (enable ? "true" : "false") + "}");
        }

        private void CancelAll()
        {
            if (busy > 0 || pendingList.Items.Count == 0) return;
            if (!Confirm(S("confirm.cancel_all",
                           "Stop every pending recovery? Anything already handed to Codex is withdrawn only if it is still queued."),
                         S("action.cancel_all", "Cancel all")))
                return;
            CallAsync("cancel-all", null, delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply))
                {
                    Report(reply);
                    RefreshAfterChange();
                    return;
                }
                var result = Map(reply, "result");
                pendingNoteFor = BulkNote;
                pendingNoteText = S("result.cancel_all", "Cancelled: {n}", "n", (int)Number(result, "cancelled"));
                ShowPendingNote();
                RefreshAfterChange();
            });
        }

        /// What the watcher is doing, as the header's status light shows it: the light of the header's word
        /// (ActivityWord), and a light that is off - grey, as it was until v0.6.3 - for a watcher that is not
        /// running or not known to be, beside the word that asks for attention (HeaderLight).
        ///
        /// Pure, so the rule can be checked without a window.
        internal static string Activity(Dictionary<string, object> status, List<object> pending, double now)
        {
            return HeaderLight(status, pending, ActivityWord(status, pending, now));
        }

        /// The header's word, activity.<word> in the catalog, for what the window read (v0.6.10).
        ///
        /// The rule every header keeps - the popup's (ui/popup/model.activity) and the Codex panel's (panel.js
        /// activity) too - and tests/data/light_states.json holds all three to it: until v0.6.10 three hand-written
        /// copies told one moment three ways. A watcher that is not running, or not known to be, asks for
        /// attention; so does one that runs but is not well (AttentionCause); then a pause; then a continuation
        /// sent into Codex, or being followed or taken back out of it; then a task that has come due, which this
        /// window, redrawn every second, is checking; then anything else waiting; and a running watcher with
        /// nothing to do is monitoring. With no pending list - it could not be read - the status's own counts say
        /// what it would have, so a list that cannot be read is never shown as nothing to do.
        internal static string ActivityWord(Dictionary<string, object> status, List<object> pending, double now)
        {
            if (status == null || !Equals(Get(status, "watcher_running"), true)) return "attention";
            if (AttentionCause(status, pending) != null) return "attention";
            if (!Equals(Get(status, "enabled"), true)) return "paused";
            bool waiting = Number(status, "pending") > 0, due = false, recovering = false;
            var codes = Map(status, "codes");
            if (codes != null)
                foreach (KeyValuePair<string, object> code in codes)
                    if (Moving(code.Key) && code.Value is double && (double)code.Value > 0) recovering = true;
            if (pending != null)
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row == null) continue;
                    waiting = true;
                    if (Moving(Str(row, "code")))
                    {
                        recovering = true;
                        continue;
                    }
                    object eligible = Get(row, "eligible_at");
                    if (eligible is double && (double)eligible <= now) due = true;
                }
            if (recovering) return "recovering";
            if (due) return "checking";
            return waiting ? "waiting" : "monitoring";
        }

        /// The status light for a header's word: the word's own, except that a watcher not known to be running is a
        /// light that is off, grey and still, whatever the word beside it asks (tray_popup.light_for, panel.js
        /// lightFor). A light that moves says the product is running; amber is for a watcher that runs and is not well.
        /// A row held for a watcher not running (engine_unavailable) outweighs a status that says it runs, the two
        /// read a moment apart, so the dot is not a moving light beside "Watcher not running" (HeroFacts).
        internal static string HeaderLight(Dictionary<string, object> status, List<object> pending, string word)
        {
            if (!Equals(Get(status, "watcher_running"), true)) return "idle";
            if (pending != null)
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row != null && HasOverlay(row, "engine_unavailable")) return "idle";
                }
            return word;
        }

        /// Why a watcher that runs needs a person, or null when it does not: an older watcher still owns the state, it
        /// has stopped ticking, the engine is not supported or failed its checks here - or a row is held for one of
        /// those (tray_popup.ATTENTION_OVERLAYS), which the list, read a moment after the status, can know first. In
        /// this order, and the rows in theirs, as panel.js attentionCause.
        internal static string AttentionCause(Dictionary<string, object> status, List<object> pending)
        {
            var watcher = Map(status, "watcher");
            if (Equals(Get(status, "upgrade_pending"), true)) return "upgrade_pending";
            if (Equals(Get(watcher, "ticking"), false)) return "watcher_not_ticking";
            string engine = Str(watcher, "engine_state");
            if (engine == "incompatible") return "compatibility_blocked";
            if (engine == "failed_here") return "compatibility_failed_here";
            if (pending != null)
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row == null) continue;
                    foreach (string held in HeldFor)
                        if (HasOverlay(row, held)) return held;
                }
            return null;
        }

        /// The overlays that hold a record for something only a person can put right, in the order AttentionCause
        /// names them (tray_popup.ATTENTION_OVERLAYS).
        private static readonly string[] HeldFor =
            { "compatibility_blocked", "compatibility_failed_here", "engine_unavailable", "watcher_not_ticking" };

        /// A public code of a record already handed to Codex, or being followed or taken back out of it
        /// (tray_popup.MOVING_CODES): every pending record that is not waiting.
        private static bool Moving(string code)
        {
            return code == "submission_claimed" || code == "submitted" || code == "withdrawing" || code == "turn_running" ||
                   code == "turn_finishing";
        }

        /// The facts under the header's word, most consequential first: whether anything can be recovered, and what
        /// is waiting on it - the Codex panel's (panel.js heroFacts), in `strings`, the catalog the window was served,
        /// and held to them by tests/test_light_parity.py. The panel adds the soonest check as a clock time; this
        /// window counts it down on the Dashboard instead.
        internal static List<string> HeroFacts(Dictionary<string, object> strings, Dictionary<string, object> status,
                                               List<object> pending, string word)
        {
            int count = (int)Number(status, "pending");
            string waiting = count == 0 ? Said(strings, "status.pending_none", "Nothing pending")
                           : count == 1 ? Said(strings, "status.pending_one", "1 recovery pending")
                           : Said(strings, "status.pending_many", "{n} recoveries pending")
                                 .Replace("{n}", count.ToString(CultureInfo.InvariantCulture));
            var facts = new List<string>();
            object running = Get(status, "watcher_running");
            if (!Equals(running, true))
            {
                facts.Add(Equals(running, false) ? Said(strings, "status.not_running", "Watcher not running")
                                                 : Said(strings, "status.unknown", "Watcher status unknown"));
                facts.Add(Said(strings, "status.recovery_idle", "Nothing will be recovered until it is running"));
                if (count != 0) facts.Add(waiting);
                return facts;
            }
            if (word == "attention")
            {
                // A watcher that runs and is not well: what is wrong, not "recovery is on".
                string cause = AttentionCause(status, pending);
                facts.Add(cause == "upgrade_pending"
                              ? Said(strings, "diag.upgrade_pending",
                                     "An older watcher still owns the state; finish by restarting the watcher")
                          : cause == "compatibility_blocked"
                              ? Said(strings, "overlay.compatibility_blocked", "Codex version not supported")
                          : cause == "compatibility_failed_here"
                              ? Said(strings, "overlay.compatibility_failed_here", "Codex checks failed on this computer")
                          : cause == "engine_unavailable" ? Said(strings, "status.not_running", "Watcher not running")
                          : Said(strings, "status.not_responding", "Watcher not responding"));
                facts.Add(waiting);
                return facts;
            }
            facts.Add(word == "paused" ? Said(strings, "status.recovery_paused", "Automatic recovery is paused")
                                       : Said(strings, "status.recovery_on", "Automatic recovery is on"));
            facts.Add(waiting);
            return facts;
        }

        /// A word from `strings`, as S says it, for the pure functions that are handed the catalog.
        private static string Said(Dictionary<string, object> strings, string key, string fallback)
        {
            object value;
            if (strings != null && strings.TryGetValue(key, out value) && value is string && ((string)value).Length > 0)
                return (string)value;
            return fallback;
        }

        /// What the notification-area icon shows for the watcher the window read, as the status-light word its state
        /// is made from (v0.6.5): the taskbar button's, which TaskbarMark maps as the icon does (Brand.Mark.IconState,
        /// tray.ICON_FOR_LIGHT).
        ///
        /// The icon's own rule, not the header light's (Activity), and kept apart from the one rule the headers share
        /// (tests/data/light_states.json, v0.6.10) on purpose: a failure nobody has seen is red here and in no header
        /// (standard J14), and a list that was read decides here without the status's counts. tray.icon_state is ICON_FOR_LIGHT of
        /// tray_popup.snapshot_activity: the tick's snapshot of the store (tray.snapshot_from) - a pause, then any
        /// record sent or being followed, then any waiting - with, while its popup is open, the popup's word that a
        /// person must act (tray_popup.icon_attention, the icon's own rule and not the header's word). The window
        /// reads what that popup reads, get_status and list_pending, and reads it now, so this is the icon with its
        /// popup open. With no list the status's counts of the store's
        /// records by public code say the same (status.codes). Where no icon of this version can be showing, it is the
        /// header light's word: grey with no watcher running or none known to be, and needing a person while an older
        /// watcher still owns the state. Pure, so tests/test_gui_v065_taskbar.py holds it to tray.py's own code.
        internal static string TrayActivity(Dictionary<string, object> status, List<object> pending, double now)
        {
            if (status == null || !Equals(Get(status, "watcher_running"), true)) return "idle";
            // v0.6.8: a certain failure nobody has seen yet is red on the icon (tray.icon_state), and so it is here.
            if (Equals(Get(status, "failure_unseen"), true)) return "failed";
            if (Equals(Get(status, "upgrade_pending"), true)) return "attention";
            var watcher = Map(status, "watcher");
            if (Equals(Get(watcher, "ticking"), false) || Str(watcher, "engine_state") == "incompatible" ||
                Str(watcher, "engine_state") == "failed_here")
                return "attention";
            if (pending != null)
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    // tray_popup.ATTENTION_OVERLAYS: a record held for one of the above, or for a watcher not running.
                    if (row != null && (HasOverlay(row, "compatibility_blocked") || HasOverlay(row, "compatibility_failed_here") ||
                                        HasOverlay(row, "engine_unavailable") ||
                                        HasOverlay(row, "watcher_not_ticking")))
                        return "attention";
                }
            object enabled;
            if (status.TryGetValue("enabled", out enabled) && (enabled == null || Equals(enabled, false))) return "paused";
            bool waiting = false, due = false, running = false;
            if (pending != null)
                foreach (object entry in pending)
                {
                    var row = entry as Dictionary<string, object>;
                    if (row == null) continue;
                    if (!WaitingCode(Str(row, "code")))
                    {
                        running = true;
                        continue;
                    }
                    waiting = true;
                    double eligible = Number(row, "eligible_at");
                    if (eligible > 0 && eligible <= now) due = true;
                }
            else
            {
                var codes = Map(status, "codes");
                if (codes != null)
                    foreach (KeyValuePair<string, object> code in codes)
                    {
                        if (!(code.Value is double) || (double)code.Value <= 0) continue;
                        if (WaitingCode(code.Key)) waiting = true;
                        else running = true;
                    }
            }
            if (running) return "recovering";
            if (due) return "checking";
            return waiting ? "waiting" : "monitoring";
        }

        /// A pending record's public code that means it waits (machine.WAITING_CODES): every other pending record has
        /// been sent into Codex, or is being followed or taken back out of it.
        private static bool WaitingCode(string code)
        {
            return code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" || code == "scheduled" ||
                   code == "failed_retryable";
        }

        /// The taskbar button told what the window read (TrayActivity), wherever the header light is told. A failure is
        /// seen the moment this window is in front (v0.6.8): it is acknowledged, not shown red to somebody already
        /// looking at the Dashboard, and the clock asks again every second, so bringing the window forward is enough.
        private void TellTaskbar(Dictionary<string, object> status, List<object> pending, double now)
        {
            if (status != null && Equals(Get(status, "failure_unseen"), true) && !auditing && ActiveForm == this)
            {
                AcknowledgeFailure();
                status = new Dictionary<string, object>(status);
                status["failure_unseen"] = false;
            }
            if (taskbar != null) taskbar.Follow(TrayActivity(status, pending, now));
        }

        private bool acknowledging, acknowledged, readingFailure;
        private int acknowledgedAt;
        // However an acknowledgement went, the next is at least this far behind it: a write Windows refuses, or a
        // failure the file cannot yet cover, is asked about again, never in a loop.
        private const int AcknowledgeEveryMs = 10000;

        /// Tells the watcher's side the failure was seen (control.acknowledge_failure), one call at a time and at most
        /// every AcknowledgeEveryMs, and then reads again, so the next snapshot no longer says it.
        private void AcknowledgeFailure()
        {
            if (acknowledging || (acknowledged && unchecked(Environment.TickCount - acknowledgedAt) < AcknowledgeEveryMs))
                return;
            acknowledging = true;
            acknowledged = true;
            acknowledgedAt = Environment.TickCount;
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                try { bridge.Call("failure-seen", null); }
                catch (Exception) { }
                MethodInvoker done = delegate
                {
                    acknowledging = false;
                    if (currentPage == "settings" || snapshot == null) RefreshFailure();
                    else RefreshAfterChange();
                };
                try
                {
                    if (IsHandleCreated && !IsDisposed) BeginInvoke(done);
                    else acknowledging = false;
                }
                catch (Exception) { acknowledging = false; }
            });
        }

        /// Whether a failure is unseen, from the status alone: where the clock reads no snapshot (the Settings page) or
        /// has none yet. Only that one answer is taken - into the snapshot the clock tells the button from, or to the
        /// button directly - so nothing on the page, and no edit on it, is touched.
        private void RefreshFailure()
        {
            if (readingFailure || auditing) return;
            readingFailure = true;
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply = null;
                try { reply = bridge.Call("status", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    readingFailure = false;
                    var status = Ok(reply) ? reply["status"] as Dictionary<string, object> : null;
                    if (status == null) return;
                    var held = snapshot != null ? Map(snapshot, "status") : null;
                    if (held != null) held["failure_unseen"] = Equals(Get(status, "failure_unseen"), true);
                    else TellTaskbar(status, null, Now());
                };
                try
                {
                    if (IsHandleCreated && !IsDisposed) BeginInvoke(apply);
                    else readingFailure = false;
                }
                catch (Exception) { readingFailure = false; }
            });
        }

        /// The selected task's safety checks, as the watcher last recorded them.
        private void ShowExplain()
        {
            if (explainList == null) return;
            var row = Selected(pendingList);
            var rows = new List<string[]>();
            if (row == null)
            {
                explainAsOf.Text = "";
                explainList.SetRows(rows, S("explain.none_selected", "Select a task to see why it is waiting."));
                return;
            }
            var gates = Map(row, "gates");
            double at = Number(row, "gates_at");
            // Said once: either when the checks were last run, or - in the list's own place -
            // that they have not been run yet.
            explainAsOf.Text = gates == null || at <= 0 ? "" : S("explain.as_of", "Last checked {time}", "time", Ago(at));
            if (gates != null)
                foreach (string name in GateOrder)
                {
                    var result = Items(gates, name);
                    string code = result != null && result.Count > 0 ? Convert.ToString(result[0], CultureInfo.InvariantCulture) : "UNKNOWN";
                    string word = code == "PASS" ? S("gate.result.pass", "OK")
                                : code == "WAIT" ? S("gate.result.wait", "Waiting")
                                : code == "BLOCK" ? S("gate.result.block", "Blocked")
                                : S("gate.result.unknown", "Unknown");
                    rows.Add(new[] { S("gate." + name, name.Replace('_', ' ')), word, code });
                }
            explainList.SetRows(rows, S("explain.not_checked", "Not checked yet"));
        }

        private void TogglePause()
        {
            if (shownEnabled.HasValue)
            {
                SetEnabled(!shownEnabled.Value);
                return;
            }
            // No status has been read yet, or the last read failed, and the button then
            // shows "Pause recovery" only because it has to show something. So the state is
            // read first rather than guessed: pressing "Pause recovery" must never turn
            // recovery on, and if it is already paused there is nothing to do.
            CallAsync("status", null, delegate(Dictionary<string, object> reply)
            {
                var status = Ok(reply) ? Map(reply, "status") : null;
                if (status == null)
                {
                    Tell(S("status.unavailable", "Status unavailable"));
                    return;
                }
                bool enabled = Equals(Get(status, "enabled"), true);
                shownEnabled = enabled;
                UpdateToggle();
                if (enabled) SetEnabled(false);
            });
        }

        private void SetEnabled(bool enable)
        {
            // Pausing never asks: it only reduces what happens. Turning recovery back on does.
            if (enable && !Confirm(S("confirm.resume", "Turn automatic recovery back on?"),
                                   S("action.resume", "Resume recovery"))) return;
            Send("enabled", enable ? "{\"enabled\":true}" : "{\"enabled\":false}");
        }

        private void ClearHistory()
        {
            if (!Confirm(S("confirm.clear", "Hide finished recoveries from the history?"),
                         S("action.clear_history", "Clear history"))) return;
            Send("clear-history", null);
        }

        // A statistics read for its own sake: the clock, a page switch, F5.
        private void LoadStatistics()
        {
            LoadStatistics(false);
        }

        // A read after the period changed. An answer already in flight is for the period
        // before it, so it is thrown away and a new read made.
        private void LoadStatistics(bool afterChange)
        {
            // One read at a time. Without this the clock queues another every five
            // seconds whether or not the last one has answered, and a bridge that is
            // slow - every call a fresh interpreter once the long-lived one is given up -
            // leaves a growing pile of them waiting on its lock.
            if (period == null) return;
            if (loadingStats)
            {
                if (afterChange) { statsAgain = true; statsToken++; }
                return;
            }
            loadingStats = true;
            statsAgain = false;
            var choice = period.SelectedItem as Choice;
            string argument = choice == null || choice.Value.Length == 0 ? "{}" : "{\"days\":" + choice.Value + "}";
            int mine = ++statsToken;
            // Not through CallAsync: reading numbers is not an action, and must not grey out
            // every button of the window each time the page refreshes.
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call("statistics", argument); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    loadingStats = false;
                    if (statsAgain)
                    {
                        statsAgain = false;
                        LoadStatistics(false);
                        return;
                    }
                    if (mine != statsToken) return;
                    if (Ok(reply)) ApplyStatistics(Map(reply, "result"));
                    else MarkStatisticsUnavailable();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { loadingStats = false; statsAgain = false; }
            });
        }

        private void MarkStatisticsUnavailable()
        {
            // The same rule as the Overview: a number that could not be read is shown as
            // unknown, never as the answer to a different question - the period before
            // this one, or a week whose figures are no longer being read.
            if (chart == null) return;
            foreach (Label label in new[] { statsDetected, statsSent, statsRecovered, statsSuccess,
                                            statsWait, statsRecover, statsRetry, statsKinds })
                label.Text = "-";
            chart.Bars.Clear();
            chart.EmptyText = S("pending.unavailable", "This cannot be read right now");
            chart.Font = Font;
            chart.Height = chart.RowHeight() + Px(4);
            chart.Describe();
            chart.Invalidate();
        }

        private void ApplyStatistics(Dictionary<string, object> stats)
        {
            var outcomes = Map(stats, "outcomes");
            statsDetected.Text = ((int)Number(stats, "interruptions_detected")).ToString(CultureInfo.CurrentCulture);
            statsSent.Text = ((int)Number(stats, "continuations_submitted")).ToString(CultureInfo.CurrentCulture);
            statsRecovered.Text = ((int)Number(outcomes, "recovered")).ToString(CultureInfo.CurrentCulture);
            statsSuccess.Text = Rate(stats);
            object wait = Get(stats, "median_wait_seconds");
            object recover = Get(stats, "median_recovery_seconds");
            statsWait.Text = wait is double ? Duration((double)wait) : "-";
            statsRecover.Text = recover is double ? Duration((double)recover) : "-";
            statsRetry.Text = ((int)Number(stats, "retry_now_requests")).ToString(CultureInfo.CurrentCulture);
            var kinds = Map(stats, "by_category");
            var parts = new List<string>();
            if (kinds != null)
                foreach (var pair in kinds)
                    parts.Add(S("field.recover_" + pair.Key, pair.Key) + " " +
                              Whole(pair.Value).ToString(CultureInfo.CurrentCulture));
            // One kind per line: a wrapped list breaks Korean inside a word.
            statsKinds.Text = parts.Count == 0 ? "-" : string.Join(Environment.NewLine, parts.ToArray());
            chart.Bars.Clear();
            if (outcomes != null)
                foreach (var pair in outcomes)
                {
                    int count = Whole(pair.Value);
                    if (count > 0) chart.Bars.Add(new KeyValuePair<string, int>(S("code." + pair.Key, pair.Key), count));
                }
            // Most common first, and as tall as its bars rather than a fixed box.
            chart.Bars.Sort(delegate(KeyValuePair<string, int> a, KeyValuePair<string, int> b)
            {
                int order = b.Value.CompareTo(a.Value);
                return order != 0 ? order : string.CompareOrdinal(a.Key, b.Key);
            });
            chart.EmptyText = S("stats.none", "Nothing yet");
            chart.Font = Font;
            chart.Height = Math.Max(1, chart.Bars.Count) * chart.RowHeight() + Px(4);
            chart.Describe();
            chart.Invalidate();
        }

        private void ShowTimeline(ListView list)
        {
            var row = Selected(list);
            if (row == null) return;
            CallAsync("timeline", IdArgument(row), delegate(Dictionary<string, object> reply)
            {
                if (!Ok(reply)) { Report(reply); return; }
                OpenTimeline(row, Items(Map(reply, "result"), "events"));
            });
        }

        private void OpenTimeline(Dictionary<string, object> row, List<object> events)
        {
            using (Form dialog = BuildTimeline(row, events)) dialog.ShowDialog(this);
        }

        /// The Timeline dialog for `row`'s `events`, built and not shown - OpenTimeline shows it, LayoutAudit
        /// measures it.
        private Form BuildTimeline(Dictionary<string, object> row, List<object> events)
        {
            {
                var dialog = new Form();
                dialog.Text = S("timeline.title", "Timeline") + " - " + Conversation(row);
                dialog.Font = Font;
                dialog.BackColor = Canvas;
                dialog.ForeColor = Ink;
                // In the window's theme, title bar and all.
                Soft.TitleBar(dialog);
                dialog.StartPosition = FormStartPosition.CenterParent;
                dialog.ClientSize = new Size(Px(640), Px(420));
                dialog.MinimizeBox = false;
                dialog.ShowInTaskbar = false;
                var view = List(S("timeline.title", "Timeline"),
                                Col(S("timeline.col_time", "Time"), 140),
                                Col(S("timeline.col_event", "Event"), 250),
                                Col(S("timeline.col_detail", "Detail"), 220));
                if (events != null)
                {
                    foreach (object entry in events)
                    {
                        var item = entry as Dictionary<string, object>;
                        if (item == null) continue;
                        string code = Str(item, "code") ?? "other";
                        var line = new ListViewItem(When(Number(item, "at")));
                        line.SubItems.Add(S("event." + code, code));
                        // The state it moved to, in the words the lists use. The engine's reason
                        // codes are not shown: they are a closed vocabulary for logs and tools,
                        // and a translated label for each would say no more than the state does.
                        string to = Str(item, "to_code");
                        line.SubItems.Add(to == null ? "" : S("code." + to, to.Replace('_', ' ')));
                        view.Items.Add(line);
                    }
                }
                // Each column's widest cell, so the columns share the dialog's width by what they hold (FitColumns).
                MeasureCells(view);
                var padding = new Panel();
                padding.BackColor = Canvas;
                padding.Dock = DockStyle.Fill;
                padding.Padding = Pad(12, 12, 12, 12);
                // On the soft scroll bar, as the lists in the window are (see SoftListHost).
                var host = new SoftListHost(view);
                host.Dock = DockStyle.Fill;
                padding.Controls.Add(host);
                dialog.Controls.Add(padding);
                var close = MakeButton(S("action.close", "Close"), true, delegate { dialog.Close(); });
                var buttons = ButtonRow();
                buttons.FlowDirection = FlowDirection.RightToLeft;
                buttons.Padding = Pad(12, 0, 12, 12);
                buttons.Controls.Add(close);
                dialog.Controls.Add(buttons);
                dialog.AcceptButton = close;
                dialog.CancelButton = close;
                // Escape closes it whatever has the focus, the list included, which is where
                // the focus is when the dialog opens.
                dialog.KeyPreview = true;
                dialog.KeyDown += delegate(object sender, KeyEventArgs e)
                {
                    if (e.KeyCode == Keys.Escape) { e.Handled = true; dialog.Close(); }
                };
                timelineList = view;
                return dialog;
            }
        }

        // The last Timeline dialog's list, for LayoutAudit.
        private ListView timelineList;
    }
}

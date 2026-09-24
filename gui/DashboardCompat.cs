// Codex Auto Resume - the compatibility card, and what it is allowed to say.
//
// Verified, Checked, Compatible and "Failed here" (v0.6.7). The wording each outcome is
// reported in is here rather than in the page that shows it, because what may be claimed of
// a version of Codex is the point of the card.

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
        // The capabilities, in the registry's own order (compat.CAPABILITIES). Four are not offered yet; their rows are
        // left out, as the command line leaves them out.
        private static readonly string[] CompatOrder = { "engine_present", "exact_thread_recovery", "usage_limit_detection",
            "usage_reset_hint", "usage_probe", "thread_eligibility", "loaded_state_detection", "recovery_turn_tracking",
            "queue_withdraw", "outcome_observation", "transient_classification", "projection_freshness",
            "empty_response_recovery", "not_loaded_recovery", "goal_continuation", "subagent_recovery" };

        // The six states, in the order their meanings are listed (compat.STATES).
        private static readonly string[] CompatStates =
            { "VERIFIED", "CHECKED", "COMPATIBLE", "FAILED_HERE", "INCOMPATIBLE", "UNKNOWN" };

        // How long the live check a refresh brought may stand in for the watcher's report at most: as long as a report
        // may be relied on at all (compat.REPORT_MAX_AGE - the watcher's interval between evaluations, its longest wait
        // between ticks, and a margin). Past it the live check is as old as a report too old to use, and the report,
        // older still, says so.
        private const double CompatMaxAge = 4500;

        // The argument that asks the bridge's `compatibility` for a live check instead of the watcher's report.
        private const string LiveArgument = "{\"live\":true}";

        private TableLayoutPanel BuildCompatibility()
        {
            TableLayoutPanel card = MakeCard(S("compat.title", "Codex compatibility"));
            // The width of the page, under the two cards over it: no gap of its own beside them or under it.
            card.Margin = new Padding(0);
            TableLayoutPanel facts = Facts(card);
            compatOverall = Fact(facts, S("compat.overall", "Overall"));
            compatEngine = Fact(facts, S("compat.engine", "Codex version"));
            compatChecked = Fact(facts, S("compat.checked", "Checked"));
            compatData = Fact(facts, S("compat.data", "Data in force"));
            // What the view cannot vouch for - no report, one too old, an engine that changed, a watcher still acting on
            // what it found when it started, refreshed data that expired - in the accent, as the upgrade note above is.
            compatNotice = HelpText("");
            compatNotice.ForeColor = Accent;
            // Every group on the card - the facts, this, the parts, what the words mean, the refresh - the scale's
            // medium step apart, as the button is from what its card holds (LeadGap).
            compatNotice.Margin = Pad(0, Brand.SpaceM, 0, 0);
            // As wide as the card, which is the page's width: at the help text's 600 px a sentence of this card broke
            // in two with most of the card empty beside it.
            compatNotice.MaximumSize = Size.Empty;
            card.Controls.Add(compatNotice);
            // The parts, in two lists side by side: rows as the panel's settings rows are, a hairline between each two
            // and the state as a chip at the end (GateList, as Why it is waiting draws its checks).
            var lists = new SoftStack();
            lists.ColumnCount = 2;
            lists.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            lists.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
            lists.AutoSize = true;
            lists.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            lists.Dock = DockStyle.Fill;
            lists.Margin = Pad(0, Brand.SpaceM, 0, 0);
            lists.BackColor = Card;
            compatLeft = CompatList();
            compatLeft.Margin = Pad(0, 0, Brand.SpaceXl / 2, 0);
            compatRight = CompatList();
            compatRight.Margin = Pad(Brand.SpaceXl / 2, 0, 0, 0);
            lists.Controls.Add(compatLeft, 0, 0);
            lists.Controls.Add(compatRight, 1, 0);
            card.Controls.Add(lists);
            compatLists = lists;
            // What each state word on the card means, one line each, for the words the card shows.
            compatLegend = HelpText("");
            compatLegend.Margin = Pad(0, Brand.SpaceM, 0, 0);
            compatLegend.MaximumSize = Size.Empty;
            card.Controls.Add(compatLegend);
            // The refresh, at the card's bottom left as every card's button now is, and beside it what it last answered.
            var row = new SoftStack();
            row.ColumnCount = 2;
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.Dock = DockStyle.Fill;
            row.Margin = Pad(0, LeadGap, 0, 0);
            row.BackColor = Card;
            compatButton = MakeButton(S("diag.compat_refresh", "Refresh compatibility data"), false, delegate { RefreshCompatibility(); });
            compatButton.Margin = new Padding(0);
            compatButton.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;
            compatButton.Enabled = busy == 0;
            compatNote = Note();
            compatNote.AutoSize = true;
            compatNote.Anchor = AnchorStyles.Left | AnchorStyles.Right;
            compatNote.Margin = Pad(Brand.SpaceM, 0, 0, 0);
            compatNote.Text = compatSaid;
            row.Controls.Add(compatButton, 0, 0);
            row.Controls.Add(compatNote, 1, 0);
            card.Controls.Add(row);
            ShowCompatibility();
            return card;
        }

        private GateList CompatList()
        {
            var list = new GateList();
            list.Dock = DockStyle.Fill;
            list.Font = Font;
            list.AccessibleName = S("compat.title", "Codex compatibility");
            return list;
        }

        /// A view of the registry has arrived: the watcher's report (`live` false), read on the long-lived bridge, or the
        /// live check a refresh brought - the refresh button's answer, or the check made after an update check's refresh.
        /// The live check is shown for as long as it stands over the reports read after it (LiveStands).
        private void ApplyCompatibility(Dictionary<string, object> view, bool live)
        {
            if (view == null) return;
            if (live)
            {
                compatLive = view;
                // What the watcher's report said as this check was made: whatever it says later that it did not say
                // then is news this check never saw.
                compatLiveOver = Reading(compatView);
            }
            else
            {
                compatView = view;
                if (compatLive != null && !LiveStands(compatLive, compatLiveOver, view, Now())) compatLive = null;
            }
            compatUnreadable = false;
            ShowCompatibility();
        }

        /// Whether the live check a refresh brought (`live`) still stands over the watcher's report just read. A live
        /// check is relied on as a report is, and no longer:
        /// - a usable report as new as it takes its place: the watcher has caught up;
        /// - past the age a report may have (CompatMaxAge) it is as stale as one;
        /// - a report that has since become unusable - Codex changed under it, or it went missing, unreadable or too
        ///   old - ends it, failing closed as every reader of the report does, since the live check cannot tell whether
        ///   that change reached it too. What the report already said when the check was made (`over`), the check has
        ///   seen past: a watcher that is not running, whose report is missing, older or about the Codex before, leaves
        ///   it standing - and never snaps the card back to the data before the refresh.
        internal static bool LiveStands(Dictionary<string, object> live, string over, Dictionary<string, object> report, double now)
        {
            double at = Number(live, "checked_at");
            if (now - at >= CompatMaxAge) return false;
            if (Str(report, "status") == "ok") return Number(report, "checked_at") < at;
            return Reading(report) == over;
        }

        /// What a read of the report said, as its status and its time: "ok@1757000000.5", "absent@0", or "" for none.
        internal static string Reading(Dictionary<string, object> view)
        {
            if (view == null) return "";
            return (Str(view, "status") ?? "invalid") + "@" + Number(view, "checked_at").ToString("R", CultureInfo.InvariantCulture);
        }

        /// The Diagnostics card from the view in hand (ApplyCompatibility): nothing yet before the first read, and a read
        /// that failed said as one - never the last answer as if it were current.
        private void ShowCompatibility()
        {
            if (compatOverall == null) return;
            Dictionary<string, object> view = compatLive ?? compatView;
            var shown = new List<string[]>();
            var notices = new List<string>();
            var states = new List<string>();
            if (view == null)
            {
                string nothing = compatUnreadable ? S("pending.unavailable", "This cannot be read right now") : "-";
                compatOverall.Text = compatEngine.Text = compatChecked.Text = compatData.Text = compatUnreadable ? S("diag.unknown", "unknown") : "-";
                SetLines(compatNotice, compatUnreadable ? new List<string> { nothing } : notices);
                ShowParts(shown);
                SetLines(compatLegend, notices);
                return;
            }
            string status = Str(view, "status") ?? "invalid";
            bool usable = status == "ok";
            string overall = CompatState(Str(view, "overall"));
            compatOverall.Text = S("compat.state." + overall, overall.ToLowerInvariant());
            var engine = Map(view, "engine");
            string version = Str(engine, "version");
            // A report that cannot be used vouches for nothing it says - not the Codex it was about, which may since have
            // changed, nor the data then in force: "-" for both, as the panel has them, and never "not found". When it
            // was made is still said: it is what makes a report too old.
            compatEngine.Text = !usable ? "-" : !string.IsNullOrEmpty(version) ? version : S("compat.engine_none", "not found");
            compatChecked.Text = Ago(Number(view, "checked_at"));
            compatData.Text = usable ? CompatData(Map(view, "data")) : "-";
            // Why the view cannot be used - every part is unknown then, for that one reason, so the parts are not listed.
            if (!usable) notices.Add(S("compat.status." + status, S("compat.status.invalid", "The last check could not be read, so nothing in it is relied on.")));
            string acting = Str(view, "acting");
            if (usable && acting != null && acting != Str(view, "overall"))
                notices.Add(S("diag.compat_acting_differs",
                              "The watcher is still acting on what it found when it started. Stop it and start it again from this page to check again."));
            string cache = usable ? Str(Map(view, "data"), "cache") : null;
            if (cache == "expired" || cache == "from_the_future" || cache == "rejected" || cache == "superseded" || cache == "from_newer_product")
                notices.Add(S("compat.cache." + cache, cache.Replace('_', ' ')));
            SetLines(compatNotice, notices);
            var capabilities = Map(view, "capabilities");
            // The words the card shows, explained: the overall's and the parts', when there are parts to show. A view that
            // cannot be used is unknown for the one reason its notice gives, which the legend's reason would contradict.
            if (usable) states.Add(overall);
            if (usable && capabilities != null)
                foreach (string name in CompatOrder)
                {
                    var entry = Map(capabilities, name);
                    if (entry == null || Str(entry, "reason") == "not_implemented") continue;
                    string state = CompatState(Str(entry, "state"));
                    if (!states.Contains(state)) states.Add(state);
                    shown.Add(new[] { S("compat.capability." + name, name.Replace('_', ' ')),
                                      S("compat.state." + state, state.ToLowerInvariant()),
                                      state == "INCOMPATIBLE" || state == "FAILED_HERE" ? "BLOCK" : state == "UNKNOWN" ? "UNKNOWN" : "PASS" });
                }
            ShowParts(shown);
            var meanings = new List<string>();
            foreach (string state in CompatStates)
                if (states.Contains(state)) meanings.Add(S("compat.meaning." + state, state));
            SetLines(compatLegend, meanings);
        }

        /// The parts in the two lists, the first half on the left - and no room taken while there are none.
        private void ShowParts(List<string[]> shown)
        {
            int half = (shown.Count + 1) / 2;
            compatLeft.SetRows(shown.GetRange(0, half), "");
            compatRight.SetRows(shown.GetRange(half, shown.Count - half), "");
            bool any = shown.Count > 0;
            if (Soft.OwnVisible(compatLists) != any) compatLists.Visible = any;
        }

        /// A registry state word from any of the vocabularies a view carries it in: the four capability states, and the
        /// coarse word the overall and the watcher's gate use. Anything else is UNKNOWN, as the registry reads it.
        internal static string CompatState(string word)
        {
            if (word == "VERIFIED" || word == "verified") return "VERIFIED";
            if (word == "CHECKED" || word == "checked") return "CHECKED";
            if (word == "COMPATIBLE" || word == "structurally_compatible") return "COMPATIBLE";
            if (word == "FAILED_HERE" || word == "failed_here") return "FAILED_HERE";
            if (word == "INCOMPATIBLE" || word == "incompatible") return "INCOMPATIBLE";
            return "UNKNOWN";
        }

        /// Which data was in force: the data bundled with this version, data refreshed from GitHub, or none, with its
        /// sequence number.
        private string CompatData(Dictionary<string, object> data)
        {
            if (data == null) return "-";
            string source = Str(data, "source") ?? "none";
            if (source != "cache" && source != "bundled") source = "none";
            string said = S("compat.source." + source, source);
            object sequence = Get(data, source == "cache" ? "cache_sequence" : "bundled_sequence");
            if (source == "none" || !(sequence is double)) return said;
            return S("compat.source_sequence", "{source}, #{sequence}").Replace("{source}", said)
                   .Replace("{sequence}", ((int)(double)sequence).ToString(CultureInfo.InvariantCulture));
        }

        /// Lines of text in a label that says nothing, and takes no room, while it has none. Its own visibility, not
        /// Visible's answer, which is false for every label on a page that is not on screen - a card updated while
        /// another page was showing kept a line it no longer had.
        private static void SetLines(Label label, List<string> lines)
        {
            string text = string.Join(Environment.NewLine, lines.ToArray());
            if (label.Text != text) label.Text = text;
            bool any = text.Length > 0;
            if (Soft.OwnVisible(label) != any) label.Visible = any;
        }

        /// The registry's view for the card: the watcher's report, as the page is shown and with every read while it is.
        /// A file read, as quick as the dashboard's own, so it goes over the long-lived bridge; never the live check.
        private void LoadCompatibility()
        {
            if (compatOverall == null || loadingCompat || auditing) return;
            loadingCompat = true;
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                Dictionary<string, object> reply;
                try { reply = bridge.Call("compatibility", null); }
                catch (Exception) { reply = null; }
                MethodInvoker apply = delegate
                {
                    loadingCompat = false;
                    var view = Ok(reply) ? Map(reply, "compatibility") : null;
                    if (view != null) ApplyCompatibility(view, false);
                    else
                    {
                        // Unreadable now: the last report is not shown as if it were current. A live check still
                        // stands - a failed read says nothing about it - but no longer than a report would.
                        compatView = null;
                        compatUnreadable = true;
                        if (compatLive != null && Now() - Number(compatLive, "checked_at") >= CompatMaxAge) compatLive = null;
                        ShowCompatibility();
                    }
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(apply); }
                catch (Exception) { loadingCompat = false; }
            });
        }

        /// The refresh button: the registry data asked for once, from its one address, on the one-shot bridge from a
        /// worker thread (see the note at the top of this section). Every other action waits while it runs, as it does
        /// for any action here, and what it answered is said beside the button.
        private void RefreshCompatibility()
        {
            if (compatRefreshing) return;
            compatRefreshing = true;
            SetBusy(true);
            SetCompatNote(S("diag.compat_refreshing", "Asking GitHub for the compatibility data..."));
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string outcome;
                Dictionary<string, object> result;
                RunCompatibilityRefresh(bridge, out outcome, out result);
                MethodInvoker finish = delegate
                {
                    compatRefreshing = false;
                    SetBusy(false);
                    var view = Map(result, "compatibility");
                    if (view != null) ApplyCompatibility(view, Equals(Get(view, "live"), true));
                    object sequence = Get(result, "sequence") ?? Get(Map(view, "data"), "cache_sequence");
                    SetCompatNote(CompatibilitySaid(outcome, sequence is double ? ((int)(double)sequence).ToString(CultureInfo.InvariantCulture) : "?",
                                                    Str(result, "reason")));
                    if (view == null) LoadCompatibility();
                };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(finish); }
                catch (Exception) { }
            });
        }

        /// Runs the refresh and says which of six things happened. Busy first: an installation or a repair holds the
        /// installer's lock while it replaces the files the refresh would run, so the lock is looked at - taken and let
        /// go at once, never held for the refresh, so an installation that starts meanwhile is not turned away for it.
        private static void RunCompatibilityRefresh(PersistentBridge bridge, out string outcome, out Dictionary<string, object> result)
        {
            outcome = "failed";
            result = null;
            try
            {
                using (var gate = new System.Threading.Mutex(false, "Local\\CodexAutoResume.Install"))
                {
                    bool free;
                    try { free = gate.WaitOne(0); }
                    catch (System.Threading.AbandonedMutexException) { free = true; }
                    if (!free) { outcome = "busy"; return; }
                    gate.ReleaseMutex();
                }
                Dictionary<string, object> reply = bridge.CallOnce("compat-refresh", null);
                result = Ok(reply) ? Map(reply, "result") : null;
                outcome = CompatibilityOutcome(reply);
            }
            catch (Exception) { outcome = "failed"; }
        }

        /// The refresh's answer from the bridge's reply: `refreshed`, `refused`, `unavailable` or `incomplete` as it said
        /// it, and anything else - no reply, a refusal of the request, a word this window does not know - `failed`.
        internal static string CompatibilityOutcome(Dictionary<string, object> reply)
        {
            if (!Ok(reply)) return "failed";
            string answer = Str(Map(reply, "result"), "answer");
            if (answer == "refreshed" || answer == "refused" || answer == "unavailable" || answer == "incomplete") return answer;
            return "failed";
        }

        /// The `compatibility:` line an update check prints once github.com has answered - `refreshed <sequence>`,
        /// `refused <reason>` or `unavailable` (scripts/bootstrap.ps1) - as those words, or null when there is none or
        /// it says something else. The last one counts, as the `update:` line's does.
        internal static string CompatibilityLine(string printed)
        {
            string line = null;
            foreach (string raw in (printed ?? "").Replace("\r", "").Split('\n'))
            {
                string trimmed = raw.Trim();
                if (trimmed.StartsWith("compatibility: ", StringComparison.Ordinal)) line = trimmed.Substring("compatibility: ".Length);
            }
            if (line == null) return null;
            string[] words = line.Split(' ');
            if (words.Length == 1 && words[0] == "unavailable") return "unavailable";
            if (words.Length != 2) return null;
            if (words[0] == "refreshed" && Plain(words[1], true)) return line;
            if (words[0] == "refused" && Plain(words[1], false)) return line;
            return null;
        }

        // A sequence number (digits), or a refusal's code (lower-case letters and underscores), one to forty long.
        private static bool Plain(string word, bool digits)
        {
            if (word.Length == 0 || word.Length > 40) return false;
            foreach (char c in word)
                if (digits ? !(c >= '0' && c <= '9') : !((c >= 'a' && c <= 'z') || c == '_')) return false;
            return true;
        }

        /// What the update check's `compatibility:` line said, on the card, in the refresh's own words - the second
        /// request the check made, and its result - with the live check made after it when it brought new data
        /// (CheckAfterRefresh), as the refresh button's answer carries one, and the card read again.
        private void ReportCompatibilityLine(string line, Dictionary<string, object> live)
        {
            if (line == null) return;
            string[] words = line.Split(' ');
            SetCompatNote(CompatibilitySaid(words[0], words[0] == "refreshed" ? words[1] : "?", words[0] == "refused" ? words[1] : null));
            // A watcher that is not running has not looked at the new data, and its last report still says the data
            // before was in force - beside a note saying it no longer is. The live check says what is in force now.
            if (live != null) ApplyCompatibility(live, true);
            LoadCompatibility();
        }

        /// After an update check brought in new data (its `compatibility:` line says `refreshed`): the live check the
        /// refresh button's answer carries, which the check's own script does not make. It runs Codex's `--version` and
        /// `queue --help` on this machine and asks nothing of the network; on the one-shot bridge, from the update
        /// check's worker thread, never on the long-lived pipe the window paints from. Null for any other answer, or
        /// when the check could not be made - the watcher's report is what the card has then.
        private static Dictionary<string, object> CheckAfterRefresh(PersistentBridge bridge, string line)
        {
            if (line == null || !line.StartsWith("refreshed ", StringComparison.Ordinal)) return null;
            try
            {
                Dictionary<string, object> reply = bridge.CallOnce("compatibility", LiveArgument);
                var view = Ok(reply) ? Map(reply, "compatibility") : null;
                return view != null && Equals(Get(view, "live"), true) ? view : null;
            }
            catch (Exception) { return null; }
        }

        /// One sentence for what a refresh answered, from the refresh button or an update check.
        internal string CompatibilitySaid(string outcome, string sequence, string reason)
        {
            if (outcome == "refreshed")
                return S("diag.compat_refreshed", "Compatibility data #{sequence} is now in force.", "sequence", sequence);
            if (outcome == "refused")
                return S("diag.compat_refused", "The downloaded data was refused ({code}): {reason}. The data in force before still applies.")
                       .Replace("{code}", reason ?? "?").Replace("{reason}", RefusedBecause(reason));
            if (outcome == "unavailable")
                return S("diag.compat_unavailable", "GitHub could not be reached, so nothing was changed.");
            if (outcome == "incomplete")
                return S("diag.compat_incomplete",
                         "Files this installation is made of are missing, so the data could not be refreshed. Install it again from the release archive.");
            if (outcome == "busy")
                return S("diag.compat_busy", "An installation or a repair is running. Refresh once it has finished.");
            return S("diag.compat_failed", "The refresh did not finish, so nothing was changed.");
        }

        /// Why the validator refused a document, in plain words: one of six, for the eighteen codes it can give
        /// (compat.IMPORT_REASONS). The code itself is said beside it, for whoever asks for help with it.
        private string RefusedBecause(string code)
        {
            if (code == "from_the_future") return S("compat.refused.future", "it is dated after this computer's clock");
            if (code == "from_newer_product") return S("compat.refused.newer", "it needs a newer version of Codex Auto Resume");
            if (code == "rollback") return S("compat.refused.rollback", "it is older than the data already in force");
            if (code == "unreadable" || code == "not_a_json_file") return S("compat.refused.unreadable", "it could not be read");
            if (code == "write_failed") return S("compat.refused.not_saved", "it could not be saved on this computer");
            return S("compat.refused.invalid", "it is not valid compatibility data");
        }

        /// What the refresh last answered, beside its button: kept for a card built later, and said to a screen reader as
        /// it changes (NoteLabel).
        private void SetCompatNote(string text)
        {
            compatSaid = text ?? "";
            if (compatNote != null) SetNote(compatNote, compatSaid);
        }
    }
}

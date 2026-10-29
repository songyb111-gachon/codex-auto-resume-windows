// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - early_reset on Pending (v0.6.19, issue #50).
//
// While early_reset stands on, what it last did - when it read usage early, what that reading found and whether anything
// was continued (the status's advanced.early_check, control/earlycheck.py) - is said in Pending's Why it is waiting panel,
// under the usage readings core says there, for a recovery that waits for a usage limit (UsageNoted). It has no line, no
// button and no place of its own on Pending (the owner's decision of 2026-10-24: its Check now and its settings button
// went; its on/off is on the Advanced features page alone). A person's Retry now or Rescan asks the watcher to read
// Codex's usage once; while early_reset stands on, that reading is one of its two (UsageAsked: advanced-early-check, the
// probe for every waiting conversation together, answered by the click's own reading). It never sends: every check still
// runs. With early_reset off, or a status that does not carry it, nothing is said.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // The last status's early_reset reading (advanced.early_check), or null while it is off.
        private Dictionary<string, object> earlyShown;

        /// From each snapshot: what early_reset last did, as the status carries it, or none - and the panel told again
        /// when that changed, since core drew it before this edition read the status.
        private void EarlyApplied(Dictionary<string, object> reply)
        {
            Dictionary<string, object> shown = Map(Map(Map(reply, "status"), "advanced"), "early_check");
            bool same = shown == null ? earlyShown == null : earlyShown != null && EarlyText(shown) == EarlyText(earlyShown);
            earlyShown = shown;
            if (!same) ShowExplain();
        }

        /// v0.6.19 (the owner's decision of 2026-10-24): under the usage readings Why it is waiting says for a recovery that
        /// waits for a usage limit, early_reset's own - when it last read, what it read, whether anything went on.
        partial void UsageNoted(Dictionary<string, object> row, List<string> said)
        {
            if (earlyShown == null || said == null) return;
            string text = EarlyText(earlyShown);
            if (!string.IsNullOrEmpty(text)) said.Add(text);
        }

        /// What early_reset's last reading was, in words: when, what it read, and whether anything went on.
        internal string EarlyText(Dictionary<string, object> shown)
        {
            if (shown == null) return "";
            if (!(Get(shown, "checked_at") is double)) return Word("page.early.none", "Early reset check: no reading yet.");
            string time = ClockTime(Number(shown, "checked_at"));
            string read = Str(shown, "read");
            if (read == "available")
            {
                if (Equals(Get(shown, "lifted"), true))
                    return Word("page.early.lifted", "Early reset check at {time}: usage available twice. The waiting recoveries went on through every other check.", "time", time);
                string confirm = Get(shown, "confirm_at") is double ? ClockTime(Number(shown, "confirm_at")) : time;
                return Word("page.early.available_first", "Early reset check at {time}: usage available. A second reading from {confirm} confirms it; nothing was continued yet.", "time", time)
                    .Replace("{confirm}", confirm);
            }
            if (read == "still_limited")
                return Word("page.early.limited", "Early reset check at {time}: still limited. Nothing was continued.", "time", time);
            if (read == "unknown")
                return Word("page.early.unknown", "Early reset check at {time}: usage could not be told. Nothing was continued.", "time", time);
            return Word("page.early.not_read", "Early reset check at {time}: usage was not read, because another check came first. Nothing was continued.", "time", time);
        }

        /// v0.6.19 (the owner's decision of 2026-10-24): a person's Retry now or Rescan asked the watcher to read Codex's
        /// usage once. While early_reset stands on, that reading is also one of its two - the probe for every waiting
        /// conversation together, opened at the click's look and answered by the click's own reading (advanced-early-check,
        /// which folds a request made within one reading's life). Its answer changes nothing on the page.
        partial void UsageAsked()
        {
            if (earlyShown == null) return;
            AdvancedCall("advanced-early-check", "{}", false, delegate(Dictionary<string, object> reply) { });
        }
    }
}

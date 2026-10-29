// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - Start the 5-hour window early on the Advanced features page (v0.6.20, window_anchor).
//
// Its card says the reset its last start fixed - "Next reset fixed at 12:20." - under where it stands, while it stands
// on and that reset is still ahead (the status's advanced.window_anchor, engine/anchor.view). Its choices are the
// page's own controls: each time of day a drop-down of Off and every half hour, with Custom... opening the Settings
// page's clock dialog for any minute (a time is held as its minute of the day plus two, Off as 1), and Start right after
// a reset a switch, as every on-or-off choice of the window is. The request itself is the watcher's: nothing here
// starts it.
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
        private const string AnchorId = "window_anchor";
        // A time choice off, and how far a time of day is shifted to be held as a whole number from 1 (engine/anchor.py).
        private const int AnchorOff = 1, AnchorShift = 2;

        // The last status's window_anchor times (advanced.window_anchor), or null while it is off.
        private Dictionary<string, object> anchorShown;

        /// From each snapshot: the reset window_anchor's last start fixed, as the status carries it, or none.
        private void AnchorApplied(Dictionary<string, object> reply)
        {
            anchorShown = Map(Map(Map(reply, "status"), "advanced"), AnchorId);
        }

        /// What the card shows of it, for ShowAdvancedDetail's "built again only when it changed".
        private string AnchorShownText(Dictionary<string, object> item)
        {
            return Str(item, "id") == AnchorId ? AnchorText() ?? "" : "";
        }

        /// "Next reset fixed at HH:MM." while a fixed reset is ahead, or null.
        private string AnchorText()
        {
            object fixedAt = Get(anchorShown, "fixed_at");
            if (!(fixedAt is double) || (double)fixedAt <= Now()) return null;
            return Word("page.anchor.fixed", "Next reset fixed at {time}.", "time", ClockTime((double)fixedAt));
        }

        /// Its line on the head card, under where it stands: only for window_anchor, only with a fixed reset ahead.
        private void BuildAnchorLine(Dictionary<string, object> item, TableLayoutPanel head)
        {
            if (Str(item, "id") != AnchorId) return;
            string text = AnchorText();
            if (text == null) return;
            Label line = HelpText(text);
            line.ForeColor = Ink;
            line.Margin = Pad(0, Brand.SpaceS, 0, 0);
            head.Controls.Add(line);
        }

        /// Whether a choice is one of its times of day.
        private static bool IsAnchorTime(string key)
        {
            return key != null && key.StartsWith("anchor_at_", StringComparison.Ordinal);
        }

        /// A time choice's value as the drop-down says it: Off, or HH:MM.
        private string AnchorTimeText(int value)
        {
            if (value < AnchorShift || value > 1439 + AnchorShift) return Word("page.option.off", "Off");
            int minute = value - AnchorShift;
            return (minute / 60).ToString("00", CultureInfo.InvariantCulture) + ":" +
                   (minute % 60).ToString("00", CultureInfo.InvariantCulture);
        }

        /// A held value as the clock dialog starts from ("HH:MM"), or null for Off.
        private static string AnchorClock(string held)
        {
            int value;
            if (held == null || !int.TryParse(held, NumberStyles.None, CultureInfo.InvariantCulture, out value) ||
                value < AnchorShift || value > 1439 + AnchorShift) return null;
            int minute = value - AnchorShift;
            return (minute / 60).ToString("00", CultureInfo.InvariantCulture) + ":" +
                   (minute % 60).ToString("00", CultureInfo.InvariantCulture);
        }

        /// What the clock dialog answered ("HH:MM") as the value a time choice holds, or null for one that is no time.
        private static string AnchorValue(string typed)
        {
            string[] parts = (typed ?? "").Split(':');
            int hour, minute;
            if (parts.Length != 2 || !int.TryParse(parts[0], NumberStyles.None, CultureInfo.InvariantCulture, out hour) ||
                !int.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out minute) ||
                hour > 23 || minute > 59) return null;
            return (hour * 60 + minute + AnchorShift).ToString(CultureInfo.InvariantCulture);
        }
    }
}

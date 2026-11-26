// Codex Auto Resume - what the icon says: its tooltip, and how much of one Windows will take (v0.6.27, S6.3c).
//
// ui/tray/words.py and the parts of ui/words.py it reads (countdown, share, left, window_name), ported call for call.
// Pure: it asks Windows nothing. Lengths and cuts are by code point, as Python's len and slices count a str.
// A JSON number reaches the host as a double (gui/SurfaceJson.cs, the window's Json): a whole one is read as the int
// the core writes (PopupWords.Str), so `300` and `300.0` are one value here (AUDIT-v0628, S6.3c).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace CodexAutoResume
{
    internal static class TrayWords
    {
        internal const int TipChars = 128;
        /// The edition no surface names beside the version or the product (v0.6.14).
        internal const string UnnamedEdition = "standard";
        /// domain/plug.EXTRA: the key a surface puts an edition plug's fields under.
        internal const string Extra = "advanced";
        internal const int LowLeft = 10;
        internal const int WeekMinutes = 7 * 24 * 60;
        private const string NameHeld = "\u0000";
        private static readonly char[] RoundTheName = { ' ', ':', ' ', ' ' };

        private static readonly Dictionary<string, string> UsageWords = new Dictionary<string, string>
        {
            { "usage.window", "{window} {percent}% left" }, { "usage.weekly", "weekly" }, { "usage.days", "{n}-day" },
            { "usage.hours", "{n}-hour" }, { "usage.minutes", "{n}-minute" }, { "usage.limit", "limit" },
        };

        /// ui/words.countdown: 45s, 12:04, 3:05:00.
        internal static string Countdown(double seconds)
        {
            if (double.IsNaN(seconds) || double.IsInfinity(seconds))
                throw new OverflowException("cannot convert float " + (double.IsNaN(seconds) ? "NaN" : "infinity") + " to integer");
            long total = Math.Max(0L, (long)Math.Truncate(seconds));
            long hours = total / 3600, rest = total % 3600;
            long minutes = rest / 60, secs = rest % 60;
            if (hours != 0)
                return hours.ToString(CultureInfo.InvariantCulture) + ":" + minutes.ToString("00", CultureInfo.InvariantCulture)
                       + ":" + secs.ToString("00", CultureInfo.InvariantCulture);
            if (minutes != 0)
                return minutes.ToString(CultureInfo.InvariantCulture) + ":" + secs.ToString("00", CultureInfo.InvariantCulture);
            return secs.ToString(CultureInfo.InvariantCulture) + "s";
        }

        /// ui/words.share: the share used as a whole number, never rounded up to 100.
        internal static long Share(Dictionary<string, object> window)
        {
            object value = SurfaceRender.Field(window, "used_percent");
            double used = SurfaceMath.Truthy(value) ? Number(value) : 0;
            return used >= 100 ? 100 : (long)Math.Floor(used);
        }

        /// ui/words.left: the share LEFT, 0 to 100.
        internal static long Left(Dictionary<string, object> window)
        {
            return Math.Max(0L, Math.Min(100L, 100 - Share(window)));
        }

        private static double Number(object value)
        {
            if (value is bool) return (bool)value ? 1 : 0;
            return (double)value;
        }

        private static bool IsInt(object value)
        {
            return value is double && (double)value == Math.Floor((double)value) && !double.IsInfinity((double)value);
        }

        /// ui/words.window_name: weekly, days, hours or minutes; "limit" when Codex gave no length.
        internal static string WindowName(object minutes, Func<string, object, string> say)
        {
            if (!IsInt(minutes) || (double)minutes <= 0) return say("usage.limit", null);
            long whole = (long)(double)minutes;
            if (whole == WeekMinutes) return say("usage.weekly", null);
            if (whole % 1440 == 0) return say("usage.days", whole / 1440);
            if (whole % 60 == 0) return say("usage.hours", whole / 60);
            return say("usage.minutes", whole);
        }

        private static string Get(IDictionary<string, object> strings, string key, string fallback)
        {
            object found;
            if (strings == null || !strings.TryGetValue(key, out found)) return fallback;
            var text = found as string;
            if (text == null) throw new InvalidCastException("'" + PopupWords.Str(found) + "' has no replace");
            return text;
        }

        /// A piece of the state line: its text, and whether it is the one that counts down.
        internal sealed class Piece
        {
            internal string Text;
            internal bool Counts;
        }

        /// tooltip_parts: the title, the edition's word, the state line's pieces and the meter's rows.
        internal sealed class Parts
        {
            internal string Title;
            internal string Edition;
            internal List<Piece> Line = new List<Piece>();
            internal List<Dictionary<string, object>> Meter = new List<Dictionary<string, object>>();

            internal Dictionary<string, object> ToJson()
            {
                var line = new List<object>();
                foreach (Piece piece in Line) line.Add(new List<object> { piece.Text, piece.Counts });
                var meter = new List<object>();
                foreach (Dictionary<string, object> row in Meter) meter.Add(row);
                return new Dictionary<string, object>
                {
                    { "title", Title }, { "edition", Edition }, { "line", line }, { "meter", meter },
                };
            }
        }

        /// tooltip_parts: what hovering over the icon says, in its parts (v0.6.24).
        internal static Parts TooltipParts(Dictionary<string, object> snapshot, IDictionary<string, object> strings,
                                           double now, string edition)
        {
            var parts = new Parts { Title = Get(strings, "tray.title", "Codex Auto Resume") };
            object named = null;
            if (!string.IsNullOrEmpty(edition) && edition != UnnamedEdition)
            {
                object found;
                named = strings != null && strings.TryGetValue("edition." + edition, out found) ? found : edition;
            }
            parts.Edition = named == null ? null : PopupWords.Str(named);
            if (snapshot == null || snapshot.Count == 0) return parts;
            var line = new List<Piece>();
            if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "failed")))
                line.Add(new Piece { Text = Get(strings, "tray.failed", "A recovery failed") });
            else if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "unconfirmed")))
                line.Add(new Piece { Text = Get(strings, "activity.attention", "Needs your attention") });
            else if (!SurfaceMath.Truthy(snapshot.ContainsKey("enabled") ? snapshot["enabled"] : true))
                line.Add(new Piece { Text = Get(strings, "tray.paused", "Paused") });
            else
            {
                object waiting = snapshot.ContainsKey("waiting") ? snapshot["waiting"] : 0.0;
                object running = snapshot.ContainsKey("running") ? snapshot["running"] : 0.0;
                if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "held")))
                    line.Add(new Piece { Text = Get(strings, "activity.attention", "Needs your attention") });
                if (SurfaceMath.Truthy(running))
                    line.Add(new Piece { Text = Get(strings, "tray.running", "{n} running in Codex").Replace("{n}", PopupWords.Str(running)) });
                if (SurfaceMath.Truthy(waiting))
                {
                    line.Add(new Piece { Text = Get(strings, "tray.waiting", "{n} waiting").Replace("{n}", PopupWords.Str(waiting)) });
                    object due = SurfaceRender.Field(snapshot, "next_at");
                    if (SurfaceMath.Truthy(due))
                        line.Add(new Piece
                        {
                            Text = Get(strings, "tray.next", "next check in {time}").Replace("{time}", Countdown(Number(due) - now)),
                            Counts = true,
                        });
                }
                if (line.Count == 0) line.Add(new Piece { Text = Get(strings, "tray.idle", "Nothing waiting") });
            }
            parts.Line = line;
            parts.Meter = MeterRows(snapshot, strings);
            return parts;
        }

        /// tooltip: the parts joined, and cut to szTip's length a row or a piece at a time (v0.6.26 N1).
        internal static string Tooltip(Dictionary<string, object> snapshot, IDictionary<string, object> strings, double now,
                                       string edition)
        {
            Parts parts = TooltipParts(snapshot, strings, now, edition);
            string text = Joined(parts.Title, parts.Edition, parts.Line, parts.Meter);
            if (parts.Line.Count == 0 || Length(text) < TipChars) return text;
            List<Dictionary<string, object>> rows = parts.Meter;
            List<Piece> line = parts.Line;
            while (rows.Count > 0 || line.Count > 1)
            {
                if (rows.Count > 0) rows = rows.GetRange(0, rows.Count - 1);
                else line = line.GetRange(0, line.Count - 1);
                text = Joined(parts.Title, parts.Edition, line, rows);
                if (Length(text) < TipChars) return text;
            }
            return Cut(text, TipChars - 1);
        }

        /// tooltip_joined: the title (and the edition's word), the state line, the meter, each on a line of its own.
        internal static string Joined(Parts parts)
        {
            return Joined(parts.Title, parts.Edition, parts.Line, parts.Meter);
        }

        private static string Joined(string title, string edition, List<Piece> line, List<Dictionary<string, object>> meter)
        {
            string head = title + (!string.IsNullOrEmpty(edition) ? " · " + edition : "");
            if (line.Count == 0) return head;
            var rows = new List<string>();
            foreach (Dictionary<string, object> row in meter) rows.Add((string)row["text"]);
            var pieces = new List<string>();
            foreach (Piece piece in line) pieces.Add(piece.Text);
            string joined = string.Join(" · ", rows);
            return head + "\n" + string.Join(" · ", pieces) + (joined.Length > 0 ? "\n" + joined : "");
        }

        /// meter_rows: the advanced edition's usage meter, a row per window it last read.
        internal static List<Dictionary<string, object>> MeterRows(Dictionary<string, object> snapshot,
                                                                 IDictionary<string, object> strings)
        {
            var rows = new List<Dictionary<string, object>>();
            var added = SurfaceRender.Field(snapshot, Extra) as Dictionary<string, object>;
            var meter = SurfaceRender.Field(added, "meter") as Dictionary<string, object>;
            var windows = SurfaceRender.Field(meter, "windows") as List<object>;
            if (windows == null) return rows;
            Func<string, object, string> sayN = (key, n) => Say(strings, key, "n", n);
            foreach (object entry in windows)
            {
                var window = entry as Dictionary<string, object>;
                if (window == null || !(SurfaceRender.Field(window, "used_percent") is double)) continue;
                string label = WindowName(SurfaceRender.Field(window, "window_minutes"), sayN);
                long percent = Left(window);
                string alone = Say(strings, "usage.window", "window", NameHeld, "percent", percent)
                    .Replace(NameHeld, "").Trim(RoundTheName);
                double fraction = Math.Max(0.0, Math.Min(1.0, 1.0 - (double)window["used_percent"] / 100.0));
                rows.Add(new Dictionary<string, object>
                {
                    { "label", label }, { "percent", alone },
                    { "text", Say(strings, "usage.window", "window", label, "percent", percent) },
                    { "fraction", fraction }, { "low", percent <= LowLeft },
                });
            }
            return rows;
        }

        /// meter_line: the meter as one line, or null.
        internal static string MeterLine(Dictionary<string, object> snapshot, IDictionary<string, object> strings)
        {
            var texts = new List<string>();
            foreach (Dictionary<string, object> row in MeterRows(snapshot, strings)) texts.Add((string)row["text"]);
            string line = string.Join(" · ", texts);
            return line.Length > 0 ? line : null;
        }

        /// meter_rows' say: the catalog's words when they are not empty, else the catalog's own English, else the key;
        /// each {name} replaced by str(value), in the order given.
        private static string Say(IDictionary<string, object> strings, string key, params object[] fields)
        {
            object found = null;
            if (strings != null) strings.TryGetValue(key, out found);
            string text;
            if (SurfaceMath.Truthy(found))
            {
                text = found as string;
                if (text == null) throw new InvalidCastException("'" + PopupWords.Str(found) + "' has no replace");
            }
            else
            {
                string english;
                text = UsageWords.TryGetValue(key, out english) ? english : key;
            }
            for (int at = 0; at + 1 < fields.Length; at += 2)
            {
                if (fields[at + 1] == null && fields.Length == 2) break;
                object value = fields[at + 1];
                text = text.Replace("{" + fields[at] + "}", value is long ? ((long)value).ToString(CultureInfo.InvariantCulture)
                                                                         : PopupWords.Str(value));
            }
            return text;
        }

        /// len(text): code points.
        internal static int Length(string text)
        {
            int count = 0;
            for (int at = 0; at < text.Length; at++)
            {
                if (char.IsHighSurrogate(text[at]) && at + 1 < text.Length && char.IsLowSurrogate(text[at + 1])) at++;
                count++;
            }
            return count;
        }

        /// text[:points]: the first `points` code points.
        internal static string Cut(string text, int points)
        {
            var built = new StringBuilder();
            int count = 0;
            for (int at = 0; at < text.Length && count < points; at++, count++)
            {
                built.Append(text[at]);
                if (char.IsHighSurrogate(text[at]) && at + 1 < text.Length && char.IsLowSurrogate(text[at + 1]))
                    built.Append(text[++at]);
            }
            return built.ToString();
        }
    }
}

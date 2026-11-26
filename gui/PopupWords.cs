// Codex Auto Resume - the popup's own words: how a line is cut and broken (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/words.py's drawing half, call for call: `say` (one string from the
// catalog the surfaces were given, English under it), `one_line` (a conversation name as one bounded line) and
// `unbroken` (the pieces of a label no line may break inside). What the Python reads of l10n to build a view model
// (`kept`, `locale_of`, `vocabulary`) is the core's (car-surface): the host is handed the view model and its locale.
//
// Python counts a text by its code points and splits it on what str.isspace calls a space; .NET counts UTF-16 units
// and has its own idea of a space. Every helper below works on code points and on Python's spaces, so a name with an
// emoji or a supplementary ideograph is cut and broken exactly where the Python cuts and breaks it.
using System;
using System.Collections.Generic;
using System.Text;

namespace CodexAutoResume
{
    internal static class PopupWords
    {
        /// The catalog English is read from when the surfaces' own has no word (l10n.catalog(l10n.DEFAULT)); null
        /// when the host was given none, and then the key itself is what is said, as the Python says for a key no
        /// catalog has.
        internal static Dictionary<string, object> English { get; set; }

        /// One string from the catalog the icon was given, English underneath it (words.say). Each {name} in it is
        /// replaced by its field, in the order given.
        internal static string Say(IDictionary<string, object> strings, string key, params KeyValuePair<string, object>[] fields)
        {
            object found = null;
            if (strings != null) strings.TryGetValue(key, out found);
            string value = found as string;
            if (string.IsNullOrEmpty(value))
            {
                object english = null;
                if (English != null) English.TryGetValue(key, out english);
                value = english as string ?? key;
            }
            foreach (KeyValuePair<string, object> field in fields)
                value = value.Replace("{" + field.Key + "}", Str(field.Value));
            return value;
        }

        /// A conversation name as a single, bounded line (words.one_line): its words joined by one space, and past
        /// `limit` code points cut to limit - 1 of them and an ellipsis.
        internal static string OneLine(object text, int limit = 120)
        {
            string flat = string.Join(" ", Split(Str(text)).ToArray());
            List<string> points = CodePoints(flat);
            if (points.Count <= limit) return flat;
            var cut = new StringBuilder();
            for (int i = 0; i < limit - 1 && i < points.Count; i++) cut.Append(points[i]);
            return cut.Append('…').ToString();
        }

        /// A character a line may break before or after: Chinese and Japanese are set without spaces (_breaks_anywhere).
        internal static bool BreaksAnywhere(int code)
        {
            return (0x2E80 <= code && code <= 0x9FFF) || (0xF900 <= code && code <= 0xFAFF)
                || (0xFF00 <= code && code <= 0xFFEF);
        }

        /// The pieces of a label no line may break inside (words.unbroken): its words, and in a run of Chinese or
        /// Japanese each character. Never empty: a label of no words is one empty piece.
        internal static List<string> Unbroken(object text)
        {
            var pieces = new List<string>();
            foreach (string word in Split(Str(text)))
            {
                List<string> points = CodePoints(word);
                bool anywhere = false;
                foreach (string point in points)
                    if (BreaksAnywhere(Code(point))) anywhere = true;
                if (anywhere) pieces.AddRange(points);
                else pieces.Add(word);
            }
            if (pieces.Count == 0) pieces.Add("");
            return pieces;
        }

        // ------------------------------------------------------------------ Python's text, in .NET

        /// str(value) as the Python writes the values a view model holds: a text as it is, True/False, None as "None".
        internal static string Str(object value)
        {
            if (value == null) return "None";
            if (value is string) return (string)value;
            if (value is bool) return (bool)value ? "True" : "False";
            if (value is double)
            {
                double number = (double)value;
                if (number == Math.Floor(number) && Math.Abs(number) < 1e16)
                    return ((long)number).ToString(System.Globalization.CultureInfo.InvariantCulture);
                return number.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
            }
            return Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
        }

        /// Whether str.isspace holds for this code point: the C0 separators Python counts and .NET does not, and
        /// .NET's spaces but U+180E, which Unicode stopped calling one (Python follows; .NET Framework's tables do not).
        internal static bool IsSpace(int code)
        {
            if (code >= 0x1C && code <= 0x1F) return true;
            if (code == 0x180E || code > 0xFFFF) return false;
            return char.IsWhiteSpace((char)code);
        }

        /// str.split() with no separator: the runs between spaces, none empty.
        internal static List<string> Split(string text)
        {
            var words = new List<string>();
            var word = new StringBuilder();
            foreach (string point in CodePoints(text))
            {
                if (IsSpace(Code(point)))
                {
                    if (word.Length > 0) words.Add(word.ToString());
                    word.Length = 0;
                }
                else word.Append(point);
            }
            if (word.Length > 0) words.Add(word.ToString());
            return words;
        }

        /// One code point's number, from the units CodePoints gave it.
        internal static int Code(string point)
        {
            return point.Length == 2 ? char.ConvertToUtf32(point[0], point[1]) : point[0];
        }

        /// The text's code points, each as the one or two UTF-16 units that spell it; a lone surrogate is a point of
        /// its own, as Python keeps it.
        internal static List<string> CodePoints(string text)
        {
            var points = new List<string>();
            if (text == null) return points;
            for (int i = 0; i < text.Length; i++)
            {
                if (char.IsHighSurrogate(text[i]) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1]))
                {
                    points.Add(text.Substring(i, 2));
                    i++;
                }
                else points.Add(text.Substring(i, 1));
            }
            return points;
        }
    }
}

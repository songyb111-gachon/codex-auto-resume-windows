// Codex Auto Resume - the watcher host's JSON reader and writer (v0.6.27, S6.3).
//
// The host speaks JSON with the core (HostCore: every request and reply) and reads its render jobs in it, and the
// surfaces take every value as the window's Json.Parse gives it (gui/ISurfaces.cs). The window's reader is in
// gui/WindowJson.cs beside its strings cache, which needs Windows Forms and the window's own process; the host has
// neither (its references are System.dll and System.Drawing.dll). So the host compiles this copy of that one class,
// and tests/test_surface_parity.py holds it to gui/WindowJson.cs's `Json` byte for byte: one reader, kept in two
// lists, never two readers. A change to either is a change to both.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace CodexAutoResume
{
    internal static class Json
    {
        // A minimal reader for the control bridge's own output. Not a general parser:
        // it accepts exactly the shapes we emit, and anything else raises.
        // The bridge's deepest real output is four levels. A limit well above that turns
        // pathological input into a FormatException, which every caller catches, instead of
        // a StackOverflowException, which .NET cannot catch and which ends the process -
        // measured at about 6,000 levels with no limit.
        private const int MaxDepth = 64;

        internal static object Parse(string text)
        {
            return ParseText(text, false);
        }

        /// A JSON document as Python's json.loads takes one: a value with nothing after it but whitespace. For
        /// a file the settings layer reads too (Theme.Stored), where "{...} and more" is no settings at all.
        internal static object ParseDocument(string text)
        {
            return ParseText(text, true);
        }

        private static object ParseText(string text, bool whole)
        {
            int index = 0;
            int depth = 0;
            try
            {
                object value = ParseValue(text, ref index, ref depth);
                if (whole)
                {
                    SkipWhitespace(text, ref index);
                    if (index != text.Length) throw new FormatException("more after the JSON value");
                }
                return value;
            }
            catch (IndexOutOfRangeException)
            {
                // Truncated input ran off the end of the string: say so as a format error.
                throw new FormatException("unexpected end of JSON");
            }
            catch (ArgumentOutOfRangeException)
            {
                throw new FormatException("unexpected end of JSON");
            }
        }

        private static void SkipWhitespace(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
        }

        private static object ParseValue(string s, ref int i, ref int depth)
        {
            SkipWhitespace(s, ref i);
            if (i >= s.Length) throw new FormatException("unexpected end of JSON");
            char c = s[i];
            if (c == '{' || c == '[')
            {
                if (++depth > MaxDepth) throw new FormatException("JSON nested too deeply");
                object nested = c == '{' ? (object)ParseObject(s, ref i, ref depth)
                                         : (object)ParseArray(s, ref i, ref depth);
                depth--;
                return nested;
            }
            if (c == '"') return ParseString(s, ref i);
            if (s.Length - i >= 4 && s.Substring(i, 4) == "true") { i += 4; return true; }
            if (s.Length - i >= 5 && s.Substring(i, 5) == "false") { i += 5; return false; }
            if (s.Length - i >= 4 && s.Substring(i, 4) == "null") { i += 4; return null; }
            return ParseNumber(s, ref i);
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i, ref int depth)
        {
            var result = new Dictionary<string, object>();
            i++;
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return result; }
            while (true)
            {
                SkipWhitespace(s, ref i);
                string key = ParseString(s, ref i);
                SkipWhitespace(s, ref i);
                if (s[i] != ':') throw new FormatException("expected :");
                i++;
                result[key] = ParseValue(s, ref i, ref depth);
                SkipWhitespace(s, ref i);
                if (s[i] == ',') { i++; continue; }
                if (s[i] == '}') { i++; return result; }
                throw new FormatException("expected , or }");
            }
        }

        private static List<object> ParseArray(string s, ref int i, ref int depth)
        {
            var result = new List<object>();
            i++;
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return result; }
            while (true)
            {
                result.Add(ParseValue(s, ref i, ref depth));
                SkipWhitespace(s, ref i);
                if (s[i] == ',') { i++; continue; }
                if (s[i] == ']') { i++; return result; }
                throw new FormatException("expected , or ]");
            }
        }

        private static string ParseString(string s, ref int i)
        {
            if (s[i] != '"') throw new FormatException("expected string");
            i++;
            var builder = new StringBuilder();
            while (s[i] != '"')
            {
                if (s[i] == '\\')
                {
                    i++;
                    char e = s[i];
                    if (e == 'n') builder.Append('\n');
                    else if (e == 't') builder.Append('\t');
                    else if (e == 'r') builder.Append('\r');
                    else if (e == 'b') builder.Append('\b');
                    else if (e == 'f') builder.Append('\f');
                    else if (e == 'u')
                    {
                        builder.Append((char)Convert.ToInt32(s.Substring(i + 1, 4), 16));
                        i += 4;
                    }
                    else builder.Append(e);
                }
                else builder.Append(s[i]);
                i++;
            }
            i++;
            return builder.ToString();
        }

        private static object ParseNumber(string s, ref int i)
        {
            int start = i;
            while (i < s.Length && (char.IsDigit(s[i]) || s[i] == '-' || s[i] == '+' ||
                                    s[i] == '.' || s[i] == 'e' || s[i] == 'E')) i++;
            return double.Parse(s.Substring(start, i - start), CultureInfo.InvariantCulture);
        }

        internal static string Escape(string value)
        {
            var builder = new StringBuilder("\"");
            foreach (char c in value ?? string.Empty)
            {
                if (c == '"' || c == '\\') builder.Append('\\').Append(c);
                else if (c < 32) builder.Append("\\u").Append(((int)c).ToString("x4"));
                else builder.Append(c);
            }
            return builder.Append('"').ToString();
        }

        /// The shapes Parse returns, written back as JSON: for the window's own strings cache,
        /// which keeps a bridge reply as it was parsed.
        internal static string Write(object value)
        {
            var builder = new StringBuilder();
            WriteValue(builder, value, 0);
            return builder.ToString();
        }

        private static void WriteValue(StringBuilder builder, object value, int depth)
        {
            if (depth > MaxDepth) throw new FormatException("JSON nested too deeply");
            var map = value as Dictionary<string, object>;
            var list = value as List<object>;
            if (value == null) builder.Append("null");
            else if (value is bool) builder.Append((bool)value ? "true" : "false");
            else if (value is string) builder.Append(Escape((string)value));
            else if (value is double) builder.Append(((double)value).ToString("R", CultureInfo.InvariantCulture));
            else if (map != null)
            {
                builder.Append('{');
                bool first = true;
                foreach (KeyValuePair<string, object> pair in map)
                {
                    if (!first) builder.Append(',');
                    first = false;
                    builder.Append(Escape(pair.Key)).Append(':');
                    WriteValue(builder, pair.Value, depth + 1);
                }
                builder.Append('}');
            }
            else if (list != null)
            {
                builder.Append('[');
                for (int i = 0; i < list.Count; i++)
                {
                    if (i > 0) builder.Append(',');
                    WriteValue(builder, list[i], depth + 1);
                }
                builder.Append(']');
            }
            else throw new FormatException("not a JSON value");
        }
    }
}

// Codex Auto Resume - the window's JSON reader, and the words it keeps.
//
// The window talks to the watcher in JSON and has no framework to read it with, so this is the
// reader: values, objects, arrays and the escapes, and nothing else. `StringsCache` is beside
// it because it is the one thing read back off disk in the same shape.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using System.Windows.Forms.Automation;

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

    /// The last strings reply, kept so the window can label itself before the interpreter that
    /// answers has started.
    ///
    /// Opening the window waited 260-400 ms for Python to start and import, to be told the words
    /// it was told last time. A strings reply depends on three things, and a cached one is used
    /// only while all three are exactly what they were when it was written:
    ///   * the product and its catalogs: the window's version, and a digest of every file the
    ///     words and the language rules are read from. Not their length and time: a release
    ///     archive gives every file one fixed time, which extracting and copying keep, so a word
    ///     corrected to one of the same length changed neither;
    ///   * the Interface language stored in settings: a digest of the settings file, so any save
    ///     at all makes the next opening ask again, and the language read from those same bytes,
    ///     which a reply has to name as its own ("preference") to be kept or used;
    ///   * the language Windows asks for: the preferred UI languages, and the environment
    ///     variables Python reads before them.
    /// Anything else - no cache, one that cannot be read, a key that differs - is a miss, and a miss
    /// asks the bridge before the first label, as the window always did.
    ///
    /// The bridge reads the settings when it answers, after the key was taken. So a reply is kept
    /// only if the key still describes the installation just before the file is put in place: a
    /// language saved in between was otherwise kept under the old key, and opened a later window
    /// once the language had been set back. So a language that has just changed never opens in
    /// the old one.
    ///
    /// The file (config\strings-cache.json in the installation) is the window's own, beside the
    /// settings: config\ and logs\ are the only folders the product writes, and uninstalling with
    /// -Purge removes it with config\. Nothing else reads it, and deleting it only makes the next
    /// opening ask.
    internal static class StringsCache
    {
        [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern bool GetUserPreferredUILanguages(int flags, out int count, char[] buffer, ref int size);

        private const int MUI_LANGUAGE_NAME = 0x8;

        // Where a key names the Interface language it was made from (PreferenceIn).
        private const string PreferencePart = "|interface_language ";

        private static string PathIn(string root)
        {
            return Path.Combine(Path.Combine(root, "config"), "strings-cache.json");
        }

        /// This installation's key as it is now, or null when it cannot be told.
        internal static string Key(string root)
        {
            try
            {
                var key = new StringBuilder("2");
                key.Append("|window ").Append(typeof(StringsCache).Assembly.GetName().Version);
                key.Append("|root ").Append(Path.GetFullPath(root));
                using (var sha = System.Security.Cryptography.SHA256.Create())
                {
                    string app = Path.Combine(root, "app");
                    Stamp(key, sha, Path.Combine(Path.Combine(app, ".codex-plugin"), "plugin.json"));
                    string package = Path.Combine(Path.Combine(app, "src"), "codex_auto_resume");
                    foreach (string name in new[] { "interface.py", "l10n.py", "settings.py", "config.py", "controlcli.py" })
                        Stamp(key, sha, Path.Combine(package, name));
                    string locales = Path.Combine(package, "locales");
                    string[] catalogs = Directory.Exists(locales) ? Directory.GetFiles(locales, "*.json") : new string[0];
                    Array.Sort(catalogs, StringComparer.OrdinalIgnoreCase);
                    foreach (string catalog in catalogs) Stamp(key, sha, catalog);
                    // Read once, so the language is taken from the very bytes the digest is of. The
                    // file's own digest is deliberately not part of the key: the only thing in it these
                    // words depend on is the Interface language, which is below - and keying on the
                    // whole file made every save of any setting, the theme included, throw the cache
                    // away and open the next window cold on a fresh interpreter.
                    string settings = Path.Combine(Path.Combine(root, "config"), "settings.json");
                    byte[] stored = File.Exists(settings) ? File.ReadAllBytes(settings) : null;
                    string preference = StoredPreference(stored);
                    if (preference == null) return null;
                    key.Append(PreferencePart).Append(preference);
                }
                foreach (string name in new[] { "CODEX_AUTO_RESUME_LANG", "LC_ALL", "LC_MESSAGES", "LANG" })
                    key.Append('|').Append(name).Append(' ').Append(Environment.GetEnvironmentVariable(name) ?? "");
                key.Append("|windows ").Append(PreferredLanguages());
                return key.ToString();
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static void Stamp(StringBuilder key, System.Security.Cryptography.HashAlgorithm sha, string path)
        {
            key.Append('|').Append(Path.GetFileName(path)).Append(' ');
            key.Append(File.Exists(path) ? Convert.ToBase64String(sha.ComputeHash(File.ReadAllBytes(path))) : "-");
        }

        /// The Interface language `settings` stores, as the bridge takes it - `system` when there is
        /// no settings file or it names none - or null when the file cannot be read as settings.
        /// Wherever the bridge takes the file otherwise (a value it does not know is `system` to
        /// it), its reply names another language and is not kept, which is only a miss.
        private static string StoredPreference(byte[] settings)
        {
            if (settings == null) return "system";
            var map = Json.Parse(new UTF8Encoding(false).GetString(settings).TrimStart('﻿')) as Dictionary<string, object>;
            if (map == null) return null;
            object value;
            return map.TryGetValue("interface_language", out value) && value is string ? (string)value : "system";
        }

        /// The Interface language `key` was made from. Nothing before it in a key can hold a '|'.
        private static string PreferenceIn(string key)
        {
            int start = key.IndexOf(PreferencePart, StringComparison.Ordinal);
            if (start < 0) return null;
            start += PreferencePart.Length;
            int end = key.IndexOf('|', start);
            return end < 0 ? key.Substring(start) : key.Substring(start, end - start);
        }

        /// Whether `reply` is the answer for the Interface language `key` was made from.
        private static bool AnswersFor(Dictionary<string, object> reply, string key)
        {
            object preference;
            string wanted = PreferenceIn(key);
            return wanted != null && reply.TryGetValue("preference", out preference) &&
                   preference is string && (string)preference == wanted;
        }

        private static string PreferredLanguages()
        {
            int count, size = 0;
            if (!GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, out count, null, ref size) || size <= 0) return "-";
            var buffer = new char[size];
            if (!GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, out count, buffer, ref size)) return "-";
            return new string(buffer, 0, Math.Min(size, buffer.Length)).TrimEnd('\0').Replace('\0', ',');
        }

        private static bool Usable(Dictionary<string, object> reply)
        {
            object ok, words;
            return reply != null && reply.TryGetValue("ok", out ok) && Equals(ok, true) &&
                   reply.TryGetValue("strings", out words) && words is Dictionary<string, object>;
        }

        /// The reply cached for exactly `key`, and for the Interface language it was made from, or null.
        internal static Dictionary<string, object> Read(string root, string key)
        {
            if (key == null) return null;
            try
            {
                string path = PathIn(root);
                if (!File.Exists(path)) return null;
                var entry = Json.Parse(File.ReadAllText(path, Encoding.UTF8)) as Dictionary<string, object>;
                object stored, reply;
                if (entry == null || !entry.TryGetValue("key", out stored) || !(stored is string) || (string)stored != key) return null;
                if (!entry.TryGetValue("reply", out reply)) return null;
                var map = reply as Dictionary<string, object>;
                return Usable(map) && AnswersFor(map, key) ? map : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// Keeps `reply` under `key`: a reply for the Interface language the key was made from, and
        /// only while the key still describes this installation, checked again just before the file
        /// is put in place. Written beside the old file and moved over it, so nothing ever reads half
        /// of one; a failure leaves no cache, which is only a miss.
        internal static void Write(string root, string key, Dictionary<string, object> reply)
        {
            if (key == null || !Usable(reply) || !AnswersFor(reply, key)) return;
            string temporary = null;
            try
            {
                var entry = new Dictionary<string, object>();
                entry["key"] = key;
                entry["reply"] = reply;
                string path = PathIn(root);
                string folder = Path.GetDirectoryName(path);
                // The installation's own config\, never a folder made for the cache.
                if (!Directory.Exists(folder)) return;
                // Short, and this process's own: .NET Framework refuses a path of 260 characters, and
                // a GUID in the name took an installation in a deep folder past that - every write
                // failed there, silently, and the cache was never used.
                temporary = Path.Combine(folder,
                                         "strings-cache." + Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture) + ".tmp");
                File.WriteAllText(temporary, Json.Write(entry), new UTF8Encoding(false));
                if (Key(root) != key) return;
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
                temporary = null;
            }
            catch (Exception) { }
            finally
            {
                try { if (temporary != null && File.Exists(temporary)) File.Delete(temporary); }
                catch (Exception) { }
            }
        }

        /// Replaces the cache when a fresh reply says something other than the cached one - kept as
        /// Write keeps any reply, so only while `key` still describes this installation.
        internal static void Refresh(string root, string key, Dictionary<string, object> cached, Dictionary<string, object> fresh)
        {
            try
            {
                if (!Usable(fresh) || Json.Write(fresh) == Json.Write(cached)) return;
                Write(root, key, fresh);
            }
            catch (Exception) { }
        }
    }
}

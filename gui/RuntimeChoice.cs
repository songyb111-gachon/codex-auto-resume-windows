// Codex Auto Resume - which Python this installation's programs run under (v0.6.23).
//
// The C# reader of the record src/codex_auto_resume/chosen_runtime.py reads: <home>\runtimes\chosen.json, {"version":
// "3.15.2"}. The window's bridges, the MCP launcher and the hook launcher ask here for the interpreter they start. Only the
// advanced edition writes that record, and this reader takes it only in an installation with a package beside core's in
// app\src - the fact the product itself reads (edition.py) - so a record left behind can never move a standard installation.
//
// A record missing, unreadable, or not of a version's shape, or a runtime folder that is a link or lacks a file: the
// bundled runtime, as ever. The folder is worked out from the version, so the record cannot point anywhere else. Repair and
// the setup window's own steps do not ask here: they stay on the bundled runtime so that a broken choice cannot stop them.
//
// C# 5 and System.dll only: the launchers are console programs of one reference.

using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace CodexAutoResume
{
    internal static class RuntimeChoice
    {
        private const string Bundled = "runtime";
        private const string Folder = "runtimes";
        private const string Record = "chosen.json";
        private const string CorePackage = "codex_auto_resume";
        private const int RecordMost = 4096;

        private static readonly Regex Named = new Regex(
            "^\\s*\\{\\s*\"version\"\\s*:\\s*\"(3\\.([1-9][0-9])\\.(?:0|[1-9][0-9]{0,2}))\"", RegexOptions.CultureInvariant);

        /// python.exe of the runtime to run: the chosen one where the record stands, else the bundled one.
        internal static string Python(string home)
        {
            return Interpreter(home, "python.exe");
        }

        /// python.exe of the runtime the installation came with, whatever is chosen.
        internal static string BundledPython(string home)
        {
            return Path.Combine(Path.Combine(home, Bundled), "python.exe");
        }

        private static string Interpreter(string home, string name)
        {
            try
            {
                string version, minor;
                if (ReadRecord(home, out version, out minor) && AdvancedInstalled(home))
                {
                    string where = Path.Combine(Path.Combine(home, Folder), version);
                    if (Complete(Path.Combine(home, Folder), where, minor)) return Path.Combine(where, name);
                }
            }
            catch (Exception) { /* whatever went wrong, the bundled runtime is there */ }
            return Path.Combine(Path.Combine(home, Bundled), name);
        }

        private static bool ReadRecord(string home, out string version, out string minor)
        {
            version = minor = null;
            string path = Path.Combine(Path.Combine(home, Folder), Record);
            if (!File.Exists(path) || new FileInfo(path).Length > RecordMost) return false;
            Match found = Named.Match(File.ReadAllText(path, new UTF8Encoding(false)));
            if (!found.Success) return false;
            version = found.Groups[1].Value;
            minor = found.Groups[2].Value;
            return true;
        }

        /// Whether a package sits beside core's in app\src: what makes an installation the advanced edition.
        private static bool AdvancedInstalled(string home)
        {
            string source = Path.Combine(Path.Combine(home, "app"), "src");
            foreach (string each in Directory.GetDirectories(source))
                if (!string.Equals(Path.GetFileName(each), CorePackage, StringComparison.Ordinal) &&
                    File.Exists(Path.Combine(each, "__init__.py"))) return true;
            return false;
        }

        private static bool Real(string folder)
        {
            return Directory.Exists(folder) && (File.GetAttributes(folder) & FileAttributes.ReparsePoint) == 0;
        }

        private static bool Complete(string root, string where, string minor)
        {
            if (!Real(root) || !Real(where)) return false;
            string stem = "python3" + minor;
            string[] needed = { "python.exe", "pythonw.exe", stem + ".dll", stem + "._pth", stem + ".zip" };
            foreach (string name in needed)
                if (!File.Exists(Path.Combine(where, name))) return false;
            return true;
        }
    }
}

// CodexAutoResume-Setup-v<version>.exe, and the advanced edition's CodexAutoResume-Advanced-Setup-v<version>.exe:
// the release's ZIP in one file that installs when it is double-clicked, with nothing to unzip first.
//
// It carries one thing, its edition's release archive, byte for byte, as a managed resource, with the archive's
// SHA-256 as a constant beside it (build/make_setup.py compiles both in). When it starts it
//   1. takes DLLs from System32 alone, or stops. It is downloaded and started from Downloads, where anything
//      else downloaded lies too, and Windows looks for a DLL that is not one of its KnownDLLs in a program's own
//      folder first: codex-compat-reporter 1.4.0 loaded bcrypt, CRYPTSP, CRYPTBASE and profapi from there;
//   2. stops when a <program>.config is beside it. .NET reads one before Main, and this program never comes
//      with one, so it is someone else's file;
//   3. checks the carried bytes against the constant, and stops on any difference;
//   4. makes a folder of its own in the user's temporary folder - a new name, created new, refused when it is
//      already there, a junction included, and held open so it cannot be swapped while it is used - and unpacks
//      the archive into it, refusing any entry that would land anywhere else. A long temporary folder does not
//      stop it: the files are written by their \\?\ names, which have no 260-character limit;
//   5. runs that archive's own Install.cmd by its full path, in that folder, as a double-click in Explorer runs
//      it: the same installer, asking the same questions in this same console, with the arguments given here
//      passed on;
//   6. removes the folder, and ends with Install.cmd's exit code. Closing the console window ends a console
//      program a few seconds after Windows tells it so, and ends Install.cmd with it: the folder is removed in
//      those seconds, so a window closed at Install.cmd's last "Press any key" leaves nothing behind either.
// No network, no administrator rights (its manifest asks for none) and no Python of its own: the archive
// carries the Python the installer uses.
//
// The digest shows the carried bytes are the ones the build put in, so a damaged download or disk is caught -
// not who made them: whoever could change the archive could change the constant too. Who made them is what the
// release's build provenance attestation says (docs/VERIFY.md).
//
// Two hooks, for tests/test_setup.py, and neither starts anything: --loaded-modules does steps 1 to 4 and 6 and
// prints, as a JSON array, the path of every module this process has loaded; --unpack-into <name> does steps 1
// to 4 into <name> in the temporary folder rather than a new name, then 6 - how the tests hold the refusal of a
// folder that is already there.
//
// Its own messages are in English, as Install.cmd's and the installer's are: it runs before anything of the
// product is on the machine, and hands over to that installer within a second.
//
// C# 5 only: this is compiled by the in-box csc (build/make_setup.py).
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

// Each DLL this program's own code calls into is taken from System32 alone. Without this, .NET Framework looks
// for it in the program's folder first, by its full path, whatever SetDefaultDllDirectories says.
[assembly: DefaultDllImportSearchPaths(DllImportSearchPath.System32)]

namespace CodexAutoResumeSetup
{
    // Its own exit codes, apart from every one Install.cmd passes back (0, 1 and 14 today).
    internal static class Codes
    {
        internal const int Unguarded = 40;
        internal const int Configured = 41;
        internal const int Arguments = 42;
        internal const int Damaged = 43;
        internal const int NoFolder = 44;
        internal const int NotUnpacked = 45;
        internal const int NotStarted = 46;
    }

    internal static class Program
    {
        // First of all, before anything loads a DLL: DLLs from System32 alone, or nothing runs. The rest is in a
        // method of its own, so compiling this one loads nothing more.
        static int Main(string[] arguments)
        {
            if (!Dlls.FromSystem32Only())
            {
                return Say.Stopped(Codes.Unguarded, Dlls.Unguarded, !Hook(arguments));
            }
            string config = Dlls.ConfigBeside();
            if (config != null)
            {
                return Say.Stopped(Codes.Configured, string.Format(CultureInfo.InvariantCulture, Dlls.Configured,
                                                                   config), !Hook(arguments));
            }
            return Started(arguments, Hook(arguments));
        }

        // A test's hook, which never waits for Enter: every one begins with two hyphens, and nothing Install.cmd
        // is given does.
        static bool Hook(string[] arguments)
        {
            return arguments.Length > 0 && arguments[0].StartsWith("--", StringComparison.Ordinal);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        static int Started(string[] arguments, bool hook)
        {
            bool modules = arguments.Length == 1 && arguments[0] == "--loaded-modules";
            string into = arguments.Length == 2 && arguments[0] == "--unpack-into" ? arguments[1] : null;
            if (hook ? !(modules || (into != null && Passed.Name(into))) : !Passed.Acceptable(arguments))
            {
                return Say.Stopped(Codes.Arguments, Passed.Refused, !hook);
            }
            byte[] archive = Carried.Read();
            if (archive == null)
            {
                return Say.Stopped(Codes.Damaged, "This setup program stops here: the archive it carries is not the " +
                                   "one it was built with (its SHA-256 differs). The file is damaged - download it " +
                                   "again.", !hook);
            }
            // Before the folder is made, so a console window closed at any moment after it finds it removed.
            Closing.Watch();
            string reason;
            Folder folder = Folder.Fresh(into ?? "CodexAutoResume-Setup-" + Guid.NewGuid().ToString("N").Substring(0, 16),
                                         out reason);
            if (folder == null)
            {
                return Say.Stopped(Codes.NoFolder, reason, !hook);
            }
            try
            {
                if (!hook)
                {
                    Say.Line("Codex Auto Resume setup: unpacking " + Embedded.Archive + " into " + folder.Path);
                }
                string failed = Unpacking.Into(archive, folder.Path);
                if (Closing.Now)
                {
                    // The console window was closed: there is no one to ask anything, and Install.cmd is not started
                    // in a console that is going away.
                    return Codes.NotStarted;
                }
                if (failed != null)
                {
                    return Say.Stopped(Codes.NotUnpacked, "This setup program stops here: " + failed, !hook);
                }
                if (modules)
                {
                    Say.Raw(Json.Array(Loaded()) + "\n");
                }
                return hook ? 0 : Install(folder.Path, arguments);
            }
            finally
            {
                bool removed = folder.Remove();
                // A closed console window ends Install.cmd and what it started at the same moment as it tells this
                // program, so a file one of them held a moment ago is let go of soon: it is tried again while
                // Windows still gives this program time.
                while (!removed && Closing.Now && Closing.Left() > 400)
                {
                    Thread.Sleep(200);
                    removed = folder.Remove();
                }
                if (!removed && !Closing.Now)
                {
                    Say.Line("The temporary folder " + folder.Path + " could not be removed completely. It holds " +
                             "only an unpacked copy of " + Embedded.Archive + ", and can be deleted.");
                }
                Closing.Done();
            }
        }

        // Install.cmd as Explorer runs a double-clicked one - cmd.exe /c with the script's full path, in the
        // script's folder - from System32 by its full path, with /d so no AutoRun command of the machine's runs
        // first and moves it elsewhere. It shares this console: the person answers its questions here. Ctrl+C
        // is Install.cmd's to answer, so this program outlives it and still removes the folder
        // (Closing.OutliveCtrlC). Closing the console window is not anyone's to answer: it ends Install.cmd, and
        // this program waits a moment for that and goes on to remove the folder (Closing).
        static int Install(string folder, string[] arguments)
        {
            string script = Path.Combine(folder, "Install.cmd");
            if (!File.Exists(script))
            {
                return Say.Stopped(Codes.NotStarted, "This setup program stops here: the archive it carries has no " +
                                   "Install.cmd.", true);
            }
            ProcessStartInfo start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "cmd.exe"));
            start.Arguments = "/d /s /c \"\"" + script + "\"" +
                              (arguments.Length > 0 ? " " + string.Join(" ", arguments) : "") + "\"";
            start.WorkingDirectory = folder;
            start.UseShellExecute = false;
            Closing.OutliveCtrlC();
            try
            {
                using (Process run = Process.Start(start))
                {
                    while (!run.WaitForExit(200))
                    {
                        if (Closing.Now)
                        {
                            run.WaitForExit(Math.Max(0, Math.Min(1500, Closing.Left() - 2000)));
                            break;
                        }
                    }
                    // Not exited only when the window was closed and Windows is about to end this program: the code
                    // reaches no one then.
                    return run.HasExited ? run.ExitCode : Codes.NotStarted;
                }
            }
            catch (Win32Exception error)
            {
                return Say.Stopped(Codes.NotStarted, "This setup program stops here: Install.cmd could not be " +
                                   "started (" + error.Message + ").", true);
            }
        }

        static List<string> Loaded()
        {
            List<string> paths = new List<string>();
            using (Process self = Process.GetCurrentProcess())
            {
                foreach (ProcessModule module in self.Modules)
                {
                    paths.Add(module.FileName);
                }
            }
            return paths;
        }
    }

    // Where this program takes DLLs from: Windows' System32 folder and nowhere else - the reporter's guard,
    // codex-compat-reporter gui/Program.cs, as it was released in 1.4.1.
    internal static class Dlls
    {
        const uint LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x800;
        internal const string Unguarded =
            "This setup program stops here: Windows did not let it load DLLs from the System32 folder alone, and " +
            "then a DLL in the folder it is in, such as Downloads, could run in Windows' place. Windows 10 and 11 " +
            "let it.";
        internal const string Configured =
            "This setup program stops here: a file named {0} is beside it. .NET reads such a file as a program " +
            "like this one starts, and this one never comes with one, so it may have been put there to change " +
            "what runs. Delete that file, or move the setup program to a folder of its own.";

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool SetDefaultDllDirectories(uint directoryFlags);

        [DllImport("kernel32.dll", EntryPoint = "SetDllDirectoryW", CharSet = CharSet.Unicode, ExactSpelling = true,
                   SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool SetDllDirectory(string pathName);

        // SetDefaultDllDirectories, for every DLL loaded from here on and every DLL each of them loads; and
        // SetDllDirectory(""), which takes the current folder out of the older search that a load by a full path
        // with an altered search path still makes. When Windows has not the one, or refuses either, nothing runs.
        public static bool FromSystem32Only()
        {
            try
            {
                return SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32) && SetDllDirectory("");
            }
            catch (EntryPointNotFoundException)
            {
                return false;
            }
        }

        // The name of a <program>.config beside it, or null. What .NET did with it before Main cannot be undone
        // here; what it would change later - which assemblies load, from where - does not happen, because the
        // program stops.
        public static string ConfigBeside()
        {
            string config = typeof(Dlls).Assembly.Location + ".config";
            return File.Exists(config) ? Path.GetFileName(config) : null;
        }
    }

    // What may be passed on to Install.cmd: its switches and plain values - letters, digits and hyphens, as
    // install.ps1 takes them. cmd.exe reads the line it is given, so a character it gives a meaning to
    // (& | < > ^ % " and the rest) would change what runs; such an argument is refused, not passed on.
    internal static class Passed
    {
        internal const string Refused =
            "This setup program stops here: it passes on to Install.cmd only switches and plain words - letters, " +
            "digits and hyphens, such as -SkipStartup - and was given something else.";

        public static bool Acceptable(string[] arguments)
        {
            foreach (string argument in arguments)
            {
                string word = argument.StartsWith("-", StringComparison.Ordinal) ? argument.Substring(1) : argument;
                if (!Name(word))
                {
                    return false;
                }
            }
            return true;
        }

        // Letters, digits and hyphens, beginning with a letter or a digit, at most 64 of them.
        public static bool Name(string word)
        {
            if (word.Length == 0 || word.Length > 64 || word[0] == '-')
            {
                return false;
            }
            foreach (char c in word)
            {
                if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-'))
                {
                    return false;
                }
            }
            return true;
        }
    }

    // The archive this program carries: read whole, once, and held to the digest compiled in beside it; the
    // bytes that were checked are the bytes that are unpacked.
    internal static class Carried
    {
        public static byte[] Read()
        {
            using (Stream stream = typeof(Carried).Assembly.GetManifestResourceStream(Embedded.Resource))
            {
                if (stream == null || stream.Length != Embedded.Length)
                {
                    return null;
                }
                byte[] bytes = new byte[Embedded.Length];
                int at = 0;
                while (at < bytes.Length)
                {
                    int got = stream.Read(bytes, at, bytes.Length - at);
                    if (got <= 0)
                    {
                        return null;
                    }
                    at += got;
                }
                return string.Equals(Sha256(bytes), Embedded.Sha256, StringComparison.Ordinal) ? bytes : null;
            }
        }

        static string Sha256(byte[] bytes)
        {
            using (SHA256 sha = SHA256.Create())
            {
                StringBuilder hex = new StringBuilder(64);
                foreach (byte b in sha.ComputeHash(bytes))
                {
                    hex.Append(b.ToString("x2", CultureInfo.InvariantCulture));
                }
                return hex.ToString();
            }
        }
    }

    // A folder of this program's own in the user's temporary folder. CreateDirectory makes a new one or fails -
    // it never takes a folder or a junction that is already there - and the folder is then held open, without
    // FILE_SHARE_DELETE, so nothing can rename it or put a junction in its place while it is written and run.
    internal sealed class Folder
    {
        const int ERROR_ALREADY_EXISTS = 183;
        const uint FILE_READ_ATTRIBUTES = 0x80;
        const uint FILE_SHARE_READ = 0x1;
        const uint FILE_SHARE_WRITE = 0x2;
        const uint OPEN_EXISTING = 3;
        const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
        const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
        const uint FILE_ATTRIBUTE_DIRECTORY = 0x10;
        const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x400;

        [DllImport("kernel32.dll", EntryPoint = "CreateDirectoryW", CharSet = CharSet.Unicode, ExactSpelling = true,
                   SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool CreateDirectory(string path, IntPtr attributes);

        [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, ExactSpelling = true,
                   SetLastError = true)]
        static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr attributes,
                                                uint disposition, uint flags, IntPtr template);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool GetFileInformationByHandle(SafeFileHandle file, out Information information);

        // BY_HANDLE_FILE_INFORMATION: thirteen DWORDs, the attributes first.
        [StructLayout(LayoutKind.Sequential)]
        struct Information
        {
            public uint Attributes;
            public uint Created1, Created2, Accessed1, Accessed2, Written1, Written2;
            public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }

        public readonly string Path;
        SafeFileHandle held;

        Folder(string path, SafeFileHandle handle)
        {
            Path = path;
            held = handle;
        }

        public static Folder Fresh(string name, out string reason)
        {
            string path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), name);
            reason = null;
            if (!CreateDirectory(LongName.Of(path), IntPtr.Zero))
            {
                int error = Marshal.GetLastWin32Error();
                reason = "This setup program stops here: " + path + (error == ERROR_ALREADY_EXISTS
                    ? " is already there, and it unpacks only into a folder it has just made."
                    : " could not be made (Windows error " + error.ToString(CultureInfo.InvariantCulture) + ").");
                return null;
            }
            SafeFileHandle handle = CreateFile(LongName.Of(path), FILE_READ_ATTRIBUTES,
                                               FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero, OPEN_EXISTING,
                                               FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero);
            Information information;
            if (handle.IsInvalid || !GetFileInformationByHandle(handle, out information) ||
                (information.Attributes & FILE_ATTRIBUTE_DIRECTORY) == 0 ||
                (information.Attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
            {
                // Not the folder it made a moment ago. It is not this program's, so it is left as it is.
                handle.Dispose();
                reason = "This setup program stops here: the folder it made, " + path + ", was replaced by " +
                         "something else before it could be used.";
                return null;
            }
            return new Folder(path, handle);
        }

        // Lets go of the folder and removes it with everything in it, never following a link out of it: a
        // junction or a link inside is removed as the link it is. False when something could not be removed; true
        // once it is gone, so it can be asked again after a file in it was let go of. By its \\?\ name, as it
        // was written.
        public bool Remove()
        {
            held.Dispose();
            try
            {
                DirectoryInfo directory = new DirectoryInfo(LongName.Of(Path));
                if (!directory.Exists)
                {
                    return true;
                }
                Erase(directory);
                return true;
            }
            catch (IOException)
            {
                return false;
            }
            catch (UnauthorizedAccessException)
            {
                return false;
            }
        }

        static void Erase(DirectoryInfo directory)
        {
            foreach (FileSystemInfo item in directory.EnumerateFileSystemInfos())
            {
                DirectoryInfo inner = item as DirectoryInfo;
                if (inner != null && (item.Attributes & FileAttributes.ReparsePoint) == 0)
                {
                    Erase(inner);
                    continue;
                }
                if (inner != null)
                {
                    inner.Delete(false);
                    continue;
                }
                if ((item.Attributes & FileAttributes.ReadOnly) != 0)
                {
                    item.Attributes = FileAttributes.Normal;
                }
                item.Delete();
            }
            directory.Delete(false);
        }
    }

    // The archive, unpacked from the checked bytes into the new folder. Each entry is held to the folder first:
    // a name that climbs out of it, is rooted, names a drive, a stream or a device, or that Windows would store
    // under another name (a trailing dot or space) is refused, and so is a file that is already there. The
    // release's own archive has none of these; this is so that no archive could.
    internal static class Unpacking
    {
        public static string Into(byte[] archive, string folder)
        {
            string root = Path.GetFullPath(folder).TrimEnd('\\') + "\\";
            int files = 0;
            try
            {
                using (ZipArchive zip = new ZipArchive(new MemoryStream(archive, false), ZipArchiveMode.Read))
                {
                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        string name = entry.FullName;
                        bool directory = name.EndsWith("/", StringComparison.Ordinal);
                        if (!Plain(directory ? name.Substring(0, name.Length - 1) : name))
                        {
                            return "the archive holds an entry named \"" + name + "\", which would not be unpacked " +
                                   "inside its folder.";
                        }
                        string target = Path.GetFullPath(root + name.Replace('/', '\\'));
                        if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                        {
                            return "the archive holds an entry named \"" + name + "\", which would be unpacked " +
                                   "outside its folder.";
                        }
                        if (Closing.Now)
                        {
                            return "the console window was closed.";
                        }
                        // Written by the \\?\ name, which has no 260-character limit: the user's temporary folder
                        // can be long, and the release's own entries run to 62 characters below this folder.
                        string written = LongName.Of(target);
                        if (directory)
                        {
                            Directory.CreateDirectory(written);
                            continue;
                        }
                        Directory.CreateDirectory(Path.GetDirectoryName(written));
                        using (Stream source = entry.Open())
                        using (FileStream to = new FileStream(written, FileMode.CreateNew, FileAccess.Write,
                                                              FileShare.None))
                        {
                            source.CopyTo(to);
                        }
                        files++;
                    }
                }
            }
            catch (InvalidDataException error)
            {
                return "the archive could not be read (" + error.Message + ").";
            }
            catch (IOException error)
            {
                return "the archive could not be unpacked (" + error.Message + ").";
            }
            catch (UnauthorizedAccessException error)
            {
                return "the archive could not be unpacked (" + error.Message + ").";
            }
            return files > 0 ? null : "the archive it carries is empty.";
        }

        static bool Plain(string name)
        {
            if (name.Length == 0 || name.Length > 400)
            {
                return false;
            }
            foreach (string part in name.Split('/'))
            {
                if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".", StringComparison.Ordinal) ||
                    part.EndsWith(" ", StringComparison.Ordinal))
                {
                    return false;
                }
                foreach (char c in part)
                {
                    if (c < ' ' || "\\:*?\"<>|".IndexOf(c) >= 0)
                    {
                        return false;
                    }
                }
            }
            return true;
        }
    }

    // A full path as the \\?\ name Windows reads without the 260-character limit that .NET Framework's file
    // functions and CreateDirectory keep for an ordinary one. The path it is given is already full and normalized
    // (GetTempPath, then GetFullPath), which is what such a name has to be: Windows takes it as it is.
    internal static class LongName
    {
        public static string Of(string path)
        {
            if (path.StartsWith(@"\\?\", StringComparison.Ordinal))
            {
                return path;
            }
            if (path.StartsWith(@"\\", StringComparison.Ordinal))
            {
                return @"\\?\UNC\" + path.Substring(2);
            }
            return @"\\?\" + path;
        }
    }

    // What closing the console window does. Windows tells every program in the console (CTRL_CLOSE_EVENT, and the
    // same at sign-out and shutdown) and ends each one when its handler returns, or after about five seconds.
    // Install.cmd and what it started end at once; this program's handler waits, up to Grace, for the folder to be
    // removed by the code that removes it anyway - Started's finally - which learns from Now that the window is
    // going and that it has Left() milliseconds.
    //
    // It is the one handler this program ever has: added once, before the folder is made, and never taken away.
    // Windows holds its list of handlers while one of them runs, and this one runs for as long as the folder is
    // being removed. Install used to add a handler for Ctrl+C (Console.CancelKeyPress) and take it away when
    // Install.cmd ended; when the window was closed as Install.cmd ended, taking it away waited for this handler,
    // which waited for the folder to be removed, until Windows ended the program with the folder still there.
    // So Ctrl+C and Ctrl+Break are this handler's too: left to Windows' own handler, which ends the program,
    // until Install.cmd is started, and answered here from then on (OutliveCtrlC).
    internal static class Closing
    {
        const uint CTRL_C_EVENT = 0;
        const uint CTRL_BREAK_EVENT = 1;
        const uint CTRL_CLOSE_EVENT = 2;
        const uint CTRL_LOGOFF_EVENT = 5;
        const uint CTRL_SHUTDOWN_EVENT = 6;
        const int Grace = 4500;

        delegate bool Handler(uint type);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool SetConsoleCtrlHandler(Handler handler, [MarshalAs(UnmanagedType.Bool)] bool add);

        // Held for as long as the process lives: Windows calls it through a pointer the collector cannot see.
        static readonly Handler heard = Heard;
        static readonly ManualResetEvent cleaned = new ManualResetEvent(false);
        static readonly Stopwatch clock = Stopwatch.StartNew();
        static long closedAt = -1;
        static volatile bool outliveCtrlC;

        public static void Watch()
        {
            SetConsoleCtrlHandler(heard, true);
        }

        // From Install.cmd's start to this program's end, Ctrl+C and Ctrl+Break are Install.cmd's to answer - it
        // is told on its own, in the same console - and they do not end this program, which still removes the
        // folder.
        public static void OutliveCtrlC()
        {
            outliveCtrlC = true;
        }

        public static bool Now
        {
            get { return Interlocked.Read(ref closedAt) >= 0; }
        }

        // Milliseconds left of the grace since the window was closed.
        public static int Left()
        {
            long at = Interlocked.Read(ref closedAt);
            return at < 0 ? Grace : (int)Math.Max(0, Grace - (clock.ElapsedMilliseconds - at));
        }

        public static void Done()
        {
            cleaned.Set();
        }

        static bool Heard(uint type)
        {
            if (type == CTRL_C_EVENT || type == CTRL_BREAK_EVENT)
            {
                // True is answered: Windows does not end the program. False goes on to Windows' own handler.
                return outliveCtrlC;
            }
            if (type != CTRL_CLOSE_EVENT && type != CTRL_LOGOFF_EVENT && type != CTRL_SHUTDOWN_EVENT)
            {
                return false;
            }
            Interlocked.CompareExchange(ref closedAt, clock.ElapsedMilliseconds, -1);
            cleaned.WaitOne(Left());
            // Then on to Windows' own handler, which ends the program as it always would have.
            return false;
        }
    }

    // The console: what this program says, and whether it has to wait before the window closes. A double-click
    // gives a console program a window of its own that closes the moment it ends, so a message it stops with
    // waits for Enter there - and only there: in a console someone else opened, or for a test, it does not.
    internal static class Say
    {
        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        static extern uint GetConsoleProcessList([Out] uint[] processes, uint count);

        public static void Line(string text)
        {
            Console.Out.WriteLine(text);
        }

        public static void Raw(string text)
        {
            byte[] bytes = new UTF8Encoding(false).GetBytes(text);
            using (Stream output = Console.OpenStandardOutput())
            {
                output.Write(bytes, 0, bytes.Length);
            }
        }

        public static int Stopped(int code, string text, bool wait)
        {
            Console.Error.WriteLine(text);
            if (wait && GetConsoleProcessList(new uint[2], 2) == 1)
            {
                Console.Error.WriteLine("Press Enter to close this window.");
                Console.In.ReadLine();
            }
            return code;
        }
    }

    internal static class Json
    {
        public static string Array(List<string> values)
        {
            StringBuilder text = new StringBuilder("[");
            for (int i = 0; i < values.Count; i++)
            {
                text.Append(i == 0 ? "\"" : ",\"");
                foreach (char c in values[i])
                {
                    if (c == '"' || c == '\\')
                    {
                        text.Append('\\').Append(c);
                    }
                    else if (c < ' ')
                    {
                        text.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        text.Append(c);
                    }
                }
                text.Append('"');
            }
            return text.Append(']').ToString();
        }
    }
}

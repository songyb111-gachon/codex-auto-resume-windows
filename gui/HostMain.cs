// The watcher host's entry (v0.6.27, P6-DESIGN 1.4, 1.6, 1.8; seat S6.2b): CodexAutoResume.exe, one process that
// loads the core's DLL and draws the surfaces. It decides nothing about recovery, reads no state and starts no process:
// everything the watcher does is the core's, reached through the six exports (HostCore.cs).
//
// Main does only this:
//   1. the render and probe modes first (S6.3's SurfaceRender: a picture job or a probe answers, and no DLL is loaded);
//   2. SetDefaultDllDirectories(SYSTEM32), then LoadLibraryExW(<own folder>\the core's DLL) by its full path, before any
//      DllImport resolves - the imports bind to that module, so no copy in the current directory or on PATH is ever
//      loaded. A load that fails leaves the launcher's trace (errors.log and launcher.log) and ends with 1;
//   3. car_start({"argv", "home", "image"}): a reply whose "abi" is not 1, or that is not "ok", ends with 1 and one
//      launcher.log line;
//   4. the STA message loop (GetMessageW/TranslateMessage/DispatchMessageW, as the reference's icon thread runs it)
//      until the core's "ended", then the process ends with its exit_code. The pump (HostPump.cs) pulls the events on
//      an MTA thread and posts one WM_APP message per event to a message-only window of this thread; the events are
//      handed to the surfaces here, on the thread that owns every window.
//
// The host uses no WinForms message loop. Its manifest declares no DPI awareness (gui/host.manifest):
// the surfaces switch their own calls to Per-Monitor-v2 inside a scope, as pythonw.exe's did.

using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

// The core's imports are looked for beside this program and in the system folder only, never the current directory or
// PATH (Main has already loaded <own folder>\the core's DLL by its full path before the first one resolves).
[assembly: DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory | DllImportSearchPath.System32)]

namespace CodexAutoResume
{
    internal static class HostMain
    {
        /// runtime/loop.py EXIT_ERROR: the host could not run the core.
        internal const int ExitError = 1;

        private const uint LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR = 0x00000100;
        private const uint LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800;
        private const int LaunchLogLines = 200;

        [DllImport("kernel32.dll", SetLastError = true, ExactSpelling = true)]
        private static extern bool SetDefaultDllDirectories(uint directoryFlags);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode, ExactSpelling = true)]
        private static extern IntPtr LoadLibraryExW(string fileName, IntPtr file, uint flags);

        // The window is kept for the process's life, and so is its procedure's delegate (as Python keeps `_proc`).
        private static HostWindow window;
        private static int exitCode = ExitError;

        [STAThread]
        private static int Main(string[] args)
        {
            int? rendered = SurfaceRender.Run();
            if (rendered.HasValue) return rendered.Value;
            int? probed = SurfaceRender.Probe(args);
            if (probed.HasValue) return probed.Value;
            string image = ImagePath();
            string folder = Path.GetDirectoryName(image);
            string home = HomeOf(args, image);
            string loadError = Load(folder);
            if (loadError != null)
            {
                Complain(home, HostCore.Dll + " could not be loaded from " + folder + " (" + loadError + "); not starting");
                return ExitError;
            }
            string reply;
            try
            {
                reply = HostCore.Start(StartRequest(args, image));
            }
            catch (Exception exc)
            {
                Note(home, "watcher host: car_start failed (" + exc.GetType().Name + "); not starting");
                return ExitError;
            }
            string refusal = Refusal(reply);
            if (refusal != null)
            {
                Note(home, "watcher host: " + refusal + "; not starting");
                return ExitError;
            }
            window = new HostWindow();
            var pump = new HostPump(window.Handle);
            window.Pump = pump;
            window.Surfaces = new HostSurfaces();
            window.Ended = code => exitCode = code;
            pump.Start();
            HostWindow.Loop();
            return exitCode;
        }

        /// This program's own full path.
        internal static string ImagePath()
        {
            return Path.GetFullPath(System.Reflection.Assembly.GetEntryAssembly().Location);
        }

        /// The installation the host runs for: `--home <home>` where given, else the folder above app\bin.
        internal static string HomeOf(string[] args, string image)
        {
            for (int i = 0; i + 1 < args.Length; i++)
            {
                if (args[i] == "--home") return args[i + 1];
            }
            string bin = Path.GetDirectoryName(image);
            string app = bin == null ? null : Path.GetDirectoryName(bin);
            string home = app == null ? null : Path.GetDirectoryName(app);
            return home ?? bin ?? ".";
        }

        /// Loads <folder>\the core's DLL by its full path, the system folder the only other place searched; null when
        /// it loaded, else why not. The default directories are set first, so nothing later searches the current
        /// directory or PATH either.
        internal static string Load(string folder)
        {
            if (!SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32))
            {
                return "SetDefaultDllDirectories error " + Marshal.GetLastWin32Error();
            }
            string path = Path.Combine(folder ?? ".", HostCore.Dll);
            if (!File.Exists(path)) return "no such file";
            IntPtr module = LoadLibraryExW(path, IntPtr.Zero, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
            if (module == IntPtr.Zero) return "LoadLibraryExW error " + Marshal.GetLastWin32Error();
            return null;
        }

        /// `{"argv": [...], "home": null, "image": <own path>}`.
        internal static string StartRequest(string[] args, string image)
        {
            var argv = new List<object>();
            foreach (string arg in args) argv.Add(arg);
            var request = new Dictionary<string, object>();
            request["argv"] = argv;
            request["home"] = null;
            request["image"] = image;
            return Json.Write(request);
        }

        /// Why a car_start reply cannot be run with (an abi other than 1, or not ok), or null.
        internal static string Refusal(string reply)
        {
            var answer = reply == null ? null : Json.Parse(reply) as Dictionary<string, object>;
            if (answer == null) return "car_start gave no reply";
            object abi;
            // The window's reader gives every JSON number as a double (gui/SurfaceJson.cs).
            if (!answer.TryGetValue("abi", out abi) || !(abi is double) || (double)abi != HostCore.Abi)
            {
                return HostCore.Dll + " speaks another contract (abi " + (abi == null ? "none" : Convert.ToString(abi)) +
                       ", the host speaks " + HostCore.Abi + ")";
            }
            object ok;
            if (!answer.TryGetValue("ok", out ok) || !(ok is bool) || !(bool)ok)
            {
                object error;
                answer.TryGetValue("error", out error);
                return "car_start refused (" + (error == null ? "no reason" : Convert.ToString(error)) + ")";
            }
            return null;
        }

        private static string Stamp()
        {
            return DateTime.Now.ToString("[yyyy-MM-dd HH:mm:ss] ", System.Globalization.CultureInfo.InvariantCulture);
        }

        /// The launcher's `_complain`: one line in errors.log (no console to say it on), and the same in launcher.log.
        internal static void Complain(string home, string reason)
        {
            try
            {
                string logs = Path.Combine(home, "logs");
                Directory.CreateDirectory(logs);
                File.AppendAllText(Path.Combine(logs, "errors.log"), Stamp() + "watcher launcher: " + reason + "\n",
                                   new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
            Note(home, "watcher launcher: " + reason);
        }

        /// The launcher's `_note`: one line in launcher.log, trimmed to its last 200.
        internal static void Note(string home, string text)
        {
            try
            {
                string logs = Path.Combine(home, "logs");
                Directory.CreateDirectory(logs);
                string path = Path.Combine(logs, "launcher.log");
                var lines = new List<string>();
                if (File.Exists(path)) lines.AddRange(File.ReadAllText(path, Encoding.UTF8).Replace("\r\n", "\n").TrimEnd('\n').Split('\n'));
                if (lines.Count == 1 && lines[0].Length == 0) lines.Clear();
                if (lines.Count > LaunchLogLines) lines.RemoveRange(0, lines.Count - LaunchLogLines);
                lines.Add(Stamp() + text);
                File.WriteAllText(path, string.Join("\n", lines) + "\n", new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }
    }
}

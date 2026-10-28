// Codex Auto Resume - whether this program runs inside another app's private view of Windows, the way out of it, and
// a window brought to the front when a person asked for it (v0.6.17).
//
// A process descended from an MSIX app - the Codex app (OpenAI.Codex), Claude desktop - writes HKCU and %APPDATA% into
// that app's private view, which Windows itself never reads (measured 2026-10-19 on Codex 26.1013 and Claude 2.42304).
// A Dashboard opened from the tray of a watcher that Codex started, or a setup program an agent inside Codex runs,
// would put the entry in Settings > Apps, the Run value, the notifications' identity, the link handler and the Start
// menu shortcut where Windows never looks. Nothing in the process itself tells: not its package (the descendants have
// none), its token, its keys' names or its job. What held in every case is a LIVE ANCESTOR WITH PACKAGE IDENTITY,
// walked parent by parent with a creation-time guard against a reused process id (Inside, Decide).
//
// Two ways out held from inside both apps: the desktop shell's own IShellDispatch2.ShellExecute, where explorer.exe
// creates the process (ShellRun), and WMI's Win32_Process.Create, where the WMI service does (WmiRun). Both are
// reached late-bound, so the builds pass csc no reference they did not pass before. The relaunched program is given
// one more argument, `--outside` (Outside), and never relaunches again.
//
// Compiled into the settings window and the setup programs alike - the [installer] group of gui/window.sources - so it
// names nothing of either.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal static class HostApp
    {
        /// The argument a relaunched program is given: it never relaunches again. Every argument parser of the
        /// Dashboard and the setup programs accepts it and otherwise ignores it.
        internal const string Outside = "--outside";

        /// How many parents the walk looks at, at most.
        internal const int MaxSteps = 32;

        /// The package family name of the app this process is inside, when it stayed inside: the check found an
        /// ancestor with package identity and the program could not get out (Relaunch). Null otherwise. What Windows
        /// would keep inside that app - Repair, an update, another version - is refused while it is set.
        internal static string StuckInside;

        /// One process as the walk sees it: its parent's id, when it was created (FILETIME; 0 when it could not be
        /// opened, which ends the walk) and its package family name (null without package identity).
        internal struct Row
        {
            internal int Parent;
            internal long Created;
            internal string Package;

            internal Row(int parent, long created, string package)
            {
                Parent = parent;
                Created = created;
                Package = package;
            }
        }

        /// The decision over a process table: the package family name of `self`, or of its nearest live ancestor
        /// that has one, or null. The walk stops - outside - where a parent is not in the table or could not be
        /// opened, where a parent was created after its child (its id was reused), on a cycle, and after MaxSteps.
        /// Pure, so a test can feed it a table of its own.
        internal static string Decide(int self, IDictionary<int, Row> table)
        {
            Row row;
            if (table == null || !table.TryGetValue(self, out row)) return null;
            if (row.Package != null) return row.Package;
            var seen = new HashSet<int>();
            seen.Add(self);
            for (int step = 0; step < MaxSteps; step++)
            {
                Row parent;
                if (!table.TryGetValue(row.Parent, out parent) || parent.Created == 0) return null;
                if (!seen.Add(row.Parent)) return null;
                if (parent.Created > row.Created) return null;
                if (parent.Package != null) return parent.Package;
                row = parent;
            }
            return null;
        }

        /// The package family name of the app this process runs inside, or null: Decide over this process and its
        /// live ancestors. Null too where Windows does not answer - the program then does what it always did.
        internal static string Inside()
        {
            try
            {
                return Decide(Process.GetCurrentProcess().Id, LiveTable());
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// The app's name for a person: the family name without its publisher hash ("OpenAI.Codex", "Claude").
        internal static string Name(string family)
        {
            if (string.IsNullOrEmpty(family)) return "";
            int cut = family.LastIndexOf('_');
            return cut > 0 ? family.Substring(0, cut) : family;
        }

        /// Whether the command line is a relaunched program's (Outside).
        internal static bool Relaunched(string[] arguments)
        {
            return arguments != null && Array.IndexOf(arguments, Outside) >= 0;
        }

        /// The command line without Outside, for the parsers that refuse what they do not know.
        internal static string[] Without(string[] arguments)
        {
            if (arguments == null) return new string[0];
            var kept = new List<string>();
            foreach (string argument in arguments) if (argument != Outside) kept.Add(argument);
            return kept.ToArray();
        }

        /// The command line a relaunch passes on: these arguments, each quoted as CommandLineToArgvW reads it back,
        /// and Outside last.
        internal static string Arguments(string[] arguments)
        {
            var line = new StringBuilder();
            foreach (string argument in Without(arguments)) line.Append(Quote(argument)).Append(' ');
            return line.Append(Outside).ToString();
        }

        internal static string Quote(string value)
        {
            var builder = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value ?? string.Empty)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '\"') builder.Append('\\', slashes * 2 + 1).Append('\"');
                else builder.Append('\\', slashes).Append(c);
                slashes = 0;
            }
            return builder.Append('\\', slashes * 2).Append('\"').ToString();
        }

        /// Starts `exe` with `arguments` outside any app's private view, its window allowed to the front: the shell
        /// route first, WMI where the shell does not answer. True once one of them started it; nothing waits for it.
        internal static bool Relaunch(string exe, string arguments, string directory)
        {
            // A program the shell or the WMI service creates may not take the foreground on its own; this one, which
            // a person just opened, may let it (the relaunched window brings itself forward, BringToFront).
            try { AllowSetForegroundWindow(AsfwAny); }
            catch (Exception) { }
            return ShellRun(exe, arguments, directory) || WmiRun(Quote(exe) + " " + arguments, directory) > 0;
        }

        // ------------------------------------------------------------------ the front
        /// Starts a window program - the Dashboard, by its full path - and lets it take the foreground, which this
        /// program, the one a person just clicked in, may give: without that it opened behind the windows already
        /// there (v0.6.16 acceptance, after Finish). The window brings itself forward as it is shown (BringToFront).
        internal static bool StartInFront(string exe, string arguments, string directory)
        {
            try
            {
                var start = new ProcessStartInfo(exe);
                if (!string.IsNullOrEmpty(arguments)) start.Arguments = arguments;
                start.UseShellExecute = false;
                start.WorkingDirectory = directory;
                using (Process started = Process.Start(start))
                {
                    try { AllowSetForegroundWindow(started.Id); }
                    catch (Exception) { /* it opens, behind */ }
                }
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// A window shown as one a person opened: normal and in front. Windows can hand a window out minimized when
        /// the program that started it ended first (the uninstall window, v0.6.16 acceptance).
        internal static void Present(Form window)
        {
            window.WindowState = FormWindowState.Normal;
            BringToFront(window);
        }

        /// Once `window` is first shown: restored when Windows handed it out minimized, and brought to the front,
        /// which the program that started it allowed (StartInFront, Relaunch). Its size and place are its own.
        internal static void BringToFront(Form window)
        {
            window.Shown += delegate
            {
                try
                {
                    if (IsIconic(window.Handle) || window.WindowState == FormWindowState.Minimized)
                    {
                        ShowWindow(window.Handle, SwRestore);
                        if (window.WindowState == FormWindowState.Minimized) window.WindowState = FormWindowState.Normal;
                    }
                    window.Activate();
                    SetForegroundWindow(window.Handle);
                }
                catch (Exception) { /* it is open, wherever Windows put it */ }
            };
        }

        // ------------------------------------------------------------------ the walk, live
        // This process and its ancestors, as far as the walk can go: each one's parent from one Toolhelp snapshot,
        // its creation time and package from a handle opened for limited query. One that cannot be opened is in the
        // table with Created 0, which ends the walk there.
        private static Dictionary<int, Row> LiveTable()
        {
            Dictionary<int, int> parents = Parents();
            var table = new Dictionary<int, Row>();
            int self = Process.GetCurrentProcess().Id;
            int id = self;
            for (int step = 0; step <= MaxSteps + 1 && !table.ContainsKey(id); step++)
            {
                int parent;
                if (!parents.TryGetValue(id, out parent)) break;
                long created;
                string package;
                Open(id, id == self, out created, out package);
                table[id] = new Row(parent, created, package);
                if (created == 0) break;
                id = parent;
            }
            return table;
        }

        private static Dictionary<int, int> Parents()
        {
            var parents = new Dictionary<int, int>();
            IntPtr snapshot = CreateToolhelp32Snapshot(Th32csSnapProcess, 0);
            if (snapshot == InvalidHandle) return parents;
            try
            {
                var entry = new ProcessEntry();
                entry.Size = (uint)Marshal.SizeOf(typeof(ProcessEntry));
                for (bool more = Process32FirstW(snapshot, ref entry); more; more = Process32NextW(snapshot, ref entry))
                    parents[(int)entry.ProcessId] = (int)entry.ParentProcessId;
            }
            finally
            {
                CloseHandle(snapshot);
            }
            return parents;
        }

        private static void Open(int id, bool self, out long created, out string package)
        {
            created = 0;
            package = null;
            IntPtr handle = OpenProcess(ProcessQueryLimitedInformation, false, id);
            if (handle == IntPtr.Zero) return;
            try
            {
                long exited, kernel, user;
                if (!GetProcessTimes(handle, out created, out exited, out kernel, out user)) created = 0;
                var name = new StringBuilder(256);
                uint length = (uint)name.Capacity;
                int answer = self ? GetCurrentPackageFamilyName(ref length, name) : GetPackageFamilyName(handle, ref length, name);
                if (answer == 0 && name.Length > 0) package = name.ToString();
            }
            catch (EntryPointNotFoundException) { /* a Windows with no packages at all */ }
            finally
            {
                CloseHandle(handle);
            }
        }

        // ------------------------------------------------------------------ the ways out
        // The desktop shell's ShellExecute: explorer.exe creates the process, outside every app's view. No process id
        // comes back. The chain is the documented one for running unelevated from an elevated process: ShellWindows
        // -> the desktop's window -> its top-level browser -> the active shell view -> its background's dispatch ->
        // Application.ShellExecute.
        private static bool ShellRun(string exe, string arguments, string directory)
        {
            try
            {
                var windows = (IShellWindows)Activator.CreateInstance(Type.GetTypeFromCLSID(ShellWindowsClass, true));
                object location = CsidlDesktop, root = Type.Missing;
                int window;
                object desktop = windows.FindWindowSW(ref location, ref root, SwcDesktop, out window, SwfoNeedDispatch);
                if (desktop == null) return false;
                Guid top = TopLevelBrowser, browserId = typeof(IShellBrowser).GUID, dispatch = DispatchId;
                var browser = (IShellBrowser)((IServiceProvider)desktop).QueryService(ref top, ref browserId);
                IShellView view = browser.QueryActiveShellView();
                object folder = view.GetItemObject(SvgioBackground, ref dispatch);
                object application = Late(folder, "Application", BindingFlags.GetProperty);
                Late(application, "ShellExecute", BindingFlags.InvokeMethod, exe, arguments, directory ?? "", "open", SwShowNormal);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // WMI's Win32_Process.Create: the WMI service creates the process, outside every app's view, in this session,
        // with the user's own environment. Its process id, or 0 where it was not created.
        internal static int WmiRun(string commandLine, string directory)
        {
            try
            {
                object locator = Activator.CreateInstance(Type.GetTypeFromProgID("WbemScripting.SWbemLocator", true));
                object services = Late(locator, "ConnectServer", BindingFlags.InvokeMethod, ".", "root\\cimv2");
                object process = Late(services, "Get", BindingFlags.InvokeMethod, "Win32_Process");
                object startup = Late(Late(services, "Get", BindingFlags.InvokeMethod, "Win32_ProcessStartup"),
                                      "SpawnInstance_", BindingFlags.InvokeMethod);
                Put(startup, "ShowWindow", SwShowNormal);
                object method = Late(Late(process, "Methods_", BindingFlags.GetProperty), "Item", BindingFlags.InvokeMethod, "Create");
                object input = Late(Late(method, "InParameters", BindingFlags.GetProperty), "SpawnInstance_", BindingFlags.InvokeMethod);
                Put(input, "CommandLine", commandLine);
                if (!string.IsNullOrEmpty(directory)) Put(input, "CurrentDirectory", directory);
                Put(input, "ProcessStartupInformation", startup);
                object output = Late(process, "ExecMethod_", BindingFlags.InvokeMethod, "Create", input);
                if (Convert.ToInt32(Got(output, "ReturnValue")) != 0) return 0;
                return Convert.ToInt32(Got(output, "ProcessId"));
            }
            catch (Exception)
            {
                return 0;
            }
        }

        private static object Late(object target, string name, BindingFlags how, params object[] arguments)
        {
            return target.GetType().InvokeMember(name, how, null, target, arguments);
        }

        private static object Property(object instance, string name)
        {
            return Late(Late(instance, "Properties_", BindingFlags.GetProperty), "Item", BindingFlags.InvokeMethod, name);
        }

        private static void Put(object instance, string name, object value)
        {
            Late(Property(instance, name), "Value", BindingFlags.SetProperty, value);
        }

        private static object Got(object instance, string name)
        {
            return Late(Property(instance, name), "Value", BindingFlags.GetProperty);
        }

        // ------------------------------------------------------------------ Windows
        private const uint Th32csSnapProcess = 0x2;
        private const uint ProcessQueryLimitedInformation = 0x1000;
        private static readonly IntPtr InvalidHandle = new IntPtr(-1);
        private const int AsfwAny = -1;
        private const int SwRestore = 9;
        private const int SwShowNormal = 1;
        private const int CsidlDesktop = 0;
        private const int SwcDesktop = 8;
        private const int SwfoNeedDispatch = 1;
        private const uint SvgioBackground = 0;
        // Windows' constants are built from their fields, as everywhere in the window (test_gui_v065_controls). Only
        // the four interface ids below stay strings: `[ComImport, Guid(...)]` takes nothing else, and this file is on
        // tests/test_repo_hygiene.py's GUID_ALLOWLIST for them.
        private static readonly Guid ShellWindowsClass =                 // CLSID_ShellWindows
            new Guid(0x9BA05972, 0xF6A8, 0x11CF, 0xA4, 0x42, 0x00, 0xA0, 0xC9, 0x0A, 0x8F, 0x39);
        private static readonly Guid TopLevelBrowser =                   // SID_STopLevelBrowser
            new Guid(0x4C96BE40, 0x915C, 0x11CF, 0x99, 0xD3, 0x00, 0xAA, 0x00, 0x4A, 0xE8, 0x37);
        private static readonly Guid DispatchId =                        // IID_IDispatch
            new Guid(0x00020400, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct ProcessEntry
        {
            internal uint Size;
            internal uint Usage;
            internal uint ProcessId;
            internal IntPtr DefaultHeapId;
            internal uint ModuleId;
            internal uint Threads;
            internal uint ParentProcessId;
            internal int PriorityClassBase;
            internal uint Flags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] internal string ExeFile;
        }

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint process);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool Process32FirstW(IntPtr snapshot, ref ProcessEntry entry);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool Process32NextW(IntPtr snapshot, ref ProcessEntry entry);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        private static extern IntPtr OpenProcess(uint access, bool inherit, int process);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetProcessTimes(IntPtr process, out long created, out long exited, out long kernel, out long user);

        [DllImport("kernel32.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        private static extern int GetPackageFamilyName(IntPtr process, ref uint length, StringBuilder name);

        [DllImport("kernel32.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        private static extern int GetCurrentPackageFamilyName(ref uint length, StringBuilder name);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr handle);

        [DllImport("user32.dll", ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AllowSetForegroundWindow(int process);

        [DllImport("user32.dll", ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool IsIconic(IntPtr window);

        [DllImport("user32.dll", ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ShowWindow(IntPtr window, int command);

        [DllImport("user32.dll", ExactSpelling = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetForegroundWindow(IntPtr window);

        [ComImport, Guid("85CB6900-4D95-11CF-960C-0080C7F4EE85"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
        private interface IShellWindows
        {
            [DispId(1610743816)]
            [return: MarshalAs(UnmanagedType.IDispatch)]
            object FindWindowSW([In, MarshalAs(UnmanagedType.Struct)] ref object location,
                                [In, MarshalAs(UnmanagedType.Struct)] ref object root, int windowClass, out int window,
                                int options);
        }

        [ComImport, Guid("6D5140C1-7436-11CE-8034-00AA006009FA"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IServiceProvider
        {
            [return: MarshalAs(UnmanagedType.IUnknown)]
            object QueryService(ref Guid service, ref Guid interfaceId);
        }

        [ComImport, Guid("000214E2-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellBrowser
        {
            void GetWindow(out IntPtr window);
            void ContextSensitiveHelp(bool enter);
            void InsertMenusSB(IntPtr shared, IntPtr widths);
            void SetMenuSB(IntPtr shared, IntPtr descriptor, IntPtr active);
            void RemoveMenusSB(IntPtr shared);
            void SetStatusTextSB(IntPtr text);
            void EnableModelessSB(bool enable);
            void TranslateAcceleratorSB(IntPtr message, ushort id);
            void BrowseObject(IntPtr item, uint flags);
            void GetViewStateStream(uint mode, out IntPtr stream);
            void GetControlWindow(uint id, out IntPtr window);
            void SendControlMsg(uint id, uint message, IntPtr wParam, IntPtr lParam, out IntPtr result);
            [return: MarshalAs(UnmanagedType.Interface)]
            IShellView QueryActiveShellView();
        }

        [ComImport, Guid("000214E3-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellView
        {
            void GetWindow(out IntPtr window);
            void ContextSensitiveHelp(bool enter);
            void TranslateAccelerator(IntPtr message);
            void EnableModeless(bool enable);
            void UIActivate(uint state);
            void Refresh();
            void CreateViewWindow(IntPtr previous, IntPtr settings, IntPtr browser, IntPtr rectangle, out IntPtr window);
            void DestroyViewWindow();
            void GetCurrentInfo(IntPtr settings);
            void AddPropertySheetPages(uint reserved, IntPtr add, IntPtr parameter);
            void SaveViewState();
            void SelectItem(IntPtr item, uint flags);
            [return: MarshalAs(UnmanagedType.IUnknown)]
            object GetItemObject(uint item, ref Guid interfaceId);
        }
    }
}

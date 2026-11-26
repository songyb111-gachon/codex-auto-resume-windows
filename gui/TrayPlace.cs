// Codex Auto Resume - where Windows keeps the icon, and whether the machine is saving power (v0.6.27, S6.3c).
//
// tray_place.py, ported call for call: IconPlacement (Windows' own settings for the icon say whether it is in the
// overflow flyout; Shell_NotifyIconGetRect cannot), overflow_open (the flyout's own window shown and not cloaked),
// battery_saver (GetSystemPowerStatus's SystemStatusFlag), and the path comparison (ntpath.normcase(normpath(...)),
// LCMapStringEx's invariant lower case as CPython calls it). Everything here reads: nothing writes a registry value or
// changes a Windows setting, and nothing it reads is stored or sent.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32;

namespace CodexAutoResume
{
    /// HKEY_CURRENT_USER read only, as tray_place.CurrentUserKeys reads it (a stand-in in the tests).
    internal interface ICurrentUserKeys
    {
        /// The names of a key's subkeys; throws when the key cannot be opened (winreg.OpenKey's FileNotFoundError).
        List<string> Subkeys(string path);

        /// One value of a key, or null when the key or the value is not there; any other failure throws.
        object Value(string path, string name);
    }

    internal sealed class CurrentUserKeys : ICurrentUserKeys
    {
        public List<string> Subkeys(string path)
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(path, false))
            {
                if (key == null) throw new System.IO.FileNotFoundException(path);
                return new List<string>(key.GetSubKeyNames());
            }
        }

        public object Value(string path, string name)
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(path, false))
            {
                if (key == null) return null;
                object value = key.GetValue(name, null, RegistryValueOptions.DoNotExpandEnvironmentNames);
                if (value == null) return null;
                // winreg's QueryValueEx: a REG_DWORD is an unsigned int, a REG_QWORD too; .NET gives them signed.
                RegistryValueKind kind = key.GetValueKind(name);
                if (kind == RegistryValueKind.DWord) return (double)(uint)(int)value;
                if (kind == RegistryValueKind.QWord) return (double)(ulong)(long)value;
                return value;
            }
        }
    }

    /// Whether Windows keeps this process's icon in the overflow flyout (tray_place.IconPlacement).
    internal sealed class IconPlacement
    {
        internal const string NotifyIconSettings = @"Control Panel\NotifyIconSettings";
        internal const string TrayNotify = @"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\TrayNotify";
        internal const double LookAgainS = 30.0;

        internal readonly string Executable;
        internal readonly int Uid;
        private readonly Func<double> clock;
        private readonly ICurrentUserKeys reader;
        private readonly Func<string, string> folders;
        private List<string> entries = new List<string>();
        private double? looked;

        internal IconPlacement(string executable = null, int uid = 1, ICurrentUserKeys reader = null,
                               Func<string, string> folders = null, Func<double> clock = null)
        {
            Executable = TrayPlace.SamePath(executable ?? TrayPlace.ProcessImage());
            Uid = uid;
            this.clock = clock ?? TrayPlace.Monotonic;
            this.reader = reader ?? new CurrentUserKeys();
            this.folders = folders ?? TrayPlace.KnownFolder;
        }

        /// True while Windows says the icon is in the overflow flyout, false while on the taskbar (or every icon is
        /// shown), null where Windows does not say.
        internal bool? Overflowed()
        {
            try
            {
                if (PythonEquals(reader.Value(TrayNotify, "SystemTrayChevronVisibility"), 0)) return false;
                bool? promoted = Promoted();
                if (promoted == null)
                {
                    double now = clock();
                    if (looked != null && now - looked.Value < LookAgainS) return null;
                    looked = now;
                    entries = Find();
                    promoted = Promoted();
                }
                return promoted == null ? (bool?)null : !promoted.Value;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private bool? Promoted()
        {
            bool? answer = null;
            foreach (string path in entries)
            {
                if (reader.Value(path, "ExecutablePath") == null) return null;
                answer = SurfaceMath.Truthy(reader.Value(path, "IsPromoted")) || (answer ?? false);
            }
            return answer;
        }

        private List<string> Find()
        {
            var found = new List<string>();
            foreach (string name in reader.Subkeys(NotifyIconSettings))
            {
                string path = NotifyIconSettings + "\\" + name;
                if (reader.Value(path, "IconGuid") != null || !PythonEquals(reader.Value(path, "UID"), Uid)) continue;
                var stored = reader.Value(path, "ExecutablePath") as string;
                if (stored != null && Ours(stored)) found.Add(path);
            }
            return found;
        }

        private bool Ours(string stored)
        {
            if (stored.StartsWith("{", StringComparison.Ordinal) && stored.Contains("}"))
            {
                int close = stored.IndexOf('}');
                string folder = folders(stored.Substring(0, close) + "}");
                if (folder == null) return false;
                stored = folder + stored.Substring(close + 1);
            }
            return TrayPlace.SamePath(stored) == Executable;
        }

        /// `value == number` as Python compares a registry value with an int: a number (or a bool) by its value,
        /// anything else never.
        private static bool PythonEquals(object value, int number)
        {
            if (value is double) return (double)value == number;
            if (value is bool) return ((bool)value ? 1 : 0) == number;
            if (value is int) return (int)value == number;
            return false;
        }
    }

    /// The overflow flyout's windows as tray_place.overflow_open asks for them (a stand-in in the tests).
    internal interface IOverflowWindows
    {
        IntPtr FindWindowEx(IntPtr after, string className);
        bool IsWindowVisible(IntPtr hwnd);
        /// DwmGetWindowAttribute(DWMWA_CLOAKED): its HRESULT, and the value.
        int Cloaked(IntPtr hwnd, out uint value);
    }

    internal static class TrayPlace
    {
        /// The overflow flyout's own window: Windows 11's, and Windows 10's.
        internal static readonly string[] OverflowWindows = { "TopLevelWindowForOverflowXamlIsland", "NotifyIconOverflowWindow" };
        internal const int DwmwaCloaked = 14;
        private const uint LcmapLowercase = 0x00000100;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetModuleFileNameW(IntPtr module, StringBuilder buffer, uint size);

        [DllImport("ole32.dll", CharSet = CharSet.Unicode)]
        private static extern int CLSIDFromString(string text, out Guid guid);

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SHGetKnownFolderPath(ref Guid folder, uint flags, IntPtr token, out IntPtr path);

        [DllImport("ole32.dll")]
        private static extern void CoTaskMemFree(IntPtr memory);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int LCMapStringEx(string locale, uint flags, string source, int sourceLength,
                                                [Out] char[] destination, int destinationLength, IntPtr version,
                                                IntPtr reserved, IntPtr handle);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr FindWindowExW(IntPtr parent, IntPtr after, string className, string title);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hwnd);

        [DllImport("dwmapi.dll")]
        private static extern int DwmGetWindowAttribute(IntPtr hwnd, int attribute, out uint value, int size);

        [StructLayout(LayoutKind.Sequential)]
        private struct SystemPowerStatus
        {
            internal byte ACLineStatus, BatteryFlag, BatteryLifePercent, SystemStatusFlag;
            internal uint BatteryLifeTime, BatteryFullLifeTime;
        }

        [DllImport("kernel32.dll")]
        private static extern bool GetSystemPowerStatus(out SystemPowerStatus status);

        [DllImport("kernel32.dll")]
        private static extern bool QueryPerformanceCounter(out long count);

        [DllImport("kernel32.dll")]
        private static extern bool QueryPerformanceFrequency(out long frequency);

        /// time.monotonic.
        internal static double Monotonic()
        {
            long count, frequency;
            QueryPerformanceCounter(out count);
            QueryPerformanceFrequency(out frequency);
            return (double)count / frequency;
        }

        /// This process's program, as Windows writes it in an icon's settings.
        internal static string ProcessImage()
        {
            try
            {
                var buffer = new StringBuilder(32768);
                if (GetModuleFileNameW(IntPtr.Zero, buffer, (uint)buffer.Capacity) != 0) return buffer.ToString();
            }
            catch (Exception)
            {
            }
            return System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName;
        }

        /// The folder Windows means by a known-folder GUID, or null where it will not say.
        internal static string KnownFolder(string guid)
        {
            try
            {
                Guid folder;
                if (CLSIDFromString(guid, out folder) != 0) return null;
                IntPtr path;
                if (SHGetKnownFolderPath(ref folder, 0, IntPtr.Zero, out path) != 0) return null;
                try
                {
                    return Marshal.PtrToStringUni(path);
                }
                finally
                {
                    CoTaskMemFree(path);
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// A path as it is compared: ntpath.normcase(ntpath.normpath(value)).
        internal static string SamePath(string value)
        {
            return NormCase(NormPath(value));
        }

        /// ntpath.normcase: '/' as '\', then LCMapStringEx(LOCALE_NAME_INVARIANT, LCMAP_LOWERCASE).
        internal static string NormCase(string value)
        {
            if (string.IsNullOrEmpty(value)) return value;
            string source = value.Replace('/', '\\');
            int size = LCMapStringEx("", LcmapLowercase, source, source.Length, null, 0, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (size == 0) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            var made = new char[size];
            size = LCMapStringEx("", LcmapLowercase, source, source.Length, made, size, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (size == 0) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            return new string(made, 0, size);
        }

        /// ntpath.splitroot: (drive, root, tail).
        internal static string[] SplitRoot(string path)
        {
            string normalised = path.Replace('/', '\\');
            if (normalised.StartsWith("\\", StringComparison.Ordinal))
            {
                if (normalised.Length > 1 && normalised[1] == '\\')
                {
                    int start = normalised.Length >= 8 && normalised.Substring(0, 8).ToUpperInvariant() == "\\\\?\\UNC\\" ? 8 : 2;
                    int index = start <= normalised.Length ? normalised.IndexOf('\\', start) : -1;
                    if (index == -1) return new[] { path, "", "" };
                    int second = normalised.IndexOf('\\', index + 1);
                    if (second == -1) return new[] { path, "", "" };
                    return new[] { path.Substring(0, second), path.Substring(second, 1), path.Substring(second + 1) };
                }
                return new[] { "", path.Substring(0, 1), path.Substring(1) };
            }
            if (normalised.Length > 1 && normalised[1] == ':')
            {
                if (normalised.Length > 2 && normalised[2] == '\\')
                    return new[] { path.Substring(0, 2), path.Substring(2, 1), path.Substring(3) };
                return new[] { path.Substring(0, 2), "", path.Substring(2) };
            }
            return new[] { "", "", path };
        }

        /// ntpath.normpath.
        internal static string NormPath(string path)
        {
            path = path.Replace('/', '\\');
            string[] split = SplitRoot(path);
            string prefix = split[0] + split[1];
            bool root = split[1].Length > 0;
            var parts = new List<string>(split[2].Split('\\'));
            int at = 0;
            while (at < parts.Count)
            {
                if (parts[at].Length == 0 || parts[at] == ".") parts.RemoveAt(at);
                else if (parts[at] == "..")
                {
                    if (at > 0 && parts[at - 1] != "..")
                    {
                        parts.RemoveRange(at - 1, 2);
                        at--;
                    }
                    else if (at == 0 && root) parts.RemoveAt(at);
                    else at++;
                }
                else at++;
            }
            if (prefix.Length == 0 && parts.Count == 0) parts.Add(".");
            return prefix + string.Join("\\", parts);
        }

        private sealed class LiveOverflowWindows : IOverflowWindows
        {
            public IntPtr FindWindowEx(IntPtr after, string className) { return FindWindowExW(IntPtr.Zero, after, className, null); }
            public bool IsWindowVisible(IntPtr hwnd) { return TrayPlace.IsWindowVisible(hwnd); }
            public int Cloaked(IntPtr hwnd, out uint value) { return DwmGetWindowAttribute(hwnd, DwmwaCloaked, out value, 4); }
        }

        /// True while Windows shows the overflow flyout, false while it is closed or where Windows cannot say.
        internal static bool OverflowOpen(IOverflowWindows windows = null)
        {
            windows = windows ?? new LiveOverflowWindows();
            try
            {
                foreach (string name in OverflowWindows)
                {
                    IntPtr hwnd = IntPtr.Zero;
                    int seen = 0;
                    while (seen < 16)
                    {
                        hwnd = windows.FindWindowEx(hwnd, name);
                        if (hwnd == IntPtr.Zero) break;
                        seen++;
                        if (windows.IsWindowVisible(hwnd) && !IsCloaked(windows, hwnd)) return true;
                    }
                }
                return false;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static bool IsCloaked(IOverflowWindows windows, IntPtr hwnd)
        {
            try
            {
                uint value;
                if (windows.Cloaked(hwnd, out value) != 0) return false;
                return value != 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// True while Windows' battery saver is on; false where Windows cannot say.
        internal static bool BatterySaver()
        {
            try
            {
                SystemPowerStatus status;
                if (!GetSystemPowerStatus(out status)) return false;
                return (status.SystemStatusFlag & 1) != 0;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}

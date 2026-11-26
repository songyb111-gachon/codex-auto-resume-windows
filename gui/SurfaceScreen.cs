// Codex Auto Resume - the Win32 calls by which a surface's window reaches the screen, one door for the probe mode
// (v0.6.27, S6.3d).
//
// The popup, its card layers, the icon's menu and the notification cards make these calls only through here: showing,
// placing, fading, uploading a layered picture, the focus, the timers, the messages a window posts itself, Windows' default
// procedure. On a live host `Probe` is null and every one is Windows' own call, made as the Python makes it. In the probe
// mode (P6-DESIGN 3.2) `Probe` is a list: each call is written to it in the reference's words and NOT made - the windows
// are made but never shown, never placed and never given a picture, so nothing reaches the owner's screen - and what a
// window posts itself is queued in `Posted` for the script to deliver. The reference is driven with the same calls stood
// in (tests/test_surface_windows.py), so the two records are compared call for call.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class SurfaceScreen
    {
        /// The probe's record of every call (null: a live host, every call made).
        internal static List<string> Probe = null;
        /// What a window posted itself while probed: (hwnd, message, wParam, lParam), delivered by the script.
        internal static readonly List<long[]> Posted = new List<long[]>();
        /// The name a window has in the record ("card", "shadow", "menu", ...).
        internal static Func<IntPtr, string> Name = hwnd => "0x" + hwnd.ToInt64().ToString("x", CultureInfo.InvariantCulture);
        /// What GetKeyState answers while probed, by virtual key (absent: 0).
        internal static readonly Dictionary<int, short> Keys = new Dictionary<int, short>();

        internal static bool Probing { get { return Probe != null; } }

        private static void Log(string call, params object[] values)
        {
            var parts = new List<string> { call };
            foreach (object value in values)
            {
                if (value is IntPtr) parts.Add(Name((IntPtr)value));
                else if (value is double) parts.Add(((double)value).ToString("R", CultureInfo.InvariantCulture));
                else if (value is int[]) parts.Add(value == null ? "None" : "(" + string.Join(", ", (int[])value) + ")");
                else if (value is bool) parts.Add((bool)value ? "True" : "False");
                else if (value == null) parts.Add("None");
                else parts.Add(Convert.ToString(value, CultureInfo.InvariantCulture));
            }
            Probe.Add(string.Join(" ", parts));
        }

        [DllImport("user32.dll", EntryPoint = "SetClassLongPtrW")] private static extern IntPtr SetClassLongPtrW(IntPtr hwnd, int index, IntPtr value);
        [DllImport("user32.dll", EntryPoint = "GetClassLongPtrW")] private static extern IntPtr GetClassLongPtrW(IntPtr hwnd, int index);

        internal static bool ShowWindow(IntPtr hwnd, int command)
        {
            if (!Probing) return SurfaceNative.ShowWindow(hwnd, command);
            Log("ShowWindow", hwnd, command);
            return true;
        }

        internal static bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int cx, int cy, uint flags)
        {
            if (!Probing)
                using (new SurfaceNative.PerMonitorDpi())
                    return SurfaceNative.SetWindowPos(hwnd, after, x, y, cx, cy, flags);
            Log("SetWindowPos", hwnd, x, y, cx, cy, flags);
            return true;
        }

        /// The extended styles the probe set, by window: what GetWindowLongW answers while probed (0 for any other, as
        /// Windows answers for a window that is not one).
        internal static readonly Dictionary<long, int> Styles = new Dictionary<long, int>();

        internal static int GetExStyle(IntPtr hwnd)
        {
            if (!Probing) return SurfaceNative.GetWindowLongW(hwnd, SurfaceNative.GWL_EXSTYLE);
            int style;
            return Styles.TryGetValue(hwnd.ToInt64(), out style) ? style : 0;
        }

        internal static void SetExStyle(IntPtr hwnd, int style)
        {
            if (!Probing)
            {
                SurfaceNative.SetWindowLongW(hwnd, SurfaceNative.GWL_EXSTYLE, style);
                return;
            }
            Log("SetWindowLongW", hwnd, style);
            Styles[hwnd.ToInt64()] = style;
        }

        /// The window that has the foreground: while probed, the last one the probe gave it to (Foreground).
        internal static IntPtr Foreground = IntPtr.Zero;
        /// Whether the probe's Windows grants the foreground when asked (false: as Windows refuses a window it).
        internal static bool Grant = true;

        internal static IntPtr GetForegroundWindow()
        {
            return Probing ? Foreground : SurfaceNative.GetForegroundWindow();
        }

        /// UpdateLayeredWindow: the picture in `dc`, `size` px from (0, 0), at `at`, `alpha` opaque (the menu's and the
        /// tip's blit).
        internal static bool UpdateLayered(IntPtr hwnd, int[] at, int[] size, IntPtr dc, int alpha)
        {
            if (Probing)
            {
                Log("UpdateLayeredWindow", hwnd, at[0], at[1], size[0], size[1], alpha);
                return true;
            }
            var blend = new SurfaceNative.BLENDFUNCTION { BlendOp = 0, BlendFlags = 0, SourceConstantAlpha = (byte)alpha,
                                                          AlphaFormat = SurfaceNative.AC_SRC_ALPHA };
            var where = new SurfaceNative.POINT { X = at[0], Y = at[1] };
            var extent = new SurfaceNative.SIZE { Cx = size[0], Cy = size[1] };
            var source = new SurfaceNative.POINT();
            using (new SurfaceNative.PerMonitorDpi())
                return SurfaceNative.UpdateLayeredWindow(hwnd, IntPtr.Zero, ref where, ref extent, dc, ref source, 0, ref blend,
                                                         SurfaceNative.ULW_ALPHA);
        }

        internal static bool SetLayeredAlpha(IntPtr hwnd, int alpha)
        {
            if (!Probing) return SurfaceNative.SetLayeredWindowAttributes(hwnd, 0, (byte)alpha, SurfaceNative.LWA_ALPHA);
            Log("SetLayeredWindowAttributes", hwnd, alpha);
            return true;
        }

        internal static void SetForegroundWindow(IntPtr hwnd)
        {
            if (!Probing) SurfaceNative.SetForegroundWindow(hwnd);
            else
            {
                Log("SetForegroundWindow", hwnd);
                if (Grant) Foreground = hwnd;
            }
        }

        internal static void SetFocus(IntPtr hwnd)
        {
            if (!Probing) SurfaceNative.SetFocus(hwnd);
            else Log("SetFocus", hwnd);
        }

        internal static void InvalidateRect(IntPtr hwnd)
        {
            if (!Probing) SurfaceNative.InvalidateRect(hwnd, IntPtr.Zero, false);
            else Log("InvalidateRect", hwnd);
        }

        internal static void UpdateWindow(IntPtr hwnd)
        {
            if (!Probing) SurfaceNative.UpdateWindow(hwnd);
            else Log("UpdateWindow", hwnd);
        }

        internal static void SetTimer(IntPtr hwnd, int id, int ms)
        {
            if (!Probing) SurfaceNative.SetTimer(hwnd, new UIntPtr((uint)id), (uint)ms, IntPtr.Zero);
            else Log("SetTimer", hwnd, id, ms);
        }

        internal static void KillTimer(IntPtr hwnd, int id)
        {
            if (!Probing) SurfaceNative.KillTimer(hwnd, new UIntPtr((uint)id));
            else Log("KillTimer", hwnd, id);
        }

        internal static void Post(IntPtr hwnd, int message, long wParam, long lParam)
        {
            if (!Probing)
            {
                SurfaceNative.PostMessageW(hwnd, (uint)message, new IntPtr(wParam), new IntPtr(lParam));
                return;
            }
            Log("PostMessageW", hwnd, message, wParam, lParam);
            Posted.Add(new[] { hwnd.ToInt64(), message, wParam, lParam });
        }

        /// Windows' default procedure: always Windows' own, probed or not - a window is made through it (WM_NCCREATE), and
        /// for a hidden window it shows nothing.
        internal static IntPtr DefWindowProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam)
        {
            return SurfaceNative.DefWindowProcW(hwnd, message, wParam, lParam);
        }

        /// layers.update: UpdateLayeredWindowIndirect with the picture in `dc`, its `size` from `source`, at `at`, `alpha`
        /// opaque, only `dirty` when given (SurfaceLayers.Update).
        internal static bool Update(IntPtr hwnd, double[] at, double alpha, IntPtr dc, int[] size, int[] source, int[] dirty)
        {
            if (!Probing) return SurfaceLayers.UpdateNow(hwnd, at, alpha, dc, size, source, dirty);
            Log("update", hwnd, "(" + Number(at[0]) + ", " + Number(at[1]) + ")", Number(alpha), size, source, dirty);
            return true;
        }

        /// A number as Python's repr writes it in the record: an int as an int.
        private static string Number(double value)
        {
            return value == Math.Floor(value) && Math.Abs(value) < 1e15
                ? ((long)value).ToString(CultureInfo.InvariantCulture) : value.ToString("R", CultureInfo.InvariantCulture);
        }

        internal static bool TrackMouseLeave(IntPtr hwnd)
        {
            if (Probing)
            {
                Log("TrackMouseEvent", hwnd);
                return true;
            }
            var track = new SurfaceNative.TRACKMOUSEEVENT { DwFlags = SurfaceNative.TME_LEAVE, HwndTrack = hwnd };
            track.CbSize = (uint)Marshal.SizeOf(track);
            return SurfaceNative.TrackMouseEvent(ref track);
        }

        internal static short KeyState(int key)
        {
            if (!Probing) return SurfaceNative.GetKeyState(key);
            short state;
            return Keys.TryGetValue(key, out state) ? state : (short)0;
        }

        internal static void ClientToScreen(IntPtr hwnd, ref SurfaceNative.POINT point)
        {
            if (!Probing) SurfaceNative.ClientToScreen(hwnd, ref point);
        }

        internal static void ScreenToClient(IntPtr hwnd, ref SurfaceNative.POINT point)
        {
            if (!Probing) SurfaceNative.ScreenToClient(hwnd, ref point);
        }

        internal static uint DpiForWindow(IntPtr hwnd)
        {
            if (Probing) return 0;
            try
            {
                return SurfaceNative.GetDpiForWindow(hwnd);
            }
            catch (EntryPointNotFoundException)
            {
                return 0;
            }
        }

        /// DwmSetWindowAttribute with one int: 0 (S_OK) when Windows took it.
        internal static int Dwm(IntPtr hwnd, int attribute, int value)
        {
            if (Probing)
            {
                Log("DwmSetWindowAttribute", hwnd, attribute, value);
                return 0;
            }
            return SurfaceNative.DwmSetWindowAttribute(hwnd, attribute, ref value, 4);
        }

        /// The plain window's round region, `radius` across its corners (_shape): the region kept by Windows or deleted.
        internal static void RoundRegion(IntPtr hwnd, int width, int height, int radius)
        {
            if (Probing)
            {
                Log("SetWindowRgn", hwnd, width, height, radius);
                return;
            }
            IntPtr region = SurfaceNative.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius);
            if (region != IntPtr.Zero && SurfaceNative.SetWindowRgn(hwnd, region, true) == 0) SurfaceNative.DeleteObject(region);
        }

        /// The class's style with `bits` added (_class_shadow: CS_DROPSHADOW).
        internal static void AddClassStyle(IntPtr hwnd, uint bits)
        {
            const int GCL_STYLE = -26;
            if (Probing)
            {
                Log("SetClassLongPtrW", hwnd, bits);
                return;
            }
            SetClassLongPtrW(hwnd, GCL_STYLE, new IntPtr(GetClassLongPtrW(hwnd, GCL_STYLE).ToInt64() | bits));
        }
    }
}

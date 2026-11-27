// Codex Auto Resume - the Win32 the surfaces call: the numbers, the structures and the declarations (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/win32.py (and the few calls ui/tray/win32.py and ui/card/win32.py add):
// the same entry points of the same user32.dll, gdi32.dll, shell32.dll and shcore.dll, with the same argument types the
// Python's one declaration pass gives them (Q8: the same calls, so the same pixels). Every handle is an IntPtr, as the
// Python declares every handle a pointer so that a 64-bit handle is never cut in half. The flat GDI+ calls are in
// SurfaceGdip.cs.
//
// The host declares no DPI awareness of its own (P6-DESIGN 1.4: pythonw.exe is DPI-unaware, and so is the host); the
// surfaces switch their own thread to Per-Monitor-v2 inside a scope, PerMonitorDpi, as _PerMonitorDpi does.
using System;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class SurfaceNative
    {
        // ---------------------------------------------------------------------------------- messages
        internal const int WM_ACTIVATE = 0x0006, WM_PAINT = 0x000F, WM_CLOSE = 0x0010, WM_ERASEBKGND = 0x0014;
        internal const int WM_SYSCOLORCHANGE = 0x0015, WM_SETTINGCHANGE = 0x001A, WM_KEYDOWN = 0x0100, WM_TIMER = 0x0113;
        internal const int WM_MOUSEMOVE = 0x0200, WM_LBUTTONDOWN = 0x0201, WM_LBUTTONUP = 0x0202, WM_MOUSELEAVE = 0x02A3;
        internal const int WM_DPICHANGED = 0x02E0;
        internal const int WM_CONTEXTMENU = 0x007B;
        internal const int WM_GETOBJECT = 0x003D;
        internal const int WM_APP = 0x8000;
        internal const int WM_POPUP_RESULT = WM_APP + 2, WM_POPUP_STRINGS = WM_APP + 3;
        internal const int WA_INACTIVE = 0;

        internal const uint MF_STRING = 0x0, MF_GRAYED = 0x1, MF_CHECKED = 0x8, MF_POPUP = 0x10, MF_SEPARATOR = 0x800;
        internal const uint TPM_RIGHTBUTTON = 0x2, TPM_RETURNCMD = 0x100, TPM_NONOTIFY = 0x80;
        internal const uint TPM_RIGHTALIGN = 0x8, TPM_LAYOUTRTL = 0x8000;

        internal const int VK_TAB = 0x09, VK_RETURN = 0x0D, VK_SHIFT = 0x10, VK_ESCAPE = 0x1B, VK_SPACE = 0x20;
        internal const int VK_UP = 0x26, VK_DOWN = 0x28;
        internal const long KEY_WAS_DOWN = 1L << 30;

        // ---------------------------------------------------------------------------------- windows
        internal const uint WS_POPUP = 0x80000000;
        internal const uint WS_EX_TOPMOST = 0x00000008, WS_EX_TOOLWINDOW = 0x00000080;
        internal const uint WS_EX_LAYERED = 0x00080000, WS_EX_NOACTIVATE = 0x08000000;
        internal const uint CS_DROPSHADOW = 0x00020000;
        internal const int SW_HIDE = 0, SW_SHOWNOACTIVATE = 4, SW_SHOW = 5;
        internal const uint SWP_NOSIZE = 0x0001, SWP_NOZORDER = 0x0004, SWP_NOACTIVATE = 0x0010;
        internal const int GWL_EXSTYLE = -20;
        internal const uint LWA_ALPHA = 0x2;
        internal static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
        internal const int IDC_ARROW = 32512;
        internal const uint MONITOR_DEFAULTTONEAREST = 2;
        internal const uint TME_LEAVE = 0x2;
        internal const uint ULW_ALPHA = 0x2;
        internal const byte AC_SRC_OVER = 0, AC_SRC_ALPHA = 1;

        // ---------------------------------------------------------------------------------- Windows' settings
        internal const uint SPI_GETCLIENTAREAANIMATION = 0x1042;
        internal const uint SPI_GETHIGHCONTRAST = 0x0042, HCF_HIGHCONTRASTON = 0x1;
        internal const int DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2;
        internal const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19;
        internal static readonly UIntPtr HKEY_CURRENT_USER = new UIntPtr(0x80000001u);
        internal const uint RRF_RT_REG_DWORD = 0x00000010;
        internal static readonly IntPtr DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = new IntPtr(-4);

        // ---------------------------------------------------------------------------------- text
        internal const uint DT_CENTER = 0x1, DT_VCENTER = 0x4, DT_WORDBREAK = 0x10, DT_SINGLELINE = 0x20;
        internal const uint DT_CALCRECT = 0x400, DT_NOPREFIX = 0x800, DT_EDITCONTROL = 0x2000, DT_END_ELLIPSIS = 0x8000;
        internal const uint DT_RIGHT = 0x2, DT_RTLREADING = 0x20000;
        internal const int TRANSPARENT = 1;

        internal const int TIMER_TICK = 1, TIMER_FRAME = 2, TIMER_FIRST = 3;
        internal const uint GR_GDIOBJECTS = 0, GR_USEROBJECTS = 1;
        internal const int UNIT_PIXEL = 2, INTERPOLATION_NEAREST = 5;

        /// (red, green, blue) and an alpha as the ARGB number GDI+ takes (_pack): the alpha rounded half to even, as
        /// Python's round is, and held to 0-255.
        internal static uint Pack(int red, int green, int blue, double alpha = 1.0)
        {
            int a = Math.Max(0, Math.Min(255, (int)Math.Round(alpha * 255, MidpointRounding.ToEven)));
            return ((uint)a << 24) | ((uint)red << 16) | ((uint)green << 8) | (uint)blue;
        }

        // ---------------------------------------------------------------------------------- structures
        [StructLayout(LayoutKind.Sequential)]
        internal struct POINT { internal int X, Y; }

        [StructLayout(LayoutKind.Sequential)]
        internal struct SIZE { internal int Cx, Cy; }

        [StructLayout(LayoutKind.Sequential)]
        internal struct RECT
        {
            internal int Left, Top, Right, Bottom;
            internal RECT(int left, int top, int right, int bottom) { Left = left; Top = top; Right = right; Bottom = bottom; }
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct MONITORINFO
        {
            internal uint CbSize;
            internal RECT RcMonitor, RcWork;
            internal uint DwFlags;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct PAINTSTRUCT
        {
            internal IntPtr Hdc;
            internal int FErase;
            internal RECT RcPaint;
            internal int FRestore, FIncUpdate;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] internal byte[] RgbReserved;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct TRACKMOUSEEVENT
        {
            internal uint CbSize, DwFlags;
            internal IntPtr HwndTrack;
            internal uint DwHoverTime;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct BITMAPINFOHEADER
        {
            internal uint BiSize;
            internal int BiWidth, BiHeight;
            internal ushort BiPlanes, BiBitCount;
            internal uint BiCompression, BiSizeImage;
            internal int BiXPelsPerMeter, BiYPelsPerMeter;
            internal uint BiClrUsed, BiClrImportant;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct BITMAPINFO
        {
            internal BITMAPINFOHEADER BmiHeader;
            internal uint Colour0, Colour1, Colour2;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct ICONINFO
        {
            internal int FIcon;
            internal uint XHotspot, YHotspot;
            internal IntPtr HbmMask, HbmColor;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct NOTIFYICONIDENTIFIER
        {
            internal uint CbSize;
            internal IntPtr HWnd;
            internal uint UID;
            internal Guid GuidItem;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        internal struct HIGHCONTRASTW
        {
            internal uint CbSize, DwFlags;
            internal IntPtr LpszDefaultScheme;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct BLENDFUNCTION
        {
            internal byte BlendOp, BlendFlags, SourceConstantAlpha, AlphaFormat;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        internal struct TEXTMETRICW
        {
            internal int TmHeight, TmAscent, TmDescent, TmInternalLeading, TmExternalLeading, TmAveCharWidth,
                         TmMaxCharWidth, TmWeight, TmOverhang, TmDigitizedAspectX, TmDigitizedAspectY;
            internal char TmFirstChar, TmLastChar, TmDefaultChar, TmBreakChar;
            internal byte TmItalic, TmUnderlined, TmStruckOut, TmPitchAndFamily, TmCharSet;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct GLYPHMETRICS
        {
            internal uint GmBlackBoxX, GmBlackBoxY;
            internal POINT GmptGlyphOrigin;
            internal short GmCellIncX, GmCellIncY;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct FIXED { internal ushort Fract; internal short Value; }

        [StructLayout(LayoutKind.Sequential)]
        internal struct MAT2 { internal FIXED EM11, EM12, EM21, EM22; }

        internal const uint GGO_METRICS = 0, GDI_ERROR = 0xFFFFFFFF;

        /// A window procedure, kept in a field for the window's whole life (the Python keeps its _proc).
        [UnmanagedFunctionPointer(CallingConvention.Winapi)]
        internal delegate IntPtr WndProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        internal struct WNDCLASSW
        {
            internal uint Style;
            internal WndProc LpfnWndProc;
            internal int CbClsExtra, CbWndExtra;
            internal IntPtr HInstance, HIcon, HCursor, HbrBackground;
            internal string LpszMenuName, LpszClassName;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct MSG
        {
            internal IntPtr Hwnd;
            internal uint Message;
            internal IntPtr WParam, LParam;
            internal uint Time;
            internal POINT Pt;
        }

        // ---------------------------------------------------------------------------------- user32
        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        internal static extern IntPtr CreateWindowExW(uint exStyle, string className, string windowName, uint style,
                                                      int x, int y, int width, int height, IntPtr parent, IntPtr menu,
                                                      IntPtr instance, IntPtr param);
        [DllImport("user32.dll")] internal static extern IntPtr DefWindowProcW(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern ushort RegisterClassW(ref WNDCLASSW cls);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern bool UnregisterClassW(string name, IntPtr instance);
        [DllImport("user32.dll")] internal static extern bool DestroyWindow(IntPtr hwnd);
        [DllImport("user32.dll")] internal static extern bool ShowWindow(IntPtr hwnd, int command);
        [DllImport("user32.dll")] internal static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
        [DllImport("user32.dll")] internal static extern int GetWindowLongW(IntPtr hwnd, int index);
        [DllImport("user32.dll")] internal static extern int SetWindowLongW(IntPtr hwnd, int index, int value);
        [DllImport("user32.dll")] internal static extern bool SetLayeredWindowAttributes(IntPtr hwnd, uint key, byte alpha, uint flags);
        [DllImport("user32.dll")]
        internal static extern bool UpdateLayeredWindow(IntPtr hwnd, IntPtr screen, ref POINT destination, ref SIZE size,
                                                        IntPtr source, ref POINT sourcePoint, uint key, ref BLENDFUNCTION blend,
                                                        uint flags);
        [DllImport("user32.dll")] internal static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] internal static extern bool SetForegroundWindow(IntPtr hwnd);
        [DllImport("user32.dll")] internal static extern IntPtr SetFocus(IntPtr hwnd);
        [DllImport("user32.dll")] internal static extern bool InvalidateRect(IntPtr hwnd, IntPtr rect, bool erase);
        [DllImport("user32.dll")] internal static extern bool UpdateWindow(IntPtr hwnd);
        [DllImport("user32.dll")] internal static extern IntPtr BeginPaint(IntPtr hwnd, out PAINTSTRUCT paint);
        [DllImport("user32.dll")] internal static extern bool EndPaint(IntPtr hwnd, ref PAINTSTRUCT paint);
        [DllImport("user32.dll")] internal static extern UIntPtr SetTimer(IntPtr hwnd, UIntPtr id, uint ms, IntPtr proc);
        [DllImport("user32.dll")] internal static extern bool KillTimer(IntPtr hwnd, UIntPtr id);
        [DllImport("user32.dll")] internal static extern bool PostMessageW(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")] internal static extern bool GetCursorPos(out POINT point);
        [DllImport("user32.dll")] internal static extern bool ScreenToClient(IntPtr hwnd, ref POINT point);
        [DllImport("user32.dll")] internal static extern bool ClientToScreen(IntPtr hwnd, ref POINT point);
        [DllImport("user32.dll")] internal static extern IntPtr CreatePopupMenu();
        [DllImport("user32.dll")] internal static extern bool DestroyMenu(IntPtr menu);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern bool AppendMenuW(IntPtr menu, uint flags, UIntPtr id, string text);
        [DllImport("user32.dll")] internal static extern int TrackPopupMenu(IntPtr menu, uint flags, int x, int y, int reserved, IntPtr hwnd, IntPtr rect);
        [DllImport("user32.dll")] internal static extern IntPtr MonitorFromRect(ref RECT rect, uint flags);
        [DllImport("user32.dll")] internal static extern bool GetMonitorInfoW(IntPtr monitor, ref MONITORINFO info);
        [DllImport("user32.dll", EntryPoint = "SystemParametersInfoW")]
        internal static extern bool SystemParametersInfoBool(uint action, uint param, ref int value, uint winIni);
        [DllImport("user32.dll", EntryPoint = "SystemParametersInfoW")]
        internal static extern bool SystemParametersInfoContrast(uint action, uint param, ref HIGHCONTRASTW value, uint winIni);
        [DllImport("user32.dll")] internal static extern short GetKeyState(int key);
        [DllImport("user32.dll")] internal static extern bool TrackMouseEvent(ref TRACKMOUSEEVENT track);
        [DllImport("user32.dll")] internal static extern IntPtr LoadCursorW(IntPtr instance, IntPtr name);
        [DllImport("user32.dll")] internal static extern int SetWindowRgn(IntPtr hwnd, IntPtr region, bool redraw);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        internal static extern int DrawTextW(IntPtr dc, string text, int count, ref RECT rect, uint format);
        [DllImport("user32.dll")] internal static extern bool GetIconInfo(IntPtr icon, out ICONINFO info);
        [DllImport("user32.dll")] internal static extern IntPtr CreateIconIndirect(ref ICONINFO info);
        [DllImport("user32.dll")] internal static extern bool DestroyIcon(IntPtr icon);
        [DllImport("user32.dll")] internal static extern uint GetGuiResources(IntPtr process, uint flags);
        [DllImport("user32.dll")] internal static extern uint GetSysColor(int index);
        [DllImport("user32.dll")] internal static extern uint GetDpiForWindow(IntPtr hwnd);
        [DllImport("user32.dll")] internal static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
        [DllImport("user32.dll")] internal static extern int GetMessageW(out MSG message, IntPtr hwnd, uint min, uint max);
        [DllImport("user32.dll")] internal static extern bool TranslateMessage(ref MSG message);
        [DllImport("user32.dll")] internal static extern IntPtr DispatchMessageW(ref MSG message);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern uint RegisterWindowMessageW(string name);

        // ---------------------------------------------------------------------------------- gdi32
        [DllImport("gdi32.dll")] internal static extern IntPtr CreateCompatibleDC(IntPtr dc);
        [DllImport("gdi32.dll")] internal static extern bool DeleteDC(IntPtr dc);
        [DllImport("gdi32.dll")]
        internal static extern IntPtr CreateDIBSection(IntPtr dc, ref BITMAPINFO info, uint usage, out IntPtr bits,
                                                       IntPtr section, uint offset);
        [DllImport("gdi32.dll")] internal static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);
        [DllImport("gdi32.dll")] internal static extern bool DeleteObject(IntPtr obj);
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        internal static extern IntPtr CreateFontW(int height, int width, int escapement, int orientation, int weight,
                                                  uint italic, uint underline, uint strikeOut, uint charSet,
                                                  uint outPrecision, uint clipPrecision, uint quality,
                                                  uint pitchAndFamily, string face);
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        internal static extern int GetTextFaceW(IntPtr dc, int count, [Out] char[] face);
        [DllImport("gdi32.dll")] internal static extern uint SetTextColor(IntPtr dc, uint colour);
        [DllImport("gdi32.dll")] internal static extern int SetBkMode(IntPtr dc, int mode);
        [DllImport("gdi32.dll")] internal static extern IntPtr CreateRoundRectRgn(int left, int top, int right, int bottom, int w, int h);
        [DllImport("gdi32.dll")] internal static extern IntPtr CreateBitmap(int width, int height, uint planes, uint bits, byte[] data);
        [DllImport("gdi32.dll")] internal static extern bool GdiFlush();
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)] internal static extern bool GetTextMetricsW(IntPtr dc, out TEXTMETRICW metrics);
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        internal static extern uint GetGlyphOutlineW(IntPtr dc, uint character, uint format, out GLYPHMETRICS metrics,
                                                     uint size, IntPtr buffer, ref MAT2 matrix);

        // ---------------------------------------------------------------------------------- the rest
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] internal static extern IntPtr GetModuleHandleW(string name);
        [DllImport("kernel32.dll")] internal static extern IntPtr GetCurrentProcess();
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
        internal static extern int RegGetValueW(UIntPtr key, string subKey, string value, uint flags, IntPtr type,
                                                ref uint data, ref uint size);
        [DllImport("shcore.dll")] internal static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint x, out uint y);
        [DllImport("shell32.dll")] internal static extern int Shell_NotifyIconGetRect(ref NOTIFYICONIDENTIFIER identifier, out RECT rect);
        [DllImport("dwmapi.dll")] internal static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

        /// Per-monitor-v2 coordinates for this thread while the scope lasts, restored after (_PerMonitorDpi). Where
        /// Windows has no SetThreadDpiAwarenessContext (before Windows 10 1607) it does nothing, as the Python's getattr does.
        internal sealed class PerMonitorDpi : IDisposable
        {
            private readonly IntPtr previous;

            internal PerMonitorDpi()
            {
                try { previous = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2); }
                catch (EntryPointNotFoundException) { previous = IntPtr.Zero; }
            }

            public void Dispose()
            {
                if (previous == IntPtr.Zero) return;
                try { SetThreadDpiAwarenessContext(previous); }
                catch (EntryPointNotFoundException) { }
            }
        }

        /// Where the drawn menu opens (screen_at): the pointer (or `at`), the work area of the monitor it is on and that
        /// monitor's DPI (96 where Windows does not say), in physical pixels.
        internal static void ScreenAt(int[] at, out int[] cursor, out int dpi, out int[] work)
        {
            var info = new MONITORINFO();
            POINT point;
            using (new PerMonitorDpi())
            {
                if (at == null) GetCursorPos(out point);
                else { point.X = at[0]; point.Y = at[1]; }
                var probe = new RECT(point.X, point.Y, point.X + 1, point.Y + 1);
                IntPtr monitor = MonitorFromRect(ref probe, MONITOR_DEFAULTTONEAREST);
                info.CbSize = (uint)Marshal.SizeOf(typeof(MONITORINFO));
                GetMonitorInfoW(monitor, ref info);
                dpi = 0;
                try
                {
                    uint x, y;
                    if (GetDpiForMonitor(monitor, 0, out x, out y) == 0) dpi = (int)x;
                }
                catch (Exception) { dpi = 0; }
            }
            if (dpi == 0) dpi = 96;
            cursor = new[] { point.X, point.Y };
            work = new[] { info.RcWork.Left, info.RcWork.Top, info.RcWork.Right, info.RcWork.Bottom };
        }

        /// (GDI objects, USER objects) this process holds, for the leak tests (gui_resources).
        internal static uint[] GuiResources()
        {
            IntPtr process = GetCurrentProcess();
            return new[] { GetGuiResources(process, GR_GDIOBJECTS), GetGuiResources(process, GR_USEROBJECTS) };
        }

        /// The icon's rectangle on screen, or null - in the overflow flyout, or not yet placed (icon_rect).
        internal static int[] IconRect(IntPtr hwnd, uint uid = 1)
        {
            try
            {
                var identifier = new NOTIFYICONIDENTIFIER();
                identifier.CbSize = (uint)Marshal.SizeOf(typeof(NOTIFYICONIDENTIFIER));
                identifier.HWnd = hwnd;
                identifier.UID = uid;
                RECT rect;
                if (Shell_NotifyIconGetRect(ref identifier, out rect) != 0) return null;
                if (rect.Right <= rect.Left || rect.Bottom <= rect.Top) return null;
                return new[] { rect.Left, rect.Top, rect.Right, rect.Bottom };
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// A top-down 32-bit DIB's header (_bitmap_info).
        internal static BITMAPINFO BitmapInfo(int width, int height)
        {
            var info = new BITMAPINFO();
            info.BmiHeader.BiSize = (uint)Marshal.SizeOf(typeof(BITMAPINFOHEADER));
            info.BmiHeader.BiWidth = width;
            info.BmiHeader.BiHeight = -height;
            info.BmiHeader.BiPlanes = 1;
            info.BmiHeader.BiBitCount = 32;
            return info;
        }

        /// An icon from top-down BGRA pixels with straight alpha (_icon_from_pixels), or IntPtr.Zero; the caller
        /// destroys it.
        internal static IntPtr IconFromPixels(byte[] pixels, int width, int height)
        {
            IntPtr bits;
            BITMAPINFO info = BitmapInfo(width, height);
            IntPtr colour = CreateDIBSection(IntPtr.Zero, ref info, 0, out bits, IntPtr.Zero, 0);
            if (colour == IntPtr.Zero) return IntPtr.Zero;
            int rows = ((width + 15) / 16) * 2;
            IntPtr mask = CreateBitmap(width, height, 1, 1, new byte[rows * height]);
            try
            {
                if (mask == IntPtr.Zero) return IntPtr.Zero;
                Marshal.Copy(pixels, 0, bits, pixels.Length);
                var iconInfo = new ICONINFO();
                iconInfo.FIcon = 1;
                iconInfo.HbmMask = mask;
                iconInfo.HbmColor = colour;
                return CreateIconIndirect(ref iconInfo);
            }
            finally
            {
                DeleteObject(colour);
                if (mask != IntPtr.Zero) DeleteObject(mask);
            }
        }
    }
}

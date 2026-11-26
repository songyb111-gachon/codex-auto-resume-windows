// Codex Auto Resume - the icon's own tooltip card: its window, its picture, and what a screen reader is told
// (v0.6.27, S6.3c).
//
// ui/tray/tipcard.py's window half, ported call for call (its drawing is SurfaceRenderer.TipLayout/DrawTip/DrawTipLight,
// gui/SurfaceDrawn.cs): one layered window that never takes the focus or a click (WS_EX_NOACTIVATE | WS_EX_TRANSPARENT),
// made on the first hover, kept, hidden between hovers; redrawn each second for the countdown and its light's band per
// frame while it breathes; faded in and out as the menus fade; hidden by the backstop when the shell's NIN_POPUPCLOSE never
// comes, on a display or DPI change and on a suspend or a resume. It runs on the host's UI thread, which owns every window
// (P6-DESIGN 1.4). Nothing here acts: hovering shows, and that is all.
//
// Its clocks (`Monotonic`, `Now`) and the pointer (`Pointer`) are fields, so the probe mode can drive it with a window that
// is never shown; the live icon leaves them as they are.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal sealed class TipCard : IDisposable
    {
        internal const uint WS_EX_TRANSPARENT = 0x00000020;
        /// Never activated, never hit: what the card is to the pointer and the keyboard (TIP_STYLE).
        internal const uint TipStyle = SurfaceNative.WS_EX_LAYERED | SurfaceNative.WS_EX_TOOLWINDOW | SurfaceNative.WS_EX_TOPMOST
                                       | SurfaceNative.WS_EX_NOACTIVATE | WS_EX_TRANSPARENT;
        internal const int WM_MOUSEACTIVATE = 0x0021, MA_NOACTIVATE = 3, WM_NCHITTEST = 0x0084, HTTRANSPARENT = -1;
        internal const int WM_DISPLAYCHANGE = 0x007E, WM_THEMECHANGED = 0x031A;
        internal const int TipTick = 1, TipFrame = 2, TipFade = 3, TipWatch = 4;
        internal const int TipWatchMs = 250;
        internal const double TipAwayS = 1.0;
        internal const int TipNear = 16;
        internal const int WM_POWERBROADCAST = 0x0218, PBT_APMSUSPEND = 0x0004, PBT_APMRESUMESUSPEND = 0x0007,
                           PBT_APMRESUMEAUTOMATIC = 0x0012;
        internal const int ROLE_SYSTEM_TOOLTIP = 0x0D, STATE_SYSTEM_READONLY = 0x40;
        internal const uint EVENT_OBJECT_SHOW = 0x8002, EVENT_OBJECT_HIDE = 0x8003;
        internal const int OBJID_CLIENT = -4, CHILDID_SELF = 0;
        /// About thirty frames a second, and only while something moves (window.FRAME_MS).
        internal const int FrameMs = 33;

        [DllImport("user32.dll")]
        private static extern void NotifyWinEvent(uint winEvent, IntPtr hwnd, int objectId, int childId);

        // ------------------------------------------------------------------ the pure halves
        /// model.snapshot_activity: the popup header's word from the icon's own tick snapshot.
        internal static string SnapshotActivity(Dictionary<string, object> snapshot, double now, bool attention = false)
        {
            snapshot = snapshot ?? new Dictionary<string, object>();
            if (attention) return "attention";
            if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "held")) || SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "unconfirmed")))
                return "attention";
            if (snapshot.Count > 0 && !SurfaceMath.Truthy(snapshot.ContainsKey("enabled") ? snapshot["enabled"] : true))
                return "paused";
            if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "unmatched")) || SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "blocked")))
                return "attention";
            if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "running"))) return "recovering";
            if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "waiting")))
            {
                object due = SurfaceRender.Field(snapshot, "next_at");
                return due != null && Compare(due, now) <= 0 ? "checking" : "waiting";
            }
            return "monitoring";
        }

        private static int Compare(object value, double now)
        {
            double number = value is bool ? ((bool)value ? 1 : 0) : (double)value;
            return number.CompareTo(now);
        }

        /// tip_light: the light the card's dot shows; a failure nobody has seen is red, as the icon shows it.
        internal static string TipLight(Dictionary<string, object> snapshot, double now)
        {
            if (snapshot == null) throw new NullReferenceException("'NoneType' object has no attribute 'get'");
            if (SurfaceMath.Truthy(SurfaceRender.Field(snapshot, "failed"))) return "failed";
            return SnapshotActivity(snapshot, now);
        }

        /// tip_place: where the window goes, (x, y), for the card's size beside `box`.
        internal static int[] TipPlace(SurfacePlan plan, int[] work, int[] monitor, int[] box)
        {
            int[] card = plan.Card;
            int gap = SurfaceMath.Round(TipPlan.TipGap * plan.Scale);
            string edge;
            int[] at = PopupPlace.Place(new[] { card[2] - card[0], card[3] - card[1] }, work, monitor, box, null, gap, out edge);
            return new[] { at[0] - card[0], at[1] - card[1] };
        }

        /// tip_away: whether the pointer is off the icon's box (grown by `near` px) and off the card.
        internal static bool TipAway(int[] pointer, int[] box, int[] origin, int[] size, int near)
        {
            if (pointer == null) return false;
            int x = pointer[0], y = pointer[1];
            if (box[0] - near <= x && x < box[2] + near && box[1] - near <= y && y < box[3] + near) return false;
            return !(origin[0] <= x && x < origin[0] + size[0] && origin[1] <= y && y < origin[1] + size[1]);
        }

        /// tip_pointer: where the pointer is, in per-monitor pixels, or null.
        internal static int[] TipPointer()
        {
            SurfaceNative.POINT spot;
            using (new SurfaceNative.PerMonitorDpi())
                if (!SurfaceNative.GetCursorPos(out spot)) return null;
            return new[] { spot.X, spot.Y };
        }

        /// tip_screen: the box the card stands by, the work area and the monitor that box is on, and its DPI.
        internal static TipScreen ReadScreen(Func<int[]> icon, int[] point)
        {
            using (new SurfaceNative.PerMonitorDpi())
            {
                int[] rect = icon != null ? icon() : null;
                SurfaceNative.POINT spot;
                SurfaceNative.GetCursorPos(out spot);
                int[] box = TipPlan.Anchor(rect, point, new[] { spot.X, spot.Y })
                            ?? new[] { spot.X, spot.Y, spot.X + 1, spot.Y + 1 };
                var probe = new SurfaceNative.RECT(box[0], box[1], box[2], box[3]);
                IntPtr monitor = SurfaceNative.MonitorFromRect(ref probe, SurfaceNative.MONITOR_DEFAULTTONEAREST);
                var info = new SurfaceNative.MONITORINFO { CbSize = (uint)Marshal.SizeOf(typeof(SurfaceNative.MONITORINFO)) };
                SurfaceNative.GetMonitorInfoW(monitor, ref info);
                uint dpi = 0;
                try
                {
                    uint x, y;
                    if (SurfaceNative.GetDpiForMonitor(monitor, 0, out x, out y) == 0) dpi = x;
                }
                catch (Exception)
                {
                    dpi = 0;
                }
                return new TipScreen
                {
                    Box = box, Dpi = dpi != 0 ? dpi : 96,
                    Work = new[] { info.RcWork.Left, info.RcWork.Top, info.RcWork.Right, info.RcWork.Bottom },
                    Monitor = new[] { info.RcMonitor.Left, info.RcMonitor.Top, info.RcMonitor.Right, info.RcMonitor.Bottom },
                };
            }
        }

        internal sealed class TipScreen
        {
            internal int[] Box, Work, Monitor;
            internal uint Dpi;
        }

        /// What the card shows, read again each second it is shown: words.tooltip_parts of the icon's snapshot, that
        /// snapshot, and the catalog it is said in.
        internal sealed class Content
        {
            internal TrayWords.Parts Parts;
            internal Dictionary<string, object> Snapshot;
            internal Dictionary<string, object> Strings;
            /// The catalog's locale (popup.locale_of): the core's word, since the host carries no catalogs.
            internal string Locale;
            /// The letters the catalog writes (fonts._letters), which pick each language's face: the core's word too.
            internal string Letters;
        }

        // ------------------------------------------------------------------ the window
        private readonly Func<Content> content;
        private readonly Func<bool> held;
        private readonly Action<string> log;
        private readonly bool days;
        internal IntPtr Hwnd;
        internal bool Visible;
        /// The tooltip's whole text, as a screen reader is told it.
        internal string Text = "";
        internal Dictionary<string, object> Strings = new Dictionary<string, object>();
        internal string Locale = "en";
        internal bool Contrast;
        private string theme = "light", design = "soft";
        private bool reduced, still;
        private double textScale = 1.0;
        private SurfaceRenderer renderer;
        internal SurfacePlan Plan;
        private string shown;
        internal TipScreen Screen;
        internal int[] Origin = { 0, 0 };
        private SurfaceNative.WndProc proc;
        private string className;
        private string light;
        private double lightSince;
        private bool frameRunning;
        private double? awaySince;
        internal int Alpha = 255;
        /// The fade: "in" or "out", when it started (null until its first frame), the alpha it left from.
        private string fadeWay;
        private double? fadeStarted;
        private int fadeFrom;
        private static int made;

        /// The clocks and the pointer (time.monotonic, time.time, tip_pointer): fields, for the probe mode.
        internal Func<double> Monotonic = TrayPlace.Monotonic;
        internal Func<double> Now = () => (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        internal Func<int[]> Pointer = TipPointer;
        /// The screen read for a showing (tip_screen): a field, for the probe mode.
        internal Func<Func<int[]>, int[], TipScreen> ScreenReader = ReadScreen;
        /// The look's questions (theme.py's, through SurfaceTheme): fields, for the probe mode.
        internal Func<bool> AskContrast = SurfaceTheme.HighContrast, AskReduced = SurfaceTheme.ReducedMotion;
        internal Func<bool?> AskAppsLight = SurfaceTheme.AppsUseLightTheme;
        internal Func<double> AskTextScale = SurfaceTheme.TextScale;
        /// WM_GETOBJECT's answer (SurfaceAccess) for this card, or null to leave it to Windows.
        internal Func<TipCard, IntPtr, IntPtr, IntPtr?> Accessible = null;
        /// Whether the window is pushed to the screen (UpdateLayeredWindow, SetWindowPos, ShowWindow): false in the probe
        /// mode, which keeps the window hidden and reads the picture from the renderer's canvas.
        internal bool OnScreen = true;

        internal TipCard(Func<Content> content, Func<bool> held = null, Action<string> log = null, bool days = false)
        {
            this.content = content;
            this.held = held;
            this.log = log ?? (unused => { });
            this.days = days;
            lightSince = TrayPlace.Monotonic();
        }

        internal SurfaceRenderer Renderer { get { return renderer; } }

        // ------------------------------------------------------------------ life
        internal void Create()
        {
            IntPtr instance = SurfaceNative.GetModuleHandleW(null);
            proc = WindowProc;
            var klass = new SurfaceNative.WNDCLASSW
            {
                LpfnWndProc = proc, HInstance = instance,
                HCursor = SurfaceNative.LoadCursorW(IntPtr.Zero, new IntPtr(SurfaceNative.IDC_ARROW)),
            };
            className = "CodexAutoResumeTip-" + System.Diagnostics.Process.GetCurrentProcess().Id + "-"
                        + System.Threading.Interlocked.Increment(ref made);
            klass.LpszClassName = className;
            if (SurfaceNative.RegisterClassW(ref klass) == 0)
            {
                className = null;
                throw new InvalidOperationException("RegisterClassW");
            }
            try
            {
                using (new SurfaceNative.PerMonitorDpi())
                    Hwnd = SurfaceNative.CreateWindowExW(TipStyle, className, "Codex Auto Resume", SurfaceNative.WS_POPUP,
                                                         0, 0, 1, 1, IntPtr.Zero, IntPtr.Zero, instance, IntPtr.Zero);
                if (Hwnd == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
                renderer = SurfaceRenderer.Open();
            }
            catch (Exception)
            {
                Dispose();
                throw;
            }
        }

        /// destroy: the window, its timers, the renderer and the class.
        public void Dispose()
        {
            SurfaceAccessHooks.Disconnect(this);
            IntPtr hwnd = Hwnd;
            Hwnd = IntPtr.Zero;
            Visible = false;
            fadeWay = null;
            if (hwnd != IntPtr.Zero)
            {
                foreach (int timer in new[] { TipTick, TipFrame, TipFade, TipWatch })
                    SurfaceNative.KillTimer(hwnd, new UIntPtr((uint)timer));
                SurfaceNative.DestroyWindow(hwnd);
            }
            frameRunning = false;
            if (renderer != null)
            {
                renderer.Dispose();
                renderer = null;
            }
            Plan = null;
            shown = null;
            if (className != null)
            {
                SurfaceNative.UnregisterClassW(className, SurfaceNative.GetModuleHandleW(null));
                className = null;
            }
        }

        // ------------------------------------------------------------------ the icon asks
        /// show: beside the icon (`icon` asks for its rectangle, or is null; `point` the shell's anchor point or null),
        /// with what the icon says now; already shown, brought up to date where it is.
        internal void Show(Func<int[]> icon = null, int[] point = null)
        {
            if (Hwnd == IntPtr.Zero) Create();
            ReadLook();
            Screen = ScreenReader(icon, point);
            bool fading = fadeWay == "out";
            Lay(true);
            if (!Visible || fading) Appear();
            Push();
            Place();
            if (OnScreen) SurfaceNative.ShowWindow(Hwnd, SurfaceNative.SW_SHOWNOACTIVATE);
            if (!Visible) Tell(EVENT_OBJECT_SHOW);
            Visible = true;
            awaySince = null;
            SetTimer(TipTick, 1000);
            SetTimer(TipWatch, TipWatchMs);
            SyncFrames();
        }

        /// hide: at once, or (`atOnce` false: the pointer left) fading out in brand's press time where motion is allowed.
        internal void Hide(bool atOnce = true)
        {
            if (Hwnd == IntPtr.Zero) return;
            if (!Visible)
            {
                if (atOnce && fadeWay == "out") Gone();
                return;
            }
            Visible = false;
            foreach (int timer in new[] { TipTick, TipFrame, TipWatch }) KillTimer(timer);
            frameRunning = false;
            Tell(EVENT_OBJECT_HIDE);
            if (atOnce || !Moves() || Alpha <= 0)
            {
                Gone();
                return;
            }
            fadeWay = "out";
            fadeStarted = NowMs();
            fadeFrom = Alpha;
            SetTimer(TipFade, PopupMotion.GlideFrameMs);
        }

        /// tick: a second on - what the icon says now, drawn again where it changed.
        internal void Tick()
        {
            if (!Visible) return;
            still = AskHeld();
            if (Lay(false))
            {
                Push();
                Place();
            }
            SyncFrames();
        }

        /// watch: the backstop's look - the pointer away from the icon and the card for TipAwayS, and the card goes.
        internal void Watch()
        {
            if (!Visible || Plan == null || Screen == null) return;
            double scale = Plan.Scale;
            if (!TipAway(Pointer(), Screen.Box, Origin, Plan.Size, SurfaceMath.Round(TipNear * scale)))
            {
                awaySince = null;
                return;
            }
            double now = Monotonic();
            if (awaySince == null) awaySince = now;
            else if (now - awaySince.Value >= TipAwayS) Hide(false);
        }

        // ------------------------------------------------------------------ what it shows
        private void ReadLook()
        {
            Contrast = AskContrast();
            theme = SurfaceTheme.EffectiveTheme(SurfaceTheme.ThemeSetting, AskAppsLight());
            design = SurfaceTheme.DesignSetting;
            reduced = AskReduced() || Contrast;
            textScale = AskTextScale();
            still = AskHeld();
        }

        private bool AskHeld()
        {
            try
            {
                return held != null && held();
            }
            catch (Exception)
            {
                return false;
            }
        }

        private bool Holds() { return reduced || still; }

        /// Whether it fades: not with motion reduced, nor in High Contrast.
        private bool Moves() { return Hwnd != IntPtr.Zero && !(Contrast || AskReduced()); }

        /// Read what the icon says and lay the card out for it, placed by the icon. True when the plan is new.
        internal bool Lay(bool force)
        {
            Content now = content();
            string lit = TipLight(now.Snapshot, Now());
            string locale = string.IsNullOrEmpty(now.Locale) ? "en" : now.Locale;
            string day = SurfaceRenderer.TipDay(days ? DayLookAt(Now()) : null, Contrast, design);
            Dictionary<string, object> parts = now.Parts.ToJson();
            string key = Json.Write(parts) + "\u0001" + lit + "\u0001" + locale + "\u0001" + theme + "\u0001" + design + "\u0001"
                         + Contrast + "\u0001" + textScale.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                         + "\u0001" + day;
            if (!force && key == shown && Plan != null) return false;
            if (lit != light)
            {
                light = lit;
                lightSince = Monotonic();
            }
            Strings = now.Strings;
            Locale = locale;
            Text = TrayWords.Joined(now.Parts);
            double scale = Screen.Dpi / 96.0;
            int[] work = Screen.Work;
            renderer.Letters = now.Letters;
            SurfacePlan plan = renderer.TipLayout(parts, lit, scale, locale, day);
            double fit = SurfaceTheme.Fitting(textScale, new double[] { plan.Size[0], plan.Size[1] },
                                              new double[] { work[2] - work[0], work[3] - work[1] });
            if (fit > 1.0) plan = renderer.TipLayout(parts, lit, scale * fit, locale, day);
            Plan = plan;
            shown = key;
            Origin = TipPlace(plan, work, Screen.Monitor, Screen.Box);
            return true;
        }

        /// brand.day_look_at: the look of the local date at `moment`, or null for an ordinary day.
        internal static string DayLookAt(double moment)
        {
            DateTime local = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(moment).ToLocalTime();
            string look, top, bottom;
            return Brand.DayLook(local.Year, local.Month, local.Day, out look, out top, out bottom) ? look : null;
        }

        /// The light for this instant, its cycle starting with its state.
        internal LightFrame Frame()
        {
            double since = (Monotonic() - lightSince) * 1000.0;
            return PopupMotion.Halo(light, since, Holds(), design);
        }

        /// The window's picture as it is now.
        internal SurfaceCanvas Render()
        {
            renderer.Theme = theme;
            renderer.Design = design;
            renderer.Contrast = Contrast;
            return renderer.DrawTip(Plan, Frame());
        }

        private void Push()
        {
            Render();
            Blit();
        }

        private void Blit()
        {
            if (!OnScreen) return;
            var blend = new SurfaceNative.BLENDFUNCTION { BlendOp = 0, BlendFlags = 0, SourceConstantAlpha = (byte)Alpha,
                                                          AlphaFormat = SurfaceNative.AC_SRC_ALPHA };
            var where = new SurfaceNative.POINT { X = Origin[0], Y = Origin[1] };
            var size = new SurfaceNative.SIZE { Cx = Plan.Size[0], Cy = Plan.Size[1] };
            var source = new SurfaceNative.POINT();
            bool ok;
            using (new SurfaceNative.PerMonitorDpi())
                ok = SurfaceNative.UpdateLayeredWindow(Hwnd, IntPtr.Zero, ref where, ref size, renderer.Canvas.Dc, ref source, 0,
                                                       ref blend, SurfaceNative.ULW_ALPHA);
            if (!ok) throw new InvalidOperationException("UpdateLayeredWindow");
        }

        private void Place()
        {
            if (!OnScreen) return;
            using (new SurfaceNative.PerMonitorDpi())
                SurfaceNative.SetWindowPos(Hwnd, SurfaceNative.HWND_TOPMOST, Origin[0], Origin[1], Plan.Size[0], Plan.Size[1],
                                           SurfaceNative.SWP_NOACTIVATE);
        }

        // ------------------------------------------------------------------ its motion
        private void SyncFrames()
        {
            bool wanted = Visible && PopupMotion.Animates(light, Holds());
            if (wanted && !frameRunning)
            {
                SetTimer(TipFrame, FrameMs);
                frameRunning = true;
            }
            else if (!wanted && frameRunning)
            {
                KillTimer(TipFrame);
                frameRunning = false;
            }
        }

        /// Whether the light's frame timer runs (the probe reads it).
        internal bool FrameRunning { get { return frameRunning; } }

        /// The fade as (way, started) or null (the probe reads it).
        internal string Fade { get { return fadeWay; } }

        internal void LightStep()
        {
            if (!Visible || Plan == null) return;
            renderer.DrawTipLight(Plan, Frame());
            Blit();
        }

        private void Appear()
        {
            KillTimer(TipFade);
            if (Moves())
            {
                Alpha = 0;
                fadeWay = "in";
                fadeStarted = null;
                SetTimer(TipFade, PopupMotion.GlideFrameMs);
            }
            else
            {
                Alpha = 255;
                fadeWay = null;
            }
        }

        internal void FadeStep()
        {
            if (fadeWay == null || Hwnd == IntPtr.Zero) return;
            string way = fadeWay;
            if (fadeStarted == null) fadeStarted = NowMs();
            bool done;
            if (way == "in")
            {
                int[] step = PopupMotion.Opening(NowMs() - fadeStarted.Value, 0);
                Alpha = step[0];
                done = step[2] != 0;
            }
            else
            {
                int[] step = PopupMotion.Closing(NowMs() - fadeStarted.Value, fadeFrom);
                Alpha = step[0];
                done = step[1] != 0;
            }
            if (done)
            {
                KillTimer(TipFade);
                fadeWay = null;
                if (way == "out")
                {
                    Gone();
                    return;
                }
            }
            Blit();
        }

        private void Gone()
        {
            KillTimer(TipFade);
            fadeWay = null;
            SurfaceNative.ShowWindow(Hwnd, SurfaceNative.SW_HIDE);
            Alpha = 255;
        }

        private double NowMs() { return Monotonic() * 1000.0; }

        private void SetTimer(int id, int ms) { SurfaceNative.SetTimer(Hwnd, new UIntPtr((uint)id), (uint)ms, IntPtr.Zero); }

        private void KillTimer(int id) { SurfaceNative.KillTimer(Hwnd, new UIntPtr((uint)id)); }

        private void Tell(uint winEvent)
        {
            if (Hwnd == IntPtr.Zero) return;
            try
            {
                NotifyWinEvent(winEvent, Hwnd, OBJID_CLIENT, CHILDID_SELF);
            }
            catch (Exception)
            {
            }
        }

        // ------------------------------------------------------------------ messages
        private IntPtr WindowProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam)
        {
            try
            {
                if (message == SurfaceNative.WM_TIMER)
                {
                    long timer = wParam.ToInt64();
                    if (timer == TipTick) Tick();
                    else if (timer == TipFrame) LightStep();
                    else if (timer == TipFade) FadeStep();
                    else if (timer == TipWatch) Watch();
                    return IntPtr.Zero;
                }
                if (message == SurfaceNative.WM_GETOBJECT)
                {
                    IntPtr? answered = Accessible != null ? Accessible(this, wParam, lParam) : null;
                    if (answered != null) return answered.Value;
                }
                else if (message == WM_MOUSEACTIVATE) return new IntPtr(MA_NOACTIVATE);
                else if (message == WM_NCHITTEST) return new IntPtr(HTTRANSPARENT);
                else if (message == SurfaceNative.WM_SETTINGCHANGE || message == SurfaceNative.WM_SYSCOLORCHANGE
                         || message == WM_THEMECHANGED)
                {
                    if (Visible)
                    {
                        ReadLook();
                        Lay(true);
                        Push();
                        SyncFrames();
                    }
                }
                else if (message == WM_DISPLAYCHANGE || message == SurfaceNative.WM_DPICHANGED) Hide();
                else if (message == WM_POWERBROADCAST)
                {
                    long what = wParam.ToInt64();
                    if (what == PBT_APMSUSPEND || what == PBT_APMRESUMESUSPEND || what == PBT_APMRESUMEAUTOMATIC) Hide();
                }
            }
            catch (Exception exc)
            {
                log("tray tip card message failed (" + PythonName(exc) + ")");
                try
                {
                    Hide();
                }
                catch (Exception)
                {
                }
                return IntPtr.Zero;
            }
            return SurfaceNative.DefWindowProcW(hwnd, message, wParam, lParam);
        }

        /// The Python's name for the error class a log line names.
        internal static string PythonName(Exception exc)
        {
            if (exc is InvalidOperationException || exc is System.ComponentModel.Win32Exception) return "OSError";
            if (exc is KeyNotFoundException) return "KeyError";
            if (exc is InvalidCastException || exc is NullReferenceException) return "AttributeError";
            if (exc is ArgumentException || exc is FormatException) return "ValueError";
            if (exc is IndexOutOfRangeException || exc is ArgumentOutOfRangeException) return "IndexError";
            return exc.GetType().Name;
        }
    }

    /// The screen reader's hold on a surface's client object, cut as its window goes (access.disconnect); SurfaceAccess
    /// sets `Disconnecting` when it hands out an object.
    internal static class SurfaceAccessHooks
    {
        internal static Action<object> Disconnecting = null;

        internal static void Disconnect(object surface)
        {
            try
            {
                if (Disconnecting != null) Disconnecting(surface);
            }
            catch (Exception)
            {
            }
        }
    }
}

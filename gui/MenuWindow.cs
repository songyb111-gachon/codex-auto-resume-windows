// Codex Auto Resume - the drawn menu's window: the icon's right-click menu and the popup's row menus (v0.6.27, S6.3d).
//
// ui/popup/menuwindow.py's Menu, ported call for call (its picture is SurfaceRenderer.MenuLayout/DrawMenu, gui/SurfaceDrawn.cs;
// where everything goes, gui/MenuPlan.cs). One layered window - an alpha for every pixel - that opens at the pointer, takes
// the keyboard and closes on Esc, Alt or F10, a click anywhere else, or anything that takes the focus; Up and Down, Home and
// End, Enter, a letter; the pointer puts an item in hand and a release chooses it. An item with an arrow opens a second Menu
// beside it, never activated, its keys heard by the first. Choosing hands the item's id to the caller after the menu has
// closed, which is all it can do: nothing here acts. It runs on the host's UI thread (P6-DESIGN 1.4); every call that reaches
// the screen goes through SurfaceScreen, so the probe mode drives it over a window that is made and never shown.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

namespace CodexAutoResume
{
    internal sealed class MenuWindow : IRowMenu, IDisposable
    {
        internal const int WM_CANCELMODE = 0x001F, WM_ACTIVATEAPP = 0x001C, WM_CHAR = 0x0102;
        internal const int WM_SYSKEYDOWN = 0x0104, WM_RBUTTONDOWN = 0x0204, WM_RBUTTONUP = 0x0205;
        internal const int VK_MENU = 0x12, VK_END = 0x23, VK_HOME = 0x24, VK_F10 = 0x79, VK_LEFT = 0x25, VK_RIGHT = 0x27;
        internal const int WM_MOUSEACTIVATE = 0x0021, MA_NOACTIVATE = 3;
        internal const uint SPI_GETMENUSHOWDELAY = 0x006A;
        internal const int HoverTimer = 1, FadeTimer = 2;
        internal const int WS_EX_TRANSPARENT = 0x00000020;
        internal const uint EVENT_SYSTEM_MENUPOPUPSTART = 0x0006, EVENT_SYSTEM_MENUPOPUPEND = 0x0007;

        private static int made;

        [DllImport("user32.dll", EntryPoint = "SystemParametersInfoW")]
        private static extern bool SystemParametersInfoDword(uint action, uint param, ref uint value, uint winIni);

        internal Action<string> Log = unused => { };
        internal readonly MenuWindow Parent;
        internal IntPtr Owner;
        internal Action OnLeave;
        private MenuWindow child;
        private int? childIndex, hover;
        internal int[] Work = new int[4];
        private IntPtr hwnd;
        internal bool Visible;
        internal List<object> Entries = new List<object>();
        internal Dictionary<string, object> Strings = new Dictionary<string, object>();
        internal string Locale = "en";
        internal string Letters = "";
        internal Action<object> OnChoose;
        internal int? Selected;
        internal bool Contrast;
        internal string Theme = "light", Design = Brand.DesignDefault;
        private SurfaceRenderer renderer;
        internal SurfacePlan Plan;
        internal int[] Origin = { 0, 0 };
        private SurfaceNative.WndProc proc;
        private string className;
        private bool tracking;
        internal int Alpha = 255, Below;
        // ("in", started ms or NaN, rise) or ("out", started ms, the alpha it left from), or null.
        internal string FadeWay;
        private double fadeStarted;
        private int fadeValue;
        /// A screen reader's hooks (SurfaceAccess): WM_GETOBJECT's answer, what changed, and the menu events told.
        internal Func<MenuWindow, IntPtr, IntPtr, IntPtr?> Accessible = null;
        internal Action<MenuWindow> Speaking = null;
        internal Action<IntPtr, uint> Telling = null;
        internal List<Dictionary<string, object>> Spoken = new List<Dictionary<string, object>>();
        internal Func<double> Monotonic = TrayPlace.Monotonic;
        internal Func<int[], MenuScreen> ScreenReader = ReadScreen;
        internal Func<bool> AskContrast = SurfaceTheme.HighContrast, AskReduced = SurfaceTheme.ReducedMotion;
        internal Func<bool?> AskAppsLight = SurfaceTheme.AppsUseLightTheme;
        internal Func<double> AskTextScale = SurfaceTheme.TextScale;

        internal sealed class MenuScreen
        {
            internal int[] Cursor, Work;
            internal double Dpi;
        }

        internal MenuWindow(Action<string> log = null, MenuWindow parent = null)
        {
            Log = log ?? (unused => { });
            Parent = parent;
            if (parent != null)
            {
                Monotonic = parent.Monotonic;
                ScreenReader = parent.ScreenReader;
                AskContrast = parent.AskContrast;
                AskReduced = parent.AskReduced;
                AskAppsLight = parent.AskAppsLight;
                AskTextScale = parent.AskTextScale;
                Accessible = parent.Accessible;
                Speaking = parent.Speaking;
                Telling = parent.Telling;
            }
        }

        public IntPtr Hwnd { get { return hwnd; } }
        internal SurfaceRenderer Renderer { get { return renderer; } }
        internal MenuWindow Child { get { return child; } }

        private double NowMs() { return Monotonic() * 1000.0; }

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
            className = "CodexAutoResumeMenu-" + System.Diagnostics.Process.GetCurrentProcess().Id + "-"
                        + Interlocked.Increment(ref made);
            klass.LpszClassName = className;
            if (SurfaceNative.RegisterClassW(ref klass) == 0)
            {
                className = null;
                throw new InvalidOperationException("RegisterClassW");
            }
            try
            {
                using (new SurfaceNative.PerMonitorDpi())
                {
                    uint style = SurfaceNative.WS_EX_LAYERED | SurfaceNative.WS_EX_TOOLWINDOW | SurfaceNative.WS_EX_TOPMOST
                                 | (Parent != null ? SurfaceNative.WS_EX_NOACTIVATE : 0);
                    hwnd = SurfaceNative.CreateWindowExW(style, className, PopupWords.Say(Strings, "tray.title"), SurfaceNative.WS_POPUP,
                                                         0, 0, 1, 1, IntPtr.Zero, IntPtr.Zero, instance, IntPtr.Zero);
                }
                if (hwnd == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
                renderer = SurfaceRenderer.Open();
            }
            catch (Exception)
            {
                Destroy();
                throw;
            }
        }

        public void Dispose() { Destroy(); }

        /// destroy: its submenu, the screen reader's hold, the window, the renderer and the class.
        public void Destroy()
        {
            MenuWindow sub = child;
            child = null;
            if (sub != null) sub.Destroy();
            SurfaceAccessHooks.Disconnect(this);
            IntPtr window = hwnd;
            hwnd = IntPtr.Zero;
            Visible = false;
            if (window != IntPtr.Zero) SurfaceNative.DestroyWindow(window);
            if (renderer != null)
            {
                renderer.Dispose();
                renderer = null;
            }
            Plan = null;
            if (className != null)
            {
                SurfaceNative.UnregisterClassW(className, SurfaceNative.GetModuleHandleW(null));
                className = null;
            }
        }

        // ------------------------------------------------------------------ the icon asks
        /// IRowMenu: the popup's row menu, its ids handed over as ints.
        public bool Open(List<object> entries, Dictionary<string, object> strings, Action<int> run, int[] point, IntPtr owner,
                         Action onLeave)
        {
            return Open(entries, strings, null, null, chosen => run(Convert.ToInt32(chosen)), point, owner, onLeave);
        }

        /// open: `entries` at the pointer - or at `point` - taking the keyboard; `onChoose(id)` once one is chosen. False
        /// when Windows refused it the foreground, and it is hidden again. `locale` and `letters` are the catalog's (the host
        /// has no locale_of); null keeps the ones it had.
        internal bool Open(List<object> entries, Dictionary<string, object> strings, string locale, string letters,
                           Action<object> onChoose, int[] point = null, IntPtr owner = default(IntPtr), Action onLeave = null)
        {
            if (hwnd == IntPtr.Zero) Create();
            Entries = new List<object>(entries);
            Strings = strings != null ? new Dictionary<string, object>(strings) : new Dictionary<string, object>();
            OnChoose = onChoose;
            Owner = owner;
            OnLeave = onLeave;
            if (locale != null) Locale = locale;
            if (letters != null) Letters = letters;
            renderer.Letters = Letters;
            Selected = null;
            ReadLook();
            MenuScreen screen = ScreenReader(point);
            double scale = screen.Dpi / 96.0;
            int[] work = screen.Work;
            SurfacePlan plan = renderer.MenuLayout(Entries, scale, Locale, work[2] - work[0]);
            double fit = SurfaceTheme.Fitting(AskTextScale(), new double[] { plan.Card[2] - plan.Card[0], plan.Card[3] - plan.Card[1] },
                                              new double[] { work[2] - work[0], work[3] - work[1] });
            if (fit > 1.0) plan = renderer.MenuLayout(Entries, scale * fit, Locale, work[2] - work[0]);
            Plan = plan;
            Work = work;
            Origin = MenuPlan.Place(plan, screen.Cursor, work);
            Appear();
            Push();
            SurfaceScreen.SetWindowPos(hwnd, SurfaceNative.HWND_TOPMOST, Origin[0], Origin[1] + Below, plan.Size[0], plan.Size[1],
                                       SurfaceNative.SWP_NOACTIVATE);
            SurfaceScreen.ShowWindow(hwnd, SurfaceNative.SW_SHOW);
            Visible = true;
            SurfaceScreen.SetForegroundWindow(hwnd);
            SurfaceScreen.SetFocus(hwnd);
            if (SurfaceScreen.GetForegroundWindow() != hwnd)
            {
                Close(true);
                return false;
            }
            Spoken = AccessibleItems();
            Tell(EVENT_SYSTEM_MENUPOPUPSTART);
            return true;
        }

        public void Close() { Close(false); }

        /// close: hidden, with nothing chosen, and its submenu with it.
        internal void Close(bool quietly)
        {
            if (!Visible) return;
            Visible = false;
            if (child != null) child.Close();
            childIndex = hover = null;
            if (hwnd != IntPtr.Zero) SurfaceScreen.KillTimer(hwnd, HoverTimer);
            Selected = null;
            tracking = false;
            if (hwnd != IntPtr.Zero) LeaveScreen(quietly);
            if (!quietly) Tell(EVENT_SYSTEM_MENUPOPUPEND);
            Spoken = new List<Dictionary<string, object>>();
        }

        /// _dismiss: closed by the person - the keyboard goes back to the window it came from first.
        private void Dismiss()
        {
            if (Owner != IntPtr.Zero && Visible) SurfaceScreen.SetForegroundWindow(Owner);
            Close();
        }

        private static Dictionary<string, object> EntryAt(List<object> entries, int index)
        {
            return index >= 0 && index < entries.Count ? entries[index] as Dictionary<string, object> : null;
        }

        /// _activate: choose the item at `index`; an item that cannot be used does nothing, one with a submenu opens it.
        internal void Activate(int index, bool keyboard = false)
        {
            if (!Visible || !(0 <= index && index < Entries.Count)) return;
            Dictionary<string, object> entry = EntryAt(Entries, index);
            if (entry == null || !SurfaceMath.Truthy(SurfaceRender.Field(entry, "enabled"))) return;
            if (SurfaceMath.Truthy(SurfaceRender.Field(entry, "items")))
            {
                OpenChild(index, keyboard);
                return;
            }
            ChosenBelow(SurfaceRender.Field(entry, "id"));
        }

        // ------------------------------------------------------------------ a submenu
        private void ChosenBelow(object identifier)
        {
            Action<object> chosen = OnChoose;
            if (Parent != null) Close();
            else Dismiss();
            if (chosen != null) chosen(identifier);
        }

        private void OpenChild(int index, bool first = false)
        {
            if (child == null) child = new MenuWindow(Log, this);
            child.Close();
            if (hwnd != IntPtr.Zero) SurfaceScreen.KillTimer(hwnd, HoverTimer);
            childIndex = index;
            hover = null;
            Select(index);
            child.ShowBeside(this, index, first);
        }

        /// show_beside: open as `parent`'s item `index`'s submenu, at its scale and in its look, not taking the keyboard.
        internal void ShowBeside(MenuWindow parent, int index, bool first)
        {
            if (hwnd == IntPtr.Zero) Create();
            Entries = new List<object>((List<object>)EntryAt(parent.Entries, index)["items"]);
            Strings = parent.Strings;
            Locale = parent.Locale;
            Letters = parent.Letters;
            renderer.Letters = Letters;
            OnChoose = parent.ChosenBelow;
            Contrast = parent.Contrast;
            Theme = parent.Theme;
            Design = parent.Design;
            Work = parent.Work;
            Plan = renderer.MenuLayout(Entries, parent.Plan.Scale, Locale, Work[2] - Work[0]);
            int[] rect = null;
            foreach (PlanItem item in parent.Plan.Items)
                if (Equals(item.Get("index"), index) || (item.Get("index") is double && (double)item.Get("index") == index))
                {
                    rect = item.Rect;
                    break;
                }
            int[] card = parent.Plan.Card;
            int x = parent.Origin[0], y = parent.Origin[1];
            Origin = MenuPlan.Beside(Plan, new[] { x + card[0], y + rect[1], x + card[2], y + rect[3] }, Work);
            Selected = first ? MenuPlan.End(Entries) : null;
            Appear();
            Push();
            SurfaceScreen.SetWindowPos(hwnd, SurfaceNative.HWND_TOPMOST, Origin[0], Origin[1] + Below, Plan.Size[0], Plan.Size[1],
                                       SurfaceNative.SWP_NOACTIVATE);
            SurfaceScreen.ShowWindow(hwnd, SurfaceNative.SW_SHOWNOACTIVATE);
            Visible = true;
            Spoken = AccessibleItems();
            Tell(EVENT_SYSTEM_MENUPOPUPSTART);
        }

        private bool ChildOpen() { return child != null && child.Visible; }

        private void CloseChild()
        {
            if (child != null) child.Close();
            childIndex = null;
        }

        private void Rest(int? index)
        {
            if (index == hover) return;
            hover = index;
            if (hwnd != IntPtr.Zero) SurfaceScreen.KillTimer(hwnd, HoverTimer);
            if (hwnd == IntPtr.Zero || index == null || index == childIndex) return;
            uint delay = 400;
            SystemParametersInfoDword(SPI_GETMENUSHOWDELAY, 0, ref delay, 0);
            SurfaceScreen.SetTimer(hwnd, HoverTimer, (int)Math.Max(1, delay));
        }

        private void Rested()
        {
            if (hwnd != IntPtr.Zero) SurfaceScreen.KillTimer(hwnd, HoverTimer);
            int? index = hover;
            hover = null;
            if (!Visible || index == null || index == childIndex) return;
            Dictionary<string, object> entry = EntryAt(Entries, index.Value);
            if (entry != null && SurfaceMath.Truthy(SurfaceRender.Field(entry, "enabled")) && SurfaceMath.Truthy(SurfaceRender.Field(entry, "items")))
                OpenChild(index.Value);
            else CloseChild();
        }

        // ------------------------------------------------------------------ what it looks like
        private void ReadLook()
        {
            Contrast = AskContrast();
            Theme = SurfaceTheme.EffectiveTheme(SurfaceTheme.ThemeSetting, AskAppsLight());
            Design = SurfaceTheme.DesignSetting;
        }

        internal static MenuScreen ReadScreen(int[] at)
        {
            int[] cursor, work;
            int dpi;
            SurfaceNative.ScreenAt(at, out cursor, out dpi, out work);
            return new MenuScreen { Cursor = cursor, Dpi = dpi, Work = work };
        }

        internal SurfaceCanvas Render()
        {
            renderer.Theme = Theme;
            renderer.Design = Design;
            renderer.Contrast = Contrast;
            return renderer.DrawMenu(Plan, Selected);
        }

        private void Push()
        {
            Render();
            Blit();
        }

        private void Blit()
        {
            if (!SurfaceScreen.UpdateLayered(hwnd, new[] { Origin[0], Origin[1] + Below }, Plan.Size, renderer.Canvas.Dc, Alpha))
                throw new InvalidOperationException("UpdateLayeredWindow");
        }

        // ------------------------------------------------------------------ its motion (v0.6.23)
        private void Appear()
        {
            StopFade();
            bool moves = hwnd != IntPtr.Zero && !(Contrast || AskReduced());
            int rise = moves ? Math.Max(1, SurfaceMath.Round(PopupWindow.SpacingXs * Plan.Scale)) : 0;
            if (moves)
            {
                Alpha = 0;
                Below = rise;
                FadeWay = "in";
                fadeStarted = double.NaN;
                fadeValue = rise;
                SurfaceScreen.SetTimer(hwnd, FadeTimer, PopupMotion.GlideFrameMs);
            }
            else
            {
                Alpha = 255;
                Below = 0;
                FadeWay = null;
            }
        }

        private void LeaveScreen(bool quietly)
        {
            int alpha = Alpha;
            StopFade();
            if (quietly || Contrast || AskReduced() || alpha <= 0)
            {
                Hide();
                return;
            }
            Alpha = alpha;
            FadeWay = "out";
            fadeStarted = NowMs();
            fadeValue = alpha;
            SurfaceScreen.SetExStyle(hwnd, SurfaceScreen.GetExStyle(hwnd) | WS_EX_TRANSPARENT);
            SurfaceScreen.SetTimer(hwnd, FadeTimer, PopupMotion.GlideFrameMs);
        }

        internal void FadeStep()
        {
            if (FadeWay == null || hwnd == IntPtr.Zero) return;
            string way = FadeWay;
            if (double.IsNaN(fadeStarted)) fadeStarted = NowMs();
            bool done;
            if (way == "in")
            {
                int[] step = PopupMotion.Opening(NowMs() - fadeStarted, fadeValue);
                Alpha = step[0];
                Below = step[1];
                done = step[2] != 0;
            }
            else
            {
                int[] step = PopupMotion.Closing(NowMs() - fadeStarted, fadeValue);
                Alpha = step[0];
                done = step[1] != 0;
            }
            if (done)
            {
                StopFade();
                if (way == "out")
                {
                    Hide();
                    return;
                }
            }
            Blit();
        }

        private void Hide()
        {
            SurfaceScreen.ShowWindow(hwnd, SurfaceNative.SW_HIDE);
            Alpha = 255;
            Below = 0;
        }

        private void StopFade()
        {
            FadeWay = null;
            if (hwnd != IntPtr.Zero)
            {
                SurfaceScreen.KillTimer(hwnd, FadeTimer);
                int style = SurfaceScreen.GetExStyle(hwnd);
                if ((style & WS_EX_TRANSPARENT) != 0) SurfaceScreen.SetExStyle(hwnd, style & ~WS_EX_TRANSPARENT);
            }
        }

        private void Select(int? index)
        {
            if (index == Selected) return;
            Selected = index;
            if (Visible)
            {
                Push();
                Speak();
            }
        }

        // ------------------------------------------------------------------ a screen reader
        internal List<Dictionary<string, object>> AccessibleItems()
        {
            return Visible ? MenuPlan.AccessibleItems(Plan, Selected, Strings) : new List<Dictionary<string, object>>();
        }

        private void Speak()
        {
            if (Speaking != null) Speaking(this);
            else Spoken = AccessibleItems();
        }

        private void Tell(uint winEvent)
        {
            if (Telling != null) Telling(hwnd, winEvent);
        }

        // ------------------------------------------------------------------ messages
        /// The window procedure, for the probe to send a message to (as Windows would).
        internal IntPtr Message(int message, long wParam, long lParam)
        {
            return WindowProc(hwnd, (uint)message, new IntPtr(wParam), new IntPtr(lParam));
        }

        private IntPtr WindowProc(IntPtr window, uint message, IntPtr wParam, IntPtr lParam)
        {
            try
            {
                IntPtr? handled = Handle((int)message, wParam.ToInt64(), lParam.ToInt64());
                if (handled != null) return handled.Value;
            }
            catch (Exception exc)
            {
                Log("tray menu message failed (" + TipCard.PythonName(exc) + ")");
                try
                {
                    Close();
                }
                catch (Exception)
                {
                }
            }
            return SurfaceScreen.DefWindowProc(window, message, wParam, lParam);
        }

        private IntPtr? Handle(int message, long wparam, long lparam)
        {
            IntPtr zero = IntPtr.Zero;
            if (message == SurfaceNative.WM_GETOBJECT)
                return Accessible != null ? Accessible(this, new IntPtr(wparam), new IntPtr(lparam)) : null;
            if (message == WM_MOUSEACTIVATE && Parent != null) return new IntPtr(MA_NOACTIVATE);
            if (message == SurfaceNative.WM_TIMER && wparam == HoverTimer)
            {
                Rested();
                return zero;
            }
            if (message == SurfaceNative.WM_TIMER && wparam == FadeTimer)
            {
                FadeStep();
                return zero;
            }
            if (message == SurfaceNative.WM_ACTIVATE)
            {
                if ((wparam & 0xFFFF) == SurfaceNative.WA_INACTIVE)
                {
                    Leave(new IntPtr(lparam));
                    return zero;
                }
                return null;
            }
            if (message == WM_CANCELMODE || message == SurfaceNative.WM_CLOSE)
            {
                Close();
                return zero;
            }
            if (message == WM_ACTIVATEAPP)
            {
                if (wparam == 0) Leave(null);
                return null;
            }
            if (message == SurfaceNative.WM_KEYDOWN) return Key((int)wparam);
            if (message == WM_SYSKEYDOWN)
            {
                if (wparam == VK_MENU || wparam == VK_F10)
                {
                    Dismiss();
                    return zero;
                }
                return null;
            }
            if (message == WM_CHAR) return Char((int)(wparam & 0xFFFF));
            if (message == SurfaceNative.WM_MOUSEMOVE)
            {
                MouseMove(lparam);
                return zero;
            }
            if (message == SurfaceNative.WM_MOUSELEAVE)
            {
                tracking = false;
                Rest(null);
                Select(ChildOpen() ? childIndex : null);
                return zero;
            }
            if (message == SurfaceNative.WM_LBUTTONDOWN || message == WM_RBUTTONDOWN)
            {
                if (!OnCard(lparam))
                {
                    MenuWindow root = this;
                    while (root.Parent != null) root = root.Parent;
                    root.Dismiss();
                }
                return zero;
            }
            if (message == SurfaceNative.WM_LBUTTONUP || message == WM_RBUTTONUP)
            {
                int? target = Hit(lparam);
                if (target != null) Activate(target.Value);
                return zero;
            }
            if (message == SurfaceNative.WM_SETTINGCHANGE || message == SurfaceNative.WM_SYSCOLORCHANGE)
            {
                if (Visible)
                {
                    ReadLook();
                    Push();
                }
                return null;
            }
            return null;
        }

        private static int[] Point(long lparam)
        {
            return new int[] { (short)(lparam & 0xFFFF), (short)((lparam >> 16) & 0xFFFF) };
        }

        private int? Hit(long lparam)
        {
            if (Plan == null) return null;
            int[] point = Point(lparam);
            object target = PopupPlace.HitTest(Plan.Targets, point[0], point[1]);
            if (target == null) return null;
            return Convert.ToInt32(target);
        }

        private bool OnCard(long lparam)
        {
            if (Plan == null) return false;
            int[] point = Point(lparam), card = Plan.Card;
            return card[0] <= point[0] && point[0] < card[2] && card[1] <= point[1] && point[1] < card[3];
        }

        private void Leave(IntPtr? to)
        {
            bool was = Visible;
            Close();
            if (was && OnLeave != null && !(Owner != IntPtr.Zero && to.HasValue && to.Value == Owner)) OnLeave();
        }

        private IntPtr? Char(int code)
        {
            if (ChildOpen()) return child.Char(code);
            if (!Visible || code < 0x20) return IntPtr.Zero;
            KeyValuePair<int?, bool> found = MenuPlan.Letter(Entries, Selected, char.ConvertFromUtf32(code));
            if (found.Value) Activate(found.Key.Value, true);
            else Select(found.Key);
            return IntPtr.Zero;
        }

        private void MouseMove(long lparam)
        {
            MenuWindow parent = Parent;
            if (parent != null)
            {
                parent.Rest(parent.childIndex);
                parent.Select(parent.childIndex);
            }
            int? target = Hit(lparam);
            Rest(target);
            Select(target != null || !ChildOpen() ? target : childIndex);
            if (!tracking && hwnd != IntPtr.Zero) tracking = SurfaceScreen.TrackMouseLeave(hwnd);
        }

        private IntPtr? Key(int key)
        {
            bool rtl = Plan != null && Plan.Rtl == true;
            int onward = rtl ? VK_LEFT : VK_RIGHT, back = rtl ? VK_RIGHT : VK_LEFT;
            if (ChildOpen())
            {
                if (key == SurfaceNative.VK_ESCAPE || key == back)
                {
                    CloseChild();
                    return IntPtr.Zero;
                }
                return child.Key(key);
            }
            if (key == SurfaceNative.VK_ESCAPE) Dismiss();
            else if (key == onward)
            {
                Dictionary<string, object> entry = Selected != null ? EntryAt(Entries, Selected.Value) : null;
                if (entry != null && SurfaceMath.Truthy(SurfaceRender.Field(entry, "enabled")) && SurfaceMath.Truthy(SurfaceRender.Field(entry, "items")))
                    OpenChild(Selected.Value, true);
            }
            else if (key == SurfaceNative.VK_UP || key == SurfaceNative.VK_DOWN)
                Select(MenuPlan.Step(Entries, Selected, key == SurfaceNative.VK_UP));
            else if (key == VK_HOME || key == VK_END) Select(MenuPlan.End(Entries, key == VK_END));
            else if (key == SurfaceNative.VK_RETURN)
            {
                if (Selected != null) Activate(Selected.Value, true);
            }
            else return null;
            return IntPtr.Zero;
        }
    }
}

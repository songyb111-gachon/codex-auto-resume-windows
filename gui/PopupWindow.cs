// Codex Auto Resume - the popup's window: its class, the life of one popup, what it draws and how that reaches the screen
// (v0.6.27, S6.3d).
//
// ui/popup/window.py's Popup, hidden.py's PopupHidden and layers.py's PopupCard half, ported call for call; its messages
// are gui/PopupMessages.cs (messages.py), the other half of this partial class. It runs on the host's UI thread, which owns
// every window (P6-DESIGN 1.4).
//
// The popup's model stays in the core (DECISIONS.md, "The popup's model at the host boundary"): each `snapshot` event hands
// the window `popup` - car-surface's PopupModel.view, ready to draw - in this shape:
//
//   {"view": <PopupModel.view(now)>, "menus": [[interruption id, <row_menu(task, strings, default_tier)>], ...],
//    "read": <the core's first read is done>, "attention": <PopupModel.attention()>}
//
// so the window computes no row, status or menu. What a click means is read from what was drawn (action_for, over the
// view's tasks and paused), and done by posting one `popup {call, args}` action (args: the action's own fields after its
// kind, as perform unpacks them; the Dashboard's two are `open_dashboard`) through IHostActions on a worker thread; until
// the snapshot after the core's answer, the window shows that action as under way itself (begin's busy, the overlay below),
// as the reference's model does from the click to its outcome.
//
// Its clocks (`Monotonic`, `Now`) and where the screen is (`ScreenReader`) are fields, so the probe mode can drive it over
// a window that is made and never shown (SurfaceScreen.Probe); the live host leaves them as they are.
using System;
using System.Collections.Generic;
using System.Threading;

namespace CodexAutoResume
{
    /// A row's drawn menu as the popup opens it (menuwindow.Menu): MenuWindow on the live host.
    internal interface IRowMenu
    {
        IntPtr Hwnd { get; }
        bool Open(List<object> entries, Dictionary<string, object> strings, Action<int> run, int[] point, IntPtr owner,
                  Action onLeave);
        void Close();
        void Destroy();
    }

    internal sealed partial class PopupWindow : IDisposable
    {
        /// About thirty frames a second, and only while something moves (FRAME_MS).
        internal const int FrameMs = 33;
        /// The first opening waits this long for the core's first read at most (FIRST_READ_WAIT_MS).
        internal const int FirstReadWaitMs = 300;
        internal const int TimerTick = 1, TimerFrame = 2, TimerFirst = 3;
        /// model.py: a click on the icon that closed the window does not reopen it; a double click; Enter arriving twice.
        internal const double ClickAwaySeconds = 0.5, DoubleClickSeconds = 0.6, KeyRepeatSeconds = 0.3;
        /// brand.SPACING m and xs.
        internal const int SpacingM = 12, SpacingXs = 4;
        /// ROW_DIALOGS: the Dashboard dialogs a row's menu may open.
        internal static readonly string[] RowDialogs = { "message", "once_words" };
        /// The kinds perform does through the control layer, and the call each is (perform).
        internal static readonly Dictionary<string, string> Calls = new Dictionary<string, string> {
            { "read", null }, { "recovery", "set_interruption_recovery" }, { "enabled", "set_enabled" },
            { "postpone", "postpone" }, { "unpostpone", "unpostpone" }, { "release", "release_hold" },
            { "tier", "set_thread_tier" }, { "project", "set_project_rule" }, { "unsay", "set_once_words" } };
        /// ROW_ACTIONS: a row menu's control calls, each bound to its row.
        internal static readonly string[] RowActions = { "postpone", "unpostpone", "release", "tier", "project", "unsay" };

        private static int made;

        // ------------------------------------------------------------------ what it is given
        internal bool Days;
        internal Func<bool> Held;
        internal Action<string> Log = unused => { };
        internal Func<int[]> Anchor = null;
        internal Action ThemeMenu = null;
        internal Func<IRowMenu> MakeMenu = null;
        /// Where its actions go (the pump's), or null: then it waits for no read and posts nothing.
        internal IHostActions Actions = null;
        /// How a posted action runs off the UI thread (a pool thread on the live host; the probe queues it).
        internal Action<Action> Worker = work => ThreadPool.QueueUserWorkItem(unused => work());
        internal Func<double> Monotonic = TrayPlace.Monotonic;
        internal Func<double> Now = () => (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        internal Func<PopupWindow, PopupScreen> ScreenReader = ReadScreen;
        internal Func<bool> AskContrast = SurfaceTheme.HighContrast, AskReduced = SurfaceTheme.ReducedMotion;
        internal Func<bool?> AskAppsLight = SurfaceTheme.AppsUseLightTheme;
        internal Func<double> AskTextScale = SurfaceTheme.TextScale;
        /// WM_GETOBJECT's answer (SurfaceAccess) for this popup, or null to leave it to Windows.
        internal Func<PopupWindow, IntPtr, IntPtr, IntPtr?> Accessible = null;
        /// What a screen reader is told after each change (_speak, access.announce), or null.
        internal Action<PopupWindow> Speaking = null;
        /// What a screen reader was last told is on screen (_spoken): SurfaceAccess's, emptied as the popup hides.
        internal List<object> Spoken = new List<object>();

        // ------------------------------------------------------------------ its state
        internal Dictionary<string, object> Strings = new Dictionary<string, object>();
        internal string Locale = "en";
        internal string Letters = "";
        internal IntPtr Hwnd;
        internal bool Visible;
        private SurfaceNative.WndProc proc;
        private string className;
        private SurfaceRenderer renderer;
        private bool rounded;
        internal object[] PendingShow;               // (activate, origin) or null
        internal double? HiddenAt;
        private double? doubleClickAt, keyAt;
        internal SurfacePlan PaintedPlan;
        internal object Hover, Pressed, Focus;
        internal bool Keyboard;
        internal double Dpi = 96;
        internal Dictionary<string, object> Vm;
        internal SurfacePlan Plan;
        internal PopupScreen Screen;
        private readonly object guard = new object();
        private readonly Dictionary<long, object[]> results = new Dictionary<long, object[]>();
        private long sequence;
        internal int Ticks;
        internal bool FrameRunning;
        private int? frameMs;
        private string state;
        private double stateSince;
        internal bool Reduced, Contrast, Still;
        private bool? appsLight;
        private double text = 1.0;
        internal double? Fit;
        internal string Theme = "light", Design = Brand.DesignDefault;
        private bool? framedDark;
        private bool tracking;
        private object[] pendingStrings;             // (strings, locale, letters) or null
        internal bool StaticDirty = true;
        internal int[] Origin;
        internal int[] Home;
        internal int Below;
        private bool layered;
        private Dictionary<object, bool> switches;
        internal Dictionary<object, Glide> Glides = new Dictionary<object, Glide>();
        internal Dictionary<object, Face> Faces = new Dictionary<object, Face>();
        private Dictionary<object, string> faceStates;
        internal double[] Opening;                    // (started ms or NaN, rise) or null
        internal CardLayers Layers;
        internal bool Card;
        internal int Alpha = 255;
        internal bool Owed;
        internal int[] Rows;
        private object rowMenu;                       // null, an IRowMenu, or false once it broke
        // The core's popup (the shape above), the actions under way here and those the core has answered.
        private Dictionary<string, object> core;
        private readonly List<List<object>> begun = new List<List<object>>();
        private readonly List<List<object>> answered = new List<List<object>>();
        // What the last view drew: interruption id -> (thread id, checked), its tasks, and paused.
        private readonly Dictionary<object, object[]> drawn = new Dictionary<object, object[]>();
        private readonly Dictionary<object, Dictionary<string, object>> drawnTasks = new Dictionary<object, Dictionary<string, object>>();
        private object drawnPaused;
        // The seventh press (hidden.py).
        private int presses;
        private double? lastPress;
        internal double? SweepSince, AsideFrom;
        private bool asideShown;
        private double sceneSince = 0.0;

        /// A button part way to a new face: when it started, the (fill, edge) it left from, how long it takes.
        internal sealed class Face
        {
            internal double Started;
            internal int[][] From;
            internal double Length;
        }

        internal sealed class PopupScreen
        {
            internal int[] Icon, Cursor, Work, Monitor;
            internal double Dpi;
        }

        internal PopupWindow(Dictionary<string, object> strings = null, string locale = null, string letters = null,
                             bool days = false, Func<bool> held = null)
        {
            Days = days;
            Held = held;
            Strings = strings != null ? new Dictionary<string, object>(strings) : new Dictionary<string, object>();
            Locale = string.IsNullOrEmpty(locale) ? "en" : locale;
            Letters = letters ?? "";
            stateSince = TrayPlace.Monotonic();
        }

        internal SurfaceRenderer Renderer { get { return renderer; } }

        // ------------------------------------------------------------------ lifecycle
        internal void Create()
        {
            IntPtr instance = SurfaceNative.GetModuleHandleW(null);
            proc = WindowProc;
            bool canBeCard = SurfaceLayers.CanBeCard();
            var klass = new SurfaceNative.WNDCLASSW
            {
                Style = canBeCard ? 0 : SurfaceNative.CS_DROPSHADOW, LpfnWndProc = proc, HInstance = instance,
                HCursor = SurfaceNative.LoadCursorW(IntPtr.Zero, new IntPtr(SurfaceNative.IDC_ARROW)),
            };
            className = "CodexAutoResumePopup-" + System.Diagnostics.Process.GetCurrentProcess().Id + "-"
                        + Interlocked.Increment(ref made);
            klass.LpszClassName = className;
            if (SurfaceNative.RegisterClassW(ref klass) == 0)
            {
                className = null;
                throw new InvalidOperationException("RegisterClassW");
            }
            try
            {
                IntPtr owner;
                using (new SurfaceNative.PerMonitorDpi())
                {
                    owner = klass.Style == 0 ? MakeLayers(instance) : IntPtr.Zero;
                    uint style = SurfaceNative.WS_EX_TOOLWINDOW | SurfaceNative.WS_EX_TOPMOST
                                 | (owner != IntPtr.Zero ? SurfaceNative.WS_EX_LAYERED : 0);
                    Hwnd = SurfaceNative.CreateWindowExW(style, className, PopupWords.Say(Strings, "tray.title"),
                                                         SurfaceNative.WS_POPUP, 0, 0, PopupLayout.Width, 120, owner,
                                                         IntPtr.Zero, instance, IntPtr.Zero);
                }
                if (Hwnd == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
                renderer = SurfaceRenderer.Open();
                renderer.Letters = Letters;
                Card = renderer.Lone = owner != IntPtr.Zero;
                if (!Card)
                {
                    if (klass.Style == 0) ClassShadow();
                    RoundCorners();
                }
                uint dpi = SurfaceScreen.DpiForWindow(Hwnd);
                Dpi = dpi != 0 ? dpi : 96;
            }
            catch (Exception)
            {
                Dispose();
                throw;
            }
        }

        /// destroy: its row menu, the screen reader's hold, the windows, their timers, the layers, the renderer, the class.
        public void Dispose()
        {
            object menu = rowMenu;
            rowMenu = null;
            var drawnMenu = menu as IRowMenu;
            if (drawnMenu != null)
            {
                try
                {
                    drawnMenu.Destroy();
                }
                catch (Exception exc)
                {
                    Log("tray popup menu cleanup failed (" + TipCard.PythonName(exc) + ")");
                }
            }
            SurfaceAccessHooks.Disconnect(this);
            IntPtr hwnd = Hwnd;
            Hwnd = IntPtr.Zero;
            Visible = false;
            if (hwnd != IntPtr.Zero)
            {
                foreach (int timer in SurfaceMath.Three(TimerTick, TimerFrame, TimerFirst)) SurfaceScreen.KillTimer(hwnd, timer);
                SurfaceNative.DestroyWindow(hwnd);
            }
            CardLayers layers = Layers;
            Layers = null;
            Card = false;
            if (layers != null) layers.Dispose();
            FrameRunning = false;
            Opening = null;
            layered = false;
            if (renderer != null)
            {
                renderer.Dispose();
                renderer = null;
            }
            Plan = null;
            Vm = null;
            StaticDirty = true;
            framedDark = null;
            switches = null;
            Glides = new Dictionary<object, Glide>();
            if (className != null)
            {
                SurfaceNative.UnregisterClassW(className, SurfaceNative.GetModuleHandleW(null));
                className = null;
            }
        }

        /// set_strings: a new catalog, its locale and letters (the `strings` event), applied by the next rebuild.
        internal void SetStrings(Dictionary<string, object> strings, string locale, string letters)
        {
            lock (guard)
                pendingStrings = new object[] { strings != null ? new Dictionary<string, object>(strings) : new Dictionary<string, object>(),
                                                 string.IsNullOrEmpty(locale) ? "en" : locale, letters ?? "" };
            if (Hwnd != IntPtr.Zero) SurfaceScreen.Post(Hwnd, SurfaceNative.WM_POPUP_STRINGS, 0, 0);
        }

        /// What the icon reads while the popup is open: the core's own rule (model.attention).
        internal bool Attention()
        {
            return core != null && SurfaceMath.Truthy(SurfaceRender.Field(core, "attention"));
        }

        // ------------------------------------------------------------------ the core's popup
        /// The `snapshot` event's popup: the view to draw from now. The actions the core has answered stop being shown as
        /// under way here; a first opening waiting for it opens, an open popup is brought up to date.
        internal void Snapshot(Dictionary<string, object> popup)
        {
            if (popup == null) return;
            foreach (List<object> key in answered) Remove(begun, key);
            answered.Clear();
            core = popup;
            if (!SurfaceMath.Truthy(SurfaceRender.Field(popup, "read"))) return;
            // As the reference's read result does (_finished): a first opening waiting for it opens, an open popup is
            // brought up to date, whether or not anything in the view changed.
            if (PendingShow != null) Present((bool)PendingShow[0], (int[])PendingShow[1]);
            else if (Visible) Update();
        }

        /// model.view as the core gave it, with what is under way here shown as busy (begin's set), and what was drawn kept
        /// for the clicks (drawn, drawn_tasks, drawn_paused).
        internal Dictionary<string, object> View()
        {
            object given = core != null ? SurfaceRender.Field(core, "view") : null;
            var vm = given is Dictionary<string, object> ? (Dictionary<string, object>)Copy(given) : new Dictionary<string, object>();
            var tasks = SurfaceRender.Field(vm, "tasks") as List<object> ?? new List<object>();
            drawn.Clear();
            drawnTasks.Clear();
            foreach (object one in tasks)
            {
                var task = one as Dictionary<string, object>;
                if (task == null) continue;
                object id = SurfaceRender.Field(task, "interruption_id");
                if (Contains(begun, new List<object> { "recovery", id })) task["busy"] = true;
                drawn[id] = new[] { SurfaceRender.Field(task, "thread_id"), SurfaceRender.Field(task, "checked") };
                drawnTasks[id] = task;
            }
            if (Contains(begun, new List<object> { "enabled" })) vm["toggle_busy"] = true;
            drawnPaused = SurfaceRender.Field(vm, "paused");
            return vm;
        }

        /// action_for: what a click on `target` asks for, from what was drawn - or null.
        internal List<object> ActionFor(object target)
        {
            var aimed = target as SurfaceTarget;
            if (aimed == null) return null;
            object[] row;
            if (aimed.Name == "check" && aimed.Keyed && drawn.TryGetValue(aimed.Key, out row))
                return new List<object> { "recovery", aimed.Key, row[0], !SurfaceMath.Truthy(row[1]) };
            if (aimed.Name == "toggle" && drawnPaused != null) return new List<object> { "enabled", SurfaceMath.Truthy(drawnPaused) };
            if (aimed.Name == "dashboard") return new List<object> { "dashboard" };
            return null;
        }

        /// menu_for: the row menu of a task as it was last drawn, as the core made it, or none for a row that was not.
        internal List<object> MenuFor(object id)
        {
            if (!drawnTasks.ContainsKey(id)) return new List<object>();
            foreach (object pair in SurfaceRender.Field(core, "menus") as List<object> ?? new List<object>())
            {
                var both = pair as List<object>;
                if (both != null && both.Count == 2 && Equals(both[0], id)) return both[1] as List<object> ?? new List<object>();
            }
            return new List<object>();
        }

        /// busy_key: ("recovery", id), ("enabled",), ("row", id) or null.
        internal static List<object> BusyKey(List<object> action)
        {
            if (action == null || action.Count == 0) return null;
            string kind = action[0] as string;
            if (kind == "recovery") return new List<object> { "recovery", action[1] };
            if (kind == "enabled") return new List<object> { "enabled" };
            if (Array.IndexOf(RowActions, kind) >= 0) return new List<object> { "row", action[1] };
            return null;
        }

        /// begin: mark an action as under way here; false if the same one already is.
        internal bool Begin(List<object> action)
        {
            List<object> key = BusyKey(action);
            if (key == null) return true;
            if (Contains(begun, key)) return false;
            begun.Add(key);
            return true;
        }

        private static bool Same(List<object> one, List<object> other)
        {
            if (one.Count != other.Count) return false;
            for (int i = 0; i < one.Count; i++)
                if (!Equals(one[i], other[i])) return false;
            return true;
        }

        private static bool Contains(List<List<object>> keys, List<object> key)
        {
            foreach (List<object> one in keys)
                if (Same(one, key)) return true;
            return false;
        }

        private static void Remove(List<List<object>> keys, List<object> key)
        {
            for (int i = 0; i < keys.Count; i++)
                if (Same(keys[i], key))
                {
                    keys.RemoveAt(i);
                    return;
                }
        }

        /// A JSON value copied, so what the window changes in its view is its own.
        internal static object Copy(object value)
        {
            var map = value as Dictionary<string, object>;
            if (map != null)
            {
                var copy = new Dictionary<string, object>();
                foreach (KeyValuePair<string, object> pair in map) copy[pair.Key] = Copy(pair.Value);
                return copy;
            }
            var list = value as List<object>;
            if (list != null) return list.ConvertAll(Copy);
            return value;
        }

        // ---------------------------------------------------------------- the icon asks
        /// select_action: what a select on the icon does - "show", "hide" or "none".
        internal static string SelectAction(bool visible, double now, double? hiddenAt, double? doubleClickAt, double? previousKeyAt,
                                            bool keyboard)
        {
            if (keyboard && previousKeyAt.HasValue && 0 <= now - previousKeyAt.Value && now - previousKeyAt.Value < KeyRepeatSeconds)
                return "none";
            if (doubleClickAt.HasValue && 0 <= now - doubleClickAt.Value && now - doubleClickAt.Value < DoubleClickSeconds)
                return visible ? "none" : "show";
            if (visible) return "hide";
            if (hiddenAt.HasValue && 0 <= now - hiddenAt.Value && now - hiddenAt.Value < ClickAwaySeconds) return "none";
            return "show";
        }

        internal void OnSelect(bool keyboard = false)
        {
            double now = Monotonic();
            string choice = SelectAction(Visible || PendingShow != null, now, HiddenAt, doubleClickAt, keyAt, keyboard);
            if (keyboard) keyAt = now;
            if (choice == "show") Show(keyboard);
            else if (choice == "hide") Hide();
        }

        internal void OnDoubleClick()
        {
            doubleClickAt = Monotonic();
            if (!Visible && PendingShow == null) Show();
        }

        internal void Show(bool keyboard = false, bool activate = true, int[] origin = null)
        {
            if (Hwnd == IntPtr.Zero) Create();
            Keyboard = keyboard;
            Hover = Pressed = null;
            Focus = null;
            ReadLook();
            RequestRead();
            if ((core == null || !SurfaceMath.Truthy(SurfaceRender.Field(core, "read"))) && Actions != null)
            {
                PendingShow = new object[] { activate, origin };
                SurfaceScreen.SetTimer(Hwnd, TimerFirst, FirstReadWaitMs);
                return;
            }
            Present(activate, origin);
        }

        internal void Hide()
        {
            PendingShow = null;
            var menu = rowMenu as IRowMenu;
            if (menu != null) menu.Close();
            IntPtr hwnd = Hwnd;
            if (hwnd == IntPtr.Zero) return;
            foreach (int timer in SurfaceMath.Three(TimerTick, TimerFrame, TimerFirst)) SurfaceScreen.KillTimer(hwnd, timer);
            FrameRunning = false;
            if (Visible)
            {
                Visible = false;
                SurfaceScreen.ShowWindow(hwnd, SurfaceNative.SW_HIDE);
                if (Layers != null)
                {
                    Layers.Hide();
                    Layers.Forget();
                }
                HiddenAt = Monotonic();
            }
            EndOpening();
            Faces = new Dictionary<object, Face>();
            faceStates = null;
            Hover = Pressed = Focus = null;
            PaintedPlan = null;
            switches = null;
            Glides = new Dictionary<object, Glide>();
            Spoken = new List<object>();
            Fit = null;
        }

        // ------------------------------------------------------------------ appearance
        /// _read_look: High Contrast, Windows' app mode, its motion setting and its text size, asked on every opening and
        /// whenever Windows says a setting changed, never per frame.
        internal void ReadLook()
        {
            double asked = AskTextScale();
            if (asked != text)
            {
                text = asked;
                Fit = null;
            }
            Contrast = AskContrast();
            appsLight = AskAppsLight();
            Reduced = AskReduced() || Contrast;
            Still = AskStill();
            Theme = SurfaceTheme.EffectiveTheme(SurfaceTheme.ThemeSetting, appsLight);
            Design = SurfaceTheme.DesignSetting;
        }

        private bool AskStill()
        {
            try
            {
                return Held != null && Held();
            }
            catch (Exception)
            {
                return false;
            }
        }

        internal bool Holds() { return Reduced || Still; }

        private void FollowTheme()
        {
            string theme = SurfaceTheme.EffectiveTheme(SurfaceTheme.ThemeSetting, appsLight), design = SurfaceTheme.DesignSetting;
            if (theme != Theme || design != Design)
            {
                Theme = theme;
                Design = design;
                StaticDirty = true;
            }
        }

        /// follow_settings: the theme, the design and Reduce motion a read of the stored settings says (the `settings`
        /// event); the language comes as its own `strings` event, the host having no catalogs.
        internal void FollowSettings(Dictionary<string, object> values)
        {
            if (values == null) return;
            SurfaceTheme.AdoptSettings(values);
            Reduced = AskReduced() || Contrast;
        }

        // ------------------------------------------------------------------ presenting
        internal static PopupScreen ReadScreen(PopupWindow popup)
        {
            using (new SurfaceNative.PerMonitorDpi())
            {
                int[] icon = popup.Anchor != null ? popup.Anchor() : null;
                SurfaceNative.POINT point;
                SurfaceNative.GetCursorPos(out point);
                int[] cursor = { point.X, point.Y };
                var probe = icon != null ? new SurfaceNative.RECT(icon[0], icon[1], icon[2], icon[3])
                                         : new SurfaceNative.RECT(cursor[0], cursor[1], cursor[0] + 1, cursor[1] + 1);
                IntPtr monitor = SurfaceNative.MonitorFromRect(ref probe, SurfaceNative.MONITOR_DEFAULTTONEAREST);
                var info = new SurfaceNative.MONITORINFO();
                info.CbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf(info);
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
                SurfaceNative.RECT work = info.RcWork, whole = info.RcMonitor;
                return new PopupScreen
                {
                    Icon = icon, Cursor = cursor, Dpi = dpi != 0 ? dpi : (popup.Dpi != 0 ? popup.Dpi : 96),
                    Work = new[] { work.Left, work.Top, work.Right, work.Bottom },
                    Monitor = new[] { whole.Left, whole.Top, whole.Right, whole.Bottom },
                };
            }
        }

        internal void Present(bool activate = true, int[] origin = null)
        {
            PendingShow = null;
            SurfaceScreen.KillTimer(Hwnd, TimerFirst);
            Screen = ScreenReader(this);
            Dpi = Screen.Dpi;
            Fit = null;
            SurfacePlan plan = Rebuild(Now());
            if (Keyboard && Focus == null)
            {
                List<object> order = PopupPlace.FocusOrder(plan.Targets);
                Focus = order.Count > 0 ? order[0] : null;
            }
            Move(plan, origin);
            FrameTheme();
            StartOpening();
            Visible = true;
            if (Card) Push();
            if (Card) Layers.Show();
            else SurfaceScreen.InvalidateRect(Hwnd);
            SurfaceScreen.ShowWindow(Hwnd, activate ? SurfaceNative.SW_SHOW : SurfaceNative.SW_SHOWNOACTIVATE);
            if (activate)
            {
                SurfaceScreen.SetForegroundWindow(Hwnd);
                SurfaceScreen.SetFocus(Hwnd);
            }
            SurfaceScreen.SetTimer(Hwnd, TimerTick, 1000);
            SyncFrames();
            if (!Card) SurfaceScreen.UpdateWindow(Hwnd);
            Speak();
        }

        /// _move: beside the icon, SPACING m from the taskbar and the work area's edges - the card's own edge, or the plain
        /// window's whole canvas; `origin`, and Home, are then the card's corner.
        internal void Move(SurfacePlan plan, int[] origin = null)
        {
            int width = plan.Size[0], height = plan.Size[1];
            if (Card)
            {
                int[] card = plan.Card;
                width = card[2] - card[0];
                height = card[3] - card[1];
            }
            int x, y;
            if (origin != null)
            {
                x = origin[0];
                y = origin[1];
            }
            else
            {
                int gap = SurfaceMath.Round(SpacingM * Dpi / 96.0);
                string edge;
                int[] at = PopupPlace.Place(new[] { width, height }, Screen.Work, Screen.Monitor, Screen.Icon, Screen.Cursor, gap,
                                            out edge);
                x = at[0];
                y = at[1];
            }
            Origin = origin;
            Home = new[] { x, y };
            if (Card)
            {
                if (Visible) Push();
                return;
            }
            SurfaceScreen.SetWindowPos(Hwnd, SurfaceNative.HWND_TOPMOST, x, y + Below, width, height, SurfaceNative.SWP_NOACTIVATE);
            Shape(width, height);
        }

        internal SurfacePlan Rebuild(double now)
        {
            object[] strings;
            lock (guard)
            {
                strings = pendingStrings;
                pendingStrings = null;
            }
            if (strings != null)
            {
                Strings = (Dictionary<string, object>)strings[0];
                Locale = (string)strings[1];
                Letters = (string)strings[2];
                if (renderer != null) renderer.Letters = Letters;
            }
            FollowTheme();
            Dictionary<string, object> vm = View();
            DayView(vm, now);
            string light = SurfaceRender.Field(vm, "light") as string;
            if (light != state)
            {
                state = light;
                stateSince = Monotonic();
            }
            if (!Fit.HasValue) Fit = Fitting(vm);
            SurfacePlan plan = renderer.Layout(vm, Dpi / 96.0 * Fit.Value, Locale);
            Vm = vm;
            Plan = plan;
            StaticDirty = true;
            FollowSwitches(plan);
            return plan;
        }

        /// _fitting: Windows' text size, but never larger than the screen it opens on holds; 1 without a screen.
        private double Fitting(Dictionary<string, object> vm)
        {
            if (text <= 1.0 || Screen == null) return 1.0;
            int[] work = Screen.Work;
            int gap = 2 * SurfaceMath.Round(SpacingM * Dpi / 96.0);
            int[] usual = renderer.Layout(vm, Dpi / 96.0, Locale).Size;
            return SurfaceTheme.Fitting(text, new double[] { usual[0], usual[1] },
                                        new double[] { work[2] - work[0] - gap, work[3] - work[1] - gap });
        }

        private void FollowSwitches(SurfacePlan plan)
        {
            var seen = new Dictionary<object, bool>();
            foreach (PlanItem item in plan.Items)
                if (item.Kind == "switch") seen[item["target"]] = SurfaceMath.Truthy(item["checked"]);
            Dictionary<object, bool> previous = Visible ? switches : null;
            Glides = PopupMotion.NextGlides(seen, previous, Glides, Monotonic() * 1000.0, Visible && !Holds());
            switches = Visible ? seen : null;
        }

        private Dictionary<object, double> GlideAmounts()
        {
            double now = Monotonic() * 1000.0;
            var amounts = new Dictionary<object, double>();
            foreach (object target in new List<object>(Glides.Keys))
            {
                double[] amount = PopupMotion.GlideAmount(Glides[target], now);
                if (amount[1] != 0.0) Glides.Remove(target);
                else amounts[target] = amount[0];
            }
            return amounts;
        }

        internal void Update(double? now = null)
        {
            if (Hwnd == IntPtr.Zero || renderer == null) return;
            int[] previous = Plan != null ? Plan.Size : null;
            SurfacePlan plan = Rebuild(now ?? Now());
            if (Visible && (previous == null || plan.Size[0] != previous[0] || plan.Size[1] != previous[1]) && Screen != null)
                Move(plan, Origin);
            List<object> order = PopupPlace.FocusOrder(plan.Targets);
            if (Focus != null && !order.Contains(Focus)) Focus = order.Count > 0 && Keyboard ? order[0] : null;
            if (Visible) FrameTheme();
            SyncFrames();
            Redraw();
            Speak();
        }

        private void Speak()
        {
            if (Speaking != null) Speaking(this);
        }

        private double SinceStateMs() { return (Monotonic() - stateSince) * 1000.0; }

        internal void SyncFrames()
        {
            if (Holds() && (Opening != null || Faces.Count > 0))
            {
                EndOpening();
                Faces = new Dictionary<object, Face>();
            }
            bool quick = Faces.Count > 0 || Opening != null;
            bool wanted = Visible && Vm != null
                          && (Glides.Count > 0 || quick || PopupMotion.Animates(state, Holds())
                              || (SurfaceMath.Truthy(SurfaceRender.Field(Vm, "scene")) && !Holds()) || Sweeping());
            int interval = quick ? PopupMotion.GlideFrameMs : FrameMs;
            if (wanted && (!FrameRunning || interval != frameMs))
            {
                SurfaceScreen.SetTimer(Hwnd, TimerFrame, interval);
                FrameRunning = true;
                frameMs = interval;
            }
            else if (!wanted && FrameRunning)
            {
                SurfaceScreen.KillTimer(Hwnd, TimerFrame);
                FrameRunning = false;
                frameMs = null;
            }
        }

        /// The halo for this instant, its cycle starting with its state.
        internal LightFrame Frame()
        {
            if (Vm == null) return null;
            return PopupMotion.Halo(state, SinceStateMs(), Holds(), Design);
        }

        /// render: the current view drawn into the canvas, which is returned.
        internal SurfaceCanvas Render()
        {
            if (Plan == null) Rebuild(Now());
            if (renderer.Theme != Theme || renderer.Design != Design || renderer.Contrast != Contrast)
            {
                renderer.Theme = Theme;
                renderer.Design = Design;
                renderer.Contrast = Contrast;
                StaticDirty = true;
            }
            if (Glides.Count > 0 || Faces.Count > 0) StaticDirty = true;
            Dictionary<object, ButtonFace> faces = FaceGlides();
            StepHidden();
            if (StaticDirty || renderer.HaloPlan != Plan)
            {
                StaticDirty = false;
                Rows = null;
                return renderer.Draw(Plan, Frame(), Hover, Pressed, Keyboard ? Focus : null, GlideAmounts(),
                                     SceneMs(Holds(), sceneSince), faces);
            }
            SurfaceCanvas canvas = renderer.DrawHalo(Plan, Frame());
            Rows = renderer.HaloRows;
            PlanItem scene = null;
            foreach (PlanItem item in Plan.Items)
                if (item.Kind == "scene")
                {
                    scene = item;
                    break;
                }
            if (scene == null || !SurfaceMath.Truthy(SurfaceRender.Field(Vm, "scene")) || Holds()) return canvas;
            double[] rect = SurfaceRenderer.Box(scene["rect"]);
            int top = (int)rect[1], bottom = (int)Math.Ceiling(rect[3]);
            Rows = Rows != null ? new[] { Math.Min(Rows[0], top), Math.Max(Rows[1], bottom) } : new[] { top, bottom };
            return renderer.DrawScene(Plan, SceneMs(false, sceneSince));
        }

        /// How far on the day's scene a whole frame drawn now has it (render's scene_ms), for the live-path proof.
        internal double SceneNowMs() { return SceneMs(Holds(), sceneSince); }

        /// motion.scene_ms: how far on the day's scene is - at its first instant, and still, while held.
        private double SceneMs(bool reduced, double since)
        {
            return reduced ? 0.0 : (Monotonic() - since) * 1000.0;
        }

        private void Invalidate()
        {
            StaticDirty = true;
            Redraw();
        }

        // ------------------------------------------------------------ a row's own menu (v0.6.11)
        private void ContextMenu(long lparam)
        {
            SurfacePlan plan = PaintedPlan;
            if (plan == null || Hwnd == IntPtr.Zero) return;
            var point = new SurfaceNative.POINT();
            object key = null;
            if ((lparam & 0xFFFFFFFF) == 0xFFFFFFFF)
            {
                var focus = Focus as SurfaceTarget;
                key = focus != null && focus.Name == "check" ? focus.Key : null;
                int[] rect = null;
                if (plan.Rows != null)
                    foreach (KeyValuePair<object, int[]> row in plan.Rows)
                        if (Equals(row.Key, key)) rect = row.Value;
                if (rect == null) return;
                int[] offset = ClientOffset();
                point.X = (plan.Rtl == true ? rect[2] : rect[0]) - offset[0];
                point.Y = rect[1] - offset[1];
                SurfaceScreen.ClientToScreen(Hwnd, ref point);
            }
            else
            {
                point.X = (short)(lparam & 0xFFFF);
                point.Y = (short)((lparam >> 16) & 0xFFFF);
                var inside = new SurfaceNative.POINT { X = point.X, Y = point.Y };
                SurfaceScreen.ScreenToClient(Hwnd, ref inside);
                int[] offset = ClientOffset();
                inside.X += offset[0];
                inside.Y += offset[1];
                if (plan.Rows != null)
                    foreach (KeyValuePair<object, int[]> row in plan.Rows)
                    {
                        int[] r = row.Value;
                        if (r[0] <= inside.X && inside.X < r[2] && r[1] <= inside.Y && inside.Y < r[3])
                        {
                            key = row.Key;
                            break;
                        }
                    }
            }
            List<object> entries = key != null ? MenuFor(key) : new List<object>();
            if (entries.Count == 0) return;
            var actions = new Dictionary<int, object>();
            List<object> numbered = MenuPlan.Numbered(entries, actions);
            Action<int> run = command =>
            {
                object chosen;
                var action = actions.TryGetValue(command, out chosen) ? chosen as List<object> : null;
                if (action == null || !Begin(action)) return;
                if ((action[0] as string) == "dashboard_row") Hide();
                Run(action);
                Update();
            };
            if (DrawRowMenu(numbered, run, new[] { point.X, point.Y })) return;
            if (ThemeMenu != null)
            {
                try
                {
                    ThemeMenu();
                }
                catch (Exception exc)
                {
                    Log("tray popup menu theme failed (" + TipCard.PythonName(exc) + ")");
                }
            }
            var menus = new List<IntPtr>();
            Func<List<object>, IntPtr> build = null;
            build = items =>
            {
                IntPtr menu = SurfaceNative.CreatePopupMenu();
                menus.Add(menu);
                foreach (object one in items)
                {
                    var entry = one as Dictionary<string, object>;
                    if (entry == null)
                    {
                        SurfaceNative.AppendMenuW(menu, SurfaceNative.MF_SEPARATOR, UIntPtr.Zero, null);
                        continue;
                    }
                    uint flags = SurfaceNative.MF_STRING | (SurfaceMath.Truthy(entry["enabled"]) ? 0 : SurfaceNative.MF_GRAYED)
                                 | (SurfaceMath.Truthy(entry["checked"]) ? SurfaceNative.MF_CHECKED : 0);
                    var sub = entry["items"] as List<object>;
                    if (SurfaceMath.Truthy(sub))
                    {
                        SurfaceNative.AppendMenuW(menu, flags | SurfaceNative.MF_POPUP, new UIntPtr((ulong)build(sub).ToInt64()),
                                                  PopupWords.Str(entry["text"]));
                        continue;
                    }
                    SurfaceNative.AppendMenuW(menu, flags, new UIntPtr(Convert.ToUInt64(entry["id"])), PopupWords.Str(entry["text"]));
                }
                return menu;
            };
            int picked;
            try
            {
                uint direction = plan.Rtl == true ? SurfaceNative.TPM_LAYOUTRTL | SurfaceNative.TPM_RIGHTALIGN : 0;
                picked = SurfaceNative.TrackPopupMenu(build(numbered), SurfaceNative.TPM_RIGHTBUTTON | SurfaceNative.TPM_RETURNCMD
                                                      | SurfaceNative.TPM_NONOTIFY | direction, point.X, point.Y, 0, Hwnd, IntPtr.Zero);
                SurfaceScreen.Post(Hwnd, 0, 0, 0);
            }
            finally
            {
                SurfaceNative.DestroyMenu(menus[0]);
            }
            run(picked);
        }

        /// _draw_row_menu: the row's menu drawn at `point`; false when Windows' menu is to open instead.
        private bool DrawRowMenu(List<object> entries, Action<int> run, int[] point)
        {
            if (MakeMenu == null || rowMenu is bool || Hwnd == IntPtr.Zero) return false;
            try
            {
                if (rowMenu == null) rowMenu = MakeMenu();
                return ((IRowMenu)rowMenu).Open(entries, Strings, run, point, Hwnd, Hide);
            }
            catch (Exception exc)
            {
                Log("tray popup menu drawn unavailable (" + TipCard.PythonName(exc) + ")");
                var menu = rowMenu as IRowMenu;
                rowMenu = false;
                if (menu != null)
                {
                    try
                    {
                        menu.Destroy();
                    }
                    catch (Exception)
                    {
                    }
                }
                return false;
            }
        }

        private bool MenuHas(IntPtr hwnd)
        {
            var menu = rowMenu as IRowMenu;
            return menu != null && hwnd != IntPtr.Zero && menu.Hwnd == hwnd;
        }

        internal void Activate(object target)
        {
            List<object> action = ActionFor(target);
            if (action == null) return;
            if ((action[0] as string) == "dashboard")
            {
                Hide();
                Run(action);
                return;
            }
            if (!Begin(action)) return;
            Run(action);
            Update();
        }

        // ------------------------------------------------------------------ the seventh press (hidden.py)
        /// day_view: the day's scene, and the sentence in the state line while it is its moment.
        private void DayView(Dictionary<string, object> vm, double now)
        {
            vm["scene"] = Days && !Contrast && Design != "classic" ? (object)TipCard.DayLookAt(now) : null;
            vm["state_text"] = AsideWords(SurfaceRender.Field(vm, "state_text"));
        }

        private void TitlePressed(long lparam, double nowMs)
        {
            SurfacePlan plan = PaintedPlan;
            if (plan == null) return;
            int[] point = ClientPoint(lparam);
            foreach (PlanItem item in plan.Items)
                if (item.Kind == "title_press")
                {
                    double[] rect = SurfaceRenderer.Box(item["rect"]);
                    if (rect[0] <= point[0] && point[0] < rect[2] && rect[1] <= point[1] && point[1] < rect[3]) TitlePress(nowMs);
                    return;
                }
        }

        /// brand.PressRun.press: seven presses, each within 1.8 s of the last, say so once and start again.
        private bool Press(double milliseconds)
        {
            presses = lastPress.HasValue && milliseconds - lastPress.Value <= 1800 ? presses + 1 : 1;
            lastPress = milliseconds;
            if (presses < 7) return false;
            presses = 0;
            return true;
        }

        private void TitlePress(double nowMs)
        {
            if (!Press(nowMs)) return;
            bool moves = !Holds() && !Contrast;
            SweepSince = moves ? (double?)nowMs : null;
            AsideFrom = nowMs + (moves ? 850 : 0);
            SyncFrames();
            Update();
        }

        internal bool Sweeping() { return SweepSince.HasValue; }

        private object AsideWords(object stateText)
        {
            if (!AsideFrom.HasValue) return stateText;
            double now = Monotonic() * 1000.0;
            if (now < AsideFrom.Value) return stateText;
            if (now >= AsideFrom.Value + 4150)
            {
                AsideFrom = null;
                return stateText;
            }
            object aside;
            return Strings.TryGetValue("status.aside", out aside) ? aside : stateText;
        }

        private void StepHidden()
        {
            if (SweepSince.HasValue)
            {
                double elapsed = Monotonic() * 1000.0 - SweepSince.Value;
                if (elapsed >= SurfaceRenderer.SweepSecondRingMs + SurfaceRenderer.SweepRingMs || Holds() || !Visible)
                {
                    SweepSince = null;
                    renderer.SweepMs = null;
                }
                else renderer.SweepMs = elapsed;
            }
            else renderer.SweepMs = null;
            bool due = AsideFrom.HasValue && Monotonic() * 1000.0 >= AsideFrom.Value;
            bool ended = due && Monotonic() * 1000.0 >= AsideFrom.Value + 4150;
            if ((due && !asideShown) || ended)
            {
                asideShown = due && !ended;
                Plan = null;
                Rebuild(Now());
                StaticDirty = true;
            }
        }

        // ------------------------------------------------------------------ the card (layers.py's PopupCard)
        private IntPtr MakeLayers(IntPtr instance)
        {
            uint style = SurfaceNative.WS_EX_LAYERED | TipCard.WS_EX_TRANSPARENT | SurfaceNative.WS_EX_NOACTIVATE
                         | SurfaceNative.WS_EX_TOOLWINDOW | SurfaceNative.WS_EX_TOPMOST;
            IntPtr shadow = SurfaceNative.CreateWindowExW(style, className, "", SurfaceNative.WS_POPUP, 0, 0, 1, 1, IntPtr.Zero,
                                                          IntPtr.Zero, instance, IntPtr.Zero);
            if (shadow == IntPtr.Zero)
            {
                Log("tray popup card window unavailable (CreateWindowExW)");
                return IntPtr.Zero;
            }
            try
            {
                Layers = new CardLayers(shadow);
            }
            catch (Exception exc)
            {
                Log("tray popup card window unavailable (" + TipCard.PythonName(exc) + ")");
                SurfaceNative.DestroyWindow(shadow);
                return IntPtr.Zero;
            }
            return shadow;
        }

        /// _redraw: the picture is owed - a plain window's invalidated, the card's pushed once the messages already queued
        /// are handled (WM_POPUP_PAINT).
        private void Redraw()
        {
            if (Hwnd == IntPtr.Zero) return;
            if (!Card) SurfaceScreen.InvalidateRect(Hwnd);
            else if (!Owed)
            {
                Owed = true;
                SurfaceScreen.Post(Hwnd, WM_POPUP_PAINT, 0, 0);
            }
        }

        internal const int WM_POPUP_PAINT = SurfaceNative.WM_APP + 4;

        private void Push()
        {
            Owed = false;
            if (!Card || Hwnd == IntPtr.Zero || renderer == null || !Visible || Home == null) return;
            SurfaceCanvas canvas = Render();
            CardLayers layers = Layers;
            layers.Shade(renderer, Plan);
            if (layers.Push(Hwnd, canvas, Plan, new double[] { Home[0], Home[1] + Below }, Alpha, Rows))
            {
                PaintedPlan = Plan;
                return;
            }
            Plain("UpdateLayeredWindowIndirect");
        }

        private void Plain(string why)
        {
            Log("tray popup card window unavailable (" + why + ")");
            EndOpening();
            Card = false;
            Alpha = 255;
            Owed = false;
            if (Layers != null) Layers.Hide();
            if (renderer != null) renderer.Lone = false;
            SurfaceScreen.SetExStyle(Hwnd, SurfaceScreen.GetExStyle(Hwnd) & ~(int)SurfaceNative.WS_EX_LAYERED);
            ClassShadow();
            RoundCorners();
            StaticDirty = true;
            if (Plan != null && Screen != null)
            {
                int[] card = Plan.Card, origin = Origin;
                Move(Plan, origin == null ? null : new[] { origin[0] - card[0], origin[1] - card[1] });
                FrameTheme();
            }
            SurfaceScreen.InvalidateRect(Hwnd);
        }

        private void RoundCorners()
        {
            try
            {
                rounded = SurfaceScreen.Dwm(Hwnd, SurfaceNative.DWMWA_WINDOW_CORNER_PREFERENCE, SurfaceNative.DWMWCP_ROUND) == 0;
            }
            catch (Exception)
            {
                rounded = false;
            }
        }

        private void Shape(int width, int height)
        {
            if (rounded || Card) return;
            int radius = SurfaceMath.Round(8 * Dpi / 96.0) * 2;
            SurfaceScreen.RoundRegion(Hwnd, width, height, radius);
        }

        /// _frame_theme: tell DWM whether the plain window is dark, so the hairline Windows 11 draws round it matches.
        private void FrameTheme()
        {
            bool dark = SurfaceTheme.Appearance(Theme, null, Contrast) == "dark";
            if (Hwnd == IntPtr.Zero || framedDark == dark || Card) return;
            framedDark = dark;
            try
            {
                foreach (int attribute in new[] { SurfaceNative.DWMWA_USE_IMMERSIVE_DARK_MODE,
                                                  SurfaceNative.DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 })
                    if (SurfaceScreen.Dwm(Hwnd, attribute, dark ? 1 : 0) == 0) break;
            }
            catch (Exception)
            {
            }
        }

        private void ClassShadow()
        {
            SurfaceScreen.AddClassStyle(Hwnd, SurfaceNative.CS_DROPSHADOW);
        }

        /// Where the card's window's (0, 0) is on the plan: the card's corner; the plain window's is the plan's own.
        internal int[] ClientOffset()
        {
            SurfacePlan plan = PaintedPlan ?? Plan;
            return Card && plan != null ? new[] { plan.Card[0], plan.Card[1] } : new[] { 0, 0 };
        }

        /// A mouse message's point, in the plan's pixels.
        internal int[] ClientPoint(long lparam)
        {
            int[] offset = ClientOffset();
            return new[] { (short)(lparam & 0xFFFF) + offset[0], (short)((lparam >> 16) & 0xFFFF) + offset[1] };
        }
    }
}

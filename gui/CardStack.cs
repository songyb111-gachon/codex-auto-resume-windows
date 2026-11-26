// Codex Auto Resume - the notification cards on screen together: shown, stacked, hovered, clicked and closed, and the
// window procedure that runs them (v0.6.27, S6.3d).
//
// ui/card/stack.py's CardStack and ui/card/win32.py's screen half (screen, look, focus_snapshot, taskbar_corner), ported
// call for call; one card is NoticeCard (gui/CardWindow.cs), whose windows it makes through ICardHost. It runs on the
// host's UI thread (P6-DESIGN 1.4). The notifier's inbox is the core's: each card arrives as a `notice` event (`Show`), in
// this shape -
//
//   {"id": <the notice's id>, "key": <its conversation key or null>, "title": <the window title>, "stays": <bool>,
//    "view": <notice_card.view(notice)>, "letters": <every character its words draw>}
//
// - and what the reference hands its callbacks is posted instead: a button (or the card's face) as `notice_action {uri}`,
// a notice ended as `notice_complete {id, shown}`, each on a worker thread as `_on_a_worker_thread` runs them.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace CodexAutoResume
{
    internal sealed class CardStack : ICardHost, IDisposable
    {
        internal const int WM_NOTICE = SurfaceNative.WM_APP + 7;
        internal const int TimerFrame = 1, TimerWait = 2, TimerFocus = 3;
        internal const int WM_MOUSEACTIVATE = 0x0021, MA_NOACTIVATE = 3, WM_RBUTTONUP = 0x0205;
        /// How long after a card is shown who has the keyboard is asked again (FOCUS_AFTER, issue #32).
        internal const double FocusAfter = 0.5;
        internal static readonly IntPtr HWND_MESSAGE = new IntPtr(-3);
        private const uint SPI_GETMESSAGEDURATION = 0x2016;

        private static int made;

        [DllImport("user32.dll", EntryPoint = "SystemParametersInfoW")]
        private static extern bool SystemParametersInfoDword(uint action, uint param, ref uint value, uint winIni);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetClassNameW(IntPtr hwnd, StringBuilder name, int count);
        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint process);
        [DllImport("user32.dll")]
        private static extern bool GetGUIThreadInfo(uint thread, ref GUITHREADINFO info);
        [DllImport("kernel32.dll")]
        private static extern IntPtr OpenProcess(uint access, bool inherit, uint process);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags, StringBuilder name, ref uint size);
        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);
        [DllImport("shell32.dll")]
        private static extern UIntPtr SHAppBarMessage(uint message, ref APPBARDATA data);
        [DllImport("user32.dll")]
        private static extern IntPtr MonitorFromPoint(SurfaceNative.POINT point, uint flags);

        [StructLayout(LayoutKind.Sequential)]
        private struct GUITHREADINFO
        {
            internal uint CbSize, Flags;
            internal IntPtr HwndActive, HwndFocus, HwndCapture, HwndMenuOwner, HwndMoveSize, HwndCaret;
            internal SurfaceNative.RECT RcCaret;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct APPBARDATA
        {
            internal uint CbSize;
            internal IntPtr HWnd;
            internal uint UCallbackMessage, UEdge;
            internal SurfaceNative.RECT Rc;
            internal IntPtr LParam;
        }

        // ------------------------------------------------------------------ what it is given
        internal Action<string> Log = unused => { };
        internal Func<int[]> Anchor = null;
        /// Where its posts go (the pump's), or null: then nothing is posted.
        internal IHostActions Actions = null;
        /// How a post runs off the UI thread (a pool thread on the live host; the probe queues it).
        internal Action<Action> Worker = work => ThreadPool.QueueUserWorkItem(unused => work());
        internal Func<double> Clock = () => TrayPlace.Monotonic() * 1000.0;
        internal Func<CardScreen> Locate;
        internal Func<Dictionary<string, object>> Appearance = Look;
        internal Func<Dictionary<string, object>> Focus = FocusSnapshot;
        /// Whether the cards' windows are made (false: offscreen, as the reference's tests and the render mode draw them).
        internal bool MakeWindows = true;

        // ------------------------------------------------------------------ its state
        private Dictionary<string, object> focusBefore;
        private IntPtr hwnd;
        private string className;
        private IntPtr instance;
        internal readonly List<NoticeCard> Cards = new List<NoticeCard>();
        private readonly Dictionary<IntPtr, NoticeCard> windows = new Dictionary<IntPtr, NoticeCard>();
        private readonly Dictionary<NoticeCard, Dictionary<string, object>> notices = new Dictionary<NoticeCard, Dictionary<string, object>>();
        private SurfaceNative.WndProc proc;
        internal bool FrameRunning;
        internal int? FrameMs;
        private bool hovered;

        internal sealed class CardScreen
        {
            internal int[] Anchor, Work, Monitor;
            internal double Dpi;
        }

        internal CardStack()
        {
            Locate = () => Screen(Anchor);
        }

        public string ClassName { get { return className; } }
        public IntPtr Instance { get { return instance; } }
        public Dictionary<IntPtr, NoticeCard> Windows { get { return windows; } }
        internal IntPtr Hwnd { get { return hwnd; } }

        // ------------------------------------------------------------------ lifecycle
        internal CardStack Create()
        {
            instance = SurfaceNative.GetModuleHandleW(null);
            proc = WindowProc;
            var klass = new SurfaceNative.WNDCLASSW
            {
                LpfnWndProc = proc, HInstance = instance,
                HCursor = SurfaceNative.LoadCursorW(IntPtr.Zero, new IntPtr(SurfaceNative.IDC_ARROW)),
            };
            className = "CodexAutoResumeCard-" + System.Diagnostics.Process.GetCurrentProcess().Id + "-" + Interlocked.Increment(ref made);
            klass.LpszClassName = className;
            if (SurfaceNative.RegisterClassW(ref klass) == 0)
            {
                className = null;
                throw new InvalidOperationException("RegisterClassW");
            }
            hwnd = SurfaceNative.CreateWindowExW(0, className, "", 0, 0, 0, 0, 0, HWND_MESSAGE, IntPtr.Zero, instance, IntPtr.Zero);
            if (hwnd == IntPtr.Zero)
            {
                Dispose();
                throw new InvalidOperationException("CreateWindowExW");
            }
            return this;
        }

        /// destroy: every card down; each notice not ended yet ends now - shown if it was seen (or had left by design).
        public void Dispose()
        {
            foreach (NoticeCard card in new List<NoticeCard>(Cards))
            {
                End(card, card.Seen || card.Superseded);
                Drop(card);
            }
            IntPtr window = hwnd;
            hwnd = IntPtr.Zero;
            if (window != IntPtr.Zero)
            {
                foreach (int timer in new[] { TimerFrame, TimerWait, TimerFocus }) SurfaceScreen.KillTimer(window, timer);
                SurfaceNative.DestroyWindow(window);
            }
            focusBefore = null;
            FrameRunning = false;
            FrameMs = null;
            if (className != null)
            {
                SurfaceNative.UnregisterClassW(className, instance);
                className = null;
            }
        }

        /// hold: HOLD_MS, or Windows' own "dismiss notifications after" time when that is longer.
        internal double Hold()
        {
            return Holding != null ? Holding() : CardPlan.HoldFor(MessageDurationMs());
        }

        /// The hold a probe gives the stack in place of Windows' setting (the reference's tests set `hold`), or null.
        internal Func<double> Holding = null;

        /// The id of the notice a card shows, as the `notice` event gave it.
        internal object IdOf(NoticeCard card)
        {
            Dictionary<string, object> notice;
            return notices.TryGetValue(card, out notice) ? SurfaceRender.Field(notice, "id") : null;
        }

        internal static object MessageDurationMs()
        {
            try
            {
                uint value = 0;
                if (!SystemParametersInfoDword(SPI_GETMESSAGEDURATION, 0, ref value, 0) || value == 0) return null;
                return (int)value * 1000;
            }
            catch (Exception)
            {
                return null;
            }
        }

        // ------------------------------------------------------------------ showing
        /// show: one notice on screen as the newest card; the card, or null if it failed (its notice then ended).
        internal NoticeCard Show(Dictionary<string, object> notice, CardScreen where = null, Dictionary<string, object> drawn = null)
        {
            Dictionary<string, object> before = FocusNow();
            NoticeCard card;
            try
            {
                where = where ?? Locate();
                drawn = drawn ?? Appearance();
                var view = (Dictionary<string, object>)notice["view"];
                card = new NoticeCard(this, view, PopupWords.Str(SurfaceRender.Field(notice, "title")),
                                      Equals(SurfaceRender.Field(notice, "stays"), true), Hold(), Clock(), where.Dpi, where.Work, drawn,
                                      MakeWindows, SurfaceRender.Field(notice, "letters") as string);
            }
            catch (Exception exc)
            {
                Log("notification card unavailable (" + TipCard.PythonName(exc) + ")");
                Complete(notice, false);
                return null;
            }
            notices[card] = notice;
            double now = Clock();
            card.Motion.Restart(now);
            try
            {
                Admit(card, now, where);
            }
            catch (Exception exc)
            {
                Log("notification card unavailable (" + TipCard.PythonName(exc) + ")");
                End(card, false);
                Drop(card);
                return null;
            }
            if (before != null && hwnd != IntPtr.Zero)
            {
                if (focusBefore == null) focusBefore = before;
                SurfaceScreen.SetTimer(hwnd, TimerFocus, (int)(FocusAfter * 1000));
            }
            Tick();
            return card;
        }

        private Dictionary<string, object> FocusNow()
        {
            try
            {
                return Focus();
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// focus_line: the one log line for who has the keyboard before a card and FOCUS_AFTER after, or null.
        internal static string FocusLine(Dictionary<string, object> before, Dictionary<string, object> after)
        {
            if (before == null || after == null || Json.Write(before) == Json.Write(after)) return null;
            Func<Dictionary<string, object>, string> said = found =>
                Said(SurfaceRender.Field(found, "front_class")) + " (" + Said(SurfaceRender.Field(found, "front_process")) + "), focus "
                + Said(SurfaceRender.Field(found, "focus_class"));
            return "notification card: the keyboard moved while it was shown: " + said(before) + " -> " + said(after);
        }

        private static string Said(object value) { return value == null ? "None" : PopupWords.Str(value); }

        private void FocusAfterNow(Dictionary<string, object> before)
        {
            string line = FocusLine(before, FocusNow());
            if (line != null) Log(line);
        }

        private string KeyOf(NoticeCard card)
        {
            Dictionary<string, object> notice;
            return notices.TryGetValue(card, out notice) ? SurfaceRender.Field(notice, "key") as string : null;
        }

        /// admit: a new card joins; what it replaces or pushes out leaves.
        internal void Admit(NoticeCard card, double now, CardScreen where)
        {
            string key = KeyOf(card);
            var living = Living();
            NoticeCard replaced = null;
            foreach (NoticeCard entry in living)
                if (!string.IsNullOrEmpty(key) && KeyOf(entry) == key)
                {
                    replaced = entry;
                    break;
                }
            double settle;
            if (replaced != null)
            {
                replaced.Motion.Retire(now, true);
                replaced.Superseded = true;
                Cards.Insert(Cards.IndexOf(replaced), card);
                card.Motion.Delay(CardPlan.SwapMs);
                settle = CardPlan.SwapMs;
            }
            else
            {
                Cards.Insert(0, card);
                settle = 0;
                if (living.Count > 0) card.Motion.Delay(CardPlan.StackDelayMs);
            }
            living = Living();
            for (int i = CardPlan.MaxCards; i < living.Count; i++)
            {
                living[i].Motion.Retire(now);
                living[i].PushedOut = true;
            }
            Restack(now, where, settle);
            if (hovered) card.Motion.Pause(now, true);
        }

        private List<NoticeCard> Living()
        {
            var living = new List<NoticeCard>();
            foreach (NoticeCard entry in Cards)
                if (entry.Motion.Phase != "exit" && entry.Motion.Phase != "gone") living.Add(entry);
            return living;
        }

        private void Restack(double now, CardScreen where, double delay = 0)
        {
            List<NoticeCard> living = Living();
            double scale = where.Dpi / 96.0;
            int gap = SurfaceMath.Round(PopupWindow.SpacingM * scale);
            int spacing = SurfaceMath.Round(PopupWindow.SpacingM * scale);
            var sizes = living.ConvertAll(card => card.Size);
            string edge;
            List<int[]> positions = CardPlan.StackPositions(sizes, where.Work, where.Monitor, where.Anchor, gap, spacing, out edge);
            for (int i = positions.Count; i < living.Count; i++)
            {
                living[i].Motion.Retire(now);
                living[i].PushedOut = true;
            }
            if (living.Count > positions.Count) living = living.GetRange(0, positions.Count);
            for (int i = 0; i < living.Count; i++)
            {
                if (living[i].Motion.Position == null) living[i].Edge = edge;
                living[i].Motion.MoveTo(now, positions[i], delay);
            }
            if (living.Count == 0 || positions.Count == 0) return;
            NoticeCard newest = living[0];
            int away = CardPlan.StackDirection(edge, positions[0][1], newest.Size[1], where.Work);
            int step = away * (newest.Size[1] + spacing);
            foreach (NoticeCard card in Cards)
                if (card.PushedOut && !card.MovedOut && card.Motion.Phase == "exit" && card.Motion.Position != null)
                {
                    int[] at = card.Motion.Position;
                    card.Motion.MoveTo(now, new[] { at[0], at[1] + step });
                    card.MovedOut = true;
                }
        }

        /// _complete: end one notice, off this thread - notice_complete {id, shown}.
        private void Complete(Dictionary<string, object> notice, bool shown)
        {
            IHostActions actions = Actions;
            if (actions == null) return;
            object id = SurfaceRender.Field(notice, "id");
            Worker(() => Quietly(() => actions.Post(HostActions.NoticeComplete,
                                                    new Dictionary<string, object> { { "id", id }, { "shown", shown } })));
        }

        private void End(NoticeCard card, bool shown)
        {
            if (card.Ended) return;
            card.Ended = true;
            Dictionary<string, object> notice;
            if (notices.TryGetValue(card, out notice)) Complete(notice, shown);
        }

        private void Quietly(Action callback)
        {
            try
            {
                callback();
            }
            catch (Exception exc)
            {
                Log("notification card callback failed (" + TipCard.PythonName(exc) + ")");
            }
        }

        private void Drop(NoticeCard card)
        {
            Cards.Remove(card);
            card.Dispose();
        }

        // ------------------------------------------------------------------ time
        internal void Tick()
        {
            double now = Clock();
            foreach (NoticeCard card in new List<NoticeCard>(Cards))
            {
                card.Motion.Frame(now);
                if (card.Motion.Gone)
                {
                    End(card, card.Seen || card.Superseded);
                    Drop(card);
                    notices.Remove(card);
                    continue;
                }
                try
                {
                    card.Present(now);
                }
                catch (Exception exc)
                {
                    Log("notification card frame failed (" + TipCard.PythonName(exc) + ")");
                    End(card, false);
                    Drop(card);
                    notices.Remove(card);
                    continue;
                }
                if (card.Seen) End(card, true);
            }
            SyncHover(now);
            Schedule(now);
        }

        private void SyncHover(double now)
        {
            bool any = false;
            foreach (NoticeCard card in Cards) any = any || card.Tracking;
            if (any != hovered)
            {
                hovered = any;
                foreach (NoticeCard card in Cards) card.Motion.Pause(now, any);
            }
        }

        private void Schedule(double now)
        {
            if (hwnd == IntPtr.Zero) return;
            var moved = Cards.ConvertAll(card => card.Motion.Moving(now));
            bool motion = moved.Contains(true);
            bool breathing = false;
            for (int i = 0; i < Cards.Count; i++)
            {
                bool breathes = !moved[i] && Cards[i].Breathe(now);
                breathing = breathing || breathes;
            }
            bool moving = motion || breathing;
            int interval = motion ? CardPlan.FrameMs : PopupWindowMotion.FrameMs;
            if (moving && (!FrameRunning || FrameMs != interval))
            {
                SurfaceScreen.SetTimer(hwnd, TimerFrame, interval);
                FrameRunning = true;
                FrameMs = interval;
            }
            else if (!moving && FrameRunning)
            {
                SurfaceScreen.KillTimer(hwnd, TimerFrame);
                FrameRunning = false;
                FrameMs = null;
            }
            SurfaceScreen.KillTimer(hwnd, TimerWait);
            if (!moving)
            {
                double? least = null;
                foreach (NoticeCard card in Cards)
                {
                    double? wait = card.Motion.WaitMs(now);
                    if (wait != null && (least == null || wait.Value < least.Value)) least = wait;
                }
                if (least != null) SurfaceScreen.SetTimer(hwnd, TimerWait, Math.Max(1, (int)least.Value + 1));
            }
        }

        // ------------------------------------------------------------------ the pointer
        private void Hover(NoticeCard card, object target)
        {
            if (!Equals(target, card.Hover))
            {
                card.Hover = target;
                card.Redraw();
            }
            SyncHover(Clock());
            Tick();
        }

        private void Click(NoticeCard card, object target, bool face = false)
        {
            double now = Clock();
            IHostActions actions = Actions;
            var aimed = target as SurfaceTarget;
            if (aimed != null)
            {
                int index = Convert.ToInt32(aimed.Key);
                var buttons = SurfaceRender.Field(card.Vm, "actions") as List<object> ?? new List<object>();
                if (0 <= index && index < buttons.Count && actions != null)
                {
                    object uri = SurfaceRender.Field((Dictionary<string, object>)buttons[index], "uri");
                    Worker(() => Quietly(() => actions.Post(HostActions.NoticeAction, new Dictionary<string, object> { { "uri", uri } })));
                }
            }
            else if (face && SurfaceMath.Truthy(SurfaceRender.Field(card.Vm, "click")) && actions != null)
            {
                object uri = card.Vm["click"];
                Worker(() => Quietly(() => actions.Post(HostActions.NoticeAction, new Dictionary<string, object> { { "uri", uri } })));
            }
            card.Seen = true;
            card.Motion.Retire(now);
            Tick();
        }

        // ------------------------------------------------------------------ messages
        /// The window procedure, for the probe to send a message to (as Windows would).
        internal IntPtr Message(IntPtr window, int message, long wParam, long lParam)
        {
            return WindowProc(window, (uint)message, new IntPtr(wParam), new IntPtr(lParam));
        }

        private IntPtr WindowProc(IntPtr window, uint message, IntPtr wParam, IntPtr lParam)
        {
            try
            {
                IntPtr? handled = Handle(window, (int)message, wParam.ToInt64(), lParam.ToInt64());
                if (handled != null) return handled.Value;
            }
            catch (Exception exc)
            {
                Log("notification card message failed (" + TipCard.PythonName(exc) + ")");
            }
            return SurfaceScreen.DefWindowProc(window, message, wParam, lParam);
        }

        private IntPtr? Handle(IntPtr window, int message, long wparam, long lparam)
        {
            IntPtr zero = IntPtr.Zero;
            if (window == hwnd && hwnd != IntPtr.Zero)
            {
                if (message == SurfaceNative.WM_TIMER)
                {
                    if (wparam == TimerFocus)
                    {
                        SurfaceScreen.KillTimer(window, TimerFocus);
                        Dictionary<string, object> before = focusBefore;
                        focusBefore = null;
                        if (before != null) FocusAfterNow(before);
                        return zero;
                    }
                    if (wparam == TimerWait) SurfaceScreen.KillTimer(window, TimerWait);
                    Tick();
                    return zero;
                }
                return null;
            }
            NoticeCard card;
            windows.TryGetValue(window, out card);
            if (card == null || card.Body == null || window != card.Body.Hwnd)
            {
                if (message == WM_MOUSEACTIVATE) return new IntPtr(MA_NOACTIVATE);
                return null;
            }
            if (message == WM_MOUSEACTIVATE) return new IntPtr(MA_NOACTIVATE);
            if (message == SurfaceNative.WM_MOUSEMOVE)
            {
                if (!card.Tracking) card.Tracking = SurfaceScreen.TrackMouseLeave(window);
                Hover(card, card.Hit(lparam));
                return zero;
            }
            if (message == SurfaceNative.WM_MOUSELEAVE)
            {
                card.Tracking = false;
                card.Pressed = null;
                Hover(card, null);
                return zero;
            }
            if (message == SurfaceNative.WM_LBUTTONDOWN)
            {
                card.Pressed = card.Hit(lparam);
                if (card.Pressed != null)
                {
                    card.Redraw();
                    Tick();
                }
                return zero;
            }
            if (message == SurfaceNative.WM_LBUTTONUP)
            {
                object target = card.Hit(lparam), pressed = card.Pressed;
                card.Pressed = null;
                if (target != null && Equals(target, pressed)) Click(card, target);
                else if (target == null && pressed == null) Click(card, null, true);
                else
                {
                    card.Redraw();
                    Tick();
                }
                return zero;
            }
            if (message == WM_RBUTTONUP)
            {
                Click(card, null);
                return zero;
            }
            return null;
        }

        // ------------------------------------------------------------------ the screen (ui/card/win32.py)
        private static string Plain(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            if (text.Length > 64) return "other";
            foreach (char ch in text)
                if (!(char.IsLetterOrDigit(ch) || ch == '_' || ch == '.' || ch == ':' || ch == '-')) return "other";
            return text;
        }

        /// focus_snapshot: the class and program file name of the window in front, and the class of the window with the
        /// focus in its thread - never a title, a text or a path. Each null where Windows does not say.
        internal static Dictionary<string, object> FocusSnapshot()
        {
            var found = new Dictionary<string, object> { { "front_class", null }, { "front_process", null }, { "focus_class", null } };
            try
            {
                Func<IntPtr, string> classOf = window =>
                {
                    var buffer = new StringBuilder(256);
                    return window != IntPtr.Zero && GetClassNameW(window, buffer, 256) != 0 ? Plain(buffer.ToString()) : null;
                };
                IntPtr front = SurfaceNative.GetForegroundWindow();
                if (front == IntPtr.Zero) return found;
                found["front_class"] = classOf(front);
                uint process;
                uint thread = GetWindowThreadProcessId(front, out process);
                var info = new GUITHREADINFO();
                info.CbSize = (uint)Marshal.SizeOf(info);
                if (thread != 0 && GetGUIThreadInfo(thread, ref info)) found["focus_class"] = classOf(info.HwndFocus);
                IntPtr handle = OpenProcess(0x1000, false, process);
                if (handle != IntPtr.Zero)
                {
                    try
                    {
                        var buffer = new StringBuilder(1024);
                        uint size = 1024;
                        if (QueryFullProcessImageNameW(handle, 0, buffer, ref size))
                            found["front_process"] = Plain(System.IO.Path.GetFileName(buffer.ToString()));
                    }
                    finally
                    {
                        CloseHandle(handle);
                    }
                }
            }
            catch (Exception)
            {
            }
            return found;
        }

        /// taskbar_corner: the primary taskbar's notification-area end as a thin rectangle, or null.
        internal static int[] TaskbarCorner()
        {
            try
            {
                var data = new APPBARDATA();
                data.CbSize = (uint)Marshal.SizeOf(data);
                if (SHAppBarMessage(5, ref data) == UIntPtr.Zero) return null;
                SurfaceNative.RECT rc = data.Rc;
                if (rc.Right <= rc.Left || rc.Bottom <= rc.Top) return null;
                if (data.UEdge == 0 || data.UEdge == 2) return new[] { rc.Left, rc.Bottom - 2, rc.Right, rc.Bottom - 1 };
                return new[] { rc.Right - 2, rc.Top, rc.Right - 1, rc.Bottom };
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// screen: the monitor a card goes on - the icon's, else the notification area's, else the primary.
        internal static CardScreen Screen(Func<int[]> anchor)
        {
            using (new SurfaceNative.PerMonitorDpi())
            {
                int[] icon = null;
                try
                {
                    icon = anchor != null ? anchor() : null;
                }
                catch (Exception)
                {
                    icon = null;
                }
                int[] corner = icon ?? TaskbarCorner();
                IntPtr monitor;
                if (corner != null)
                {
                    var probe = new SurfaceNative.RECT(corner[0], corner[1], corner[2], corner[3]);
                    monitor = SurfaceNative.MonitorFromRect(ref probe, SurfaceNative.MONITOR_DEFAULTTONEAREST);
                }
                else monitor = MonitorFromPoint(new SurfaceNative.POINT(), 1);
                var info = new SurfaceNative.MONITORINFO();
                info.CbSize = (uint)Marshal.SizeOf(info);
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
                return new CardScreen
                {
                    Anchor = corner, Dpi = dpi != 0 ? dpi : 96, Work = new[] { work.Left, work.Top, work.Right, work.Bottom },
                    Monitor = new[] { whole.Left, whole.Top, whole.Right, whole.Bottom },
                };
            }
        }

        /// look: theme, design, High Contrast, what may move (every stopper, battery saver too) and the text size.
        internal static Dictionary<string, object> Look()
        {
            bool contrast = SurfaceTheme.HighContrast();
            return new Dictionary<string, object>
            {
                { "theme", SurfaceTheme.EffectiveTheme(SurfaceTheme.ThemeSetting, SurfaceTheme.AppsUseLightTheme()) },
                { "design", SurfaceTheme.DesignSetting }, { "contrast", contrast },
                { "reduced", SurfaceTheme.ReducedMotion() || contrast || TrayPlace.BatterySaver() },
                { "text", SurfaceTheme.TextScale() },
            };
        }
    }
}
